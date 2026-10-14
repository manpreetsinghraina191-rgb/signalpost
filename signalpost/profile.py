"""Profile and Fact data model.

A Fact is the unit of evidence: one value, the exact source it came from, when the
source says it was true (`as_of`) and when we read it (`retrieved_at`). Nothing
enters a profile without a source URL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Fact:
    key: str                 # e.g. "name", "address.business", "financials.2024.revenue"
    value: Any
    source_name: str         # e.g. "Enhetsregisteret (Brønnøysundregistrene)"
    source_url: str          # machine-readable URL the value was read from
    retrieved_at: str        # when we fetched it (ISO-8601 UTC)
    as_of: str | None = None # date the source states the value applies to / was last changed
    evidence: str | None = None  # how we know it belongs to this orgnr
    human_url: str | None = None # human-readable page for the same record
    confidence: str = "high"     # high = official register keyed on orgnr; medium = orgnr confirmed on page


@dataclass
class Change:
    key: str
    old: Any
    new: Any
    detected_at: str


@dataclass
class Profile:
    orgnr: str
    status: str                       # active | deleted | not_found | invalid | error
    generated_at: str
    facts: list[Fact] = field(default_factory=list)
    summary: str = ""
    changes: list[Change] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, fact: Fact) -> None:
        if fact.value in (None, "", [], {}):
            return
        self.facts.append(fact)

    def get(self, key: str) -> Any:
        for f in self.facts:
            if f.key == key:
                return f.value
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            orgnr=d["orgnr"], status=d["status"], generated_at=d["generated_at"],
            facts=[Fact(**f) for f in d.get("facts", [])], summary=d.get("summary", ""),
            changes=[Change(**c) for c in d.get("changes", [])], sources=d.get("sources", []),
            errors=d.get("errors", []),
        )


def diff(old: Profile | None, new: Profile) -> list[Change]:
    """Fact-level changes between two runs (used for 'keep profiles current')."""
    if old is None:
        return []
    def as_map(p: Profile) -> dict[str, Any]:
        return {f.key: f.value for f in p.facts}
    o, n = as_map(old), as_map(new)
    changes = []
    for key in sorted(set(o) | set(n)):
        if o.get(key) != n.get(key):
            changes.append(Change(key, o.get(key), n.get(key), new.generated_at))
    return changes
