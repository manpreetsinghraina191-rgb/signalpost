"""Brønnøysundregistrene open data (NLOD licence), keyed on organisasjonsnummer.

These are the authoritative sources: every value is looked up by the exact orgnr,
so identity is guaranteed by the register itself.

  Enhetsregisteret  https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}
  Underenheter      https://data.brreg.no/enhetsregisteret/api/underenheter/{orgnr}
  Roller            https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}/roller
  Regnskapsregisteret https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}
"""

from __future__ import annotations

from ..profile import Fact, Profile

API = "https://data.brreg.no"
ER = "Enhetsregisteret (Brønnøysundregistrene)"
RR = "Regnskapsregisteret (Brønnøysundregistrene)"
EVIDENCE = "Looked up by organisasjonsnummer in the official register"


def enhet_url(orgnr: str) -> str:
    return f"{API}/enhetsregisteret/api/enheter/{orgnr}"


def underenhet_url(orgnr: str) -> str:
    return f"{API}/enhetsregisteret/api/underenheter/{orgnr}"


def roller_url(orgnr: str) -> str:
    return f"{API}/enhetsregisteret/api/enheter/{orgnr}/roller"


def regnskap_url(orgnr: str) -> str:
    return f"{API}/regnskapsregisteret/regnskap/{orgnr}"


def human_url(orgnr: str, kind: str = "enheter") -> str:
    return f"https://virksomhet.brreg.no/nb/oppslag/{kind}/{orgnr}"


def _addr(a: dict | None) -> str | None:
    if not a:
        return None
    parts = [", ".join(a.get("adresse") or []), " ".join(filter(None, [a.get("postnummer"), a.get("poststed")]))]
    if a.get("landkode") and a.get("landkode") != "NO":
        parts.append(a.get("land") or a["landkode"])
    return ", ".join(p for p in parts if p) or None


def parse_enhet(p: Profile, d: dict, url: str, fetched_at: str, kind: str = "enheter") -> None:
    orgnr = d["organisasjonsnummer"]
    h = human_url(orgnr, kind)

    def add(key, value, as_of=None):
        p.add(Fact(key, value, ER, url, fetched_at, as_of, EVIDENCE, h))

    reg_date = d.get("registreringsdatoEnhetsregisteret")
    add("entity_type", "underenhet" if kind == "underenheter" else "hovedenhet")
    add("name", d.get("navn"))
    if of := d.get("organisasjonsform"):
        add("legal_form", f"{of.get('beskrivelse')} ({of.get('kode')})")
    add("registered_date", reg_date)
    add("founded_date", d.get("stiftelsesdato"))
    add("address.business", _addr(d.get("forretningsadresse")))
    add("address.postal", _addr(d.get("postadresse")))
    add("address.location", _addr(d.get("beliggenhetsadresse")))
    if fa := d.get("forretningsadresse") or d.get("beliggenhetsadresse"):
        add("municipality", f"{fa.get('kommune')} ({fa.get('kommunenummer')})" if fa.get("kommune") else None)
    for i in (1, 2, 3):
        if nk := d.get(f"naeringskode{i}"):
            add(f"industry.nace{i}", f"{nk.get('kode')} {nk.get('beskrivelse')}")
    if d.get("harRegistrertAntallAnsatte") or d.get("antallAnsatte"):
        add("employees", d.get("antallAnsatte"), d.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
    add("website", d.get("hjemmeside"))
    add("email", d.get("epostadresse"))
    add("phone", d.get("telefon"))
    add("mobile", d.get("mobil"))
    add("purpose", " ".join(d.get("vedtektsfestetFormaal") or []) or None, d.get("vedtektsdato"))
    add("activity", " ".join(d.get("aktivitet") or []) or None)
    add("parent_orgnr", d.get("overordnetEnhet"))
    if sek := d.get("institusjonellSektorkode"):
        add("sector", f"{sek.get('kode')} {sek.get('beskrivelse')}")
    for flag, key in [
        ("registrertIMvaregisteret", "registers.vat"),
        ("registrertIForetaksregisteret", "registers.foretaksregisteret"),
        ("registrertIStiftelsesregisteret", "registers.stiftelsesregisteret"),
        ("registrertIFrivillighetsregisteret", "registers.frivillighetsregisteret"),
    ]:
        if flag in d:
            add(key, bool(d[flag]))
    add("last_annual_accounts_year", d.get("sisteInnsendteAarsregnskap"))
    distress = []
    if d.get("konkurs"):
        distress.append(f"bankrupt{' since ' + d['konkursdato'] if d.get('konkursdato') else ''}")
    if d.get("underAvvikling"):
        distress.append(f"under liquidation{' since ' + d['underAvviklingDato'] if d.get('underAvviklingDato') else ''}")
    if d.get("underTvangsavviklingEllerTvangsopplosning"):
        distress.append("under compulsory liquidation/dissolution")
    add("status.distress", "; ".join(distress) or "none registered")
    add("deleted_date", d.get("slettedato"))


ROLE_LABELS = {
    "DAGL": "CEO", "LEDE": "Chair", "NEST": "Deputy chair", "MEDL": "Board member",
    "VARA": "Deputy board member", "REVI": "Auditor", "REGN": "Accountant",
    "KONT": "Contact person", "INNH": "Owner", "DTSO": "Partner (joint liability)",
    "DTPR": "Partner (pro rata liability)", "KOMP": "General partner",
}


def parse_roller(p: Profile, d: dict, url: str, fetched_at: str) -> None:
    orgnr = p.orgnr
    people = []
    for group in d.get("rollegrupper", []):
        as_of = group.get("sistEndret")
        for r in group.get("roller", []):
            if r.get("fratraadt"):
                continue
            code = (r.get("type") or {}).get("kode")
            label = ROLE_LABELS.get(code, (r.get("type") or {}).get("beskrivelse"))
            if person := r.get("person"):
                if person.get("erDoed"):
                    continue
                n = person.get("navn") or {}
                name = " ".join(filter(None, [n.get("fornavn"), n.get("mellomnavn"), n.get("etternavn")]))
                holder = {"name": name}
            elif enhet := r.get("enhet"):
                holder = {"name": " ".join(enhet.get("navn") or []), "orgnr": enhet.get("organisasjonsnummer")}
            else:
                continue
            people.append((code, label, holder, as_of))
    for i, (code, label, holder, as_of) in enumerate(people):
        p.add(Fact(f"roles.{code}.{i}", {"role": label, **holder}, ER, url, fetched_at, as_of, EVIDENCE, human_url(orgnr)))


def _num(x):
    return x if isinstance(x, (int, float)) else None


def parse_regnskap(p: Profile, items: list[dict], url: str, fetched_at: str) -> None:
    """Only values that appear literally in the filed accounts. Never derived or estimated."""
    # Prefer company (not consolidated) accounts, newest period first.
    items = sorted(items, key=lambda x: ((x.get("regnskapsperiode") or {}).get("tilDato") or ""), reverse=True)
    seen_years = set()
    for it in items:
        if (it.get("virksomhet") or {}).get("organisasjonsnummer") not in (None, p.orgnr):
            continue  # identity guard: never attach someone else's accounts
        period = it.get("regnskapsperiode") or {}
        year = (period.get("tilDato") or "")[:4]
        rtype = it.get("regnskapstype") or "SELSKAP"
        if not year or (year, rtype) in seen_years or rtype != "SELSKAP":
            continue
        seen_years.add((year, rtype))
        res = it.get("resultatregnskapResultat") or {}
        drift = res.get("driftsresultat") or {}
        ek = it.get("egenkapitalGjeld") or {}
        values = {
            "revenue": (drift.get("driftsinntekter") or {}).get("sumDriftsinntekter"),
            "operating_expenses": (drift.get("driftskostnad") or {}).get("sumDriftskostnad"),
            "operating_profit": drift.get("driftsresultat"),
            "profit_before_tax": res.get("ordinaertResultatFoerSkattekostnad"),
            "net_profit": res.get("aarsresultat"),
            "total_assets": (it.get("eiendeler") or {}).get("sumEiendeler"),
            "equity": (ek.get("egenkapital") or {}).get("sumEgenkapital"),
            "total_debt": (ek.get("gjeldOversikt") or {}).get("sumGjeld"),
        }
        currency = it.get("valuta") or "NOK"
        as_of = period.get("tilDato")
        for k, v in values.items():
            if _num(v) is None:
                continue
            p.add(Fact(
                f"financials.{year}.{k}", {"amount": v, "currency": currency,
                                           "period": f"{period.get('fraDato')}..{period.get('tilDato')}"},
                RR, url, fetched_at, as_of,
                f"Filed annual accounts for orgnr {p.orgnr}, period ending {as_of}",
                human_url(p.orgnr),
            ))
