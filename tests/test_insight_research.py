"""The on-demand investigation uses real workspaces, scoped tools and persisted receipts."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest

from stockinsight import db, evidence, executor, research, universe, workspace
from stockinsight.bridge import Bridge


SAMPLE = Path(__file__).resolve().parents[1] / "examples/stockinsight/watchlist.csv"
QUESTION = "NVIDIA has fallen. What do the reported results support, and should I buy?"
CUTOFF = "2024-08-28T20:30:00Z"


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "trial.sqlite3"
        self.db = db.connect(self.path, fixture=True)
        self.addCleanup(self.db.close)
        universe.import_snapshot(self.db, SAMPLE.read_bytes(), complete=True)
        self.listings = {i["ticker"]: i["id"] for i in universe.universe(self.db)["instruments"]}
        self.nvda = self.listings["NVDA"]

    def ask(self, cutoff=CUTOFF, **kwargs):
        return research.ask(self.db, self.nvda, QUESTION, cutoff=cutoff, **kwargs)

    def draft(self, lease):
        context = json.loads(research.authorized(self.db, lease)["context"])
        bridge = Bridge(self.db, lease)
        context["capabilities"] = bridge.catalog()
        return executor.execute(context["question"], context, bridge.call, fixture=True)

    def count(self, table):
        return self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_concurrent_claim_retry_expiration_and_fencing(self):
        job = self.ask()
        barrier = threading.Barrier(2, timeout=5)

        def claim(owner):
            with closing(db.connect(self.path)) as second:
                barrier.wait()
                try:
                    return owner, research.claim(second, job, owner, "dispatch-1")
                except ValueError:
                    return owner, None

        with ThreadPoolExecutor(2) as workers:
            claims = list(workers.map(claim, ("dispatcher-one", "dispatcher-two")))
        self.assertEqual(sum(lease is not None for _, lease in claims), 1)
        first_owner, first = next(item for item in claims if item[1])
        self.assertEqual(research.claim(self.db, job, first_owner, "dispatch-1"), first)
        self.assertEqual(self.count("runs"), 1)
        with self.assertRaises(ValueError):
            research.claim(self.db, job, first_owner, "different dispatch")
        with self.assertRaises(ValueError):
            research.renew(self.db, replace(first, token="unrelated-request"))
        # Model a stopped process whose deadline has passed, without sleeping.
        self.db.execute("UPDATE runs SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (first.run_id,))
        with self.assertRaises(ValueError):
            research.renew(self.db, first)
        second = research.claim(self.db, job, "recovered-owner", "dispatch-2")
        self.assertEqual(second.generation, first.generation + 1)
        self.assertNotEqual(second.token, first.token)
        with self.assertRaises(ValueError):
            Bridge(self.db, first)
        with self.assertRaises(ValueError):
            research.submit(self.db, first, {}, {})
        research.renew(self.db, second)
        self.assertEqual(self.count("briefs"), 0)

    def test_evidence_during_run_accepted_once_and_identical_after_restart(self):
        job = self.ask(request_key="same-click")
        self.assertEqual(job, self.ask(request_key="same-click"))
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.ask(cutoff="2024-08-28T20:40:00Z", request_key="same-click")
        lease = research.claim(self.db, job, "foreground", "dispatch")
        evidence.seed_fixture(self.db, self.nvda)
        draft = self.draft(lease)
        first = research.submit(self.db, lease, draft, draft.runtime)
        with closing(db.connect(self.path)) as reopened:
            self.assertEqual(research.submit(reopened, lease, draft, draft.runtime), first)
            changed = {**draft, "next_steps": ["Check the next quarterly filing."]}
            with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
                research.submit(reopened, lease, changed, draft.runtime)
            record = workspace.case_detail(reopened, workspace.cases(reopened)[0]["id"])
        brief = record["briefs"][0]
        self.assertEqual((record["revision"], record["jobs"][0]["state"]), (1, "partial"))
        self.assertEqual(
            (len(record["briefs"]), self.count("inbox"), self.count("brief_calculations")), (1, 1, 1)
        )
        self.assertIsNone(brief["reviewed_at"])
        self.assertEqual(brief["id"], first)
        self.assertEqual(set(brief["manifest"]["passages"]), set(brief["sources"]))
        self.assertEqual({g["capability"] for g in record["gaps"]}, {"historical_consensus", "price_context"})
        self.assertEqual(brief["comparisons"][0]["percent_change"], "20")
        self.assertTrue(any("shipment" in p["text"] for p in brief["sources"].values()))
        self.assertNotIn(lease.token, "\n".join(self.db.iterdump()))
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_competing_interpretation_keeps_draft_and_reviewed_revision(self):
        first = self.ask()
        case_id = workspace.cases(self.db)[0]["id"]
        stale = research.continuation(self.db, case_id)
        evidence.seed_fixture(self.db, self.nvda)
        accepted = research.run_job(self.db, first)
        research.review(self.db, accepted)
        lease = research.claim(self.db, stale, "new-worker", "stale-interpretation")
        draft = self.draft(lease)
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            research.submit(self.db, lease, draft, draft.runtime)
        row = self.db.execute(
            "SELECT * FROM reconciliation_drafts WHERE run_id=?", (lease.run_id,)
        ).fetchone()
        self.assertEqual((row["reason"], json.loads(row["body"])), ("revision_conflict", dict(draft)))
        self.assertEqual(
            self.db.execute("SELECT state FROM jobs WHERE id=?", (stale,)).fetchone()[0], "superseded"
        )
        record = workspace.case_detail(self.db, case_id)
        self.assertEqual((record["revision"], len(record["briefs"])), (1, 1))
        self.assertIsNotNone(record["briefs"][0]["reviewed_at"])
        self.assertEqual(record["briefs"][0]["id"], accepted)

    def test_cutoff_blocks_later_evidence_while_job_and_limitation_survive(self):
        evidence.seed_fixture(self.db, self.nvda)
        job = self.ask(cutoff="2024-08-28T20:29:59Z")
        self.assertIsNone(research.run_job(self.db, job))
        self.assertEqual(self.count("briefs"), 0)
        self.assertEqual(self.count("inbox"), 0)
        record = workspace.case_detail(self.db, workspace.cases(self.db)[0]["id"])
        self.assertEqual(record["jobs"][0]["state"], "blocked")
        self.assertIn("search_evidence", {g["capability"] for g in record["gaps"]})
        draft = self.db.execute("SELECT body FROM reconciliation_drafts").fetchone()
        self.assertEqual(json.loads(draft[0])["claims"], [])

    def test_unsupported_claim_gap_omission_and_cross_assignment_read(self):
        evidence.seed_fixture(self.db, self.nvda)
        job = self.ask()
        lease = research.claim(self.db, job, "worker", "request")
        bridge = Bridge(self.db, lease)
        reference = evidence.search(self.db, self.nvda, fixture=True)[0]["id"]
        with self.assertRaises(ValueError):
            bridge.call("get_evidence", {"id": reference})
        draft = self.draft(lease)
        inaccurate = deepcopy(dict(draft))
        inaccurate["claims"][0]["text"] = "Management quantified next year's demand forecast."
        with self.assertRaises(ValueError):
            research.submit(self.db, lease, inaccurate, draft.runtime)
        with self.assertRaises(ValueError):
            research.submit(self.db, lease, {**draft, "gaps": [], "status": "complete"}, draft.runtime)
        self.assertEqual((self.count("briefs"), self.count("claim_evidence"), self.count("inbox")), (0, 0, 0))
        repeated = bridge.call("price_context", {})
        self.assertIn(repeated["gap_id"], draft["gaps"])
        self.assertEqual(self.count("capability_gaps"), 2)
        self.assertGreaterEqual(
            self.db.execute(
                "SELECT count(*) FROM gap_attempts WHERE gap_id=?", (repeated["gap_id"],)
            ).fetchone()[0],
            2,
        )
        self.assertTrue(research.submit(self.db, lease, draft, draft.runtime))
        msft_job = research.ask(self.db, self.listings["MSFT"], "What evidence is available?")
        msft_lease = research.claim(self.db, msft_job, "worker", "second-case")
        msft = Bridge(self.db, msft_lease)
        self.assertEqual(msft.call("search_evidence", {})["evidence_ids"], [])
        with self.assertRaises(ValueError):
            msft.call("get_evidence", {"id": reference})

    def test_membership_removed_during_run_closes_scope_without_losing_history(self):
        job = self.ask()
        lease = research.claim(self.db, job, "worker", "active-at-start")
        evidence.seed_fixture(self.db, self.nvda)
        bridge = Bridge(self.db, lease)
        draft = self.draft(lease)
        replacement = universe.import_snapshot(self.db, b"", complete=True)
        universe.accept_candidate(self.db, replacement["id"])
        with self.assertRaises(ValueError):
            bridge.call("search_evidence", {})
        with self.assertRaises(ValueError):
            research.submit(self.db, lease, draft, draft.runtime)
        with self.assertRaises(ValueError):
            self.ask()
        self.assertEqual(self.count("cases"), 1)
        self.assertEqual(self.count("briefs"), 0)
        self.assertTrue(evidence.search(self.db, self.nvda, fixture=True))

    def test_price_premise_needs_receipted_price_coverage(self):
        evidence.seed_fixture(self.db, self.nvda)
        lease = research.claim(self.db, self.ask(), "worker", "request")
        bridge = Bridge(self.db, lease)
        available = bridge.call("search_evidence", {})
        detail = bridge.call("get_evidence", {"id": available["evidence_ids"][0]})["data"]
        draft = {
            "status": "complete",
            "conclusion": "The issuer release reports revenue.",
            "changes": [],
            "calculations": [],
            "gaps": [],
            "claims": [{"type": "issuer_statement", "text": detail["text"], "evidence_refs": [detail["id"]]}],
            "alternative_explanations": ["Market-wide moves could affect the share price."],
            "next_steps": ["Verify the price interval."],
        }
        with self.assertRaises(ValueError):
            research.submit(self.db, lease, draft, {"adapter": "contract fixture"})
        self.assertEqual((self.count("briefs"), self.count("inbox")), (0, 0))

    def test_headline_is_an_unverified_premise_and_primary_qualification_is_retained(self):
        evidence.seed_fixture(self.db, self.nvda)
        question = "A headline says revenue growth guarantees stronger full-year demand. Does the release support it?"
        job = research.ask(self.db, self.nvda, question, cutoff=CUTOFF)
        self.assertIsNotNone(research.run_job(self.db, job))
        case = self.db.execute("SELECT case_id FROM jobs WHERE id=?", (job,)).fetchone()[0]
        brief = workspace.case_detail(self.db, case)["briefs"][0]
        self.assertIn("qualification", brief["body"]["conclusion"])
        qualification = next(c for c in brief["body"]["claims"] if "did not quantify" in c["text"])
        self.assertEqual(qualification["text"], brief["sources"][qualification["evidence_refs"][0]]["text"])
        self.assertTrue(brief["body"]["alternative_explanations"])
        self.assertNotIn("guarantees stronger", brief["body"]["conclusion"])


if __name__ == "__main__":
    unittest.main()
