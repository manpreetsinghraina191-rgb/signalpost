"""Company website enrichment.

We only visit the homepage the register itself lists for this orgnr, so the page is
tied to the company by the register. We record whether the page also states the
orgnr, which is stronger evidence, and we keep only plain descriptive facts.
"""

from __future__ import annotations

import html
import re

from ..http import Client
from ..profile import Fact, Profile

SOURCE = "Company website"


def normalize_url(site: str) -> str:
    site = site.strip()
    return site if re.match(r"https?://", site) else "https://" + site


def orgnr_pattern(orgnr: str) -> re.Pattern:
    a, b, c = orgnr[:3], orgnr[3:6], orgnr[6:]
    return re.compile(rf"(?<!\d){a}[\s .]?{b}[\s .]?{c}(?!\d)")


def _meta(page: str, name: str) -> str | None:
    m = re.search(
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']+)', page, re.I
    ) or re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:name|property)=["\']{re.escape(name)}["\']', page, re.I
    )
    return html.unescape(m.group(1)).strip() if m else None


def parse_homepage(p: Profile, page: str, url: str, fetched_at: str) -> None:
    orgnr_on_page = bool(orgnr_pattern(p.orgnr).search(page))
    evidence = (
        f"Homepage listed for {p.orgnr} in Enhetsregisteret"
        + ("; page also states the orgnr" if orgnr_on_page else "")
    )
    conf = "high" if orgnr_on_page else "medium"

    def add(key, value):
        p.add(Fact(key, value, SOURCE, url, fetched_at, None, evidence, url, conf))

    add("web.orgnr_on_homepage", orgnr_on_page)
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    add("web.title", html.unescape(re.sub(r"\s+", " ", title.group(1))).strip()[:200] if title else None)
    add("web.description", (_meta(page, "description") or _meta(page, "og:description") or "")[:500] or None)
    socials = sorted(set(re.findall(
        r'https?://(?:www\.)?(?:linkedin\.com/company|facebook\.com|instagram\.com|x\.com|twitter\.com)/[A-Za-z0-9_.\-/%]+',
        page)))
    add("web.social_links", socials[:6] or None)


def enrich(client: Client, p: Profile) -> None:
    site = p.get("website")
    if not site:
        return
    url = normalize_url(site)
    try:
        r = client.get(url, accept="text/html,application/xhtml+xml")
    except Exception as e:  # network errors on third-party sites are expected
        p.errors.append(f"website: {e}")
        return
    if r.status != 200 or "html" not in r.content_type.lower():
        p.errors.append(f"website: HTTP {r.status} {r.content_type}")
        return
    parse_homepage(p, r.text(), r.url, r.fetched_at)
    p.sources.append({"name": SOURCE, "url": r.url, "retrieved_at": r.fetched_at})
