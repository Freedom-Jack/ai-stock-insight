"""Exercise the foreground scheduler, including real adapters and durable delivery."""

import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from stockwatch import followup
from stockwatch.config import EXAMPLES, load_config
from stockwatch.issuer import IssuerSnapshot, parse_bulletins
from stockwatch.model import utc
from stockwatch.monitor import coverage, cycle, run, scheduler_lock, setting
from stockwatch.replay import FIRST, FOLLOW_UP
from stockwatch.store import connect


class MonitorTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db_path = Path(folder.name) / "local.sqlite3"
        self.profile = load_config()
        self.quake = (EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes()
        self.issuer = (EXAMPLES / "issuer-twse-2024.json").read_bytes()

    def test_real_cli_configured_replay_restarts_and_early_cutoff(self):
        config = self.db_path.parent / "settings.json"
        root = EXAMPLES.parent

        def command(*args):
            result = subprocess.run([sys.executable, "-m", "stockwatch", *map(str, args)], cwd=root,
                                    capture_output=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return result.stdout

        command("configure", "--config", config, "--tickers", "NVDA")
        demo = ["demo", "--monitor", "--config", config, "--db", self.db_path]
        first = command(*demo)
        for text in ("WARNING", "COVERAGE RESTORED", "ISSUER FOLLOW-UP", "mopsov.twse.com.tw",
                     "$10,000.00 of $100,000.00", "10.00%"):
            self.assertIn(text, first)
        self.assertNotIn("AMD / NVDA", first)
        self.assertIn("0 linked alerts", command(*demo))
        early = command("inbox", "--db", self.db_path, "--config", config, "--as-of", FIRST)
        self.assertIn("NVDA", early)
        self.assertNotIn("mopsov.twse.com.tw", early)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM inbox").fetchone(), (2,))
        rendered = Path(str(self.db_path) + ".alerts.html").read_text(encoding="utf-8")
        self.assertIn("mopsov.twse.com.tw", rendered)
        self.assertNotIn("$10,000", rendered)

    def test_recurring_loop_recovers_and_skips_issuer_until_due(self):
        seconds = 0
        quakes, bulletins, pauses = [], [], []

        def clock():
            return utc((datetime.fromisoformat(FIRST) + timedelta(seconds=seconds)).isoformat())

        def wait(delay):
            nonlocal seconds
            pauses.append(delay)
            if len(pauses) == 3:
                raise KeyboardInterrupt
            seconds += delay

        def quake():
            quakes.append(clock())
            return self.quake

        def issuer(stamp):
            bulletins.append(stamp)
            if len(bulletins) == 1:
                raise OSError("temporary TWSE outage")
            return IssuerSnapshot("2024-04-03", [])

        with redirect_stdout(io.StringIO()) as screen:
            run(self.db_path, self.profile, clock=clock, wait=wait, monotonic=lambda: seconds,
                quake_fetch=quake, issuer_fetch=issuer, interval=60)
        self.assertEqual(len(quakes), 3)
        self.assertEqual(len(bulletins), 2)
        self.assertEqual(pauses, [60, 60, 60])
        self.assertEqual(screen.getvalue().count("LOCAL ALERT"), 1)
        self.assertIn("COVERAGE RESTORED", screen.getvalue())
        with closing(connect(self.db_path, "live")) as db:
            self.assertEqual(setting(db, "monitor")["state"], "stopped")
            self.assertEqual(setting(db, "terminal_sequence"), 1)
            self.assertTrue(any("stopped" in w.lower() for w in coverage(db, clock())[2]))
        with redirect_stdout(io.StringIO()) as restart:
            self.assertEqual(run(self.db_path, self.profile, clock=clock, once=True, quake_fetch=quake,
                                 issuer_fetch=issuer, interval=60), 0)
        self.assertNotIn("LOCAL ALERT", restart.getvalue())

    def test_throttled_source_respects_retry_after_while_issuer_collects(self):
        calls = []

        def throttled():
            calls.append(1)
            raise HTTPError("https://earthquake.usgs.gov", 429, "Slow down", {"Retry-After": "600"}, None)

        with closing(connect(self.db_path, "live")) as db, redirect_stdout(io.StringIO()):
            for stamp in (FIRST, utc("2024-04-03T00:16:00Z")):
                result = cycle(db, self.profile, clock=lambda: stamp, quake_fetch=throttled,
                               issuer_fetch=lambda _: IssuerSnapshot("2024-04-03", []))
                self.assertIn("TSMC", result)
            self.assertEqual(calls, [1])
            self.assertIn("429", db.execute("SELECT error FROM feed_health WHERE source='USGS'").fetchone()[0])

    def test_crash_after_capture_does_not_commit_or_lose_the_document(self):
        fetch = lambda seen: parse_bulletins(self.issuer, seen)
        with closing(connect(self.db_path, "live")) as db:
            with patch.object(followup, "_review", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    followup.poll_issuer(db, clock=lambda: FOLLOW_UP, fetch=fetch)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT count(*) FROM issuer_documents").fetchone()[0], 0)
            self.assertEqual(followup.poll_issuer(db, clock=lambda: FOLLOW_UP, fetch=fetch), (1, 0))

    def test_only_one_scheduler_owns_a_ledger_and_lock_is_reusable(self):
        with scheduler_lock(self.db_path):
            with self.assertRaisesRegex(ValueError, "already running"):
                with scheduler_lock(self.db_path):
                    self.fail("a second scheduler acquired the lock")
        with scheduler_lock(self.db_path):
            pass

    def test_locked_html_file_does_not_interrupt_ingestion_or_terminal_alerts(self):
        feeds = dict(clock=lambda: FIRST, quake_fetch=lambda: self.quake,
                     issuer_fetch=lambda _: IssuerSnapshot("2024-04-03", []), once=True)
        with redirect_stdout(io.StringIO()) as output:
            with patch("stockwatch.localview.write_view", side_effect=PermissionError("file locked")):
                self.assertEqual(run(self.db_path, self.profile, **feeds), 1)
        self.assertIn("LOCAL ALERT", output.getvalue())
        self.assertIn("Could not update", output.getvalue())
        with closing(connect(self.db_path, "live")) as db:
            self.assertTrue(any("HTML inbox" in w for w in coverage(db, FIRST)[2]))
        with redirect_stdout(io.StringIO()) as restored:
            self.assertEqual(run(self.db_path, self.profile, **feeds), 0)
        self.assertIn("HTML inbox restored", restored.getvalue())
        self.assertNotIn("LOCAL ALERT", restored.getvalue())
