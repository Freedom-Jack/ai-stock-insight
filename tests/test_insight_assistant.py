"""Replay clocks, scoped cloud writes, point-in-time evidence and MCP Events."""

import base64
import json
import os
import secrets
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from stockinsight import assistant, assistant_events, assistant_mcp, db, goals, replay


class AssistantStage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "replay"
        self.key = secrets.token_hex(20)

    def start(self, scenario):
        conn = replay.workspace(self.folder, scenario)
        self.addCleanup(conn.close)
        return conn

    def start_job(self, conn, job):
        info = assistant.claim(conn, job, self.key)
        ref = info["event_passage"]
        assistant.read(conn, job, self.key, ref)
        return ref

    def submit(self, conn, job, refs, calcs=()):
        return assistant.accept(
            conn,
            job,
            self.key,
            refs,
            list(calcs),
            "Shipments could change over the next quarter.",
            "Existing contracts could dampen the effect.",
            "Check the next dated primary disclosure.",
        )

    def test_financial_followup_frozen_scope_receipts_and_restart(self):
        conn = self.start("company")
        first = replay.advance(conn, "company")["jobs"][0]
        job = first["id"]
        ref = self.start_job(conn, job)
        with self.assertRaises(ValueError):
            assistant.claim(conn, job, "other-research-worker")
        rows = assistant.sources(conn, job, self.key)
        other = next(p["id"] for p in rows if p["id"] != ref)
        with self.assertRaises(ValueError):
            self.submit(conn, job, [ref, other])
        c = assistant.compare(conn, job, self.key, ref, other)
        self.assertEqual(c["percent_change"], "15.3433")
        with self.assertRaises(ValueError):
            assistant_mcp.capture(conn, job, self.key, "issuer")
        replay.ingest(
            conn, goals.listings(conn, "watchlist")[0], "filing", db.instant(replay.STEPS["company"][1][0])
        )
        later = conn.execute("SELECT id FROM evidence_passages ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        with self.assertRaises(ValueError):
            assistant.read(conn, job, self.key, later)
        self.assertNotIn(later, {p["id"] for p in assistant.sources(conn, job, self.key)})
        b = self.submit(conn, job, [ref, other], [c["receipt"]])
        self.assertIn("15.3433%", b["summary"])
        self.assertEqual(b, self.submit(conn, job, [ref, other], [c["receipt"]]))
        self.assertEqual(replay.advance(conn, "company")["step"], "filing")
        question = "What does the later filing add?"
        follow = assistant.follow_up(conn, job, question, "same-key")
        with closing(db.connect(self.folder / "research.sqlite3", fixture=True)) as restored:
            self.assertEqual(assistant.follow_up(restored, job, question, "same-key"), follow)
            with self.assertRaises(ValueError):
                assistant.follow_up(restored, job, "A changed question?", "same-key")
            new = follow["job_id"]
            self.start_job(restored, new)
            assistant.read(restored, new, self.key, later)
            self.assertEqual(self.submit(restored, new, [ref, later])["parent"], job)
            case = assistant.case(restored, job)
            self.assertEqual(len(case["jobs"]), 2)
            self.assertEqual(
                restored.execute(
                    "SELECT count(*) FROM delivery_notices WHERE notice_key LIKE 'assistant:%'"
                ).fetchone()[0],
                2,
            )

    def test_irrelevance_duplicate_and_changed_news(self):
        conn = self.start("noise")
        self.assertFalse(replay.advance(conn, "noise")["jobs"])
        job = replay.advance(conn, "noise")["jobs"][0]["id"]
        original = self.start_job(conn, job)
        self.submit(conn, job, [original])
        self.assertEqual(len(replay.advance(conn, "noise")["jobs"]), 1)
        self.assertEqual(conn.execute("SELECT count(*) FROM delivery_notices").fetchone()[0], 1)
        new = replay.advance(conn, "noise")["jobs"][-1]
        self.assertEqual(new["case_id"], job)
        updated = self.start_job(conn, new["id"])
        assistant.read(conn, new["id"], self.key, original)
        result = self.submit(conn, new["id"], [updated, original])
        self.assertIn("one product only", result["summary"])
        self.assertEqual(result["parent"], job)

    def test_calendar_alone_cannot_establish_an_outcome(self):
        conn = self.start("policy")
        job = replay.advance(conn, "policy")["jobs"][0]["id"]
        observed = self.start_job(conn, job)
        prep = self.submit(conn, job, [observed])
        self.assertIn("tentative", prep["summary"])
        self.assertEqual(len(replay.advance(conn, "policy")["jobs"]), 1)
        self.assertNotIn("reduced", json.dumps(assistant.case(conn, job)))
        later = replay.advance(conn, "policy")["jobs"][-1]["id"]
        outcome = self.start_job(conn, later)
        self.assertIn("reduced", self.submit(conn, later, [outcome])["summary"])
        self.assertEqual([r[0] for r in conn.execute("SELECT DISTINCT case_id FROM assistant_jobs")], [job])

    def test_workspace_guard_precedes_migration(self):
        self.folder.mkdir()
        path = self.folder / "research.sqlite3"
        with closing(sqlite3.connect(path)) as other:
            other.execute("CREATE TABLE private_data(value)")
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            replay.workspace(self.folder, "policy")
        self.assertEqual(original, path.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows subscription secret protection")
    def test_verified_subscription_rotation_delivery_restart_and_unsubscribe(self):
        conn = self.start("policy")
        job = replay.advance(conn, "policy")["jobs"][0]["id"]
        key = "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()
        params = {
            "name": assistant_events.EVENT,
            "arguments": {},
            "delivery": {"mode": "webhook", "url": "https://chatgpt.com/test-callback", "secret": key},
        }

        def receiver(url, keys, sub, ident, body):
            if body.get("type") == "verification":
                return json.dumps({"challenge": body["challenge"]}).encode()
            self.assertEqual(body["eventId"], job)
            self.assertEqual(set(body["data"]), {"case_id", "job_id", "label"})
            return b""

        with patch.object(assistant_events, "_post", side_effect=receiver) as send:
            first = assistant_events.subscription(conn, params)
            self.assertEqual(assistant_events.subscription(conn, params)["id"], first["id"])
            self.assertEqual(send.call_count, 1)
            with closing(db.connect(self.folder / "research.sqlite3")) as restored:
                self.assertEqual(assistant_mcp.status(restored)["subscriptions"], 1)
                self.assertEqual(assistant_events.tick(restored), job)
                self.assertIsNone(assistant_events.tick(restored))
                self.assertEqual(assistant_mcp.status(restored)["platform_events"], {"accepted": 1})
                self.assertEqual(
                    restored.execute("SELECT state FROM assistant_jobs").fetchone()[0], "pending"
                )
                self.assertFalse(restored.execute("SELECT 1 FROM delivery_notices").fetchone())
                params["delivery"]["secret"] = "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()
                assistant_events.subscription(restored, params)
                dest = restored.execute("SELECT destination FROM assistant_subscriptions").fetchone()[0]
                self.assertNotIn(key.encode(), dest)
                self.assertEqual(json.loads(assistant_events._protect(dest, decrypt=True))["old"], key)
                assistant_events.subscription(restored, params, remove=True)
                self.assertEqual(assistant_mcp.status(restored)["subscriptions"], 0)
        with self.assertRaises(ValueError):
            assistant_events.subscription(
                conn, {**params, "delivery": {**params["delivery"], "url": "http://127.0.0.1/"}}
            )


if __name__ == "__main__":
    unittest.main()
