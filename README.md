# SignalPost

Give it a Norwegian organisasjonsnummer; it returns a company profile where every
fact carries its source URL, the date the source says it applies to, and the time
it was retrieved.

## Run

```bash
python -m signalpost run orgnrs.txt --out out      # batch: out/profiles/<orgnr>.json + out/run_summary.json
python -m signalpost profile 923609016             # one company to stdout
python -m signalpost seed --count 1200 > orgnrs.txt  # sample 1,200 active AS orgnrs from Enhetsregisteret
```

Python 3.10+, standard library only (no `pip install` needed). Tests: `python -m unittest discover -s tests`.

## Architecture

```
orgnr ──► validate (MOD11) ──► Enhetsregisteret /enheter (fallback /underenheter)
                                   │  identity anchor: response orgnr must equal input
                                   ├─► /enheter/{orgnr}/roller        (CEO, board, auditor…)
                                   ├─► Regnskapsregisteret /regnskap  (filed annual accounts)
                                   └─► homepage listed in the register (title, description,
                                        socials, "orgnr appears on page" evidence)
                            ──► Profile(facts[], summary, changes[], sources[], errors[])
                            ──► diff against previous run ──► out/profiles/<orgnr>.json
```

Design rules, mapped to the scoring:

| Criterion | How it is met |
|---|---|
| Coverage (35) | Identity, legal form, addresses, NACE codes, employees, registers (VAT, Foretaksregisteret…), purpose, distress status, current roles, up to 8 key figures per filed year, website metadata. |
| Correct match + evidence (30) | Every source is queried by the exact orgnr. Responses whose orgnr differs from the input are rejected. Accounts filed under another orgnr are dropped. Websites are only visited when the register lists them for that orgnr, and the profile records whether the page itself states the orgnr. Each fact has `source_url`, `human_url`, `as_of`, `retrieved_at`, `evidence`, `confidence`. |
| Updates (20) | Each run diffs against the stored profile and lists changed fields in `changes`. A failed lookup never overwrites the last good profile. HTTP cache TTL is 6 h (`--fresh` disables it). Resigned roles and deceased persons are excluded. |
| Explanations (10) | `summary` is a plain-language paragraph generated only from facts in the profile. |
| Ease of use (5) | One command, no dependencies, JSON output. |

**No fabricated financials.** Financial facts are copied verbatim from filed accounts
(`Regnskapsregisteret`), with currency and period. Nothing is estimated or derived.

## Limits and cost

| Limit | Budget | Usage per 100 companies |
|---|---|---|
| Outbound requests | 2,000 | ≤ 5 per company (≈ 400–500). Hard cap `--max-requests 1900`. |
| Time | 45 min | Hard deadline `--deadline-min 40`, 8 parallel workers. |
| External API cost | $10 | **$0.** All sources are free open data (NLOD licence). No LLM calls. |

## Model / API details

- Brønnøysundregistrene open APIs: `data.brreg.no/enhetsregisteret/api`, `data.brreg.no/regnskapsregisteret/regnskap` (free, no key, NLOD).
- Company homepages as listed in Enhetsregisteret.
- No LLM is used in the current version.
