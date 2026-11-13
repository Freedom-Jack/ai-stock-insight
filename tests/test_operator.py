import json
from pathlib import Path
import unittest

from stockwatch.model import utc
from stockwatch.operator import parse_updates


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "operator-taiwan-2024.json"
RECEIPT = "2024-04-20T01:00:00+01:00"


class OperatorImportTest(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads(FIXTURE.read_bytes())

    def test_selected_filings_preserve_publication_vs_receipt(self):
        first, second, third = parse_updates(FIXTURE.read_bytes(), RECEIPT)
        self.assertEqual([s.facts["status"] for s in (first, second, third)],
                         ["monitoring", "narrowed", "closed"])
        self.assertEqual(first.occurred_at, utc("2024-04-04T04:00:00Z"))
        self.assertEqual(third.revision, utc("2024-04-18T11:26:54Z"))
        for item in (first, second, third):
            self.assertEqual(item.seen_at, utc(RECEIPT))
            self.assertEqual(item.facts["incident_id"], "usgs:us7000m9g4")
            self.assertEqual(item.kind, "operator_update")
        self.assertEqual(len({first.id, second.id, third.id}), 3)

    def test_retry_with_later_receipt_has_same_source_identity(self):
        earlier = parse_updates(FIXTURE.read_bytes(), RECEIPT)
        later = parse_updates(FIXTURE.read_bytes(), "2024-05-02T12:00:00Z")
        for original, retried in zip(earlier, later):
            self.assertEqual((original.id, original.revision), (retried.id, retried.revision))

    def test_future_evidence_rejects_the_whole_batch(self):
        with self.assertRaisesRegex(ValueError, "postdates"):
            parse_updates(FIXTURE.read_bytes(), self.rows[1]["published_at"])
        just_first = json.dumps(self.rows[:1]).encode()
        self.assertEqual(len(parse_updates(just_first, self.rows[0]["published_at"])), 1)

    def test_disclosure_link_must_be_specific_to_issuer(self):
        for url in (
            "http://pr.tsmc.com/english/example",
            "https://pr.tsmc.com.evil.example/news/123",
            "https://www.sec.gov@evil.example/Archives/edgar/data/1046179",
            "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda.htm",
            "https://www.sec.gov/Archives/edgar/data/1046179/../../other",
            "https://www.tsmc.com/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                row = dict(self.rows[0], url=url)
                parse_updates(json.dumps([row]).encode(), RECEIPT)

    def test_rejects_untrusted_clock_and_incomplete_review(self):
        for bad_input in (
            [], {}, [dict(self.rows[0], seen_at="2024-04-01T00:00:00Z")],
            [dict(self.rows[0], published_at="2024-04-05")],
            [dict(self.rows[0], locator="")], [dict(self.rows[0], status="confirmed_revenue_loss")],
            [dict(self.rows[0], title="untrusted\x1b[31mtext")],
            [dict(self.rows[0], incident_id="unrelated")],
        ):
            with self.subTest(value=bad_input), self.assertRaises(ValueError):
                parse_updates(json.dumps(bad_input).encode(), RECEIPT)
