"""Private research database, independently versioned from Stockwatch."""

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def instant(value):
    if not isinstance(value, str):
        raise ValueError("Expected a timestamp with a timezone")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Expected a timestamp with a timezone")
    return stamp.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def uid(prefix):
    return f"{prefix}_{secrets.token_hex(12)}"


@contextmanager
def write(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        seq = conn.execute("INSERT INTO commits(committed_at) VALUES (?)", (now(),)).lastrowid
        yield seq
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


FOUNDATION = """
CREATE TABLE migrations(version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL);
CREATE TABLE installation(mode TEXT NOT NULL CHECK(mode IN ('fixture','local_trial')));
CREATE TABLE commits(seq INTEGER PRIMARY KEY AUTOINCREMENT, committed_at TEXT NOT NULL);
CREATE TABLE event_versions(
    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, supersedes TEXT UNIQUE REFERENCES event_versions,
    instrument_id TEXT NOT NULL REFERENCES instruments(id), kind TEXT NOT NULL, state TEXT NOT NULL,
    scheduled_start TEXT, scheduled_end TEXT, occurred_at TEXT, source_timezone TEXT,
    precision TEXT NOT NULL, source_ref TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits
);
"""


def _apply(conn, script):
    # executescript() can commit an existing transaction. Execute whole SQL
    # statements here so every table and the migration stamp share one commit.
    statement = []
    for char in script:
        statement.append(char)
        if char == ";" and sqlite3.complete_statement("".join(statement)):
            conn.execute("".join(statement))
            statement.clear()
    if "".join(statement).strip():
        raise ValueError("Incomplete schema migration")


def migrations():
    from . import agenda, assistant, delivery, evidence, exposure, gaps, goals, journal, memory, methods, monitor, research, sources_calendar, universe

    return [
        FOUNDATION + universe.SCHEMA + evidence.SCHEMA + research.SCHEMA,
        universe.IDENTITY_MIGRATION + gaps.MIGRATION,
        journal.SCHEMA + monitor.SCHEMA,
        goals.SCHEMA + sources_calendar.SCHEMA + methods.SCHEMA + delivery.SCHEMA,
        memory.SCHEMA,
        agenda.SCHEMA,
        exposure.SCHEMA,
        goals.LINKED_EVENTS,
        goals.SHARED_DELIVERY,
        assistant.SCHEMA,
    ]


def connect(path, *, fixture=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        scripts = migrations()
        db.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and "migrations" not in tables:
            raise ValueError("Choose a separate Stock Insight database")
        applied = dict(db.execute("SELECT version,sha256 FROM migrations")) if tables else {}
        if sorted(applied) != list(range(1, len(applied) + 1)) or len(applied) > len(scripts):
            raise ValueError("Unrecognized database schema version")
        for version, script in enumerate(scripts, 1):
            checksum = hashlib.sha256(script.encode()).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise ValueError("Schema checksum mismatch")
                continue
            _apply(db, script)
            db.execute("INSERT INTO migrations VALUES (?,?,?)", (version, checksum, now()))
        if not tables:
            db.execute("INSERT INTO installation VALUES (?)", ("fixture" if fixture else "local_trial",))
        elif fixture is not None and fixture != is_fixture(db):
            raise ValueError("Select a separate workspace for fixture and live research")
        db.commit()
        return db
    except BaseException:
        db.close()
        raise


def is_fixture(conn):
    return conn.execute("SELECT mode FROM installation").fetchone()[0] == "fixture"
