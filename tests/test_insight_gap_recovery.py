"""A research requirement survives input mistakes and stays visible at the worker's search boundary."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stockinsight import assessment, db, evidence, executor, research
from stockinsight.bridge import Bridge
from tests.test_insight_evidence import workspace
from tests.test_insight_executor import SETTINGS, reply


class GapRecovery(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ordinary.sqlite"
        self.conn, items = workspace(path=self.path)
        self.addCleanup(lambda: self.conn.close())
        self.msft = items["MSFT"]["id"]

    def add(self, metric, quarter, value, stream, currency="USD", unit=None, *, at="2025-01-02T12:00:00Z"):
        start, end = {
            1: ("2024-01-01", "2024-03-31"),
            2: ("2024-04-01", "2024-06-30"),
            3: ("2024-07-01", "2024-09-30"),
        }[quarter]
        unit = unit or (currency + " per share" if metric == "dividend_per_share" else currency)
        f = evidence.revenue("CIK0000789019", f"Q{quarter} FY25", start, end, str(value), unit)
        f.update(
            metric=metric,
            currency=currency,
            share_basis="common share" if metric.endswith("_per_share") else "total",
        )
        raw = json.dumps(f).encode()
        staged = evidence._stage(self.conn, "full", raw)
        with db.write(self.conn) as seq:
            doc = evidence._save(
                self.conn,
                seq,
                self.msft,
                "test_issuer",
                stream,
                "Synthetic MSFT disclosure",
                staged,
                [("data/1", f"{metric} {f['period_label']}: {value} {unit}", at, f)],
                at,
                published=at,
                precision="second",
                retention="full",
            )
        return self.conn.execute("SELECT id FROM evidence_passages WHERE document_id=?", (doc,)).fetchone()[0]

    def claim(self, question, cutoff=None):
        job = research.ask(self.conn, self.msft, question, cutoff=cutoff)
        self.lease = research.claim(self.conn, job, "disposable-worker", "attempt")
        self.bridge = Bridge(self.conn, self.lease)

    def compare(self, current, baseline):
        return self.bridge.call(
            "compare_financials", {"kind": "period_trend", "current": current, "baseline": baseline}
        )

    def submit(self, ids, calculation=None):
        calls = [
            (r["tool"], json.loads(r["output"]))
            for r in self.conn.execute(
                "SELECT * FROM receipts WHERE run_id=? ORDER BY commit_seq", (self.lease.run_id,)
            )
        ]
        brief, _ = assessment.render(
            self.bridge.context,
            {
                "status": "complete",
                "passage_ids": ids,
                "calculations": [calculation] if calculation else [],
                "gaps": [],
            },
            calls,
        )
        return research.submit(self.conn, self.lease, brief, {"adapter": "offline contract"})

    def test_legacy_reversed_trend_recovers_the_requested_periods_units_and_metric_exactly_once(self):
        a, b, c = [self.add("revenue", i, n, f"test:revenue-{i}") for i, n in enumerate((80, 120, 150), 1)]
        eps = [self.add("dividend_per_share", i, "0.5", f"test:dividend-{i}") for i in (1, 2)]
        eur = [self.add("revenue", i, 40 + i, f"test:eur-{i}", "EUR") for i in (1, 2)]
        scaled = [self.add("revenue", i, 80 + i, f"test:scaled-{i}", unit="USD million") for i in (1, 2)]
        self.claim("Compare Microsoft's GAAP revenue for Q1 FY25 and Q2 FY25.")
        available = self.bridge.call("search_evidence", {})
        for ref in available["evidence_ids"]:
            self.bridge.call("get_evidence", {"id": ref})
        failed = self.compare(a, b)
        self.assertEqual(failed["status"], "invalid_input")
        gap_id = failed["gap_id"]

        # Precisely the requirement, signature and search-receipt version written by reviewed schema v2.
        pair = []
        for ref in (a, b):
            f = evidence.get(self.conn, self.msft, ref)["financial"]
            pair.append([f[k] for k in ("company", "metric", "period_start", "period_end")])
        old = json.dumps({"kind": "comparison", "operation": "period_trend", "pair": pair}, sort_keys=True)
        signature = hashlib.sha256(old.encode()).hexdigest()[:16]
        with db.write(self.conn):
            self.conn.execute("UPDATE gap_requirements SET requirement=? WHERE gap_id=?", (old, gap_id))
            self.conn.execute(
                "UPDATE capability_gaps SET capability=? WHERE id=?",
                (f"compare_financials (period_trend {signature})", gap_id),
            )
            self.conn.execute("UPDATE receipts SET version='1' WHERE id=?", (available["receipt_id"],))
        self.conn.close()
        self.conn = db.connect(self.path)
        self.bridge = Bridge(self.conn, self.lease)
        for curr, base in ((c, b), (eps[1], eps[0]), (eur[1], eur[0]), (scaled[1], scaled[0])):
            wrong = self.compare(curr, base)
            self.assertEqual(wrong["status"], "ok")
            self.assertEqual(wrong["outstanding_gap_ids"], [gap_id])
        self.assertEqual(self.compare(a, b)["gap_id"], gap_id)
        valid = self.compare(b, a)
        self.assertEqual(valid["outstanding_gap_ids"], [])
        self.assertEqual((valid["data"]["difference"], valid["data"]["percent_change"]), ("40", "50"))
        repeated_error = self.compare(a, b)
        self.assertEqual(repeated_error["status"], "invalid_input")
        self.assertEqual(repeated_error["outstanding_gap_ids"], [])
        self.assertEqual(repeated_error["data"]["covered_by_receipt_id"], valid["receipt_id"])
        repeated_good = self.compare(b, a)
        self.assertEqual(repeated_good["outstanding_gap_ids"], [])
        self.assertIsNotNone(self.submit([b, a], valid["receipt_id"]))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM capability_gaps").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM gap_resolutions").fetchone()[0], 1)
        proof = self.conn.execute("SELECT * FROM gap_resolutions").fetchone()
        self.assertEqual(proof["receipt_id"], valid["receipt_id"])
        self.assertEqual(json.loads(proof["passage_ids"]), [b, a])
        self.assertEqual(self.conn.execute("SELECT requirement FROM gap_requirements").fetchone()[0], old)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM receipts WHERE status='invalid_input'").fetchone()[0], 3
        )
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        case = self.bridge.context["case_id"]
        self.conn.close()
        self.conn = db.connect(self.path)

        def followup():
            job = research.continuation(self.conn, case)
            self.lease = research.claim(self.conn, job, "next-worker", "attempt")
            self.bridge = Bridge(self.conn, self.lease)

        followup()
        with self.assertRaisesRegex(ValueError, "outside the run read-set"):
            self.bridge.call("get_evidence", {"id": b})
        self.bridge.call("search_evidence", {})
        retry = self.compare(a, b)
        self.assertEqual(retry["outstanding_gap_ids"], [])
        self.assertIn(
            retry["data"]["covered_by_receipt_id"], (valid["receipt_id"], repeated_good["receipt_id"])
        )
        for ref in (b, a):
            self.bridge.call("get_evidence", {"id": ref})
        with self.assertRaises(ValueError):
            self.submit([b, a], valid["receipt_id"])
        fresh = self.compare(b, a)
        self.assertIsNotNone(self.submit([b, a], fresh["receipt_id"]))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM gap_resolutions").fetchone()[0], 1)
        # An actual amendment invalidates both previous attempts' proof. The new gap
        # is resolved only after the new pair has been calculated for this run.
        amended = self.add("revenue", 1, 85, "test:revenue-1")
        followup()
        self.bridge.call("search_evidence", {})
        for ref in (b, amended):
            self.bridge.call("get_evidence", {"id": ref})
        stale = self.compare(amended, b)
        self.assertEqual(stale["outstanding_gap_ids"], [gap_id])
        self.assertNotIn("covered_by_receipt_id", stale["data"])
        repaired = self.compare(b, amended)
        self.assertEqual((repaired["outstanding_gap_ids"], repaired["data"]["difference"]), ([], "35"))
        self.assertTrue(self.submit([b, amended], repaired["receipt_id"]))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM gap_resolutions").fetchone()[0], 2)

    def test_ordinary_worker_can_read_every_returned_id_and_answer_from_match_seventeen(self):
        target = self.add("dividend_per_share", 2, "0.61", "test:dividend")
        for i in range(16):
            self.add("revenue", 2, 120 + i, f"test:unrelated-{i}")
        projected = []

        def model(body, *_):
            request = json.loads(body)
            last = request["input"][-1]
            if last.get("type") != "function_call_output":
                return reply("search_evidence", {}, 1)
            out = json.loads(last["output"])
            if out["coverage"] == "search_evidence":
                rows = out["data"]["passages"]
                projected.extend(row["id"] for row in rows)
                matching = [row for row in rows if row["financial"]["metric"] == "dividend_per_share"]
                self.assertEqual(len(matching), 1, "Only the seventeenth result is eligible.")
                self.assertFalse(out["data"]["has_more"])
                return reply("get_evidence", {"id": matching[0]["id"]}, 2)
            return reply(
                "submit_brief",
                {"status": "complete", "passage_ids": out["evidence_ids"], "gaps": [], "calculations": []},
                3,
            )

        with patch.dict(os.environ, SETTINGS, clear=True), patch.object(executor, "_post", model):
            job = research.ask(
                self.conn, self.msft, "What dividend per share did Microsoft report in Q2 FY25?"
            )
            self.assertIsNotNone(research.run_job(self.conn, job))
        self.assertEqual(projected[16], target)
        host = json.loads(
            self.conn.execute("SELECT output FROM receipts WHERE tool='search_evidence'").fetchone()[0]
        )
        self.assertEqual(host["evidence_ids"], projected)
        brief = json.loads(self.conn.execute("SELECT body FROM briefs").fetchone()[0])
        self.assertIn("0.61", brief["conclusion"])

    def test_next_page_is_receipt_scoped_at_the_original_watermark_and_case_cutoff(self):
        excluded = self.add("dividend_per_share", 2, "0.61", "test:dividend")
        for i in range(24):
            self.add("revenue", 2, 80 + i, f"test:revenue-{i}")
        question = "What dividend per share did Microsoft report in Q2 FY25?"
        self.claim(question, cutoff="2025-01-03T00:00:00Z")
        page = self.bridge.call("search_evidence", {})
        sent = executor._tool_output("search_evidence", page)
        self.assertEqual(sent["data"]["limit"], 24)
        self.assertTrue(sent["data"]["has_more"])
        self.assertEqual(sent["evidence_ids"], page["evidence_ids"])
        self.assertNotIn(excluded, page["evidence_ids"])
        limitation = self.bridge.call(
            "record_gap",
            {"metric": "dividend_per_share", "period": "Q2 FY25", "attempt_receipt_id": sent["receipt_id"]},
        )
        self.assertEqual(limitation["outstanding_gap_ids"], [limitation["gap_id"]])
        self.assertTrue(limitation["data"]["search_has_more"])
        cursor = sent["data"]["next_cursor"]
        self.assertEqual(cursor, sent["receipt_id"])
        with self.assertRaisesRegex(ValueError, "Cursor"):
            self.bridge.call("next_evidence_page", {"cursor": limitation["receipt_id"]})
        # One newly ingested stream is eligible at the cutoff, while the amended
        # dividend is known only later. Neither may displace this cursor's #25.
        extra = self.add("revenue", 1, 900, "test:added")
        later = self.add("dividend_per_share", 2, ".75", "test:dividend", at="2025-01-04T00:00:00Z")
        terminal = self.bridge.call("next_evidence_page", {"cursor": cursor})
        self.assertEqual(terminal["evidence_ids"], [excluded])
        self.assertEqual(terminal["outstanding_gap_ids"], [])
        self.assertEqual(terminal["data"]["evidence_commit_seq"], page["data"]["evidence_commit_seq"])
        self.assertEqual((terminal["data"]["page"], terminal["data"]["next_cursor"]), (2, None))
        self.assertEqual(
            terminal["resolved_gaps"],
            [
                {
                    "gap_id": limitation["gap_id"],
                    "passage_ids": [excluded],
                    "proof_receipt_ids": [terminal["receipt_id"]],
                }
            ],
        )
        replay = self.bridge.call("next_evidence_page", {"cursor": cursor})
        self.assertEqual(replay["evidence_ids"], terminal["evidence_ids"])
        self.assertNotIn("resolved_gaps", replay)
        with self.assertRaisesRegex(ValueError, "Cursor"):
            self.bridge.call("next_evidence_page", {"cursor": terminal["receipt_id"]})
        self.bridge.call("get_evidence", {"id": excluded})
        self.assertTrue(self.submit([excluded]))
        self.claim(question, cutoff="2025-01-03T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "Cursor"):
            self.bridge.call("next_evidence_page", {"cursor": cursor})
        with self.assertRaisesRegex(ValueError, "read-set"):
            self.bridge.call("get_evidence", {"id": excluded})
        fresh = self.bridge.call("search_evidence", {})
        self.assertIn(extra, fresh["evidence_ids"])
        remainder = self.bridge.call("next_evidence_page", {"cursor": fresh["data"]["next_cursor"]})
        self.assertIn(excluded, remainder["evidence_ids"])
        self.assertNotIn(later, fresh["evidence_ids"] + remainder["evidence_ids"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM gap_resolutions").fetchone()[0], 1)

    def test_ordinary_worker_can_follow_cursor_and_complete_using_result_twenty_five(self):
        target = self.add("dividend_per_share", 2, "0.61", "test:dividend")
        for i in range(24):
            self.add("revenue", 2, i + 1, f"test:income-{i}")
        cursor = None

        def model(body, *_):
            nonlocal cursor
            last = json.loads(body)["input"][-1]
            if last.get("type") != "function_call_output":
                return reply("search_evidence", {}, 1)
            out = json.loads(last["output"])
            if out["coverage"] == "search_evidence":
                self.assertTrue(out["data"]["has_more"])
                cursor = out["data"]["next_cursor"]
                return reply(
                    "record_gap",
                    {
                        "metric": "dividend_per_share",
                        "period": "Q2 FY25",
                        "attempt_receipt_id": out["receipt_id"],
                    },
                    2,
                )
            if out["coverage"] == "record_gap":
                self.assertTrue(out["outstanding_gap_ids"])
                return reply("next_evidence_page", {"cursor": cursor}, 3)
            if out["coverage"] == "next_evidence_page":
                self.assertEqual(out["outstanding_gap_ids"], [])
                self.assertEqual(out["evidence_ids"], [target])
                self.assertFalse(out["data"]["has_more"])
                return reply("get_evidence", {"id": out["data"]["passages"][0]["id"]}, 4)
            return reply(
                "submit_brief",
                {"status": "complete", "passage_ids": out["evidence_ids"], "gaps": [], "calculations": []},
                5,
            )

        with (
            patch.dict(os.environ, {**SETTINGS, "STOCKINSIGHT_MAX_REQUESTS": "5"}, clear=True),
            patch.object(executor, "_post", model),
        ):
            job = research.ask(
                self.conn, self.msft, "What dividend per share did Microsoft report in Q2 FY25?"
            )
            self.assertIsNotNone(research.run_job(self.conn, job))
        result = json.loads(self.conn.execute("SELECT body FROM briefs").fetchone()[0])
        self.assertIn("0.61", result["conclusion"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM gap_resolutions").fetchone()[0], 1)

    def test_empty_search_and_failed_capture_require_eligible_cross_page_proof(self):
        self.claim("What were Q2 FY25 revenue and Q2 FY25 dividend per share?")
        empty = self.bridge.call("search_evidence", {})
        with patch.object(evidence, "capture_public", return_value={"status": "unavailable"}):
            failure = self.bridge.call("capture_public", {"provider": "sec"})
        expected = {empty["gap_id"], failure["gap_id"]}
        self.assertEqual(set(failure["outstanding_gap_ids"]), expected)
        at = "2025-01-02T12:00:00Z"
        rows = []
        for i in range(25):
            metric = "revenue" if i == 0 else "dividend_per_share" if i == 24 else "net_income"
            unit = "USD per share" if i == 24 else "USD"
            fact = evidence.revenue(
                "CIK0000789019",
                "Q2 FY25",
                "2024-04-01",
                "2024-06-30",
                "0.61" if i == 24 else str(i + 100),
                unit,
            )
            fact.update(metric=metric, share_basis="common share" if i == 24 else "total")
            rows.append((f"reported/{i:02d}", f"{metric} {fact['value']} {unit}", at, fact))
        staged = evidence._stage(self.conn, "full", json.dumps(rows).encode())
        with db.write(self.conn) as seq:
            doc = evidence._save(
                self.conn,
                seq,
                self.msft,
                "sec",
                "test:paged-source",
                "Synthetic MSFT filing",
                staged,
                rows,
                at,
                published=at,
                precision="second",
                retention="full",
            )
        with patch.object(evidence, "capture_public", return_value={"status": "ok", "document_id": doc}):
            capture = self.bridge.call("capture_public", {"provider": "sec"})
        self.assertEqual(set(capture["outstanding_gap_ids"]), expected)
        first = self.bridge.call("search_evidence", {})
        self.assertEqual(set(first["outstanding_gap_ids"]), expected)
        second = self.bridge.call("next_evidence_page", {"cursor": first["data"]["next_cursor"]})
        self.assertEqual(second["outstanding_gap_ids"], [])
        proof = {first["evidence_ids"][0], second["evidence_ids"][0]}
        self.assertEqual({x["gap_id"] for x in second["resolved_gaps"]}, expected)
        for record in second["resolved_gaps"]:
            self.assertEqual(set(record["passage_ids"]), proof)
            self.assertEqual(set(record["proof_receipt_ids"]), {first["receipt_id"], second["receipt_id"]})
        for row in self.conn.execute("SELECT * FROM gap_resolutions"):
            self.assertEqual(row["receipt_id"], second["receipt_id"])
            self.assertEqual(set(json.loads(row["passage_ids"])), proof)
        for ref in sorted(proof):
            self.bridge.call("get_evidence", {"id": ref})
        self.assertTrue(self.submit(sorted(proof)))
        attempts = {row[0] for row in self.conn.execute("SELECT receipt_id FROM gap_attempts")}
        self.assertEqual(attempts, {failure["receipt_id"], empty["receipt_id"]})
