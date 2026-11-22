import json
import unittest

from stockinsight import db, methods, price_research, research, universe, workspace
from stockinsight.bridge import Bridge

QUESTION = "How did NVDA’s closing price change from 2024-04-01 to 2024-04-15?"


class DatedClosingPriceCases(unittest.TestCase):
    def setUp(self):
        self.db = db.connect(":memory:")
        self.addCleanup(self.db.close)
        universe.import_snapshot(
            self.db,
            b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\n",
            complete=True,
        )
        self.listing = next(i for i in universe.universe(self.db)["instruments"] if i["ticker"] == "NVDA")

    def quote(self, day, price, publisher="Market file"):
        raw = (
            ",".join(methods.PRICE_FIELDS)
            + f"\nNVDA,NASDAQ,{day},{day}T16:00:00-04:00,USD,{price},unadjusted,,15"
        )
        return methods.import_prices(self.db, self.listing["id"], publisher, "regular", raw)[0]

    def case(self, question=QUESTION, cutoff=None):
        job = research.ask(self.db, self.listing["id"], question, cutoff=cutoff)
        bid = research.run_job(self.db, job, engine="local")
        case_id = self.db.execute("SELECT case_id FROM jobs WHERE id=?", (job,)).fetchone()[0]
        return case_id, bid

    def test_missing_window_one_endpoint_then_complete_with_reproducible_run_receipts(self):
        case, bid = self.case()
        self.assertIsNone(bid)
        self.assertEqual(workspace.case_detail(self.db, case)["jobs"][0]["state"], "blocked")
        a = self.quote("2024-04-01", "100")
        first = research.run_job(self.db, research.continuation(self.db, case), engine="local")
        self.assertIsNotNone(first)
        partial = workspace.case_detail(self.db, case)["briefs"][0]
        self.assertEqual(partial["body"]["status"], "partial")
        self.assertEqual(list(partial["sources"]), [a])
        self.assertIn("2024-04-15", partial["body"]["conclusion"])
        b = self.quote("2024-04-15", "110")
        research.run_job(self.db, research.continuation(self.db, case), engine="local")
        detail = workspace.case_detail(self.db, case)
        result = detail["briefs"][0]
        self.assertEqual(result["method"], price_research.METHOD)
        self.assertEqual(result["body"]["status"], "complete")
        self.assertIn("10%", result["body"]["conclusion"])
        self.assertIn("operator-supplied", result["body"]["conclusion"])
        self.assertEqual({a, b}, set(result["sources"]))
        self.assertEqual(result["comparisons"][0]["session_window"], ["2024-04-01", "2024-04-15"])
        self.assertEqual(
            [r["tool"] for r in result["receipts"]], ["price_context", "get_evidence", "get_evidence"]
        )
        self.assertEqual(len(result["manifest"]["versions"]), 2)
        self.assertEqual(
            {r["kind"] for r in result["manifest"]["assertions"]},
            {"market_close_observation", "market_close_calculation"},
        )
        self.assertEqual(detail["gaps"][0]["lifecycle"], "resolved")
        self.assertEqual(detail["briefs"][1]["body"], partial["body"])

    def test_cutoff_causal_foreign_and_wrong_basis_cannot_claim_complete(self):
        self.quote("2024-04-01", "100")
        self.quote("2024-04-15", "110")
        _, frozen = self.case(cutoff="2024-04-16T12:00:00Z")
        self.assertIsNone(frozen)
        for phrase in [
            "Why did NVDA’s closing price move",
            "What was the split-adjusted price change",
            "What was the adjusted price change",
            "What was the total return",
            "What was NVDA’s closing price and should I buy it",
            "What was the price in EUR",
            "What was NVDA’s closing price and did its stock change listing",
            "What was the price in €",
            "What was MSFT’s stock price",
            "Did an unlisted competitor’s price outperform the stock",
        ]:
            case, b = self.case(phrase + " from 2024-04-01 to 2024-04-15?")
            if b:
                r = workspace.case_detail(self.db, case)["briefs"][0]
                self.assertEqual(r["body"]["status"], "partial", phrase)
                self.assertTrue(r["body"]["gaps"])
            else:
                self.assertEqual(workspace.case_detail(self.db, case)["jobs"][0]["state"], "blocked")
        self.assertFalse(
            price_research.accepts(
                "What was the revenue per share of this stock from 2024-04-01 to 2024-04-15?"
            )
        )

    def test_conflicting_source_after_calculation_is_rejected_at_the_freeze_boundary(self):
        self.quote("2024-04-01", "100")
        self.quote("2024-04-15", "110")
        job = research.ask(self.db, self.listing["id"], QUESTION)
        lease = research.claim(self.db, job, "offline-worker", "dispatch")
        bridge = Bridge(self.db, lease)
        context = json.loads(research.authorized(self.db, lease)["context"])
        body = price_research.execute(context, bridge.call, {})
        self.quote("2024-04-15", "120", "Second publisher")
        with self.assertRaisesRegex(ValueError, "changed before submission"):
            research.submit(self.db, lease, body, {})
        self.assertEqual(self.db.execute("SELECT count(*) FROM briefs").fetchone()[0], 0)
