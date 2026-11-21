import asyncio
import copy
from contextlib import closing
import hashlib
import json
import os
from importlib.util import find_spec
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from stockinsight import db, evidence, providers, universe


SAMPLE = b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\n"


def workspace(fixture=False, path=":memory:"):
    conn = db.connect(path, fixture=fixture)
    universe.import_snapshot(conn, SAMPLE, complete=True)
    rows = conn.execute("SELECT id,ticker FROM instruments")
    return conn, {r["ticker"]: universe.instrument(conn, r["id"]) for r in rows}


class PassageTests(unittest.TestCase):
    def setUp(self):
        self.conn, self.ids = workspace(fixture=True)
        self.addCleanup(self.conn.close)
        self.nvda = self.ids["NVDA"]["id"]
        self.passages = evidence.seed_fixture(self.conn, self.nvda)

    def test_source_byte_identity_scope_fts_cutoff_and_replay(self):
        first = self.passages[0]
        doc = self.conn.execute("SELECT * FROM documents WHERE id=?", (first["document_id"],)).fetchone()
        self.assertEqual(hashlib.sha256(doc["body"]).hexdigest(), first["version_hash"])
        self.assertEqual(json.loads(doc["body"])["periods"][0]["text"], first["text"])
        self.assertEqual(
            [r["id"] for r in evidence.seed_fixture(self.conn, self.nvda)], [r["id"] for r in self.passages]
        )
        self.assertEqual(
            evidence.search(self.conn, self.nvda, query="shipment")[0]["locator"], "/qualification"
        )
        self.assertEqual(evidence.search(self.conn, self.nvda, cutoff="2024-08-28T13:29:59-07:00"), [])
        self.assertEqual(len(evidence.search(self.conn, self.nvda, cutoff="2024-08-28T13:30:00-07:00")), 3)
        self.assertEqual(evidence.search(self.conn, self.nvda, commit_seq=doc["commit_seq"] - 1), [])
        for args in [(self.ids["MSFT"]["id"], first["id"]), (self.nvda, "missing")]:
            with self.assertRaises(ValueError):
                evidence.get(self.conn, *args)
        with self.assertRaises(ValueError):
            evidence.get(self.conn, self.nvda, first["id"], fixture=False)
        with self.assertRaises(ValueError):
            evidence.seed_fixture(self.conn, self.ids["MSFT"]["id"])

    def test_revisions_and_failed_index_write_preserve_exact_earlier_input(self):
        initial = self.passages[0]

        def revision(raw, text):
            staged = evidence._stage(self.conn, "full", raw)
            with db.write(self.conn) as seq:
                return evidence._save(
                    self.conn,
                    seq,
                    self.nvda,
                    initial["origin"],
                    initial["source_url"],
                    "Revision",
                    staged,
                    [("/revision", text, "2024-09-01T12:00:00Z", None)],
                    db.now(),
                    published=None,
                    precision="unknown",
                    retention="full",
                    fixture=True,
                )

        revised = revision(b'{"revised":true}', "Revised qualification.")
        current = evidence.search(self.conn, self.nvda)
        self.assertEqual([p["document_id"] for p in current], [revised])
        self.assertEqual(current[0]["previous_version_id"], initial["document_id"])
        self.assertEqual(evidence.search(self.conn, self.nvda, cutoff="2024-08-31T00:00:00Z")[0], initial)
        self.assertEqual(evidence.get(self.conn, self.nvda, initial["id"]), initial)
        with self.assertRaises(sqlite3.IntegrityError):
            revision(b'{"invalid":true}', None)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 2)

    def test_trends_expectations_peers_and_incompatible_basis(self):
        a, b = self.passages[:2]
        trend = evidence.compare(a, b, "period_trend")
        self.assertEqual((trend["difference"], trend["percent_change"]), ("20", "20"))
        self.assertEqual(trend["input_ids"], [a["id"], b["id"]])
        other = copy.deepcopy(a)
        other["id"] = b["id"]
        other["financial"].update(role="issuer_guidance", value="96")
        other["available_at"] = "2024-07-28T00:00:00Z"
        surprise = evidence.compare(a, other, "actual_vs_expectation")
        self.assertEqual((surprise["difference"], surprise["percent_change"]), ("24", "25"))
        other["available_at"] = a["available_at"]
        with self.assertRaisesRegex(ValueError, "before"):
            evidence.compare(a, other, "actual_vs_expectation")
        other["financial"].update(role="actual", company="CIK0000789019")
        self.assertEqual(evidence.compare(a, other, "peer_comparison")["difference"], "24")
        for key, new_value in [
            ("company", "OTHER"),
            ("duration", "year_to_date"),
            ("basis", "adjusted"),
            ("currency", "EUR"),
            ("share_basis", "diluted"),
            ("unit", "USD"),
            ("value", None),
        ]:
            bad = copy.deepcopy(b)
            bad["financial"][key] = new_value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.compare(a, bad, "period_trend")
        for value in ("0", "0.00000001"):
            near_zero = copy.deepcopy(b)
            near_zero["financial"]["value"] = value
            measured = evidence.compare(a, near_zero, "period_trend")
            self.assertIsNone(measured["percent_change"])
            self.assertTrue(measured["warnings"])


def sec_packet():
    dates = [
        ("2024-01-29", "2024-04-28", 100),
        ("2024-04-29", "2024-07-28", 120),
        ("2024-01-29", "2024-07-28", 220),
    ]
    facts = [
        {
            "start": s,
            "end": e,
            "val": val,
            "filed": "2024-08-28",
            "accn": "0001045810-24-000001",
            "form": "10-Q",
        }
        for s, e, val in dates
    ]
    return {"cik": 1045810, "taxonomy": "us-gaap", "tag": providers.SEC_TAG, "units": {"USD": facts}}


class DiskSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "workspace.sqlite"
        self.conn, ids = workspace(True, path=self.path)
        self.addCleanup(self.conn.close)
        self.instrument_id = ids["NVDA"]["id"]

    def test_interrupted_stage_and_rolled_back_index_are_recoverable(self):
        with patch.object(evidence, "_publish", side_effect=OSError("simulated rename failure")):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                evidence.seed_fixture(self.conn, self.instrument_id)
        directory = self.root / "documents"
        self.assertEqual(list(directory.iterdir()), [])
        self.assertEqual(evidence.search(self.conn, self.instrument_id), [])

        # Simulate failure after durable publication but before the SQL commit.
        self.conn.execute("""CREATE TRIGGER simulate_crash BEFORE INSERT ON evidence_passages
                             BEGIN SELECT RAISE(ABORT,'injected crash'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            evidence.seed_fixture(self.conn, self.instrument_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        raw = evidence.FIXTURE_PATH.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual([f.name for f in directory.iterdir()], [digest])
        self.conn.execute("DROP TRIGGER simulate_crash")
        # Reuse only matching bytes. No second publication is necessary.
        with patch.object(evidence, "_publish", side_effect=AssertionError):
            first = evidence.seed_fixture(self.conn, self.instrument_id)[0]
        self.assertIsNone(self.conn.execute("SELECT body FROM documents").fetchone()[0])
        with closing(db.connect(self.path, fixture=True)) as reader:
            self.assertEqual(evidence.document_bytes(reader, self.instrument_id, first["document_id"]), raw)
            self.assertEqual(
                evidence.verify_documents(reader), {"checked": 1, "problems": [], "next_after": None}
            )

    def test_restore_reports_missing_tampered_and_legacy_bodies_and_pages_the_check(self):
        first = evidence.seed_fixture(self.conn, self.instrument_id)[0]
        raw = evidence.FIXTURE_PATH.read_bytes()
        target = self.root / "documents" / first["version_hash"]
        target.unlink()
        self.assertEqual(
            evidence.verify_documents(self.conn)["problems"][0]["document_id"], first["document_id"]
        )
        self.assertEqual(evidence.seed_fixture(self.conn, self.instrument_id)[0]["id"], first["id"])
        target.write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "integrity"):
            evidence.document_bytes(self.conn, self.instrument_id, first["document_id"])
        evidence.seed_fixture(self.conn, self.instrument_id)
        self.assertEqual(target.read_bytes(), raw)
        second_body = b"retained earlier embedded version"
        # Disk databases written before file-backed storage can hold a verified embedded body.
        with db.write(self.conn) as seq:
            old = evidence._save(
                self.conn,
                seq,
                self.instrument_id,
                "legacy",
                "legacy:test",
                "legacy",
                (hashlib.sha256(second_body).hexdigest(), second_body),
                [],
                db.now(),
                published=None,
                precision="unknown",
                retention="full",
            )
        check = evidence.verify_documents(self.conn, limit=1)
        self.assertEqual(check, {"checked": 1, "problems": [], "next_after": first["document_id"]})
        self.assertEqual(
            evidence.verify_documents(self.conn, after=check["next_after"]),
            {"checked": 1, "problems": [], "next_after": None},
        )
        self.assertEqual(evidence.document_bytes(self.conn, self.instrument_id, old), second_body)
        with self.assertRaises(ValueError):
            evidence.document_bytes(self.conn, "another-instrument", first["document_id"])

    def test_excerpt_only_retention_cannot_publish_or_return_page_bytes(self):
        raw = b"source content with a restricted narrative"
        staged = evidence._stage(self.conn, "selected_cells_and_hash", raw)
        with db.write(self.conn) as seq:
            document = evidence._save(
                self.conn,
                seq,
                self.instrument_id,
                "issuer",
                "issuer:test",
                "selected cells",
                staged,
                [("GAAP table", "Revenue / 120", db.now(), None)],
                db.now(),
                published=None,
                precision="unknown",
                retention="selected_cells_and_hash",
            )
        self.assertFalse((self.root / "documents").exists())
        self.assertIsNone(self.conn.execute("SELECT body FROM documents").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            evidence.document_bytes(self.conn, self.instrument_id, document)
        self.assertEqual(evidence.verify_documents(self.conn)["checked"], 0)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.conn, self.ids = workspace()
        self.addCleanup(self.conn.close)
        self.identity = self.ids["NVDA"]
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_sec_retains_version_and_exact_accession_skips_ytd_and_uses_actual_receipt(self):
        raw = json.dumps(sec_packet()).encode()

        def read(host, path, **kwargs):
            self.assertFalse(self.conn.in_transaction)
            self.assertEqual(host, "data.sec.gov")
            self.assertIn("CIK0001045810/us-gaap", path)
            return raw

        with patch.object(providers, "_fetch", side_effect=read) as fetch:
            self.assertEqual(
                evidence.capture_public(self.conn, self.identity, "sec")["status"], "unavailable"
            )
            fetch.assert_not_called()
            os.environ["STOCKINSIGHT_SEC_CONTACT"] = "test@example.org"
            capture = evidence.capture_public(self.conn, self.identity, "sec")
            self.assertEqual(capture["status"], "ok")
            self.assertTrue(evidence.capture_public(self.conn, self.identity, "sec")["cached"])
            fetch.assert_called_once()
        rows = evidence.search(self.conn, self.identity["id"], fixture=False)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["financial"]["accession"], "0001045810-24-000001")
        self.assertEqual(rows[0]["version_hash"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(rows[0]["locator"], "/units/USD/1/val")
        self.assertEqual(evidence.search(self.conn, self.identity["id"], cutoff="2024-08-29T00:00:00Z"), [])
        self.assertEqual(evidence.compare(*rows, "period_trend")["percent_change"], "20")
        with self.assertRaises(ValueError):
            evidence.seed_fixture(self.conn, self.identity["id"])

    def test_source_quota_and_malformed_responses_never_advance_document_version(self):
        os.environ["STOCKINSIGHT_SEC_CONTACT"] = "demo@example.org"
        invalid = sec_packet()
        invalid["cik"] = 1
        with patch.object(providers, "_fetch", return_value=json.dumps(invalid).encode()):
            self.assertEqual(evidence.capture_public(self.conn, self.identity, "sec")["status"], "error")
        later = "2099-01-01T00:00:00.000000Z"
        with patch.object(
            providers, "_fetch", side_effect=providers.SourceError("rate_limited", "HTTP 429", later)
        ) as fetch:
            for _ in range(2):
                self.assertEqual(evidence.capture_public(self.conn, self.identity)["status"], "rate_limited")
            fetch.assert_called_once()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT retry_at FROM source_checks WHERE provider='issuer'").fetchone()[0],
            later,
        )

    def test_issuer_refuses_units_or_header_drift(self):
        rows = [
            ["GAAP"],
            ["($ in millions, except earnings per share)", "Q2 FY25", "Q1 FY25", "Q2 FY24", "Q/Q", "Y/Y"],
            ["Revenue", "$30,040", "$26,044", "$13,507", "Up 15%", "Up 122%"],
        ]
        table = "".join("<tr><td>" + "</td><td>".join(row) + "</td></tr>" for row in rows)
        source = (
            "NVIDIA Announces Financial Results for Second Quarter Fiscal 2025<table>" + table + "</table>"
        ).encode()
        with patch.object(providers, "_fetch", return_value=source):
            result = evidence.capture_public(self.conn, self.identity)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(self.conn.execute("SELECT body FROM documents").fetchone()[0])
        with self.assertRaises(ValueError):
            evidence._issuer_rows(source.replace(b"millions", b"billions"), db.now())

    def test_fiscal_profile_probe_projects_identity_and_records_real_failures(self):
        with patch.object(providers, "_fetch") as fetch:
            self.assertEqual(providers.probe_fiscal(self.conn, self.identity)["status"], "unavailable")
            fetch.assert_not_called()
        os.environ.update(STOCKINSIGHT_FISCAL_KEY="key-in-memory-only", STOCKINSIGHT_FISCAL_INCLUDED="1")
        raw = json.dumps(
            {
                "primaryListing": {"ticker": "NVDA", "exchangeCode": "NASDAQ", "isin": "LICENSED_TEST"},
                "cik": "1045810",
            }
        ).encode()
        with patch.object(
            providers, "_fetch", side_effect=[raw, b"{}", providers.SourceError("not_entitled", "HTTP 403")]
        ):
            results = [providers.probe_fiscal(self.conn, self.identity) for _ in range(3)]
            self.assertEqual([r["status"] for r in results], ["ok", "error", "not_entitled"])
        persisted = str([tuple(r) for r in self.conn.execute("SELECT * FROM provider_attempts")])
        self.assertNotIn("LICENSED_TEST", persisted)
        self.assertNotIn("key-in-memory-only", persisted)
        self.assertIn(hashlib.sha256(raw).hexdigest(), persisted)

    def test_observed_mcp_schemas_retained_discovery_cannot_enable_tools(self):
        os.environ.update(STOCKINSIGHT_FISCAL_KEY="test", STOCKINSIGHT_FISCAL_INCLUDED="1")
        schema = [
            {
                "name": "fixture_reader",
                "inputSchema": {"type": "object", "required": ["company"]},
                "outputSchema": None,
            }
        ]
        with (
            patch.object(providers.util, "find_spec", return_value=True),
            patch.object(
                providers, "_mcp_catalog", new=AsyncMock(return_value=("fixture.protocol", schema, True))
            ),
        ):
            result = providers.discover_fiscal(self.conn)
        self.assertEqual(result["status"], "partial")
        stored = self.conn.execute("SELECT schemas FROM provider_catalogs").fetchone()
        self.assertEqual(json.loads(stored[0]), schema)
        self.assertFalse(any(c["id"] == "fixture_reader" for c in providers.capabilities()))

    @unittest.skipUnless(find_spec("mcp"), "optional Fiscal MCP SDK")
    def test_locked_sdk_negotiates_and_reads_schema_over_scoped_transport(self):
        import httpx

        reference = {"name": "example_read", "inputSchema": {"type": "object", "required": ["symbol"]}}

        def server(request):
            self.assertEqual(request.url.host, "8.8.8.8")
            self.assertEqual(request.headers["host"], providers.FISCAL_HOST)
            self.assertEqual(request.extensions["sni_hostname"], providers.FISCAL_HOST)
            self.assertEqual(request.headers["authorization"], "Bearer ephemeral-test-key")
            if request.method != "POST":
                return httpx.Response(405)
            payload = json.loads(request.content)
            if payload["method"] == "initialize":
                body = {
                    "protocolVersion": payload["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture", "version": "1"},
                }
            elif payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            else:
                self.assertEqual(payload["method"], "tools/list")
                body = {"tools": [reference]}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": body})

        public = [(2, 1, 0, "", ("8.8.8.8", 443))]
        with patch.object(providers, "_public_addresses", return_value=public):
            protocol, tools, more = asyncio.run(
                asyncio.wait_for(
                    providers._mcp_catalog("ephemeral-test-key", transport=httpx.MockTransport(server)), 7
                )
            )
        self.assertTrue(protocol)
        self.assertEqual(tools[0]["inputSchema"], reference["inputSchema"])
        self.assertFalse(more)


if __name__ == "__main__":
    unittest.main()
