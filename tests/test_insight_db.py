"""Foundation schema migrations, sourced event revisions and system-state replay."""

import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stockinsight import db, events, evidence, universe


def contents(path):
    with closing(sqlite3.connect(path)) as raw:
        return list(raw.iterdump())


class MigrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "workspace.sqlite3"

    def test_initialize_reopen_and_reject_mode_changes(self):
        with closing(db.connect(self.path, fixture=True)) as conn:
            self.assertTrue(db.is_fixture(conn))
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            before = tuple(conn.execute("SELECT * FROM migrations WHERE version=1").fetchone())
            item = universe.import_snapshot(conn, b"MSFT", complete=True)["id"]
        with self.assertRaisesRegex(ValueError, "separate workspace"):
            db.connect(self.path, fixture=False)
        with closing(db.connect(self.path)) as conn:
            self.assertTrue(db.is_fixture(conn))
            self.assertEqual(
                tuple(conn.execute("SELECT * FROM migrations WHERE version=1").fetchone()), before
            )
            self.assertEqual(universe.universe(conn)["sources"][0]["active_snapshot_id"], item)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_foreign_database_and_mismatched_migration_preserve_contents(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript("CREATE TABLE legacy(note TEXT); INSERT INTO legacy VALUES ('keep me');")
        before = contents(self.path)
        with self.assertRaisesRegex(ValueError, "separate Stock Insight database"):
            db.connect(self.path)
        self.assertEqual(contents(self.path), before)
        other = self.path.with_name("different-edition.sqlite3")
        with closing(db.connect(other)) as conn:
            universe.import_snapshot(conn, b"NVDA", complete=True)
            conn.execute("UPDATE migrations SET sha256='other schema edition' WHERE version=1")
        before = contents(other)
        with self.assertRaisesRegex(ValueError, "checksum"):
            db.connect(other)
        self.assertEqual(contents(other), before)

    def test_failed_upgrade_rolls_back_ddl_state_and_migration_marker(self):
        with closing(db.connect(self.path, fixture=True)) as conn:
            universe.import_snapshot(conn, b"MSFT", complete=True)
        before = contents(self.path)
        v2 = """CREATE TABLE added_by_upgrade(value TEXT);
                UPDATE watchlist_sources SET alias='partially changed';
                INSERT INTO missing_upgrade_table VALUES ('forced failure');"""
        with patch.object(db, "migrations", return_value=[*db.migrations(), v2]):
            with self.assertRaises(sqlite3.OperationalError):
                db.connect(self.path)
        self.assertEqual(contents(self.path), before)
        with closing(db.connect(self.path)) as conn:
            self.assertEqual(universe.universe(conn)["instruments"][0]["ticker"], "MSFT")
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")


class EventTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "workspace.sqlite3"
        self.conn = db.connect(self.path, fixture=True)
        self.addCleanup(self.conn.close)
        universe.import_snapshot(self.conn, b"NVDA\nMSFT", complete=True)
        self.ids = {i["ticker"]: i["id"] for i in universe.universe(self.conn)["instruments"]}
        self.nvda = self.ids["NVDA"]

    def source(self, text, published):
        staged = evidence._stage(self.conn, "full", text.encode())
        with db.write(self.conn) as seq:
            doc = evidence._save(
                self.conn,
                seq,
                self.nvda,
                "test_calendar",
                "fixture:calendar",
                "Synthetic calendar",
                staged,
                [("announcement", text, published, None)],
                db.now(),
                published=published,
                precision="instant",
                retention="full",
                fixture=True,
            )
        return self.conn.execute("SELECT id FROM evidence_passages WHERE document_id=?", (doc,)).fetchone()[0]

    def test_unknown_date_tentative_interval_confirmed_instant_and_replay(self):
        first_ref = self.source("The next briefing has no announced date.", "2024-10-03T10:00:00Z")
        first = events.append_event(
            self.conn,
            self.nvda,
            kind="company_briefing",
            state="tentative",
            source_ref=first_ref,
            precision="unknown",
        )
        self.assertIsNone(first["scheduled_start"])
        self.assertIsNone(events.at_commit(self.conn, first["event_id"], first["commit_seq"] - 1))
        second_ref = self.source("Tentative dates are April 3–5, 2099 in New York.", "2024-10-03T12:00:00Z")
        second = events.append_event(
            self.conn,
            self.nvda,
            kind="company_briefing",
            state="tentative",
            source_ref=second_ref,
            precision="day",
            scheduled_start="2099-04-03",
            scheduled_end="2099-04-05",
            source_timezone="America/New_York",
            supersedes=first["id"],
        )
        self.assertEqual(second["scheduled_start"], "2099-04-03")
        self.assertIsNone(second["occurred_at"])
        # A version acquired later can have an earlier publication time.
        third_ref = self.source("Confirmed April 4, 2099 at 10 am New York time.", "2024-10-03T11:00:00Z")
        edition = dict(
            kind="company_briefing",
            state="confirmed",
            source_ref=third_ref,
            precision="instant",
            scheduled_start="2099-04-04T10:00:00-04:00",
            source_timezone="America/New_York",
            supersedes=second["id"],
        )
        third = events.append_event(self.conn, self.nvda, **edition)
        self.assertEqual(third["scheduled_start"], "2099-04-04T14:00:00.000000Z")
        self.assertEqual(events.append_event(self.conn, self.nvda, **edition), third)
        with self.assertRaisesRegex(ValueError, "revision conflict"):
            events.append_event(
                self.conn, self.nvda, **{**edition, "scheduled_start": "2099-04-05T08:00:00Z"}
            )
        with closing(db.connect(self.path)) as reopened:
            for version, ref in ((first, first_ref), (second, second_ref), (third, third_ref)):
                visible = events.at_commit(reopened, first["event_id"], version["commit_seq"])
                self.assertEqual(visible, version)
                saved = evidence.get(reopened, self.nvda, ref, commit_seq=visible["commit_seq"], fixture=True)
                self.assertEqual(
                    (visible["source_ref"], visible["document_id"]), (saved["id"], saved["document_id"])
                )
            self.assertEqual(events.at_commit(reopened, first["event_id"]), third)
            self.assertEqual(reopened.execute("SELECT count(*) FROM event_versions").fetchone()[0], 3)

    def test_scope_precision_and_source_checks_rollback_ineligible_revisions(self):
        ref = self.source("Fixture briefing occurred August 1, 2024.", "2024-08-02T00:00:00Z")
        edition = dict(
            kind="briefing", state="occurred", source_ref=ref, precision="day", occurred_at="2024-08-01"
        )
        original = events.append_event(self.conn, self.nvda, **edition)
        self.assertEqual(events.append_event(self.conn, self.nvda, **edition), original)
        before = self.conn.execute("SELECT max(seq) FROM commits").fetchone()[0]
        for overrides in (
            {"source_ref": "missing_passage"},
            {"source_ref": None},
            {"occurred_at": "2099-01-01"},
            {"occurred_at": "2024-06-33"},
            {"precision": "unknown"},
            {"precision": "instant", "occurred_at": "2024-08-01T12:00:00"},
            {"scheduled_start": "2024-08-02", "scheduled_end": "2024-08-01"},
            {"supersedes": original["id"], "kind": "other_kind"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                events.append_event(self.conn, self.nvda, **{**edition, **overrides})
        with self.assertRaises(ValueError):
            events.append_event(self.conn, self.ids["MSFT"], **edition)
        self.assertEqual(self.conn.execute("SELECT max(seq) FROM commits").fetchone()[0], before)
        empty = universe.import_snapshot(self.conn, b"", complete=True)
        universe.accept_candidate(self.conn, empty["id"])
        with self.assertRaises(ValueError):
            events.append_event(self.conn, self.nvda, **{**edition, "supersedes": original["id"]})
        self.assertEqual(events.at_commit(self.conn, original["event_id"]), original)


if __name__ == "__main__":
    unittest.main()
