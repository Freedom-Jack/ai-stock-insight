"""Record specific unmet inputs and the scoped evidence that subsequently satisfied them."""

import hashlib
import json
import re
from datetime import date

from . import assessment, evidence
from .db import is_fixture, uid

DIMENSIONS = ("basis", "currency", "duration", "unit_scale", "share_basis")

MIGRATION = """
CREATE TABLE gap_requirements(
    gap_id TEXT PRIMARY KEY REFERENCES capability_gaps, requirement TEXT NOT NULL
);
CREATE TABLE gap_resolutions(
    gap_id TEXT NOT NULL REFERENCES capability_gaps, receipt_id TEXT NOT NULL REFERENCES receipts,
    passage_ids TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits,
    PRIMARY KEY(gap_id,receipt_id)
);
CREATE INDEX gap_resolution_history ON gap_resolutions(gap_id,commit_seq);
"""


def _period(value):
    value = " ".join(value.upper().split())
    if value == "UNSPECIFIED":
        return "unspecified"
    if re.fullmatch(r"Q[1-4]", value):
        return value
    quarter = re.fullmatch(r"(?:Q([1-4]) )?FY(?:20)?([0-9]{2})", value)
    if quarter:
        q, year = quarter.groups()
        return (f"Q{q} " if q else "") + "FY" + year
    dates = re.fullmatch(r"(\d{4}-\d\d-\d\d) TO (\d{4}-\d\d-\d\d)", value)
    if dates and date.fromisoformat(dates[1]) <= date.fromisoformat(dates[2]):
        return f"{dates[1]} to {dates[2]}"
    raise ValueError("Specify a fiscal period (Q2 FY25), exact date range, or unspecified.")


def _matches(passage, metric, period, objective):
    fact = passage.get("financial") or {}
    if not fact or fact.get("role") != "actual" or fact.get("value") in (None, ""):
        return False
    if metric and fact.get("metric") != metric:
        return False
    return assessment.matches_dimensions(fact, objective) and assessment.period_matches(fact, period)


def _objective_proof(requested, passages):
    metrics = requested.metrics or (None,)
    periods = requested.periods or (None,)
    if not requested.metrics and not requested.periods:
        return [p["id"] for p in passages]
    proof = set()
    for metric in metrics:
        for period in periods:
            matched = [p["id"] for p in passages if _matches(p, metric, period, requested)]
            if not matched:
                return []
            proof.update(matched)
    return sorted(proof)


def missing_input(db, run_id, args):
    """A scoped search result can establish a gap in the instrument's retrieved coverage."""
    metric = args["metric"]
    if not isinstance(metric, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", metric):
        raise ValueError("Use a metric identifier, for example dividend_per_share.")
    period = _period(args["period"])
    receipt = db.execute(
        "SELECT * FROM receipts WHERE run_id=? AND tool='search_evidence' ORDER BY commit_seq DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if (
        not receipt
        or receipt["id"] != args["attempt_receipt_id"]
        or receipt["status"] not in ("ok", "partial")
    ):
        raise ValueError("A missing metric must cite this run's latest scoped evidence search.")
    run = db.execute("SELECT context FROM runs WHERE id=?", (run_id,)).fetchone()
    context = json.loads(run["context"])
    requested = assessment.objective(context["question"])
    # Include earlier reads even when a later page has filled with unrelated documents.
    reads = db.execute(
        "SELECT tool,output FROM receipts WHERE run_id=? AND tool IN ('search_evidence','get_evidence') AND status='ok'",
        (run_id,),
    )
    for operation, encoded in reads:
        data = json.loads(encoded)["data"]
        for passage in data["passages"] if operation == "search_evidence" else [data]:
            if (
                evidence.supports_actual(passage.get("financial") or {}, context["instrument"].get("cik"))
                and _matches(passage, metric, period, requested)
                and evidence.still_supported(db, passage, context["cutoff"])
            ):
                raise ValueError("A scoped read returned the requested metric and period.")
    return {
        "metric": metric,
        "period": period,
        **{k: getattr(requested, k) for k in DIMENSIONS},
        "attempt_receipt_id": receipt["id"],
    }


CAPTURE_CAUSES = {
    "unavailable": (
        "temporarily_unavailable",
        "Restore the source connection and repeat the scoped retrieval.",
    ),
    "not_entitled": (
        "not_entitled",
        "Verify the exact endpoint entitlement or use a permitted primary source.",
    ),
    "rate_limited": (
        "rate_limited",
        "Respect the source retry deadline, then retrieve the requested period.",
    ),
    "unsupported": ("unsupported", "Configure a named read route that supports this listing."),
    "partial": (
        "history_missing",
        "Obtain a filing covering this period and the requested financial definition.",
    ),
    "error": (
        "semantics_unverified",
        "Verify the response schema, entity and period before ingesting again.",
    ),
}


def _comparison(db, run_id, args):
    readings = db.execute(
        "SELECT output FROM receipts WHERE run_id=? AND tool IN ('search_evidence','get_evidence') AND status='ok'",
        (run_id,),
    )
    facts = {}
    for row in readings:
        data = json.loads(row["output"])["data"]
        for passage in data.get("passages", [data]):
            f = passage.get("financial") or {}
            facts[passage["id"]] = [
                f.get("company"),
                f.get("metric"),
                f.get("period_start"),
                f.get("period_end"),
            ]
    return {
        "kind": "comparison",
        "operation": args["kind"],
        "pair": [facts.get(args[k]) for k in ("current", "baseline")],
    }


def register(db, run, name, args, status, data, defaults, seq):
    """Return a deduplicated gap. Its status describes the observed cause; lifecycle is separate."""
    capability = name
    requirement = {"kind": name}
    if name == "record_gap":
        metric, period = data["metric"], data["period"]
        requirement = {
            "kind": "metric",
            **{k: data[k] for k in ("metric", "period", *DIMENSIONS)},
        }
        capability = f"financials.{metric} ({period})"
        spec = (
            f"{metric.replace('_', ' ')} for {period}"
            if period != "unspecified"
            else metric.replace("_", " ")
        )
        cause = "history_missing"
        dimensions = ", ".join(data[k] for k in DIMENSIONS if data[k])
        if dimensions:
            spec += " (" + dimensions.replace("_", " ") + ")"
        impact = f"The retrieved evidence lacks {spec} for this listing."
        fallback = "Use available observations only for the questions they answer."
        remedy = f"Retrieve a permitted primary filing or an entitled provider observation for {spec}."
        example = f"Read an eligible {spec} observation with a source version, units and financial basis."
    elif name in defaults and status != "ok":
        cause, impact, fallback, remedy, example = defaults[name]
        if name == "capture_public":
            provider = args["provider"]
            capability = f"capture_public ({provider})"
            cause, remedy = CAPTURE_CAUSES.get(status, ("temporarily_unavailable", remedy))
            if (
                provider == "sec"
                and status == "unavailable"
                and "STOCKINSIGHT_SEC_CONTACT" in data.get("message", "")
            ):
                cause, remedy = (
                    "not_connected",
                    "Configure an identified SEC contact and retry the scoped filing retrieval.",
                )
            requirement["provider"] = provider
        elif name == "compare_financials":
            requirement = _comparison(db, run["id"], args)
            signature = hashlib.sha256(json.dumps(requirement, sort_keys=True).encode()).hexdigest()[:16]
            capability = f"compare_financials ({args['kind']} {signature})"
    else:
        return None
    db.execute(
        "INSERT INTO capability_gaps(id,case_id,capability,status,impact,fallback,remedy,acceptance_example,commit_seq) "
        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id,capability,status) DO UPDATE SET lifecycle='open',"
        "commit_seq=excluded.commit_seq",
        (uid("gap"), run["case_id"], capability, cause, impact, fallback, remedy, example, seq),
    )
    gap_id = db.execute(
        "SELECT id FROM capability_gaps WHERE case_id=? AND capability=? AND status=?",
        (run["case_id"], capability, cause),
    ).fetchone()[0]
    db.execute("INSERT OR IGNORE INTO gap_requirements VALUES(?,?)", (gap_id, json.dumps(requirement)))
    return gap_id


def outstanding(db, run, receipts):
    """As-of this run's actual read boundary, retaining open limitations on the same case."""
    context = json.loads(run["context"])
    at_seq = max([context["at_seq"], *(r["commit_seq"] for r in receipts)])
    rows = db.execute(
        """SELECT g.id FROM capability_gaps g JOIN gap_attempts a ON a.gap_id=g.id
           JOIN receipts r ON r.id=a.receipt_id WHERE g.case_id=? AND r.commit_seq<=?
           GROUP BY g.id HAVING max(r.commit_seq)>coalesce((
               SELECT max(z.commit_seq) FROM gap_resolutions z WHERE z.gap_id=g.id AND z.commit_seq<=?),0)""",
        (context["case_id"], at_seq, at_seq),
    )
    return {r["id"] for r in rows}


def describe(db, case_id, ids):
    if not ids:
        return []
    rows = db.execute(
        """SELECT g.id,g.capability,q.requirement FROM capability_gaps g LEFT JOIN gap_requirements q ON q.gap_id=g.id
           WHERE g.case_id=? ORDER BY g.id""",
        (case_id,),
    )
    result = []
    for row in rows:
        if row["id"] not in ids:
            continue
        req = json.loads(row["requirement"]) if row["requirement"] else {"kind": row["capability"]}
        name = {"metric": "record_gap", "comparison": "compare_financials"}.get(req["kind"], req["kind"])
        item = {"gap_id": row["id"], "tool": name}
        item.update({key: req[key] for key in ("metric", "period", *DIMENSIONS) if key in req})
        result.append(item)
    return result


def _capture_proof(db, run, gap_id, objective, readings):
    # Legacy cases grouped failed transports under capture_public before the recorded
    # requirement became provider-specific. Require proof for each affected source.
    attempts = db.execute(
        """SELECT r.args,max(r.commit_seq) AS last_attempt FROM gap_attempts a
           JOIN receipts r ON r.id=a.receipt_id WHERE a.gap_id=? AND r.tool='capture_public'
           GROUP BY r.args""",
        (gap_id,),
    )
    proof = set()
    for attempt in attempts:
        provider = json.loads(attempt["args"])["provider"]
        rows = db.execute(
            """SELECT output FROM receipts WHERE run_id=? AND tool='capture_public' AND status='ok'
               AND args=? AND commit_seq>?""",
            (run["id"], attempt["args"], attempt["last_attempt"]),
        )
        docs = {json.loads(row["output"])["data"].get("document_id") for row in rows}
        matches = _objective_proof(
            objective, [p for p in readings if p["document_id"] in docs and p["origin"] == provider]
        )
        if not matches:
            return []
        proof.update(matches)
    return sorted(proof)


def reconcile(db, run, name, args, output, seq):
    """Only scope-checked evidence reads and comparable calculations may close an earlier gap."""
    if output["status"] != "ok" or name not in ("search_evidence", "get_evidence", "compare_financials"):
        return
    gaps = db.execute(
        """SELECT g.*,q.requirement FROM capability_gaps g LEFT JOIN gap_requirements q ON q.gap_id=g.id
           WHERE case_id=? AND lifecycle='open'""",
        (run["case_id"],),
    ).fetchall()
    if not gaps:
        return
    context = json.loads(run["context"])
    objective = assessment.objective(context["question"])
    data = output["data"]
    # Exact passage IDs intentionally remain readable after a correction. Only
    # a version still eligible for this assignment may resolve a current gap.
    if name == "compare_financials":
        passages = [
            evidence.get(db, context["instrument"]["id"], ref, context["cutoff"], fixture=is_fixture(db))
            for ref in output["evidence_ids"]
        ]
    else:
        passages = data.get("passages", [data])
    eligible = [
        p
        for p in passages
        if evidence.still_supported(db, p, context["cutoff"])
        and (not p["financial"] or evidence.supports_actual(p["financial"], context["instrument"].get("cik")))
    ]
    readings = eligible if name != "compare_financials" else []
    for gap in gaps:
        req = json.loads(gap["requirement"]) if gap["requirement"] else {"kind": gap["capability"]}
        proof = []
        if req["kind"] == "metric":
            proof = [p["id"] for p in readings if _matches(p, req["metric"], req["period"], objective)]
        elif req["kind"] == "search_evidence":
            proof = _objective_proof(objective, readings)
        elif req["kind"] == "capture_public" and readings:
            proof = _capture_proof(db, run, gap["id"], objective, readings)
        elif (
            req["kind"] == "comparison"
            and name == "compare_financials"
            and req == _comparison(db, run["id"], args)
            and len(eligible) == len(output["evidence_ids"])
        ):
            proof = output["evidence_ids"]
        if proof:
            db.execute(
                "INSERT INTO gap_resolutions VALUES(?,?,?,?)",
                (gap["id"], output["receipt_id"], json.dumps(proof), seq),
            )
            db.execute(
                "UPDATE capability_gaps SET lifecycle='resolved',commit_seq=? WHERE id=?", (seq, gap["id"])
            )
