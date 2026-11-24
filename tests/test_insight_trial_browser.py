"""Run the operator's fixture trial in a browser against two fresh desk processes."""

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, contextmanager
from datetime import date, timedelta
from importlib.util import find_spec
from pathlib import Path
from queue import Queue
from threading import Thread
from urllib.parse import urlsplit

from stockinsight.__main__ import DEMO_QUESTION
from stockinsight.evidence import FIXTURE_PATH

QUESTION = "Compare NVIDIA revenue in Q2 FY25 and Q1 FY25."
NOTE = "I want to separate shipment timing from recurring demand."
CONDITION = "Revisit after another quarter of reported revenue."
PREPARATION = "Read the next earnings release"


@contextmanager
def foreground_desk(browser, folder):
    """Start the real foreground launcher and use its one-time terminal password."""
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    launcher = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "stockinsight",
            "--data-dir",
            str(folder),
            "--fixture",
            "serve",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    startup = Queue(maxsize=1)

    def read_password():
        for line in launcher.stdout:
            if line.startswith("Terminal password: "):
                startup.put(line.split(": ", 1)[1].strip())
                return
        startup.put(None)

    try:
        reader = Thread(target=read_password, daemon=True)
        reader.start()
        password = startup.get(timeout=20)
        if not password:
            raise RuntimeError(
                "Fixture desk exited before opening its loopback listener"
            )
        credentials = {"username": "research", "password": password, "origin": origin}
        with browser.new_context(http_credentials=credentials) as context:
            page = context.new_page()
            page.set_default_timeout(6000)
            page.goto(origin + "/today")
            yield page
    finally:
        # Stop the actual process to check disk persistence and recover its queued follow-up.
        launcher.terminate()
        launcher.wait(timeout=10)
        launcher.stdout.close()


@unittest.skipUnless(
    find_spec("playwright"), "Install the browser-test dependency group"
)
class ForegroundTrialTest(unittest.TestCase):
    def check_monitor_history(self, page):
        """Poll the rendered desk until its foreground dispatcher has checked both listings."""
        page.get_by_role("navigation").get_by_role(
            "link", name="Events & monitoring"
        ).click()
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            success = page.get_by_text("NVDA · ISSUER · completed", exact=True)
            failure = page.get_by_text("MSFT · ISSUER · failed", exact=True)
            if success.is_visible() and failure.is_visible():
                break
            time.sleep(0.4)
            page.reload()
        self.assertTrue(
            success.is_visible(), "The enabled NVDA source check did not finish."
        )
        self.assertTrue(
            failure.is_visible(),
            "A listing without fixture data should show a failed check.",
        )
        nvda = page.locator("article").filter(has=success)
        msft = page.locator("article").filter(has=failure)
        self.assertIn("Source result ok", nvda.inner_text())
        self.assertIn("Source result unavailable", msft.inner_text())
        self.assertTrue(
            nvda.get_by_role(
                "link", name="Synthetic NVIDIA quarterly revenue exercise"
            ).is_visible()
        )

    def check_source(self, brief, page):
        citation = brief.locator("summary").filter(has_text="/periods/0/text").first
        citation.click()
        passage = citation.locator("xpath=..")
        self.assertIn(
            "Q2 FY25 GAAP revenue was USD 120 million",
            passage.locator("blockquote").inner_text(),
        )
        passage.get_by_text("Source version", exact=True).click()
        expected = FIXTURE_PATH.read_bytes()
        self.assertEqual(
            passage.locator("code").inner_text(), hashlib.sha256(expected).hexdigest()
        )
        with page.expect_download() as download:
            passage.get_by_role("link", name="Download retained version").click()
        self.assertEqual(download.value.path().read_bytes(), expected)

    def test_monitor_investigate_journal_queue_restart_and_continue(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as directory, sync_playwright() as driver:
            folder = Path(directory)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "stockinsight",
                    "--data-dir",
                    str(folder),
                    "--fixture",
                    "demo",
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            channel = os.environ.get(
                "STOCKINSIGHT_TEST_BROWSER", "msedge" if os.name == "nt" else "chromium"
            )
            with driver.chromium.launch(channel=channel, headless=True) as browser:
                with foreground_desk(browser, folder) as page:
                    nav = page.get_by_role("navigation")
                    self.assertTrue(
                        page.get_by_text(
                            "Fixture workspace · synthetic evidence"
                        ).is_visible()
                    )
                    nav.get_by_role("link", name="Events & monitoring").click()
                    for ticker in ("NVDA", "MSFT"):
                        page.get_by_text("Set a check schedule", exact=True).click()
                        route = page.get_by_role(
                            "group", name="NVIDIA historical issuer release"
                        )
                        route.get_by_label("Listing").select_option(
                            label=ticker + " · NASDAQ"
                        )
                        route.get_by_role(
                            "button", name="Save and enable checks"
                        ).click()
                    page.get_by_text("Add a dated event to your plan").click()
                    event = page.locator("form[action='/actions/monitor-event']")
                    event.get_by_role("combobox").select_option(label="NVDA · NASDAQ")
                    event.get_by_label("Event or preparation task").fill(PREPARATION)
                    event.get_by_label("Planned day").fill(
                        (date.today() + timedelta(days=7)).isoformat()
                    )
                    event.get_by_label("Why it matters").fill(
                        "Check the issuer's reported revenue and outlook."
                    )
                    event.get_by_role("button", name="Add to plan").click()
                    nav.get_by_role("link", name="Today", exact=True).click()
                    self.assertIn(PREPARATION, page.locator("main").inner_text())

                    nav.get_by_role("link", name="Research", exact=True).click()
                    page.get_by_label("Listing").select_option(label="NVDA · NASDAQ")
                    page.get_by_label("Research question").fill(QUESTION)
                    page.get_by_role("button", name="Investigate", exact=True).click()
                    original = urlsplit(page.url).path
                    self.assertTrue(original.startswith("/cases/"))
                    revision = page.locator("article").filter(
                        has=page.get_by_role("heading", name="Assessment")
                    )
                    self.assertIn("20%", revision.inner_text())
                    self.check_source(revision, page)
                    page.get_by_role(
                        "button", name="Mark this revision reviewed"
                    ).click()

                    page.get_by_text("Add a note", exact=True).click()
                    note = page.locator("form[action='/actions/journal-note']")
                    note.get_by_label("Your note and rationale").fill(NOTE)
                    note.get_by_text("Set a review condition").click()
                    note.get_by_label("What would prompt another look?").fill(CONDITION)
                    note.get_by_role("button", name="Save note").click()
                    self.assertTrue(page.get_by_text(NOTE, exact=True).is_visible())
                    page.get_by_text("Plan a follow-up question", exact=True).click()
                    page.get_by_label("Question to investigate").fill(DEMO_QUESTION)
                    page.get_by_role("button", name="Save planned question").click()
                    nav.get_by_role(
                        "link", name="Upcoming research", exact=True
                    ).click()
                    pending = page.locator("article").filter(
                        has=page.get_by_text(DEMO_QUESTION, exact=True)
                    )
                    self.assertIn("Pending investigation", pending.inner_text())
                    pending.get_by_role(
                        "button", name="Queue investigation with current evidence"
                    ).click()
                    child = urlsplit(page.url).path
                    self.assertNotEqual(original, child)
                    self.assertTrue(
                        page.get_by_role(
                            "button", name="Run or recover job"
                        ).is_visible()
                    )
                    self.assertTrue(page.get_by_text("ready", exact=True).is_visible())
                    self.check_monitor_history(page)

                with foreground_desk(browser, folder) as page:
                    nav = page.get_by_role("navigation")
                    self.assertIn(PREPARATION, page.locator("main").inner_text())
                    nav.get_by_role("link", name="Journal", exact=True).click()
                    note = page.locator("article").filter(
                        has=page.get_by_text(NOTE, exact=True)
                    )
                    self.assertIn("Research judgment · You", note.inner_text())
                    self.assertIn("Revision 1", note.inner_text())
                    self.assertIn(CONDITION, note.inner_text())
                    plan = page.locator("article").filter(
                        has=page.get_by_text(DEMO_QUESTION, exact=True)
                    )
                    self.assertIn("Latest job ready", plan.inner_text())
                    plan.get_by_role(
                        "link", name="Open follow-up investigation"
                    ).click()
                    self.assertEqual(urlsplit(page.url).path, child)
                    page.get_by_role("button", name="Run or recover job").click()
                    self.assertTrue(
                        page.get_by_role(
                            "heading", name="Missing evidence"
                        ).is_visible()
                    )
                    self.assertTrue(
                        page.get_by_text("partial", exact=True).is_visible()
                    )
                    nav.get_by_role("link", name="Journal", exact=True).click()
                    self.assertIn("Investigated through revision 1", plan.inner_text())
                    nav.get_by_role(
                        "link", name="Upcoming research", exact=True
                    ).click()
                    self.assertFalse(
                        page.get_by_text(DEMO_QUESTION, exact=True).is_visible()
                    )

                    nav.get_by_role("link", name="Journal", exact=True).click()
                    note.get_by_role("link", name=QUESTION, exact=True).click()
                    self.assertEqual(urlsplit(page.url).path, original)
                    page.get_by_role("button", name="Investigate again").click()
                    briefs = page.locator("article").filter(
                        has=page.get_by_role("heading", name="Assessment")
                    )
                    self.assertEqual(briefs.count(), 2)
                    self.assertIn("Revision 2", briefs.first.inner_text())
                    self.assertIn("Marked reviewed", briefs.last.inner_text())
                    self.check_source(briefs.last, page)
                    briefs.first.get_by_text(
                        "Method and tool receipts", exact=True
                    ).click()
                    self.assertIn("compare_financials", briefs.first.inner_text())
                    self.assertIn("Revision 1", note.inner_text())
                    self.check_monitor_history(page)
