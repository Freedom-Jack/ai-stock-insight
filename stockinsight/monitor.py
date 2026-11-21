"""Foreground, opt-in checks of named public sources for active watchlist listings."""

import json
import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

from . import events, evidence, issuer_news, providers, universe
from .db import connect, instant, is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE monitor_schedules(
    id INTEGER PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments, provider TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), interval_minutes INTEGER NOT NULL,
    start_at TEXT NOT NULL, expand_from TEXT NOT NULL, superseded_at TEXT,
    commit_seq INTEGER NOT NULL REFERENCES commits
);
CREATE UNIQUE INDEX monitor_current ON monitor_schedules(instrument_id,provider) WHERE superseded_at IS NULL;
CREATE TABLE monitor_occurrences(
    id TEXT PRIMARY KEY, schedule_id INTEGER NOT NULL REFERENCES monitor_schedules, scheduled_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('scheduled','catch_up')), slot_count INTEGER NOT NULL DEFAULT 1,
    last_slot TEXT, recovery_group TEXT, status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','missed','cancelled')),
    started_at TEXT, finished_at TEXT, lease_until TEXT, detail TEXT, source_status TEXT,
    source_check_id TEXT REFERENCES source_checks, document_id TEXT REFERENCES documents, cached INTEGER,
    UNIQUE(schedule_id,scheduled_at,kind)
);
CREATE INDEX monitor_due ON monitor_occurrences(status,scheduled_at);
CREATE UNIQUE INDEX monitor_one_running ON monitor_occurrences(status) WHERE status='running';
CREATE TABLE monitor_plans(
    id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments, title TEXT NOT NULL,
    scheduled_day TEXT NOT NULL, relevance TEXT NOT NULL, created_at TEXT NOT NULL,
    commit_seq INTEGER NOT NULL REFERENCES commits, UNIQUE(instrument_id,title,scheduled_day,relevance)
);
"""

HORIZON = timedelta(days=14)
DISPATCH_GRACE = timedelta(minutes=10)
LEASE = timedelta(minutes=3)
INTERVALS = (60, 240, 720, 1440, 10080)


def _stamp(value, delta=timedelta()):
    return instant((datetime.fromisoformat(value) + delta).isoformat())


def _expand(db, schedule, stamp):
    """Keep fourteen days ahead; preserve long absences as counted, exact cadence ranges."""
    step = timedelta(minutes=schedule["interval_minutes"])
    next_slot = datetime.fromisoformat(schedule["expand_from"])
    clock = datetime.fromisoformat(stamp)
    cutoff = clock - DISPATCH_GRACE
    if next_slot < cutoff:
        count = (cutoff - next_slot - timedelta(microseconds=1)) // step + 1
        last = next_slot + (count - 1) * step
        db.execute(
            """INSERT INTO monitor_occurrences(id,schedule_id,scheduled_at,last_slot,slot_count,kind,status,finished_at,detail)
               VALUES(?,?,?,?,?,'scheduled','missed',?,'Foreground scheduler was unavailable at dispatch time.')""",
            (
                uid("occ"),
                schedule["id"],
                instant(next_slot.isoformat()),
                instant(last.isoformat()),
                count,
                stamp,
            ),
        )
        next_slot += count * step
    slots = []
    while next_slot <= clock + HORIZON:
        slots.append((uid("occ"), schedule["id"], instant(next_slot.isoformat())))
        next_slot += step
    db.executemany(
        """INSERT INTO monitor_occurrences(id,schedule_id,scheduled_at,kind,status)
           VALUES(?,?,?,'scheduled','pending')""",
        slots,
    )
    db.execute(
        "UPDATE monitor_schedules SET expand_from=? WHERE id=?",
        (instant(next_slot.isoformat()), schedule["id"]),
    )


def _age(db, schedule, stamp, *, catch_up):
    db.execute(
        """UPDATE monitor_occurrences SET status='missed',finished_at=?,detail='Foreground check missed its dispatch window.'
           WHERE schedule_id=? AND status='pending' AND kind='scheduled' AND scheduled_at<?""",
        (stamp, schedule["id"], _stamp(stamp, -DISPATCH_GRACE)),
    )
    if not catch_up:
        return
    if not db.execute(
        "SELECT 1 FROM monitor_occurrences WHERE schedule_id=? AND status='missed' AND recovery_group IS NULL LIMIT 1",
        (schedule["id"],),
    ).fetchone():
        return
    # A due scheduled check can catch up the same source. An existing pending
    # catch-up can absorb another interruption; original misses remain visible.
    due = db.execute(
        """SELECT id FROM monitor_occurrences WHERE schedule_id=? AND status='pending' AND scheduled_at<=?
           ORDER BY scheduled_at LIMIT 1""",
        (schedule["id"], stamp),
    ).fetchone()
    recovery = due[0] if due else uid("occ")
    if not due:
        db.execute(
            "INSERT INTO monitor_occurrences(id,schedule_id,scheduled_at,kind,status) VALUES(?,?,?,'catch_up','pending')",
            (recovery, schedule["id"], stamp),
        )
    db.execute(
        "UPDATE monitor_occurrences SET recovery_group=? WHERE schedule_id=? AND status='missed' AND recovery_group IS NULL",
        (recovery, schedule["id"]),
    )


def configure(db, instrument_id, provider, interval_minutes, enabled, *, at=None):
    if (
        provider not in ("issuer", "issuer_news", "sec")
        or type(enabled) is not bool
        or interval_minutes not in INTERVALS
    ):
        raise ValueError("Choose a named source and supported interval.")
    stamp = instant(at or now())
    with write(db) as seq:
        listing = universe.instrument(db, instrument_id, active=enabled)
        if (
            enabled
            and not is_fixture(db)
            and (
                not listing["cik"]
                or (
                    provider in ("issuer", "issuer_news")
                    and listing["cik"] != "0001045810"
                )
            )
        ):
            raise ValueError("Choose a resolved issuer with this source route.")
        old = db.execute(
            "SELECT * FROM monitor_schedules WHERE instrument_id=? AND provider=? AND superseded_at IS NULL",
            (instrument_id, provider),
        ).fetchone()
        if old:
            if (old["interval_minutes"], bool(old["enabled"])) == (
                interval_minutes,
                enabled,
            ):
                return old["id"]
            if old["enabled"]:
                _expand(db, old, stamp)
                _age(db, old, stamp, catch_up=False)
                db.execute(
                    """UPDATE monitor_occurrences SET status='cancelled',finished_at=?,detail='Schedule changed.'
                       WHERE schedule_id=? AND status='pending'""",
                    (stamp, old["id"]),
                )
            db.execute(
                "UPDATE monitor_schedules SET superseded_at=? WHERE id=?",
                (stamp, old["id"]),
            )
        version = db.execute(
            """INSERT INTO monitor_schedules(instrument_id,provider,interval_minutes,enabled,start_at,expand_from,commit_seq)
               VALUES(?,?,?,?,?,?,?)""",
            (
                instrument_id,
                provider,
                interval_minutes,
                int(enabled),
                stamp,
                stamp,
                seq,
            ),
        ).lastrowid
        if enabled:
            _expand(
                db,
                db.execute(
                    "SELECT * FROM monitor_schedules WHERE id=?", (version,)
                ).fetchone(),
                stamp,
            )
        return version


def _due(db, stamp):
    return db.execute(
        """SELECT EXISTS(SELECT 1 FROM monitor_occurrences WHERE status='pending' AND scheduled_at<=?)
               OR EXISTS(SELECT 1 FROM monitor_occurrences WHERE status='running' AND lease_until<=?)
               OR EXISTS(SELECT 1 FROM monitor_schedules WHERE enabled AND superseded_at IS NULL AND expand_from<=?)""",
        (stamp, stamp, _stamp(stamp, HORIZON - timedelta(days=1))),
    ).fetchone()[0]


def _claim(db, stamp):
    if not _due(db, stamp):
        return None
    with write(db):
        db.execute(
            """UPDATE monitor_occurrences SET status='failed', finished_at=?, detail='Foreground check interrupted; source outcome unconfirmed.'
               WHERE status='running' AND lease_until<=?""",
            (stamp, stamp),
        )
        for schedule in db.execute(
            "SELECT * FROM monitor_schedules WHERE enabled AND superseded_at IS NULL"
        ):
            if schedule["expand_from"] <= _stamp(stamp, HORIZON - timedelta(days=1)):
                _expand(db, schedule, stamp)
            _age(db, schedule, stamp, catch_up=True)
        if db.execute(
            "SELECT 1 FROM monitor_occurrences WHERE status='running'"
        ).fetchone():
            return None
        occurrence = db.execute(
            """SELECT o.id,s.instrument_id,s.provider FROM monitor_occurrences o JOIN monitor_schedules s ON s.id=o.schedule_id
               WHERE o.status='pending' AND o.scheduled_at<=? AND s.enabled AND s.superseded_at IS NULL
               ORDER BY o.scheduled_at,o.id LIMIT 1""",
            (stamp,),
        ).fetchone()
        if occurrence:
            db.execute(
                "UPDATE monitor_occurrences SET status='running',started_at=?,lease_until=? WHERE id=?",
                (stamp, _stamp(stamp, LEASE), occurrence["id"]),
            )
        return occurrence


def _capture(db, listing, provider):
    if not is_fixture(db):
        return evidence.capture_public(db, listing, provider=provider)
    rows = evidence.search(db, listing["id"], fixture=True)
    return {
        "status": "ok" if rows else "unavailable",
        "document_id": rows[0]["document_id"] if rows else None,
        "message": "Read saved synthetic passages."
        if rows
        else "No synthetic observations for this listing.",
    }


def _observe(db, listing, provider, doc_id):
    """Record only explicit occurred dates supplied by these known source adapters."""
    if provider == "issuer_news":
        issuer_news.observe(db, listing["id"], doc_id)
        return
    rows = db.execute(
        """SELECT p.id,p.financial,d.origin,d.published_at,d.source_url FROM evidence_passages p
           JOIN documents d ON d.id=p.document_id WHERE d.id=? AND d.instrument_id=? ORDER BY p.locator,p.id""",
        (doc_id, listing["id"]),
    )
    seen = set()
    for row in rows:
        if row["origin"] == "issuer" and provider == "issuer":
            kind, day, accession = "earnings_release", row["published_at"], None
        elif row["origin"] == "sec" and provider == "sec":
            fact = json.loads(row["financial"] or "{}")
            kind, day, accession = (
                "financial_filing",
                fact.get("filed"),
                fact.get("accession"),
            )
            if not accession:
                continue
        else:
            continue
        if not day or (day, accession) in seen:
            continue
        seen.add((day, accession))
        exists = db.execute(
            """SELECT 1 FROM event_versions e JOIN evidence_passages p ON p.id=e.source_ref
               JOIN documents d ON d.id=p.document_id WHERE e.instrument_id=? AND e.kind=? AND e.occurred_at=?
               AND d.origin=? AND d.source_url=? AND json_extract(p.financial,'$.accession') IS ? LIMIT 1""",
            (listing["id"], kind, day, provider, row["source_url"], accession),
        ).fetchone()
        if not exists:
            events.append_event(
                db,
                listing["id"],
                kind=kind,
                state="occurred",
                source_ref=row["id"],
                precision="day",
                occurred_at=day,
            )


def tick(db, *, at=None):
    stamp = instant(at or now())
    occurrence = _claim(db, stamp)
    if not occurrence:
        return None
    try:
        listing = universe.instrument(db, occurrence["instrument_id"])
        result = _capture(db, listing, occurrence["provider"])
        if result.get("status") == "ok" and result.get("document_id"):
            _observe(db, listing, occurrence["provider"], result["document_id"])
    except (ValueError, OSError, sqlite3.Error):
        result = {
            "status": "unavailable",
            "message": "Listing or source check unavailable; see current membership and source status.",
        }
    finished = instant(at or now())
    state = "completed" if result["status"] == "ok" else "failed"
    with write(db):
        changed = db.execute(
            """UPDATE monitor_occurrences SET status=?,finished_at=?,detail=?,source_status=?,source_check_id=?,document_id=?,cached=?
               WHERE id=? AND status='running' AND lease_until>?""",
            (
                state,
                finished,
                result.get("message", ""),
                result["status"],
                result.get("receipt_id"),
                result.get("document_id"),
                int(bool(result.get("cached"))),
                occurrence["id"],
                finished,
            ),
        ).rowcount
    return state if changed else None


def run_foreground(path, stop_event):
    """Only the private app process runs this loop; SQLite arbitrates overlapping foreground workers."""
    with closing(connect(path)) as db:
        while not stop_event.is_set():
            try:
                work = tick(db)
            except sqlite3.Error:
                logging.getLogger(__name__).exception(
                    "Foreground monitor database unavailable"
                )
                work = None
            stop_event.wait(2 if work else 15)


def _text(data, key, limit):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Complete the event fields within their limits.")
    return value.strip()


def action(db, action, data):
    if action == "monitor-configure":
        if data.get("enabled") not in ("0", "1"):
            raise ValueError("Choose whether to enable the schedule.")
        configure(
            db,
            _text(data, "instrument_id", 96),
            _text(data, "provider", 16),
            int(_text(data, "interval_minutes", 5)),
            data["enabled"] == "1",
        )
    elif action == "monitor-event":
        day = _text(data, "day", 10)
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Enter a calendar date.")
        listing_id = _text(data, "instrument_id", 96)
        title, relevance = _text(data, "title", 100), _text(data, "relevance", 350)
        with write(db) as seq:
            universe.instrument(db, listing_id)
            db.execute(
                """INSERT INTO monitor_plans VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(instrument_id,title,scheduled_day,relevance) DO NOTHING""",
                (uid("plan"), listing_id, title, day, relevance, now(), seq),
            )
    else:
        raise ValueError("Unknown monitoring action.")
    return "/monitor"


def dashboard(db, *, at=None):
    stamp = instant(at or now())

    def rows(sql, args=()):
        return [dict(row) for row in db.execute(sql, args)]

    schedules = rows(
        """SELECT s.*,i.ticker,i.raw_label,i.listing_exchange,
           EXISTS(SELECT 1 FROM source_memberships m WHERE m.instrument_id=i.id AND m.status='active') AS active_listing
           FROM monitor_schedules s JOIN instruments i ON i.id=s.instrument_id WHERE s.superseded_at IS NULL
           ORDER BY i.raw_label,s.provider"""
    )
    next_checks = rows(
        """SELECT s.instrument_id,s.provider,i.ticker,i.raw_label,min(o.scheduled_at) AS scheduled_at FROM monitor_occurrences o
           JOIN monitor_schedules s ON s.id=o.schedule_id JOIN instruments i ON i.id=s.instrument_id
           WHERE o.status='pending' AND s.superseded_at IS NULL GROUP BY s.id ORDER BY scheduled_at LIMIT 100"""
    )
    history = rows(
        """SELECT o.*, s.instrument_id,s.provider,i.ticker,i.raw_label,c.finished_at AS source_checked_at,
                 c.retry_at,d.title AS document_title,d.source_url FROM monitor_occurrences o
           JOIN monitor_schedules s ON s.id=o.schedule_id JOIN instruments i ON i.id=s.instrument_id
           LEFT JOIN source_checks c ON c.id=o.source_check_id LEFT JOIN documents d ON d.id=o.document_id
           WHERE o.status IN ('running','completed','failed','missed')
           ORDER BY coalesce(o.finished_at,o.started_at) DESC,o.scheduled_at DESC,o.id LIMIT 60"""
    )
    plans = rows(
        """SELECT p.id,p.instrument_id,i.ticker,i.raw_label,p.title,p.scheduled_day AS day,p.relevance,
           'operator plan' AS provenance FROM monitor_plans p JOIN instruments i ON i.id=p.instrument_id
           WHERE EXISTS(SELECT 1 FROM source_memberships m WHERE m.instrument_id=i.id AND m.status='active')
           ORDER BY p.scheduled_day DESC,p.id"""
    )
    sourced = """SELECT e.event_id AS id,e.instrument_id,i.ticker,i.raw_label,
           CASE WHEN d.origin='issuer_news' THEN p.text ELSE e.kind END AS title,e.kind,e.state,
           e.scheduled_start,e.scheduled_end,e.occurred_at,e.precision,e.source_ref,d.title AS provenance,
           CASE WHEN d.origin='issuer_news' THEN json_extract(p.locator,'$.link') ELSE d.source_url END AS source_url,
           d.version_hash,p.text AS excerpt,d.received_at FROM event_versions e
           JOIN instruments i ON i.id=e.instrument_id JOIN evidence_passages p ON p.id=e.source_ref
           JOIN documents d ON d.id=p.document_id WHERE NOT EXISTS(
               SELECT 1 FROM event_versions newer WHERE newer.event_id=e.event_id AND newer.commit_seq>e.commit_seq)
           AND EXISTS(SELECT 1 FROM source_memberships m WHERE m.instrument_id=i.id AND m.status='active')"""
    upcoming = [p for p in plans if p["day"] >= stamp[:10]]
    upcoming.extend(
        rows(
            sourced
            + """ AND e.state IN ('confirmed','tentative','postponed') AND
            (e.scheduled_start IS NULL OR substr(coalesce(e.scheduled_end,e.scheduled_start),1,10)>=?)
            ORDER BY e.scheduled_start,e.event_id LIMIT 100""",
            (stamp[:10],),
        )
    )
    for observation in upcoming:
        if "day" not in observation:
            observation["day"] = observation["scheduled_start"]
            observation["relevance"] = (
                f"Named source for {observation['ticker'] or observation['raw_label']}."
            )
    upcoming.sort(key=lambda v: (v["day"] is None, v["day"] or "", v["id"]))
    recent = rows(
        sourced
        + " ORDER BY coalesce(e.occurred_at,e.scheduled_start,'') DESC,e.commit_seq DESC LIMIT 60"
    )
    return {
        "schedules": schedules,
        "next_checks": next_checks,
        "history": history,
        "upcoming": upcoming[:100],
        "events": recent,
        "past_plans": [p for p in plans if p["day"] < stamp[:10]][:30],
        "intervals": INTERVALS,
        "sec_ready": bool(providers.sec_contact()),
    }
