"""Profile builder: orgnr in, sourced and dated profile out."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import orgnr as orgnr_mod
from .http import BudgetExceeded, Client, utcnow_iso
from .profile import Profile, diff
from .sources import brreg, website


def _fetch_core(client: Client, p: Profile) -> bool:
    """Enhetsregisteret lookup. Falls back to underenheter. Returns False if nothing to enrich."""
    for kind, url in (("enheter", brreg.enhet_url(p.orgnr)), ("underenheter", brreg.underenhet_url(p.orgnr))):
        r = client.get(url)
        if r.status == 200:
            data = r.json()
            if data.get("organisasjonsnummer") != p.orgnr:  # identity guard
                p.status = "error"
                p.errors.append(f"{url} returned orgnr {data.get('organisasjonsnummer')}")
                return False
            brreg.parse_enhet(p, data, url, r.fetched_at, kind)
            p.sources.append({"name": brreg.ER, "url": url, "retrieved_at": r.fetched_at})
            p.status = "deleted" if data.get("slettedato") else "active"
            return kind == "enheter"
        if r.status == 410:  # removed for legal reasons / deleted
            p.status = "deleted"
            p.sources.append({"name": brreg.ER, "url": url, "retrieved_at": r.fetched_at})
            return False
        if r.status != 404:
            p.status = "error"
            p.errors.append(f"{url}: HTTP {r.status}")
            return False
    p.status = "not_found"
    return False


def build_profile(client: Client, raw_orgnr: str, previous: Profile | None = None, web: bool = True) -> Profile:
    orgnr = orgnr_mod.normalize(raw_orgnr)
    p = Profile(orgnr=orgnr, status="invalid", generated_at=utcnow_iso())
    if not orgnr_mod.is_valid(orgnr):
        p.errors.append("not a valid organisasjonsnummer (MOD11 check failed)")
        p.summary = explain(p)
        return p
    try:
        is_main = _fetch_core(client, p)
        if is_main:
            r = client.get(brreg.roller_url(orgnr))
            if r.status == 200:
                brreg.parse_roller(p, r.json(), r.url, r.fetched_at)
                p.sources.append({"name": brreg.ER + " – roller", "url": r.url, "retrieved_at": r.fetched_at})
            r = client.get(brreg.regnskap_url(orgnr))
            if r.status == 200:
                body = r.json()
                brreg.parse_regnskap(p, body if isinstance(body, list) else [body], r.url, r.fetched_at)
                p.sources.append({"name": brreg.RR, "url": r.url, "retrieved_at": r.fetched_at})
        if web and p.status == "active":
            website.enrich(client, p)
    except BudgetExceeded as e:
        p.errors.append(str(e))
    except Exception as e:
        p.errors.append(f"{type(e).__name__}: {e}")
        if p.status == "invalid":
            p.status = "error"
    p.changes = diff(previous, p) if previous else []
    p.summary = explain(p)
    return p


def _fmt_nok(v: dict) -> str:
    return f"{v['amount']:,.0f} {v['currency']}".replace(",", " ")


def explain(p: Profile) -> str:
    """Plain-language summary built only from facts in the profile."""
    if p.status == "invalid":
        return f"{p.orgnr} is not a valid Norwegian organisation number, so no lookup was made."
    if p.status == "not_found":
        return f"No unit with organisation number {p.orgnr} exists in Enhetsregisteret."
    if p.status == "error":
        return f"Lookup of {p.orgnr} failed: {'; '.join(p.errors) or 'unknown error'}."
    name = p.get("name") or p.orgnr
    if p.status == "deleted":
        d = p.get("deleted_date")
        return f"{name} ({p.orgnr}) is deleted from Enhetsregisteret{' as of ' + d if d else ''}."
    bits = [f"{name} ({p.orgnr}) is a {p.get('legal_form') or 'registered unit'}"]
    if muni := p.get("municipality"):
        bits[0] += f" based in {muni.split(' (')[0].title()}"
    if reg := p.get("registered_date"):
        bits[0] += f", registered {reg}"
    bits[0] += "."
    if nace := p.get("industry.nace1"):
        bits.append(f"Main industry: {nace}.")
    if (emp := p.get("employees")) is not None:
        bits.append(f"Registered employees: {emp}.")
    ceo = next((f.value["name"] for f in p.facts if f.key.startswith("roles.DAGL.")), None)
    chair = next((f.value["name"] for f in p.facts if f.key.startswith("roles.LEDE.")), None)
    if ceo or chair:
        bits.append(" ".join(filter(None, [f"CEO: {ceo}." if ceo else None, f"Chair: {chair}." if chair else None])))
    years = sorted({f.key.split(".")[1] for f in p.facts if f.key.startswith("financials.")}, reverse=True)
    if years:
        y = years[0]
        rev, net = p.get(f"financials.{y}.revenue"), p.get(f"financials.{y}.net_profit")
        parts = [f"revenue {_fmt_nok(rev)}" if rev else None, f"net result {_fmt_nok(net)}" if net else None]
        if any(parts):
            bits.append(f"Filed accounts for {y}: {', '.join(filter(None, parts))}.")
    if (d := p.get("status.distress")) and d != "none registered":
        bits.append(f"Warning: {d}.")
    if p.changes:
        bits.append(f"{len(p.changes)} field(s) changed since the previous run.")
    return " ".join(bits)


# -- batch -------------------------------------------------------------------

def load_previous(out_dir: Path, orgnr: str) -> Profile | None:
    path = out_dir / "profiles" / f"{orgnr}.json"
    if path.exists():
        try:
            return Profile.from_dict(json.loads(path.read_text()))
        except Exception:
            return None
    return None


def run_batch(orgnrs: list[str], out_dir: Path, max_requests: int = 1900, deadline_s: int = 40 * 60,
              workers: int = 8, web: bool = True, cache_ttl_s: int = 6 * 3600) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "profiles").mkdir(exist_ok=True)
    client = Client(max_requests=max_requests, cache_dir=out_dir / ".cache", cache_ttl_s=cache_ttl_s)
    start = time.monotonic()
    results: dict[str, str] = {}

    def work(o: str) -> Profile:
        norm = orgnr_mod.normalize(o)
        if time.monotonic() - start > deadline_s:
            p = Profile(norm, "error", utcnow_iso(), errors=["run deadline reached before lookup"])
            p.summary = explain(p)
            return p
        prev = load_previous(out_dir, norm)
        p = build_profile(client, norm, prev, web=web)
        if prev and prev.status == "active" and p.status == "error":
            # keep the last good profile rather than overwriting it with a failed lookup
            prev.errors = p.errors
            return prev
        return p

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(work, o): o for o in orgnrs}
        for fut in as_completed(futures):
            p = fut.result()
            (out_dir / "profiles" / f"{p.orgnr}.json").write_text(json.dumps(p.to_dict(), ensure_ascii=False, indent=2))
            results[p.orgnr] = p.status
    summary = {
        "companies": len(orgnrs),
        "by_status": {s: list(results.values()).count(s) for s in sorted(set(results.values()))},
        "outbound_requests": client.requests_made,
        "elapsed_s": round(time.monotonic() - start, 1),
        "external_api_cost_usd": 0.0,
        "finished_at": utcnow_iso(),
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))
    return summary
