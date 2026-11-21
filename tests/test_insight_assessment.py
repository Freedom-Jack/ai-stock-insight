"""Non-NVIDIA controls for the assessment that enters the private inbox."""

import json
import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from stockinsight import assessment, evidence, executor, providers, research
from stockinsight.bridge import Bridge
from tests.test_insight_evidence import sec_packet, workspace
from tests.test_insight_executor import SETTINGS, reply


class Assessments(unittest.TestCase):
    def setUp(self):
        self.db, listings = workspace()
        self.addCleanup(self.db.close)
        self.msft = listings["MSFT"]
        packet = sec_packet()
        packet["cik"] = 789019
        for fact, value in zip(packet["units"]["USD"], [80_000_000, 120_000_000, 200_000_000]):
            fact.update(val=value, accn="0000789019-24-000001")
        with (
            patch.dict(os.environ, {"STOCKINSIGHT_SEC_CONTACT": "test@example.org"}),
            patch.object(providers, "_fetch", return_value=json.dumps(packet).encode()),
        ):
            self.assertEqual(evidence.capture_public(self.db, self.msft, "sec")["status"], "ok")

    def run_tools(self, question):
        job = research.ask(self.db, self.msft["id"], question)
        lease = research.claim(self.db, job, "fixture-dispatch", "request")
        bridge = Bridge(self.db, lease)
        search = bridge.call("search_evidence", {})
        ids = [p["id"] for p in search["data"]["passages"]]
        for pid in ids:
            bridge.call("get_evidence", {"id": pid})
        return lease, bridge, ids, search

    def render(self, lease, selection):
        run = research.authorized(self.db, lease)
        rows = self.db.execute("SELECT * FROM receipts WHERE run_id=? ORDER BY commit_seq", (run["id"],))
        return assessment.render(
            json.loads(run["context"]), selection, [(r["tool"], json.loads(r["output"])) for r in rows]
        )[0]

    def test_ordinary_scripted_worker_accepts_msft_trend_with_typed_dimensions(self):
        ids = []

        def transport(body, *_):
            request = json.loads(body)
            outputs = [i for i in request["input"] if i.get("type") == "function_call_output"]
            n = len(outputs)
            if n == 0:
                return reply("search_evidence", {}, n)
            data = json.loads(outputs[-1]["output"])
            if n == 1:
                ids.extend(p["id"] for p in data["data"]["passages"])
                return reply("get_evidence", {"id": ids[0]}, n)
            if n == 2:
                return reply("get_evidence", {"id": ids[1]}, n)
            if n == 3:
                return reply(
                    "compare_financials", {"current": ids[0], "baseline": ids[1], "kind": "period_trend"}, n
                )
            return reply(
                "submit_brief",
                {"status": "complete", "passage_ids": ids, "calculations": [data["receipt_id"]], "gaps": []},
                n,
            )

        with (
            patch.dict(os.environ, {**SETTINGS, "STOCKINSIGHT_MAX_REQUESTS": "6"}, clear=True),
            patch.object(executor, "_post", transport),
        ):
            job = research.ask(
                self.db, self.msft["id"], "Compare Microsoft's quarterly revenue across the two periods."
            )
            brief_id = research.run_job(self.db, job)
        brief = self.db.execute("SELECT body,manifest FROM briefs WHERE id=?", (brief_id,)).fetchone()
        body, manifest = map(json.loads, brief)
        self.assertIn("MSFT US GAAP revenue", body["conclusion"])
        self.assertIn("40000000 USD (50%)", body["conclusion"])
        items = manifest["assertions"]
        first = next(a for a in items if a["kind"] == "observation" and a["value"] == "120000000")
        self.assertEqual(
            (
                first["company"],
                first["metric"],
                first["period_start"],
                first["period_end"],
                first["unit"],
                first["basis"],
                first["share_basis"],
            ),
            ("CIK0000789019", "revenue", "2024-04-29", "2024-07-28", "USD", "US GAAP", "total"),
        )
        calc = next(a for a in items if a["kind"] == "calculation")
        self.assertEqual(calc["input_ids"], ids)
        self.assertEqual(calc["difference"], "40000000")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0], 1)

    def test_fabricated_dividend_is_refused_and_a_specific_partial_can_be_accepted(self):
        lease, bridge, ids, search = self.run_tools("What dividend per share did Microsoft declare?")
        fake = {
            "status": "complete",
            "conclusion": "Microsoft declared $12.34 per share.",
            "changes": ["The dividend is $12.34."],
            "calculations": [],
            "gaps": [],
            "claims": [{"type": "fact", "text": "120000000", "evidence_refs": [ids[0]]}],
            "alternative_explanations": ["An alternative."],
            "next_steps": ["Check the filing."],
        }
        with self.assertRaises(ValueError):
            research.submit(self.db, lease, fake, {})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0], 0)
        gap = bridge.call(
            "record_gap",
            {
                "metric": "dividend_per_share",
                "period": "unspecified",
                "attempt_receipt_id": search["receipt_id"],
            },
        )
        draft = self.render(
            lease, {"status": "partial", "passage_ids": [ids[0]], "calculations": [], "gaps": [gap["gap_id"]]}
        )
        self.assertIn("dividend per share is unavailable", draft["conclusion"])
        self.assertTrue(research.submit(self.db, lease, draft, {}))
        self.assertNotIn("12.34", self.db.execute("SELECT body FROM briefs").fetchone()[0])

    def test_all_displayed_fields_are_checked_against_the_typed_result(self):
        lease, _, ids, _ = self.run_tools("What quarterly revenue is in the filing?")
        draft = self.render(
            lease, {"status": "complete", "passage_ids": [ids[0]], "calculations": [], "gaps": []}
        )
        for field, false_text in (
            ("conclusion", "MSFT paid a dividend of $12.34."),
            ("changes", "MSFT reported 120 million EUR of adjusted revenue in 2025."),
            ("alternative_explanations", "NVIDIA recognized these sales."),
            ("next_steps", "The GAAP margin changed by 70%."),
        ):
            with self.subTest(field=field):
                modified = deepcopy(draft)
                modified[field] = false_text if field == "conclusion" else [false_text]
                with self.assertRaises(ValueError):
                    research.submit(self.db, lease, modified, {})
        self.assertTrue(research.submit(self.db, lease, draft, {}))

    def test_question_horizon_and_metric_gate(self):
        unsupported = [
            "What was FY26 third-quarter GAAP operating margin?",
            "What was FY27 second-quarter revenue?",
            "How did annual revenue compare with last year?",
            "What was Q4 FY25 revenue?",
            "What was the revenue per share for Q2 FY25?",
            "Did quarterly revenue decline year over year?",
        ]
        for q in unsupported:
            with self.subTest(question=q), self.assertRaises(executor.ExecutorError):
                executor.execute(q, {}, self.fail, fixture=True)
        self.assertEqual(assessment.objective(unsupported[0]).periods, ("Q3 FY26",))
        self.assertEqual(assessment.required_checks(unsupported[-1]), [])
        self.assertEqual(assessment.required_checks("Did shares rally after the filing?"), ["price_context"])
        self.assertEqual(assessment.required_checks("What were shares outstanding?"), [])
        self.assertEqual(assessment.required_checks("What dividend per share did Microsoft declare?"), [])

    def test_revenue_alone_cannot_complete_another_entity_horizon_or_metric(self):
        _, bridge, ids, _ = self.run_tools("What was quarterly revenue?")
        envelopes = [
            (r["tool"], json.loads(r["output"]))
            for r in self.db.execute("SELECT * FROM receipts ORDER BY commit_seq")
        ]
        selection = {"status": "complete", "passage_ids": [ids[0]], "calculations": [], "gaps": []}
        for q in (
            "What was NVIDIA revenue?",
            "What was FY26 Q3 revenue?",
            "What is revenue per share?",
            "What was reported revenue in EUR?",
            "What was reported revenue in billions?",
            "What was revenue from 2024-01-29 to 2024-04-28?",
            "What was annual GAAP revenue?",
            "How much adjusted revenue did Microsoft report?",
            "What is Microsoft's current revenue?",
            "Compare revenue with customer retention.",
            "Did quarterly revenue decline year over year?",
        ):
            with self.subTest(question=q), self.assertRaises(ValueError):
                assessment.render({**bridge.context, "question": q}, selection, envelopes)

    def test_latest_saved_period_cannot_be_selected_from_an_older_quarter(self):
        lease, _, ids, _ = self.run_tools("What is the latest saved quarterly revenue?")
        old = self.render(
            lease, {"status": "complete", "passage_ids": [ids[1]], "calculations": [], "gaps": []}
        )
        with self.assertRaisesRegex(ValueError, "latest eligible"):
            research.submit(self.db, lease, old, {})
        latest = self.render(
            lease, {"status": "complete", "passage_ids": [ids[0]], "calculations": [], "gaps": []}
        )
        self.assertTrue(research.submit(self.db, lease, latest, {}))
        self.assertIn("Coverage is limited to saved observations", latest["conclusion"])
