import json
import sqlite3
import tempfile
import unittest
from base64 import b64encode
from contextlib import closing
from datetime import datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from stockinsight import db, events, evidence, exposure, goals, universe
from tests.test_insight_evidence import workspace
from tests.test_insight_web import FormFields, served


class ExposureReviewTests(unittest.TestCase):
    def setUp(self):
        self.conn, self.listings = workspace()
        self.addCleanup(self.conn.close)
        self.msft = self.listings["MSFT"]["id"]
        self.nvda = self.listings["NVDA"]["id"]

    def source(
        self, listing, origin, url, text, *, receipt=True, fixture=False, raw=None, published_url=None
    ):
        payload = raw if raw is not None else text.encode()
        locator = (
            json.dumps({"link": published_url or url, "published_at": db.now()})
            if origin == "issuer_news"
            else "paragraph 1"
        )
        with db.write(self.conn) as seq:
            doc = evidence._save(
                self.conn,
                seq,
                listing,
                origin,
                url,
                "Named report " + origin,
                evidence._stage(self.conn, "full", payload),
                [(locator, text, db.now(), None)],
                db.now(),
                published=None,
                precision="source",
                retention="full",
                fixture=fixture,
            )
            if receipt:
                self.conn.execute(
                    """INSERT INTO source_checks(id,instrument_id,provider,started_at,finished_at,status,document_id,commit_seq)
                                  VALUES(?,?,?,?,?,'ok',?,?)""",
                    (db.uid("check"), listing, origin, db.now(), db.now(), doc, seq),
                )
        return self.conn.execute("SELECT id FROM evidence_passages WHERE document_id=?", (doc,)).fetchone()[0]

    def event(self, listing, ref, kind="issuer_announcement", supersedes=None):
        return events.append_event(
            self.conn,
            listing,
            kind=kind,
            state="occurred",
            source_ref=ref,
            precision="day",
            occurred_at="2025-01-02",
            supersedes=supersedes,
        )["id"]

    def propose(self, ref, **change):
        data = {
            "instrument_id": self.msft,
            "entity_type": "company",
            "counterparty": self.nvda,
            "relation": "supplier",
            "trigger_kind": "issuer_announcement",
            "passage_id": ref,
            "rationale": "Review supplier availability and verify capacity commitments.",
        }
        return exposure.action(self.conn, "exposure-propose", {**data, **change})

    def approve(self):
        ident = self.conn.execute(
            "SELECT id FROM exposure_proposals ORDER BY commit_seq DESC LIMIT 1"
        ).fetchone()[0]
        exposure.action(self.conn, "exposure-approve", {"proposal": ident})
        return ident

    def test_counterparty_needs_review_distinct_current_sources_and_explicit_withdrawal(self):
        proof = self.source(
            self.msft,
            "sec_filing",
            "https://www.sec.gov/a",
            "NVIDIA supplies processing systems to our business.",
        )
        old = universe.record_exposure(
            self.conn,
            self.listings["MSFT"]["company_id"],
            self.listings["NVDA"]["company_id"],
            relation="supplier",
            uncertainty="Capacity could change.",
            valid_from="2025-01-01T00:00:00Z",
            evidence_ids=(proof,),
            supported=True,
        )
        observed = self.source(
            self.nvda,
            "issuer_news",
            "https://nvidianews.nvidia.com/a",
            "New processing systems enter production.",
        )
        event = self.event(self.nvda, observed)
        self.propose(proof)
        self.propose(proof)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM exposure_proposals").fetchone()[0], 1)
        self.assertEqual(exposure.for_event(self.conn, self.msft, event), [])
        ident = self.approve()
        match = exposure.for_event(self.conn, self.listings["MSFT"], event)
        self.assertEqual(
            [(m["passage_id"], m["event_passage_id"], m["legacy_id"]) for m in match],
            [(proof, observed, old)],
        )
        self.assertNotEqual(match[0]["source_receipt"], match[0]["event_receipt"])
        self.assertFalse(exposure.for_event(self.conn, self.nvda, event))
        exposure.action(self.conn, "exposure-approve", {"proposal": ident})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM exposure_decisions").fetchone()[0], 1)
        exposure.action(
            self.conn, "exposure-revoke", {"proposal": ident, "reason": "The supply agreement ended."}
        )
        self.assertFalse(exposure.for_event(self.conn, self.msft, event))
        with self.assertRaises(ValueError):
            exposure.action(self.conn, "exposure-approve", {"proposal": ident})
        history = exposure.dashboard(self.conn)["proposals"][0]
        self.assertEqual(history["quotation"], "NVIDIA supplies processing systems to our business.")
        self.assertEqual([r["state"] for r in history["decisions"]], ["revoked", "approved"])

    def test_replaced_or_retired_report_and_superseded_events_cannot_trigger(self):
        proof = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/a", "NVIDIA is a supplier of processing systems."
        )
        first = self.source(
            self.nvda, "issuer_news", "https://nvidianews.nvidia.com/1", "New GPU capacity is available."
        )
        v1 = self.event(self.nvda, first)
        self.propose(proof)
        self.approve()
        second = self.source(
            self.nvda,
            "issuer_news",
            "https://nvidianews.nvidia.com/1",
            "A revised capacity schedule was announced.",
        )
        v2 = self.event(self.nvda, second, supersedes=v1)
        self.assertFalse(exposure.for_event(self.conn, self.msft, v1))
        self.assertTrue(exposure.for_event(self.conn, self.msft, v2))
        self.source(self.msft, "sec_filing", "https://www.sec.gov/a", "The prior supplier agreement expired.")
        self.assertFalse(exposure.for_event(self.conn, self.msft, v2))
        history = exposure.dashboard(self.conn)["proposals"][0]
        self.assertEqual(history["state"], "approved")
        self.assertFalse(history["current"])
        self.assertIn("NVIDIA is a supplier", history["quotation"])

    def test_exact_named_geographies_registered_macro_sources_and_unrelated_events(self):
        proof = self.source(
            self.msft,
            "sec_filing",
            "https://www.sec.gov/geo",
            "Revenue from Taiwan is material to this segment.",
        )
        self.propose(
            proof,
            entity_type="geography",
            entity="Taiwan",
            relation="geographic",
            trigger_kind="regulatory_notice",
        )
        self.approve()
        wrong = self.source(
            self.msft, "cma_news", "https://www.gov.uk/x", "Microsoft licensing terms in other markets."
        )
        right = self.source(
            self.msft, "cma_news", "https://www.gov.uk/y", "Microsoft comments on Taiwan market supply."
        )
        self.assertFalse(
            exposure.for_event(self.conn, self.msft, self.event(self.msft, wrong, "regulatory_notice"))
        )
        self.assertTrue(
            exposure.for_event(self.conn, self.msft, self.event(self.msft, right, "regulatory_notice"))
        )
        wrong = self.source(
            self.msft, "cma_news", "https://www.gov.uk/z", "Taiwanese facilities are discussed."
        )
        self.assertFalse(
            exposure.for_event(self.conn, self.msft, self.event(self.msft, wrong, "regulatory_notice"))
        )
        another = self.source(
            self.nvda, "cma_news", "https://www.gov.uk/z", "Taiwan policy report for NVIDIA."
        )
        self.assertFalse(
            exposure.for_event(self.conn, self.msft, self.event(self.nvda, another, "regulatory_notice"))
        )
        policy = self.source(
            self.msft,
            "msft_release",
            "https://www.microsoft.com/policy",
            "Federal Reserve policy rates influence our borrowing cost.",
        )
        self.propose(
            policy,
            entity_type="policy",
            entity="Federal Reserve",
            relation="policy",
            trigger_kind="monetary_policy_meeting",
        )
        self.approve()
        calendar = self.source(
            self.msft, "fed_calendar", "https://www.federalreserve.gov/calendar", "FOMC meeting · 2025-01-02."
        )
        self.assertTrue(
            exposure.for_event(
                self.conn, self.msft, self.event(self.msft, calendar, "monetary_policy_meeting")
            )
        )
        wrong_source = self.event(self.msft, right, "monetary_policy_meeting")
        self.assertFalse(exposure.for_event(self.conn, self.msft, wrong_source))

    def test_shared_underlying_source_fails_and_unsigned_or_cross_listing_proposals_fail(self):
        text = "NVIDIA supplies processing systems to our business."
        support = self.source(self.msft, "sec_filing", "https://www.sec.gov/x", text)
        observed = self.source(self.nvda, "issuer_news", "https://nvidianews.nvidia.com/a", text)
        event = self.event(self.nvda, observed)
        self.propose(support)
        self.approve()
        self.assertFalse(exposure.for_event(self.conn, self.msft, event))
        unsigned = self.source(self.msft, "sec_filing", "https://www.sec.gov/u", text, receipt=False)
        for ref, changes in [
            (unsigned, {}),
            (observed, {}),
            (support, {"quotation": "Different quote"}),
            (support, {"entity_type": "entity", "entity": "Not Named Anywhere"}),
            (support, {"relation": "geographic"}),
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.propose(ref, **changes)
        candidate = universe.import_snapshot(
            self.conn, b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD", complete=True
        )
        if candidate["state"] == "candidate":
            universe.accept_candidate(self.conn, candidate["id"])
        self.assertFalse(exposure.for_event(self.conn, self.msft, event))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM exposure_proposals").fetchone()[0], 1)

    def test_goal_candidates_are_read_only_and_theme_does_not_change_membership(self):
        source = self.source(
            self.msft,
            "cma_news",
            "https://www.gov.uk/g",
            "Microsoft cites increased demand for cloud infrastructure in the United Kingdom.",
        )
        self.event(self.msft, source, "regulatory_notice")
        theme = universe.create_theme(self.conn, "cloud infrastructure", "How does demand change?")
        before = list(self.conn.execute("SELECT * FROM theme_memberships"))
        self.assertFalse(exposure.dashboard(self.conn)["candidates"])
        goals.save(
            self.conn,
            {
                "objective": "Monitor cloud infrastructure daily",
                "scope": "listing:" + self.nvda,
                "key": "goal-1",
                "timezone": "UTC",
            },
        )
        self.assertFalse(exposure.dashboard(self.conn)["candidates"])
        goals.save(
            self.conn,
            {
                "objective": "Monitor cloud infrastructure daily",
                "scope": "listing:" + self.msft,
                "key": "goal-2",
                "timezone": "UTC",
            },
        )
        candidates = exposure.dashboard(self.conn)["candidates"]
        self.assertEqual([(c["theme"], c["passage"]["id"]) for c in candidates], [(theme, source)])
        self.assertFalse(self.conn.execute("SELECT 1 FROM exposure_proposals").fetchone())
        self.propose(
            source,
            entity_type="theme",
            theme=theme,
            relation="shared_demand",
            trigger_kind="regulatory_notice",
        )
        self.approve()
        self.assertEqual(before, list(self.conn.execute("SELECT * FROM theme_memberships")))
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_verified_publisher_excerpts_preserve_original_receipt_and_retire_after_revision(self):
        from stockinsight import disclosure, providers
        from tests.test_insight_disclosure import transcript

        statement = "NVIDIA supplies equipment for our business."
        with patch.object(providers, "_fetch", return_value=transcript([statement])):
            call_ref = disclosure.capture(self.conn, self.msft, disclosure.TRANSCRIPT_URL, statement)
        self.propose(call_ref)
        call_id = self.approve()
        url = "https://www.sec.gov/Archives/edgar/data/789019/000078901924000001/test8k.htm"
        raw = f'<ix:nonNumeric name="dei:EntityCentralIndexKey">789019</ix:nonNumeric><p>Item 1.01 Entry into an Agreement</p><p>{statement}</p><p>Signatures</p>'.encode()
        self.source(self.msft, "sec_filing", url, "Filing summary.", raw=raw)
        with patch.object(providers, "_fetch") as wire:
            filing_ref = disclosure.capture(self.conn, self.msft, url, statement)
            wire.assert_not_called()
        self.propose(filing_ref)
        filing_id = self.approve()
        news = self.source(
            self.nvda,
            "issuer_news",
            "https://nvidianews.nvidia.com/news/launch",
            "New equipment ships in April.",
        )
        event = self.event(self.nvda, news)
        receipts = {r["provider"]: r["id"] for r in self.conn.execute("SELECT * FROM source_checks")}
        links = exposure.for_event(self.conn, self.msft, event)
        self.assertEqual(
            {link["id"]: link["source_receipt"] for link in links},
            {call_id: receipts["msft_transcript"], filing_id: receipts["sec_filing"]},
        )
        self.source(self.msft, "sec_filing", url, "Revised contract scope.")
        self.assertEqual([link["id"] for link in exposure.for_event(self.conn, self.msft, event)], [call_id])

    def test_feed_item_and_linked_article_are_one_underlying_publication(self):
        url = "https://nvidianews.nvidia.com/news/expansion"
        proof = self.source(self.nvda, "issuer", url, "Operations in Taiwan are expanding.")
        self.propose(
            proof, instrument_id=self.nvda, entity_type="geography", entity="Taiwan", relation="geographic"
        )
        self.approve()
        item = self.source(
            self.nvda,
            "issuer_news",
            "https://nvidianews.nvidia.com/cats/press_release.xml",
            "Taiwan operating site expansion announced.",
            published_url=url,
        )
        self.assertFalse(exposure.for_event(self.conn, self.nvda, self.event(self.nvda, item)))

    def test_monitor_targets_follow_verified_approval_current_watchlist_and_named_provider(self):
        from stockinsight import providers

        ref = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/supplier", "NVIDIA supplies processing systems."
        )

        def targets():
            return [
                (listing["id"], route) for listing, route in exposure.monitor_targets(self.conn, self.msft)
            ]

        self.propose(ref)
        self.assertEqual(targets(), [])
        approved = self.approve()
        self.assertEqual(targets(), [(self.nvda, "issuer_news")])
        self.assertFalse(exposure.monitor_targets(self.conn, self.listings["NVDA"]))
        exposure.action(self.conn, "exposure-revoke", {"proposal": approved, "reason": "Supplier change."})
        self.assertEqual(targets(), [])

        self.propose(ref, trigger_kind="earnings_release")
        self.approve()
        self.propose(ref, trigger_kind="monetary_policy_meeting")
        self.approve()
        self.propose(ref, trigger_kind="filed_disclosure")
        self.approve()
        with patch.object(providers, "sec_contact", return_value=None):
            self.assertEqual(targets(), [])
        with patch.object(providers, "sec_contact", return_value="Example Research research@example.org"):
            self.assertEqual(targets(), [(self.nvda, "sec_filing")])
            self.source(
                self.msft, "sec_filing", "https://www.sec.gov/supplier", "Revised supplier commitment."
            )
            self.assertEqual(targets(), [])

        current = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/confirmed", "NVIDIA supplies new systems."
        )
        for reason in ("First goal relevance.", "Second goal relevance."):
            self.propose(current, rationale=reason)
            self.approve()
        self.assertEqual(targets(), [(self.nvda, "issuer_news")])
        candidate = universe.import_snapshot(
            self.conn, b"ticker,listing_exchange,security_type,currency\nMSFT,NASDAQ,STK,USD", complete=True
        )
        if candidate["state"] == "candidate":
            universe.accept_candidate(self.conn, candidate["id"])
        self.assertEqual(targets(), [])

    def test_narrow_goal_checks_only_approved_counterparty_route_and_withdraws_it(self):
        from stockinsight import monitor

        goals.save(
            self.conn,
            {
                "objective": "Monitor supplier availability",
                "scope": "listing:" + self.msft,
                "key": "linked-coverage",
                "timezone": "UTC",
            },
        )
        plan = goals.active(self.conn)[0]
        ref = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/supplier", "NVIDIA supplies new systems."
        )
        self.propose(ref)
        start = db.now()
        goals.reconcile_sources(self.conn, [plan], start)

        def peer_coverage(stamp):
            return [
                (r["provider"], r["enabled"])
                for r in goals.coverage(self.conn, plan, start, stamp)
                if r["ticker"] == "NVDA"
            ]

        self.assertFalse(peer_coverage(start))
        approved = self.approve()
        stamp = db.now()
        goals.reconcile_sources(self.conn, [plan], stamp)
        self.assertEqual(peer_coverage(stamp), [("issuer_news", True)])

        def dispatch(stamp):
            with patch.object(monitor, "_capture", return_value={"status": "ok"}) as capture:
                for _ in range(16):
                    if monitor.tick(self.conn, at=stamp) is None:
                        break
                return [c.args[2] for c in capture.call_args_list if c.args[1]["id"] == self.nvda]

        self.assertEqual(dispatch(stamp), ["issuer_news"])
        exposure.action(self.conn, "exposure-revoke", {"proposal": approved, "reason": "Agreement ended."})
        due = (datetime.fromisoformat(stamp) + timedelta(hours=4)).isoformat()
        self.assertEqual(dispatch(due), [])
        goals.reconcile_sources(self.conn, [plan], due)
        self.assertEqual(dispatch(due), [])
        self.assertFalse(peer_coverage(due))
        self.assertEqual(
            self.conn.execute(
                "SELECT enabled FROM monitor_schedules WHERE instrument_id=? AND provider='issuer_news' AND superseded_at IS NULL",
                (self.nvda,),
            ).fetchone()[0],
            0,
        )

    def test_retired_negated_hypothetical_and_unrelated_terms_cannot_establish_relationship(self):
        for index, statement in enumerate(
            (
                "NVIDIA is not a supplier.",
                "NVIDIA previously supplied processing systems.",
                "NVIDIA could become our supplier.",
                "We supply NVIDIA with processing systems.",
                "NVIDIA announced a release. The supplier in another operation remains unknown.",
            )
        ):
            ref = self.source(self.msft, "sec_filing", f"https://www.sec.gov/{index}", statement)
            with self.subTest(statement=statement), self.assertRaises(ValueError):
                self.propose(ref)
        denied = self.source(
            self.msft,
            "sec_filing",
            "https://www.sec.gov/denied",
            "It is not true that NVIDIA supplies processing systems.",
        )
        with self.assertRaises(ValueError):
            self.propose(denied, quotation="NVIDIA supplies processing systems")
        good = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/current", "NVIDIA supplies processing systems."
        )
        self.propose(good, expires_on="2031-01-01")
        self.approve()
        event_ref = self.source(
            self.nvda, "issuer_news", "https://nvidianews.nvidia.com/1", "New systems are available."
        )
        event = self.event(self.nvda, event_ref)
        with patch.object(exposure, "now", return_value="2031-01-02T00:00:00.000000Z"):
            self.assertFalse(exposure.for_event(self.conn, self.msft, event))
            self.assertFalse(exposure.monitor_targets(self.conn, self.msft))

    def test_private_desk_relationship_forms_preserve_attribution_and_quote(self):
        from stockinsight.web import application

        ref = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/test", "NVIDIA supplies processing systems."
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "research.sqlite3"
            with closing(sqlite3.connect(path)) as target:
                self.conn.backup(target)
            with served(lambda port: application(path, port, "example-password")) as port:
                origin = f"http://127.0.0.1:{port}"

                def request(path, form=None):
                    headers = {"Authorization": "Basic " + b64encode(b"research:example-password").decode()}
                    if form is not None:
                        headers.update(
                            {"Origin": origin, "Content-Type": "application/x-www-form-urlencoded"}
                        )
                    with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as client:
                        client.request(
                            "GET" if form is None else "POST",
                            path,
                            urlencode(form) if form else None,
                            headers,
                        )
                        response = client.getresponse()
                        return response.status, response.read().decode()

                status, body = request("/exposures")
                self.assertEqual(status, 200)
                self.assertIn("Watchlist exposures", body)
                csrf = FormFields(body).values["csrf"]
                proposal = {
                    "csrf": csrf,
                    "instrument_id": self.msft,
                    "entity_type": "company",
                    "entity": "",
                    "counterparty": self.nvda,
                    "theme": "",
                    "relation": "supplier",
                    "trigger_kind": "issuer_announcement",
                    "passage_id": ref,
                    "quotation": "",
                    "rationale": "Investigate supply availability.",
                    "expires_on": "",
                }
                self.assertEqual(request("/actions/exposure-propose", proposal)[0], 303)
                _, body = request("/exposures")
                self.assertIn("Approve relationship", body)
                self.assertIn("NVIDIA supplies processing systems.", body)
                ident = FormFields(body).values["proposal"]
                self.assertEqual(
                    request("/actions/exposure-approve", {"proposal": ident, "csrf": csrf})[0], 303
                )
                self.assertIn("Approved · You", request("/exposures")[1])
                self.assertEqual(
                    request(
                        "/actions/exposure-revoke",
                        {"proposal": ident, "reason": "Review superseded.", "csrf": csrf},
                    )[0],
                    303,
                )
                _, body = request("/exposures")
                self.assertIn("Revoked · You", body)
                self.assertIn("Review superseded.", body)

    def test_standing_goal_queues_cross_listing_review_only_after_approval(self):
        from stockinsight import local_model, proactive

        proof = self.source(
            self.msft, "sec_filing", "https://www.sec.gov/counterparty", "NVIDIA supplies processing systems."
        )
        observed = self.source(
            self.nvda,
            "issuer_news",
            "https://nvidianews.nvidia.com/supplier",
            "New processing systems will ship in January.",
        )
        event = events.append_event(
            self.conn,
            self.nvda,
            kind="issuer_announcement",
            source_ref=observed,
            precision="day",
            state="occurred",
            occurred_at=db.now()[:10],
        )["id"]
        goals.save(
            self.conn,
            {
                "objective": "Monitor supplier developments each day",
                "scope": "listing:" + self.msft,
                "key": "supply",
                "timezone": "UTC",
            },
        )
        self.propose(proof)
        with patch.object(local_model, "available", return_value=False):
            proactive.tick(self.conn)
            self.assertFalse(
                self.conn.execute(
                    "SELECT 1 FROM goal_relevance WHERE event_version_id=?", (event,)
                ).fetchone()
            )
            self.approve()
            for _ in range(3):
                proactive.tick(self.conn)
        result = self.conn.execute(
            """SELECT r.instrument_id,d.state,d.body FROM goal_dispatch d JOIN goal_relevance r
                                ON r.id=d.decision_id WHERE r.event_version_id=? AND r.decision='linked'""",
            (event,),
        ).fetchone()
        self.assertEqual((result["instrument_id"], result["state"]), (self.msft, "complete"))
        impact = json.loads(result["body"])["exposures"][0]
        self.assertEqual((impact["passage_id"], impact["event_passage_id"]), (proof, observed))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM goal_impacts").fetchone()[0], 1)
