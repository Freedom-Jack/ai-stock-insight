import json
from pathlib import Path
import unittest

from stockwatch import usgs


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "usgs-taiwan-2024.geojson"
RECEIVED = "2024-04-03T08:15:00+08:00"


class USGSFeedTests(unittest.TestCase):
    def setUp(self):
        self.payload = FIXTURE.read_bytes()
        self.doc = json.loads(self.payload)
        self.event = self.doc["features"][0]

    def parse(self):
        return usgs.parse_feed(json.dumps(self.doc).encode(), RECEIVED)

    def test_historical_origin_and_distinct_clocks(self):
        event, = self.parse()
        self.assertEqual(event.id, "usgs:us7000m9g4")
        self.assertEqual(event.kind, "earthquake")
        self.assertEqual(event.occurred_at, "2024-04-02T23:58:11.228000Z")
        self.assertEqual(event.revision, "2024-04-03T00:14:10.040000Z")
        self.assertEqual(usgs.generated_at(self.payload), "2024-04-03T00:14:16.677000Z")
        self.assertEqual(event.seen_at, "2024-04-03T00:15:00.000000Z")
        self.assertEqual(event.url, self.doc["provenance"]["product_url"])
        self.assertEqual(event.facts, {"latitude": 23.819, "longitude": 121.5616, "magnitude": 7.4})

    def test_rejects_future_knowledge_at_receipt(self):
        with self.assertRaisesRegex(ValueError, "generated after"):
            usgs.parse_feed(self.payload, "2024-04-03T00:14:00Z")
        self.event["properties"]["updated"] = self.doc["metadata"]["generated"] + 1
        with self.assertRaisesRegex(ValueError, "revision"):
            self.parse()

    def test_empty_feed_requires_valid_metadata(self):
        self.doc["features"] = []
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            self.parse()
        self.doc["metadata"]["count"] = 0
        self.assertEqual(self.parse(), [])

    def test_untrustworthy_numbers_or_urls_fail_the_batch(self):
        for coordinates in ([23.819, 121.5616, 35], [float("nan"), 0, 0], [True, 0, 0]):
            with self.subTest(coords=coordinates), self.assertRaises(ValueError):
                self.event["geometry"]["coordinates"] = coordinates
                self.parse()
        self.event["geometry"]["coordinates"] = [0, 0, 0]
        self.event["properties"]["url"] = "https://earthquake.usgs.gov@untrusted.example/source"
        with self.assertRaisesRegex(ValueError, "evidence URL"):
            self.parse()

    def test_distinguishes_withdrawal_and_other_event_types(self):
        self.event["properties"]["type"] = "quarry blast"
        self.assertEqual(self.parse(), [])
        self.event["properties"]["status"] = "deleted"
        withdrawn, = self.parse()
        self.assertEqual((withdrawn.id, withdrawn.kind), ("usgs:us7000m9g4", "withdrawn"))

    def test_malformed_or_oversized_response_fails(self):
        for bad in (b"<html>unavailable", b"[]", b"null", b" " * (usgs.MAX_BYTES + 1)):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                usgs.parse_feed(bad, RECEIVED)
