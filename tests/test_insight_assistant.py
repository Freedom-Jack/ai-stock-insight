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

from stockinsight import assistant, assistant_events, assistant_mcp, db, goals, replay, universe


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

    def test_watchlist_reports_the_active_list_names_and_positions(self):
        conn = self.start("company")
        original = goals.listings(conn, "watchlist")[0]
        source_id = original["source_ids"][0]
        universe.rename_source(conn, source_id, "Long term")
        qualified = ",".join(original[field] for field in universe.LISTING)
        header = ",".join(universe.LISTING)
        result = universe.import_snapshot(
            conn, f"{header}\nQQQ,,,\n{qualified}".encode(), complete=True, source_id="research"
        )
        self.assertEqual(result["state"], "complete")
        reply = assistant_mcp.rpc(conn, "tools/call", {"name": "watchlist", "arguments": {}})
        self.assertFalse(reply["isError"])
        listings = {item["id"]: item for item in json.loads(reply["content"][0]["text"])}
        self.assertCountEqual(
            listings[original["id"]]["watchlists"],
            [{"name": "Long term", "position": 1}, {"name": "research", "position": 2}],
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

    def test_real_http_keeps_browser_and_research_credentials_separate(self):
        import http.client
        from stockinsight.web import application
        from tests.test_insight_web import served

        self.start("company")
        path = self.folder / "research.sqlite3"
        key = secrets.token_hex(24)
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        with (
            patch.object(assistant_mcp, "token", return_value=key),
            served(lambda port: application(path, port, "desk-password")) as port,
        ):

            def post(headers, route="/mcp"):
                with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
                    conn.request("POST", route, payload, {"Content-Type": "application/json", **headers})
                    reply = conn.getresponse()
                    return reply.status, reply.read()

            self.assertEqual(post({})[0], 403)
            self.assertEqual(post({"Authorization": "Basic ZGVtbw=="})[0], 403)
            self.assertEqual(
                post({"Origin": "http://127.0.0.1:" + str(port), "X-StockInsight-Key": key})[0], 403
            )
            status, body = post({"X-StockInsight-Key": key})
            self.assertEqual(status, 200)
            tools = {r["name"] for r in json.loads(body)["result"]["tools"]}
            self.assertEqual(tools, set(assistant_mcp.TOOLS))
            self.assertEqual(post({"X-StockInsight-Key": key}, "/actions/stop")[0], 403)

    def test_stale_claim_and_retired_goal_cannot_commit_or_deliver(self):
        conn = self.start("noise")
        replay.advance(conn, "noise")
        first = replay.advance(conn, "noise")["jobs"][0]["id"]
        original = self.start_job(conn, first)
        replay.ingest(
            conn,
            goals.listings(conn, "watchlist")[0],
            "clarification",
            db.instant(replay.STEPS["noise"][-1][0]),
        )
        with self.assertRaises(ValueError):
            self.submit(conn, first, [original])
        plan = goals.active(conn)[0]
        goals.action(conn, "goal-stop", {"plan": plan["id"]})
        self.assertEqual(
            conn.execute("SELECT state FROM assistant_jobs WHERE id=?", (first,)).fetchone()[0], "cancelled"
        )
        self.assertFalse(conn.execute("SELECT 1 FROM delivery_notices").fetchone())

    def test_interrupted_worker_is_fenced_and_reissued_within_bound(self):
        conn = self.start("company")
        job = replay.advance(conn, "company")["jobs"][0]["id"]
        for attempt in range(1, 4):
            ref = self.start_job(conn, job)
            conn.execute("UPDATE assistant_jobs SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (job,))
            self.assertEqual(assistant.recover(conn), job)
            with self.assertRaises(ValueError):
                self.submit(conn, job, [ref])
            self.assertEqual(
                conn.execute("SELECT state FROM assistant_jobs WHERE id=?", (job,)).fetchone()[0],
                "pending" if attempt < 3 else "failed",
            )
        self.assertEqual(
            conn.execute("SELECT count(*) FROM assistant_interruptions WHERE job_id=?", (job,)).fetchone()[0],
            3,
        )
        self.assertFalse(conn.execute("SELECT 1 FROM delivery_notices").fetchone())

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
