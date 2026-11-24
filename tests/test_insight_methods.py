import json
import tempfile
import unittest
from base64 import b64encode
from contextlib import closing
from http.client import HTTPConnection
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from stockinsight import db, events, evidence, methods, universe

CONTROL = b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\nUNKNOWN,NASDAQ,STK,USD\n"
Q1 = ("2024-01-01", "2024-03-31")
Q2 = ("2024-04-01", "2024-06-30")
Q3 = ("2024-07-01", "2024-09-30")
DEFAULT_TIME = "2024-04-10T12:00:00Z"


class MethodsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "research.sqlite3"
        self.db = db.connect(self.path, fixture=True)
        self.addCleanup(lambda: self.db.close())
        universe.import_snapshot(self.db, CONTROL, complete=True)
        self.items = {i["ticker"]: i for i in universe.universe(self.db)["instruments"]}

    def source(
        self,
        ticker,
        period=None,
        value=None,
        *,
        time=DEFAULT_TIME,
        stream=None,
        role="actual",
        unit="USD million",
        metric="revenue",
        note=None,
        basis="US GAAP",
        origin="synthetic",
    ):
        i = self.items[ticker]
        fact = (
            evidence.revenue("CIK" + i["cik"], " to ".join(period), *period, str(value), unit)
            if period
            else None
        )
        if fact is not None:
            fact.update(role=role, basis=basis, metric=metric)
        text = f"{metric} {value} {unit}" if period else (note or "Scheduled company calendar observation.")
        packet = [("/cell", text, time, fact)]
        if period and note:
            for index, item in enumerate(note if isinstance(note, list) else [note]):
                quote, available = item if isinstance(item, tuple) else (item, time)
                packet.append((f"/qualification/{index:03}", quote, available, None))
        staged = evidence._stage(self.db, "full", json.dumps(packet).encode())
        with db.write(self.db) as seq:
            doc = evidence._save(
                self.db,
                seq,
                i["id"],
                origin,
                stream or db.uid("stream"),
                "Synthetic primary source",
                staged,
                packet,
                time,
                published=time,
                precision="instant",
                retention="full",
                fixture=True,
            )
        return self.db.execute(
            "SELECT id FROM evidence_passages WHERE document_id=? AND locator='/cell'", (doc,)
        ).fetchone()[0]

    def test_original_revised_and_postrelease_expectations_with_exact_sources_and_event_replay(self):
        issuer = self.items["NVDA"]["id"]
        current = self.source("NVDA", Q1, 95)
        guidance = self.source("NVDA", Q2, 115, role="issuer_guidance", time="2024-06-20T00:00:00Z")
        calendar = self.source("NVDA")
        planned = events.append_event(
            self.db,
            issuer,
            kind="earnings_release",
            source_ref=calendar,
            state="confirmed",
            precision="instant",
            scheduled_start="2024-08-01T12:00:00Z",
        )
        with patch.object(methods, "now", return_value="2024-06-21T00:00:00.000000Z"):
            original = methods.freeze_expectation(
                self.db, planned["id"], current, value="120", start=Q2[0], end=Q2[1]
            )
            issued = methods.freeze_expectation(self.db, planned["id"], guidance)
        with patch.object(methods, "now", return_value="2024-07-20T00:00:00.000000Z"):
            revised = methods.freeze_expectation(
                self.db, planned["id"], current, value="140", start=Q2[0], end=Q2[1]
            )
            preview = methods.event_report(self.db, planned["id"], focus="expectations")
        original_manifest = methods.export(self.db, preview["id"])
        actual = self.source(
            "NVDA", Q2, 130, time="2024-08-01T12:00:00Z", note="Shipment timing affected the quarter."
        )
        released = events.append_event(
            self.db,
            issuer,
            kind="earnings_release",
            source_ref=actual,
            state="occurred",
            precision="instant",
            occurred_at="2024-08-01T12:00:00Z",
            supersedes=planned["id"],
        )
        late = methods.freeze_expectation(
            self.db, released["id"], current, value="129", start=Q2[0], end=Q2[1]
        )
        report = methods.event_report(
            self.db, released["id"], goal_id="goal1", objective="Assess Q2", focus="expectations"
        )
        self.assertEqual(report["method"], "earnings_review.v1")
        self.assertEqual(report["body"]["expectations"][-1]["id"], late)
        self.assertFalse(report["body"]["expectations"][-1]["pre_event"])
        diffs = {
            r["expectation_id"]: r["difference"]
            for r in report["body"]["calculations"]
            if "expectation_id" in r
        }
        self.assertEqual(diffs, {original: "10", issued: "15", revised: "-10"})
        self.assertEqual(report["body"]["expectations"][2]["prior_id"], original)
        self.assertIn("Shipment timing", str(report["body"]["claims"]))
        self.assertIn("Street consensus", str(report["body"]["gaps"]))
        self.assertTrue(all(c["version_hash"] for c in report["body"]["citations"]))
        self.assertEqual(
            methods.event_report(
                self.db, released["id"], goal_id="goal1", objective="Assess Q2", focus="expectations"
            )["id"],
            report["id"],
        )
        with self.assertRaisesRegex(ValueError, "event changed"):
            methods.event_report(self.db, planned["id"])
        self.db.close()
        self.db = db.connect(self.path)
        self.assertEqual(methods.export(self.db, preview["id"]), original_manifest)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_financial_qualifications_cover_each_edition_and_pin_event_era_evidence(self):
        nv = self.items["NVDA"]["id"]
        prior = self.source("NVDA", Q1, 90, stream="prior", note="Equipment deliveries were delayed.")
        stamp = "2024-08-01T12:00:00Z"
        actual = self.source(
            "NVDA",
            Q2,
            100,
            time=stamp,
            note=[
                "Contract pricing contributed to reported growth.",
                "Currency translation offset part of the increase.",
                ("Management added a later qualification.", "2024-08-20T10:00:00Z"),
            ],
        )
        # A later restatement of an earlier fiscal period should appear only in today's dossier.
        revised = self.source("NVDA", Q1, 80, stream="prior", time="2024-08-20T10:00:00Z")
        event = events.append_event(
            self.db,
            nv,
            kind="earnings_release",
            source_ref=actual,
            state="occurred",
            precision="instant",
            occurred_at=stamp,
        )
        post = methods.event_report(self.db, event["id"])
        narrative = post["body"]["claims"]
        for text in ("Contract pricing", "Currency translation", "Equipment deliveries"):
            anchored = next(c for c in narrative if text in c["text"])
            self.assertEqual(len(anchored["passage_ids"]), 2)
        self.assertNotIn("later qualification", str(narrative))
        self.assertIn(prior, post["body"]["calculations"][0]["input_ids"])
        self.assertNotIn(revised, str(post))
        self.assertEqual({x["reviewed"] for x in post["body"]["disclosure_coverage"]}, {1, 2})
        publication = events.append_event(
            self.db,
            nv,
            kind="issuer_update",
            state="occurred",
            precision="instant",
            occurred_at=stamp,
            source_ref=actual,
        )
        non_earnings = methods.event_report(self.db, publication["id"], focus="exposure")
        self.assertIn("Currency translation", str(non_earnings["body"]["claims"]))
        self.assertEqual(non_earnings["body"]["disclosure_coverage"][0]["reviewed"], 2)
        dossier = methods.dossier(self.db, nv)
        self.assertIn("later qualification", str(dossier["body"]["claims"]))
        self.assertIn(revised, dossier["body"]["calculations"][0]["input_ids"])
        self.assertNotIn(prior, str(dossier))
        self.source(
            "NVDA",
            Q3,
            110,
            time="2024-10-10T12:00:00Z",
            note=[f"Published operating context {n}." for n in range(19)],
        )
        large = methods.dossier(self.db, nv)["body"]
        bounded = next(s for s in large["disclosure_coverage"] if s["unreviewed"])
        self.assertEqual((bounded["reviewed"], bounded["unreviewed"]), (16, 3))
        self.assertIn(bounded["source_ref"], str(large["gaps"]))
        self.assertIn(bounded["document_id"], str(large["gaps"]))

    def test_dossier_peer_and_conditional_valuation_reject_wrong_basis(self):
        nv, ms = self.items["NVDA"]["id"], self.items["MSFT"]["id"]
        q1 = self.source("NVDA", Q1, 100)
        q2 = self.source("NVDA", Q2, 120)
        peer = self.source("MSFT", Q2, 200)
        incompatible = self.source("MSFT", Q2, 200, basis="non-GAAP")
        profile = methods.dossier(self.db, nv)
        self.assertEqual(profile["body"]["calculations"][0]["difference"], "20")
        self.assertEqual(len(profile["body"]["agenda"]), 3)
        value = methods.valuation(self.db, nv, q2, "2", "4", "25")
        calc = value["body"]["calculations"][0]
        self.assertEqual(
            [v["conditional_value"] for v in calc["scenarios"]], ["1200.00", "1800.00", "2400.00"]
        )
        self.assertEqual(calc["output"], "enterprise value")
        comparison = methods.peer(self.db, nv, q2, ms, peer)
        self.assertEqual(comparison["body"]["calculations"][0]["difference"], "-80")
        for a, b, company in [(q1, peer, ms), (q2, incompatible, ms), (q2, q1, nv)]:
            with self.assertRaises(ValueError):
                methods.peer(self.db, nv, a, company, b)
        with self.assertRaises(ValueError):
            methods.valuation(self.db, nv, peer, "2", "4", "0")
        with self.assertRaises(ValueError):
            methods.valuation(self.db, nv, q2, "NaN", "4", "0")

    def test_cohort_declared_before_outcomes_exports_entire_universe_and_preserves_adverse_results(self):
        self.source("NVDA", Q1, 100, stream="base")
        self.source("MSFT", Q1, 80)
        cutoff = "2024-05-01T12:00:00Z"
        c = methods.freeze_cohort(self.db, self.items["NVDA"]["id"], "revenue", Q1[1], cutoff, Q3[1])
        unchanged = self.db.execute("SELECT members FROM method_cohorts WHERE id=?", (c,)).fetchone()[0]
        first = methods.evaluate_cohort(self.db, c)
        self.assertIn("2 missing", first["summary"])
        self.source("NVDA", Q1, 200, stream="base", time="2024-10-25T00:00:00Z")
        self.source("NVDA", Q3, 120, time="2024-10-25T00:00:00Z")
        self.source("MSFT", Q3, 60, time="2024-10-26T00:00:00Z")
        final = methods.evaluate_cohort(self.db, c)
        self.assertEqual(final["prior_id"], first["id"])
        members = final["body"]["cohort"]["members"]
        self.assertEqual(
            {m["ticker"]: m["status"] for m in members},
            {"MSFT": "observed", "NVDA": "observed", "UNKNOWN": "excluded"},
        )
        group = next(iter(final["body"]["cohort"]["groups"].values()))
        self.assertEqual((group["median_percent"], group["negative"], group["positive"]), ("-2.5", 1, 1))
        self.assertEqual(
            json.loads(unchanged),
            json.loads(self.db.execute("SELECT members FROM method_cohorts WHERE id=?", (c,)).fetchone()[0]),
        )
        self.assertEqual(final["id"], methods.evaluate_cohort(self.db, c)["id"])
        self.assertEqual(methods.export(self.db, first["id"])["summary"], first["summary"])
        with self.assertRaises(ValueError):
            methods.freeze_cohort(self.db, self.items["NVDA"]["id"], "revenue", Q1[1], cutoff, Q1[1])

    def test_policy_uses_dated_relationship_and_focus_specific_next_observation(self):
        nv, ms = self.items["NVDA"], self.items["MSFT"]
        direct = self.source("NVDA", note="FOMC calendar lists a two-day meeting.")
        scoped = self.source("MSFT", note="Signed agreement names both businesses.")
        universe.record_exposure(
            self.db,
            nv["company_id"],
            ms["company_id"],
            relation="customer",
            uncertainty="Contract size remains undisclosed",
            valid_from="2024-03-01T00:00:00Z",
            evidence_ids=[scoped],
            supported=True,
        )
        e = events.append_event(
            self.db,
            nv["id"],
            kind="monetary_policy_meeting",
            state="confirmed",
            source_ref=direct,
            precision="day",
            scheduled_start="2024-08-01",
        )
        r = methods.event_report(self.db, e["id"], focus="exposure")
        self.assertIn("customer", str(r["body"]["claims"]))
        self.assertIn("discounted valuations", str(r["body"]["alternatives"]))
        self.assertIn("counterparties", str(r["body"]["next_observations"]))
        self.assertEqual({c["id"] for c in r["body"]["citations"]}, {direct, scoped})
        self.assertFalse(r["body"]["calculations"])
        wrong = {"instrument_id": ms["id"], "event_version_id": e["id"]}
        with self.assertRaisesRegex(ValueError, "listing"):
            methods.action(self.db, "method-event", wrong)
        redirect = methods.action(
            self.db,
            "method-event",
            {"instrument_id": nv["id"], "event_version_id": e["id"], "focus": "disclosure"},
        )
        self.assertTrue(redirect.startswith("/methods?instrument_id=" + nv["id"] + "#report_"))
        self.assertTrue(methods.dashboard(self.db, nv["id"])["reports"])

    def test_federal_reserve_range_source_and_cancellation_are_separate_from_listing_relevance(self):
        nv, ms = self.items["NVDA"]["id"], self.items["MSFT"]["id"]
        src = self.source("NVDA", origin="fed_calendar", note="The December FOMC meeting is tentative.")
        meeting = events.append_event(
            self.db,
            nv,
            kind="monetary_policy_meeting",
            source_ref=src,
            precision="day",
            state="tentative",
            scheduled_start="2026-12-08",
            scheduled_end="2026-12-09",
            source_timezone="America/New_York",
        )
        with db.write(self.db) as seq:
            self.db.execute(
                "INSERT INTO calendar_reports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    nv,
                    "fed_calendar",
                    "dec-fomc",
                    "Federal Reserve",
                    src,
                    meeting["event_id"],
                    "signature",
                    "FOMC meeting",
                    "Rate expectations may affect equity valuations.",
                    seq,
                    seq,
                ),
            )
        prepared = methods.event_report(self.db, meeting["id"], goal_id="local", request_key="dispatch")
        self.assertEqual(prepared["title"], "Federal Reserve meeting · relevance to NVDA")
        self.assertIn("tentative, 2026-12-08 through 2026-12-09", prepared["summary"])
        self.assertIn("calendar-date precision, America/New_York", prepared["summary"])
        self.assertNotIn("valuations", prepared["summary"])
        self.assertTrue(any(c.get("kind") == "conditional_relevance" for c in prepared["body"]["claims"]))
        with self.assertRaisesRegex(ValueError, "dispatch key"):
            methods.event_report(
                self.db, meeting["id"], goal_id="local", request_key="dispatch", instrument_id=ms
            )
        with self.assertRaisesRegex(ValueError, "approved relationship"):
            methods.event_report(self.db, meeting["id"], instrument_id=ms)
        change = self.source(
            "NVDA", origin="fed_calendar", note="Calendar correction. The meeting is cancelled."
        )
        cancellation = events.append_event(
            self.db,
            nv,
            kind="monetary_policy_meeting",
            source_ref=change,
            state="cancelled",
            precision="unknown",
            supersedes=meeting["id"],
        )
        updated = methods.event_report(self.db, cancellation["id"])
        self.assertIn("cancelled", updated["summary"])
        history = next(c for c in updated["body"]["claims"] if "prior edition" in c["text"])
        self.assertIn("2026-12-08 through 2026-12-09", history["text"])
        self.assertEqual({c["id"] for c in updated["body"]["citations"]}, {src, change})
        self.assertEqual(methods.export(self.db, prepared["id"]), prepared)

    def test_market_import_window_benchmark_and_predecision_cohort_suppress_unknowns(self):
        nv, ms = self.items["NVDA"]["id"], self.items["MSFT"]["id"]
        header = ",".join(methods.PRICE_FIELDS) + "\n"

        def quote(ticker, day, value, adjusted="unadjusted", vintage="", delay=0):
            return f"{ticker},NASDAQ,{day},{day}T16:00:00-04:00,USD,{value},{adjusted},{vintage},{delay}\n"

        left, right = "2024-04-01", "2024-04-15"
        with patch.object(methods, "now", return_value="2024-04-01T21:00:00.000000Z"):
            for ticker, i, value in (("NVDA", nv, "100"), ("MSFT", ms, "200")):
                methods.import_prices(
                    self.db, i, "Market control", "regular-close", header + quote(ticker, left, value)
                )
        pre = methods.freeze_cohort(self.db, nv, "close_price", left, "2024-04-01T21:05:00Z", right)
        self.assertIn("remains unverified", methods.price_window(self.db, nv, left, right, ms)["summary"])
        for ticker, i, value in (("NVDA", nv, "110"), ("MSFT", ms, "190")):
            rows = header + quote(ticker, right, value)
            location = methods.action(
                self.db,
                "method-price-import",
                {"instrument_id": i, "publisher": "Market control", "series": "regular-close", "rows": rows},
            )
            self.assertIn("#prices", location)
        result = methods.price_window(self.db, nv, left, right, ms)
        self.assertEqual([r["percent_change"] for r in result["body"]["calculations"]], ["10", "-5"])
        self.assertEqual(result["body"]["window"]["benchmark_spread_percentage_points"], "15")
        self.assertIn("operator’s market file", str(result["body"]["gaps"]))
        self.assertTrue(all(c["financial"]["delay_seconds"] == 0 for c in result["body"]["citations"]))
        members = methods.evaluate_cohort(self.db, pre)["body"]["cohort"]
        self.assertEqual(next(iter(members["groups"].values()))["median_percent"], "2.5")
        with self.assertRaises(ValueError):
            methods.import_prices(self.db, nv, "Market control", "series", header + "Account,holding,private")
        with self.assertRaisesRegex(ValueError, "listing"):
            methods.import_prices(
                self.db, nv, "Market control", "series", header + quote("MSFT", right, "99")
            )
        with self.assertRaisesRegex(ValueError, "vintage"):
            methods.import_prices(
                self.db, nv, "Market control", "series", header + quote("NVDA", right, "99", "split_adjusted")
            )
        for invalid in (
            quote("NVDA", "2024-04-06", "99"),
            quote("NVDA", "2026-07-03", "99"),
            quote("NVDA", right, "99").replace("T16:00", "T10:45"),
        ):
            with self.assertRaisesRegex(ValueError, "regular-session"):
                methods.import_prices(self.db, nv, "Market control", "regular-close", header + invalid)
        with (
            patch.object(methods, "now", return_value="2024-04-15T20:00:05.000000Z"),
            self.assertRaisesRegex(ValueError, "stated delay"),
        ):
            methods.import_prices(
                self.db, nv, "Market control", "regular-close", header + quote("NVDA", right, "99", delay=15)
            )
        methods.import_prices(
            self.db, nv, "Other publisher", "different", header + quote("NVDA", right, "115")
        )
        unclear = methods.price_window(self.db, nv, left, right, ms)
        self.assertIn("remains unverified", unclear["summary"])
        self.assertNotIn("benchmark_spread_percentage_points", unclear["body"]["window"])

    def test_dispatch_replay_survives_newer_event_and_agenda_but_rejects_foreign_goal(self):
        nv = self.items["NVDA"]["id"]
        p = self.source("NVDA", note="Expected issuer meeting in October.")
        old = events.append_event(
            self.db,
            nv,
            kind="meeting",
            state="tentative",
            source_ref=p,
            precision="day",
            scheduled_start="2024-10-01",
        )
        original = methods.event_report(
            self.db, old["id"], goal_id="one", objective="Original objective", request_key="dispatch-1"
        )
        events.append_event(
            self.db,
            nv,
            kind="meeting",
            state="postponed",
            source_ref=p,
            precision="day",
            scheduled_start="2024-10-08",
            supersedes=old["id"],
        )
        replay = methods.event_report(
            self.db,
            old["id"],
            goal_id="one",
            objective="Follow up on different input",
            focus="exposure",
            request_key="dispatch-1",
        )
        self.assertEqual(original, replay)
        with self.assertRaisesRegex(ValueError, "dispatch key"):
            methods.event_report(self.db, old["id"], goal_id="two", request_key="dispatch-1")

    @unittest.skipUnless(
        find_spec("fastapi") and find_spec("uvicorn"), "Install the locked desk dependencies"
    )
    def test_private_desk_valuation_form_and_exact_json_export(self):
        from stockinsight.web import application
        from tests.test_insight_web import FormFields, served

        ref = self.source("NVDA", Q1, 100)
        listing = self.items["NVDA"]["id"]
        with served(lambda port: application(self.path, port, "method-test")) as port:

            def read(path, fields=None):
                headers = {"Authorization": "Basic " + b64encode(b"research:method-test").decode()}
                payload = None
                if fields is not None:
                    payload = urlencode(fields)
                    headers.update(
                        {
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Origin": f"http://127.0.0.1:{port}",
                        }
                    )
                with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
                    client.request(
                        "POST" if fields is not None else "GET", path, body=payload, headers=headers
                    )
                    reply = client.getresponse()
                    return reply.status, reply.getheader("Location"), reply.read().decode()

            status, _, html = read("/methods?instrument_id=" + listing)
            self.assertEqual(status, 200)
            self.assertIn("Model valuation sensitivity", html)
            csrf = FormFields(html).values["csrf"]
            status, location, _ = read(
                "/actions/method-valuation",
                {
                    "csrf": csrf,
                    "instrument_id": listing,
                    "passage_id": ref,
                    "low": "2",
                    "high": "4",
                    "growth": "25",
                },
            )
            self.assertEqual(status, 303)
            path, report = location.split("#")
            status, _, html = read(path)
            self.assertEqual(status, 200)
            self.assertIn("Conditional enterprise value", html)
            self.assertIn(report, html)
            status, _, body = read("/methods/reports/" + report + ".json")
            self.assertEqual(status, 200)
            retained = json.loads(body)["body"]
            self.assertEqual(retained["citations"][0]["id"], ref)
            self.assertEqual(retained["calculations"][0]["scenarios"][1]["conditional_value"], "1500.00")
            market_file = ",".join(methods.PRICE_FIELDS) + (
                "\nNVDA,NASDAQ,2024-04-01,2024-04-01T16:00:00-04:00,USD,100,unadjusted,,15"
                "\nNVDA,NASDAQ,2024-04-15,2024-04-15T16:00:00-04:00,USD,110,unadjusted,,15"
            )
            status, _, _ = read(
                "/actions/method-price-import",
                {
                    "csrf": csrf,
                    "instrument_id": listing,
                    "publisher": "Synthetic USD quotes",
                    "series": "regular",
                    "rows": market_file,
                },
            )
            self.assertEqual(status, 303)
            fields = FormFields(read("/")[2]).values
            status, case_url, _ = read(
                "/actions/ask",
                {
                    **fields,
                    "instrument_id": listing,
                    "question": "How did NVDA’s closing price change from 2024-04-01 to 2024-04-15?",
                },
            )
            self.assertEqual(status, 303)
            status, _, case_html = read(case_url)
            self.assertEqual(status, 200)
            for phrase in (
                "10%",
                "2024-04-01",
                "2024-04-15",
                "unadjusted",
                "Synthetic USD quotes",
                "operator-supplied",
            ):
                self.assertIn(phrase, case_html)
