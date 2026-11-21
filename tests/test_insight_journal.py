"""Attribution, review conditions and ordinary research cases from journal questions."""

import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from stockinsight import db, evidence, journal, research, universe
from stockinsight.__main__ import DEMO_CUTOFF, DEMO_QUESTION, EXAMPLE


class JournalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "desk.sqlite3"
        self.conn = db.connect(self.path, fixture=True)
        self.addCleanup(self.conn.close)
        universe.import_snapshot(self.conn, EXAMPLE.read_bytes(), complete=True)
        self.items = {
            i["ticker"]: i["id"] for i in universe.universe(self.conn)["instruments"]
        }
        self.nvda = self.items["NVDA"]
        evidence.seed_fixture(self.conn, self.nvda)
        job = research.ask(self.conn, self.nvda, DEMO_QUESTION, cutoff=DEMO_CUTOFF)
        self.brief = research.run_job(self.conn, job)
        self.case = self.conn.execute(
            "SELECT case_id FROM jobs WHERE id=?", (job,)
        ).fetchone()[0]
        self.scope = {"scope": "case:" + self.case, "brief": self.brief}

    def save(self, name, **fields):
        return journal.action(self.conn, "journal-" + name, fields)

    def source(self, instrument_id, title):
        stamp = db.now()
        staged = evidence._stage(self.conn, "full", title.encode())
        with db.write(self.conn) as seq:
            return evidence._save(
                self.conn,
                seq,
                instrument_id,
                "journal_test",
                "fixture:journal/" + instrument_id,
                title,
                staged,
                [("summary", title, stamp, None)],
                stamp,
                published=stamp,
                precision="second",
                retention="full",
                fixture=True,
            )

    def test_note_attribution_review_condition_reflection_and_reported_action_remain_separate(
        self,
    ):
        original = {
            "key": "n1",
            **self.scope,
            "kind": "intention",
            "body": "Revisit the shipment timing before deciding.",
            "next_source": "yes",
            "condition": "Check whether the next release quantifies the timing effect.",
            "review_on": "2099-03-10",
        }
        path = self.save("note", **original)
        self.assertEqual(self.save("note", **original), path)
        with self.assertRaisesRegex(ValueError, "idempotency"):
            self.save("note", **{**original, "body": "Changed on replay."})
        note = journal.dashboard(self.conn)["upcoming"][0]
        self.assertEqual(
            (note["author"], note["kind"], note["source_revision"], note["body"]),
            ("user", "intention", 1, original["body"]),
        )
        self.assertFalse(note["ready_for_review"])
        with patch.object(journal, "now", return_value="2099-03-10T00:10:00Z"):
            self.assertTrue(journal.dashboard(self.conn)["upcoming"][0]["date_due"])
        self.source(self.items["MSFT"], "Unrelated synthetic Microsoft update")
        self.assertIsNone(
            journal.dashboard(self.conn)["upcoming"][0]["trigger_document_id"]
        )
        exact = self.source(self.nvda, "A new synthetic NVIDIA release")
        due = journal.dashboard(self.conn)["upcoming"][0]
        self.assertTrue(due["ready_for_review"])
        self.assertEqual(due["trigger_document_id"], exact)
        self.assertIsNone(due["reviewed_at"])
        reflection = {
            "key": "review-1",
            "entry": note["id"],
            "body": "The update leaves my question open.",
        }
        self.save("reflect", **reflection)
        self.save("reflect", **reflection)
        self.save(
            "note",
            **self.scope,
            key="n2",
            kind="reported_action",
            body="I chose to wait.",
        )
        with closing(db.connect(self.path)) as restarted:
            records = journal.case_notes(restarted, self.case)["entries"]
            self.assertEqual(
                [r["kind"] for r in records], ["reported_action", "review", "intention"]
            )
            self.assertEqual(records[1]["review_of_id"], note["id"])
            self.assertEqual(
                (records[-1]["body"], records[-1]["brief_id"]),
                (original["body"], self.brief),
            )
            self.assertIsNotNone(records[-1]["reviewed_at"])
            self.assertFalse(journal.dashboard(restarted)["upcoming"])
            self.assertIsNone(
                restarted.execute(
                    "SELECT reviewed_at FROM inbox WHERE brief_id=?", (self.brief,)
                ).fetchone()[0]
            )

    def test_follow_up_once_across_concurrent_starts_restart_and_accepted_result(self):
        form = {"key": "plan-1", **self.scope, "body": DEMO_QUESTION}
        self.save("plan", **form)
        self.save("plan", **form)
        plan = journal.dashboard(self.conn)["upcoming"][0]
        self.assertEqual(
            (plan["case_id"], plan["instrument_id"], plan["job_state"]),
            (self.case, self.nvda, None),
        )
        gate = threading.Barrier(2, timeout=10)

        def launch(_):
            with closing(db.connect(self.path)) as separate:
                gate.wait()
                return journal.action(separate, "journal-start", {"entry": plan["id"]})

        with ThreadPoolExecutor(2) as workers:
            destinations = list(workers.map(launch, range(2)))
        self.assertEqual(destinations[0], destinations[1])
        child = destinations[0].split("/")[-1]
        self.assertNotEqual(child, self.case)
        queued = journal.dashboard(self.conn)["upcoming"][0]
        self.assertEqual(
            (queued["followup_case"], queued["job_state"], queued["accepted_revision"]),
            (child, "ready", None),
        )
        with closing(db.connect(self.path)) as restarted:
            self.assertEqual(
                journal.action(restarted, "journal-start", {"entry": plan["id"]}),
                destinations[0],
            )
            origin = journal.case_notes(restarted, child)["origin"]
            self.assertEqual((origin["id"], origin["case_id"]), (plan["id"], self.case))
            job = restarted.execute(
                "SELECT id FROM jobs WHERE case_id=?", (child,)
            ).fetchone()[0]
            brief_id = research.run_job(restarted, job)
            self.assertTrue(brief_id)
            finished = journal.case_notes(restarted, self.case)["entries"][0]
            self.assertEqual(
                (
                    finished["accepted_revision"],
                    finished["job_state"],
                    finished["brief_id"],
                ),
                (1, "partial", self.brief),
            )
            self.assertFalse(journal.dashboard(restarted)["upcoming"])
            self.assertEqual(
                restarted.execute("SELECT count(*) FROM jobs").fetchone()[0], 2
            )
            self.assertEqual(
                restarted.execute("PRAGMA foreign_key_check").fetchall(), []
            )

    def test_unconfigured_investigation_remains_visible_and_removal_preserves_journal(
        self,
    ):
        with closing(db.connect(self.path.with_name("ordinary.sqlite3"))) as conn:
            universe.import_snapshot(conn, EXAMPLE.read_bytes(), complete=True)
            item = universe.universe(conn)["instruments"][0]
            scope = {"scope": "listing:" + item["id"]}
            journal.action(
                conn,
                "journal-plan",
                {**scope, "key": "p", "body": "What was the reported revenue?"},
            )
            plan = journal.dashboard(conn)["upcoming"][0]
            child = journal.action(conn, "journal-start", {"entry": plan["id"]}).split(
                "/"
            )[-1]
            job = conn.execute(
                "SELECT id FROM jobs WHERE case_id=?", (child,)
            ).fetchone()[0]
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                research.run_job(conn, job)
            blocked = journal.dashboard(conn)["upcoming"][0]
            self.assertEqual(
                (blocked["job_state"], blocked["accepted_revision"]), ("blocked", None)
            )
            journal.action(
                conn,
                "journal-plan",
                {**scope, "key": "another", "body": "When is the next filing?"},
            )
            empty = universe.import_snapshot(conn, b"", complete=True)
            universe.accept_candidate(conn, empty["id"])
            waiting = next(
                n
                for n in journal.dashboard(conn)["upcoming"]
                if n["body"] == "When is the next filing?"
            )
            self.assertFalse(waiting["watched"])
            with self.assertRaises(ValueError):
                journal.action(conn, "journal-start", {"entry": waiting["id"]})
            self.assertEqual(
                conn.execute("SELECT count(*) FROM journal_entries").fetchone()[0], 2
            )
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_mismatched_revisions_bad_dates_and_unknown_attribution_cannot_create_entries(
        self,
    ):
        form = {
            **self.scope,
            "key": "typed",
            "kind": "judgment",
            "body": "The quarter needs more context.",
        }
        for override in (
            {"scope": "listing:" + self.items["MSFT"]},
            {"brief": "absent"},
            {"review_on": "2025-02-30"},
            {"next_source": "custom"},
            {"scope": "case:missing"},
            {"kind": "assistant_inference"},
        ):
            with self.subTest(inputs=override), self.assertRaises(ValueError):
                self.save("note", **{**form, **override})
        self.assertFalse(journal.dashboard(self.conn)["entries"])
