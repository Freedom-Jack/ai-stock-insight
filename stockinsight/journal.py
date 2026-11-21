"""Private user-authored notes, review conditions and queued follow-up questions."""

import re
from datetime import date

from . import research, universe, workspace
from .db import now, uid, write

SCHEMA = """
CREATE TABLE journal_entries (
    id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    case_id TEXT REFERENCES cases(id), brief_id TEXT REFERENCES briefs(id),
    kind TEXT NOT NULL CHECK(kind IN ('judgment','intention','reported_action','review','question')),
    author TEXT NOT NULL CHECK(author='user'), body TEXT NOT NULL,
    review_on TEXT, next_source INTEGER NOT NULL CHECK(next_source IN (0,1)), condition_text TEXT NOT NULL,
    review_of_id TEXT REFERENCES journal_entries(id), request_key TEXT NOT NULL UNIQUE,
    launch_key TEXT UNIQUE, created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits(seq),
    CHECK ((kind='question') = (launch_key IS NOT NULL)),
    CHECK (brief_id IS NULL OR case_id IS NOT NULL),
    CHECK (review_of_id IS NULL OR kind='review')
);
CREATE INDEX journal_case_entries ON journal_entries(case_id,commit_seq);
CREATE INDEX journal_review_target ON journal_entries(review_of_id);
"""

LABELS = {
    "judgment": "Research judgment",
    "intention": "Stated intention",
    "reported_action": "Reported action",
    "review": "Review note",
    "question": "Planned question",
}


def _text(value, field, limit, *, optional=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not optional and not value.strip())
    ):
        raise ValueError(f"Invalid {field}.")
    return value.strip()


def _scope(conn, scope, *, active=True):
    category, _, item_id = scope.partition(":")
    if category == "case":
        case = conn.execute(
            "SELECT instrument_id FROM cases WHERE id=?", (item_id,)
        ).fetchone()
        if case:
            return case["instrument_id"], item_id
    if category == "listing":
        return universe.instrument(conn, item_id, active=active)["id"], None
    raise ValueError("Choose a saved case or a watched listing.")


def _new_entry(conn, command, data):
    key = data.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", key):
        raise ValueError("Missing journal request key.")
    request_key = command + ":" + key
    body = _text(data.get("body"), "entry", 3000)
    with write(conn) as seq:
        previous = conn.execute(
            "SELECT * FROM journal_entries WHERE request_key=?", (request_key,)
        ).fetchone()
        review_of = None
        if command == "journal-reflect":
            review_of = data.get("entry")
            prior = conn.execute(
                "SELECT * FROM journal_entries WHERE id=?", (review_of,)
            ).fetchone()
            if not prior or prior["kind"] == "question":
                raise ValueError("Choose the journal note being reviewed.")
            instrument_id, case_id, brief_id = (
                prior["instrument_id"],
                prior["case_id"],
                prior["brief_id"],
            )
            kind = "review"
        else:
            instrument_id, case_id = _scope(
                conn, data.get("scope", ""), active=previous is None
            )
            brief_id = data.get("brief") or None
            if (
                brief_id
                and not conn.execute(
                    "SELECT 1 FROM briefs WHERE id=? AND case_id=?", (brief_id, case_id)
                ).fetchone()
            ):
                raise ValueError("The selected revision belongs to a different case.")
            kind = "question" if command == "journal-plan" else data.get("kind")
            if kind not in LABELS or (command == "journal-note" and kind == "question"):
                raise ValueError("Choose a journal entry type.")

        due = data.get("review_on") or None
        if due and (
            not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", due)
            or due != date.fromisoformat(due).isoformat()
        ):
            raise ValueError("Use an ISO calendar date for review.")
        source_trigger = data.get("next_source", "")
        if source_trigger not in ("", "yes"):
            raise ValueError("Unknown review trigger.")
        condition = _text(
            data.get("condition", ""), "review condition", 1000, optional=True
        )
        fields = {
            "instrument_id": instrument_id,
            "case_id": case_id,
            "brief_id": brief_id,
            "kind": kind,
            "body": body,
            "review_on": due,
            "next_source": int(source_trigger == "yes"),
            "condition_text": condition,
            "review_of_id": review_of,
        }
        if previous:
            if any(previous[k] != v for k, v in fields.items()):
                raise ValueError("Journal idempotency conflict.")
        else:
            conn.execute(
                """
                INSERT INTO journal_entries(id,instrument_id,case_id,brief_id,kind,author,body,review_on,next_source,
                   condition_text,review_of_id,request_key,launch_key,created_at,commit_seq)
                VALUES (:id,:instrument_id,:case_id,:brief_id,:kind,'user',:body,:review_on,:next_source,
                   :condition_text,:review_of_id,:request_key,:launch_key,:created_at,:commit_seq)""",
                {
                    **fields,
                    "id": uid("entry"),
                    "request_key": request_key,
                    "created_at": now(),
                    "commit_seq": seq,
                    "launch_key": uid("journal_followup")
                    if kind == "question"
                    else None,
                },
            )
    return "/cases/" + case_id if case_id else "/journal"


def action(conn, command, data):
    if command in ("journal-note", "journal-plan", "journal-reflect"):
        return _new_entry(conn, command, data)
    if command == "journal-start":
        plan = conn.execute(
            "SELECT * FROM journal_entries WHERE id=? AND kind='question'",
            (data.get("entry"),),
        ).fetchone()
        if not plan:
            raise ValueError("Unknown follow-up question.")
        # The immutable launch key links this plan to the ordinary case/job transaction.
        # Restarting after ask() commits returns the original job, even after a browser retry.
        job_id = research.ask(
            conn, plan["instrument_id"], plan["body"], request_key=plan["launch_key"]
        )
        child_id = conn.execute(
            "SELECT case_id FROM jobs WHERE id=?", (job_id,)
        ).fetchone()[0]
        return "/cases/" + child_id
    raise ValueError("Unknown journal action.")


_ENTRIES = """
SELECT n.id,n.kind,n.body,n.author,n.created_at,n.commit_seq,n.condition_text,n.review_on,n.next_source,
       n.instrument_id,i.ticker,i.raw_label,i.listing_exchange,i.resolution_status,n.case_id,c.question AS source_question,
       n.brief_id,b.revision AS source_revision,n.review_of_id,original.body AS reviewed_text,
       launch.case_id AS followup_case,
       (SELECT j.state FROM jobs j WHERE j.case_id=launch.case_id ORDER BY j.rowid DESC LIMIT 1) AS job_state,
       (SELECT max(br.revision) FROM briefs br WHERE br.case_id=launch.case_id) AS accepted_revision,
       (SELECT r.created_at FROM journal_entries r WHERE r.review_of_id=n.id ORDER BY r.commit_seq LIMIT 1) AS reviewed_at,
       EXISTS(SELECT 1 FROM source_memberships m WHERE m.instrument_id=n.instrument_id AND m.status='active')
            AS watched,
       d.id AS trigger_document_id,d.title AS trigger_document_title,d.received_at AS trigger_document_received_at,
       d.retention AS trigger_document_retention
FROM journal_entries n JOIN instruments i ON i.id=n.instrument_id
LEFT JOIN cases c ON c.id=n.case_id LEFT JOIN briefs b ON b.id=n.brief_id
LEFT JOIN journal_entries original ON original.id=n.review_of_id
LEFT JOIN jobs launch ON launch.request_key=n.launch_key
LEFT JOIN documents d ON d.id=(
    SELECT doc.id FROM documents doc WHERE n.next_source=1 AND doc.instrument_id=n.instrument_id
    AND doc.commit_seq>n.commit_seq AND doc.fixture=(SELECT mode='fixture' FROM installation)
    ORDER BY doc.commit_seq,doc.rowid LIMIT 1
)
"""


def _entries(conn, case_id=None):
    sql = (
        _ENTRIES
        + (" WHERE n.case_id=?" if case_id else "")
        + " ORDER BY n.commit_seq DESC"
    )
    today = now()[:10]
    entries = []
    for row in conn.execute(sql, (case_id,) if case_id else ()):
        entry = dict(row)
        entry["label"] = LABELS[entry["kind"]]
        entry["date_due"] = bool(entry["review_on"] and entry["review_on"] <= today)
        entry["ready_for_review"] = entry["date_due"] or bool(
            entry["trigger_document_id"]
        )
        entry["has_condition"] = bool(
            entry["condition_text"] or entry["review_on"] or entry["next_source"]
        )
        entries.append(entry)
    return entries


def dashboard(conn):
    entries = _entries(conn)
    upcoming = [
        n
        for n in entries
        if (n["kind"] == "question" and not n["accepted_revision"])
        or (n["kind"] != "question" and n["has_condition"] and not n["reviewed_at"])
    ]
    upcoming.sort(
        key=lambda n: (
            not n["ready_for_review"],
            n["review_on"] or "9999-12-31",
            n["commit_seq"],
        )
    )
    return {
        "entries": entries,
        "upcoming": upcoming,
        "cases": workspace.cases(conn),
        "instruments": universe.universe(conn)["instruments"],
    }


def case_notes(conn, case_id):
    case = conn.execute(
        "SELECT instrument_id FROM cases WHERE id=?", (case_id,)
    ).fetchone()
    if not case:
        raise ValueError("Unknown case.")
    origin = conn.execute(
        """
        SELECT n.id,n.case_id,n.body,c.question FROM jobs j JOIN journal_entries n ON n.launch_key=j.request_key
        LEFT JOIN cases c ON c.id=n.case_id WHERE j.case_id=?""",
        (case_id,),
    ).fetchone()
    return {
        "entries": _entries(conn, case_id),
        "origin": dict(origin) if origin else None,
    }
