"""User-declared watchlist snapshots, separate instrument/company identity and local research."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from stockinsight import db, universe as u


FULL = b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\n"


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(db.FOUNDATION + u.SCHEMA)

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
        self.observe(b"ticker,conid\nACM.A,000000012345", mode="file")
        self.assertEqual(self.members()[0]["id"], before["id"])
        self.assertEqual(
            set(r[0] for r in self.conn.execute("SELECT ticker FROM instrument_aliases")), {"ACME", "ACM.A"}
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


if __name__ == "__main__":
    unittest.main()
