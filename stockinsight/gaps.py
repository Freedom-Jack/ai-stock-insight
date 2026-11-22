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
    dimensions = objective.dimensions_for(metric, period)
    return assessment.matches_dimensions(fact, dimensions) and assessment.period_matches(fact, period)


def _objective_proof(requested, passages):
    if not requested.bindings_complete:
        return []
    requirements = requested.requirements or [(None, p) for p in requested.periods]
    if not requirements:
        return [p["id"] for p in passages]
    proof = set()
    for metric, period in requirements:
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
        "SELECT * FROM receipts WHERE run_id=? AND tool IN ('search_evidence','next_evidence_page') ORDER BY commit_seq DESC LIMIT 1",
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
    dimensions = requested.dimensions_for(metric, period)
    # Include earlier reads even when a later page has filled with unrelated documents.
    reads = db.execute(
        "SELECT tool,version,output FROM receipts WHERE run_id=? AND tool IN ('search_evidence','next_evidence_page','get_evidence') AND status='ok'",
        (run_id,),
    )
    for operation, version, encoded in reads:
        data = json.loads(encoded)["data"]
        passages = data["passages"] if operation != "get_evidence" else [data]
        if operation == "search_evidence" and version == "1":
            # The previous worker projection exposed just the first sixteen IDs.
            passages = passages[:16]
        for passage in passages:
            if (
                evidence.supports_actual(passage.get("financial") or {}, context["instrument"].get("cik"))
                and _matches(passage, metric, period, requested)
                and evidence.still_supported(db, passage, context["cutoff"])
            ):
                raise ValueError("A scoped read returned the requested metric and period.")
    return {
        "metric": metric,
        "period": period,
        **{k: getattr(dimensions, k) for k in DIMENSIONS},
        "attempt_receipt_id": receipt["id"],
        "search_has_more": bool(json.loads(receipt["output"])["data"].get("has_more")),
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


_SERIES_FIELDS = ("company", "metric", "period_start", "period_end")
_COMPARABLE_FIELDS = ("currency", "unit", "basis", "share_basis", "duration")


def _comparison(db, run_id, args, *, requirement=False):
    readings = db.execute(
        "SELECT output FROM receipts WHERE run_id=? AND tool IN ('search_evidence','next_evidence_page','get_evidence') AND status='ok'",
        (run_id,),
    )
    facts = {}
    for row in readings:
        data = json.loads(row["output"])["data"]
        for passage in data.get("passages", [data]):
            f = passage.get("financial") or {}
            facts[passage["id"]] = f
    left, right = (facts.get(args[k], {}) for k in ("current", "baseline"))
    pair = [[f.get(k) for k in _SERIES_FIELDS] for f in (left, right)]
    if any(not all(part) for part in pair) or left is right:
        # An unknown ID, a non-financial cell, or a repeated operand is an input
        # error. It supplies no evidence that the underlying metric is missing.
        return None
    if args["kind"] == "period_trend":
        if pair[0][:2] != pair[1][:2] or pair[0][2:] == pair[1][2:]:
            return None
        # The question compares these two periods. Only the calculation needs
        # an ordered current and baseline; a mistaken order is still this gap.
        pair.sort()
    dimensions = {
        key: left[key] for key in _COMPARABLE_FIELDS if left.get(key) and left[key] == right.get(key)
    }
    if requirement:
        row = db.execute("SELECT context FROM runs WHERE id=?", (run_id,)).fetchone()
        objective = assessment.objective(json.loads(row["context"])["question"])
        rules = [rule for f in (left, right) for rule in _fact_rules(objective, f)]
        for key in ("basis", "currency", "duration", "share_basis"):
            explicit = {getattr(rule, key) for rule in rules if getattr(rule, key)}
            if len(explicit) == 1:
                value = next(iter(explicit))
                if key in ("currency", "share_basis") and dimensions.get(key) != value:
                    dimensions.pop("unit", None)
                dimensions[key] = value
        if "unit" in dimensions and any(
            rule.unit_scale and rule.unit_scale not in dimensions["unit"].lower().split() for rule in rules
        ):
            del dimensions["unit"]
    return {"kind": "comparison", "operation": args["kind"], "pair": pair, "dimensions": dimensions}


def _stored_requirement(db, gap):
    req = json.loads(gap["requirement"]) if gap["requirement"] else {"kind": gap["capability"]}
    if req.get("kind") != "comparison" or "dimensions" in req:
        return req
    # Recover the intended series and its units from the genuine failed v2
    # receipt. Leave the immutable prior requirement and reviewed brief intact.
    row = db.execute(
        """SELECT r.run_id,r.args FROM gap_attempts a JOIN receipts r ON r.id=a.receipt_id
           WHERE a.gap_id=? AND r.tool='compare_financials' AND r.status='invalid_input'
           ORDER BY r.commit_seq LIMIT 1""",
        (gap["id"],),
    ).fetchone()
    return (_comparison(db, row["run_id"], json.loads(row["args"]), requirement=True) if row else None) or req


def _proves_comparison(req, actual):
    return bool(
        actual
        and "dimensions" in req
        and req["operation"] == actual["operation"]
        and req["pair"] == actual["pair"]
        and all(actual["dimensions"].get(k) == v for k, v in req["dimensions"].items())
    )


def _fact_rules(objective, fact):
    return [
        objective.dimensions_for(metric, period)
        for metric, period in objective.requirements
        if metric == fact["metric"] and assessment.period_matches(fact, period)
    ] or [objective]


def _comparison_dimensions_match(objective, passages):
    for passage in passages:
        fact = passage["financial"]
        if not any(assessment.matches_dimensions(fact, rule) for rule in _fact_rules(objective, fact)):
            return False
    return True


def _eligible(db, context, passages):
    return [
        p
        for p in passages
        if evidence.still_supported(db, p, context["cutoff"])
        and (not p["financial"] or evidence.supports_actual(p["financial"], context["instrument"].get("cik")))
    ]


def _earlier_proof(db, run, req):
    context = json.loads(run["context"])
    objective = assessment.objective(context["question"])
    successes = db.execute(
        """SELECT s.id,s.run_id,s.args,s.output FROM receipts s JOIN runs r ON r.id=s.run_id
           JOIN jobs j ON j.id=r.job_id WHERE j.case_id=? AND s.tool='compare_financials'
           AND s.status='ok' ORDER BY s.commit_seq DESC""",
        (run["case_id"],),
    )
    for receipt in successes:
        actual = _comparison(db, receipt["run_id"], json.loads(receipt["args"]))
        if not _proves_comparison(req, actual):
            continue
        refs = json.loads(receipt["output"])["evidence_ids"]
        try:
            passages = [
                evidence.get(db, context["instrument"]["id"], ref, context["cutoff"], fixture=is_fixture(db))
                for ref in refs
            ]
            valid = _eligible(db, context, passages)
            for version in {p["document_id"] for p in valid if p["retention"] == "full"}:
                evidence.document_bytes(db, context["instrument"]["id"], version)
        except ValueError:
            continue
        if len(valid) == 2 and _comparison_dimensions_match(objective, valid):
            return receipt["id"]
    return None


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
        if name == "price_context" and "calculation" in data:
            start, end = data.get("start"), data.get("end")
            requirement.update(start=start, end=end)
            capability = f"price_context ({start} to {end})" if start and end else "price_context (session dates)"
            cause = "history_missing" if not data["calculation"] else "unsupported"
            impact = " ".join(data["gaps"]) or "The complete requested price window is unresolved."
            remedy = ("Use the Methods page to import matching attributed regular closes, "
                      "or ask a single-listing, two-date closing-price question.")
            fallback = "Use only the session endpoints and price arithmetic actually observed."
            example = "Return the requested two dated closes for one listing, currency, series and adjustment basis."
        elif name == "capture_public":
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
            requirement = _comparison(db, run["id"], args, requirement=True)
            if requirement is None:
                return None
            signature = hashlib.sha256(json.dumps(requirement, sort_keys=True).encode()).hexdigest()[:16]
            capability = f"compare_financials ({args['kind']} {signature})"
            existing = db.execute(
                "SELECT g.id,g.capability,g.lifecycle,q.requirement FROM capability_gaps g JOIN gap_requirements q ON q.gap_id=g.id "
                "WHERE g.case_id=? AND g.status=? AND json_extract(q.requirement,'$.kind')='comparison'",
                (run["case_id"], cause),
            )
            matching = next((g for g in existing if _stored_requirement(db, g) == requirement), None)
            if matching:
                capability = matching["capability"]
            if not matching or matching["lifecycle"] == "resolved":
                prior = _earlier_proof(db, run, requirement)
                if prior:
                    # A still-valid case calculation is proof of availability. It grants
                    # no read or submission permission to the new worker.
                    data["covered_by_receipt_id"] = prior
                    return None
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


def _read_history(db, run, context):
    """Return the latest worker-visible read of each still-eligible exact passage."""
    rows = db.execute(
        """SELECT tool,version,id,commit_seq,output FROM receipts WHERE run_id=? AND status='ok'
           AND tool IN ('search_evidence','next_evidence_page','get_evidence') ORDER BY commit_seq""",
        (run["id"],),
    )
    history = {}
    for row in rows:
        data = json.loads(row["output"])["data"]
        passages = data["passages"] if row["tool"] != "get_evidence" else [data]
        if row["tool"] == "search_evidence" and row["version"] == "1":
            passages = passages[:16]
        for p in passages:
            history[p["id"]] = (row["commit_seq"], row["id"], p)
    supported = _eligible(db, context, [p for _, _, p in history.values()])
    return {p["id"]: history[p["id"]] for p in supported}


def _capture_proof(db, run, gap_id, objective, history):
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
            """SELECT output,commit_seq FROM receipts WHERE run_id=? AND tool='capture_public' AND status='ok'
               AND args=? AND commit_seq>? ORDER BY commit_seq""",
            (run["id"], attempt["args"], attempt["last_attempt"]),
        )
        docs = {}
        for row in rows:
            docs.setdefault(json.loads(row["output"])["data"].get("document_id"), row["commit_seq"])
        matches = _objective_proof(
            objective,
            [
                p
                for seq, _, p in history.values()
                if p["document_id"] in docs and seq > docs[p["document_id"]] and p["origin"] == provider
            ],
        )
        if not matches:
            return []
        proof.update(matches)
    return sorted(proof)


def reconcile(db, run, name, args, output, seq):
    """Only scope-checked evidence reads and comparable calculations may close an earlier gap."""
    if output["status"] != "ok" or name not in (
        "search_evidence",
        "next_evidence_page",
        "get_evidence",
        "compare_financials",
        "price_context",
    ):
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
    price_proof = []
    if name == "price_context":
        from . import price_research

        if (context["method"] != price_research.METHOD or not data.get("calculation")
                or price_research.window(db, context) != data):
            return
        price_proof = data["evidence_ids"]
    # Exact passage IDs intentionally remain readable after a correction. Only
    # a version still eligible for this assignment may resolve a current gap.
    if name == "compare_financials":
        passages = [
            evidence.get(db, context["instrument"]["id"], ref, context["cutoff"], fixture=is_fixture(db))
            for ref in output["evidence_ids"]
        ]
    else:
        passages = data.get("passages", [data])
    eligible = _eligible(db, context, passages)
    readings = eligible if name != "compare_financials" else []
    history = None
    for gap in gaps:
        req = _stored_requirement(db, gap)
        proof = []
        receipts = {output["receipt_id"]}
        if req["kind"] == "price_context" and price_proof and (
            not req.get("start") or (req["start"], req["end"]) == (data["start"], data["end"])
        ):
            proof = price_proof
        elif req["kind"] == "metric":
            proof = [p["id"] for p in readings if _matches(p, req["metric"], req["period"], objective)]
        elif req["kind"] in ("search_evidence", "capture_public") and readings:
            if history is None:
                history = _read_history(db, run, context)
            if req["kind"] == "capture_public":
                proof = _capture_proof(db, run, gap["id"], objective, history)
            else:
                last = db.execute(
                    """SELECT max(r.commit_seq) FROM gap_attempts a JOIN receipts r ON r.id=a.receipt_id
                       WHERE a.gap_id=?""",
                    (gap["id"],),
                ).fetchone()[0]
                proof = _objective_proof(objective, [p for n, _, p in history.values() if n > last])
            receipts = {history[ref][1] for ref in proof}
        elif (
            req["kind"] == "comparison"
            and name == "compare_financials"
            and _proves_comparison(req, _comparison(db, run["id"], args))
            and len(eligible) == len(output["evidence_ids"])
            and _comparison_dimensions_match(objective, eligible)
        ):
            proof = output["evidence_ids"]
        if proof:
            output.setdefault("resolved_gaps", []).append(
                {"gap_id": gap["id"], "passage_ids": proof, "proof_receipt_ids": sorted(receipts)}
            )
            db.execute(
                "INSERT INTO gap_resolutions VALUES(?,?,?,?)",
                (gap["id"], output["receipt_id"], json.dumps(proof), seq),
            )
            db.execute(
                "UPDATE capability_gaps SET lifecycle='resolved',commit_seq=? WHERE id=?", (seq, gap["id"])
            )
