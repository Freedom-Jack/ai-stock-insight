"""Replay the Stockwatch evidence through the ordinary Stock Insight desk."""

import json
import tempfile
import unittest
from base64 import b64encode
from contextlib import closing
from datetime import datetime
from http.client import HTTPConnection
from importlib.util import find_spec
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from unittest.mock import patch

from stockinsight import db, evidence, monitor, supplier, universe
from stockwatch import issuer, usgs
from stockwatch.replay import FIRST, FOLLOW_UP
from tests.test_insight_web import FormFields, served


LIST = (
    b"ticker,listing_exchange,security_type,currency\n"
    b"NVDA,NASDAQ,STK,USD\nAMD,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\n"
)
EXAMPLES = supplier.WATCHLIST.parent


def feed_at(stamp, features):
    return json.dumps({
        "type": "FeatureCollection", "features": features,
        "metadata": {"status": 200, "count": len(features),
                     "generated": int(datetime.fromisoformat(stamp).timestamp() * 1000)},
    }).encode()


class SupplierWatchTest(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / "research.sqlite3"
        self.conn = self.enterContext(closing(db.connect(self.path)))
        universe.import_snapshot(self.conn, LIST, complete=True)
        self.quake = (EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes()
        self.disclosure = (EXAMPLES / "issuer-twse-2024.json").read_bytes()

    def check(self, stamp):
        return supplier.tick(self.conn, clock=lambda: stamp)

    def request(self, path, data=None):
        headers = {"Authorization": "Basic " + b64encode(b"research:supplier-test").decode()}
        if data is not None:
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        with closing(HTTPConnection("127.0.0.1", self.port, timeout=5)) as client:
            client.request("GET" if data is None else "POST", path,
                           None if data is None else urlencode(data), headers)
            result = client.getresponse()
            return result.status, result.read().decode()

    def form(self, operation, **fields):
        status, html = self.request("/monitor")
        self.assertEqual(status, 200)
        return self.request(
            "/actions/monitor-" + operation,
            {**fields, "csrf": FormFields(html).values["csrf"]},
        )[0]

    @unittest.skipUnless(find_spec("fastapi") and find_spec("uvicorn"), "Install the locked web dependencies")
    def test_web_opt_in_shared_capture_and_review(self):
        from stockinsight.web import application

        self.port = self.enterContext(served(lambda port: application(self.path, port, "supplier-test")))
        self.assertIsNone(self.check(FIRST))
        self.assertEqual(self.form("supplier", enabled="1"), 303)

        def fetch_quake():
            self.assertFalse(self.conn.in_transaction)
            return self.quake

        with patch.object(usgs, "fetch_feed", side_effect=fetch_quake) as fetch:
            self.assertEqual(self.check(FIRST), "USGS")
            fetch.assert_called_once()
        wait = self.conn.execute("SELECT due_at FROM supplier_due WHERE source='USGS'").fetchone()[0]
        self.assertEqual(wait, db.instant("2024-04-03T00:20:00Z"))
        with patch.object(issuer, "fetch_bulletins", side_effect=OSError("simulated TWSE outage")):
            self.assertEqual(self.check(FIRST), "TSMC")
        self.assertIn("simulated TWSE outage", self.request("/monitor")[1])
        self.assertIsNone(self.check("2024-04-03T00:19:59Z"))

        with patch.object(usgs, "fetch_feed", return_value=feed_at(FOLLOW_UP, [])):
            self.assertEqual(self.check(FOLLOW_UP), "USGS")
        second = "2024-04-06T02:00:00Z"
        with patch.object(issuer, "fetch_bulletins", side_effect=lambda at: issuer.parse_bulletins(self.disclosure, at)):
            self.assertEqual(self.check(FOLLOW_UP), "TSMC")
            with patch.object(usgs, "fetch_feed", return_value=feed_at(second, [])):
                self.assertEqual(self.check(second), "USGS")
            self.assertEqual(self.check(second), "TSMC")
        rows = monitor.dashboard(self.conn, at=second)["events"]
        self.assertEqual({r["ticker"] for r in rows}, {"NVDA", "AMD"})
        self.assertEqual({r["kind"] for r in rows}, {supplier.QUAKE, supplier.DISCLOSURE})
        self.assertEqual(len(rows), 4)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM delivery_notices").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM inbox").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT due_at FROM supplier_due WHERE source='TSMC'").fetchone()[0],
                         db.instant("2024-04-06T03:00:00Z"))
        for row in rows:
            status, html = self.request("/events/" + row["version_id"])
            self.assertEqual(status, 200)
            self.assertIn("Original source", html)
        self.assertIn("Recent watchlist events", self.request("/today")[1])

        candidate = monitor.dashboard(self.conn, at=second)["supplier"]["review"][0]
        self.assertEqual(candidate["status"], "watch")
        response = self.form(
            "supplier-review", entry=candidate["sequence"], status="narrowed",
            locator="Production update, reviewed operating passage", uncertainty="Allocation remains unknown",
            next_check="Read the next earnings release",
        )
        self.assertEqual(response, 303)
        self.assertNotIn("TSMC disclosures to review", self.request("/monitor")[1])
        with closing(db.connect(self.path)) as reopened:
            recent = monitor.dashboard(reopened)["events"]
            self.assertEqual(sum(r["kind"] == supplier.ASSESSMENT for r in recent), 2)
            self.assertEqual(reopened.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_source_cooldown_and_quake_correction(self):
        supplier.set_enabled(self.conn, True)
        retry = HTTPError(usgs.FEED_URL, 429, "rate limited", {"Retry-After": "900"}, None)
        with patch.object(usgs, "fetch_feed", side_effect=retry):
            self.assertEqual(self.check(FIRST), "USGS")
        with patch.object(issuer, "fetch_bulletins", return_value=issuer.IssuerSnapshot("2024-04-03", [])):
            self.assertEqual(self.check(FIRST), "TSMC")
        self.assertIsNone(self.check("2024-04-03T00:29:59Z"))

        initial = "2024-04-03T00:30:00Z"
        features = json.loads(self.quake)["features"]
        with patch.object(usgs, "fetch_feed", return_value=feed_at(initial, features)):
            self.assertEqual(self.check(initial), "USGS")
        revised = "2024-04-03T00:35:00Z"
        features[0]["properties"]["status"] = "deleted"
        features[0]["properties"]["updated"] = int(datetime.fromisoformat(revised).timestamp() * 1000)
        with patch.object(usgs, "fetch_feed", return_value=feed_at(revised, features)):
            self.assertEqual(self.check(revised), "USGS")
        latest = monitor.dashboard(self.conn, at=revised)["events"]
        self.assertEqual([(r["kind"], r["state"]) for r in latest], [(supplier.QUAKE, "cancelled")] * 2)
        for row in latest:
            source = evidence.get(self.conn, row["instrument_id"], row["source_ref"])
            self.assertIn("withdrew this TSMC geographic watch", source["text"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM delivery_notices").fetchone()[0], 2)
