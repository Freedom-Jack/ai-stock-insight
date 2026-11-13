import base64
import hashlib
import json
import re
import tempfile
import unittest
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from stockwatch.config import EXAMPLES, load_config
from stockwatch.localview import write_view
from stockwatch.model import Observation, utc
from stockwatch.monitor import heartbeat, set_setting
from stockwatch.store import connect, failed_poll, ingest, record_health
from stockwatch.usgs import parse_feed


NOW = utc("2024-04-03T00:15:00Z")
LATER = utc("2024-04-04T05:00:00Z")


class Page(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def attrs(self, tag):
        return [attrs for name, attrs in self.tags if tag == name]


class LocalViewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        self.db = connect(folder / "local.db", "live")
        self.addCleanup(self.db.close)
        self.path = folder / "inbox.html"
        self.watchlist = load_config().watchlist
        self.quake, = parse_feed((EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes(), NOW)

    def render(self, when=NOW, **kwargs):
        write_view(self.db, self.path, when, **kwargs)
        return self.path.read_text(encoding="utf-8")

    def test_empty_healthy_page_checks_local_heartbeat_and_refreshes(self):
        heartbeat(self.db, "running", lambda: NOW, 60, self.watchlist)
        with self.db:
            for source in ("USGS", "TSMC"):
                record_health(self.db, source, NOW, NOW)
        markup = self.render()
        self.assertIn("No watch or issuer follow-up", markup)
        self.assertIn('>Monitoring</span>', markup)
        self.assertRegex(markup, r'data-deadline="[1-9][0-9]{12}"')
        script = re.search(r"<script>(.*?)</script>", markup, flags=re.S)[1]
        self.assertIn("Date.now() > deadline", script)
        self.assertIn("location.reload()", script)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn(f"script-src 'sha256-{digest}'", markup)

    def test_degraded_stopped_and_previous_gap_are_visible(self):
        heartbeat(self.db, "stopped", lambda: LATER, 60, self.watchlist)
        with self.db:
            record_health(self.db, "USGS", NOW, NOW)
            record_health(self.db, "USGS", LATER, LATER)
        failed_poll(self.db, LATER, "<feed unavailable>", source="TSMC")
        markup = self.render(LATER)
        for text in ("Coverage warning", "Monitor stopped", "TSMC coverage degraded", "&lt;feed unavailable&gt;",
                     "Past coverage gaps", "Possible USGS gap"):
            self.assertIn(text, markup)
        self.assertIn('data-deadline="0"', markup)
        early = self.render(NOW, replay=True)
        self.assertNotIn("Past coverage gaps", early)
        self.assertNotIn("feed unavailable", early)

    def test_issuer_and_quake_alerts_have_evidence_and_keep_private_inputs_out(self):
        ingest(self.db, [self.quake], self.watchlist)
        set_setting(self.db, "private-test", {"portfolio": "private-snapshot.json", "balance": "98765.43"})
        candidate = Observation(
            id="issuer:test", revision=LATER, occurred_at=LATER, seen_at=LATER, source="TSMC",
            title="Issuer statement </h3><img src=x onerror=evil()>", url="https://example.com/document",
            kind="issuer_candidate", facts={"incident_id": self.quake.id, "supplier": "TSMC",
                "excerpt": "Localized recovery <script>alert(1)</script>", "next_check": "Read the issuer statement.",
                "uncertainty": "Customer effects are unknown."},
        )
        ingest(self.db, [candidate], self.watchlist)
        markup = self.render(LATER, replay=True)
        page = Page(markup)
        self.assertIn("Issuer statement for review", markup)
        self.assertIn("Conditional watch", markup)
        self.assertIn("Localized recovery", markup)
        self.assertIn("Read the issuer statement", markup)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertIn("Historical replay", markup)
        links = [attrs["href"] for attrs in page.attrs("a")]
        self.assertIn(candidate.url, links)
        self.assertIn(self.quake.url, links)
        self.assertTrue(all(url.startswith("https://") for url in links))
        self.assertEqual(page.attrs("img") + page.attrs("script"), [])
        early = self.render(NOW, replay=True)
        self.assertNotIn("Localized recovery", early)
        for secret in ("98765.43", "private-snapshot.json", "$15,000", "100000.00"):
            self.assertNotIn(secret, markup)

    def test_invalid_navigation_stays_text_and_exposes_no_active_content(self):
        hostile = replace(self.quake, url="javascript:alert(1)")
        ingest(self.db, [hostile], self.watchlist)
        dangerous = "https://example.com@other.test/path"
        with self.db:
            self.db.execute("INSERT INTO issuer_documents(doc_key, fingerprint, published_at, first_seen, "
                            "url,title,excerpt) VALUES (?,?,?,?,?,?,?)",
                            ("test", "hash", NOW, NOW, dangerous, "Unassigned test statement", "Public text"))
        markup = self.render()
        self.assertIn("Unassigned issuer statements", markup)
        self.assertIn("Unassigned test statement", markup)
        self.assertNotIn(dangerous, markup)
        self.assertNotIn(hostile.url, markup)
        self.assertNotIn("javascript:", json.dumps(Page(markup).attrs("a")))

    def test_failed_render_keeps_previous_file_and_releases_reader(self):
        original = self.render()
        with patch("stockwatch.localview.coverage", side_effect=ValueError("invalid data")):
            with self.assertRaises(ValueError):
                self.render()
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)
        self.assertFalse(self.db.in_transaction)
