"""Command line entry point.

  python -m signalpost profile 923609016            # one company, JSON to stdout
  python -m signalpost run orgnrs.txt --out out     # batch, writes out/profiles/*.json
  python -m signalpost seed --count 1200 > orgnrs.txt  # sample orgnrs from Enhetsregisteret
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import build_profile, run_batch
from .http import Client


def _read_orgnrs(path: str) -> list[str]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    seen, out = set(), []
    for line in text.splitlines():
        o = line.split(",")[0].strip()
        if o and not o.startswith("#") and o not in seen:
            seen.add(o)
            out.append(o)
    return out


def cmd_seed(count: int, form: str) -> None:
    client = Client(max_requests=count // 100 + 5)
    page, printed = 0, 0
    while printed < count:
        url = (f"https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform={form}"
               f"&konkurs=false&underAvvikling=false&size=100&page={page}")
        units = (client.get(url, use_cache=False).json().get("_embedded") or {}).get("enheter") or []
        if not units:
            break
        for u in units:
            print(u["organisasjonsnummer"])
            printed += 1
            if printed >= count:
                break
        page += 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="signalpost")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("profile", help="profile one organisasjonsnummer")
    a.add_argument("orgnr")
    a.add_argument("--no-web", action="store_true")
    b = sub.add_parser("run", help="profile every orgnr in a file (one per line, '-' for stdin)")
    b.add_argument("input")
    b.add_argument("--out", default="out")
    b.add_argument("--max-requests", type=int, default=1900)
    b.add_argument("--deadline-min", type=float, default=40)
    b.add_argument("--workers", type=int, default=8)
    b.add_argument("--no-web", action="store_true")
    b.add_argument("--fresh", action="store_true", help="ignore the HTTP cache")
    c = sub.add_parser("seed", help="print orgnrs sampled from Enhetsregisteret")
    c.add_argument("--count", type=int, default=1200)
    c.add_argument("--form", default="AS")
    args = ap.parse_args(argv)

    if args.cmd == "profile":
        p = build_profile(Client(), args.orgnr, web=not args.no_web)
        print(json.dumps(p.to_dict(), ensure_ascii=False, indent=2))
        return 0 if p.status in ("active", "deleted") else 1
    if args.cmd == "run":
        summary = run_batch(_read_orgnrs(args.input), Path(args.out), args.max_requests,
                            int(args.deadline_min * 60), args.workers, not args.no_web,
                            0 if args.fresh else 6 * 3600)
        print(json.dumps(summary, indent=2))
        return 0
    if args.cmd == "seed":
        cmd_seed(args.count, args.form)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
