"""Release one dated source packet into an isolated historical replay desk."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from . import assistant, backup, evidence, goals, issuer_news, monitor, proactive, universe
from .db import connect, instant, now, uid, write

FED = "https://www.federalreserve.gov/newsevents/pressreleases/monetary"
SEC = "https://www.sec.gov/Archives/edgar/data/1045810/"
RELEASE = SEC + "000104581024000262/q2fy25pr.htm"
FILING = SEC + "000104581024000264/nvda-20240728.htm"
STEPS = {
    "policy": [
        ("2024-09-12T15:00:00Z", "calendar"),
        ("2024-09-17T15:00:00Z", "meeting"),
        ("2024-09-18T18:01:00Z", "statement"),
    ],
    "company": [("2024-08-28T20:22:00Z", "earnings"), ("2024-08-28T21:06:00Z", "filing")],
    "noise": [
        ("2024-08-28T15:00:00Z", "noise"),
        ("2024-08-28T16:00:00Z", "headline"),
        ("2024-08-28T16:05:00Z", "duplicate"),
        ("2024-08-28T17:00:00Z", "clarification"),
    ],
}


def packet(step, stamp):
    if step in ("calendar", "statement"):
        outcome = step == "statement"
        published = "2024-09-18T18:00:00Z" if outcome else "2023-06-23T15:30:00Z"
        text = (
            "The FOMC reduced its target range by half a percentage point to 4.75–5 percent. "
            "One member favored a quarter-point reduction."
            if outcome
            else "The Federal Reserve's tentative calendar scheduled its September 2024 FOMC meeting for September 17–18."
        )
        meta = {
            "subject": "fomc:2024:6",
            "kind": "monetary_policy_meeting",
            "title": "FOMC policy decision" if outcome else "FOMC meeting",
            "state": "occurred" if outcome else "tentative",
            "precision": "day",
            "start": "2024-09-17",
            "end": "2024-09-18",
            "reported": "2024-09-18" if outcome else None,
            "timezone": "America/New_York",
            "origin": "Federal Reserve",
            "relevance": "A policy rate change can affect financing costs and discount rates over subsequent quarters. The issuer-specific magnitude is unknown.",
        }
        url = FED + ("20240918a.htm" if outcome else "20230623a.htm")
        return "fed_calendar", url, published, [(json.dumps(meta, sort_keys=True), text, published, None)]
    if step == "earnings":
        published = "2024-08-28T20:21:16Z"
        rows = []
        for loc, label, start, end, value in (
            ("1", "Q2 FY25", "2024-04-29", "2024-07-28", "30040"),
            ("2", "Q1 FY25", "2024-01-29", "2024-04-28", "26044"),
        ):
            fact = evidence.revenue("CIK0001045810", label, start, end, value)
            rows.append(
                (
                    "GAAP revenue / " + loc,
                    label + " GAAP revenue: " + value + " USD million.",
                    published,
                    fact,
                )
            )
        return "issuer", RELEASE, published, rows
    if step == "filing":
        published = "2024-08-28T21:05:08Z"
        text = (
            "NVIDIA reported $27.8 billion of inventory purchase and long-term supply and capacity obligations at July 28, "
            "including commitments for Hopper and Blackwell."
        )
        return (
            "historical_filing",
            FILING,
            published,
            [("10-Q / inventory purchase and capacity obligations", text, published, None)],
        )
    title = {
        "noise": "Synthetic replay: staff picnic announced",
        "headline": "Synthetic replay: issuer reports an export restriction",
        "duplicate": "Synthetic replay: issuer reports an export restriction",
        "clarification": "Synthetic replay: issuer clarifies export restriction covers one product only",
    }[step]
    name = "picnic" if step == "noise" else "export"
    pub = "Wed, 28 Aug 2024 " + ("15:00:00" if step == "noise" else "16:00:00") + " GMT"
    xml = (
        f"<rss><channel><title>Press Release - NVIDIA Newsroom</title><item><title>{title}</title>"
        f"<link>https://{issuer_news.HOST}/news/replay-{name}</link><pubDate>{pub}</pubDate></item></channel></rss>"
    ).encode()
    rows = issuer_news.rows(xml, stamp)
    return "issuer_news", "fixture:synthetic-newsroom", json.loads(rows[0][0])["published_at"], rows


def ingest(db, listing, step, stamp):
    provider, url, pub, rows = packet(step, stamp)
    raw = json.dumps([provider, url, pub, rows], sort_keys=True).encode()
    prior = db.execute(
        "SELECT id,document_id FROM source_checks WHERE instrument_id=? AND provider=? AND detail=? AND status='ok'",
        (listing["id"], provider, "Historical replay evaluated " + stamp),
    ).fetchone()
    if prior:
        monitor._observe(db, listing, provider, prior["document_id"])
        return prior["id"]
    captured = now()
    staged = evidence._stage(db, "projection", raw)
    with write(db) as seq:
        doc = evidence._save(
            db,
            seq,
            listing["id"],
            provider,
            url,
            "Replay · " + step,
            staged,
            rows,
            captured,
            published=pub[:10] if provider == "issuer" else pub,
            precision="dated replay projection",
            retention="projection",
            fixture=True,
        )
        receipt = uid("check")
        db.execute(
            "INSERT INTO source_checks VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                receipt,
                listing["id"],
                provider,
                captured,
                captured,
                "ok",
                "Historical replay evaluated " + stamp,
                doc,
                None,
                seq,
            ),
        )
    monitor._observe(db, listing, provider, doc)
    return receipt


def workspace(directory, scenario):
    if scenario not in STEPS:
        raise ValueError("Unknown replay scenario.")
    folder = backup._local_path(directory)
    path = folder / "research.sqlite3"
    label = "Historical replay · " + scenario
    if folder.exists():
        if not path.is_file():
            if any(folder.iterdir()):
                raise ValueError("Choose a new replay directory.")
        else:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as old:
                if old.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='assistant_profile'"
                ).fetchone() is None or (
                    old.execute("SELECT label FROM assistant_profile").fetchone() != (label,)
                    or old.execute("SELECT mode FROM installation").fetchone() != ("fixture",)
                ):
                    raise ValueError("Choose a dedicated replay directory.")
    db = connect(path, fixture=True)
    if assistant.profile(db)["label"] != label:
        assistant.configure(db, label)
    universe.import_snapshot(
        db, b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD", complete=True
    )
    goals.save(
        db,
        {
            "key": "historical-replay",
            "objective": "Prepare for monetary policy, earnings and export restrictions.",
            "cadence": "sunday",
            "clock": "23:50",
        },
        at=STEPS[scenario][0][0],
    )
    return db


def advance(db, scenario):
    stamp = assistant.profile(db)["replay_clock"]
    waiting = db.execute(
        "SELECT id FROM assistant_jobs WHERE state IN ('pending','running') ORDER BY rowid"
    ).fetchall()
    if waiting:
        return {"state": "awaiting assistant", "jobs": [r[0] for r in waiting], "cutoff": stamp}
    remaining = [(instant(t), step) for t, step in STEPS[scenario] if not stamp or instant(t) > stamp]
    if not remaining:
        return {"state": "finished", "cutoff": stamp}
    stamp, step = remaining[0]
    item = goals.listings(db, "watchlist")[0]
    receipt = None if step == "meeting" else ingest(db, item, step, stamp)
    for _ in range(32):
        if not proactive.tick(db, at=stamp):
            break
    else:
        raise ValueError("Replay dispatch did not settle.")
    with write(db):
        db.execute("UPDATE assistant_profile SET replay_clock=?", (stamp,))
    return {
        "state": "advanced",
        "step": step,
        "evaluated_at": stamp,
        "receipt": receipt,
        "jobs": [dict(j) for j in db.execute("SELECT id,case_id,state FROM assistant_jobs ORDER BY rowid")],
    }


def live_check(folder):
    """One first-seen public calendar check in a fresh, disposable ordinary desk."""
    folder = backup._local_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    with closing(connect(folder / "research.sqlite3", fixture=False)) as db:
        assistant.configure(db, "Live integration test")
        universe.import_snapshot(
            db, b"ticker,listing_exchange,security_type,currency\nNVDA,NASDAQ,STK,USD", complete=True
        )
        goals.save(
            db,
            {
                "key": "live-integration",
                "objective": "Prepare for upcoming monetary policy decisions.",
                "daily_limit": 1,
            },
        )
        listing = goals.listings(db, "watchlist")[0]
        checked = evidence.capture_public(db, listing, "fed_calendar")
        if checked["status"] != "ok":
            raise ValueError("Federal Reserve source check failed: " + checked["status"])
        monitor._observe(db, listing, "fed_calendar", checked["document_id"])
        for _ in range(8):
            if not proactive.tick(db):
                break
        return {
            "receipt": checked["receipt_id"],
            "jobs": [
                dict(r) for r in db.execute("SELECT id,case_id,state FROM assistant_jobs ORDER BY rowid")
            ],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=(*STEPS, "live"))
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args(argv)
    folder = args.directory or Path(".stockinsight/replays") / args.scenario
    if args.scenario == "live":
        print(json.dumps(live_check(folder), indent=2))
        return
    with closing(workspace(folder, args.scenario)) as db:
        print(json.dumps(advance(db, args.scenario), indent=2))


if __name__ == "__main__":
    main()
