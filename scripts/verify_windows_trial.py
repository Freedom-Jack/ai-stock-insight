"""Opt-in live smoke: launch the Windows trial in a NEW workspace and exercise public research in Edge."""

import argparse
import json
import socket
import sqlite3
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Thread
from time import monotonic

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
QUESTION = "Compare NVIDIA revenue for Q2 FY25 and Q1 FY25."
NEWS_QUESTION = "Which NVIDIA press releases are in the saved feed?"


@contextmanager
def desk(browser, root, *, demo=False):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            str(REPO / "Start-StockInsight.cmd"),
            "--root",
            str(root),
            "--port",
            str(port),
            "--no-browser",
            *(["--demo"] if demo else []),
        ],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    lines = Queue()

    def read_terminal():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    Thread(target=read_terminal, daemon=True).start()
    context = None
    try:
        deadline = monotonic() + 60
        while True:
            line = lines.get(timeout=max(0.1, deadline - monotonic()))
            if line is None:
                raise RuntimeError(
                    "The launcher exited before publishing its loopback address."
                )
            if line.startswith("Terminal password: "):
                password = line.partition(": ")[2].strip()
                break
        context = browser.new_context(
            viewport={"width": 1200, "height": 900},
            http_credentials={
                "origin": origin,
                "username": "research",
                "password": password,
            },
        )
        page = context.new_page()
        page.set_default_timeout(90000)
        yield origin, page
    finally:
        try:
            if context:
                stop = context.new_page()
                stop.goto(origin + "/status", timeout=15000)
                stop.get_by_text("Stop this desk", exact=True).click()
                stop.get_by_role("button", name="Stop Stock Insight").click()
                context.close()
            if process.wait(timeout=35):
                raise RuntimeError("The trial exited with an error")
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                )
            process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-parent",
        required=True,
        type=Path,
        help="Existing directory for a new smoke workspace",
    )
    args = parser.parse_args()
    root = Path(
        tempfile.mkdtemp(prefix="trial-smoke-", dir=args.output_parent)
    ).resolve()
    print("Isolated public-source verification", root, flush=True)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        with desk(browser, root) as (origin, page):
            page.goto(origin + "/today")
            page.get_by_role("link", name="Set up companies & themes").click()
            page.locator("[name=entries]").fill(
                (REPO / "stockinsight/fixtures/training-list.csv").read_text()
            )
            page.locator("[name=complete]").check()
            page.get_by_role("button", name="Import snapshot").click()
            page.get_by_role("link", name="Research", exact=True).click()
            page.locator("[name=instrument_id]").select_option(label="NVDA · NASDAQ")
            page.get_by_label("Research question").fill(QUESTION)
            page.get_by_label("Research method").select_option("device")
            page.get_by_role("button", name="Investigate", exact=True).click()
            page.get_by_role("heading", name="Financial comparison").wait_for(
                timeout=12000
            )
            assert "15.3433%" in page.locator("main").inner_text()
            page.screenshot(path=str(root / "research.png"))
            case_path = page.url.removeprefix(origin)
            page.get_by_text("Add a note", exact=True).click()
            note = page.locator('form[action="/actions/journal-note"]')
            note.get_by_label("Your note and rationale").fill(
                "Review the next comparable filing."
            )
            note.get_by_role("button", name="Save note").click()
            page.get_by_role("link", name="Research", exact=True).click()
            page.locator("[name=instrument_id]").select_option(label="NVDA · NASDAQ")
            page.get_by_label("Research question").fill(NEWS_QUESTION)
            page.get_by_label("Research method").select_option("device")
            page.get_by_role("button", name="Investigate", exact=True).click()
            page.get_by_role(
                "link", name="Issuer announcement", exact=True
            ).first.wait_for(timeout=12000)
            page.screenshot(path=str(root / "announcements.png"))
            page.get_by_role("link", name="Events & monitoring").click()
            page.get_by_text("Set a check schedule", exact=True).click()
            schedule = page.locator("form").filter(
                has=page.locator('input[value="issuer_news"]')
            )
            schedule.get_by_role("button").click()
            # Refresh through the normal view while its foreground worker handles the due task.
            deadline = monotonic() + 70
            while "completed" not in page.locator("main").inner_text().lower():
                if monotonic() >= deadline:
                    raise RuntimeError("Scheduled issuer check did not complete")
                page.wait_for_timeout(900)
                page.reload()
            page.screenshot(path=str(root / "monitor.png"))
        with desk(browser, root) as (origin, page):
            page.goto(origin + case_path)
            assert "15.3433%" in page.locator("main").inner_text()
            page.goto(origin + "/today")
            page.get_by_role("link", name=QUESTION).wait_for()
            page.get_by_role("link", name=NEWS_QUESTION).wait_for()
            page.screenshot(path=str(root / "today.png"))
            page.goto(origin + "/journal")
            page.get_by_text(
                "Review the next comparable filing.", exact=True
            ).wait_for()
        with desk(browser, root, demo=True) as (origin, page):
            page.goto(origin + "/")
            page.get_by_text("Fixture workspace · synthetic evidence", exact=True).wait_for()
            page.get_by_role("link", name="NVIDIA has fallen.", exact=False).click()
            assert "20%" in page.locator("main").inner_text()
        browser.close()
    with sqlite3.connect(root / "personal/research.sqlite3") as db:
        manifest = json.loads(
            db.execute(
                "SELECT manifest FROM briefs WHERE method='sourced_company_review.v3'"
            ).fetchone()[0]
        )
        runtime = manifest["runtime"]
        assert (
            runtime["mode"] == "on_device_model"
            and runtime["selected_plan"] in runtime["candidate_plans"]
        )
        assert (
            db.execute("SELECT count(*) FROM documents WHERE fixture=1").fetchone()[0]
            == 0
        )
        print(
            json.dumps(
                {
                    "model": runtime["actual_model"],
                    "plan": runtime["research_plan"],
                    "elapsed_ms": runtime["elapsed_ms"],
                    "receipts": db.execute(
                        "SELECT tool,status FROM receipts ORDER BY commit_seq"
                    ).fetchall(),
                    "sources": db.execute(
                        "SELECT origin,published_at,received_at,version_hash FROM documents"
                    ).fetchall(),
                    "tasks": db.execute(
                        "SELECT status,count(*) FROM monitor_occurrences GROUP BY status"
                    ).fetchall(),
                    "accepted_methods": db.execute(
                        """SELECT method,json_extract(manifest,'$.runtime.research_plan'),
                           json_array_length(body,'$.claims') FROM briefs ORDER BY commit_seq"""
                    ).fetchall(),
                    "separate_demo_verified": True,
                    "persistence_after_restart": True,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
