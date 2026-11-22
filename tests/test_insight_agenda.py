import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from stockinsight import agenda, events, goals, journal, methods, universe
from tests import test_insight_methods as method_controls
from tests.test_insight_evidence import workspace


class AgendaTests(unittest.TestCase):
    source = method_controls.MethodsTests.source

    def setUp(self):
        self.db, self.items = workspace(fixture=True)
        self.addCleanup(self.db.close)
        self.nv = self.items["NVDA"]["id"]
        self.ms = self.items["MSFT"]["id"]
        self.at = "2026-11-20T18:00:00Z"

    def goal(self, scope="watchlist"):
        return goals.save(
            self.db,
            {
                "scope": scope,
                "key": "adopt",
                "objective": "Monitor financial disclosures.",
            },
            at=self.at,
        )

    def run_agenda(self, when=None):
        return agenda.tick(self.db, at=when or self.at)

    def questions(self):
        return agenda.dashboard(self.db)["items"]

    def test_ranked_real_inputs_scope_changes_and_immutable_replay(self):
        self.source("NVDA", method_controls.Q1, 100)
        initial = methods.dossier(self.db, self.nv)
        release = self.source("NVDA", method_controls.Q2, 120)
        self.assertIsNone(self.run_agenda())
        self.assertFalse(self.questions())
        self.goal("listing:" + self.nv)
        for listing, label in ((self.nv, "NVIDIA"), (self.ms, "Microsoft")):
            journal.action(
                self.db,
                "journal-plan",
                {
                    "key": "q" + label,
                    "scope": "listing:" + listing,
                    "body": f"Did {label} volumes rise?",
                    "condition": "Check disclosed units by segment.",
                    "review_on": "2026-11-19",
                },
            )
        ref = self.source(
            "NVDA",
            note="Synthetic issuer calendar: investor presentation dated November 23.",
        )
        event = events.append_event(
            self.db,
            self.nv,
            kind="investor_day",
            state="tentative",
            source_ref=ref,
            precision="day",
            scheduled_start="2026-11-23",
            source_timezone="America/Toronto",
        )
        ident = self.run_agenda()
        ranked = self.questions()
        self.assertEqual(
            [r["kind"] for r in ranked],
            ["planned_question", "upcoming_event", "dossier"],
        )
        self.assertEqual({r["ticker"] for r in ranked}, {"NVDA"})
        self.assertEqual(
            ranked[0]["next_observation"], "Check disclosed units by segment."
        )
        self.assertEqual(ranked[1]["source_id"], event["id"])
        self.assertEqual(ranked[1]["source_ref"], ref)
        self.assertIn("tentative", ranked[1]["reason"])
        self.assertIn(initial["id"], ranked[2]["href"])
        self.assertEqual(ranked[2]["source_id"], release)
        report = methods.export(self.db, ident)
        self.assertEqual(report["prior_id"], initial["id"])
        self.assertIn(release, {r["id"] for r in report["body"]["citations"]})
        self.assertEqual(agenda.dashboard(self.db)["refreshes"][0]["report_id"], ident)
        prior = self.db.execute("SELECT * FROM agenda_revisions").fetchone()
        self.run_agenda()
        self.run_agenda()
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM agenda_revisions").fetchone()[0], 2
        )
        self.assertEqual(
            self.db.execute(
                "SELECT items FROM agenda_revisions WHERE id=?", (prior["id"],)
            ).fetchone()[0],
            prior["items"],
        )
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM agenda_refreshes").fetchone()[0], 1
        )
        replacement = universe.import_snapshot(
            self.db,
            b"ticker,listing_exchange,security_type,currency\nMSFT,NASDAQ,STK,USD",
            complete=True,
        )
        universe.accept_candidate(self.db, replacement["id"])
        self.assertFalse(self.questions())
        self.assertIsNone(self.run_agenda())

    def test_stale_or_empty_dossier_waits_for_citable_input_and_respects_both_limits(
        self,
    ):
        self.goal()
        with patch.object(methods, "now", return_value="2026-08-15T09:00:00.000000Z"):
            stale = methods.dossier(self.db, self.nv)
        self.source("NVDA", note="A narrative-only primary source.")
        self.source("MSFT", method_controls.Q1, 85, role="model_estimate")
        self.assertIsNone(self.run_agenda())
        self.assertIn(
            "30 days",
            next(i["reason"] for i in self.questions() if i["ticker"] == "NVDA"),
        )
        self.assertTrue(any(stale["id"] in i["href"] for i in self.questions()))
        self.assertFalse(agenda.dashboard(self.db)["refreshes"])
        self.source("NVDA", method_controls.Q1, 110)
        self.source("MSFT", method_controls.Q1, 80)
        self.assertIsNotNone(self.run_agenda())
        self.assertIsNone(self.run_agenda("2026-11-20T18:59:59Z"))
        self.assertIsNotNone(self.run_agenda("2026-11-20T19:00:00Z"))
        self.source("MSFT", method_controls.Q2, 93)
        self.assertIsNone(self.run_agenda("2026-11-21T17:59:59Z"))
        self.assertIsNotNone(self.run_agenda("2026-11-21T18:00:00Z"))
        self.assertEqual(len(agenda.dashboard(self.db)["refreshes"]), 3)

    def test_favorable_registered_cohort_suggests_only_a_hypothesis_and_only_owner_decides(
        self,
    ):
        self.goal("listing:" + self.nv)
        for ticker, base in (("NVDA", 100), ("MSFT", 90)):
            self.source(ticker, method_controls.Q1, base, time="2024-04-10T12:00:00Z")
        cohort = methods.freeze_cohort(
            self.db,
            self.nv,
            "revenue",
            "2024-03-31",
            "2024-05-01T19:00:00Z",
            "2024-09-30",
        )
        self.source("NVDA", method_controls.Q3, 120, time="2024-10-08T12:00:00Z")
        report = methods.evaluate_cohort(self.db, cohort)
        prior = methods.export(self.db, report["id"])
        initial_goal = dict(goals.active(self.db)[0])
        self.run_agenda()
        self.run_agenda()
        [p] = agenda.dashboard(self.db)["proposals"]
        self.assertEqual(
            (p["author"], p["status"], p["edition"], p["report_id"]),
            ("desk", "proposed", 1, report["id"]),
        )
        self.assertIn("revenue", p["hypothesis"])
        self.assertFalse(
            any(i["kind"] == "adopted_hypothesis" for i in self.questions())
        )
        approve = {
            "key": "agree",
            "revision": p["id"],
            "decision": "adopted",
            "reason": "Test it on the next preregistered report.",
        }
        self.assertEqual(agenda.action(self.db, "agenda-decide", approve), "/agenda")
        agenda.action(self.db, "agenda-decide", approve)
        with self.assertRaisesRegex(ValueError, "different instructions"):
            agenda.action(
                self.db, "agenda-decide", dict(approve, reason="Changed reason")
            )
        with self.assertRaisesRegex(ValueError, "Reload"):
            agenda.action(self.db, "agenda-decide", dict(approve, key="late"))
        self.run_agenda()
        [p] = agenda.dashboard(self.db)["proposals"]
        self.assertEqual([x["author"] for x in p["history"]], ["operator", "desk"])
        self.assertEqual(p["status"], "adopted")
        self.assertIn("adopted_hypothesis", {i["kind"] for i in self.questions()})
        self.assertEqual(methods.export(self.db, report["id"]), prior)
        self.assertEqual(dict(goals.active(self.db)[0]), initial_goal)
        self.assertEqual(len(universe.universe(self.db)["instruments"]), 2)
        agenda.action(
            self.db,
            "agenda-decide",
            {
                "key": "retire",
                "revision": p["id"],
                "decision": "retired",
                "reason": "Replication period ended.",
            },
        )
        self.run_agenda()
        self.assertNotIn("adopted_hypothesis", {i["kind"] for i in self.questions()})

    def test_negative_owner_outcome_and_operator_draft_permissions(self):
        self.goal("listing:" + self.nv)
        for ticker in self.items:
            self.source(ticker, method_controls.Q1, 100)
        cohort = methods.freeze_cohort(
            self.db,
            self.nv,
            "revenue",
            "2024-03-31",
            "2024-05-01T19:00:00Z",
            "2024-09-30",
        )
        for ticker, value in (("NVDA", 80), ("MSFT", 115)):
            self.source(ticker, method_controls.Q3, value, time="2024-10-01T12:00:00Z")
        report = methods.evaluate_cohort(self.db, cohort)
        outside = methods.dossier(self.db, self.ms)
        self.run_agenda()
        self.assertFalse(agenda.dashboard(self.db)["proposals"])
        form = {
            "key": "draft",
            "report_id": outside["id"],
            "hypothesis": "Does volume explain the change?",
            "next_observation": "Freeze unit shipments and compare the next release.",
        }
        with self.assertRaisesRegex(ValueError, "active"):
            agenda.action(self.db, "agenda-propose", form)
        form["report_id"] = report["id"]
        agenda.action(self.db, "agenda-propose", form)
        agenda.action(self.db, "agenda-propose", form)
        [p] = agenda.dashboard(self.db)["proposals"]
        self.assertEqual((p["author"], p["status"]), ("operator", "proposed"))
        goals.action(self.db, "goal-stop", {"plan": goals.active(self.db)[0]["id"]})
        self.assertFalse(agenda.dashboard(self.db)["proposals"])
        with self.assertRaisesRegex(ValueError, "active"):
            agenda.action(
                self.db,
                "agenda-decide",
                {
                    "key": "d",
                    "revision": p["id"],
                    "decision": "adopted",
                    "reason": "Replicate.",
                },
            )

    def test_restart_recovers_a_committed_dossier_without_rebuilding(self):
        self.goal("listing:" + self.nv)
        self.source("NVDA", method_controls.Q1, 100)
        dossier = methods.dossier

        def stop_after_save(db, instrument_id):
            dossier(db, instrument_id)
            raise SystemExit

        with (
            patch.object(methods, "dossier", side_effect=stop_after_save),
            self.assertRaises(SystemExit),
        ):
            self.run_agenda()
        self.assertEqual(agenda.dashboard(self.db)["refreshes"][0]["state"], "running")
        with patch.object(
            methods, "dossier", side_effect=AssertionError("Unexpected rebuild")
        ):
            self.run_agenda("2026-11-20T19:00:00Z")
        [refresh] = agenda.dashboard(self.db)["refreshes"]
        self.assertEqual((refresh["state"], refresh["attempts"]), ("saved", 1))
        self.assertTrue(
            methods.export(self.db, refresh["report_id"])["body"]["citations"]
        )

    @unittest.skipUnless(
        find_spec("httpx") and find_spec("fastapi"), "Install the desk web dependencies"
    )
    def test_private_agenda_form_roundtrip_and_report_permalink(self):
        from fastapi.testclient import TestClient

        from stockinsight import db
        from stockinsight.web import application
        from tests.test_insight_web import FormFields

        self.goal("listing:" + self.nv)
        self.source("NVDA", method_controls.Q1, 100)
        report = self.run_agenda()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desk.sqlite3"
            copy = db.connect(path, fixture=True)
            self.db.backup(copy)
            copy.close()
            # TestClient without a lifespan context exercises the real protected routes
            # without a competing foreground clock affecting this dated fixture.
            client = TestClient(
                application(path, 8123, "agenda-test"),
                base_url="http://127.0.0.1:8123",
                headers={"Origin": "http://127.0.0.1:8123"},
            )
            self.addCleanup(client.close)
            client.auth = ("research", "agenda-test")
            html = client.get("/agenda").text
            self.assertIn("Open saved dossier", html)
            fields = FormFields(html).values
            observation = "Check the next segment release."
            response = client.post(
                "/actions/agenda-propose",
                data=dict(
                    fields,
                    report_id=report,
                    hypothesis="Does the unit trend persist?",
                    next_observation=observation,
                ),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            html = client.get(response.headers["location"]).text
            self.assertIn(observation, html)
            fields = FormFields(html).values
            self.assertEqual(
                client.post(
                    "/actions/agenda-decide",
                    data=dict(fields, decision="adopted", reason="Prospective test."),
                    follow_redirects=False,
                ).status_code,
                303,
            )
            self.assertIn("adopted · edition 2", client.get("/agenda").text)
            self.assertIn(
                report, client.get("/methods", params={"instrument_id": self.nv}).text
            )
