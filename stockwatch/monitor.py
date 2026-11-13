"""Foreground scheduling, independent source health and local alert delivery."""

import json
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError

from .followup import poll_issuer, unlinked
from .model import now, utc
from .report import report
from .store import connect, coverage_gaps, failed_poll, ingest
from .usgs import fetch_feed, generated_at, parse_feed


SOURCES = ("USGS", "TSMC")
SOURCE_ERRORS = (ValueError, OSError, HTTPException)
DEFAULT_INTERVAL = 300
ISSUER_INTERVAL = 3600
COLLECTION_ERRORS = SOURCE_ERRORS + (sqlite3.Error,)


def collect_usgs(db, watchlist, *, clock=now, fetch=fetch_feed):
    """Return total earthquakes, new observations, entries, feed time and receipt."""
    db.execute("BEGIN IMMEDIATE")
    try:
        payload = fetch()
        seen = utc(clock())
        generated = generated_at(payload)
        if datetime.fromisoformat(seen) - datetime.fromisoformat(generated) > timedelta(minutes=15):
            raise ValueError(f"feed generated {generated} is over 15 minutes old")
        observations = parse_feed(payload, seen)
        added, entries = ingest(db, observations, watchlist, poll=(seen, generated))
    except COLLECTION_ERRORS as exc:
        db.rollback()
        failed_poll(db, clock(), str(exc))
        raise
    return len(observations), added, entries, generated, seen


def setting(db, name, default=None):
    row = db.execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(db, name, value):
    with db:
        db.execute("INSERT INTO settings(name,value) VALUES (?,?) "
                   "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (name, json.dumps(value)))


@contextmanager
def scheduler_lock(path):
    """A process-scoped SQLite file lock, automatically released even on a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path) + ".monitor-lock", timeout=0)) as lock:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                raise ValueError(f"a monitor is already running for {path}") from exc
            raise
        yield


def heartbeat(db, state, clock, interval, watchlist, issuer_interval=ISSUER_INTERVAL):
    when = utc(clock())
    set_setting(db, "monitor", {
        "state": state, "at": when, "interval": interval, "coverage": watchlist.coverage(when),
        "gaps": watchlist.coverage_gaps(when), "issuer_interval": issuer_interval,
    })


def coverage(db, cutoff):
    """Current monitor state and warnings, including a dead or sleeping collector."""
    stamp = datetime.fromisoformat(utc(cutoff))
    run = setting(db, "monitor", {})
    interval = run.get("interval", DEFAULT_INTERVAL)
    warnings = list(run.get("gaps", []))
    view_error = setting(db, "view_error")
    if view_error:
        warnings.append(f"Local HTML inbox update failed. Terminal delivery is active. {view_error}")
    if run.get("state") == "stopped":
        warnings.append("Monitor stopped. Start it again to resume scheduled collection.")
    if run.get("state") == "running":
        age = stamp - datetime.fromisoformat(run["at"])
        if age > timedelta(seconds=interval + 120):
            warnings.append("Monitor heartbeat overdue. Check the process and whether this computer was asleep.")
    health = {row["source"]: dict(row) for row in db.execute("SELECT * FROM feed_health")}
    for source in SOURCES:
        row = health.get(source)
        if row and row["error"]:
            warnings.append(f"{source} coverage degraded at {row['attempt']}: {row['error']}")
        elif not row or not row["last_ok"]:
            warnings.append(f"{source} coverage unknown. No valid collection recorded.")
        elif stamp - datetime.fromisoformat(row["last_ok"]) > timedelta(seconds=(
                max(900, interval + 120) if source == "USGS"
                else run.get("issuer_interval", ISSUER_INTERVAL) + interval + 120)):
            warnings.append(f"{source} coverage stale. Last successful poll was {row['last_ok']}.")
    return run, health, warnings


def print_health(db, cutoff):
    run, health, warnings = coverage(db, cutoff)
    if run:
        print(f"Monitor {run['state']} at {run['at']} | interval {run['interval']} seconds")
        print(f"Watchlist: {run['coverage']}")
    for source in SOURCES:
        if source in health:
            row = health[source]
            print(f"{source} last valid receipt: {row['last_ok'] or 'none'}"
                  + (f" | source snapshot: {row['generated']}" if row["generated"] else ""))
    for message in warnings:
        print(f"WARNING | {message}")
    for gap in coverage_gaps(db):
        print(f"Past coverage gap | {gap}")
    return warnings


def deliver_pending(db, cutoff, portfolio):
    """Print committed entries. Flush before acknowledging the terminal cursor."""
    cursor = setting(db, "terminal_sequence", 0)
    last = db.execute("SELECT MAX(sequence) FROM inbox JOIN observations USING(id,revision) "
                      "WHERE seen_at<=?", (cutoff,)).fetchone()[0]
    if last is not None and last > cursor:
        print("\nLOCAL ALERT", flush=True)
        report(db, cutoff, history=True, portfolio=portfolio, after_sequence=cursor)
        sys.stdout.flush()
        set_setting(db, "terminal_sequence", last)

    reviewed = setting(db, "terminal_issuer_edition", 0)
    for row in reversed(unlinked(db, cutoff, after_edition=reviewed, limit=-1)):
        print(f"ISSUER REVIEW | {row['title']} | {row['reason']} | {row['url']}", flush=True)
    newest = db.execute("SELECT MAX(edition) FROM issuer_documents WHERE first_seen<=?", (cutoff,)).fetchone()[0]
    if newest and newest > reviewed:
        set_setting(db, "terminal_issuer_edition", newest)


def _retry_after(error, when):
    hint = (getattr(error, "headers", None) or {}).get("Retry-After", "")
    if hint:
        try:
            if hint.strip().isdigit():
                deadline = datetime.fromisoformat(when) + timedelta(seconds=int(hint))
            else:
                deadline = parsedate_to_datetime(hint)
            return utc(deadline.isoformat())
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def cycle(db, settings, *, clock=now, quake_fetch=fetch_feed, issuer_fetch=None, issuer_due=True):
    """Both sources get an attempt, even if the first fails or finds no matches."""
    counts = {}
    for source in SOURCES:
        if source == "TSMC" and not issuer_due:
            continue
        retry_at = setting(db, f"retry_{source}")
        if retry_at and utc(clock()) < retry_at:
            print(f"WARNING | {source} waiting until {retry_at} as requested by the source.", flush=True)
            continue
        previous = db.execute("SELECT error FROM feed_health WHERE source=?", (source,)).fetchone()
        try:
            if source == "USGS":
                _, docs, entries, _, _ = collect_usgs(db, settings.watchlist, clock=clock, fetch=quake_fetch)
            elif issuer_fetch is None:
                docs, entries = poll_issuer(db, clock=clock)
            else:
                docs, entries = poll_issuer(db, clock=clock, fetch=issuer_fetch)
            counts[source] = (docs, entries)
        except SOURCE_ERRORS as exc:
            deadline = _retry_after(exc, utc(clock()))
            if deadline:
                set_setting(db, f"retry_{source}", deadline)
            print(f"WARNING | {source} coverage degraded. {exc}", flush=True)
            if isinstance(exc, HTTPError):
                exc.close()
        else:
            if previous and previous["error"]:
                print(f"COVERAGE RESTORED | {source} | {clock()}", flush=True)
        deliver_pending(db, utc(clock()), settings.portfolio)
    return counts


def issuer_is_due(db, when, issuer_interval):
    prior = db.execute("SELECT last_ok,error FROM feed_health WHERE source='TSMC'").fetchone()
    if not prior or not prior["last_ok"] or prior["error"]:
        return True
    return datetime.fromisoformat(when) - datetime.fromisoformat(prior["last_ok"]) >= timedelta(seconds=issuer_interval)


def publish_view(db, view, cutoff):
    from .localview import write_view

    previous = setting(db, "view_error")
    if previous:
        set_setting(db, "view_error", None)
    try:
        write_view(db, view, cutoff)
    except OSError as exc:
        set_setting(db, "view_error", str(exc))
        print(f"WARNING | Could not update the local HTML inbox. {exc}", flush=True)
        return False
    if previous:
        print("Local HTML inbox restored.", flush=True)
    return True


def run(db_path: Path, settings, *, interval=DEFAULT_INTERVAL, issuer_interval=ISSUER_INTERVAL, once=False, open_view=False,
        clock=now, wait=time.sleep, monotonic=time.monotonic, quake_fetch=fetch_feed, issuer_fetch=None):
    if not 60 <= interval <= 900:
        raise ValueError("collection interval must be between 60 and 900 seconds")
    if not interval <= issuer_interval <= 12 * 3600:
        raise ValueError("issuer interval must be at least the collection interval and at most 43200 seconds")
    view = Path(str(db_path) + ".alerts.html").resolve()
    with scheduler_lock(db_path), closing(connect(db_path, "live")) as db:
        state = "one-shot" if once else "running"
        heartbeat(db, state, clock, interval, settings.watchlist, issuer_interval)
        published = publish_view(db, view, utc(clock()))
        print(f"Stockwatch | local alert inbox: {view.as_uri()}", flush=True)
        print(f"Tickers: {', '.join(settings.tickers)} | USGS every {interval}s, TSMC every {issuer_interval}s | "
              + ("one collection" if once else "Ctrl+C to stop"), flush=True)
        if open_view and published:
            import webbrowser
            try:
                if not webbrowser.open(view.as_uri()):
                    print("Open the inbox file above to view alerts in a browser.", flush=True)
            except (OSError, webbrowser.Error) as exc:
                print(f"Could not open the browser. Terminal delivery is active. {exc}", flush=True)
        try:
            deliver_pending(db, utc(clock()), settings.portfolio)
            while True:
                started = monotonic()
                due = once or issuer_is_due(db, utc(clock()), issuer_interval)
                counts = cycle(db, settings, clock=clock, quake_fetch=quake_fetch, issuer_fetch=issuer_fetch, issuer_due=due)
                heartbeat(db, state, clock, interval, settings.watchlist, issuer_interval)
                cutoff = utc(clock())
                publish_view(db, view, cutoff)
                gaps = coverage_gaps(db)
                if gaps != setting(db, "announced_gaps", []):
                    for gap in gaps:
                        print(f"Past coverage gap | {gap}", flush=True)
                    set_setting(db, "announced_gaps", gaps)
                for message in settings.watchlist.coverage_gaps(cutoff):
                    print(f"WARNING | {message}", flush=True)
                summary = ", ".join(f"{source} {docs} new / {entries} alerts"
                                    for source, (docs, entries) in counts.items())
                print(f"Cycle {cutoff} | {summary or 'no successful collection this cycle'}", flush=True)
                if once:
                    return 1 if coverage(db, cutoff)[2] else 0
                delay = interval - (monotonic() - started)
                wait(delay if delay > 0 else interval)
        except KeyboardInterrupt:
            print("\nStopping local collection.", flush=True)
        finally:
            db.rollback()
            if not once:
                heartbeat(db, "stopped", clock, interval, settings.watchlist, issuer_interval)
                publish_view(db, view, utc(clock()))
    return 0
