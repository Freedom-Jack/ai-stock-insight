"""Durable on-demand questions, fenced assignments and accepted interpretations."""

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import assessment, gaps, universe
from .assessment import required_checks
from .db import instant, is_fixture, now, uid, write

METHOD = "sourced_company_review.v3"


SCHEMA = """
CREATE TABLE cases(
    id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments(id), question TEXT NOT NULL,
    cutoff TEXT, revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL
);
CREATE TABLE jobs(
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases, base_revision INTEGER NOT NULL,
    request_key TEXT NOT NULL UNIQUE, state TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', commit_seq INTEGER NOT NULL
);
CREATE TABLE runs(
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs, generation INTEGER NOT NULL,
    owner_hash TEXT NOT NULL, request_id TEXT NOT NULL, lease_hash TEXT NOT NULL,
    started_at TEXT NOT NULL, expires_at TEXT NOT NULL, max_until TEXT NOT NULL,
    state TEXT NOT NULL, context TEXT NOT NULL, runtime TEXT NOT NULL DEFAULT '{}',
    commit_seq INTEGER NOT NULL, UNIQUE(job_id,generation)
);
CREATE TABLE receipts(
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs, tool TEXT NOT NULL,
    version TEXT NOT NULL, args TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
    status TEXT NOT NULL, output TEXT NOT NULL, commit_seq INTEGER NOT NULL
);
CREATE INDEX receipt_run ON receipts(run_id,commit_seq);
CREATE TABLE capability_gaps(
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases, capability TEXT NOT NULL,
    status TEXT NOT NULL, impact TEXT NOT NULL, fallback TEXT NOT NULL, remedy TEXT NOT NULL,
    acceptance_example TEXT NOT NULL, lifecycle TEXT NOT NULL DEFAULT 'open', commit_seq INTEGER NOT NULL,
    UNIQUE(case_id,capability,status)
);
CREATE TABLE gap_attempts(
    gap_id TEXT NOT NULL REFERENCES capability_gaps, receipt_id TEXT NOT NULL REFERENCES receipts,
    PRIMARY KEY(gap_id, receipt_id)
);
CREATE TABLE briefs(
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases, revision INTEGER NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs, method TEXT NOT NULL, as_of TEXT NOT NULL,
    body TEXT NOT NULL, submission_hash TEXT NOT NULL, manifest TEXT NOT NULL, manifest_hash TEXT NOT NULL,
    commit_seq INTEGER NOT NULL, UNIQUE(case_id,revision)
);
CREATE TABLE claim_evidence(
    brief_id TEXT NOT NULL REFERENCES briefs, ordinal INTEGER NOT NULL, passage_id TEXT NOT NULL,
    PRIMARY KEY(brief_id,ordinal,passage_id)
);
CREATE TABLE brief_calculations(
    brief_id TEXT NOT NULL REFERENCES briefs, receipt_id TEXT NOT NULL REFERENCES receipts,
    PRIMARY KEY(brief_id,receipt_id)
);
CREATE TABLE reconciliation_drafts(
    run_id TEXT PRIMARY KEY REFERENCES runs, reason TEXT NOT NULL, body TEXT NOT NULL,
    commit_seq INTEGER NOT NULL
);
CREATE TABLE inbox(
    brief_id TEXT PRIMARY KEY REFERENCES briefs, created_at TEXT NOT NULL, reviewed_at TEXT,
    commit_seq INTEGER NOT NULL
);
"""


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _new_job(db, case_id, revision, key, seq):
    job_id = uid("job")
    db.execute(
        "INSERT INTO jobs(id,case_id,base_revision,request_key,state,created_at,commit_seq) "
        "VALUES (?,?,?,?,'ready',?,?)",
        (job_id, case_id, revision, key, now(), seq),
    )
    return job_id


def ask(db, instrument_id, question, *, cutoff=None, request_key=None):
    question = question.strip()
    if not 1 <= len(question) <= 3000:
        raise ValueError("Enter a research question of 1–3000 characters")
    cutoff = instant(cutoff) if cutoff else None
    if cutoff and cutoff > now():
        raise ValueError("Historical cutoff must have passed")
    key = request_key or uid("request")
    with write(db) as seq:
        previous = db.execute(
            "SELECT jobs.id,c.question,c.instrument_id,c.cutoff FROM jobs "
            "JOIN cases c ON c.id=jobs.case_id WHERE request_key=?",
            (key,),
        ).fetchone()
        if previous:
            if tuple(previous)[1:] != (question, instrument_id, cutoff):
                raise ValueError("idempotency_conflict")
            return previous["id"]
        item = universe.instrument(db, instrument_id)
        if item["resolution_status"] == "unclassified":
            raise ValueError("Classify the instrument before starting stock research")
        case_id = uid("case")
        db.execute(
            "INSERT INTO cases(id,instrument_id,question,cutoff,created_at,commit_seq) VALUES(?,?,?,?,?,?)",
            (case_id, instrument_id, question, cutoff, now(), seq),
        )
        return _new_job(db, case_id, 0, key, seq)


def continuation(db, case_id, *, request_key=None, expected_revision=None):
    with write(db) as seq:
        case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if not case:
            raise ValueError("Unknown case")
        if request_key is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("Continuation requires a base revision")
        key = "continue:" + (request_key or uid("request"))
        previous = db.execute(
            "SELECT id,case_id,base_revision FROM jobs WHERE request_key=?", (key,)
        ).fetchone()
        if previous:
            if (previous["case_id"], previous["base_revision"]) != (case_id, expected_revision):
                raise ValueError("idempotency_conflict")
            return previous["id"]
        if expected_revision is not None and case["revision"] != expected_revision:
            raise ValueError("Case changed. Reload before investigating again.")
        universe.instrument(db, case["instrument_id"])
        return _new_job(db, case_id, case["revision"], key, seq)


@dataclass(frozen=True)
class Lease:
    run_id: str
    generation: int
    token: str


def _lease(secret, run_id, generation):
    token = hmac.new(secret.encode(), run_id.encode(), hashlib.sha256).hexdigest()
    return Lease(run_id, generation, token)


def _deadline(seconds):
    stamp = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return instant(stamp.isoformat())


def claim(db, job_id, execution_secret, request_id):
    """Called by the trusted dispatcher. The worker never chooses its identity."""
    from . import announcement_research

    with write(db) as seq:
        job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] not in ("ready", "leased"):
            raise ValueError("Job unavailable or already completed")
        owner = digest(execution_secret)
        old = db.execute(
            "SELECT * FROM runs WHERE job_id=? AND generation=?", (job_id, job["generation"])
        ).fetchone()
        if old and old["expires_at"] > now():
            if old["owner_hash"] == owner and old["request_id"] == request_id:
                return _lease(execution_secret, old["id"], old["generation"])
            raise ValueError("Job already leased")
        if db.execute("SELECT 1 FROM runs WHERE state='leased' AND expires_at>?", (now(),)).fetchone():
            raise ValueError("Another investigation is running. Retry this queued job when it finishes.")
        if old:
            db.execute("UPDATE runs SET state='expired',commit_seq=? WHERE id=?", (seq, old["id"]))
        case = db.execute("SELECT * FROM cases WHERE id=?", (job["case_id"],)).fetchone()
        item = universe.instrument(db, case["instrument_id"])
        method = METHOD
        if not is_fixture(db) and announcement_research.accepts(case["question"], item):
            method = announcement_research.METHOD
        context = {
            "instrument": {
                k: item.get(k)
                for k in (
                    "id",
                    "company_id",
                    "company_name",
                    "ticker",
                    "listing_exchange",
                    "currency",
                    "cik",
                    "resolution_status",
                )
            },
            "cutoff": case["cutoff"],
            "method": method,
            "base_revision": job["base_revision"],
            "at_seq": seq,
            "case_id": case["id"],
            "question": case["question"],
            "required_checks": required_checks(case["question"]),
        }
        run_id, generation = uid("run"), job["generation"] + 1
        lease = _lease(execution_secret, run_id, generation)
        db.execute(
            "INSERT INTO runs(id,job_id,generation,owner_hash,request_id,lease_hash,started_at,"
            "expires_at,max_until,state,context,commit_seq) VALUES(?,?,?,?,?,?,?,?,?,'leased',?,?)",
            (
                run_id,
                job_id,
                generation,
                owner,
                request_id,
                digest(lease.token),
                now(),
                _deadline(180),
                _deadline(900),
                encode(context),
                seq,
            ),
        )
        db.execute(
            "UPDATE jobs SET state='leased',generation=?,commit_seq=? WHERE id=?", (generation, seq, job_id)
        )
        return lease


def authorized(db, lease, *, completed=False):
    row = db.execute(
        "SELECT r.*,j.case_id,j.base_revision,j.generation AS current_generation "
        "FROM runs r JOIN jobs j ON j.id=r.job_id WHERE r.id=?",
        (lease.run_id,),
    ).fetchone()
    if not row or not secrets.compare_digest(digest(lease.token), row["lease_hash"]):
        raise ValueError("Assignment denied")
    if lease.generation != row["generation"] or row["generation"] != row["current_generation"]:
        raise ValueError("Stale assignment generation")
    if completed and row["state"] in ("accepted", "partial"):
        return row
    if row["state"] != "leased" or row["expires_at"] <= now():
        raise ValueError("Assignment expired or closed")
    universe.instrument(db, json.loads(row["context"])["instrument"]["id"])
    return row


def renew(db, lease):
    with write(db) as seq:
        row = authorized(db, lease)
        db.execute(
            "UPDATE runs SET expires_at=?,commit_seq=? WHERE id=?",
            (min(_deadline(180), row["max_until"]), seq, lease.run_id),
        )


def _close(db, run, state, detail, seq, runtime):
    db.execute(
        "UPDATE runs SET state=?,runtime=?,commit_seq=? WHERE id=?", (state, encode(runtime), seq, run["id"])
    )
    db.execute(
        "UPDATE jobs SET state=?,detail=?,commit_seq=? WHERE id=?", (state, detail, seq, run["job_id"])
    )


def _strings(value, name, *, required=False):
    if not isinstance(value, list) or len(value) > 32 or (required and not value):
        raise ValueError(f"Invalid {name}")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 6000 for v in value):
        raise ValueError(f"Invalid text in {name}")


def validate(db, run, body, receipts):
    from . import evidence

    fields = {
        "status",
        "conclusion",
        "changes",
        "claims",
        "calculations",
        "alternative_explanations",
        "gaps",
        "next_steps",
    }
    if not isinstance(body, dict) or set(body) != fields or len(encode(body)) > 80000:
        raise ValueError("Invalid result fields")
    if body["status"] not in ("partial", "complete", "blocked"):
        raise ValueError("Invalid result status")
    _strings([body["conclusion"]], "conclusion")
    for key in ("changes", "calculations", "alternative_explanations", "gaps", "next_steps"):
        _strings(body[key], key, required=key in ("next_steps", "alternative_explanations"))
    if not isinstance(body["claims"], list) or len(body["claims"]) > 32:
        raise ValueError("Invalid claims")
    context = json.loads(run["context"])
    read_ids, quoted_ids, calculation_inputs = set(), set(), {}
    for receipt in receipts:
        output = json.loads(receipt["output"])
        read_ids.update(output["evidence_ids"])
        if receipt["tool"] == "get_evidence" and receipt["status"] == "ok":
            quoted_ids.update(output["evidence_ids"])
        if receipt["tool"] == "compare_financials" and receipt["status"] == "ok":
            calculation_inputs[receipt["id"]] = output["data"]["input_ids"]
    if not set(context["required_checks"]).issubset({r["tool"] for r in receipts}):
        raise ValueError("Missing required price or expectation coverage receipt")
    pending = gaps.outstanding(db, run, receipts)
    if set(body["gaps"]) != pending or (pending and body["status"] == "complete"):
        raise ValueError("Disclose the outstanding coverage gaps")
    if body["status"] in ("blocked", "partial") and not pending:
        raise ValueError("A partial or blocked result requires a recorded gap")
    if body["status"] != "blocked" and not body["claims"]:
        raise ValueError("Research requires a cited claim")
    retained_versions, superseded = {}, set()
    for ref in read_ids:
        p = evidence.get(db, context["instrument"]["id"], ref, context["cutoff"], fixture=is_fixture(db))
        if not evidence.still_supported(db, p, context["cutoff"]):
            superseded.add(ref)
        if p["document_id"] not in retained_versions:
            if p["retention"] == "full":
                evidence.document_bytes(db, context["instrument"]["id"], p["document_id"])
            retained_versions[p["document_id"]] = p["version_hash"]
    usable = {rid for rid, refs in calculation_inputs.items() if not superseded.intersection(refs)}
    if any(rid in calculation_inputs and rid not in usable for rid in body["calculations"]):
        raise ValueError("Calculation input superseded. Read the eligible edition and recompute.")
    selected = set(body["calculations"])
    if not selected <= usable or len(body["calculations"]) != len(selected):
        raise ValueError("Select distinct eligible calculation receipts for the submitted claims")
    for claim_item in body["claims"]:
        if not isinstance(claim_item, dict) or set(claim_item) != {"text", "type", "evidence_refs"}:
            raise ValueError("Invalid claim fields")
        _strings([claim_item["text"]], "claim")
        kind = claim_item["type"]
        if kind not in ("fact", "issuer_statement", "inference", "hypothesis"):
            raise ValueError("Unsupported claim type")
        refs = claim_item["evidence_refs"]
        _strings(refs, "citations", required=kind != "hypothesis")
        if not set(refs) <= quoted_ids or len(set(refs)) != len(refs):
            raise ValueError("Citation outside the run read-set or duplicated")
        if superseded.intersection(refs):
            raise ValueError("Cited passage superseded. Read the eligible source edition.")
        if kind in ("fact", "issuer_statement"):
            passages = [
                evidence.get(db, context["instrument"]["id"], ref, context["cutoff"], fixture=is_fixture(db))
                for ref in refs
            ]
            if not any(claim_item["text"] in p["text"] for p in passages):
                raise ValueError("Factual claim must quote its exact retained passage")
    if body["status"] != "blocked" and not any(c["evidence_refs"] for c in body["claims"]):
        raise ValueError("Research requires supporting evidence")
    return {
        "schema_version": "1.0",
        "assertions": assessment.validate_assessment(db, run, body, receipts),
        "context": context,
        "passages": sorted(read_ids),
        "versions": retained_versions,
        "receipts": [r["id"] for r in receipts],
        "method": context["method"],
    }


def submit(db, lease, body, runtime):
    signature = digest(encode(body))
    with write(db) as seq:
        run = authorized(db, lease, completed=True)
        existing = db.execute(
            "SELECT id,submission_hash FROM briefs WHERE run_id=?", (lease.run_id,)
        ).fetchone()
        if existing:
            if existing["submission_hash"] != signature:
                raise ValueError("idempotency_conflict")
            return existing["id"]
        revision = db.execute("SELECT revision FROM cases WHERE id=?", (run["case_id"],)).fetchone()[0]
        receipts = list(
            db.execute("SELECT * FROM receipts WHERE run_id=? ORDER BY commit_seq", (lease.run_id,))
        )
        manifest = validate(db, run, body, receipts)
        if revision != run["base_revision"]:
            db.execute(
                "INSERT INTO reconciliation_drafts VALUES(?,?,?,?)",
                (run["id"], "revision_conflict", encode(body), seq),
            )
            _close(db, run, "superseded", "revision_conflict", seq, runtime)
        elif body["status"] == "blocked":
            db.execute(
                "INSERT INTO reconciliation_drafts VALUES(?,?,?,?)",
                (run["id"], "insufficient_evidence", encode(body), seq),
            )
            _close(db, run, "blocked", body["conclusion"], seq, runtime)
            return None
        else:
            brief, stamp = uid("brief"), now()
            manifest["runtime"] = runtime
            db.execute(
                "INSERT INTO briefs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    brief,
                    run["case_id"],
                    revision + 1,
                    run["id"],
                    manifest["method"],
                    stamp,
                    encode(body),
                    signature,
                    encode(manifest),
                    digest(encode(manifest)),
                    seq,
                ),
            )
            for index, item in enumerate(body["claims"]):
                db.executemany(
                    "INSERT INTO claim_evidence VALUES(?,?,?)",
                    [(brief, index, ref) for ref in item["evidence_refs"]],
                )
            db.executemany(
                "INSERT INTO brief_calculations VALUES(?,?)", [(brief, r) for r in body["calculations"]]
            )
            db.execute(
                "UPDATE cases SET revision=?,commit_seq=? WHERE id=?", (revision + 1, seq, run["case_id"])
            )
            db.execute("INSERT INTO inbox VALUES(?,?,NULL,?)", (brief, stamp, seq))
            _close(db, run, "partial" if body["status"] == "partial" else "accepted", "", seq, runtime)
            return brief
    raise ValueError("revision_conflict")


def run_job(db, job_id, *, engine="responses"):
    from . import executor
    from .bridge import Bridge

    lease = claim(db, job_id, secrets.token_urlsafe(32), uid("dispatch"))
    bridge = Bridge(db, lease)
    context = json.loads(authorized(db, lease)["context"])
    context["capabilities"] = bridge.catalog()
    fixture = is_fixture(db)
    runtime = {
        "adapter": "fixture" if fixture else "responses",
        "billing_mode": "offline" if fixture else "unconfigured",
    }
    try:
        if not fixture and engine in ("local", "device"):
            from . import local_research

            runtime = {"adapter": engine, "billing_mode": "local_no_provider_charges"}
            result = local_research.execute(context, bridge.call, on_device=engine == "device", runtime=runtime)
        elif fixture or engine == "responses":
            if not fixture:
                runtime = executor.preflight()
            result = executor.execute(context["question"], context, bridge.call, fixture=fixture)
        else:
            raise ValueError("Unknown investigator")
        runtime = getattr(result, "runtime", runtime)
        return submit(db, lease, result, runtime)
    except (ValueError, TimeoutError, OSError) as exc:
        # The executor maps provider errors to safe messages. Never persist an exception
        # containing a response body, credential, or local path.
        if getattr(exc, "code", None):
            detail = f"{exc.code}: {exc}"
        else:
            detail = str(exc) if isinstance(exc, ValueError) else "Executor unavailable"
        runtime = getattr(exc, "runtime", None) or runtime
        with write(db) as seq:
            current = db.execute("SELECT * FROM runs WHERE id=?", (lease.run_id,)).fetchone()
            if current["state"] == "leased" and current["expires_at"] > now():
                _close(db, current, "blocked", detail, seq, runtime)
        raise ValueError(detail) from None


def review(db, brief_id):
    with write(db) as seq:
        if not db.execute(
            "UPDATE inbox SET reviewed_at=coalesce(reviewed_at,?),commit_seq=? WHERE brief_id=?",
            (now(), seq, brief_id),
        ).rowcount:
            raise ValueError("Unknown brief")
