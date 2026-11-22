import hashlib
import io
import unittest
import zipfile
from unittest.mock import patch
from xml.sax.saxutils import escape

from stockinsight import db, disclosure, evidence, providers, universe


def transcript(paragraphs, title="Microsoft FY27 First Quarter Earnings Conference Call"):
    parts = [title, "Call participants", "Wednesday October 28, 2026", *paragraphs]
    xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    xml += (
        "".join("<w:p><w:r><w:t>" + escape(text) + "</w:t></w:r></w:p>" for text in parts)
        + "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as doc:
        doc.writestr("word/document.xml", xml)
    return buffer.getvalue()


class DisclosureTests(unittest.TestCase):
    def setUp(self):
        self.db = db.connect(":memory:")
        self.addCleanup(self.db.close)
        clean = b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD\nMSFT,NASDAQ,STK,USD\n"
        universe.import_snapshot(self.db, clean, complete=True)
        self.ids = {i["ticker"]: i["id"] for i in universe.universe(self.db)["instruments"]}

    def test_exact_transcript_projection_retry_cache_and_foreign_route(self):
        quote = "Organic growth depended on the prior quarter’s delivery timing."
        raw = transcript([quote, "Unselected sentence that must stay out of the database."])
        with patch.object(providers, "_fetch", return_value=raw) as wire:
            for t, url in (
                ("NVDA", disclosure.TRANSCRIPT_URL),
                ("MSFT", disclosure.TRANSCRIPT_URL + "?q=1"),
                ("MSFT", "https://elsewhere.invalid/"),
            ):
                with self.assertRaisesRegex(ValueError, "approved"):
                    disclosure.capture(self.db, self.ids[t], url, quote)
            wire.assert_not_called()
            ref = disclosure.capture(
                self.db, self.ids["MSFT"], disclosure.TRANSCRIPT_URL, quote.replace(" ", "  ")
            )
            self.assertEqual(
                disclosure.capture(self.db, self.ids["MSFT"], disclosure.TRANSCRIPT_URL, quote), ref
            )
            wire.assert_called_once()
        p = evidence.get(self.db, self.ids["MSFT"], ref)
        self.assertEqual(
            (p["text"], p["version_hash"], p["published_at"]),
            (quote, hashlib.sha256(raw).hexdigest(), "2026-10-28"),
        )
        self.assertEqual(p["available_at"], p["received_at"])
        self.assertIsNone(p["financial"])
        self.assertEqual(self.db.execute("SELECT body FROM documents").fetchone()[0], None)
        self.assertEqual(self.db.execute("SELECT status FROM source_checks").fetchone()[0], "ok")
        self.assertNotIn("Unselected sentence", repr(evidence.search(self.db, self.ids["MSFT"])))
        with (
            patch.object(providers, "_fetch") as wire,
            self.assertRaisesRegex(ValueError, "in-progress|deadline"),
        ):
            disclosure.capture(
                self.db,
                self.ids["MSFT"],
                disclosure.TRANSCRIPT_URL,
                "Unselected sentence that must stay out of the database.",
            )
        wire.assert_not_called()

    def test_routing_and_uniqueness_reject_wrong_call_missing_or_duplicate_content(self):
        q = "The operator must select a unique exact paragraph."
        raw = transcript([q, q])
        for sample in (
            raw,
            transcript(["Another unrelated paragraph."]),
            transcript([q], title="Another call"),
            b"invalid DOCX",
        ):
            with patch.object(providers, "_fetch", return_value=sample), self.assertRaises(ValueError):
                disclosure.capture(self.db, self.ids["MSFT"], disclosure.TRANSCRIPT_URL, q)
            self.db.execute("UPDATE source_checks SET started_at='2020-01-01T00:00:00.000000Z'")
        self.assertEqual(self.db.execute("SELECT count(*) FROM documents").fetchone()[0], 0)
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM source_checks WHERE status='error'").fetchone()[0], 4
        )

    def test_html_excludes_navigation_scripts_hidden_and_another_issuers_content(self):
        q = "The selected public earnings paragraph is verified."
        hidden = "This hidden sentence must not support a case."
        raw = (
            f'<html><nav><p>{q}</p></nav><div id="pressreleasecontent"><p>October 28, 2026</p>'
            f"<p>{q}</p><script>{hidden}</script><div hidden><p>{hidden}</p></div></div></html>"
        ).encode()
        with patch.object(providers, "_fetch", return_value=raw):
            ref = disclosure.capture(self.db, self.ids["MSFT"], disclosure.MSFT_RELEASE_URL, q)
            self.assertEqual(evidence.get(self.db, self.ids["MSFT"], ref)["text"], q)
            self.db.execute("UPDATE source_checks SET started_at='2020-01-01T00:00:00.000000Z'")
            with self.assertRaisesRegex(ValueError, "unique"):
                disclosure.capture(self.db, self.ids["MSFT"], disclosure.MSFT_RELEASE_URL, hidden)

    def test_full_retained_sec_bytes_require_right_registrant_and_no_network(self):
        q = "The terms of the transaction include a minimum delivery commitment."
        url = "https://www.sec.gov/Archives/edgar/data/789019/000078901924000001/test8k.htm"
        raw = (
            f'<ix:nonNumeric name="dei:EntityCentralIndexKey">789019</ix:nonNumeric>'
            f"<p>Item 1.01 Entry into an Agreement</p><p>{q}</p><p>Signatures</p>"
        ).encode()
        staged = evidence._stage(self.db, "full", raw)
        with db.write(self.db) as seq:
            evidence._save(
                self.db,
                seq,
                self.ids["MSFT"],
                "sec_filing",
                url,
                "Filed 8-K",
                staged,
                [("filing/index", q, "2024-01-03T00:00:00Z", None)],
                "2024-01-03T00:00:00Z",
                published="2024-01-02",
                precision="day",
                retention="full",
            )
        with patch.object(providers, "_fetch") as wire:
            ref = disclosure.capture(self.db, self.ids["MSFT"], url, q)
            wire.assert_not_called()
        self.assertEqual(evidence.get(self.db, self.ids["MSFT"], ref)["source_url"], url)
