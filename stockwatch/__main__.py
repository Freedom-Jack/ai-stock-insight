"""Run with python -m stockwatch from the project root."""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from http.client import HTTPException
from pathlib import Path

from .config import DEFAULT_CONFIG, add_configure_command, load_config
from .followup import unlinked
from .model import now, utc
from .monitor import DEFAULT_INTERVAL, ISSUER_INTERVAL, collect_usgs, print_health, run, setting
from .operator import parse_updates
from .relevance import load_watchlist
from .report import report
from .store import connect, ingest
from .usgs import fetch_feed, parse_feed


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
DEFAULT_WATCHLIST = EXAMPLES / "watchlist.json"
LIVE_DB = Path(".stockwatch/live.sqlite3")
DEMO_DB = Path(".stockwatch/demo.sqlite3")
FIRST_RECEIPT = utc("2024-04-03T00:15:00Z")
DEMO_END = utc("2024-04-18T12:00:00Z")


def demo(args):
    if args.monitor:
        from .replay import monitor_demo
        return monitor_demo(args.db, args.watchlist_only, args.config)
    cutoff = utc(args.as_of or DEMO_END)
    observations = []
    if FIRST_RECEIPT <= cutoff:
        payload = (EXAMPLES / "usgs-taiwan-2024.geojson").read_bytes()
        observations.extend(parse_feed(payload, FIRST_RECEIPT))
    updates = json.loads((EXAMPLES / "operator-taiwan-2024.json").read_bytes())
    for update in updates:
        published = datetime.fromisoformat(utc(update["published_at"]))
        seen = utc((published + timedelta(minutes=5)).isoformat())
        if seen <= cutoff:
            observations.extend(parse_updates(json.dumps([update]).encode(), seen))
    watchlist = load_watchlist(DEFAULT_WATCHLIST)
    with closing(connect(args.db or DEMO_DB, "demo")) as db:
        added, entries = ingest(db, observations, watchlist)
        print("HISTORICAL REPLAY | Taiwan earthquake and TSMC | simulated receipts (UTC)")
        print(f"Through {cutoff}. Added {added} observations and {entries} inbox entries.")
        report(db, cutoff, history=True, portfolio=None if args.watchlist_only else EXAMPLES / "portfolio.json")


def poll(args):
    settings = load_config(args.config)
    watchlist = load_watchlist(args.watchlist) if args.watchlist else settings.watchlist
    with closing(connect(args.db, "live")) as db:
        total, added, entries, generated, seen = collect_usgs(db, watchlist, clock=now, fetch=fetch_feed)
        print(f"USGS feed generated {generated}, received {seen}. Read {total} earthquakes.")
        print(f"Added {added} observations and {entries} inbox entries.")
        print(f"Coverage: {watchlist.coverage(seen)}")
        if entries:
            # All entries in this poll share its serialized receipt time.
            report(db, seen, history=True, received_at=seen, portfolio=settings.portfolio)


def operator_import(args):
    payload = args.file.read_bytes()
    with closing(connect(args.db, "live")) as db:
        db.execute("BEGIN IMMEDIATE")
        previous_sequence = db.execute("SELECT coalesce(MAX(sequence), 0) FROM inbox").fetchone()[0]
        seen = now()
        observations = parse_updates(payload, seen)
        added, entries = ingest(db, observations)
        print(f"Added {added} operator observations and {entries} inbox entries.")
        if entries:
            report(db, seen, history=True, after_sequence=previous_sequence, portfolio=display_portfolio(args))


def display_portfolio(args):
    if getattr(args, "watchlist_only", False):
        return None
    if getattr(args, "portfolio", None):
        return args.portfolio
    try:
        return load_config(args.config).portfolio
    except (OSError, ValueError) as exc:
        print(f"WARNING | Could not load local settings. Showing public alerts. {exc}", file=sys.stderr)
        return None


def inbox(args):
    # Read-only URI also prevents inspection of a typo from creating an empty ledger.
    uri = args.db.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        mode = db.execute("SELECT value FROM settings WHERE name='mode'").fetchone()[0]
        scenario_end = setting(db, "monitor", {}).get("at", DEMO_END)
        cutoff = utc(args.as_of or (now() if mode == "live" else scenario_end))
        print(f"{mode.upper()} INBOX | through {cutoff}" + (" | simulated receipts" if mode != "live" else ""))
        if mode == "live" and not args.as_of:
            print_health(db, cutoff)
        report(db, cutoff, history=args.history, portfolio=display_portfolio(args))
        for row in unlinked(db, cutoff):
            print(f"ISSUER REVIEW | {row['title']} | {row['reason']} | {row['url']}")
        if args.audit:
            print("\nObservation audit (UTC)")
            audit = db.execute("SELECT * FROM observations WHERE seen_at<=? ORDER BY seen_at, revision, id", (cutoff,))
            for row in audit:
                print(f"  {row['seen_at']} | {row['id']} | version {row['revision']} | {row['decision']} | "
                      f"{row['rule']} config {row['watchlist_hash'][:12]} | {row['url']}")


def start(args):
    return run(args.db, load_config(args.config), interval=args.interval, issuer_interval=args.issuer_interval,
               once=args.once, open_view=args.open)


def status(args):
    if not args.db.is_file():
        print("WARNING | Coverage unknown. Start the local monitor to collect the first snapshot.")
        return 1
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        mode = db.execute("SELECT value FROM settings WHERE name='mode'").fetchone()[0]
        if mode == "demo":
            print("Reviewed historical replay. Use inbox --history to read its four source revisions.")
            return 0
        cutoff = now()
        if mode == "monitor-demo":
            cutoff = setting(db, "monitor", {}).get("at", DEMO_END)
            print(f"Simulated monitor health through {cutoff}")
        return int(bool(print_health(db, cutoff)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local, evidence-linked supplier watches")
    sub = parser.add_subparsers(dest="command", required=True)
    add_configure_command(sub)
    monitor = sub.add_parser("start", aliases=["monitor"], help="start scheduled local monitoring (Ctrl+C to stop)")
    monitor.add_argument("--once", action="store_true", help="run one full collection cycle and exit")
    monitor.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, metavar="SECONDS", help="60-900, default 300")
    monitor.add_argument("--issuer-interval", type=int, default=ISSUER_INTERVAL, metavar="SECONDS",
                         help="check the daily TWSE edition at this interval, default 3600")
    monitor.add_argument("--open", action="store_true", help="open the local alert view in your browser")
    monitor.set_defaults(run=start)
    check = sub.add_parser("status", help="check sources, heartbeat and watchlist coverage")
    check.set_defaults(run=status)
    replay = sub.add_parser("demo", help="replay the dated Taiwan case offline")
    scenario = replay.add_mutually_exclusive_group()
    scenario.add_argument("--as-of", help="inclusive ISO timestamp with timezone")
    replay.add_argument("--watchlist-only", action="store_true", help="omit the illustrative portfolio")
    scenario.add_argument("--monitor", action="store_true", help="exercise the v1 collection and automatic issuer path offline")
    replay.add_argument("--db", type=Path)
    replay.set_defaults(run=demo)
    live = sub.add_parser("poll", help="read the current USGS M4.5+ day feed once")
    live.add_argument("--watchlist", type=Path)
    live.set_defaults(run=poll)
    manual = sub.add_parser("import-update", help="attach a human-reviewed TSMC disclosure to a live watch")
    manual.add_argument("file", type=Path)
    manual.set_defaults(run=operator_import)
    for command in (live, manual, monitor, check):
        command.add_argument("--db", type=Path, default=LIVE_DB)
    show = sub.add_parser("inbox", help="read the local watches and evidence at a cutoff")
    show.add_argument("--db", type=Path, default=LIVE_DB)
    show.add_argument("--as-of", help="inclusive ISO timestamp with timezone")
    show.add_argument("--history", action="store_true", help="include earlier watch revisions")
    show.add_argument("--audit", action="store_true", help="list source versions and reasons, including suppressed observations")
    profile = show.add_mutually_exclusive_group()
    profile.add_argument("--portfolio", type=Path, help="private direct-stock snapshot, read only for display")
    profile.add_argument("--watchlist-only", action="store_true", help="omit portfolio context")
    show.set_defaults(run=inbox)
    for command in (monitor, show, live, manual, replay):
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="local Stockwatch configuration")
    args = parser.parse_args(argv)
    try:
        return args.run(args) or 0
    except (OSError, ValueError, HTTPException, sqlite3.Error) as exc:
        print(f"stockwatch: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Exchange disclosures carry their original Chinese excerpts, including when piped.
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
