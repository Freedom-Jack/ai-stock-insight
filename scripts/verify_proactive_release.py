"""Check public-source research and review persistence with the browser closed."""

import argparse
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from verify_windows_trial import launcher


def sign_in(browser, origin, password):
    context = browser.new_context(
        http_credentials={
            "origin": origin,
            "username": "research",
            "password": password,
        },
        viewport={"width": 1240, "height": 900},
    )
    return context.new_page()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-parent", type=Path, required=True)
    root = Path(
        tempfile.mkdtemp(prefix="proactive-release-", dir=parser.parse_args().output_parent)
    ).resolve()
    print("Fresh acceptance workspace", root, flush=True)
    proof = {}
    with sync_playwright() as driver, launcher(root) as (origin, password):
        edge = driver.chromium.launch(channel="msedge", headless=True)
        page = sign_in(edge, origin, password)
        page.goto(origin + "/universe")
        page.locator("[name=entries]").fill(
            "ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD"
        )
        page.locator("[name=complete]").check()
        page.get_by_role("button", name="Import snapshot").click()
        page.goto(origin + "/goals")
        page.get_by_label("Standing research goal").fill(
            "Keep me prepared for important developments affecting my watchlist."
        )
        page.get_by_role("button", name="Adopt goal").click()
        edge.close()
        closed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        proof["browser_closed_at"] = closed_at
        path = root / "personal/research.sqlite3"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            deadline = time.monotonic() + 220
            while time.monotonic() < deadline:
                row = db.execute("""SELECT id,runtime,method_report,ended_at FROM goal_dispatch
                    WHERE state='complete' AND kind='event' AND ended_at>?
                    ORDER BY ended_at LIMIT 1""", (closed_at,)).fetchone()
                if row and "report_id" not in proof:
                    proof.update(report_id=row["id"], method_id=row["method_report"],
                                 ended_at=row["ended_at"], worker=json.loads(row["runtime"]))
                if (
                    proof.get("report_id")
                    and db.execute("SELECT 1 FROM goal_context_reads LIMIT 1").fetchone()
                ):
                    break
                time.sleep(0.25)
            if not proof.get("report_id"):
                print(
                    "Dispatch states",
                    [tuple(r) for r in db.execute("SELECT kind,state,detail FROM goal_dispatch LIMIT 8")],
                )
                raise RuntimeError(
                    "No completed research report after closing the browser"
                )
            assert db.execute("SELECT count(*) FROM goal_context_reads").fetchone()[0] > 0
            assert proof["worker"]["mode"] == "on_device_model"
            proof["checks"] = [
                dict(r)
                for r in db.execute("SELECT id,provider,status,finished_at,document_id FROM source_checks")
            ]
            proof["context_reads"] = db.execute("SELECT count(*) FROM goal_context_reads").fetchone()[0]
            proof["before_review"] = db.execute(
                "SELECT reviewed_at FROM goal_dispatch WHERE id=?",
                (proof["report_id"],),
            ).fetchone()[0]
            assert proof["before_review"] is None
        edge = driver.chromium.launch(channel="msedge", headless=True)
        page = sign_in(edge, origin, password)
        page.goto(origin + "/goals/reports/" + proof["report_id"])
        page.get_by_role("heading", name="Evidence and interpretation").wait_for()
        page.locator("details").filter(has=page.locator('a[rel="noreferrer"]')).first.locator(
            "summary"
        ).click()
        assert page.get_by_role("link", name="Original source").count()
        page.screenshot(path=str(root / "report.png"))
        page.get_by_role("button", name="Mark report reviewed").click()
        page.get_by_text("Reviewed ", exact=False).first.wait_for()
        for route in (
            "goals",
            "agenda",
            "exposures",
            "methods",
            "monitor",
            "today",
            "status",
        ):
            response = page.goto(origin + "/" + route)
            assert response.status == 200, route
            page.screenshot(path=str(root / (route + ".png")))
        edge.close()
    with launcher(root) as (origin, password), closing(sqlite3.connect(path)) as db:
        assert db.execute(
            "SELECT reviewed_at FROM goal_dispatch WHERE id=?", (proof["report_id"],)
        ).fetchone()[0]
        assert (
            db.execute(
                "SELECT count(*) FROM delivery_notices WHERE notice_key=?",
                ("goal:" + proof["report_id"],),
            ).fetchone()[0]
            == 1
        )
    proof["restart_verified"] = True
    (root / "verification.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
