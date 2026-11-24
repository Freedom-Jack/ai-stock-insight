import json
import tempfile
import unittest
from pathlib import Path

from stockinsight import db, evidence, memory, research, universe, workspace


class ResearchContinuityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = db.connect(Path(folder.name) / "research.sqlite3", fixture=True)
        self.addCleanup(self.db.close)
        universe.import_snapshot(
            self.db,
            b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD",
            complete=True,
        )
        self.items = {i["ticker"]: i["id"] for i in universe.universe(self.db)["instruments"]}
        self.instrument = self.items["NVDA"]
        self.sources = evidence.seed_fixture(self.db, self.instrument)
        self.question = "Compare NVIDIA GAAP revenue in Q2 FY25 and Q1 FY25."

    def initial(self, cutoff=None):
        job = research.ask(self.db, self.instrument, self.question, cutoff=cutoff)
        brief = research.run_job(self.db, job)
        case = self.db.execute("SELECT case_id FROM jobs WHERE id=?", (job,)).fetchone()[0]
        return case, brief

    def test_portable_case_and_attributed_context_survive_fresh_execution(self):
        case, brief = self.initial()
        archived = memory.export_case(self.db, case)
        raw = json.dumps(archived)
        rid = memory.import_record(self.db, self.instrument, raw, "case", "")
        self.assertEqual(rid, memory.import_record(self.db, self.instrument, raw, "case", ""))
        self.assertTrue(memory.get_import(self.db, rid)["payload"]["case"]["revisions"][0]["sources"])
        for listing, invalid in (
            (self.items["MSFT"], raw),
            (self.instrument, raw.replace("Compare NVIDIA", "Changed NVIDIA")),
        ):
            with self.assertRaises(ValueError):
                memory.import_record(self.db, listing, invalid, "case", "")
        selected = [
            {"role": "user", "content": "Watch quarterly shipment timing."},
            {"role": "assistant", "content": "Hypothesis: full-year sales may triple."},
        ]
        chat = memory.import_record(
            self.db,
            self.instrument,
            json.dumps(selected),
            "conversation",
            "Earlier reasoning",
        )
        job = research.continuation(self.db, case)
        revision = research.run_job(self.db, job)
        row = self.db.execute("SELECT context FROM runs WHERE job_id=?", (job,)).fetchone()
        retrieved = json.loads(row[0])["prior_research"]["attributed_context"]
        self.assertEqual(
            [(m["author"], m["candidate"]) for m in retrieved if m["import_id"] == chat],
            [(m["role"], m["content"]) for m in selected],
        )
        self.assertNotIn(
            "triple",
            self.db.execute("SELECT body FROM briefs WHERE id=?", (revision,)).fetchone()[0],
        )
        self.assertFalse(memory.recall(self.db, self.items["MSFT"])["imports"])
        _, historical = self.initial(cutoff="2024-08-29T12:00:00Z")
        manifest = json.loads(
            self.db.execute("SELECT manifest FROM briefs WHERE id=?", (historical,)).fetchone()[0]
        )
        self.assertFalse(manifest["context"]["prior_research"]["attributed_context"])
        with self.assertRaises(ValueError):
            memory.import_record(
                self.db,
                self.instrument,
                '[{"role":"user","content":"password=long-secret"}]',
                "conversation",
                "Wrong",
            )

    def test_contrary_transcript_revises_reviewed_case_and_notifies_once(self):
        case, brief = self.initial()
        research.review(self.db, brief)
        original = workspace.case_detail(self.db, case)["briefs"][0]
        text = "Management attributed the shipment rise to a timing shift between quarters."
        stamp = "2026-11-15T18:00:00Z"
        with db.write(self.db) as seq:
            doc = evidence._save(
                self.db,
                seq,
                self.instrument,
                "synthetic-transcript",
                "fixture:transcript",
                "Synthetic transcript",
                evidence._stage(self.db, "full", text.encode()),
                [("answer 7", text, stamp, None)],
                stamp,
                published=stamp,
                precision="instant",
                retention="full",
                fixture=True,
            )
        ref = self.db.execute("SELECT id FROM evidence_passages WHERE document_id=?", (doc,)).fetchone()[0]
        idx = next(i for i, c in enumerate(original["body"]["claims"]) if c["evidence_refs"])
        for _ in range(2):
            memory.link_update(
                self.db,
                brief,
                idx,
                ref,
                "counterevidence",
                "Changes the demand interpretation",
            )
        self.assertIsNotNone(memory.tick(self.db))
        self.assertIsNone(memory.tick(self.db))
        detail = workspace.case_detail(self.db, case)
        self.assertEqual(len(detail["briefs"]), 2)
        self.assertEqual(detail["briefs"][1]["manifest_hash"], original["manifest_hash"])
        self.assertEqual(detail["briefs"][1]["reviewed_at"], original["reviewed_at"])
        self.assertIsNone(detail["briefs"][0]["reviewed_at"])
        self.assertIn(text, str(detail["briefs"][0]["body"]["claims"]))
        self.assertIn("operator", detail["briefs"][0]["body"]["conclusion"])
        row = self.db.execute("SELECT state,old_ref,new_ref,new_brief FROM case_updates").fetchone()
        self.assertEqual(
            (row["state"], row["new_ref"], row["new_brief"]),
            ("revised", ref, detail["briefs"][0]["id"]),
        )
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM delivery_notices WHERE title='Research correction'"
            ).fetchone()[0],
            1,
        )

    def test_new_edition_revisits_matching_current_case_and_preserves_fixed_cutoff(
        self,
    ):
        case, brief = self.initial()
        historical, old = self.initial(cutoff="2024-08-29T12:00:00Z")
        source = self.sources[0]
        edited = []
        published = "2026-11-12T00:00:00Z"
        for p in self.sources:
            fact = p["financial"]
            text = p["text"]
            if fact and fact["period_label"] == "Q2 FY25":
                text = "Revised synthetic quarter: 125 USD million."
                fact = {**fact, "value": "125"}
            edited.append((p["locator"], text, published, fact))
        with db.write(self.db) as seq:
            evidence._save(
                self.db,
                seq,
                self.instrument,
                source["origin"],
                source["source_url"],
                source["title"],
                evidence._stage(self.db, "full", json.dumps(edited).encode()),
                edited,
                published,
                published=published,
                precision="instant",
                retention="full",
                fixture=True,
            )
        memory.tick(self.db)
        r = workspace.case_detail(self.db, case)
        self.assertEqual(len(r["briefs"]), 2)
        self.assertEqual(r["briefs"][0]["comparisons"][0]["current_value"], "125")
        self.assertEqual(workspace.case_detail(self.db, historical)["briefs"][0]["id"], old)
        self.assertEqual(self.db.execute("SELECT count(*) FROM case_updates").fetchone()[0], 1)
