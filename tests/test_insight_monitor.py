"""Foreground source monitoring, outage accounting, and listing-specific event planning."""

import hashlib
import json
import os
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from stockinsight import db, events, evidence, issuer_news, monitor, providers, universe
from tests.test_insight_evidence import SAMPLE, sec_packet, workspace

START = "2026-01-01T12:00:00Z"


class ForegroundMonitorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "trial.sqlite"
        self.db, self.items = workspace(path=self.path)
        self.addCleanup(self.db.close)
        self.nvda = self.items["NVDA"]["id"]
        self.msft = self.items["MSFT"]["id"]

    def test_current_feed_uses_only_metadata_revises_editions_and_never_infers_future_events(
        self,
    ):
        article = "https://nvidianews.nvidia.com/news/issuer-example"

        def rss(title):
            item = f"<item><title>{title}</title><link>{article}</link><pubDate>Wed, 3 Sep 2025 08:30:00 -0400</pubDate><description>PRIVATE UNUSED BODY</description></item>"
            external = item.replace(article, "https://somewhere.example/news/x")
            return f"<rss><channel><title>Press Release - NVIDIA Newsroom</title>{item}{item}{external}</channel></rss>".encode()

        first, second = (
            rss("NVIDIA announces a future conference"),
            rss("NVIDIA updates conference announcement"),
        )
        with self.assertRaises(ValueError):
            monitor.configure(self.db, self.msft, "issuer_news", 60, True, at=START)
        monitor.configure(self.db, self.nvda, "issuer_news", 60, True, at=START)
        renewed = monitor._stamp(START, timedelta(hours=2))
        with patch.object(providers, "_fetch", side_effect=[first, second]) as wire:
            with patch.object(evidence, "now", return_value=START):
                self.assertEqual(monitor.tick(self.db, at=START), "completed")
                self.assertTrue(
                    evidence.capture_public(self.db, self.items["NVDA"], "issuer_news")[
                        "cached"
                    ]
                )
            initial = monitor.dashboard(self.db, at=START)
            self.assertEqual(initial["upcoming"], [])
            self.assertEqual(len(initial["events"]), 1)
            event = initial["events"][0]
            self.assertEqual(
                (event["source_url"], event["occurred_at"]),
                (article, db.instant("2025-09-03T12:30:00Z")),
            )
            self.assertEqual(event["version_hash"], hashlib.sha256(first).hexdigest())
            self.assertEqual(event["precision"], "instant")
            self.assertEqual(event["title"], "NVIDIA announces a future conference")
            with patch.object(evidence, "now", return_value=renewed):
                self.assertEqual(monitor.tick(self.db, at=renewed), "completed")
        self.assertEqual(wire.call_count, 2)
        self.assertEqual(wire.call_args.args, (providers.ISSUER_HOST, issuer_news.PATH))
        self.assertEqual(wire.call_args.kwargs["limit"], issuer_news.MAX_BYTES)
        latest = monitor.dashboard(self.db, at=renewed)
        self.assertEqual(
            [(e["id"], e["title"]) for e in latest["events"]],
            [(event["id"], "NVIDIA updates conference announcement")],
        )
        self.assertEqual(
            len(self.db.execute("SELECT id FROM event_versions").fetchall()), 2
        )
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM documents WHERE body IS NOT NULL"
            ).fetchone()[0],
            0,
        )
        self.assertFalse((self.path.parent / "documents").exists())
        passages = evidence.search(self.db, self.nvda)
        self.assertEqual(len(passages), 1)
        self.assertIsNone(passages[0]["financial"])
        self.assertNotIn("PRIVATE UNUSED BODY", repr(latest) + repr(passages))
        for unsafe in (
            b"<!DOCTYPE rss [<!ENTITY x 'expanded'>]>" + first,
            first.replace(b"08:30:00 -0400", b"08:30:00"),
            first.replace(b"Press Release - NVIDIA Newsroom", b"Fake feed"),
        ):
            with self.assertRaises(ValueError):
                issuer_news.rows(unsafe, renewed)

    def test_actual_source_adapter_runs_once_across_workers_and_preserves_event_provenance(
        self,
    ):
        self.assertIsNone(monitor.tick(self.db, at=START))
        ident = monitor.configure(self.db, self.nvda, "sec", 60, True, at=START)
        self.assertEqual(
            ident, monitor.configure(self.db, self.nvda, "sec", 60, True, at=START)
        )
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM monitor_occurrences WHERE status='pending'"
            ).fetchone()[0],
            337,
        )
        seen = []
        with closing(db.connect(self.path)) as other:

            def wire(host, path, **_):
                self.assertFalse(self.db.in_transaction)
                self.assertEqual(host, providers.SEC_HOST)
                seen.append(path)
                self.assertIsNone(monitor.tick(other, at=START))
                self.assertEqual(
                    monitor.dashboard(other, at=START)["history"][0]["status"],
                    "running",
                )
                return json.dumps(sec_packet()).encode()

            with (
                patch.dict(
                    os.environ, {"STOCKINSIGHT_SEC_CONTACT": "contract@example.org"}
                ),
                patch.object(providers, "_fetch", wire),
            ):
                self.assertEqual(monitor.tick(self.db, at=START), "completed")
                self.assertIsNone(monitor.tick(other, at=START))
                self.assertEqual(
                    monitor.tick(other, at=monitor._stamp(START, timedelta(hours=1))),
                    "completed",
                )
        view = monitor.dashboard(self.db, at=START)
        self.assertEqual(len(seen), 1)  # Second schedule slot reused a cache receipt.
        self.assertTrue(view["history"][0]["cached"])
        self.assertEqual(
            view["history"][0]["source_check_id"], view["history"][1]["source_check_id"]
        )
        self.assertTrue(view["history"][0]["source_checked_at"])
        self.assertTrue(view["events"])
        for event in view["events"]:
            self.assertEqual(event["instrument_id"], self.nvda)
            self.assertEqual(event["state"], "occurred")
            ref = evidence.get(self.db, self.nvda, event["source_ref"])
            self.assertEqual(ref["financial"]["filed"], event["occurred_at"])
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_outage_marks_every_original_slot_once_and_one_bounded_catchup(self):
        monitor.configure(self.db, self.msft, "sec", 60, True, at=START)
        resumed = monitor._stamp(START, timedelta(days=100, minutes=30))
        with (
            closing(db.connect(self.path)) as restarted,
            patch.dict(os.environ, {}, clear=True),
            patch.object(providers, "_fetch") as fetch,
        ):
            self.assertEqual(monitor.tick(restarted, at=resumed), "failed")
            self.assertIsNone(monitor.tick(restarted, at=resumed))
            fetch.assert_not_called()
        stats = self.db.execute(
            """SELECT sum(slot_count),count(DISTINCT recovery_group),max(slot_count)
               FROM monitor_occurrences WHERE status='missed'"""
        ).fetchone()
        self.assertEqual(tuple(stats[:2]), (2401, 1))
        self.assertGreater(stats[2], 1000)
        catchup = self.db.execute(
            "SELECT * FROM monitor_occurrences WHERE kind='catch_up'"
        ).fetchone()
        self.assertEqual(
            (catchup["status"], catchup["source_status"]), ("failed", "unavailable")
        )
        self.assertIn("contact", catchup["detail"])
        self.assertEqual(
            catchup["id"],
            self.db.execute(
                "SELECT DISTINCT recovery_group FROM monitor_occurrences WHERE status='missed'"
            ).fetchone()[0],
        )
        original = monitor.configure(self.db, self.msft, "sec", 60, False, at=resumed)
        self.assertEqual(
            original,
            monitor.configure(self.db, self.msft, "sec", 60, False, at=resumed),
        )
        self.assertEqual(monitor.dashboard(self.db, at=resumed)["next_checks"], [])
        self.assertIsNone(
            monitor.tick(self.db, at=monitor._stamp(resumed, timedelta(days=10)))
        )
        self.assertGreater(
            self.db.execute(
                "SELECT count(*) FROM monitor_occurrences WHERE status='cancelled'"
            ).fetchone()[0],
            0,
        )

    def test_crashed_claim_is_fenced_and_never_reissued(self):
        monitor.configure(self.db, self.nvda, "issuer", 60, True, at=START)
        claimed = monitor._claim(self.db, db.instant(START))
        self.assertIsNotNone(claimed)
        with (
            closing(db.connect(self.path)) as restarted,
            patch.object(providers, "_fetch") as fetch,
        ):
            self.assertIsNone(
                monitor.tick(restarted, at=monitor._stamp(START, monitor.LEASE))
            )
            fetch.assert_not_called()
        stale = monitor.dashboard(self.db, at=START)["history"][0]
        self.assertEqual((stale["id"], stale["status"]), (claimed["id"], "failed"))
        self.assertIn("unconfirmed", stale["detail"])
        self.assertEqual(stale["source_check_id"], None)

    def test_fixture_foreground_loop_event_revisions_and_scoped_manual_plans(self):
        fixture_path = self.path.parent / "fixture.sqlite"
        with closing(workspace(fixture=True, path=fixture_path)[0]) as fixture:
            ids = {
                i["ticker"]: i["id"] for i in universe.universe(fixture)["instruments"]
            }
            nvda, msft = ids["NVDA"], ids["MSFT"]
            passages = evidence.seed_fixture(fixture, nvda)
            day = "2030-05-08"
            first = events.append_event(
                fixture,
                nvda,
                kind="earnings_call",
                state="tentative",
                source_ref=passages[0]["id"],
                precision="day",
                scheduled_start=day,
            )
            plan = {
                "title": "Read Microsoft results",
                "instrument_id": msft,
                "day": day,
                "relevance": "Check the watchlist listing's next report.",
            }
            self.assertEqual(monitor.action(fixture, "monitor-event", plan), "/monitor")
            monitor.action(fixture, "monitor-event", plan)
            upcoming = monitor.dashboard(fixture, at=START)["upcoming"]
            self.assertEqual({r["instrument_id"] for r in upcoming}, {nvda, msft})
            self.assertEqual(len(upcoming), 2)
            events.append_event(
                fixture,
                nvda,
                kind="earnings_call",
                state="cancelled",
                source_ref=passages[0]["id"],
                precision="day",
                scheduled_start=day,
                supersedes=first["id"],
            )
            self.assertEqual(
                [x["id"] for x in monitor.dashboard(fixture, at=START)["events"]],
                [first["event_id"]],
            )
            self.assertEqual(
                [
                    x["instrument_id"]
                    for x in monitor.dashboard(fixture, at=START)["upcoming"]
                ],
                [msft],
            )
            monitor.action(
                fixture,
                "monitor-configure",
                {
                    "provider": "issuer",
                    "interval_minutes": "60",
                    "enabled": "1",
                    "instrument_id": nvda,
                },
            )
            stop = threading.Event()

            class StopAfterTick:
                def is_set(self):
                    return stop.is_set()

                def wait(self, _):
                    stop.set()

            with patch.object(providers, "_fetch") as fetch:
                thread = threading.Thread(
                    target=monitor.run_foreground, args=(fixture_path, StopAfterTick())
                )
                thread.start()
                thread.join(10)
                self.assertFalse(thread.is_alive())
                fetch.assert_not_called()
            row = monitor.dashboard(fixture)["history"][0]
            self.assertEqual(row["status"], "completed")
            self.assertIn("synthetic", row["detail"])
            self.assertIsNone(row["source_check_id"])
            proposal = universe.import_snapshot(
                fixture, SAMPLE.split(b"MSFT")[0], complete=True
            )
            if proposal["confirmable"]:
                universe.accept_candidate(fixture, proposal["id"])
            self.assertEqual(monitor.dashboard(fixture, at=START)["upcoming"], [])
            with self.assertRaisesRegex(ValueError, "active"):
                monitor.action(
                    fixture, "monitor-event", {**plan, "title": "Outside watchlist"}
                )
