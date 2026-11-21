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

    def edition(self, value, received, *, stream="revenue", move_cell=False):
        packet = sec_packet()
        packet["cik"] = int(self.item["cik"])
        for row in packet["units"]["USD"]:
            row["accn"] = "0000789019-24-000001"
        packet["units"]["USD"][1]["val"] = value
        if move_cell:
            packet["units"]["USD"].reverse()
        raw = json.dumps(packet).encode()
        rows = evidence._sec_rows(raw, received, self.item["cik"])
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

    def claim(self, *, cutoff=None):
        job = research.ask(
            self.conn, self.item["id"], "Compare the reported quarterly revenue.", cutoff=cutoff
        )
        lease = research.claim(self.conn, job, "test-worker", "initial")
        return lease, Bridge(self.conn, lease)

    def draft(self, lease, bridge):
        read = bridge.call("search_evidence", {})["data"]["passages"]
        chosen = [p for p in read if p["source_url"] == "test:revenue"]
        pair = [p["id"] for p in chosen]
        for ref in pair:
            bridge.call("get_evidence", {"id": ref})
        calc = bridge.call(
            "compare_financials", {"kind": "period_trend", "current": pair[0], "baseline": pair[1]}
        )
        calls = [
            (r[0], json.loads(r[1]))
            for r in self.conn.execute(
                "SELECT tool,output FROM receipts WHERE run_id=? ORDER BY commit_seq", (lease.run_id,)
            )
        ]
        body, _ = assessment.render(
            bridge.context,
            {"status": "complete", "passage_ids": pair, "calculations": [calc["receipt_id"]], "gaps": []},
            calls,
        )
        return body

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
