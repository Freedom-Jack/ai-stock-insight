"""Missing-input declarations, recoverable source failures and frozen case history."""

import json
import os
import unittest
from unittest.mock import patch

from stockinsight import assessment, db, evidence, gaps, providers, research, universe
from stockinsight.bridge import Bridge
from tests.test_insight_evidence import SAMPLE, sec_packet


class GapTests(unittest.TestCase):
    def setUp(self):
        self.db = db.connect(":memory:")
        self.addCleanup(self.db.close)
        universe.import_snapshot(self.db, SAMPLE, complete=True)
        self.instrument = self.db.execute("SELECT id FROM instruments WHERE ticker='MSFT'").fetchone()[0]
        self.identity = universe.instrument(self.db, self.instrument)

    def start(self, question=None, case=None):
        job = (
            research.ask(self.db, self.instrument, question)
            if question
            else research.continuation(self.db, case)
        )
        self.lease = research.claim(self.db, job, "local_test", "dispatch")
        self.bridge = Bridge(self.db, self.lease)

    def perform(self, tool, args=None):
        return self.bridge.call(tool, args or {})

    def capture(self):
        packet = sec_packet()
        packet["cik"] = "789019"
        with (
            patch.dict(os.environ, {"STOCKINSIGHT_SEC_CONTACT": "fixture@example.org"}),
            patch.object(providers, "_fetch", return_value=json.dumps(packet).encode()),
        ):
            return self.perform("capture_public", {"provider": "sec"})

    def declare(self, attempt, metric="dividend_per_share", period="Q2 FY25"):
        return self.perform("record_gap", {"metric": metric, "period": period, "attempt_receipt_id": attempt})

    def receipts(self):
        return list(
            self.db.execute("SELECT * FROM receipts WHERE run_id=? ORDER BY commit_seq", (self.lease.run_id,))
        )

    def submit(self, ids, gap_ids):
        calls = [(r["tool"], json.loads(r["output"])) for r in self.receipts()]
        body, _ = assessment.render(
            self.bridge.context,
            {
                "status": "partial" if gap_ids else "complete",
                "passage_ids": ids,
                "gaps": gap_ids,
                "calculations": [],
            },
            calls,
        )
        return research.submit(self.db, self.lease, body, {"adapter": "offline transport"})

    def fact(
        self,
        metric,
        period,
        *,
        basis="US GAAP",
        value="0.76",
        role="actual",
        currency="USD",
        unit=None,
        share_basis=None,
        company="CIK0000789019",
        stream="fixture:test-disclosure",
    ):
        # A later primary-source observation in the same scope; no source or model service is contacted.
        per_share = metric.endswith("_per_share")
        unit = unit or (currency + " per share" if per_share else "%")
        share_basis = share_basis or ("common share" if per_share else "total")
        label = f"Reported {company} {metric} {period} {basis} {role} {value} {unit} {share_basis}."
        raw = label.encode()
        staged = evidence._stage(self.db, "full", raw)
        fact = evidence.revenue(company, period, "2024-04-01", "2024-06-30", value, unit)
        fact.update(metric=metric, basis=basis, share_basis=share_basis, role=role, currency=currency)
        with db.write(self.db) as seq:
            evidence._save(
                self.db,
                seq,
                self.instrument,
                "test_disclosure",
                stream,
                label,
                staged,
                [("table/cell", label, db.now(), fact)],
                db.now(),
                published=None,
                precision="unknown",
                retention="full",
            )

    def test_scoped_dividend_gap_partial_and_later_eligible_evidence_preserve_first_revision(self):
        self.start("What GAAP dividend per share did Microsoft report in USD in Q2 FY25?")
        self.assertEqual(self.capture()["status"], "ok")
        found = self.perform("search_evidence")
        revenue = self.perform("get_evidence", {"id": found["evidence_ids"][0]})
        with self.assertRaisesRegex(ValueError, "latest scoped evidence search"):
            self.declare(revenue["receipt_id"])
        gap = self.declare(found["receipt_id"])
        again = self.declare(found["receipt_id"])
        self.assertEqual(gap["gap_id"], again["gap_id"])
        self.assertEqual(gap["outstanding_gap_ids"], [gap["gap_id"]])
        self.assertEqual(gap["data"]["attempt_receipt_id"], found["receipt_id"])
        original = self.submit(revenue["evidence_ids"], [gap["gap_id"]])
        frozen = tuple(
            self.db.execute(
                "SELECT body,manifest,manifest_hash,case_id FROM briefs WHERE id=?", (original,)
            ).fetchone()
        )
        self.assertIn("unavailable", json.loads(frozen[0])["conclusion"])
        self.assertEqual(json.loads(frozen[0])["gaps"], [gap["gap_id"]])
        research.review(self.db, original)
        self.start(case=frozen[3])
        # Another run cannot use the previous worker's reading to manufacture a declaration.
        with self.assertRaisesRegex(ValueError, "latest scoped evidence search"):
            self.declare(found["receipt_id"])
        self.assertEqual(self.capture()["outstanding_gap_ids"], [gap["gap_id"]])
        for period, basis, currency in (
            ("Q1 FY25", "US GAAP", "USD"),
            ("Q2 FY25", "non-GAAP", "USD"),
            ("Q2 FY25", "US GAAP", "EUR"),
        ):
            self.fact("dividend_per_share", period, basis=basis, currency=currency)
            found = self.perform("search_evidence")
            self.assertEqual(found["outstanding_gap_ids"], [gap["gap_id"]])
        # The current worker's real search still lacks a GAAP dividend for Q2. It
        # can submit the inherited material gap without issuing a second declaration.
        self.perform("get_evidence", {"id": revenue["evidence_ids"][0]})
        self.assertTrue(self.submit(revenue["evidence_ids"], [gap["gap_id"]]))
        self.start(case=frozen[3])
        self.fact("dividend_per_share", "Q2 FY25")
        found = self.perform("search_evidence")
        self.assertEqual(found["outstanding_gap_ids"], [])
        relevant = next(
            p for p in found["data"]["passages"] if p["financial"]["metric"] == "dividend_per_share"
        )
        self.perform("get_evidence", {"id": relevant["id"]})
        self.assertTrue(self.submit([relevant["id"]], []))
        self.assertEqual(
            tuple(
                self.db.execute(
                    "SELECT body,manifest,manifest_hash,case_id FROM briefs WHERE id=?", (original,)
                ).fetchone()
            ),
            frozen,
        )
        self.assertEqual(self.db.execute("SELECT lifecycle FROM capability_gaps").fetchone()[0], "resolved")
        proof = self.db.execute("SELECT receipt_id,passage_ids FROM gap_resolutions").fetchone()
        self.assertEqual((proof[0], json.loads(proof[1])), (found["receipt_id"], [relevant["id"]]))
        self.assertEqual(self.db.execute("SELECT count(*) FROM gap_attempts").fetchone()[0], 3)

    def test_empty_capture_reread_accepts_complete_and_keeps_each_observation(self):
        self.start("What quarterly revenue did Microsoft report?")
        empty = self.perform("search_evidence")
        self.assertEqual(empty["status"], "partial")
        capture = self.capture()
        self.assertEqual(capture["status"], "ok")
        self.assertEqual(capture["outstanding_gap_ids"], [empty["gap_id"]])
        found = self.perform("search_evidence")
        self.assertEqual(found["outstanding_gap_ids"], [])
        exact = self.perform("get_evidence", {"id": found["evidence_ids"][0]})
        self.assertTrue(self.submit(exact["evidence_ids"], []))
        rows = self.receipts()
        run = self.db.execute("SELECT * FROM runs WHERE id=?", (self.lease.run_id,)).fetchone()
        self.assertEqual(gaps.outstanding(self.db, run, rows[:1]), {empty["gap_id"]})
        self.assertEqual(gaps.outstanding(self.db, run, rows), set())
        self.assertEqual(json.loads(rows[0]["output"]), empty)

    def test_empty_search_for_specific_period_requires_matching_data_and_actual_role(self):
        self.start("What GAAP operating margin did Microsoft report in Q3 FY26?")
        empty = self.perform("search_evidence")["gap_id"]
        self.capture()
        self.assertEqual(self.perform("search_evidence")["outstanding_gap_ids"], [empty])
        self.fact("operating_margin", "Q2 FY26")
        self.assertEqual(self.perform("search_evidence")["outstanding_gap_ids"], [empty])
        self.fact("operating_margin", "Q3 FY26", role="issuer_guidance")
        self.assertEqual(self.perform("search_evidence")["outstanding_gap_ids"], [empty])
        self.fact("operating_margin", "Q3 FY26")
        found = self.perform("search_evidence")
        self.assertEqual(found["outstanding_gap_ids"], [])
        with self.assertRaisesRegex(ValueError, "returned the requested metric"):
            self.declare(found["receipt_id"], metric="operating_margin", period="Q3 FY26")

    def test_financial_proof_requires_a_valid_number_issuer_unit_and_share_basis(self):
        self.start("What GAAP dividend per share did Microsoft report in Q2 FY25?")
        empty = self.perform("search_evidence")["gap_id"]
        for overrides in (
            {"unit": "USD million"},
            {"share_basis": "total"},
            {"company": "CIK0001045810"},
            {"value": "NaN"},
            {"unit": "EUR per share"},
        ):
            with self.subTest(overrides=overrides):
                self.fact("dividend_per_share", "Q2 FY25", **overrides)
                found = self.perform("search_evidence")
                self.assertIn(empty, found["outstanding_gap_ids"])
                self.perform("get_evidence", {"id": found["evidence_ids"][0]})
                with self.assertRaises(ValueError):
                    self.submit(found["evidence_ids"], [empty])
        self.fact("dividend_per_share", "Q2 FY25")
        found = self.perform("search_evidence")
        self.assertEqual(found["outstanding_gap_ids"], [])
        self.perform("get_evidence", {"id": found["evidence_ids"][0]})
        self.assertTrue(self.submit(found["evidence_ids"], []))

    def test_exact_read_outside_search_page_can_prove_a_scoped_gap(self):
        self.start("What quarterly revenue did Microsoft report?")
        self.assertEqual(self.capture()["status"], "ok")
        proof = self.perform("search_evidence")["evidence_ids"][0]
        with patch.object(
            evidence, "capture_public", return_value={"status": "error", "message": "invalid response"}
        ):
            gap = self.perform("capture_public", {"provider": "sec"})
        self.assertEqual(self.capture()["outstanding_gap_ids"], [gap["gap_id"]])
        for index in range(51):
            self.fact("operating_margin", "Q2 FY26", stream=f"fixture:other-disclosure/{index}")
        page = self.perform("search_evidence")
        self.assertNotIn(proof, page["evidence_ids"])
        self.assertEqual(page["outstanding_gap_ids"], [gap["gap_id"]])
        with self.assertRaisesRegex(ValueError, "returned the requested metric"):
            self.declare(page["receipt_id"], "revenue", "unspecified")
        read = self.perform("get_evidence", {"id": proof})
        self.assertEqual(read["outstanding_gap_ids"], [])
        self.assertTrue(self.submit([proof], []))

    def test_distinct_source_failures_require_qualified_provider_specific_recovery(self):
        self.start("Which quarterly revenue was reported?")
        with patch.dict(os.environ, {"STOCKINSIGHT_SEC_CONTACT": ""}):
            config = self.perform("capture_public", {"provider": "sec"})
        unavailable_issuer = self.perform("capture_public", {"provider": "issuer"})
        with patch.object(
            evidence,
            "capture_public",
            return_value={
                "status": "rate_limited",
                "message": "HTTP 429",
                "retry_at": "2099-01-01T00:00:00Z",
            },
        ):
            limited = self.perform("capture_public", {"provider": "sec"})
        self.assertEqual(limited["retry_after"], "2099-01-01T00:00:00Z")
        causes = {r["status"]: r["remedy"] for r in self.db.execute("SELECT * FROM capability_gaps")}
        self.assertEqual(set(causes), {"not_connected", "unsupported", "rate_limited"})
        self.assertEqual(len(set(causes.values())), 3)
        captured = self.capture()
        self.assertEqual(
            set(captured["outstanding_gap_ids"]),
            {config["gap_id"], limited["gap_id"], unavailable_issuer["gap_id"]},
        )
        found = self.perform("search_evidence")
        self.assertEqual(found["outstanding_gap_ids"], [unavailable_issuer["gap_id"]])
        self.assertEqual(self.db.execute("SELECT count(*) FROM gap_resolutions").fetchone()[0], 2)
