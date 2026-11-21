"""Exercise question requirements through the two actual investigation paths."""

import json
import os
import unittest
from unittest.mock import patch

from stockinsight import assessment, db, evidence, executor, research
from stockinsight.bridge import Bridge
from tests.test_insight_evidence import workspace
from tests.test_insight_executor import SETTINGS, reply


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.conn, listings = workspace()
        self.addCleanup(self.conn.close)
        self.msft = listings["MSFT"]

    def fact(self, metric, quarter, value, unit, *, share_basis="total"):
        dates = {
            "Q1 FY25": ("2024-07-01", "2024-09-30"),
            "Q2 FY25": ("2024-10-01", "2024-12-31"),
            "Q2 FY26": ("2025-10-01", "2025-12-31"),
        }
        label = f"MSFT {quarter} {metric} {value} {unit}."
        observation = evidence.revenue("CIK0000789019", quarter, *dates[quarter], value, unit)
        observation.update(metric=metric, share_basis=share_basis)
        staged = evidence._stage(self.conn, "full", label.encode())
        with db.write(self.conn) as seq:
            evidence._save(
                self.conn,
                seq,
                self.msft["id"],
                "test",
                f"test:{metric}/{quarter}",
                label,
                staged,
                [("row", label, db.now(), observation)],
                db.now(),
                published=None,
                precision="unknown",
                retention="full",
            )

    def investigate(self, question, *, compare=False, checks=(), missing=(), dishonest_complete=False):
        """Only the Responses transport is scripted. IDs come from the service replies."""
        tools = [("search_evidence", {})]
        ids, calculations, gaps = [], [], []
        seen = []

        def model(encoded, *_):
            responses = [
                item for item in json.loads(encoded)["input"] if item.get("type") == "function_call_output"
            ]
            n = len(responses)
            if n:
                name, _ = tools[n - 1]
                result = json.loads(responses[-1]["output"])
                seen.append(name)
                gaps[:] = result["outstanding_gap_ids"]
                if name == "search_evidence":
                    rows = result["data"]["passages"]
                    ids.extend(row["id"] for row in rows)
                    tools.extend(("get_evidence", {"id": pid}) for pid in ids)
                    if compare:
                        by_period = {row["financial"]["period_label"]: row["id"] for row in rows}
                        tools.append(
                            (
                                "compare_financials",
                                {
                                    "kind": "period_trend",
                                    "current": by_period["Q2 FY25"],
                                    "baseline": by_period["Q1 FY25"],
                                },
                            )
                        )
                    tools.extend((name, {}) for name in checks)
                    tools.extend(
                        ("record_gap", {"metric": m, "period": p, "attempt_receipt_id": result["receipt_id"]})
                        for m, p in missing
                    )
                if name == "compare_financials":
                    calculations.append(result["receipt_id"])
            if n < len(tools):
                return reply(*tools[n], n=n)
            return reply(
                "submit_brief",
                {
                    "status": "complete" if dishonest_complete or not gaps else "partial",
                    "passage_ids": ids,
                    "calculations": calculations,
                    "gaps": gaps,
                },
                n=n,
            )

        job = research.ask(self.conn, self.msft["id"], question)
        with (
            patch.dict(os.environ, {**SETTINGS, "STOCKINSIGHT_MAX_REQUESTS": "12"}, clear=True),
            patch.object(executor, "_post", model),
        ):
            accepted = research.run_job(self.conn, job)
        body = json.loads(self.conn.execute("SELECT body FROM briefs WHERE id=?", (accepted,)).fetchone()[0])
        return body, seen

    def test_market_event_needs_receipt_in_both_modes_while_accounting_decline_completes(self):
        q = "Did the shares fall after the revenue release?"
        self.fact("revenue", "Q1 FY25", "80", "USD")
        self.fact("revenue", "Q2 FY25", "120", "USD")
        with self.assertRaisesRegex(ValueError, "required price"):
            self.investigate(q, compare=True)
        body, seen = self.investigate(q, compare=True, checks=["price_context"])
        self.assertEqual((body["status"], len(body["gaps"])), ("partial", 1))
        self.assertEqual(seen.count("price_context"), 1)
        self.assertIn("40 USD (50%)", body["conclusion"])
        self.assertIn("unverified", body["conclusion"])
        perform = Bridge._perform

        def empty_price(bridge, name, args):
            if name == "price_context":
                return "ok", {"observations": []}, []
            return perform(bridge, name, args)

        with (
            patch.object(Bridge, "_perform", empty_price),
            self.assertRaisesRegex(ValueError, "price_context"),
        ):
            self.investigate(q, compare=True, checks=["price_context"])
        accounting = "Did quarterly revenue fall after the release?"
        with self.assertRaisesRegex(ValueError, "requested comparison"):
            self.investigate(accounting)
        body, seen = self.investigate(accounting, compare=True)
        self.assertEqual((body["status"], body["gaps"]), ("complete", []))
        self.assertNotIn("price_context", seen)
        fronted, fronted_checks = self.investigate(
            "After the filing, what quarterly revenue did Microsoft report?"
        )
        self.assertEqual(fronted["status"], "complete")
        self.assertNotIn("price_context", fronted_checks)
        with self.subTest(mode="fixture"):
            conn, listings = workspace(fixture=True)
            self.addCleanup(conn.close)
            nvda = listings["NVDA"]["id"]
            evidence.seed_fixture(conn, nvda)
            for question, expected in [(q, "partial"), (accounting, "complete")]:
                job = research.ask(conn, nvda, question)
                brief = research.run_job(conn, job)
                row = conn.execute("SELECT body,run_id FROM briefs WHERE id=?", (brief,)).fetchone()
                result = json.loads(row["body"])
                receipts = [
                    r[0] for r in conn.execute("SELECT tool FROM receipts WHERE run_id=?", (row["run_id"],))
                ]
                self.assertEqual(result["status"], expected)
                self.assertIn("(20%)", result["conclusion"])
                self.assertEqual("price_context" in receipts, expected == "partial")
        for subject in (
            "Did shares underperform after the revenue release?",
            "Did MSFT fall after the revenue release?",
            "How did Microsoft trade after reporting revenue?",
            "Did the stock recover following the revenue release?",
        ):
            self.assertIn("price_context", assessment.required_checks(subject))
            partial, _ = self.investigate(subject, compare=True, checks=["price_context"])
            self.assertEqual(partial["status"], "partial")
            self.assertIn("40 USD (50%)", partial["conclusion"])
        self.assertEqual(assessment.required_checks("Did MSFT revenue fall after the release?"), [])
        self.assertEqual(assessment.required_checks("Did earnings per share fall after the release?"), [])

    def test_each_clause_binds_its_own_year_and_the_prior_year_is_only_context(self):
        self.fact("revenue", "Q1 FY25", "80", "USD")
        self.fact("revenue", "Q2 FY25", "120", "USD")
        questions = [
            "What was Q1 revenue in FY25 and Q2 revenue in FY26?",
            "What was FY26 Q2 revenue and FY25 Q1 revenue?",
            "What was revenue in Q1 FY25 and in Q2 FY26?",
        ]
        self.assertEqual(
            assessment.objective("What was Q1 revenue in FY25 and FY26?").requirements,
            (("revenue", "Q1 FY25"), ("revenue", "Q1 FY26")),
        )
        for q in questions:
            with self.subTest(question=q):
                self.assertEqual(
                    set(assessment.objective(q).requirements),
                    {("revenue", "Q1 FY25"), ("revenue", "Q2 FY26")},
                )
                with self.assertRaisesRegex(ValueError, "Q2 FY26"):
                    self.investigate(q)
                body, _ = self.investigate(q, missing=[("revenue", "Q2 FY26")])
                self.assertEqual(body["status"], "partial")
                self.assertIn("Q1 FY25", body["conclusion"])
                self.assertIn("unavailable for Q2 FY26", body["conclusion"])
                self.assertNotIn("120 USD", body["conclusion"])
        self.fact("revenue", "Q2 FY26", "135", "USD")
        body, _ = self.investigate(questions[0])
        self.assertEqual(body["status"], "complete")
        self.assertIn("135 USD for Q2 FY26", body["conclusion"])
        self.assertNotIn("120 USD", body["conclusion"])
        conn, listings = workspace(fixture=True)
        self.addCleanup(conn.close)
        nvda = listings["NVDA"]["id"]
        evidence.seed_fixture(conn, nvda)
        job = research.ask(conn, nvda, questions[0])
        record = research.run_job(conn, job)
        partial = json.loads(conn.execute("SELECT body FROM briefs WHERE id=?", (record,)).fetchone()[0])
        self.assertEqual(partial["status"], "partial")
        self.assertIn("unavailable for Q2 FY26", partial["conclusion"])

    def test_total_and_per_share_dividends_need_distinct_evidence_and_dimensions(self):
        self.fact("dividend_per_share", "Q2 FY26", "0.61", "USD per share", share_basis="common share")
        total = "What were total dividends in Q2 FY26?"
        with self.assertRaisesRegex(ValueError, "total_dividends"):
            self.investigate(total)
        partial, _ = self.investigate(total, missing=[("total_dividends", "Q2 FY26")])
        self.assertEqual(partial["status"], "partial")
        self.assertIn("total dividends is unavailable", partial["conclusion"])
        per_share, _ = self.investigate("What were dividends per share in Q2 FY26?")
        self.assertEqual(per_share["status"], "complete")
        self.assertIn("0.61 USD per share", per_share["conclusion"])
        shared_noun = (
            "What were total and per share dividends in Q2 FY26?",
            "What were dividends per share and in total for Q2 FY26?",
        )
        for question in shared_noun:
            with self.subTest(question=question):
                with self.assertRaisesRegex(ValueError, "total_dividends"):
                    self.investigate(question)
                partial, _ = self.investigate(question, missing=[("total_dividends", "Q2 FY26")])
                self.assertEqual(partial["status"], "partial")
                self.assertIn("0.61 USD per share", partial["conclusion"])
                self.assertIn("total dividends is unavailable for Q2 FY26", partial["conclusion"])
        self.fact("total_dividends", "Q1 FY25", "12", "USD million")
        mixed = "What were total dividends in USD million in Q1 FY25 and dividends per share in Q2 FY26?"
        request = assessment.objective(mixed)
        self.assertEqual(
            request.requirements, (("total_dividends", "Q1 FY25"), ("dividend_per_share", "Q2 FY26"))
        )
        self.assertEqual(request.dimensions_for("total_dividends", "Q1 FY25").unit_scale, "million")
        self.assertEqual(request.dimensions_for("dividend_per_share", "Q2 FY26").unit_scale, "")
        body, _ = self.investigate(mixed)
        self.assertEqual(body["status"], "complete")
        self.assertIn("12 USD million for Q1 FY25", body["conclusion"])
        self.assertIn("0.61 USD per share for Q2 FY26", body["conclusion"])
        self.fact("total_dividends", "Q2 FY26", "15", "USD million")
        for question in shared_noun:
            both, _ = self.investigate(question)
            self.assertEqual(both["status"], "complete")
            self.assertIn("15 USD million for Q2 FY26", both["conclusion"])
            self.assertIn("0.61 USD per share for Q2 FY26", both["conclusion"])
