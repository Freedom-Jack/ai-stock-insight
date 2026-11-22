import tempfile
import unittest
from datetime import date
from pathlib import Path

from stockinsight import db, events, evidence, goal_schedule, goals, monitor, ownership, proactive, universe


class StandingGoalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"research.sqlite3"
        self.db=db.connect(self.path,fixture=True)
        self.addCleanup(self.db.close)
        universe.import_snapshot(self.db,b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD",complete=True)
        self.item=universe.universe(self.db)["instruments"][0]
        self.ref=evidence.seed_fixture(self.db,self.item["id"])[0]["id"]
        self.start=db.instant("2026-11-20T10:00:00Z")

    def save(self,**overrides):
        return goals.save(self.db,{"objective":"Prepare me for earnings every day by 08:30","key":"first",
                                   **overrides},at=self.start)

    def test_expected_misses_are_grouped_and_quiet_report_requires_receipts(self):
        plan=self.save()
        at="2026-11-23T14:05:00Z"
        work=proactive.tick(self.db,at=at)
        r=goals.report(self.db,work)
        self.assertEqual((r["kind"],r["body"]["missed"],r["body"]["status"]),("recovery",4,"partial"))
        self.assertEqual(r["body"]["coverage"][0]["state"],"unchecked")
        self.assertEqual(self.db.execute("SELECT count(*) FROM goal_deadlines WHERE state='missed' AND finished_at IS NOT NULL").fetchone()[0],4)
        self.assertIsNone(proactive.tick(self.db,at=at))
        self.assertEqual(self.db.execute("SELECT count(*) FROM delivery_notices").fetchone()[0],1)
        self.assertIsNone(r["reviewed_at"])
        self.assertEqual(self.save(),plan)
        with self.assertRaises(ValueError):
            self.save(daily_limit=6)

    def test_start_time_tolerates_foreground_poll_and_manual_override_survives_goal_replacement(self):
        self.save(objective="Start research at 08:30 every day")
        work=proactive.tick(self.db,at="2026-11-20T13:30:09Z")
        self.assertEqual(goals.report(self.db,work)["kind"],"scheduled")
        schedule=self.db.execute("SELECT schedule_id FROM goal_auto_sources").fetchone()[0]
        manual=monitor.configure(self.db,self.item["id"],"issuer",60,False,expected_id=schedule,at=self.start)
        plan=goals.active(self.db)[0]
        goals.save(self.db,{"objective":"Report weekly on filings","scope":"watchlist","key":"changed","plan":plan["id"]},at="2026-11-21T00:00:00Z")
        proactive.tick(self.db,at="2026-11-21T00:01:00Z")
        self.assertEqual(self.db.execute("SELECT id,enabled FROM monitor_schedules WHERE superseded_at IS NULL").fetchone()[:],(manual,0))
        self.assertEqual(self.db.execute("SELECT state FROM goal_deadlines WHERE report_id=?",(work,)).fetchone()[0],"completed")

    def test_event_revision_relevance_followup_and_budget(self):
        self.save(daily_limit=2)
        def append(day,previous=None):
            return events.append_event(self.db,self.item["id"],kind="earnings_release",state="tentative",
                precision="day",scheduled_start=day,source_timezone="America/New_York",source_ref=self.ref,supersedes=previous)
        original=append("2026-12-07")
        first=proactive.tick(self.db,at=self.start)
        self.assertTrue(goals.report(self.db,first)["followups"])
        new=append("2026-12-10",original["id"])
        second=proactive.tick(self.db,at=self.start)
        self.assertEqual(goals.report(self.db,second)["event_version_id"],new["id"])
        self.assertTrue(goals.report(self.db,second)["context_reads"])
        follow=self.db.execute("""SELECT d.state FROM goal_dispatch d JOIN goal_relevance r ON r.id=d.decision_id WHERE
                r.event_version_id=? AND d.kind='followthrough'""",(original["id"],)).fetchone()[0]
        self.assertEqual(follow,"superseded")
        append("2026-12-11",new["id"])
        self.assertIsNone(proactive.tick(self.db,at=self.start))
        self.assertEqual(self.db.execute("SELECT count(*) FROM goal_runtime_usage").fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM goal_dispatch WHERE detail='Daily research budget reached'").fetchone()[0],1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_civil_exchange_schedule_and_single_worker(self):
        ny=goal_schedule.zone("America/New_York")
        self.assertEqual(goal_schedule.civil(date(2026,3,8),"02:35",ny).hour,7)
        self.assertEqual(goal_schedule.civil(date(2026,11,1),"01:30",ny).hour,5)
        p=goal_schedule.interpret("Report after market close",timezone="Europe/Paris")
        self.assertIsNone(goal_schedule.occurrence(date(2026,11,26),p))
        self.assertEqual(goal_schedule.occurrence(date(2026,11,27),p)[1],db.instant("2026-11-27T18:30:00Z"))
        with ownership.scheduler(self.path):
            with self.assertRaises((ValueError,OSError,RuntimeError)):
                with ownership.scheduler(self.path):
                    self.fail("Two workers claimed the same workspace")
        with ownership.scheduler(self.path):
            pass
