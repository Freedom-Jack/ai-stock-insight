"""User-declared watchlist snapshots, separate instrument/company identity and local research."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from stockinsight import db, research
from stockinsight import universe as u

FULL = b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\n"


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(db.FOUNDATION + u.SCHEMA + u.IDENTITY_MIGRATION)

    def observe(self, raw, **kwargs):
        return u.import_snapshot(self.conn, raw, complete=kwargs.pop("complete", True), **kwargs)

    def members(self):
        return u.universe(self.conn)["instruments"]

    def test_project_before_retention_and_keep_safe_diagnostics(self):
        good = self.observe(FULL)
        sensitive = (
            b"ticker,account,position,balance,password\nSECRETCO,U98765432,90431,12345,hunter_example\n"
        )
        rejected = self.observe(sensitive)
        self.assertEqual(
            (rejected["state"], rejected["content_hash"], rejected["entries"]), ("rejected", None, [])
        )
        persisted = "\n".join(self.conn.iterdump())
        for token in ("U98765432", "SECRETCO", "90431", "hunter_example"):
            self.assertNotIn(token, persisted)
            self.assertNotIn(token, json.dumps(u.universe(self.conn)))
        for invalid in (
            b"MSFT\nU98765432",
            b"MSFT\n=PRICE",
            b"ticker,ticker\nNVDA,MSFT",
            b"NVDA,NASDAQ\n",
            b"ticker,conid\nMSFT",
            b"NVDA\n123456",
            b"ticker,listing_exchange\nNVDA,SMART",
            b"\xff",
        ):
            self.assertEqual(self.observe(invalid)["state"], "rejected", repr(invalid))
        source = u.universe(self.conn)["sources"][0]
        self.assertEqual((source["active_snapshot_id"], source["status"]), (good["id"], "needs_review"))
        self.assertEqual({item["ticker"] for item in self.members()}, {"NVDA", "MSFT"})

    def test_candidate_review_fences_partial_empty_and_duplicate(self):
        accepted = self.observe(FULL)
        self.assertEqual(accepted["id"], self.observe(FULL)["id"])
        part = self.observe(b"NVDA", complete=False)
        with self.assertRaises(ValueError):
            u.accept_candidate(self.conn, part["id"])
        empty = self.observe(b"")
        self.assertEqual((empty["state"], empty["added"], empty["removed"]), ("candidate", 0, 2))
        self.assertEqual(self.observe(b"")["id"], empty["id"])
        remove_one = self.observe(FULL.split(b"MSFT")[0])
        with self.assertRaises(ValueError):
            u.accept_candidate(self.conn, empty["id"])
        previous = u.universe(self.conn)
        self.assertEqual(previous["sources"][0]["active_snapshot_id"], accepted["id"])
        self.assertEqual(previous["candidates"][0]["id"], remove_one["id"])
        self.assertEqual(u.accept_candidate(self.conn, remove_one["id"])["acceptance"], "confirmed")
        self.assertEqual([i["ticker"] for i in self.members()], ["NVDA"])
        self.assertEqual(u.accept_candidate(self.conn, remove_one["id"])["state"], "complete")
        empty = self.observe(b"")
        u.accept_candidate(self.conn, empty["id"])
        self.assertEqual(self.members(), [])
        self.assertEqual(self.observe(FULL)["state"], "complete")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM instruments").fetchone()[0], 2)

    def test_contract_stability_aliases_and_opaque_ids(self):
        self.observe(b"ticker,conid,security_type\nACME,000000012345,STK")
        before = self.members()[0]
        self.observe(b"conid\n000000012345")
        only = self.members()[0]
        self.assertEqual((only["id"], only["ticker"], only["conid"]), (before["id"], "ACME", "000000012345"))
        corrected = self.observe(b"ticker,conid\nACM.A,000000012345", mode="file")
        self.assertTrue(corrected["confirmable"])
        self.assertEqual(self.members()[0]["ticker"], "ACME")
        self.assertEqual(corrected["affected"][0]["action"], "correct")
        self.assertIn("ACME", corrected["affected"][0]["label"])
        self.assertIn("ACM.A", corrected["affected"][0]["label"])
        u.accept_candidate(self.conn, corrected["id"])
        self.assertEqual(self.members()[0]["id"], before["id"])
        audit = self.conn.execute("SELECT * FROM instrument_corrections").fetchone()
        self.assertEqual((audit["snapshot_id"], audit["instrument_id"]), (corrected["id"], before["id"]))
        self.assertEqual(
            (json.loads(audit["before_fields"])["ticker"], json.loads(audit["after_fields"])["ticker"]),
            ("ACME", "ACM.A"),
        )
        self.assertEqual(
            {r[0] for r in self.conn.execute("SELECT ticker FROM instrument_aliases")}, {"ACME", "ACM.A"}
        )
        source = u.universe(self.conn)["sources"][0]
        self.assertEqual(
            (source["mode"], source["authority"], source["external_list_id"]), ("file", "external", None)
        )

    def test_duplicate_listing_enrichment_and_source_rename(self):
        header = b"ticker,listing_exchange,security_type,currency,conid\n"
        result = self.observe(header + b"NVDA,NASDAQ,STK,USD,\nNVDA,NASDAQ,STK,USD,000123\n,,,,000123")
        self.assertEqual((result["added"], len(result["entries"]), len(self.members())), (1, 1, 1))
        self.assertEqual(self.members()[0]["conid"], "000123")
        u.rename_source(self.conn, "personal", "Semiconductors")
        self.observe(header + b"NVDA,NASDAQ,STK,USD,", source_id="new_list")
        u.rename_source(self.conn, "new_list", "Semiconductors")
        self.assertEqual(self.members()[0]["source_ids"], ["new_list", "personal"])
        ambiguous = self.observe(
            header + b"NVDA,NASDAQ,STK,USD,\nNVDA,NASDAQ,STK,USD,000123\nNVDA,NASDAQ,STK,USD,000124"
        )
        self.assertEqual((ambiguous["state"], self.members()[0]["conid"]), ("rejected", "000123"))

    def test_ticker_collisions_provisional_unsupported_and_routing(self):
        self.observe(
            b"ticker,listing_exchange,security_type,currency,routing_exchange\n"
            b"ABC,NASDAQ,STK,USD,SMART\nABC,LSE,STK,GBP,SMART\n"
            b"ABC,,OPT,USD,SMART\nABC.B,NASDAQ,STK,USD,SMART\nNVDA,,,,SMART"
        )
        items = self.members()
        self.assertEqual(len({i["id"] for i in items}), 5)
        provisional = next(i for i in items if i["ticker"] == "NVDA")
        self.assertIsNone(provisional["cik"])
        self.assertIsNone(provisional["listing_exchange"])
        self.assertEqual(provisional["resolution_status"], "provisional")
        self.assertEqual(
            next(i for i in items if i["security_type"] == "OPT")["resolution_status"], "unclassified"
        )
        self.observe(b"NVDA", source_id="second")
        self.assertEqual(len([i for i in self.members() if i["ticker"] == "NVDA"]), 2)

    def test_missing_listing_fields_and_changed_issuer_cannot_silently_reassign(self):
        self.observe(
            b"ticker,listing_exchange,security_type,currency,conid\n"
            b"NVDA,NASDAQ,STK,USD,123456\nMSFT,NASDAQ,STK,USD,987654\nOTHER,NYSE,STK,USD,765432"
        )
        conflict = self.observe(
            b"ticker,listing_exchange,security_type,currency,conid\nMSFT,NASDAQ,STK,USD,123456"
        )
        self.assertEqual(conflict["state"], "rejected")
        weak = self.observe(b"ticker,conid\nNVDA,\nMSFT,987654\nOTHER,765432")
        self.assertEqual((weak["state"], weak["removed"]), ("candidate", 1))
        self.assertEqual(len(self.members()), 3)

    def test_removal_preserves_other_sources_company_theme_and_exposure(self):
        self.observe(FULL)
        nvda = next(i for i in self.members() if i["ticker"] == "NVDA")
        msft = next(i for i in self.members() if i["ticker"] == "MSFT")
        self.observe(FULL.split(b"MSFT")[0], source_id="second", mode="file")
        theme = u.create_theme(self.conn, "Capex", "How does spending change over time?")
        membership = u.link_theme(
            self.conn, theme, company_id=nvda["company_id"], reason="User selected issuer."
        )
        exposure = u.record_exposure(
            self.conn,
            nvda["company_id"],
            msft["company_id"],
            relation="hypothesis",
            uncertainty="Customer concentration is unknown.",
        )
        with self.assertRaises(ValueError):
            u.record_exposure(
                self.conn,
                nvda["company_id"],
                msft["company_id"],
                relation="customer",
                uncertainty="Unknown.",
                supported=True,
            )
        u.accept_candidate(self.conn, self.observe(b"")["id"])
        self.assertEqual(u.instrument(self.conn, nvda["id"])["source_ids"], ["second"])
        with self.assertRaises(ValueError):
            u.instrument(self.conn, msft["id"])
        self.assertEqual(u.instrument(self.conn, msft["id"], active=False)["company_id"], msft["company_id"])
        u.accept_candidate(self.conn, self.observe(b"", source_id="second")["id"])
        view = u.universe(self.conn)
        self.assertEqual(view["instruments"], [])
        self.assertEqual(view["theme_memberships"][0]["id"], membership)
        self.assertEqual(view["exposures"][0]["id"], exposure)

    def test_unavailable_unstable_and_stale_input_preserve_active_set(self):
        with patch.object(u, "now", return_value="2020-01-01T00:00:00Z"):
            good = self.observe(FULL)
        self.assertEqual(u.universe(self.conn)["sources"][0]["status"], "stale")
        with tempfile.TemporaryDirectory() as td:
            selected = Path(td) / "private-selected-source-not-for-log.csv"
            result = u.import_file(self.conn, selected, complete=True)
            self.assertEqual(result["state"], "rejected")
            selected.write_bytes(FULL)
            with patch.object(u.time, "sleep", side_effect=lambda t: selected.write_bytes(b"ticker\nNVDA\n")):
                self.assertEqual(u.import_file(self.conn, selected, complete=True)["state"], "rejected")
            source = u.universe(self.conn)["sources"][0]
            self.assertEqual((source["active_snapshot_id"], source["status"]), (good["id"], "unavailable"))
            self.assertNotIn(str(selected), "\n".join(self.conn.iterdump()))
            with patch.object(u.time, "sleep"):
                self.assertEqual(u.import_file(self.conn, selected, complete=True)["state"], "candidate")

    def test_atomic_membership_replacement_rolls_back_interrupted_activation(self):
        self.observe(FULL)
        before = "\n".join(self.conn.iterdump())
        self.conn.execute("""CREATE TEMP TRIGGER fail_insert BEFORE INSERT ON source_memberships
                             BEGIN SELECT RAISE(ABORT, 'injected'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.observe(FULL + b"ACME,NYSE,STK,USD\n")
        self.assertEqual("\n".join(self.conn.iterdump()), before)
        self.assertFalse(self.conn.in_transaction)

    def test_fully_qualified_cash_listing_and_account_report_boundaries(self):
        header = b"ticker,listing_exchange,security_type,currency,conid\n"
        good = self.observe(header + b"CASH,NASDAQ,STK,USD,0444\nMSFT,NASDAQ,STK,USD,")
        self.assertEqual(good["state"], "complete")
        cash = next(i for i in self.members() if i["ticker"] == "CASH")
        self.assertEqual(
            (cash["listing_exchange"], cash["resolution_status"]), ("NASDAQ", "identified_listing")
        )
        self.assertEqual(self.observe(b"ticker,conid\nCASH,0444", source_id="second")["state"], "complete")
        for raw in (
            b"CASH",
            b"ticker,conid\nCASH,unknown",
            b"ticker,cash,quantity\nCASH,991771,112339",
        ):
            rejected = self.observe(raw)
            self.assertEqual(
                (rejected["state"], rejected["entries"], rejected["content_hash"]), ("rejected", [], None)
            )
        source = next(s for s in u.universe(self.conn)["sources"] if s["id"] == "personal")
        self.assertEqual(source["active_snapshot_id"], good["id"])
        self.assertNotIn("991771", "\n".join(self.conn.iterdump()))

    def test_ticker_column_admits_qualified_london_and_us_listings_alongside_msft(self):
        for source, listing, exchange, currency in (
            ("london", "PNL", "XLON", "GBX"),
            ("london_control", "PCT", "XLON", "GBX"),
            ("united_states", "CASH", "NASDAQ", "USD"),
        ):
            with self.subTest(listing=listing):
                packet = (
                    f"ticker,listing_exchange,security_type,currency\r\n"
                    f'"{listing.lower()}",{exchange},STK,{currency}\r\nMSFT,NASDAQ,STK,USD\r\n'
                ).encode("utf-8-sig")
                snapshot = self.observe(packet, source_id=source)
                self.assertEqual((snapshot["state"], len(snapshot["entries"])), ("complete", 2))
                members = [i for i in self.members() if source in i["source_ids"]]
                self.assertEqual({i["ticker"] for i in members}, {listing, "MSFT"})
                item = next(i for i in members if i["ticker"] == listing)
                self.assertEqual(
                    (item["listing_exchange"], item["currency"], item["security_type"]),
                    (exchange, currency, "STK"),
                )
                self.assertEqual(item["resolution_status"], "identified_listing")
        self.assertEqual(len([i for i in self.members() if i["ticker"] == "MSFT"]), 1)

    def test_explicit_symbol_column_preserves_provisional_and_unsupported_identity(self):
        symbols = self.observe(b"ticker\nPNL\nCASH\nPCT", source_id="symbols")
        listing = self.observe(
            b"ticker,listing_exchange,security_type,currency\nPNL,XLON,STK,GBX", source_id="listed"
        )
        self.assertEqual((symbols["state"], listing["state"]), ("complete", "complete"))
        incomplete = [i for i in self.members() if i["source_ids"] == ["symbols"]]
        self.assertEqual({i["ticker"] for i in incomplete}, {"PNL", "CASH", "PCT"})
        self.assertTrue(
            all(i["resolution_status"] == "provisional" and i["company_id"] is None for i in incomplete)
        )
        self.assertEqual(len([i for i in self.members() if i["ticker"] == "PNL"]), 2)
        contract = self.observe(b"ticker,conid\nCASH,09888", source_id="broker_contract")
        self.assertEqual(contract["state"], "complete")
        unresolved = next(i for i in self.members() if i["source_ids"] == ["broker_contract"])
        self.assertEqual((unresolved["conid"], unresolved["resolution_status"]), ("09888", "provisional"))
        fx = self.observe(b"ticker,security_type,currency\nEUR,CASH,USD", source_id="unsupported")
        self.assertEqual(fx["state"], "complete")
        self.assertEqual(
            next(i for i in self.members() if i["ticker"] == "EUR")["resolution_status"], "unclassified"
        )
        ambiguous = self.observe(b"PNL", source_id="symbols")
        self.assertEqual(ambiguous["state"], "rejected")
        self.assertIn("ticker column", ambiguous["reason"])

    def test_private_reports_or_mixed_invalid_rows_preserve_last_list_and_leave_no_payload(self):
        listing = self.observe(
            b"ticker,listing_exchange,security_type,currency\nPNL,XLON,STK,GBX\nMSFT,NASDAQ,STK,USD"
        )
        before = self.members()
        marker = "SENTRY"
        account = "DU876543"
        rows = [
            f"ticker,account,quantity\nPNL,{account},100\n{marker},{account},500",
            f"PNL,position,pnl\n{marker},240,193",
            f"pnl\n991700\n{marker}",
            f"ticker,conid\n{marker},003381\nPNL,{account}",
            f"ticker,listing_exchange,security_type,currency\n{marker},XLON,STK,GBX\nCASH,X{account},STK,USD",
            f"ticker,listing_exchange,security_type,currency\n{marker},XLON,STK,GBX\nPNL,ACCOUNT,POSITIONS,USD",
            f"ticker,listing_exchange,security_type,currency\n{marker},XLON,STK,GBX\nPNL,ACCOUNT,STK,GBX",
            f"ticker,listing_exchange\n{marker},XLON\nACCOUNT,BALANCE",
            f"ticker,routing_exchange\n{marker},SMART\nPNL,{account}Y",
            f"ticker\n{marker}\n=PRIVATEFORMULA()",
        ]
        for encoded in rows:
            failed = self.observe(encoded.encode())
            self.assertEqual(
                (failed["state"], failed["entries"], failed["content_hash"]), ("rejected", [], None)
            )
            self.assertEqual(self.members(), before)
            self.assertEqual(u.universe(self.conn)["sources"][0]["active_snapshot_id"], listing["id"])
            diagnostics = json.dumps(failed).upper()
            for private in (account, marker, "991700", "003381", "PRIVATEFORMULA"):
                self.assertNotIn(private, diagnostics)
                self.assertNotIn(private.encode(), self.conn.serialize().upper())

    def test_embedded_account_identifiers_do_not_enter_sql_or_diagnostics(self):
        self.observe(FULL)
        token = "U654321"
        with self.assertRaises(ValueError) as problem:
            self.observe(FULL, source_id=f"sample_{token.lower()}_source")
        with self.assertRaises(ValueError) as alias:
            u.rename_source(self.conn, "personal", "Sample " + token + " alias")
        rejects = [
            self.observe(("AB" + token + "X").encode()),
            self.observe(
                ("ticker,listing_exchange,security_type,currency\nSAFE,AB" + token + "X,STK,USD").encode()
            ),
        ]
        self.assertTrue(
            all(r["state"] == "rejected" and not r["entries"] and not r["content_hash"] for r in rejects)
        )
        for view in (
            str(problem.exception),
            str(alias.exception),
            json.dumps(rejects),
            json.dumps(u.universe(self.conn)),
            "\n".join(self.conn.iterdump()),
        ):
            self.assertNotIn(token, view.upper())
        self.assertNotIn(token.encode(), self.conn.serialize().upper())

    def test_changed_binding_across_sources_preserves_previous_issuer_and_case(self):
        head = b"ticker,listing_exchange,security_type,currency,conid\n"
        first = b"ALFA,NASDAQ,STK,USD,\nBETA,NYSE,STK,USD,"
        replacement = b"NVDA,NASDAQ,STK,USD,0111"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "workspace.sqlite3"
            with closing(db.connect(path, fixture=True)) as conn:
                active_a = u.import_snapshot(conn, head + first, source_id="source_a", complete=True)
                candidate = u.import_snapshot(conn, head + replacement, source_id="source_a", complete=True)
                self.assertTrue(candidate["confirmable"])
                self.assertEqual(candidate["source_alias"], "source_a")
                self.assertEqual(
                    {(a["action"], a["label"].split(" · ")[0]) for a in candidate["affected"]},
                    {("add", "NVDA"), ("remove", "ALFA"), ("remove", "BETA")},
                )
            with closing(db.connect(path)) as other:
                active_b = u.import_snapshot(
                    other, head + b"MSFT,NASDAQ,STK,USD,0111", source_id="source_b", complete=True
                )
                saved = next(i for i in u.universe(other)["instruments"] if i["ticker"] == "MSFT")
                job = research.ask(other, saved["id"], "What revenue was reported?")
            with closing(db.connect(path)) as conn:
                self.assertFalse(u.universe(conn)["candidates"][0]["confirmable"])
                self.assertEqual(u.accept_candidate(conn, candidate["id"])["state"], "rejected")
                case = conn.execute(
                    "SELECT c.instrument_id FROM cases c JOIN jobs j ON j.case_id=c.id WHERE j.id=?", (job,)
                ).fetchone()
                subject = u.instrument(conn, case["instrument_id"])
                self.assertEqual(
                    (subject["ticker"], subject["cik"], subject["source_ids"]),
                    ("MSFT", "0000789019", ["source_b"]),
                )
                self.assertEqual(
                    {s["id"]: s["active_snapshot_id"] for s in u.universe(conn)["sources"]},
                    {"source_a": active_a["id"], "source_b": active_b["id"]},
                )
                direct = u.import_snapshot(conn, head + replacement, source_id="source_c", complete=True)
                self.assertEqual(direct["state"], "rejected")
                positive = u.import_snapshot(
                    conn, head + b"MSFT,NASDAQ,STK,USD,0111", source_id="source_c", complete=True
                )
                self.assertEqual(positive["state"], "complete")
                self.assertEqual(u.instrument(conn, saved["id"])["source_ids"], ["source_b", "source_c"])

    def test_compatible_new_binding_requires_a_fresh_preview_then_can_be_accepted(self):
        self.observe(b"FIRST\nSECOND", source_id="alpha")
        raw = b"ticker,listing_exchange,security_type,currency,conid\nMSFT,NASDAQ,STK,USD,1234"
        original = self.observe(raw, source_id="alpha")
        self.observe(raw, source_id="beta")
        self.assertEqual(u.accept_candidate(self.conn, original["id"])["state"], "rejected")
        updated = self.observe(raw, source_id="alpha")
        self.assertNotEqual(original["id"], updated["id"])
        addition = next(a for a in updated["affected"] if a["action"] == "add")
        self.assertTrue(addition["instrument_id"])
        self.assertEqual(u.accept_candidate(self.conn, updated["id"])["state"], "complete")
        self.assertEqual(u.instrument(self.conn, addition["instrument_id"])["source_ids"], ["alpha", "beta"])

    def test_pending_v1_candidate_requires_fresh_binding_preview_after_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "earlier.sqlite3"
            # A complete-but-empty v1 observation has no frozen binding set.
            with (
                patch.object(db, "migrations", return_value=[db.migrations()[0]]),
                closing(db.connect(path)) as old,
                db.write(old) as seq,
            ):
                old.execute(
                    """INSERT INTO watchlist_sources
                        (id,alias,authority,provider,mode,status,commit_seq)
                        VALUES('external_list','Selected list','external','ibkr','file','needs_review',?)""",
                    (seq,),
                )
                old.execute(
                    """INSERT INTO watchlist_snapshots(id,source_id,observed_at,mode,content_hash,
                        entries,membership_complete,state,reason,added,removed,commit_seq)
                        VALUES('pending_v1','external_list',?,'file',?,'[]',1,'candidate','Review empty list',0,0,?)""",
                    (db.now(), hashlib.sha256(b"[]").hexdigest(), seq),
                )
                old.execute("UPDATE watchlist_sources SET last_observation_id='pending_v1'")
            with closing(db.connect(path)) as upgraded:
                self.assertFalse(u.universe(upgraded)["candidates"][0]["confirmable"])
                again = u.import_snapshot(
                    upgraded, b"", complete=True, mode="file", source_id="external_list"
                )
                self.assertNotEqual(again["id"], "pending_v1")
                self.assertTrue(again["confirmable"])
                with self.assertRaises(ValueError):
                    u.accept_candidate(upgraded, "pending_v1")
                self.assertEqual(u.accept_candidate(upgraded, again["id"])["state"], "complete")

    def test_unsupported_cross_source_metadata_and_duplicate_bindings_cannot_replace_stored_identity(self):
        header = b"ticker,listing_exchange,security_type,currency,conid\n"
        self.observe(header + b"OLD,NYSE,STK,USD,2222\nNEW,NYSE,STK,USD,3333")
        same = self.observe(b"conid\n2222", source_id="another")
        self.assertEqual(same["state"], "complete")
        for conflict in (
            header + b"OTHER,NYSE,STK,USD,2222",
            header + b"OLD,NYSE,STK,USD,9999",
            b"conid,ticker\n2222,NEW",
            header + b"SAME,NYSE,STK,USD,1234\nSAME,NYSE,STK,USD,1235",
        ):
            self.assertEqual(self.observe(conflict)["state"], "rejected")
        self.assertEqual(
            {(i["ticker"], i["conid"]) for i in self.members()}, {("OLD", "2222"), ("NEW", "3333")}
        )


if __name__ == "__main__":
    unittest.main()
