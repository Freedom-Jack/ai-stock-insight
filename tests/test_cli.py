import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from stockwatch import __main__ as cli
from stockwatch.model import utc


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
FIRST_RECEIPT = utc("2024-04-03T00:15:00Z")
AFTER_ALERT = "2024-04-03T00:16:00Z"


class CLITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "local inbox.sqlite3"
        self.quake = (EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes()

    def call(self, command, *args, expected=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = cli.main([command, "--db", str(self.db), *map(str, args)])
        self.assertEqual(result, expected, stdout.getvalue() + stderr.getvalue())
        return stdout.getvalue() + stderr.getvalue()

    def poll(self, payload, when, expected=0):
        with patch.object(cli, "fetch_feed", return_value=payload), patch.object(cli, "now", return_value=utc(when)):
            return self.call("poll", expected=expected)

    def rows(self, query):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute(query).fetchall()

    def test_replay_restarts_and_historical_views_use_only_received_evidence(self):
        command = [sys.executable, "-m", "stockwatch", "demo", "--db", str(self.db)]
        for run in range(2):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("simulated", result.stdout.lower())
            if run:
                self.assertIn("0 observations and 0 inbox entries", result.stdout)
            self.assertEqual(self.rows("SELECT count(*) FROM observations"), [(4,)])
            self.assertEqual(self.rows("SELECT DISTINCT incident FROM inbox"), [("usgs:us7000m9g4",)])
            self.assertEqual(self.rows("SELECT status FROM inbox ORDER BY sequence"),
                             [("watch",), ("monitoring",), ("narrowed",), ("closed",)])

        before = self.call("inbox", "--as-of", "2024-04-03T00:14:59.999999Z")
        self.assertNotIn("usgs:us7000m9g4", before)
        early = self.call("inbox", "--as-of", AFTER_ALERT, "--watchlist-only")
        for term in ("WATCH", "NVDA", "AMD", "TSMC", "Hsinchu", "125 km", "regional", "USGS",
                     "uncertainty", "operations", "earthquake.usgs.gov", "www.sec.gov", "investor.tsmc.com"):
            with self.subTest(term=term):
                self.assertIn(term.lower(), early.lower())
        self.assertNotIn("a20240405.htm", early)
        self.assertNotIn("basis points", early)
        self.assertNotIn("$", early)
        narrowed = self.call("inbox", "--as-of", "2024-04-06T00:00:00Z")
        self.assertIn("NARROWED", narrowed)
        self.assertIn("a20240405.htm", narrowed)
        self.assertNotIn("a20240418.htm", narrowed)

    def test_private_views_are_read_only_and_bad_input_keeps_public_alert(self):
        self.call("demo", "--as-of", AFTER_ALERT, "--watchlist-only")
        with closing(sqlite3.connect(self.db)) as db:
            before = list(db.iterdump())
        snapshot = json.loads((EXAMPLES / "portfolio.json").read_bytes())
        snapshot["account_scope"] = "private-scope-canary"
        snapshot["total"] = "101111.11"
        snapshot["positions"][0]["value"] = "11111.11"
        private = self.db.parent / "private.json"
        private.write_text(json.dumps(snapshot), encoding="utf-8")
        display = self.call("inbox", "--as-of", AFTER_ALERT, "--portfolio", private)
        self.assertIn("$16,111.11", display)
        snapshot["total"] = "1.00"
        private.write_text(json.dumps(snapshot), encoding="utf-8")
        invalid = self.call("inbox", "--as-of", AFTER_ALERT, "--portfolio", private)
        self.assertIn("Watchlist only", invalid)
        self.assertIn("earthquake.usgs.gov", invalid)
        self.assertNotIn("$", invalid)
        with closing(sqlite3.connect(self.db)) as db:
            after = list(db.iterdump())
        self.assertEqual(before, after)
        for secret in ("private-scope-canary", "101111.11", "11111.11", "MSFT"):
            self.assertNotIn(secret, "\n".join(after))

    def test_live_and_demo_ledgers_cannot_be_mixed(self):
        self.call("demo", "--as-of", AFTER_ALERT)
        with patch.object(cli, "fetch_feed") as fetch:
            self.call("poll", expected=1)
            fetch.assert_not_called()
        self.assertEqual(self.rows("SELECT count(*) FROM observations"), [(1,)])
        self.db = self.db.parent / "live.sqlite3"
        self.poll(self.quake, FIRST_RECEIPT)
        self.call("demo", expected=1)
        self.assertEqual(self.rows("SELECT count(*) FROM observations"), [(1,)])

    def test_live_watch_accepts_an_official_reviewed_update_at_import_time(self):
        opened = self.poll(self.quake, FIRST_RECEIPT)
        self.assertIn("125 km", opened)
        self.assertIn("earthquake.usgs.gov", opened)
        filename = EXAMPLES / "operator-taiwan-2024.json"
        imported_at = utc("2024-04-19T14:00:00Z")
        with patch.object(cli, "now", return_value=imported_at):
            self.call("import-update", filename)
            self.call("import-update", filename)
        self.assertEqual(self.rows("SELECT count(*) FROM observations"), [(4,)])
        self.assertEqual(self.rows("SELECT DISTINCT seen_at FROM observations WHERE source='TSMC'"), [(imported_at,)])
        earlier = self.call("inbox", "--as-of", "2024-04-18T23:59:59Z")
        self.assertIn("usgs:us7000m9g4", earlier)
        self.assertNotIn("a20240418.htm", earlier)
        resolved = self.call("inbox", "--as-of", imported_at)
        self.assertIn("CLOSED", resolved)
        self.assertIn("a20240418.htm", resolved)
        self.assertIn("earthquake.usgs.gov", resolved)
        self.assertNotIn("$", resolved)

    def test_live_fetch_holds_writer_lock_to_preserve_receipt_order(self):
        def fetch_during_other_writer_attempt():
            with closing(sqlite3.connect(self.db, timeout=0)) as competing_writer:
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    competing_writer.execute("BEGIN IMMEDIATE")
            return self.quake

        with patch.object(cli, "fetch_feed", side_effect=fetch_during_other_writer_attempt):
            with patch.object(cli, "now", return_value=FIRST_RECEIPT):
                self.call("poll")
        self.assertEqual(self.rows("SELECT count(*) FROM inbox"), [(1,)])

    def test_stale_and_malformed_polls_preserve_last_success_then_recover(self):
        self.poll(self.quake, FIRST_RECEIPT)
        stale = self.poll(self.quake, "2024-04-03T00:45:00Z", expected=1)
        self.assertIn("15 minutes", stale)
        self.poll(b"<html>unavailable</html>", "2024-04-03T00:46:00Z", expected=1)
        with patch.object(cli, "now", return_value=utc("2024-04-03T00:47:00Z")):
            degraded = self.call("inbox")
        self.assertIn("degraded", degraded.lower())
        self.assertIn(FIRST_RECEIPT, degraded)
        self.assertEqual(self.rows("SELECT count(*) FROM observations"), [(1,)])

        fresh = utc("2024-04-03T00:50:00Z")
        doc = json.loads(self.quake)
        doc["features"] = []
        doc["metadata"].update(count=0, generated=int(datetime.fromisoformat(fresh).timestamp() * 1000))
        self.poll(json.dumps(doc).encode(), fresh)
        self.assertEqual(self.rows("SELECT last_ok, error FROM feed_health"), [(fresh, None)])
        with patch.object(cli, "now", return_value=fresh):
            healthy = self.call("inbox")
        self.assertNotIn("degraded", healthy.lower())
        self.assertEqual(self.rows("SELECT count(*) FROM inbox"), [(1,)])
        with patch.object(cli, "now", return_value=utc("2024-04-03T01:10:00Z")):
            self.assertIn("stale", self.call("inbox").lower())


if __name__ == "__main__":
    unittest.main()
