"""Publisher headline research through the real case/bridge/freeze path, with scripted RSS."""

import copy
import json
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import patch

from stockinsight import announcement_research as news
from stockinsight import evidence, providers, research
from tests.test_insight_evidence import workspace

QUESTION = "Which NVIDIA press releases are in the saved feed?"
SOURCE = "https://nvidianews.nvidia.com/news/item-"


def feed(count):
    start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    items = []
    for i in range(count):
        day = format_datetime(start + timedelta(days=i))
        items.append(
            f"<item><title>Publisher headline {i}</title><link>{SOURCE}{i:02}</link><pubDate>{day}</pubDate>"
            "<description>Unread article-content marker</description></item>"
        )
    return (
        "<rss><channel><title>Press Release - NVIDIA Newsroom</title>"
        + "".join(items)
        + "</channel></rss>"
    ).encode()


class AnnouncementCases(unittest.TestCase):
    def setUp(self):
        self.db, self.listings = workspace()
        self.addCleanup(self.db.close)
        self.nvda = self.listings["NVDA"]

    def test_lookup_accepts_only_supported_scopes(self):
        for question in (
            QUESTION,
            "List NVDA's newsroom headlines.",
            "Show three NVIDIA press releases from the saved feed.",
            "Which latest NVIDIA announcements are in the retained newsroom feed?",
            "What did NVIDIA announce in the saved feed?",
            "Show the saved press releases.",
        ):
            with self.subTest(question=question):
                self.assertTrue(news.accepts(question, self.nvda))
                self.assertFalse(news.accepts(question, self.listings["MSFT"]))
        for question in (
            "What was NVIDIA's revenue in its press release?",
            "Why did NVIDIA rally after its release?",
            "Summarize the contents of the NVIDIA press releases.",
            "Show every NVIDIA press release ever.",
            "List the latest NVIDIA announcements.",
            "List five NVIDIA announcements since Monday.",
            "Show NVIDIA press releases and Microsoft's announcements.",
            "Compare the NVIDIA press releases.",
            "List seven NVIDIA press releases from the saved feed.",
            "What will NVIDIA announce next?",
        ):
            with self.subTest(question=question):
                self.assertFalse(news.accepts(question, self.nvda))

    def _run(self, question=QUESTION, cutoff=None):
        job = research.ask(self.db, self.nvda["id"], question, cutoff=cutoff)
        return research.run_job(self.db, job, engine="local")

    def _brief(self, ident):
        saved = self.db.execute(
            "SELECT body,manifest FROM briefs WHERE id=?", (ident,)
        ).fetchone()
        self.assertIsNotNone(saved)
        return tuple(json.loads(value) for value in saved)

    def test_paged_feed_freezes_dated_exact_headlines_and_checked_publisher_links(self):
        with patch.object(providers, "_fetch", return_value=feed(30)):
            brief = self._run()
        body, manifest = self._brief(brief)
        self.assertEqual(body["status"], "complete")
        self.assertIn("30 eligible headlines", body["conclusion"])
        self.assertIn("sample shows the 5 most recent", body["conclusion"])
        self.assertNotIn("Unread article-content marker", json.dumps((manifest, body)))
        headlines = manifest["assertions"]
        self.assertEqual(
            [q["source_url"] for q in headlines],
            [SOURCE + str(i) for i in range(29, 24, -1)],
        )
        self.assertEqual(headlines[0]["published_at"], "2025-01-30T12:00:00.000000Z")
        self.assertEqual(
            [q["headline"] for q in headlines], [c["text"] for c in body["claims"]]
        )
        self.assertTrue(all(q["kind"] == "issuer_announcement" for q in headlines))
        self.assertEqual(manifest["method"], news.METHOD)
        receipts = self.db.execute(
            "SELECT * FROM receipts ORDER BY commit_seq"
        ).fetchall()
        self.assertEqual(sum(r["tool"] == "get_evidence" for r in receipts), 5)
        self.assertEqual(sum(r["tool"] == "next_evidence_page" for r in receipts), 1)
        run = self.db.execute(
            "SELECT * FROM runs WHERE id=?", (receipts[0]["run_id"],)
        ).fetchone()
        with self.assertRaises(ValueError):
            forged = copy.deepcopy(body)
            forged["changes"][0] = "The company completed the investment."
            research.validate(self.db, run, forged, receipts)
        with self.assertRaises(ValueError):
            forged = copy.deepcopy(body)
            forged["claims"].reverse()
            research.validate(self.db, run, forged, receipts)

    def test_explicit_count_and_failed_update_with_prior_edition(self):
        with (
            patch.object(providers, "_fetch", return_value=feed(8)),
            patch.object(evidence, "now", return_value="2025-04-01T08:00:00Z"),
        ):
            evidence.capture_public(self.db, self.nvda, "issuer_news")
        with patch.object(
            providers,
            "_fetch",
            side_effect=providers.SourceError("unavailable", "Offline."),
        ):
            brief = self._run("Show three NVDA press releases from the saved feed.")
        body, manifest = self._brief(brief)
        self.assertEqual(body["status"], "partial")
        self.assertTrue(body["gaps"])
        self.assertIn("unsuccessful", body["conclusion"])
        self.assertIn("2025-04-01", body["conclusion"])
        self.assertEqual(len(manifest["assertions"]), 3)
        self.assertEqual(manifest["assertions"][0]["source_url"], SOURCE + "07")

    def test_insufficient_exact_count_and_explicit_up_to_scope(self):
        with patch.object(providers, "_fetch", return_value=feed(2)):
            with self.assertRaisesRegex(ValueError, "2 eligible headlines"):
                self._run("Show five NVDA press releases from the saved feed.")
            brief = self._run(
                "Show up to five headlines from NVIDIA's saved newsroom feed."
            )
        body, manifest = self._brief(brief)
        self.assertEqual(body["status"], "complete")
        self.assertEqual(len(manifest["assertions"]), 2)
        self.assertIn("2 eligible headlines", body["conclusion"])

    def test_cutoff_reconstructs_the_edition_known_then_with_original_item_url(self):
        with (
            patch.object(providers, "_fetch", return_value=feed(4)),
            patch.object(evidence, "now", return_value="2025-04-01T00:00:00Z"),
        ):
            evidence.capture_public(self.db, self.nvda, "issuer_news")
        with patch.object(providers, "_fetch", return_value=feed(2)):
            brief = self._run(cutoff="2025-04-02T00:00:00Z")
        body, manifest = self._brief(brief)
        self.assertEqual(body["status"], "complete")
        self.assertIn("4 eligible headlines", body["conclusion"])
        self.assertEqual(manifest["assertions"][0]["source_url"], SOURCE + "03")
        self.assertIn("2025-04-02", body["conclusion"])

    def test_blocked_on_outage_or_late_capture_preserves_no_headline_claim(self):
        with patch.object(
            providers,
            "_fetch",
            side_effect=providers.SourceError("unavailable", "Offline."),
        ):
            self.assertIsNone(self._run())
        draft = self.db.execute("SELECT body FROM reconciliation_drafts").fetchone()
        self.assertTrue(draft)
        self.assertEqual(json.loads(draft[0])["claims"], [])
        with patch.object(providers, "_fetch", return_value=feed(2)):
            self.assertIsNone(self._run(cutoff="2024-04-01T00:00:00Z"))
        self.assertFalse(self.db.execute("SELECT 1 FROM briefs").fetchone())
