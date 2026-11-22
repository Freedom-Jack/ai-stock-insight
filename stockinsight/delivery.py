"""Durable research-notice outbox and private, operator-configured delivery routes."""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import time
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .db import instant, is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE delivery_settings(singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));
INSERT INTO delivery_settings VALUES(1,1);
CREATE TABLE delivery_notices(
    id TEXT PRIMARY KEY, notice_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL, message TEXT NOT NULL,
    report_path TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, next_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','sending','failed','uncertain','accepted','shown','expired')),
    active_attempt TEXT, accepted_at TEXT, shown_at TEXT, open_requested_at TEXT
);
CREATE INDEX delivery_due ON delivery_notices(state,next_at);
CREATE TABLE delivery_attempts(
    id TEXT PRIMARY KEY, notice_id TEXT NOT NULL REFERENCES delivery_notices, channel TEXT NOT NULL,
    started_at TEXT NOT NULL, deadline TEXT NOT NULL, finished_at TEXT, outcome TEXT NOT NULL,
    detail TEXT NOT NULL, accepted_at TEXT, shown_at TEXT, observation TEXT
);
"""

_ID = r"[A-Za-z0-9_-]{1,96}"
_REPORT = re.compile(
    rf"/(?:today|status|journal|upcoming|goals(?:/reports/{_ID})?|cases/{_ID}|"
    rf"methods(?:\?instrument_id={_ID})?(?:#{_ID})?)\Z"
)
GENERIC_TITLE = "Stock Insight"
GENERIC_MESSAGE = "A research update is ready in your private desk."


def _later(stamp, **delta):
    return instant((datetime.fromisoformat(stamp) + timedelta(**delta)).isoformat())


def enqueue(db, *, key, title, message, report_path, at=None):
    """Join an enclosing report transaction, or commit this notice independently."""
    if not all(
        isinstance(v, str) and v.strip() and len(v) <= n
        for v, n in ((key, 200), (title, 200), (message, 2000), (report_path, 320))
    ) or not _REPORT.fullmatch(report_path):
        raise ValueError(
            "A notice requires bounded text, a stable key and a private report path."
        )
    stamp = instant(at or now())
    with nullcontext() if db.in_transaction else write(db):
        existing = db.execute(
            "SELECT * FROM delivery_notices WHERE notice_key=?", (key,)
        ).fetchone()
        if existing:
            if (title, message, report_path) != (
                existing["title"],
                existing["message"],
                existing["report_path"],
            ):
                raise ValueError(
                    "A notice key already identifies a different frozen report."
                )
            return existing["id"]
        ident = uid("notice")
        db.execute(
            """INSERT INTO delivery_notices(id,notice_key,title,message,report_path,created_at,expires_at,next_at,state)
               VALUES(?,?,?,?,?,?,?,?,'pending')""",
            (
                ident,
                key,
                title,
                message,
                report_path,
                stamp,
                _later(stamp, days=7),
                stamp,
            ),
        )
        return ident


def _channel():
    override = os.environ.get("STOCKINSIGHT_NOTIFICATION_CHANNEL")
    return override or ("windows" if os.name == "nt" else "unconfigured")


def _ntfy_config():
    endpoint = urlsplit(os.environ.get("STOCKINSIGHT_NTFY_URL", ""))
    token = os.environ.get("STOCKINSIGHT_NTFY_TOKEN", "")
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or not re.fullmatch(r"/[a-zA-Z0-9_-]{1,64}", endpoint.path)
        or not re.fullmatch(r"[!-~]{1,512}", token)
    ):
        raise ValueError(
            "Configure the private HTTPS ntfy topic and its dedicated bearer credential."
        )
    try:
        port = endpoint.port
    except ValueError:
        raise ValueError("Configure a valid HTTPS notification port.") from None
    return endpoint.hostname, port or 443, endpoint.path, token


def _available(channel):
    if channel == "windows":
        return os.name == "nt"
    if channel == "ntfy":
        try:
            _ntfy_config()
        except ValueError:
            return False
        return True
    return False


def _claim(db, stamp, channel):
    can_send = (
        not is_fixture(db)
        and _available(channel)
        and db.execute("SELECT enabled FROM delivery_settings").fetchone()[0]
    )
    due = """SELECT * FROM delivery_notices n WHERE (state='pending' OR (state='failed' AND
             (SELECT count(*) FROM delivery_attempts a WHERE a.notice_id=n.id)<6)) AND next_at<=?
             AND expires_at>? ORDER BY created_at,id LIMIT 1"""
    maintenance = db.execute(
        """SELECT 1 FROM delivery_attempts WHERE outcome='sending' AND deadline<=?
        UNION ALL SELECT 1 FROM delivery_notices WHERE state IN ('pending','failed','uncertain') AND expires_at<=? LIMIT 1""",
        (stamp, stamp),
    ).fetchone()
    if not maintenance and not (
        can_send and db.execute(due, (stamp, stamp)).fetchone()
    ):
        return None
    with write(db):
        db.execute(
            """UPDATE delivery_attempts SET outcome='uncertain', finished_at=?, detail='Dispatch interrupted; acknowledgement unavailable.'
               WHERE outcome='sending' AND deadline<=?""",
            (stamp, stamp),
        )
        db.execute("""UPDATE delivery_notices SET state='uncertain' WHERE state='sending' AND active_attempt IN
                      (SELECT id FROM delivery_attempts WHERE outcome='uncertain')""")
        db.execute(
            """UPDATE delivery_notices SET state='expired' WHERE state IN ('pending','failed','uncertain')
                      AND expires_at<=?""",
            (stamp,),
        )
        if (
            is_fixture(db)
            or not _available(channel)
            or not db.execute("SELECT enabled FROM delivery_settings").fetchone()[0]
        ):
            return None
        row = db.execute(due, (stamp, stamp)).fetchone()
        if not row:
            return None
        attempt = uid("delivery")
        db.execute(
            "UPDATE delivery_notices SET state='sending',active_attempt=? WHERE id=?",
            (attempt, row["id"]),
        )
        db.execute(
            """INSERT INTO delivery_attempts(id,notice_id,channel,started_at,deadline,outcome,detail)
                      VALUES(?,?,?,?,?,'sending','Claimed for dispatch.')""",
            (attempt, row["id"], channel, stamp, _later(stamp, seconds=50)),
        )
        return attempt, dict(row)


def _accepted(db, attempt, stamp):
    with write(db):
        db.execute(
            """UPDATE delivery_attempts SET accepted_at=coalesce(accepted_at,?)
                      WHERE id=? AND outcome='sending'""",
            (stamp, attempt),
        )
        db.execute(
            """UPDATE delivery_notices SET accepted_at=coalesce(accepted_at,?)
                      WHERE active_attempt=? AND state='sending'""",
            (stamp, attempt),
        )


def _finish(db, attempt, state, detail, *, observation=None, at=None):
    stamp = instant(at or now())
    with write(db):
        row = db.execute(
            """SELECT * FROM delivery_notices WHERE active_attempt=? AND state='sending'""",
            (attempt,),
        ).fetchone()
        if not row:
            return False
        accepted = stamp if state in ("accepted", "shown") else None
        shown = stamp if state == "shown" else None
        n = db.execute(
            "SELECT count(*) FROM delivery_attempts WHERE notice_id=?", (row["id"],)
        ).fetchone()[0]
        next_at = (
            _later(stamp, minutes=min(60, 2 ** min(n, 6)))
            if state == "failed"
            else stamp
        )
        db.execute(
            """UPDATE delivery_attempts SET finished_at=?,outcome=?,detail=?,accepted_at=coalesce(accepted_at,?),
                      shown_at=?,observation=? WHERE id=? AND outcome='sending'""",
            (
                stamp,
                state,
                detail,
                accepted,
                shown,
                json.dumps(observation) if observation else None,
                attempt,
            ),
        )
        db.execute(
            """UPDATE delivery_notices SET state=?,next_at=?,accepted_at=coalesce(accepted_at,?),
                      shown_at=coalesce(shown_at,?) WHERE id=?""",
            (state, next_at, accepted, shown, row["id"]),
        )
        return True


def _windows(db, attempt):
    db_path = db.execute("PRAGMA database_list").fetchone()["file"]
    if not db_path:
        return "failed", "Windows notices require a persistent workspace.", None
    port = os.environ.get("STOCKINSIGHT_DESK_PORT", "8765")
    if not re.fullmatch(r"[0-9]{4,5}", port) or not 1024 <= int(port) <= 65535:
        return "failed", "The private desk port is invalid.", None
    # Child reads its own frozen report path from SQLite. No financial text,
    # provider credentials or session token travel on the command line.
    env = {
        k: os.environ[k]
        for k in ("SystemRoot", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA")
        if k in os.environ
    }
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "stockinsight.windows_notice",
                db_path,
                attempt,
                port,
            ],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return (
            "failed",
            "Windows could not start the private notification process.",
            None,
        )
    _accepted(db, attempt, now())
    # The child persists the evidence before waiting for an operator click.
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        state = db.execute(
            "SELECT outcome FROM delivery_attempts WHERE id=?", (attempt,)
        ).fetchone()[0]
        if state != "sending":
            return state, None, None
        if process.poll() is not None:
            return (
                "uncertain",
                "The notification process exited without a display receipt.",
                None,
            )
        time.sleep(0.1)
    return "sending", None, None


def _ntfy():
    host, port, path, token = _ntfy_config()
    connection = http.client.HTTPSConnection(host, port, timeout=8)
    try:
        try:
            connection.connect()
        except OSError:
            return (
                "failed",
                "Could not connect to the configured notification host.",
                None,
            )
        connection.request(
            "POST",
            path,
            body=GENERIC_MESSAGE.encode(),
            headers={
                "Title": GENERIC_TITLE,
                "Authorization": "Bearer " + token,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        reply = connection.getresponse()
        if reply.status in (401, 403, 404, 429):
            return (
                "failed",
                f"Notification provider declined dispatch (HTTP {reply.status}).",
                None,
            )
        if reply.status != 200:
            return (
                "uncertain",
                f"Provider acknowledgement unverified (HTTP {reply.status}).",
                None,
            )
        raw = reply.read(8193)
        packet = json.loads(raw) if len(raw) <= 8192 else {}
        if (
            not isinstance(packet, dict)
            or packet.get("event") != "message"
            or packet.get("topic") != path[1:]
            or not isinstance(packet.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", packet["id"])
        ):
            return (
                "uncertain",
                "Provider returned no verifiable message acknowledgement.",
                None,
            )
        return (
            "accepted",
            "The private notification provider accepted the notice.",
            {"provider_receipt": packet["id"]},
        )
    except (OSError, ValueError, http.client.HTTPException):
        return (
            "uncertain",
            "Dispatch acknowledgement unavailable. Check the private subscriber before retry.",
            None,
        )
    finally:
        connection.close()


def tick(db, *, at=None):
    stamp = instant(at or now())
    channel = _channel()
    claimed = _claim(db, stamp, channel)
    if claimed is None:
        return None
    attempt, _ = claimed
    state, detail, observation = (
        _windows(db, attempt) if channel == "windows" else _ntfy()
    )
    if detail is not None:
        _finish(db, attempt, state, detail, observation=observation, at=at)
    return state


def dashboard(db):
    channel = _channel()
    return {
        "enabled": bool(
            db.execute("SELECT enabled FROM delivery_settings").fetchone()[0]
        ),
        "channel": channel,
        "available": _available(channel) and not is_fixture(db),
        "notices": [
            dict(r)
            for r in db.execute(
                "SELECT * FROM delivery_notices ORDER BY created_at DESC,id LIMIT 60"
            )
        ],
        "attempts": [
            dict(r)
            for r in db.execute(
                "SELECT * FROM delivery_attempts ORDER BY started_at DESC,id LIMIT 100"
            )
        ],
    }


def action(db, action, data):
    if action == "delivery-configure" and data.get("enabled") in ("0", "1"):
        with write(db):
            db.execute(
                "UPDATE delivery_settings SET enabled=?", (int(data["enabled"]),)
            )
    elif action == "delivery-test":
        key = data.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", key):
            raise ValueError("Supply the notification test request key.")
        enqueue(
            db,
            key="test:" + key,
            title="Channel test",
            message="Check the private delivery route.",
            report_path="/status",
        )
    elif action == "delivery-retry":
        with write(db):
            stamp = instant(now())
            row = db.execute(
                "SELECT * FROM delivery_notices WHERE id=?", (data.get("id"),)
            ).fetchone()
            if (
                not row
                or row["expires_at"] <= stamp
                or row["state"] not in ("failed", "uncertain")
            ):
                raise ValueError(
                    "Only a current failed or uncertain notice can be retried."
                )
            if row["state"] == "uncertain" and data.get("confirm") != "1":
                raise ValueError(
                    "An earlier delivery may have reached you. Confirm the possible duplicate to retry."
                )
            db.execute(
                "UPDATE delivery_notices SET state='pending',next_at=? WHERE id=?",
                (stamp, row["id"]),
            )
    else:
        raise ValueError("Unknown notification action or setting.")
    return "/status"
