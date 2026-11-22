"""Append-only sourced event observations and local commit-boundary replay."""

from contextlib import nullcontext
from datetime import date, datetime, timedelta
import re

from . import evidence, universe
from .db import instant, is_fixture, now, uid, write


_SELECT = """SELECT e.*, c.committed_at, p.document_id
             FROM event_versions e JOIN commits c ON c.seq=e.commit_seq
             JOIN evidence_passages p ON p.id=e.source_ref"""
_STATES = {"tentative", "confirmed", "postponed", "cancelled", "occurred", "unknown"}
_FIELDS = (
    "instrument_id",
    "kind",
    "state",
    "source_ref",
    "precision",
    "scheduled_start",
    "scheduled_end",
    "occurred_at",
    "source_timezone",
)


def _time(value, precision):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Supply a source date or an offset timestamp.")
    if precision == "day":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("A date-only observation requires a calendar date.")
        return date.fromisoformat(value).isoformat()
    if precision == "instant":
        return instant(value)
    raise ValueError("An unknown-time observation cannot specify a time.")


def at_commit(conn, event_id, commit_seq=None):
    """Latest visible revision in system state, irrespective of the scheduled date."""
    query = _SELECT + " WHERE e.event_id=?"
    params = [event_id]
    if commit_seq is not None:
        if type(commit_seq) is not int or commit_seq < 0:
            raise ValueError("Use a nonnegative local commit sequence.")
        query += " AND e.commit_seq<=?"
        params.append(commit_seq)
    row = conn.execute(query + " ORDER BY e.commit_seq DESC LIMIT 1", params).fetchone()
    return dict(row) if row else None


def append_event(
    conn,
    instrument_id,
    *,
    kind,
    state,
    source_ref,
    precision,
    scheduled_start=None,
    scheduled_end=None,
    occurred_at=None,
    source_timezone=None,
    supersedes=None,
    _commit_seq=None,
):
    """Save one complete edition. Revisions name the version the caller observed."""
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind):
        raise ValueError("Use a short event kind such as earnings_release.")
    if state not in _STATES or precision not in ("instant", "day", "unknown"):
        raise ValueError("Unsupported event state or source time precision.")
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError("An event observation needs an exact source passage.")
    values = (scheduled_start, scheduled_end, occurred_at)
    start, end, actual = (_time(v, precision) for v in values)
    if precision != "unknown" and not any(values):
        raise ValueError("Select unknown precision when the source gives no time.")
    if end and (not start or end < start):
        raise ValueError("Scheduled end must follow a known scheduled start.")
    if actual:
        # A date-only source may be a calendar day ahead of UTC.
        latest_day = date.fromisoformat(now()[:10]) + timedelta(days=1)
        if (
            state != "occurred"
            or (precision == "instant" and actual > now())
            or (precision == "day" and date.fromisoformat(actual) > latest_day)
        ):
            raise ValueError("Actual occurrence requires an observed event.")
    if source_timezone is not None and (
        not isinstance(source_timezone, str) or not re.fullmatch(r"[A-Za-z0-9_+:/.-]{1,80}", source_timezone)
    ):
        raise ValueError("Use the source's timezone label or leave it unknown.")
    if source_timezone is None and precision == "instant":
        offsets = {datetime.fromisoformat(v).tzname() for v in values if v is not None}
        if len(offsets) > 1:
            raise ValueError("Supply the source timezone for an interval with changing offsets.")
        source_timezone = offsets.pop()
    observation = (instrument_id, kind, state, source_ref, precision, start, end, actual, source_timezone)
    if _commit_seq is not None and not conn.in_transaction:
        raise ValueError("An existing event transaction is required.")
    with write(conn) if _commit_seq is None else nullcontext(_commit_seq) as seq:
        universe.instrument(conn, instrument_id)
        evidence.get(conn, instrument_id, source_ref, fixture=is_fixture(conn))
        if supersedes is None:
            # The same original source observation may arrive more than once.
            where = " AND ".join("e." + k + " IS ?" for k in _FIELDS)
            previous = conn.execute(
                _SELECT + " WHERE e.supersedes IS NULL AND " + where, observation
            ).fetchone()
            if previous:
                return dict(previous)
            event_id = uid("event")
        else:
            prior = conn.execute("SELECT * FROM event_versions WHERE id=?", (supersedes,)).fetchone()
            if prior is None or (prior["instrument_id"], prior["kind"]) != (instrument_id, kind):
                raise ValueError("Revision must reference a prior edition of the same event and listing.")
            event_id = prior["event_id"]
            successor = conn.execute(_SELECT + " WHERE e.supersedes=?", (supersedes,)).fetchone()
            if successor:
                if tuple(successor[k] for k in _FIELDS) == observation:
                    return dict(successor)
                raise ValueError("Event revision conflict. Read the latest edition before revising.")
        version_id = uid("event_version")
        conn.execute(
            """INSERT INTO event_versions
                     (id,event_id,supersedes,instrument_id,kind,state,source_ref,precision,scheduled_start,
                      scheduled_end,occurred_at,source_timezone,commit_seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (version_id, event_id, supersedes, *observation, seq),
        )
        return at_commit(conn, event_id, seq)
