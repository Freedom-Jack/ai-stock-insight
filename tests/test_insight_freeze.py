"""Current and fixed-cutoff interpretations across corrections of one SEC series."""

import json
import unittest

from stockinsight import assessment, db, evidence, research, workspace
from stockinsight.bridge import Bridge
from tests.test_insight_evidence import sec_packet
from tests.test_insight_evidence import workspace as open_workspace


class CorrectionAtFreezeTests(unittest.TestCase):
    def setUp(self):
        self.conn, items = open_workspace()
        self.addCleanup(self.conn.close)
        self.item = items["MSFT"]
        self.first = "2024-08-28T21:00:00Z"
        self.corrected = "2024-09-03T21:00:00Z"
        self.edition(120, self.first)

    def edition(self, value, received, *, stream="revenue", move_cell=False, notes=()):
        packet = sec_packet()
        packet["cik"] = int(self.item["cik"])
        for row in packet["units"]["USD"]:
            row["accn"] = "0000789019-24-000001"
        packet["units"]["USD"][1]["val"] = value
        if move_cell:
            packet["units"]["USD"].reverse()
        if notes:
            packet["notes"] = dict(notes)
        raw = json.dumps(packet).encode()
        rows = evidence._sec_rows(raw, received, self.item["cik"])
        rows.extend((locator, text, received, None) for locator, text in notes)
        staged = evidence._stage(self.conn, "full", raw)
        with db.write(self.conn) as seq:
            return evidence._save(
                self.conn,
                seq,
                self.item["id"],
                "sec",
                "test:" + stream,
                "SEC test series",
                staged,
                rows,
                received,
                published=None,
                precision="filing dates",
                retention="full",
            )

    def claim(self, question="Compare the reported quarterly revenue.", *, cutoff=None):
        job = research.ask(self.conn, self.item["id"], question, cutoff=cutoff)
        lease = research.claim(self.conn, job, "test-worker", "initial")
        return lease, Bridge(self.conn, lease)

    def selection(self, lease, bridge, ids, *, calculations=(), gaps=()):
        calls = [
            (r[0], json.loads(r[1]))
            for r in self.conn.execute(
                "SELECT tool,output FROM receipts WHERE run_id=? ORDER BY commit_seq", (lease.run_id,)
            )
        ]
        return assessment.render(
            bridge.context,
            {
                "status": "partial" if gaps else "complete",
                "passage_ids": ids,
                "calculations": list(calculations),
                "gaps": list(gaps),
            },
            calls,
        )[0]

    def draft(self, lease, bridge, *, include_context=True):
        read = bridge.call("search_evidence", {})["data"]["passages"]
        chosen = [p for p in read if p["source_url"] == "test:revenue"]
        pair = [p["id"] for p in chosen if p["financial"]]
        ids = [p["id"] for p in chosen if p["financial"] or include_context]
        for ref in ids:
            bridge.call("get_evidence", {"id": ref})
        calc = bridge.call(
            "compare_financials", {"kind": "period_trend", "current": pair[0], "baseline": pair[1]}
        )
        return self.selection(lease, bridge, ids, calculations=[calc["receipt_id"]])

    def test_same_amount_amended_with_source_context_requires_reread_and_disclosure(self):
        lease, bridge = self.claim()
        old = self.draft(lease, bridge)
        caveat = "The consolidation of the acquired subsidiary explains the reported increase."
        second = "Comparative figures exclude the acquired business."
        self.edition(120, self.corrected, notes=[("/qualification", caveat), ("/notes/3", second)])
        with self.assertRaisesRegex(ValueError, "superseded|source context"):
            research.submit(self.conn, lease, old, {})
        new = self.draft(lease, bridge)
        missing = self.selection(
            lease,
            bridge,
            [c["evidence_refs"][0] for c in new["claims"] if c["text"] != second],
            calculations=new["calculations"],
        )
        with self.assertRaisesRegex(ValueError, "source context|qualification"):
            research.submit(self.conn, lease, missing, {})
        accepted = research.submit(self.conn, lease, new, {})
        manifest = json.loads(
            self.conn.execute("SELECT manifest FROM briefs WHERE id=?", (accepted,)).fetchone()[0]
        )
        notes = {c["evidence_refs"][0] for c in new["claims"] if c["text"] in (caveat, second)}
        for a in manifest["assertions"]:
            if a["kind"] == "observation":
                self.assertEqual(set(a["context_passage_ids"]), notes)
        self.assertIn(caveat, new["conclusion"])
        self.assertIn(second, new["conclusion"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM inbox").fetchone()[0], 1)
        past, reader = self.claim(cutoff="2024-09-01T00:00:00Z")
        historical = self.draft(past, reader)
        self.assertTrue(research.submit(self.conn, past, historical, {}))
        self.assertNotIn(caveat, historical["conclusion"])

    def test_partial_latest_and_last_quarter_use_the_eligible_saved_horizon(self):
        question = "What is the latest saved quarterly revenue and price?"
        lease, bridge = self.claim(question)
        found = bridge.call("search_evidence", {})["evidence_ids"]
        for ref in found:
            bridge.call("get_evidence", {"id": ref})
        price = bridge.call("price_context", {})["gap_id"]
        with self.assertRaisesRegex(ValueError, "latest eligible"):
            research.submit(self.conn, lease, self.selection(lease, bridge, [found[1]], gaps=[price]), {})
        latest = self.selection(lease, bridge, [found[0]], gaps=[price])
        self.assertTrue(research.submit(self.conn, lease, latest, {}))
        self.assertIn("120", latest["conclusion"])
        self.assertIn("saved", latest["conclusion"])

    def test_last_quarter_has_no_global_freshness_proof(self):
        lease, bridge = self.claim("What was revenue last quarter?")
        found = bridge.call("search_evidence", {})["evidence_ids"]
        for ref in found:
            bridge.call("get_evidence", {"id": ref})
            with self.assertRaisesRegex(ValueError, "coverage|freshness"):
                research.submit(self.conn, lease, self.selection(lease, bridge, [ref]), {})
        for q in (
            "What was revenue in the previous fiscal quarter?",
            "Compare current revenue with saved revenue.",
        ):
            self.assertEqual(assessment._latest_saved(q), (True, False))
        self.assertEqual(
            assessment._latest_saved("What is the most recent revenue in the workspace?"), (True, True)
        )

    def test_historical_clause_does_not_narrow_a_separate_latest_saved_request(self):
        lease, bridge = self.claim(
            "What was the latest saved revenue and revenue from 2024-01-29 to 2024-04-28?"
        )
        newer, older = bridge.call("search_evidence", {})["evidence_ids"]
        for ref in (newer, older):
            bridge.call("get_evidence", {"id": ref})
        with self.assertRaisesRegex(ValueError, "latest eligible"):
            research.submit(self.conn, lease, self.selection(lease, bridge, [older]), {})
        self.assertTrue(research.submit(self.conn, lease, self.selection(lease, bridge, [older, newer]), {}))
        relative, tool = self.claim(
            "What was revenue in the prior quarter and revenue from 2024-01-29 to 2024-04-28?"
        )
        tool.call("search_evidence", {})
        tool.call("get_evidence", {"id": older})
        with self.assertRaisesRegex(ValueError, "coverage|freshness"):
            research.submit(self.conn, relative, self.selection(relative, tool, [older]), {})

    def test_current_must_reconcile_pre_freeze_correction_then_accept_reread(self):
        lease, bridge = self.claim()
        old = self.draft(lease, bridge)
        self.edition(95, self.corrected)
        with self.assertRaisesRegex(ValueError, "superseded"):
            research.submit(self.conn, lease, old, {})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM inbox").fetchone()[0], 0)
        current = self.draft(lease, bridge)
        result = research.submit(self.conn, lease, current, {})
        self.assertTrue(result)
        ref = old["claims"][0]["evidence_refs"][0]
        self.assertEqual(evidence.get(self.conn, self.item["id"], ref)["financial"]["value"], "120")
        self.assertNotEqual(current["calculations"], old["calculations"])
        brief = workspace.case_detail(self.conn, bridge.context["case_id"])["briefs"][0]
        self.assertEqual([c["current_value"] for c in brief["comparisons"]], ["95"])

    def test_cutoff_excludes_later_correction_and_preserves_accepted_record(self):
        lease, bridge = self.claim(cutoff="2024-08-30T00:00:00Z")
        body = self.draft(lease, bridge)
        self.edition(95, self.corrected)
        accepted = research.submit(self.conn, lease, body, {})
        research.review(self.conn, accepted)
        self.edition(92, "2024-09-10T12:00:00Z")
        old = workspace.case_detail(self.conn, bridge.context["case_id"])["briefs"][0]
        self.assertEqual(old["id"], accepted)
        self.assertIsNotNone(old["reviewed_at"])
        self.assertEqual(old["comparisons"][0]["current_value"], "120")
        latest, tool = self.claim()
        self.assertTrue(research.submit(self.conn, latest, self.draft(latest, tool), {}))

    def test_unrelated_source_and_identical_fact_in_new_edition_are_eligible(self):
        lease, bridge = self.claim()
        body = self.draft(lease, bridge)
        self.edition(700, self.corrected, stream="other-series")
        self.edition(120, self.corrected, move_cell=True)
        self.assertTrue(research.submit(self.conn, lease, body, {}))
