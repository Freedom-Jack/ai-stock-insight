from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from stockwatch.followup import poll_issuer, unlinked
from stockwatch.issuer import parse_bulletins
from stockwatch.model import utc
from stockwatch.operator import parse_updates
from stockwatch.relevance import load_watchlist
from stockwatch.store import connect, coverage_gaps, ingest, record_health, timeline
from stockwatch.usgs import parse_feed


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
APRIL6 = "2024-04-06T01:00:00Z"


class FollowupTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "live.sqlite3"
        self.db = connect(self.path, "live")
        self.addCleanup(lambda: self.db.close())
        self.watchlist = load_watchlist(EXAMPLES / "watchlist.json")
        self.quake, = parse_feed((EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes(), "2024-04-03T00:15:00Z")
        self.updates = parse_updates((EXAMPLES / "operator-taiwan-2024.json").read_bytes(),
                                     "2024-04-18T12:00:00Z")

    def bulletin(self, **changes):
        return SimpleNamespace(**{
            "key": "test:issuer:april5", "published_at": "2024-04-05T13:09:11Z", "event_date": "2024-04-03",
            "title": "Update on the April 3 earthquake", "excerpt": "An operator statement for review.",
            "url": self.updates[1].url, **changes,
        })

    def poll(self, *items, seen=APRIL6):
        return poll_issuer(self.db, clock=lambda: utc(seen), fetch=lambda _at: SimpleNamespace(
            report_date=seen[:10], bulletins=list(items)))

    def test_replay_restart_and_later_manual_review_of_same_document(self):
        ingest(self.db, [self.quake], self.watchlist)
        self.assertEqual(self.poll(self.bulletin()), (1, 1))
        self.db.close()
        self.db = connect(self.path, "live")
        self.assertEqual(self.poll(self.bulletin()), (0, 0))
        item, = timeline(self.db, APRIL6, history=False)
        self.assertEqual((item["kind"], item["status"], item["url"]), ("issuer_candidate", "watch", self.updates[1].url))
        self.assertEqual(timeline(self.db, "2024-04-05T23:59:00Z", history=False)[0]["kind"], "earthquake")

        # The reviewer can decide a subsequent state using the cited document.
        self.assertEqual(ingest(self.db, [self.updates[1]]), (1, 1))
        self.assertEqual(timeline(self.db, self.updates[1].seen_at, history=False)[0]["status"], "narrowed")

    def test_real_twse_filing_matches_pre_event_watch_and_accepts_a_review(self):
        payload = (EXAMPLES / "issuer-twse-2024.json").read_bytes()
        ingest(self.db, [self.quake], self.watchlist)
        self.assertEqual(poll_issuer(self.db, clock=lambda: utc(APRIL6),
                                     fetch=lambda received: parse_bulletins(payload, received)), (1, 1))
        item, = timeline(self.db, APRIL6, history=False)
        self.assertEqual(item["incident"], self.quake.id)
        self.assertEqual(item["revision"], utc("2024-04-05T13:23:03Z"))
        reviewed = json.loads((EXAMPLES / "operator-taiwan-2024.json").read_bytes())[1]
        reviewed.update(url=item["url"], published_at=item["revision"], clock_basis="TWSE filing time in Taipei.",
                        locator="The issuer's April 5 update in MOPS, operations paragraph.")
        update = parse_updates(json.dumps([reviewed]).encode(), APRIL6)
        self.assertEqual(ingest(self.db, update), (1, 1))
        self.assertEqual(timeline(self.db, APRIL6, history=False)[0]["status"], "narrowed")

    def test_geographic_and_operator_updates_still_obey_last_assessed_state(self):
        first_statement = replace(self.updates[0], seen_at="2024-04-04T08:00:00Z")
        ingest(self.db, [self.quake, first_statement], self.watchlist)
        self.poll(self.bulletin())
        retraction = replace(self.quake, kind="withdrawn", seen_at="2024-04-06T12:01:00Z",
                             revision="2024-04-06T12:00:00Z")
        self.assertEqual(ingest(self.db, [retraction], self.watchlist), (1, 0))
        older = replace(first_statement, id="older", revision="2024-04-03T11:00:00Z",
                        occurred_at="2024-04-03T11:00:00Z", seen_at="2024-04-06T13:00:00Z")
        self.assertEqual(ingest(self.db, [older]), (1, 0))
        self.assertEqual(timeline(self.db, older.seen_at, history=False)[0]["status"], "monitoring")

    def test_ambiguous_or_undated_documents_are_visible_without_assignment(self):
        second = replace(self.quake, id="usgs:aftershock")
        ingest(self.db, [self.quake, second], self.watchlist)
        self.assertEqual(self.poll(self.bulletin(), self.bulletin(key="other", event_date=None)), (2, 0))
        self.assertEqual(unlinked(self.db, "2024-04-05T23:00:00Z"), [])
        reasons = [row["reason"] for row in unlinked(self.db, APRIL6)]
        self.assertTrue(any("multiple" in reason for reason in reasons))
        self.assertTrue(any("did not identify" in reason for reason in reasons))

    def test_pending_bulletin_can_match_a_delayed_hazard_and_preserves_both_receipts(self):
        early = self.bulletin(published_at="2024-04-03T00:18:00Z")
        first = "2024-04-03T00:20:00Z"
        self.assertEqual(self.poll(early, seen=first), (1, 0))
        quake = replace(self.quake, seen_at="2024-04-03T00:30:00Z")
        ingest(self.db, [quake], self.watchlist)
        attached = "2024-04-03T00:35:00Z"
        self.assertEqual(self.poll(seen=attached), (0, 1))
        item, = timeline(self.db, attached, history=False)
        self.assertEqual((json.loads(item["facts"])["first_seen"], item["seen_at"]), (utc(first), utc(attached)))
        self.assertEqual(len(unlinked(self.db, first)), 1)
        self.assertEqual(unlinked(self.db, attached), [])

    def test_bad_batch_preserves_prior_issuer_checkpoint_and_keeps_other_source_healthy(self):
        ingest(self.db, [self.quake], self.watchlist, poll=(self.quake.seen_at, self.quake.revision))
        self.assertEqual(self.poll(), (0, 0))
        with self.assertRaisesRegex(ValueError, "postdates"):
            self.poll(self.bulletin(), self.bulletin(key="future", published_at="2024-05-01T00:00:00Z"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM issuer_documents").fetchone()[0], 0)
        states = {r["source"]: r for r in self.db.execute("SELECT * FROM feed_health")}
        self.assertEqual(states["TSMC"]["last_ok"], utc(APRIL6))
        self.assertIn("postdates", states["TSMC"]["error"])
        self.assertIsNone(states["USGS"]["error"])
        self.assertEqual(self.poll(self.bulletin()), (1, 1))

    def test_manually_assessed_filing_is_not_renotified_when_discovered(self):
        ingest(self.db, [self.quake, replace(self.updates[1], seen_at="2024-04-05T14:00:00Z")], self.watchlist)
        self.assertEqual(self.poll(self.bulletin()), (1, 0))
        self.assertIn("already assessed", unlinked(self.db, APRIL6)[0]["reason"])

    def test_changed_public_excerpt_after_manual_assessment_creates_fresh_review(self):
        ingest(self.db, [self.quake], self.watchlist)
        self.poll(self.bulletin())
        ingest(self.db, [replace(self.updates[1], seen_at="2024-04-06T02:00:00Z")])
        revised = self.bulletin(excerpt="A revised operational statement for review.")
        seen = "2024-04-06T03:00:00Z"
        self.assertEqual(self.poll(revised, seen=seen), (1, 1))
        latest, = timeline(self.db, seen, history=False)
        self.assertEqual((latest["kind"], latest["status"]), ("issuer_candidate", "narrowed"))

    def test_user_config_edits_do_not_retract_the_original_geographic_match(self):
        ingest(self.db, [self.quake], self.watchlist)
        restrictive = replace(self.watchlist, min_magnitude=9, fingerprint="new-config")
        revision = replace(self.quake, revision="2024-04-03T01:00:00Z", seen_at="2024-04-03T01:01:00Z")
        self.assertEqual(ingest(self.db, [revision], restrictive), (1, 0))
        corrected = replace(revision, revision="2024-04-03T01:02:00Z", seen_at="2024-04-03T01:03:00Z",
                            facts={**self.quake.facts, "magnitude": 5})
        self.assertEqual(ingest(self.db, [corrected], restrictive), (1, 1))
        self.assertEqual(timeline(self.db, corrected.seen_at, history=False)[0]["status"], "withdrawn")

    def test_rolling_source_gaps_survive_recovery_and_both_sources_stay_healthy(self):
        with self.db:
            for day in (3, 6, 7):
                instant = f"2024-04-{day:02}T08:00:00Z"
                record_health(self.db, "USGS", instant, instant)
                record_health(self.db, "TSMC", instant, instant)
        notes = coverage_gaps(self.db)
        self.assertEqual(len(notes), 2)
        self.assertTrue(any("TWSE" in note and "2024-04-04 through 2024-04-05" in note for note in notes))
        self.assertTrue(any("USGS" in note and "2024-04-05T08:00" in note for note in notes))
        self.assertEqual(self.db.execute("SELECT count(*) FROM feed_health WHERE error IS NULL").fetchone()[0], 2)

    def test_read_only_pre_v1_ledger_supports_new_optional_views(self):
        old = self.path.parent / "old.sqlite3"
        with closing(sqlite3.connect(old)) as writer:
            writer.execute("CREATE TABLE feed_health(source TEXT PRIMARY KEY)")
            writer.commit()
        with closing(sqlite3.connect(old.as_uri() + "?mode=ro", uri=True)) as reader:
            self.assertEqual(coverage_gaps(reader), [])
            self.assertEqual(unlinked(reader, APRIL6), [])
