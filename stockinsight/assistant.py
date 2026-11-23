"""Durable, single-owner research requests for the user's connected assistant."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta

from . import delivery, evidence, exposure, goals, methods, supplier, universe
from .db import instant, is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE assistant_profile(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), label TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0, replay_clock TEXT);
INSERT INTO assistant_profile VALUES(1,'Personal',0,NULL);
CREATE TABLE assistant_jobs(
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL, dispatch_id TEXT NOT NULL REFERENCES goal_dispatch,
 instrument_id TEXT NOT NULL REFERENCES instruments, event_id TEXT NOT NULL, method_id TEXT NOT NULL REFERENCES method_reports,
 request_key TEXT NOT NULL UNIQUE, question TEXT NOT NULL, cutoff TEXT NOT NULL, frozen_seq INTEGER NOT NULL,
 state TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, owner TEXT, lease_until TEXT, accepted_at TEXT,
 result TEXT, selection TEXT, parent TEXT REFERENCES assistant_jobs);
CREATE INDEX assistant_case ON assistant_jobs(case_id,created_at);
CREATE TABLE assistant_reads(job_id TEXT NOT NULL REFERENCES assistant_jobs,passage_id TEXT NOT NULL REFERENCES evidence_passages,
 PRIMARY KEY(job_id,passage_id));
CREATE TABLE assistant_calculations(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES assistant_jobs,
 current_ref TEXT NOT NULL, baseline_ref TEXT NOT NULL, result TEXT NOT NULL, UNIQUE(job_id,current_ref,baseline_ref));
CREATE TABLE assistant_subscriptions(id TEXT PRIMARY KEY, destination BLOB NOT NULL, expires TEXT NOT NULL,
 verified_at TEXT NOT NULL);
CREATE TABLE assistant_events(job_id TEXT NOT NULL REFERENCES assistant_jobs, sub_id TEXT NOT NULL REFERENCES assistant_subscriptions,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL, accepted_at TEXT, PRIMARY KEY(job_id,sub_id));
"""
RECOVERY = """
CREATE TABLE assistant_interruptions(
 job_id TEXT NOT NULL REFERENCES assistant_jobs, attempt INTEGER NOT NULL, expired_at TEXT NOT NULL,
 event_receipts TEXT NOT NULL, PRIMARY KEY(job_id,attempt)
);
"""

PUBLIC = {
    "issuer",
    "issuer_news",
    "msft_release",
    "fed_calendar",
    "bls_calendar",
    "cma_news",
    "msft_calendar",
    "msft_calendar_faq",
    "sec",
    "sec_filing",
    "historical_filing",
    "usgs_earthquake",
    "tsmc_earthquake_disclosure",
}


def can_research(db, version):
    row = db.execute("""SELECT d.origin FROM event_versions e JOIN evidence_passages p ON p.id=e.source_ref
                       JOIN documents d ON d.id=p.document_id WHERE e.id=?""", (version,)).fetchone()
    return bool(row and row[0] in PUBLIC)


def profile(db):
    return dict(db.execute("SELECT * FROM assistant_profile").fetchone())


def configure(db, label=None):
    with write(db):
        db.execute("UPDATE assistant_profile SET enabled=1,label=coalesce(?,label)", (label,))


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _item(db, job_id):
    row = db.execute("SELECT * FROM assistant_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise ValueError("Unknown research job.")
    plan = db.execute(
        """SELECT p.* FROM goal_plans p JOIN goal_dispatch d ON d.plan_id=p.id
                      WHERE d.id=? AND p.ended_at IS NULL""",
        (row["dispatch_id"],),
    ).fetchone()
    if not plan or row["instrument_id"] not in {i["id"] for i in goals.listings(db, plan["scope"])}:
        raise ValueError("This research scope is no longer active.")
    return row


def enqueue(db, work, stamp):
    """Freeze the host method at discovery, then hand off the unaccepted dispatch."""
    v = db.execute(
        "SELECT event_id,kind FROM event_versions WHERE id=?", (work["event_version_id"],)
    ).fetchone()
    focus = "expectations" if "earnings" in v["kind"] else "exposure"
    method = methods.event_report(
        db,
        work["event_version_id"],
        goal_id=work["goal_id"],
        instrument_id=work["instrument_id"],
        focus=focus,
        request_key=work["id"],
    )
    with write(db) as seq:
        changed = db.execute(
            """UPDATE goal_dispatch SET state='awaiting_assistant',detail='Awaiting assistant research'
                           WHERE id=? AND state='running' AND lease_id=?""",
            (work["id"], work["lease_id"]),
        ).rowcount
        if not changed:
            return
        related = supplier.incident_events(db, work["event_version_id"]) or [v["event_id"]]
        placeholders = ",".join("?" for _ in related)
        previous = db.execute(
            f"""SELECT j.case_id,j.id FROM assistant_jobs j JOIN goal_dispatch d ON d.id=j.dispatch_id
                   JOIN goal_plans p ON p.id=d.plan_id WHERE j.event_id IN ({placeholders}) AND j.instrument_id=? AND p.goal_id=?
                   ORDER BY j.rowid DESC LIMIT 1""",
            (*related, work["instrument_id"], work["goal_id"]),
        ).fetchone()
        case = previous["case_id"] if previous else work["id"]
        if previous:
            db.execute(
                "UPDATE assistant_jobs SET state='superseded' WHERE case_id=? AND event_id=? AND state IN ('pending','running')",
                (case, v["event_id"]),
            )
            db.execute(
                """UPDATE goal_dispatch SET state='superseded' WHERE state='awaiting_assistant' AND
                       id IN (SELECT dispatch_id FROM assistant_jobs WHERE case_id=? AND state='superseded')""",
                (case,),
            )
        db.execute(
            """INSERT INTO assistant_jobs(id,case_id,dispatch_id,instrument_id,event_id,method_id,request_key,
                   question,cutoff,frozen_seq,state,created_at,parent) VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?)""",
            (
                work["id"],
                case,
                work["id"],
                work["instrument_id"],
                v["event_id"],
                method["id"],
                work["id"],
                "Investigate this observation and its relevance to the watched listing.",
                stamp,
                seq,
                now(),
                previous["id"] if previous else None,
            ),
        )


def follow_up(db, case_id, question, request_key):
    if not isinstance(question, str) or not 5 <= len(question.strip()) <= 1500:
        raise ValueError("Supply a research question of 5 to 1500 characters.")
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 120:
        raise ValueError("A stable request key is required.")
    key = "follow:" + _digest(case_id + "|" + request_key)
    with write(db) as seq:
        old = db.execute("SELECT id,question FROM assistant_jobs WHERE request_key=?", (key,)).fetchone()
        if old:
            _item(db, old["id"])
            if old["question"] != question:
                raise ValueError("Request key already used for another question.")
            return {"job_id": old["id"], "case_id": case_id}
        row = db.execute(
            "SELECT id FROM assistant_jobs WHERE case_id=? ORDER BY rowid DESC LIMIT 1", (case_id,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown case.")
        base = _item(db, row[0])
        if base["state"] != "accepted":
            raise ValueError("This case already has pending work.")
        cutoff = profile(db)["replay_clock"] or now()
        ident = uid("follow")
        db.execute(
            """INSERT INTO assistant_jobs(id,case_id,dispatch_id,instrument_id,event_id,method_id,request_key,
                    question,cutoff,frozen_seq,state,created_at,parent) VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?)""",
            (
                ident,
                case_id,
                base["dispatch_id"],
                base["instrument_id"],
                base["event_id"],
                base["method_id"],
                key,
                question,
                cutoff,
                seq,
                now(),
                base["id"],
            ),
        )
        return {"job_id": ident, "case_id": case_id}


def recover(db, job_id=None):
    """Fence an expired assistant and retain its delivery receipts before redispatch."""
    stamp = now()
    row = db.execute(
        """SELECT id FROM assistant_jobs WHERE state='running' AND lease_until<=?
                     AND (? IS NULL OR id=?) ORDER BY lease_until LIMIT 1""",
        (stamp, job_id, job_id),
    ).fetchone()
    if not row:
        return
    with write(db):
        job = db.execute(
            "SELECT * FROM assistant_jobs WHERE id=? AND state='running' AND lease_until<=?", (row[0], stamp)
        ).fetchone()
        if not job:
            return
        attempt = db.execute(
            "SELECT count(*)+1 FROM assistant_interruptions WHERE job_id=?", (job["id"],)
        ).fetchone()[0]
        receipts = [
            dict(r) for r in db.execute("SELECT * FROM assistant_events WHERE job_id=?", (job["id"],))
        ]
        db.execute(
            "INSERT INTO assistant_interruptions VALUES(?,?,?,?)",
            (job["id"], attempt, stamp, json.dumps(receipts)),
        )
        db.execute("DELETE FROM assistant_events WHERE job_id=?", (job["id"],))
        state = "pending" if attempt < 3 else "failed"
        db.execute(
            "UPDATE assistant_jobs SET state=?,owner=NULL,lease_until=NULL WHERE id=?", (state, job["id"])
        )
        if state == "failed" and job["dispatch_id"] == job["id"]:
            db.execute(
                """UPDATE goal_dispatch SET state='failed',detail='Assistant lease expired three times'
                       WHERE id=? AND state='awaiting_assistant'""",
                (job["id"],),
            )
    return job["id"]


def claim(db, job_id, worker_key):
    if not isinstance(worker_key, str) or not 16 <= len(worker_key) <= 160:
        raise ValueError("Supply a random per-investigation worker key.")
    recover(db, job_id)
    with write(db):
        row = _item(db, job_id)
        stamp = now()
        if row["state"] == "accepted":
            return {"state": "accepted", "case_id": row["case_id"]}
        _current_event(db, row)
        owner = _digest(worker_key)
        if row["state"] not in ("running", "pending") or (
            row["state"] == "running" and row["lease_until"] > stamp and row["owner"] != owner
        ):
            raise ValueError("This job is unavailable or has another owner.")
        until = instant((datetime.fromisoformat(stamp) + timedelta(minutes=15)).isoformat())
        db.execute(
            """UPDATE assistant_jobs SET state='running',started_at=coalesce(started_at,?),owner=?,lease_until=?
                   WHERE id=?""",
            (stamp, owner, until, job_id),
        )
    method = methods.export(db, row["method_id"])
    return {
        "job_id": job_id,
        "case_id": row["case_id"],
        "state": "running",
        "label": profile(db)["label"],
        "question": row["question"],
        "cutoff": row["cutoff"],
        "event": method["title"],
        "event_passage": method["body"]["event"]["source_ref"],
        "parent": row["parent"],
    }


def _current_event(db, job):
    event = db.execute(
        """SELECT e.* FROM method_reports m JOIN event_versions e ON e.id=m.event_version_id
                       WHERE m.id=? AND NOT EXISTS(SELECT 1 FROM event_versions n WHERE n.supersedes=e.id)""",
        (job["method_id"],),
    ).fetchone()
    if not event or (
        event["instrument_id"] != job["instrument_id"]
        and not exposure.for_event(db, job["instrument_id"], event["id"])
    ):
        raise ValueError("An event or approved relationship changed. Inspect the newer investigation.")
    return event


def _authorize(db, job_id, worker_key):
    job = _item(db, job_id)
    if (
        job["state"] != "running"
        or not secrets.compare_digest(job["owner"], _digest(worker_key))
        or job["lease_until"] <= now()
    ):
        raise ValueError("A current research lease is required.")
    _current_event(db, job)
    return job


def _passage(db, job, ref):
    event = _current_event(db, job)
    subject = event["instrument_id"] if ref == event["source_ref"] else job["instrument_id"]
    p = evidence.get(db, subject, ref, job["cutoff"], fixture=is_fixture(db), commit_seq=job["frozen_seq"])
    if p["origin"] not in PUBLIC:
        raise ValueError("Passage outside the public research scope.")
    public = {
        k: p[k]
        for k in (
            "id",
            "text",
            "title",
            "source_url",
            "published_at",
            "available_at",
            "received_at",
            "locator",
            "financial",
            "version_hash",
            "document_id",
            "origin",
            "fixture",
            "instrument_id",
        )
    }
    if p["origin"] == "usgs_earthquake":
        public["supporting_sources"] = supplier.public_links(db, ref)
    return public


def sources(db, job_id, worker_key):
    job = _authorize(db, job_id, worker_key)
    rows = evidence.search(
        db,
        job["instrument_id"],
        cutoff=job["cutoff"],
        fixture=is_fixture(db),
        commit_seq=job["frozen_seq"],
        limit=50,
    )
    return [
        {"id": p["id"], "title": p["title"], "locator": p["locator"]} for p in rows if p["origin"] in PUBLIC
    ]


def read(db, job_id, worker_key, passage_id):
    with write(db):
        job = _authorize(db, job_id, worker_key)
        p = _passage(db, job, passage_id)
        db.execute("INSERT OR IGNORE INTO assistant_reads VALUES(?,?)", (job_id, passage_id))
        return p


def compare(db, job_id, worker_key, current, baseline):
    with write(db):
        job = _authorize(db, job_id, worker_key)
        result = evidence.compare(_passage(db, job, current), _passage(db, job, baseline), "period_trend")
        db.executemany(
            "INSERT OR IGNORE INTO assistant_reads VALUES(?,?)", [(job_id, current), (job_id, baseline)]
        )
        db.execute(
            "INSERT OR IGNORE INTO assistant_calculations VALUES(?,?,?,?,?)",
            (uid("calc"), job_id, current, baseline, json.dumps(result)),
        )
        ident = db.execute(
            "SELECT id FROM assistant_calculations WHERE job_id=? AND current_ref=? AND baseline_ref=?",
            (job_id, current, baseline),
        ).fetchone()[0]
        return {"receipt": ident, **result}


def accept(db, job_id, worker_key, passage_ids, calculation_ids, hypothesis, alternative, next_check):
    for field in (hypothesis, alternative, next_check):
        if not isinstance(field, str) or not 8 <= len(field.strip()) <= 600:
            raise ValueError("Supply a bounded conditional interpretation, alternative and next check.")
    if (
        not all(
            isinstance(v, list)
            and len(v) <= 8
            and all(isinstance(x, str) for x in v)
            and len(set(v)) == len(v)
            for v in (passage_ids, calculation_ids)
        )
        or not passage_ids
    ):
        raise ValueError("Select one to eight read passages and compatible calculation receipts.")
    selection = json.dumps([passage_ids, calculation_ids, hypothesis, alternative, next_check])
    with write(db):
        row = _item(db, job_id)
        if (
            row["state"] == "accepted"
            and row["selection"] == selection
            and secrets.compare_digest(row["owner"], _digest(worker_key))
        ):
            return json.loads(row["result"])
        job = _authorize(db, job_id, worker_key)
        method = methods.export(db, job["method_id"])
        if method["body"]["event"]["source_ref"] not in passage_ids:
            raise ValueError("Include the observed event's source.")
        seen = {r[0] for r in db.execute("SELECT passage_id FROM assistant_reads WHERE job_id=?", (job_id,))}
        if not set(passage_ids) <= seen:
            raise ValueError("Read each cited passage before submission.")
        calculations = []
        for ref in calculation_ids:
            calc = db.execute(
                "SELECT * FROM assistant_calculations WHERE job_id=? AND id=?", (job_id, ref)
            ).fetchone()
            if not calc or not {calc["current_ref"], calc["baseline_ref"]} <= set(passage_ids):
                raise ValueError("Cite both inputs to each calculation from this job.")
            calculations.append({"receipt": ref, **json.loads(calc["result"])})
        cited = [_passage(db, job, ref) for ref in passage_ids]
        body = {
            "case_id": job["case_id"],
            "job_id": job_id,
            "label": profile(db)["label"],
            "title": method["title"],
            "question": job["question"],
            "cutoff": job["cutoff"],
            "status": "partial",
            "summary": next(p["text"] for p in cited if p["id"] == method["body"]["event"]["source_ref"]),
            "hypothesis": hypothesis,
            "alternative": alternative,
            "next_observations": [next_check],
            "gaps": method["body"]["gaps"],
            "citations": cited,
            "calculations": calculations,
            "parent": job["parent"],
            "exposures": [],
        }
        if calculations:
            c = calculations[0]
            body["summary"] += (
                f" {c['metric'].capitalize()} changed from {c['baseline_value']} to "
                f"{c['current_value']} {c['unit']} ({c['percent_change']}%)."
                if c["percent_change"] is not None
                else f" Difference: {c['difference']} {c['unit']}."
            )
        finished = now()
        db.execute(
            "UPDATE assistant_jobs SET state='accepted',result=?,selection=?,accepted_at=? WHERE id=?",
            (json.dumps(body), selection, finished, job_id),
        )
        if job["id"] == job["dispatch_id"]:
            changed = db.execute(
                """UPDATE goal_dispatch SET state='complete',ended_at=?,body=?,method_report=?,runtime=?,detail=NULL
                       WHERE id=? AND state='awaiting_assistant'""",
                (
                    finished,
                    json.dumps(body),
                    method["id"],
                    json.dumps(
                        {
                            "mode": "connected_assistant",
                            "channel_verification": "see subscription and delivery receipts",
                        }
                    ),
                    job_id,
                ),
            ).rowcount
            if not changed:
                raise ValueError("This dispatch was superseded.")
            db.execute(
                "INSERT INTO goal_followups VALUES(?,?,?,?,?)",
                (uid("followup"), job_id, job["instrument_id"], next_check, finished),
            )
        demo = body["label"].startswith(("Historical replay ·", "Live integration test"))
        listing = universe.instrument(db, job["instrument_id"])
        title = body["label"] + " · " + listing["ticker"] if demo else "Stock Insight research update"
        detail = (
            (body["summary"][:190] + " " + hypothesis[:130] + " " + body["gaps"][0][:100])
            if demo and body["gaps"]
            else "A cited investigation is ready in your private desk."
        )
        notice = delivery.enqueue(
            db,
            key="assistant:" + job_id,
            title=title,
            message=detail,
            report_path="/goals/reports/" + job["dispatch_id"],
            at=finished,
        )
        if job["id"] == job["dispatch_id"]:
            db.execute("INSERT INTO goal_report_delivery VALUES(?,?,?)", (job_id, notice, job_id))
        return body


def case(db, case_id):
    rows = db.execute("SELECT id FROM assistant_jobs WHERE case_id=? ORDER BY rowid", (case_id,)).fetchall()
    if not rows:
        raise ValueError("Unknown assistant case.")
    jobs = [_item(db, r[0]) for r in rows]
    return {
        "case_id": case_id,
        "label": profile(db)["label"],
        "jobs": [
            {
                "job_id": j["id"],
                "state": j["state"],
                "cutoff": j["cutoff"],
                "started_at": j["started_at"],
                "accepted_at": j["accepted_at"],
                "result": json.loads(j["result"]) if j["result"] else None,
            }
            for j in jobs
        ],
    }
