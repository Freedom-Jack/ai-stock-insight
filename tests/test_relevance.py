import json
import tempfile
import unittest
from pathlib import Path

from stockwatch.relevance import load_watchlist, portfolio_context


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
AS_OF = "2024-04-03T00:20:00Z"
HUALIEN = {"latitude": 23.819, "longitude": 121.5616, "magnitude": 7.4}


class RelevanceTests(unittest.TestCase):
    def setUp(self):
        self.watchlist = load_watchlist(EXAMPLES / "watchlist.json")

    def test_shared_supplier_with_locatable_evidence_for_both_issuers(self):
        matches = self.watchlist.match(HUALIEN, AS_OF)
        self.assertEqual({match["ticker"] for match in matches}, {"AMD", "NVDA"})
        for match in matches:
            self.assertEqual(match["supplier"], "TSMC")
            self.assertIn("TSMC", match["scope"])
            self.assertIn("regional proxy", match["site"])
            self.assertIn("https://", match["source_url"])
            self.assertIn("https://", match["site_url"])
            self.assertIn("station", match["coordinate_basis"])
            self.assertEqual(match["distance_km"], 125)

    def test_threshold_filters_and_boundaries(self):
        self.assertEqual(self.watchlist.match(dict(HUALIEN, longitude=-122), AS_OF), [])
        self.assertEqual(self.watchlist.match(dict(HUALIEN, magnitude=5.99), AS_OF), [])
        self.assertEqual(len(self.watchlist.match(dict(HUALIEN, magnitude=6), AS_OF)), 2)
        on_reference = {"magnitude": 6, "latitude": 24.8279, "longitude": 121.014}
        self.assertEqual(self.watchlist.match(on_reference, AS_OF)[0]["distance_km"], 0)

    def test_point_in_time_links_and_coverage(self):
        for cutoff in ("2024-02-28T00:00:00Z", "2024-05-01T00:00:00Z", "2027-02-01T00:00:00Z"):
            self.assertEqual(self.watchlist.match(HUALIEN, cutoff), [])
            self.assertIn("unavailable", self.watchlist.coverage(cutoff))
        latest = self.watchlist.match(HUALIEN, "2026-11-05T15:00:00Z")
        self.assertEqual({m["filed_on"] for m in latest}, {"2026-11-04", "2026-02-25"})
        self.assertIn("AMD, NVDA", self.watchlist.coverage("2026-11-05T15:00:00Z"))
        self.assertEqual(self.watchlist.match(HUALIEN, "2026-11-05T01:00:00+02:00"), [])

    def test_bad_geography_and_unsafe_revision_windows(self):
        for bad in ({"magnitude": True}, {"longitude": float("nan")}, {"latitude": 91}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.watchlist.match(dict(HUALIEN, **bad), AS_OF)
        doc = json.loads((EXAMPLES / "watchlist.json").read_text(encoding="utf-8"))
        first, second = doc["sites"][0]["editions"]
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "watchlist.json"
            for key, value in (
                ("review_by", "2025-08-01"),
                ("checked_on", "2024-01-30"),
                ("review_by", first["checked_on"]),
            ):
                original = first[key]
                first[key] = value
                candidate.write_text(json.dumps(doc), encoding="utf-8")
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_watchlist(candidate)
                first[key] = original
            second.update(first)
            candidate.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "disjoint"):
                load_watchlist(candidate)

    def test_fingerprint_is_stable_and_limits_match_live_playbook(self):
        doc = json.loads((EXAMPLES / "watchlist.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "watchlist.json"
            candidate.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
            self.assertEqual(load_watchlist(candidate).fingerprint, self.watchlist.fingerprint)
            doc["min_magnitude"] = 6.5
            candidate.write_text(json.dumps(doc), encoding="utf-8")
            self.assertNotEqual(load_watchlist(candidate).fingerprint, self.watchlist.fingerprint)
            doc["min_magnitude"] = 4
            candidate.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "4.5"):
                load_watchlist(candidate)
            doc["min_magnitude"] = 6.5
            doc["sites"][0]["supplier"] = "UNSUPPORTED"
            candidate.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TSMC"):
                load_watchlist(candidate)


class PortfolioTests(unittest.TestCase):
    def test_duplicate_paths_are_counted_once_and_largest_position_first(self):
        result = portfolio_context(EXAMPLES / "portfolio.json", ["AMD", "AMD", "NVDA"], AS_OF)
        self.assertIn("Hypothetical USD", result)
        self.assertIn("$15,000.00 of $100,000.00 (15.00%)", result)
        self.assertIn("NVDA $10,000.00, AMD $5,000.00", result)

    def test_no_overlapping_holdings(self):
        result = portfolio_context(EXAMPLES / "portfolio.json", ["TSM"], AS_OF)
        self.assertIn("$0.00 of $100,000.00 (0.00%)", result)

    def test_abstain_on_future_or_stale_valuation(self):
        for cutoff in ("2024-04-02T19:59:59.999999Z", "2024-04-02T20:01:00Z", "2024-04-09T20:00:00.000001Z"):
            message = portfolio_context(EXAMPLES / "portfolio.json", ["NVDA"], cutoff)
            self.assertIn("Watchlist only", message)
            self.assertNotIn("$", message)
        boundary = portfolio_context(EXAMPLES / "portfolio.json", ["NVDA"], "2024-04-09T20:00:00Z")
        self.assertIn("(10.00%)", boundary)

    def test_private_position_fields_cannot_be_mixed_into_public_evidence(self):
        doc = json.loads((EXAMPLES / "watchlist.json").read_text(encoding="utf-8"))
        doc["sites"][0]["editions"][0]["relationships"][0]["shares"] = 1000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "public evidence fields"):
                load_watchlist(path)

    def test_portfolio_rejects_unreconciled_or_unsupported_amounts_and_assets(self):
        snapshot = json.loads((EXAMPLES / "portfolio.json").read_text(encoding="utf-8"))
        duplicate = snapshot["positions"] + [snapshot["positions"][0]]
        unsupported = [{"ticker": "SPY", "type": "fund", "value": "40000.00"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "positions.json"
            for update in ({"cash": "59999.99"}, {"cash": "-10"}, {"currency": "NTD"},
                           {"cash": "NaN"}, {"positions": duplicate}, {"positions": unsupported}):
                path.write_text(json.dumps(dict(snapshot, **update)), encoding="utf-8")
                with self.subTest(update=update), self.assertRaises(ValueError):
                    portfolio_context(path, ["AMD"], AS_OF)


if __name__ == "__main__":
    unittest.main()
