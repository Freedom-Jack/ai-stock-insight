"""Official calendar identities, independent source attribution and watchlist coverage."""

import json
import unittest
from contextlib import closing
from unittest.mock import patch

from stockinsight import db, events, evidence, filing_passages, goals, monitor, proactive, providers
from stockinsight import sources_calendar as sources
from tests.test_insight_evidence import workspace

NOW = "2026-11-21T13:00:00.000000Z"


def annual(sentence):
    return (
        "<h1>Microsoft Annual Meeting of Shareholders</h1><p>The 2026 Annual Shareholders Meeting "
        + sentence
        + "</p>"
    ).encode()


def fed(december="8-9"):
    dates = [
        ("January", "27-28"),
        ("March", "17-18"),
        ("April", "28-29"),
        ("June", "16-17"),
        ("July", "28-29"),
        ("September", "15-16"),
        ("October", "27-28"),
        ("December", december),
    ]
    return (
        "<h4><a>2026 FOMC Meetings</a></h4>"
        + "".join(
            f'<div class="fomc-meeting__month"><strong>{m}</strong></div><div class="fomc-meeting__date">{days}</div>'
            for m, days in dates
        )
    ).encode()


def cma(title="CMA investigates Microsoft over subscription plans"):
    item = {
        "title": title,
        "link": "/government/news/microsoft-plans",
        "public_timestamp": "2026-11-10T12:30:00Z",
        "organisations": [{"content_id": "957eb4ec-089b-4f71-ba2a-dc69ac8919ea"}],
    }
    return json.dumps(
        {"results": [item, item, {**item, "title": "Unrelated local service competition"}]}
    ).encode()


class CalendarSourceTests(unittest.TestCase):
    def test_market_calendar_does_not_require_a_company_filing_identity(self):
        from stockinsight import universe
        universe.import_snapshot(self.conn, b"ticker,listing_exchange,security_type,currency\nEXAMPLE,NASDAQ,STK,USD",
                                 complete=True, source_id="macro-test")
        item = next(i for i in universe.universe(self.conn)["instruments"] if i["ticker"] == "EXAMPLE")
        self.assertTrue(sources.eligible(item, "fed_calendar"))
        self.assertFalse(sources.eligible(item, "sec_filing"))
        self.assertFalse(sources.eligible({**item, "resolution_status": "unresolved"}, "fed_calendar"))

    def setUp(self):
        self.conn, self.instruments = workspace()
        self.addCleanup(self.conn.close)
        self.msft = self.instruments["MSFT"]["id"]

    def save(self, route, raw, ticker="MSFT"):
        listing = self.instruments[ticker]
        host, path, title = sources.ROUTES[route]
        rows = sources.rows(route, raw, NOW, cik=listing["cik"])
        with db.write(self.conn) as seq:
            doc = evidence._save(
                self.conn,
                seq,
                listing["id"],
                route,
                "https://" + host + path,
                title,
                evidence._stage(self.conn, "metadata", raw),
                rows,
                NOW,
                published=None,
                precision="source precision",
                retention="metadata",
            )
        monitor._observe(self.conn, listing, route, doc)
        return doc

    def test_one_macro_notice_links_both_watchlist_reports(self):
        self.save("fed_calendar",fed(),"MSFT")
        self.save("fed_calendar",fed(),"NVDA")
        goals.save(self.conn,{"key":"shared-fed","objective":"Prepare me for monetary policy events"},at=NOW)
        with patch("stockinsight.local_model.available",return_value=False):
            reports=[proactive.tick(self.conn,at=NOW) for _ in range(2)]
        self.assertTrue(all(reports))
        self.assertNotEqual(*reports)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM delivery_notices").fetchone()[0],1)
        self.assertEqual(goals.report(self.conn,reports[0])["related_reports"][0]["id"],reports[1])

    def test_year_event_revisions_cancellation_checked_mirror_and_replay(self):
        first = annual("will be held virtually on December 8, 2026, at 8:30 am PT.")
        original = self.save("msft_calendar", first)
        old = self.conn.execute("SELECT * FROM event_versions").fetchone()
        self.assertEqual(
            (old["scheduled_start"], old["source_timezone"]), ("2026-12-08T16:30:00.000000Z", sources.PACIFIC)
        )
        self.save("msft_calendar_faq", first)
        self.assertEqual(
            (sources.coverage(self.conn)[0]["origin_count"], sources.coverage(self.conn)[0]["disagreement"]),
            (1, False),
        )
        self.save("msft_calendar", annual("has been tentatively scheduled for December 11, 2026."))
        latest = events.at_commit(self.conn, old["event_id"])
        self.assertEqual(
            (latest["supersedes"], latest["state"], latest["scheduled_start"], latest["precision"]),
            (old["id"], "tentative", "2026-12-11", "day"),
        )
        self.assertTrue(sources.coverage(self.conn)[0]["disagreement"])
        self.assertEqual(
            events.at_commit(self.conn, old["event_id"], old["commit_seq"])["scheduled_start"],
            old["scheduled_start"],
        )
        self.save("msft_calendar", annual("has been postponed."))
        self.assertIsNone(events.at_commit(self.conn, old["event_id"])["scheduled_start"])
        self.save("msft_calendar", annual("has been cancelled."))
        self.assertEqual(events.at_commit(self.conn, old["event_id"])["state"], "cancelled")
        sources.observe(self.conn, self.msft, "msft_calendar", original)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM event_versions").fetchone()[0], 4)
        self.assertFalse(monitor.dashboard(self.conn, at=NOW)["upcoming"])

    def test_fed_date_precision_revision_holiday_dst_and_fail_closed_on_changed_shape(self):
        self.save("fed_calendar", fed())
        before = monitor.dashboard(self.conn, at=NOW)["upcoming"]
        self.assertEqual(
            [(e["day"], e["scheduled_end"], e["precision"]) for e in before],
            [("2026-12-08", "2026-12-09", "day")],
        )
        self.save("fed_calendar", fed("24-25"))
        after = monitor.dashboard(self.conn, at=NOW)["upcoming"]
        self.assertEqual((after[0]["id"], after[0]["scheduled_end"]), (before[0]["id"], "2026-12-25"))
        self.assertEqual(len(after), 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM event_versions").fetchone()[0], 9)
        with self.assertRaises(ValueError):
            sources.rows("fed_calendar", fed().replace(b"__date", b"unknown", 1), NOW)
        summer = sources.rows("msft_calendar", annual("will be held on July 3, 2026, at 8:30 am PT."), NOW)
        self.assertEqual(json.loads(summer[0][0])["start"], "2026-07-03T15:30:00.000000Z")
        for month_day, time in (("March 8", "2:30 am"), ("November 1", "1:30 am")):
            with self.assertRaises(ValueError):
                sources.rows(
                    "msft_calendar", annual(f"will be held on {month_day}, 2026, at {time} PT."), NOW
                )

    def test_bounded_regulator_discovery_dedup_attribution_contradiction_and_scope(self):
        self.save("msft_calendar", annual("will be held on December 8, 2026, at 8:30 am PT."))
        self.save("msft_calendar_faq", annual("will be held on December 8, 2026, at 8:30 am PT."))
        authority = self.save("cma_news", cma())
        source = self.conn.execute(
            "SELECT id FROM evidence_passages WHERE document_id=?", (authority,)
        ).fetchone()[0]
        ms, mirror = [
            r[0]
            for r in self.conn.execute(
                "SELECT source_ref FROM calendar_reports WHERE provider LIKE 'msft_calendar%' ORDER BY provider"
            )
        ]
        self.assertFalse(sources.rows("cma_news", cma(), NOW, cik=sources.NVIDIA))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM event_versions").fetchone()[0], 2)
        sources.compare_reports(
            self.conn, ms, mirror, "same_account", "Same issuer distributes both statements."
        )
        sources.compare_reports(
            self.conn, source, ms, "disagree", "The regulator and issuer report different positions."
        )
        sources.compare_reports(
            self.conn, ms, source, "disagree", "The regulator and issuer report different positions."
        )
        rows = sources.report_comparisons(self.conn)
        self.assertEqual([len(r["origins"]) for r in rows], [2, 1])
        self.assertEqual(len(rows[0]["sources"]), 2)
        self.assertEqual(rows[0]["judgment"], "disagree")
        self.assertFalse(sources.eligible(self.instruments["NVDA"], "msft_calendar"))
        self.assertIn("fed_calendar", sources.recommended(self.instruments["MSFT"]))

    def test_transient_host_failure_retries_same_occurrence_twice_then_waits_for_next_regular_check(self):
        schedule = monitor.configure(
            self.conn, self.msft, "msft_calendar", 1440, True, at=NOW, expected_id=None
        )
        with self.assertRaises(ValueError):
            monitor.configure(self.conn, self.msft, "msft_calendar", 60, True, at=NOW, expected_id=None)
        self.assertEqual(
            monitor.configure(
                self.conn, self.msft, "msft_calendar", 1440, True, at=NOW, expected_id=schedule
            ),
            schedule,
        )
        with patch.object(
            monitor,
            "_capture",
            return_value={
                "status": "rate_limited",
                "message": "Publisher cooldown",
                "retry_at": "2026-11-21T13:05:00Z",
            },
        ):
            first = monitor.tick(self.conn, at=NOW, detail=True)
            self.assertEqual(first["status"], "failed")
            self.assertIsNone(monitor.tick(self.conn, at="2026-11-21T13:04:59Z"))
            monitor.tick(self.conn, at="2026-11-21T13:05:00Z")
            monitor.tick(self.conn, at="2026-11-21T13:05:02Z")
            self.assertIsNone(monitor.tick(self.conn, at="2026-11-21T13:07:00Z"))
        self.assertEqual(
            [
                tuple(r)
                for r in self.conn.execute("SELECT original_id,attempt FROM source_retries ORDER BY attempt")
            ],
            [(first["id"], 1), (first["id"], 2)],
        )
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM monitor_occurrences WHERE status='failed'").fetchone()[0],
            3,
        )

    def test_new_routes_are_scoped_to_watchlist_and_fixture_never_calls_public_host(self):
        with patch.object(
            providers, "_fetch", return_value=annual("will be held on December 8, 2026, at 8:30 am PT.")
        ) as fetch:
            result = evidence.capture_public(self.conn, self.instruments["MSFT"], "msft_calendar")
            self.assertEqual(result["status"], "ok")
            self.assertTrue(
                evidence.capture_public(self.conn, self.instruments["MSFT"], "msft_calendar")["cached"]
            )
            self.assertEqual(
                evidence.capture_public(self.conn, self.instruments["NVDA"], "msft_calendar")["status"],
                "unsupported",
            )
            with closing(workspace(fixture=True)[0]) as fixture:
                self.assertEqual(
                    evidence.capture_public(fixture, self.instruments["MSFT"], "msft_calendar")["status"],
                    "unsupported",
                )
            self.assertEqual(fetch.call_count, 1)

    def test_filed_passages_require_identity_valid_accession_and_stable_narrative_locator(self):
        index = {
            "cik": "789019",
            "filings": {
                "recent": {
                    "form": ["10-Q", "8-K"],
                    "items": ["", "2.02"],
                    "accessionNumber": ["", "0000789019-26-000088"],
                    "filingDate": ["2026-10-31", "2026-10-28"],
                    "primaryDocument": ["", "msft-20261028.htm"],
                }
            },
        }
        html = b"""<html><ix:nonnumeric name="dei:EntityCentralIndexKey">0000789019</ix:nonnumeric>
        <div>Item 2.02. Results of Operations and Financial Condition.</div>
        <div>The registrant has issued a press release reporting its quarterly financial results.</div>
        <div>SIGNATURES</div><div>This paragraph after the signature is outside the selected item.</div></html>"""
        with (
            patch.object(providers, "sec_contact", return_value=None),
            patch.object(providers, "_fetch") as fetch,
        ):
            self.assertEqual(
                evidence.capture_public(self.conn, self.instruments["MSFT"], "sec_filing")["status"],
                "unavailable",
            )
            fetch.assert_not_called()
        with (
            patch.object(providers, "sec_contact", return_value="unit@example.org"),
            patch.object(filing_passages.time, "sleep"),
            patch.object(providers, "_fetch", side_effect=[json.dumps(index).encode(), html]) as fetch,
        ):
            captured = evidence.capture_public(self.conn, self.instruments["MSFT"], "sec_filing")
        self.assertEqual(captured["status"], "ok")
        self.assertEqual(
            fetch.call_args_list[1].args,
            (
                filing_passages.ARCHIVE_HOST,
                "/Archives/edgar/data/789019/000078901926000088/msft-20261028.htm",
            ),
        )
        p = evidence.get(self.conn, self.msft, captured["evidence_ids"][0])
        self.assertEqual(len(captured["evidence_ids"]), 1)
        self.assertEqual(json.loads(p["locator"])["item"], "2.02")
        self.assertIn("The registrant has issued", p["text"])
        self.assertEqual(evidence.document_bytes(self.conn, self.msft, captured["document_id"]), html)
        monitor._observe(self.conn, self.instruments["MSFT"], "sec_filing", captured["document_id"])
        self.assertEqual(
            self.conn.execute("SELECT kind FROM event_versions").fetchone()[0], "filed_disclosure"
        )
        with self.assertRaises(ValueError):
            filing_passages.passages(
                html.replace(b"0000789019", b"0001045810"),
                sources.MICROSOFT,
                ("2026-10-28", "x", "y"),
                "0" * 64,
                NOW,
            )
        index["filings"]["recent"]["primaryDocument"][1] = "../unscoped.htm"
        with self.assertRaises(ValueError):
            filing_passages.select(json.dumps(index).encode(), sources.MICROSOFT, NOW)

    def test_financial_search_keeps_qualification_and_excludes_later_calendar(self):
        raw = b"""<p>October 28, 2026</p><p>Microsoft will provide forward-looking guidance on its webcast.</p>
        <table><tr><td>MICROSOFT CORPORATION</td><td></td><td></td><td></td></tr><tr><td>INCOME STATEMENTS</td></tr>
        <tr><td>(In millions, except per share amounts) (Unaudited)</td></tr>
        <tr><td></td><td>Three Months Ended September 30,</td></tr><tr><td></td><td>2026</td><td></td><td>2025</td></tr>
        <tr><td>Total revenue</td><td>120</td><td></td><td>100</td></tr></table>"""
        self.save("msft_release", raw)
        self.save("fed_calendar", fed())
        all_rows = evidence.search(self.conn, self.msft)
        financial = evidence.search(self.conn, self.msft, financial_documents=True)
        self.assertEqual(len(all_rows), 11)
        self.assertEqual(len(financial), 3)
        self.assertTrue(any("guidance" in row["text"] for row in financial))
        values = [p for p in financial if p["financial"]]
        self.assertEqual(evidence.compare(*values, "period_trend")["percent_change"], "20")
        self.assertFalse(
            evidence.search(self.conn, self.msft, cutoff="2026-10-01T00:00:00Z", financial_documents=True)
        )

    def test_bls_zoned_schedule_and_sequence_cancellation_do_not_revive_old_reminders(self):
        def release(clock, sequence, status):
            fields = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:cpi-nov-2026",
                "SUMMARY:Consumer Price Index for November 2026",
                f"DTSTART;TZID=America/New_York:{clock}",
                f"SEQUENCE:{sequence}",
                f"STATUS:{status}",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
            return ("\r\n".join(fields) + "\r\n").encode()

        self.save("bls_calendar", release("20261210T083000", 1, "TENTATIVE"))
        first = monitor.dashboard(self.conn, at=NOW)["upcoming"][0]
        self.assertEqual((first["kind"], first["day"]), ("inflation_release", "2026-12-10T13:30:00.000000Z"))
        self.save("bls_calendar", release("20261211T083000", 2, "CONFIRMED"))
        self.save("bls_calendar", release("20261211T083000", 3, "CANCELLED"))
        self.save("bls_calendar", release("20261210T083000", 1, "TENTATIVE"))
        self.assertFalse(monitor.dashboard(self.conn, at=NOW)["upcoming"])
        self.assertEqual(events.at_commit(self.conn, first["id"])["state"], "cancelled")
        self.assertNotIn("bls_calendar", sources.recommended(self.instruments["MSFT"]))

    def test_goal_schedule_compare_and_swap_includes_ownership_in_same_transaction(self):
        original = monitor.configure(
            self.conn, self.msft, "msft_calendar", 1440, True, at=NOW, goal_managed=True, expected_id=None
        )
        self.assertEqual(
            self.conn.execute("SELECT schedule_id FROM goal_auto_sources").fetchone()[0], original
        )
        manual = monitor.configure(
            self.conn, self.msft, "msft_calendar", 60, True, at=NOW, expected_id=original
        )
        for intended in (original, manual):
            with self.assertRaises(ValueError):
                monitor.configure(
                    self.conn,
                    self.msft,
                    "msft_calendar",
                    1440,
                    False,
                    at=NOW,
                    goal_managed=True,
                    expected_id=intended,
                )
        self.assertEqual(
            self.conn.execute("SELECT id FROM monitor_schedules WHERE superseded_at IS NULL").fetchone()[0],
            manual,
        )
        self.assertEqual(self.conn.execute("SELECT count(*) FROM goal_auto_sources").fetchone()[0], 1)
