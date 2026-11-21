"""Non-fixture desk path with controlled public source packets and no hosted calls."""

import json
import os
import unittest
from unittest.mock import patch

from stockinsight import executor, local_model, providers, research, workspace
from tests.test_insight_evidence import sec_packet
from tests.test_insight_evidence import workspace as open_workspace


class TrialResearchTests(unittest.TestCase):
    def setUp(self):
        self.db, self.listings = open_workspace()
        self.addCleanup(self.db.close)
        self.enterContext(
            patch.dict(os.environ, {"STOCKINSIGHT_SEC_CONTACT": "unit@example.org"})
        )
        self.enterContext(
            patch.object(
                executor, "_post", side_effect=AssertionError("Unexpected hosted call")
            )
        )

    def investigate(self, question, *, engine="local", ticker="MSFT"):
        job = research.ask(self.db, self.listings[ticker]["id"], question)
        research.run_job(self.db, job, engine=engine)
        case = self.db.execute(
            "SELECT case_id FROM jobs WHERE id=?", (job,)
        ).fetchone()[0]
        return workspace.case_detail(self.db, case)

    def test_planner_uses_scoped_source_then_reuses_dated_observations_for_a_partial(
        self,
    ):
        packet = {**sec_packet(), "cik": 789019}
        with patch.object(
            providers, "_fetch", return_value=json.dumps(packet).encode()
        ) as fetch:
            with patch.object(
                local_model,
                "choose",
                return_value=(
                    "issuer_disclosure",
                    {"actual_model": "test-selector", "mode": "scripted_test"},
                ),
            ):
                case = self.investigate(
                    "Compare Microsoft's reported quarterly revenue.", engine="device"
                )
            brief = case["briefs"][0]
            self.assertEqual(brief["body"]["status"], "complete")
            self.assertEqual(brief["comparisons"][0]["percent_change"], "20")
            self.assertEqual(
                brief["manifest"]["runtime"]["research_plan"], "issuer_disclosure"
            )
            self.assertEqual(brief["receipts"][0]["tool"], "capture_public")
            self.assertTrue(
                all(
                    p["instrument_id"] == case["instrument_id"]
                    for p in brief["sources"].values()
                )
            )
            partial = self.investigate(
                "Did Microsoft shares fall after the revenue report?"
            )
            self.assertEqual(partial["briefs"][0]["body"]["status"], "partial")
            self.assertTrue(
                any(g["capability"] == "price_context" for g in partial["gaps"])
            )
            self.assertEqual(fetch.call_count, 1)

    def test_unavailable_source_leaves_a_visible_job_and_scoped_gaps(self):
        with patch.object(
            providers,
            "_fetch",
            side_effect=providers.SourceError("unavailable", "Offline"),
        ):
            case = self.investigate("Compare quarterly revenue.")
        self.assertEqual(case["jobs"][0]["state"], "blocked")
        self.assertFalse(case["briefs"])
        self.assertTrue(all(g["lifecycle"] == "open" for g in case["gaps"]))
        self.assertTrue(
            any(g["capability"] == "capture_public (sec)" for g in case["gaps"])
        )
