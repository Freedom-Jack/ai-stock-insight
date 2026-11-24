import tempfile
import unittest
from datetime import date
from pathlib import Path

from stockinsight import (
    db,
    events,
    evidence,
    goal_schedule,
    goals,
    monitor,
    ownership,
    proactive,
    universe,
)


class StandingGoalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "research.sqlite3"
        self.db = db.connect(self.path, fixture=True)
        self.addCleanup(self.db.close)
        universe.import_snapshot(
            self.db,
            b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD",
            complete=True,
        )
        self.item = universe.universe(self.db)["instruments"][0]
        self.ref = evidence.seed_fixture(self.db, self.item["id"])[0]["id"]
        self.start = db.instant("2026-11-20T10:00:00Z")

    def save(self, **overrides):
        return goals.save(
            self.db,
            {
                "objective": "Prepare me for earnings every day by 08:30",
                "key": "first",
                **overrides,
            },
            at=self.start,
        )

    def test_expected_misses_are_grouped_and_quiet_report_requires_receipts(self):
        plan = self.save()
        at = "2026-11-23T14:05:00Z"
        work = proactive.tick(self.db, at=at)
        r = goals.report(self.db, work)
        self.assertEqual(
            (r["kind"], r["body"]["missed"], r["body"]["status"]),
            ("recovery", 4, "partial"),
        )
        self.assertEqual(r["body"]["coverage"][0]["state"], "unchecked")
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM goal_deadlines WHERE state='missed' AND finished_at IS NOT NULL"
            ).fetchone()[0],
            4,
        )
        self.assertIsNone(proactive.tick(self.db, at=at))
        self.assertEqual(self.db.execute("SELECT count(*) FROM delivery_notices").fetchone()[0], 1)
        self.assertIsNone(r["reviewed_at"])
        self.assertEqual(self.save(), plan)
        with self.assertRaises(ValueError):
            self.save(daily_limit=6)

    def test_start_time_tolerates_foreground_poll_and_manual_override_survives_goal_replacement(
        self,
    ):
        self.save(objective="Start research at 08:30 every day")
        work = proactive.tick(self.db, at="2026-11-20T13:30:09Z")
        self.assertEqual(goals.report(self.db, work)["kind"], "scheduled")
        schedule = self.db.execute("SELECT schedule_id FROM goal_auto_sources").fetchone()[0]
        manual = monitor.configure(
            self.db,
            self.item["id"],
            "issuer",
            60,
            False,
            expected_id=schedule,
            at=self.start,
        )
        plan = goals.active(self.db)[0]
        goals.save(
            self.db,
            {
                "objective": "Report weekly on filings",
                "scope": "watchlist",
                "key": "changed",
                "plan": plan["id"],
            },
            at="2026-11-21T00:00:00Z",
        )
        proactive.tick(self.db, at="2026-11-21T00:01:00Z")
        self.assertEqual(
            self.db.execute(
                "SELECT id,enabled FROM monitor_schedules WHERE superseded_at IS NULL"
            ).fetchone()[:],
            (manual, 0),
        )
        self.assertEqual(
            self.db.execute("SELECT state FROM goal_deadlines WHERE report_id=?", (work,)).fetchone()[0],
            "completed",
        )

    def test_event_revision_relevance_followup_and_budget(self):
        self.save(daily_limit=2)

        def append(day, previous=None, state="tentative"):
            return events.append_event(
                self.db,
                self.item["id"],
                kind="earnings_release",
                state=state,
                precision="day",
                scheduled_start=day,
                source_timezone="America/New_York",
                source_ref=self.ref,
                supersedes=previous,
            )

        original = append("2026-12-07")
        first = proactive.tick(self.db, at=self.start)
        self.assertTrue(goals.report(self.db, first)["followups"])
        new = append("2026-12-10", original["id"])
        second = proactive.tick(self.db, at=self.start)
        self.assertEqual(goals.report(self.db, second)["event_version_id"], new["id"])
        self.assertTrue(goals.report(self.db, second)["context_reads"])
        follow = self.db.execute(
            """SELECT d.state FROM goal_dispatch d JOIN goal_relevance r ON r.id=d.decision_id WHERE
                r.event_version_id=? AND d.kind='followthrough'""",
            (original["id"],),
        ).fetchone()[0]
        self.assertEqual(follow, "superseded")
        deferred = append("2026-12-11", new["id"], "postponed")
        self.assertIsNone(proactive.tick(self.db, at=self.start))
        observed = self.db.execute(
            "SELECT report_path FROM delivery_notices WHERE notice_key=?",
            ("event-revision:" + deferred["id"],),
        ).fetchone()
        self.assertEqual(observed[0], "/events/" + deferred["id"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM goal_runtime_usage").fetchone()[0], 2)
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM goal_dispatch WHERE detail='Daily research budget reached'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_calendar_followthrough_requires_a_published_outcome(self):
        self.save(objective="Prepare earnings reports every Friday at 20:00")
        events.append_event(
            self.db,
            self.item["id"],
            kind="earnings_release",
            state="confirmed",
            precision="day",
            scheduled_start="2026-11-20",
            source_timezone="America/New_York",
            source_ref=self.ref,
        )
        initial = proactive.tick(self.db, at=self.start)
        self.assertEqual(goals.report(self.db, initial)["kind"], "event")
        # Live/fixture clocks agree about the calendar deadline; the event still has only a schedule.
        proactive.tick(self.db, at="2026-11-21T08:00:00Z")
        follow = proactive.tick(self.db, at="2026-11-21T08:00:01Z")
        result = goals.report(self.db, follow)
        self.assertEqual((result["kind"], result["body"]["status"]), ("followthrough", "partial"))
        self.assertIn("does not establish an outcome", result["body"]["summary"])

    def test_multiday_event_stays_upcoming_through_its_last_publisher_date(self):
        event = {
            "scheduled_start": "2026-12-08",
            "scheduled_end": "2026-12-09",
            "occurred_at": None,
            "kind": "monetary_policy_meeting",
            "text": "FOMC meeting",
            "supersedes": None,
            "source_timezone": "America/New_York",
            "state": "tentative",
        }
        plan = {"objective": "Prepare me for policy meetings"}
        self.assertEqual(proactive._decision(plan, event, db.instant("2026-12-10T02:00:00Z"))[0], "prepare")
        self.assertEqual(proactive._decision(plan, event, db.instant("2026-12-10T05:01:00Z"))[0], "suppress")

    def test_civil_exchange_schedule_and_single_worker(self):
        ny = goal_schedule.zone("America/New_York")
        self.assertEqual(goal_schedule.civil(date(2026, 3, 8), "02:35", ny).hour, 7)
        self.assertEqual(goal_schedule.civil(date(2026, 11, 1), "01:30", ny).hour, 5)
        p = goal_schedule.interpret("Report after market close", timezone="Europe/Paris")
        weekly = goal_schedule.interpret("Report Mondays and Fridays by 5 pm Pacific time")
        self.assertEqual(
            (weekly["cadence"], weekly["clock"], weekly["timezone"]),
            ("monday,friday", "17:00", "America/Los_Angeles"),
        )
        self.assertIsNone(goal_schedule.occurrence(date(2026, 11, 24), weekly))
        with self.assertRaises(ValueError):
            goal_schedule.interpret("Report at 8 am and at 5 pm")
        self.assertIsNone(goal_schedule.occurrence(date(2026, 11, 26), p))
        self.assertEqual(
            goal_schedule.occurrence(date(2026, 11, 27), p)[1],
            db.instant("2026-11-27T18:30:00Z"),
        )
        with ownership.scheduler(self.path):
            with self.assertRaises((ValueError, OSError, RuntimeError)):
                with ownership.scheduler(self.path):
                    self.fail("Two workers claimed the same workspace")
        with ownership.scheduler(self.path):
            pass

    def test_simultaneous_start_times_only_mark_a_claimed_report_as_started(self):
        self.save(objective="Start work at 08:30 every day")
        self.save(objective="Start checking at 08:30 every day", key="second")
        proactive.tick(self.db, at="2026-11-20T13:30:05Z")
        pending = self.db.execute(
            """SELECT id,report_id,started_at FROM goal_deadlines WHERE due_at=? AND state='pending'""",
            (db.instant("2026-11-20T13:30:00Z"),),
        ).fetchone()
        self.assertIsNotNone(pending["report_id"])
        self.assertIsNone(pending["started_at"])
        recovery = proactive.tick(self.db, at="2026-11-20T15:00:00Z")
        self.assertEqual(goals.report(self.db, recovery)["body"]["missed"], 1)
        self.assertEqual(
            self.db.execute(
                "SELECT state,started_at FROM goal_deadlines WHERE id=?",
                (pending["id"],),
            ).fetchone()[:],
            ("missed", None),
        )
        self.assertEqual(
            self.db.execute("SELECT state FROM goal_dispatch WHERE id=?", (pending["report_id"],)).fetchone()[
                0
            ],
            "superseded",
        )

    def test_recovery_fences_a_crashed_report_by_worker(self):
        self.save()
        plan = goals.active(self.db)[0]
        when = db.instant("2026-11-20T13:16:00Z")
        proactive._deadlines(self.db, plan, when)
        claimed = proactive._claim(self.db, when)
        self.assertEqual(claimed["kind"], "scheduled")
        recovered = proactive.tick(self.db, at="2026-11-20T15:00:00Z")
        self.assertEqual(goals.report(self.db, recovered)["body"]["missed"], 1)
        self.assertIsNone(proactive.tick(self.db, at="2026-11-20T15:00:01Z"))
        self.assertEqual(
            self.db.execute(
                "SELECT state,attempts FROM goal_dispatch WHERE id=?", (claimed["id"],)
            ).fetchone()[:],
            ("superseded", 1),
        )
        self.assertEqual(self.db.execute("SELECT count(*) FROM delivery_notices").fetchone()[0], 1)
