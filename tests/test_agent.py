import json
import unittest
from pathlib import Path

from signalpost import orgnr
from signalpost.agent import build_profile, explain
from signalpost.http import Response
from signalpost.profile import diff
from signalpost.sources import brreg

FIX = Path(__file__).parent / "fixtures"
ORG = "812345672"  # synthetic, see fixtures/README.md


class FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.requests_made = 0

    def get(self, url, accept=None, **_):
        self.requests_made += 1
        status, body, ctype = self.routes.get(url, (404, b"", "application/json"))
        return Response(url, status, body, ctype, "2026-10-14T00:00:00Z")


def routes(enhet_overrides=None):
    enhet = json.loads((FIX / f"enhet_{ORG}.json").read_text())
    enhet.update(enhet_overrides or {})
    j = "application/json"
    return {
        brreg.enhet_url(ORG): (200, json.dumps(enhet).encode(), j),
        brreg.roller_url(ORG): (200, (FIX / f"roller_{ORG}.json").read_bytes(), j),
        brreg.regnskap_url(ORG): (200, (FIX / f"regnskap_{ORG}.json").read_bytes(), j),
        "https://www.testfirma.example": (200, (FIX / "homepage.html").read_bytes(), "text/html; charset=utf-8"),
    }


class OrgnrTests(unittest.TestCase):
    def test_checksum(self):
        self.assertTrue(orgnr.is_valid("923609016"))
        self.assertFalse(orgnr.is_valid("923609017"))
        self.assertFalse(orgnr.is_valid("12345678"))

    def test_normalize(self):
        self.assertEqual(orgnr.normalize("NO 923 609 016 MVA"), "923609016")


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(routes())
        self.p = build_profile(self.client, ORG)

    def test_core_facts_have_sources(self):
        self.assertEqual(self.p.status, "active")
        self.assertEqual(self.p.get("name"), "TESTFIRMA EKSEMPEL AS")
        for f in self.p.facts:
            self.assertTrue(f.source_url.startswith("https://"), f.key)
            self.assertTrue(f.retrieved_at, f.key)

    def test_resigned_roles_excluded(self):
        names = [f.value["name"] for f in self.p.facts if f.key.startswith("roles.")]
        self.assertIn("Kari Testesen", names)
        self.assertNotIn("Gammel Medlem", names)
        self.assertIn("REVISJON EKSEMPEL AS", names)

    def test_financials_only_from_own_filing(self):
        self.assertEqual(self.p.get("financials.2024.revenue")["amount"], 14000000)
        self.assertEqual(self.p.get("financials.2024.net_profit")["amount"], 624000)
        self.assertNotIn(1, [f.value["amount"] for f in self.p.facts if f.key.startswith("financials.")])

    def test_website_evidence(self):
        self.assertTrue(self.p.get("web.orgnr_on_homepage"))
        self.assertEqual(self.p.get("web.description"), "Vi lager programvare.")

    def test_request_budget_per_company(self):
        self.assertLessEqual(self.client.requests_made, 5)

    def test_update_detects_changes(self):
        newer = build_profile(FakeClient(routes({"antallAnsatte": 15})), ORG, previous=self.p)
        self.assertEqual([c.key for c in newer.changes], ["employees"])
        self.assertIn("changed since the previous run", newer.summary)

    def test_explanation_uses_facts(self):
        self.assertIn("TESTFIRMA EKSEMPEL AS", self.p.summary)
        self.assertIn("CEO: Kari Testesen", self.p.summary)
        self.assertIn("14 000 000 NOK", self.p.summary)


class EdgeCaseTests(unittest.TestCase):
    def test_invalid(self):
        p = build_profile(FakeClient({}), "123456789")
        self.assertEqual(p.status, "invalid")
        self.assertEqual(p.facts, [])

    def test_not_found(self):
        p = build_profile(FakeClient({}), ORG)
        self.assertEqual(p.status, "not_found")

    def test_deleted(self):
        p = build_profile(FakeClient({brreg.enhet_url(ORG): (410, b"", "application/json")}), ORG)
        self.assertEqual(p.status, "deleted")

    def test_wrong_company_guard(self):
        body = json.dumps({"organisasjonsnummer": "999999999", "navn": "OTHER"}).encode()
        p = build_profile(FakeClient({brreg.enhet_url(ORG): (200, body, "application/json")}), ORG)
        self.assertEqual(p.status, "error")
        self.assertIsNone(p.get("name"))


if __name__ == "__main__":
    unittest.main()
