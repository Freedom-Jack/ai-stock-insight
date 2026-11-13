"""Exercise the SQLite inbox through the same ingestion and reporting calls as the CLI."""

from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from stockwatch.operator import parse_updates
from stockwatch.relevance import load_watchlist
from stockwatch.report import report
from stockwatch.store import connect, ingest, timeline
from stockwatch.usgs import parse_feed


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
END = "2024-04-30T00:00:00Z"


class StoreTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "watch.sqlite3"
        self.db = connect(self.path, "demo")
        self.addCleanup(lambda: self.db.close())
        self.watchlist = load_watchlist(EXAMPLES / "watchlist.json")
        self.quake, = parse_feed((EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes(),
                                 "2024-04-03T00:15:00Z")

    def ingest(self, *observations, poll=None):
        return ingest(self.db, list(observations), self.watchlist, poll=poll)

    def test_poll_conflict_rolls_back_observations_inbox_and_checkpoint(self):
        poll = (self.quake.seen_at, self.quake.revision)
        self.ingest(self.quake, poll=poll)
        before = list(self.db.iterdump())
        fresh = replace(self.quake, id="usgs:first-in-batch")
        conflict = replace(self.quake, title="Changed without a new revision", seen_at="2024-04-03T01:00:00Z")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.ingest(fresh, conflict, poll=(conflict.seen_at, conflict.revision))
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.ingest(fresh), (1, 1))

    def test_distinct_events_survive_duplicates_and_restart(self):
        events = [self.quake, replace(self.quake, id="usgs:second"), replace(self.quake, id="usgs:third")]
        self.assertEqual(self.ingest(*events, *([self.quake] * 50)), (3, 3))
        self.db.close()
        self.db = connect(self.path, "demo")
        retries = [replace(event, seen_at="2024-04-04T00:00:00Z") for event in events]
        self.assertEqual(self.ingest(*retries), (0, 0))
        rows = timeline(self.db, END, history=True)
        self.assertCountEqual([row["incident"] for row in rows], [event.id for event in events])
        self.assertEqual({row["seen_at"] for row in rows}, {self.quake.seen_at})

    def test_older_hazard_revision_cannot_reopen_a_withdrawn_screen(self):
        self.ingest(self.quake)
        corrected = replace(self.quake, facts={**self.quake.facts, "magnitude": 5.5},
                            revision="2024-04-03T01:00:00Z", seen_at="2024-04-03T01:01:00Z")
        self.assertEqual(self.ingest(corrected), (1, 1))
        delayed = replace(self.quake, revision="2024-04-03T00:30:00Z", seen_at="2024-04-03T01:02:00Z")
        self.assertEqual(self.ingest(delayed), (1, 0))
        rows = timeline(self.db, END, history=True)
        self.assertEqual([r["status"] for r in rows], ["watch", "withdrawn"])
        self.assertEqual(timeline(self.db, self.quake.seen_at, history=False)[0]["status"], "watch")
        stored = self.db.execute("SELECT decision FROM observations WHERE id=? AND revision=?",
                                 (delayed.id, delayed.revision)).fetchone()
        self.assertIn("older", stored["decision"])

    def test_operational_closure_survives_late_statement_and_geographic_revision(self):
        updates = parse_updates((EXAMPLES / "operator-taiwan-2024.json").read_bytes(), END)
        closed = replace(updates[-1], seen_at="2024-04-18T12:00:00Z")
        older_statement = replace(updates[1], seen_at="2024-04-18T13:00:00Z")
        later_hazard = replace(self.quake, revision="2024-04-18T14:00:00Z",
                               seen_at="2024-04-18T15:00:00Z", kind="withdrawn")
        self.ingest(self.quake, closed)
        self.assertEqual(self.ingest(older_statement, later_hazard), (2, 0))
        self.assertEqual([r["status"] for r in timeline(self.db, END, history=True)], ["watch", "closed"])
        self.assertEqual(timeline(self.db, END, history=False)[0]["id"], closed.id)
        self.assertEqual(timeline(self.db, "2024-04-18T11:30:00Z", history=False)[0]["status"], "watch")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 4)

    def test_operator_statement_must_reference_an_existing_incident(self):
        self.ingest(self.quake)
        update = parse_updates((EXAMPLES / "operator-taiwan-2024.json").read_bytes(), END)[0]
        unlinked = replace(update, facts={**update.facts, "incident_id": "usgs:unknown"})
        with self.assertRaisesRegex(ValueError, "unknown watch"):
            self.ingest(unlinked)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)

    def test_existing_history_cannot_acquire_an_unseen_backdated_decision(self):
        later = replace(self.quake, revision="2024-04-03T00:17:00Z", seen_at="2024-04-03T00:18:00Z",
                        facts={**self.quake.facts, "magnitude": 4.5})
        self.assertEqual(self.ingest(later), (1, 0))
        with self.assertRaisesRegex(ValueError, "backdate"):
            self.ingest(self.quake)
        received_later = replace(self.quake, seen_at="2024-04-03T00:19:00Z")
        self.assertEqual(self.ingest(received_later), (1, 0))
        self.assertEqual(timeline(self.db, END, history=True), [])

    def test_late_and_distant_earthquakes_are_audited_without_opening_watch(self):
        late = replace(self.quake, seen_at="2024-04-04T00:15:00Z")
        distant = replace(self.quake, id="usgs:distant", facts={**self.quake.facts, "longitude": 0})
        self.assertEqual(self.ingest(late, distant), (2, 0))
        self.assertEqual(timeline(self.db, END, history=True), [])
        reasons = dict(self.db.execute("SELECT id, decision FROM observations"))
        self.assertIn("window", reasons[late.id])
        self.assertIn("outside", reasons[distant.id])

    def test_portfolio_is_joined_on_read_and_does_not_enter_the_store(self):
        self.ingest(self.quake)
        before = list(self.db.iterdump())
        with redirect_stdout(StringIO()) as private:
            report(self.db, self.quake.seen_at, portfolio=EXAMPLES / "portfolio.json")
        self.assertIn("$15,000.00", private.getvalue())
        self.assertIn("15.00%", private.getvalue())
        with redirect_stdout(StringIO()) as public:
            report(self.db, self.quake.seen_at)
        self.assertNotIn("$15,000.00", public.getvalue())
        self.assertNotIn("15.00%", public.getvalue())
        self.assertEqual(list(self.db.iterdump()), before)
        persisted = "\n".join(before)
        for marker in ("Single illustrative account", "MSFT", "100000.00", "60000.00"):
            self.assertNotIn(marker, persisted)
