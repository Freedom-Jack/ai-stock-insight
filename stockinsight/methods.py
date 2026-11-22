"""Versioned local research methods. Each saved report pins inputs, assumptions and arithmetic."""

import csv
import hashlib
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from statistics import median

from . import events, evidence, universe
from .db import instant, is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE method_reports(
    id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments, method TEXT NOT NULL,
    event_version_id TEXT REFERENCES event_versions, goal_id TEXT, scope TEXT NOT NULL,
    prior_id TEXT REFERENCES method_reports, dedup_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL,
    created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits
);
CREATE INDEX method_reports_listing ON method_reports(instrument_id,commit_seq DESC);
CREATE TABLE method_expectations(
    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, event_version_id TEXT NOT NULL REFERENCES event_versions,
    instrument_id TEXT NOT NULL REFERENCES instruments, source_ref TEXT NOT NULL REFERENCES evidence_passages,
    kind TEXT NOT NULL, fact TEXT NOT NULL, source_as_of TEXT NOT NULL, captured_at TEXT NOT NULL,
    prior_id TEXT REFERENCES method_expectations, commit_seq INTEGER NOT NULL REFERENCES commits
);
CREATE TABLE method_cohorts(
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES instruments, rule TEXT NOT NULL,
    members TEXT NOT NULL, frozen_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits
);
"""

METRICS = ("revenue", "earnings_per_share", "net_income", "operating_margin", "free_cash_flow", "close_price")
EXPECTATIONS = ("issuer_guidance", "street_consensus", "model_estimate", "operator_scenario")
FOCI = ("disclosure", "expectations", "exposure")
PRICE_FIELDS = (
    "ticker",
    "exchange",
    "session_date",
    "session_end",
    "currency",
    "official_close",
    "adjustment",
    "adjustment_as_of",
    "delay_seconds",
)
METHODS = {
    "dossier.v1": "Company orientation and ranked questions",
    "earnings_preparation.v1": "Earnings preparation",
    "earnings_review.v1": "Earnings release review",
    "event_review.v1": "Event and policy assessment",
    "peer_comparison.v1": "Comparable-company financials",
    "valuation_sensitivity.v1": "Multiple-based valuation sensitivity",
    "price_window.v1": "Dated market-session price comparison",
    "historical_cohort.v1": "Declared-period financial cohort",
}


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_encode(value).encode()).hexdigest()


def _body():
    return {
        "claims": [],
        "citations": [],
        "calculations": [],
        "alternatives": [],
        "next_observations": [],
        "gaps": [],
    }


def _claim(body, text, *sources):
    for source in sources:
        if any(s["id"] == source["id"] for s in body["citations"]):
            continue
        citation = {
            k: source[k]
            for k in (
                "id",
                "instrument_id",
                "document_id",
                "version_hash",
                "parser_version",
                "precision",
                "origin",
                "title",
                "text",
                "locator",
                "source_url",
                "available_at",
                "published_at",
                "received_at",
                "fixture",
                "financial",
            )
        }
        citation["url"] = citation["source_url"]
        if source["origin"] == "issuer_news":
            meta = json.loads(source["locator"])
            citation.update(url=meta["link"], published_at=meta["published_at"])
        body["citations"].append(citation)
    body["claims"].append({"text": text, "passage_ids": [s["id"] for s in sources]})


def export(db, report_id):
    row = db.execute("SELECT * FROM method_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise ValueError("Unknown research report.")
    return {**dict(row), "body": json.loads(row["body"])}


def _save(db, seq, listing, method, title, summary, body, *, scope=None, event=None, goal=None, key=None):
    scope = scope or _digest([listing["id"], method])
    key = key or _digest([scope, method, summary, body])
    prior = db.execute("SELECT id FROM method_reports WHERE dedup_key=?", (key,)).fetchone()
    if prior:
        return export(db, prior["id"])
    previous = db.execute(
        "SELECT id FROM method_reports WHERE scope=? ORDER BY commit_seq DESC LIMIT 1", (scope,)
    ).fetchone()
    ident = uid("report")
    db.execute(
        "INSERT INTO method_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            listing["id"],
            method,
            event,
            goal,
            scope,
            previous["id"] if previous else None,
            key,
            title,
            summary,
            "partial" if body["gaps"] else "supported",
            _encode(body),
            now(),
            seq,
        ),
    )
    return export(db, ident)


def _get(db, listing, ref, cutoff=None, *, current=True):
    p = evidence.get(db, listing["id"], ref, cutoff, fixture=is_fixture(db))
    if current and not evidence.still_supported(db, p, cutoff):
        raise ValueError("This source has a superseding edition. Reopen the current evidence.")
    return p


def _qualifications(db, body, cutoff):
    """Attach narrative to each cited financial edition at the report's stated information boundary."""
    financials = {p["document_id"]: p for p in body["citations"] if p["financial"]}
    coverage = body.setdefault("disclosure_coverage", [])
    for document, number in financials.items():
        notes = db.execute(
            """SELECT id,count(*) OVER () AS total FROM evidence_passages
               WHERE document_id=? AND financial IS NULL AND available_at<=?
               ORDER BY locator,id LIMIT 16""",
            (document, cutoff),
        ).fetchall()
        total = notes[0]["total"] if notes else 0
        coverage.append(
            {
                "document_id": document,
                "source_ref": number["id"],
                "source_url": number["url"],
                "as_of": cutoff,
                "reviewed": len(notes),
                "unreviewed": total - len(notes),
            }
        )
        for note in notes:
            passage = evidence.get(db, number["instrument_id"], note["id"], cutoff, fixture=is_fixture(db))
            _claim(body, "Qualification in the same disclosure: " + passage["text"], passage, number)
        if total > len(notes):
            body["gaps"].append(
                f"{total - len(notes)} additional retained narrative passages in {number['title']} remain unreviewed "
                f"at {cutoff}. Open cited source {number['id']} for document {document}."
            )


def _numbers(db, listing, *, metric=None, end=None, before=None, cutoff=None, role="actual", limit=40):
    """Select by financial semantics before limiting, using the same as-of edition boundary as search."""
    clauses = [
        "d.instrument_id=?",
        "d.fixture=?",
        "p.financial IS NOT NULL",
        "json_extract(p.financial,'$.role')=?",
    ]
    args = [listing["id"], int(is_fixture(db)), role]
    for field, value in (("metric", metric), ("period_end", end)):
        if value:
            clauses.append(f"json_extract(p.financial,'$.{field}')=?")
            args.append(value)
    if cutoff:
        clauses.append("p.available_at<=?")
        args.append(cutoff)
    if before:
        clauses.append("json_extract(p.financial,'$.period_end')<?")
        args.append(before)
    clauses.append("""NOT EXISTS(SELECT 1 FROM documents n WHERE n.instrument_id=d.instrument_id
        AND n.source_url=d.source_url AND n.origin=d.origin AND n.fixture=d.fixture AND n.commit_seq>d.commit_seq
        AND EXISTS(SELECT 1 FROM evidence_passages np WHERE np.document_id=n.id AND (? IS NULL OR np.available_at<=?)))""")
    args.extend((cutoff, cutoff, limit))
    rows = db.execute(
        "SELECT p.id FROM evidence_passages p JOIN documents d ON d.id=p.document_id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY json_extract(p.financial,'$.period_end') DESC,d.commit_seq DESC,p.locator LIMIT ?",
        args,
    )
    output = []
    for row in rows:
        p = _get(db, listing, row["id"], cutoff)
        if evidence.supports_actual({**p["financial"], "role": "actual"}, listing.get("cik")):
            output.append(p)
    return output


def _event(db, version, *, current=True):
    row = db.execute("SELECT * FROM event_versions WHERE id=?", (version,)).fetchone()
    if not row:
        raise ValueError("Unknown event version.")
    if current and events.at_commit(db, row["event_id"])["id"] != version:
        raise ValueError("The event changed. Reopen the latest edition.")
    return dict(row)


def _boundary(event):
    when = event["occurred_at"] or event["scheduled_start"]
    if not when:
        return None
    if event["precision"] == "instant":
        return instant(when)
    # Without a time, use the earliest possible UTC instant of the publisher's day.
    return instant((datetime.fromisoformat(when).replace(tzinfo=UTC) - timedelta(hours=14)).isoformat())


def _published_lower_bound(value):
    if not value:
        return None
    if len(value) == 10:
        return _boundary({"occurred_at": value, "precision": "day"})
    return instant(value)


def _fiscal_value(p):
    f = p["financial"]
    return f"{f['basis']} {f['metric'].replace('_', ' ')} of {f['value']} {f['unit']} for {f['period_label']}"


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use an exact calendar date.")
    return value


def freeze_expectation(db, version, passage_id, *, value=None, start=None, end=None):
    """Freeze a sourced expectation or an explicitly operator-authored conditional baseline."""
    with write(db) as seq:
        event = _event(db, version)
        listing = universe.instrument(db, event["instrument_id"])
        captured = now()
        p = _get(db, listing, passage_id, captured)
        fact = dict(p.get("financial") or {})
        if not evidence.supports_actual({**fact, "role": "actual"}, listing["cik"]):
            raise ValueError("Select a verified financial basis for this issuer.")
        if value not in ("", None):
            if fact["role"] != "actual" or _date(start) > _date(end):
                raise ValueError("A scenario requires a reported basis and an ordered target period.")
            # An operator estimate inherits the cited units, accounting basis, share basis and duration.
            fstart, fend = evidence._period(fact)
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days
            if abs(span - (fend - fstart).days) > 8:
                raise ValueError("The target period duration does not match the cited financial basis.")
            fact.update(
                role="operator_scenario",
                value=str(evidence._number(value)),
                period_start=start,
                period_end=end,
                period_label=f"{start} to {end}",
            )
        elif fact.get("role") not in EXPECTATIONS[:-1]:
            raise ValueError(
                "An actual is usable as an assumption only with an explicit scenario value and target period."
            )
        as_of = captured if fact["role"] == "operator_scenario" else p["available_at"]
        if as_of > captured:
            raise ValueError("The expectation is future dated.")
        prior = None
        for row in db.execute(
            "SELECT * FROM method_expectations WHERE event_id=? AND kind=? ORDER BY commit_seq DESC",
            (event["event_id"], fact["role"]),
        ):
            prev = json.loads(row["fact"])
            fields = (
                "metric",
                "period_start",
                "period_end",
                "basis",
                "unit",
                "currency",
                "duration",
                "share_basis",
            )
            if all(prev[k] == fact[k] for k in fields):
                prior = row
                break
        if prior and prior["source_ref"] == p["id"] and json.loads(prior["fact"]) == fact:
            return prior["id"]
        ident = uid("expectation")
        db.execute(
            "INSERT INTO method_expectations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                event["event_id"],
                version,
                listing["id"],
                p["id"],
                fact["role"],
                _encode(fact),
                as_of,
                captured,
                prior["id"] if prior else None,
                seq,
            ),
        )
        return ident


def _expectations(db, event, listing, source, body):
    saved = db.execute(
        "SELECT * FROM method_expectations WHERE event_id=? ORDER BY commit_seq", (event["event_id"],)
    ).fetchall()
    boundary = _boundary(event)
    if event["state"] == "occurred" and source.get("financial"):
        limits = [
            v
            for v in (
                boundary,
                _published_lower_bound(source["published_at"]),
                _published_lower_bound(source["financial"].get("filed")),
            )
            if v
        ]
        boundary = min(limits) if limits else None
    body["expectations"] = []
    for row in saved:
        fact = json.loads(row["fact"])
        p = _get(db, listing, row["source_ref"], current=False)
        frozen = bool(boundary and max(row["captured_at"], row["source_as_of"]) < boundary)
        body["expectations"].append(
            {
                "id": row["id"],
                "prior_id": row["prior_id"],
                "kind": row["kind"],
                "captured_at": row["captured_at"],
                "as_of": row["source_as_of"],
                "fact": fact,
                "pre_event": frozen,
                "source_ref": p["id"],
                "source_version_hash": p["version_hash"],
            }
        )
        label = "Revised" if row["prior_id"] else "Original"
        _claim(
            body,
            f"{label} {row['kind'].replace('_', ' ')}: {fact['value']} {fact['unit']} for {fact['period_label']}.",
            p,
        )
        if not frozen or event["state"] != "occurred" or not source.get("financial"):
            continue
        actual = source["financial"]
        if not evidence.supports_actual(actual, listing["cik"]):
            continue
        baseline = {
            **p,
            "id": row["id"],
            "available_at": max(row["source_as_of"], row["captured_at"]),
            "financial": {
                **fact,
                "role": "model_estimate" if row["kind"] == "operator_scenario" else row["kind"],
            },
        }
        try:
            result = evidence.compare({**source, "published_at": boundary}, baseline, "actual_vs_expectation")
        except ValueError:
            body["gaps"].append(f"{label} {row['kind']} has no matching actual on the same period and basis.")
            continue
        result.update(
            baseline_role=row["kind"], expectation_id=row["id"], source_passage_ids=[source["id"], p["id"]]
        )
        body["calculations"].append(result)
        _claim(
            body,
            f"The reported amount differs from the {label.lower()} {row['kind'].replace('_', ' ')} by {result['difference']} {result['unit']}.",
            source,
            p,
        )
    if not any(x["kind"] == "street_consensus" and x["pre_event"] for x in body["expectations"]):
        body["gaps"].append("A frozen pre-release Street consensus on the same basis is unavailable.")
    if saved and not any(x["pre_event"] for x in body["expectations"]):
        body["gaps"].append("The stored expectations have no verified pre-event capture.")


def _trend(db, listing, current, body, cutoff=None):
    if not current or not evidence.supports_actual(current.get("financial") or {}, listing["cik"]):
        return
    for other in _numbers(
        db,
        listing,
        metric=current["financial"]["metric"],
        before=current["financial"]["period_start"],
        cutoff=cutoff,
    ):
        try:
            result = evidence.compare(current, other, "period_trend")
        except ValueError:
            continue
        body["calculations"].append(result)
        _claim(
            body,
            f"Change from {result['baseline_period']} to {result['current_period']}: {result['difference']} {result['unit']}.",
            current,
            other,
        )
        return
    body["gaps"].append(
        "The reviewed earlier observations did not establish a comparable period for this measure."
    )


def _exposures(db, listing, stamp, body, approved=()):
    matches = db.execute(
        """SELECT e.*,a.name AS source_company,b.name AS target_company FROM exposures e
           JOIN companies a ON a.id=e.from_company_id JOIN companies b ON b.id=e.to_company_id
           WHERE e.status='supported' AND (e.from_company_id=? OR e.to_company_id=?) AND e.valid_from<=?
           AND (e.valid_until IS NULL OR e.valid_until>?) ORDER BY e.commit_seq DESC LIMIT 6""",
        (listing["company_id"], listing["company_id"], stamp, stamp),
    )
    count = 0
    linked = {edge["legacy_id"] for edge in approved if edge.get("legacy_id")}
    for edge in approved:
        support = _get(db, listing, edge["passage_id"])
        event_ref = edge["event_passage_id"]
        hit = db.execute(
            "SELECT d.instrument_id FROM documents d JOIN evidence_passages p ON d.id=p.document_id WHERE p.id=?",
            (event_ref,),
        ).fetchone()
        trigger = evidence.get(db, hit["instrument_id"], event_ref, fixture=is_fixture(db))
        _claim(
            body,
            f"Approved {edge['relation'].replace('_', ' ')} relationship for {listing['ticker']} with {edge['entity']}. Operator rationale: {edge['reason']}",
            support,
            trigger,
        )
        body["claims"][-1]["kind"] = "reviewed_relationship"
        count += 1
    for row in matches:
        if row["id"] in linked:
            continue
        refs = []
        for ref in json.loads(row["evidence_refs"]):
            hit = db.execute(
                """SELECT d.instrument_id FROM evidence_passages p JOIN documents d ON d.id=p.document_id
                WHERE p.id=? AND d.fixture=? AND p.available_at<=?""",
                (ref, int(is_fixture(db)), stamp),
            ).fetchone()
            if not hit:
                break
            p = evidence.get(db, hit["instrument_id"], ref, stamp, fixture=is_fixture(db))
            if not evidence.still_supported(db, p, stamp):
                break
            refs.append(p)
        else:
            if refs:
                count += 1
                _claim(
                    body,
                    f"Recorded relationship: {row['source_company']} → {row['target_company']}: {row['relation']}. Qualification: {row['uncertainty']}.",
                    *refs,
                )
    if not count:
        body["gaps"].append("No dated, supported company relationship establishes indirect exposure.")


def _time_span(event):
    start = event["occurred_at"] or event["scheduled_start"]
    end = None if event["occurred_at"] else event["scheduled_end"]
    if not start:
        return "time unknown"
    span = f"{start} through {end}" if end and end != start else start
    if event["precision"] == "day":
        span += (
            " (calendar-date precision"
            + (f", {event['source_timezone']}" if event["source_timezone"] else "")
            + ")"
        )
    return span


def event_report(
    db, event_version_id, *, goal_id=None, objective="", focus=None, request_key=None, instrument_id=None
):
    from . import exposure

    if focus and focus not in FOCI:
        raise ValueError("Unknown event investigation focus.")
    if not isinstance(objective, str) or len(objective) > 3000:
        raise ValueError("Supply a bounded research objective.")
    if request_key is not None and (not isinstance(request_key, str) or not 1 <= len(request_key) <= 160):
        raise ValueError("Invalid dispatch request key.")
    with write(db) as seq:
        event = _event(db, event_version_id, current=False)
        subject = instrument_id if instrument_id is not None else event["instrument_id"]
        direct = subject == event["instrument_id"]
        dispatch_key = _digest(["dispatch", request_key]) if request_key else None
        if dispatch_key:
            replay = db.execute(
                "SELECT id,instrument_id,event_version_id,goal_id FROM method_reports WHERE dedup_key=?",
                (dispatch_key,),
            ).fetchone()
            if replay:
                if (replay["event_version_id"], replay["goal_id"], replay["instrument_id"]) != (
                    event_version_id,
                    goal_id,
                    subject,
                ):
                    raise ValueError(
                        "The dispatch key already belongs to a different event, goal or listing."
                    )
                return export(db, replay["id"])
        earnings = direct and event["kind"] in (
            "earnings_release",
            "earnings_call",
            "earnings",
            "financial_filing",
        )
        preview = event["state"] in ("confirmed", "tentative", "postponed")
        method = (
            "earnings_preparation.v1"
            if earnings and preview
            else "earnings_review.v1"
            if earnings and event["state"] == "occurred"
            else "event_review.v1"
        )
        focus = focus or ("expectations" if earnings else "disclosure")
        fixed_key = dispatch_key or (
            _digest([goal_id, event_version_id, subject, method, objective, focus]) if goal_id else None
        )
        if fixed_key:
            previous = db.execute("SELECT id FROM method_reports WHERE dedup_key=?", (fixed_key,)).fetchone()
            if previous:
                return export(db, previous["id"])
        event = _event(db, event_version_id)
        listing = universe.instrument(db, subject)
        event_listing = universe.instrument(db, event["instrument_id"])
        approved = exposure.for_event(db, listing, event_version_id)
        if not direct and not approved:
            raise ValueError("This event lacks an approved relationship to the research listing.")
        source = _get(db, event_listing, event["source_ref"], current=False)
        body = _body()
        body.update(event=event, objective=objective, focus=focus)
        time = _time_span(event)
        company = event_listing.get("company_name") or event_listing["ticker"]
        title = f"{company} {event['kind'].replace('_', ' ')}"
        if not direct:
            title += f" · relevance to {listing['ticker']}"
        summary = f"{company} {event['kind'].replace('_', ' ')} was recorded as {event['state']} ({time})."
        calendar = db.execute(
            """SELECT title,relevance FROM calendar_reports WHERE source_ref=? AND instrument_id=?
            ORDER BY commit_seq DESC LIMIT 1""",
            (source["id"], event_listing["id"]),
        ).fetchone()
        fed_calendar = event["kind"] == "monetary_policy_meeting" and source["origin"] == "fed_calendar"
        if fed_calendar:
            title = f"Federal Reserve meeting · relevance to {listing['ticker']}"
            summary = f"The Federal Reserve calendar lists the FOMC meeting as {event['state']}, {time}."
        elif calendar:
            title = calendar["title"] + (f" · relevance to {listing['ticker']}" if not direct else "")
            summary = f"{calendar['title']} is {event['state']}, {time}."
        if source["origin"] == "issuer_news":
            summary = f"{event_listing['ticker']} published “{source['text']}” on {time}."
        _claim(body, summary, source)
        if calendar and direct:
            body["relevance"] = calendar["relevance"]
            _claim(body, "Relevance to the research listing: " + calendar["relevance"], source)
            body["claims"][-1]["kind"] = "conditional_relevance"
        if event["supersedes"] and event["state"] in ("cancelled", "postponed", "unknown"):
            prior = _event(db, event["supersedes"], current=False)
            prior_source = _get(db, event_listing, prior["source_ref"], current=False)
            _claim(
                body,
                f"The prior edition showed {_time_span(prior)}. The current edition is {event['state']}.",
                source,
                prior_source,
            )
            body["next_observations"].append(
                "Check the issuing calendar for a confirmed replacement or explicit cancellation before preparing against the earlier date."
            )
        if not source.get("financial") and source["origin"] != "issuer_news":
            _claim(body, source["text"], source)
        if not evidence.still_supported(db, source, None):
            body["gaps"].append(
                "A newer source edition differs from the cited event observation. Verify the event revision."
            )
        if source.get("financial") and evidence.supports_actual(source["financial"], listing["cik"]):
            _claim(body, f"The event source records {_fiscal_value(source)}.", source)
        disclosure_cutoff = min(now(), instant(source["available_at"]))
        context_cutoff = disclosure_cutoff
        if event["state"] == "occurred" and _boundary(event):
            context_cutoff = min(context_cutoff, _boundary(event))
        body["context_as_of"] = context_cutoff
        if not source.get("financial") and focus == "disclosure":
            known = _numbers(db, listing, cutoff=context_cutoff, limit=1)
            if known:
                _claim(
                    body,
                    f"The latest reported financial context in the reviewed corpus was {_fiscal_value(known[0])}.",
                    known[0],
                )
        if direct and (earnings or focus == "expectations"):
            _expectations(db, event, listing, source, body)
            if earnings and event["state"] == "occurred":
                _trend(db, listing, source, body, cutoff=context_cutoff)
        if approved or focus == "exposure" or "policy" in event["kind"]:
            _exposures(db, listing, min(now(), _boundary(event) or now()), body, approved)
        _qualifications(db, body, disclosure_cutoff)
        if event["kind"] == "monetary_policy_meeting":
            body["alternatives"].extend(
                [
                    "If policy tightens, financing costs or discounted valuations may change. Check the decision and actual company borrowing terms.",
                    "Unchanged policy or prior market anticipation could mute that transmission. Check the statement and dated expectations.",
                ]
            )
            body["next_observations"].append(
                "Compare the published policy statement and implementation note with the scheduled meeting."
            )
        if focus == "expectations":
            body["next_observations"].append(
                "Retrieve the dated outlook or consensus and reconcile units, fiscal period and reporting basis at the next release."
            )
        elif focus == "exposure":
            body["next_observations"].append(
                "Check the named counterparties, geographic scope and effective date in the implementing document or company filing."
            )
        else:
            body["next_observations"].append(
                "Read the next issuer release or filing for quantified changes to demand, margins or guidance."
            )
        if preview:
            body["next_observations"].append(
                "Record the original expectation before publication and compare the actual when available."
            )
        if earnings:
            body["alternatives"].append(
                "Timing or product mix could account for a reported change. Check segment disclosures and the next comparable quarter."
            )
            body["gaps"].append(
                "The saved evidence does not establish a verified market-price reaction or a full call transcript."
            )
        else:
            body["alternatives"].append(
                "Publication establishes the announcement. Implementation, customer uptake and financial effects require subsequent evidence."
            )
            body["gaps"].append("A quantified earnings impact or directional market move is unverified.")
        return _save(
            db,
            seq,
            listing,
            method,
            title,
            summary,
            body,
            event=event_version_id,
            goal=goal_id,
            scope=_digest([listing["id"], event["event_id"], goal_id, focus]),
            key=fixed_key,
        )


def dossier(db, instrument_id):
    with write(db) as seq:
        listing = universe.instrument(db, instrument_id)
        body = _body()
        observations = _numbers(db, listing)
        latest = {}
        for p in observations:
            latest.setdefault(p["financial"]["metric"], p)
        for p in list(latest.values())[:4]:
            _claim(body, f"{listing['ticker']} reported {_fiscal_value(p)}.", p)
        headlines = evidence.search(db, listing["id"], fixture=is_fixture(db), origin="issuer_news", limit=40)
        if headlines:
            recent = max(headlines, key=lambda x: json.loads(x["locator"])["published_at"])
            _claim(body, f"The issuer’s dated announcement is titled “{recent['text']}”.", recent)
        if not observations:
            body["gaps"].append("No verified financial observation is saved for this listing.")
        if latest:
            leading = next(iter(latest.values()))
            _trend(db, listing, leading, body)
            _qualifications(db, body, now())
        _exposures(db, listing, now(), body)
        body["agenda"] = [
            {
                "rank": 1,
                "question": "What drove the reported change?",
                "reason": "A headline total combines price, volume and mix.",
                "next": "Read segment or volume detail in the next filing.",
            },
            {
                "rank": 2,
                "question": "How durable is the change?",
                "reason": "Shipment timing and one-off items can change quarterly totals.",
                "next": "Compare the next comparable period and the issuer’s guidance.",
            },
            {
                "rank": 3,
                "question": "Which counterparties transmit material risk?",
                "reason": "A shared industry alone does not demonstrate exposure.",
                "next": "Check dated customer, supplier and geographic disclosures.",
            },
        ]
        if latest:
            f = leading["financial"]
            body["agenda"][0].update(
                question=f"What drove {listing['ticker']}’s {f['metric'].replace('_', ' ')} in {f['period_label']}?",
                reason=f"The issuer reported {f['value']} {f['unit']}; segment or volume detail can distinguish operating drivers.",
                passage_ids=[leading["id"]],
            )
        if headlines:
            body["agenda"][1].update(
                question=f"What changes the financial interpretation of “{recent['text']}”?",
                reason="An announcement alone does not quantify customer uptake or margin effects.",
                next="Read the next operating update for quantified adoption, volume or margin changes.",
                passage_ids=[recent["id"]],
            )
        body["next_observations"] = [q["next"] for q in body["agenda"]]
        body["alternatives"].append(
            "Prices, unit volume, currency or timing may move reported sales in different directions."
        )
        body["gaps"].append(
            "A full segment, customer and geographic breakdown needs additional dated disclosures."
        )
        summary = (
            body["claims"][0]["text"]
            if body["claims"]
            else f"The saved dossier for {listing['ticker']} lacks a reported financial observation."
        )
        return _save(db, seq, listing, "dossier.v1", f"{listing['ticker']} company dossier", summary, body)


def peer(db, instrument_id, current_id, peer_id, baseline_id):
    with write(db) as seq:
        listing = universe.instrument(db, instrument_id)
        peer_listing = universe.instrument(db, peer_id)
        current = _get(db, listing, current_id)
        baseline = _get(db, peer_listing, baseline_id)
        if not evidence.supports_actual(
            current["financial"] or {}, listing["cik"]
        ) or not evidence.supports_actual(baseline["financial"] or {}, peer_listing["cik"]):
            raise ValueError("Choose an actual observation for each verified issuer.")
        result = evidence.compare(current, baseline, "peer_comparison")
        body = _body()
        body["calculations"].append(result)
        summary = (
            f"{listing['ticker']} reported {_fiscal_value(current)}; {peer_listing['ticker']} reported "
            f"{_fiscal_value(baseline)}. Difference: {result['difference']} {result['unit']}."
        )
        _claim(body, summary, current, baseline)
        body["alternatives"].append(
            "Scale, segment mix and fiscal seasonality can produce differences between companies."
        )
        body["next_observations"].append(
            "Check segment and per-unit disclosures before interpreting the difference as relative operating performance."
        )
        return _save(db, seq, listing, "peer_comparison.v1", "Peer financial comparison", summary, body)


def valuation(db, instrument_id, ref, low, high, growth):
    with write(db) as seq:
        listing = universe.instrument(db, instrument_id)
        p = _get(db, listing, ref)
        f = p.get("financial") or {}
        if not evidence.supports_actual(f, listing["cik"]) or f["metric"] not in (
            "revenue",
            "earnings_per_share",
        ):
            raise ValueError("Choose verified revenue or earnings per share.")
        base = evidence._number(f["value"])
        lo, hi, g = (evidence._number(x) for x in (low, high, growth))
        if not (0 < lo <= hi <= 1000 and -100 < g <= 1000 and base > 0):
            raise ValueError(
                "Use positive ordered multiples up to 1000, a positive base, and growth above -100% up to 1000%."
            )
        periods = {"standalone_quarter": 4, "annual": 1}
        if f["duration"] not in periods:
            raise ValueError("Use a standalone quarter or annual base.")
        start, end = evidence._period(f)
        days = (end - start).days + 1
        if (f["duration"] == "annual" and not 350 <= days <= 380) or (
            f["duration"] == "standalone_quarter" and not 80 <= days <= 100
        ):
            raise ValueError("The reported period dates do not match the valuation basis.")
        with localcontext() as ctx:
            ctx.prec = 100
            projected = base * periods[f["duration"]] * (1 + g / 100)
            multiples = (lo, (lo + hi) / 2, hi)
            values = [
                {"multiple": str(m), "conditional_value": format(projected * m, "f")} for m in multiples
            ]
        label = "enterprise value" if f["metric"] == "revenue" else "price per share"
        body = _body()
        body["calculations"].append(
            {
                "kind": "multiple_sensitivity",
                "input_ids": [ref],
                "version_ids": [p["document_id"]],
                "metric": f["metric"],
                "observed": str(base),
                "source_period": [f["period_start"], f["period_end"]],
                "periods_per_year": periods[f["duration"]],
                "growth_percent": str(g),
                "forecast_horizon": "one annualized year",
                "projected_annual_base": str(projected),
                "unit": f["unit"],
                "output": label,
                "formula": "observed × periods per year × (1 + assumed growth / 100) × assumed multiple",
                "scenarios": values,
            }
        )
        summary = f"At the chosen growth of {g}% and multiples of {lo}–{hi}×, conditional {label} ranges from {values[0]['conditional_value']} to {values[-1]['conditional_value']} {f['unit']}."
        _claim(body, summary, p)
        body["alternatives"].append(
            "Seasonality and a different multiple can change the range. The multiples and growth are operator assumptions."
        )
        body["next_observations"].append(
            "Check the next reported period, annual base and comparable companies before revisiting the assumptions."
        )
        return _save(
            db,
            seq,
            listing,
            "valuation_sensitivity.v1",
            f"{listing['ticker']} valuation sensitivity",
            summary,
            body,
        )


def _unique_value(rows):
    def signature(p):
        f = p["financial"]
        return tuple(
            f[k]
            for k in (
                "value",
                "unit",
                "basis",
                "currency",
                "duration",
                "share_basis",
                "period_start",
                "period_end",
            )
        )

    if not rows:
        return None, "No eligible observation for the declared period and metric."
    if len({signature(p) for p in rows}) != 1:
        return None, "Conflicting values or financial bases for the declared period."
    return rows[0], ""


def _eligible_close(exchange, day, closing, delay, available):
    if datetime.fromisoformat(closing) + timedelta(seconds=delay) > datetime.fromisoformat(available):
        return False
    if exchange not in ("NASDAQ", "NYSE"):
        return True
    from . import goal_schedule

    session = date.fromisoformat(day)
    local = datetime.fromisoformat(closing).astimezone(goal_schedule.zone("America/New_York"))
    if local.date() != session or session.weekday() >= 5:
        return False
    if session.year in goal_schedule.CLOSED:
        slot = goal_schedule.occurrence(
            session,
            {"clock": "16:00", "cadence": "closing", "timezone": "America/New_York", "intent": "start_at"},
        )
        return bool(slot and closing == slot[1])
    # Historical sessions outside the bundled calendar rely on the attributed
    # file for holiday and early-close status. Still reject intraday quotations.
    return local.hour in (13, 16) and local.minute == local.second == local.microsecond == 0


def import_prices(db, instrument_id, publisher, series, text):
    if (
        not isinstance(publisher, str)
        or not re.fullmatch(r"[\w .&-]{2,80}", publisher)
        or not isinstance(series, str)
        or not re.fullmatch(r"[\w .:-]{1,80}", series)
    ):
        raise ValueError("Name the market data publisher and series.")
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 40_000:
        raise ValueError("Use a market-only CSV of at most 40 KB.")
    listing = universe.instrument(db, instrument_id)
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if reader.fieldnames != list(PRICE_FIELDS):
        raise ValueError("Use only the displayed market-close columns in the specified order.")
    captured = now()
    by_day = {}
    try:
        for row in reader:
            if len(by_day) >= 100 or None in row or any(v is None for v in row.values()):
                raise ValueError("Use up to 100 complete market observations.")
            day = _date(row["session_date"])
            close = instant(row["session_end"])
            if row["session_end"][:10] != day or close > captured:
                raise ValueError("The quoted session date and its observed closing timestamp must agree.")
            if (row["ticker"], row["exchange"], row["currency"]) != (
                listing["ticker"],
                listing["listing_exchange"],
                listing["currency"],
            ):
                raise ValueError(
                    "Quote ticker, listing exchange and currency must match the selected listing."
                )
            if not re.fullmatch(r"[0-9]{1,7}", row["delay_seconds"]):
                raise ValueError("Specify the stated quote delay in seconds.")
            if not _eligible_close(row["exchange"], day, close, int(row["delay_seconds"]), captured):
                raise ValueError("Supply an eligible regular-session close available after its stated delay.")
            adjustment = row["adjustment"]
            if adjustment not in ("unadjusted", "split_adjusted", "total_return_adjusted"):
                raise ValueError("Choose a recognized adjustment basis.")
            vintage = instant(row["adjustment_as_of"]) if row["adjustment_as_of"] else ""
            if (adjustment == "unadjusted" and vintage) or (
                adjustment != "unadjusted" and not close <= vintage <= captured
            ):
                raise ValueError("Adjusted quotes require their explicit adjustment vintage.")
            value = evidence._number(row["official_close"])
            if value <= 0 or day in by_day:
                raise ValueError("Each session needs one positive close.")
            by_day[day] = {
                "metric": "close_price",
                "role": "actual",
                "observation_type": "official_close",
                "session": "regular",
                "instrument_id": instrument_id,
                "exchange": row["exchange"],
                "currency": row["currency"],
                "unit": row["currency"] + " per share",
                "value": str(value),
                "session_date": day,
                "session_end": row["session_end"],
                "adjustment": adjustment,
                "adjustment_as_of": vintage,
                "delay_seconds": int(row["delay_seconds"]),
                "publisher": publisher,
                "series_id": series,
                "provenance": "Operator-provided market data",
            }
    except csv.Error:
        raise ValueError("The supplied market CSV is malformed.") from None
    if not by_day:
        raise ValueError("The market file contains no observations.")
    staged = evidence._stage(db, "selected_price_fields_and_file_hash", text.encode())
    with write(db) as seq:
        universe.instrument(db, instrument_id)
        ids = []
        for day, f in by_day.items():
            stream = "local:market-close/" + _digest([instrument_id, publisher, series, day])
            line = (
                f"{listing['ticker']} regular close on {day}: {f['value']} {f['unit']} ({f['adjustment']})."
            )
            doc = evidence._save(
                db,
                seq,
                instrument_id,
                "operator_market_file",
                stream,
                f"{publisher} · {series} · operator-supplied closing price",
                staged,
                [("market-close/" + day, line, captured, f)],
                captured,
                published=None,
                precision="operator-supplied session time",
                retention="selected_price_fields_and_file_hash",
                fixture=is_fixture(db),
            )
            ids.append(
                db.execute("SELECT id FROM evidence_passages WHERE document_id=?", (doc,)).fetchone()[0]
            )
        return ids


def _close(db, listing, day, cutoff=None):
    """Read a typed end-of-session observation. A headline or undated last price cannot fill a window."""
    rows = db.execute(
        """SELECT p.id FROM evidence_passages p JOIN documents d ON p.document_id=d.id
        WHERE d.instrument_id=? AND d.fixture=? AND json_extract(p.financial,'$.metric')='close_price'
        AND json_extract(p.financial,'$.session_date')=? AND (? IS NULL OR p.available_at<=?)
        ORDER BY d.commit_seq DESC,p.id LIMIT 201""",
        (listing["id"], int(is_fixture(db)), day, cutoff, cutoff),
    ).fetchall()
    if len(rows) > 200:
        return None, "Too many possible price editions to select an unambiguous close."
    choices = {}
    for row in rows:
        p = _get(db, listing, row["id"], cutoff, current=False)
        f = p["financial"]
        if not evidence.still_supported(db, p, cutoff):
            continue
        try:
            close = instant(f["session_end"])
            value = evidence._number(f["value"])
            delay = f["delay_seconds"]
            adjusted = f["adjustment"]
            if (
                value <= 0
                or f["instrument_id"] != listing["id"]
                or f["role"] != "actual"
                or f["session"] != "regular"
                or f["observation_type"] != "official_close"
                or not f["series_id"]
                or f["exchange"] != listing["listing_exchange"]
                or f["currency"] != listing["currency"]
                or f["unit"] != f["currency"] + " per share"
                or type(delay) is not int
                or delay < 0
                or f["session_end"][:10] != day
                or not _eligible_close(f["exchange"], day, close, delay, p["available_at"])
                or adjusted not in ("unadjusted", "split_adjusted", "total_return_adjusted")
            ):
                continue
            vintage = instant(f["adjustment_as_of"]) if adjusted != "unadjusted" else ""
            if vintage and (vintage < close or vintage > p["available_at"]):
                continue
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
        signature = (value, close, p["origin"], f.get("publisher"), f["series_id"], adjusted, vintage)
        choices.setdefault(signature, p)
    if len(choices) != 1:
        return None, (
            "Conflicting series, adjustments or prices for the requested session."
            if choices
            else "No verified official close with listing, session, adjustment, currency and delay metadata."
        )
    return next(iter(choices.values())), ""


def _price_change(later, earlier):
    a, b = later["financial"], earlier["financial"]
    fields = ("instrument_id", "series_id", "currency", "unit", "adjustment", "session", "exchange")
    if (
        later["origin"] != earlier["origin"]
        or a.get("publisher") != b.get("publisher")
        or any(a[k] != b[k] for k in fields)
        or a["session_date"] <= b["session_date"]
        or (a["adjustment"] != "unadjusted" and a["adjustment_as_of"] != b["adjustment_as_of"])
    ):
        raise ValueError("The price endpoints need one series, currency, session and adjustment vintage.")
    with localcontext() as ctx:
        ctx.prec = 85
        start, end = evidence._number(b["value"]), evidence._number(a["value"])
        delta = end - start
        pct = (
            None
            if start <= Decimal("0.000001")
            else format((100 * delta / start).quantize(Decimal("0.0001")).normalize(), "f")
        )
    return {
        "kind": "close_price_change",
        "method": "price_window.v1",
        "metric": "close_price",
        "unit": a["unit"],
        "basis": a["adjustment"],
        "current_value": str(end),
        "baseline_value": str(start),
        "difference": str(delta),
        "percent_change": pct,
        "session_window": [b["session_date"], a["session_date"]],
        "baseline_period": b["session_date"],
        "current_period": a["session_date"],
        "formula": "(later close - earlier close) / earlier close × 100",
        "input_ids": [later["id"], earlier["id"]],
        "version_ids": [later["document_id"], earlier["document_id"]],
        "warnings": [] if pct is not None else ["Near-zero starting price."],
    }


def price_context(db, instrument_id, question, cutoff=None):
    """Read an explicitly dated, single-listing close window without dispatching or saving work."""
    if not isinstance(question, str) or not re.search(
        r"\b(price|prices|close|closing|closed|return|returns|stock|shares)\b", question, re.IGNORECASE
    ):
        return None
    dates = re.findall(r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])", question)
    if len(dates) != 2:
        return None
    try:
        start, end = (_date(s) for s in dates)
        if start >= end:
            return None
    except ValueError:
        return None
    cutoff = instant(cutoff) if cutoff else None
    standalone = not db.in_transaction
    if standalone:
        db.execute("BEGIN")
    try:
        listing = universe.instrument(db, instrument_id)
        symbol = listing["ticker"]
        output = {
            "status": "partial",
            "instrument_id": instrument_id,
            "ticker": symbol,
            "start": start,
            "end": end,
            "cutoff": cutoff,
            "passages": [],
            "evidence_ids": [],
            "calculation": None,
            "gaps": [],
            "warnings": [],
        }
        currencies = re.findall(r"\b(?:USD|EUR|GBP|CAD|AUD|CHF|JPY|CNY|HKD)\b", question, re.IGNORECASE)
        if any(c.upper() != listing["currency"] for c in currencies) or any(
            s in question for s in ("€", "£", "¥")
        ):
            output["gaps"].append(
                "No currency-converted regular close is available for the requested window."
            )
            return output
        for other in db.execute(
            """SELECT i.ticker,c.name FROM instruments i LEFT JOIN companies c ON c.id=i.company_id
                WHERE i.id<>? AND (i.company_id IS NULL OR i.company_id IS NOT ?) AND EXISTS
                (SELECT 1 FROM source_memberships sm WHERE sm.instrument_id=i.id AND sm.status='active')""",
            (instrument_id, listing["company_id"]),
        ):
            aliases = [
                other["ticker"],
                re.sub(r"\s+(corporation|corp\.?|inc\.?)$", "", other["name"] or "", flags=re.IGNORECASE),
            ]
            if any(x and re.search(r"\b" + re.escape(x) + r"\b", question, re.IGNORECASE) for x in aliases):
                output["gaps"].append(
                    "The question names another listing. Use the explicit benchmark selector to align both series."
                )
                return output
        if re.search(
            r"\b(intraday|premarket|after.hours|benchmark|relative to|versus|vs\.?|caused|why)\b",
            question,
            re.IGNORECASE,
        ):
            output["gaps"].append(
                "The local price context covers one listing’s regular closes. The requested additional comparison, session or cause is unverified."
            )
        for day in dates:
            p, reason = _close(db, listing, day, cutoff)
            if not p:
                output["gaps"].append(f"{symbol}, {day}: {reason}")
                continue
            output["passages"].append(p)
            output["evidence_ids"].append(p["id"])
        if any(p["origin"] == "operator_market_file" for p in output["passages"]):
            output["warnings"].append(
                "Prices and delay metadata are from the operator-supplied market file. Independent publisher verification is unavailable."
            )
        if len(output["passages"]) == 2:
            a, b = output["passages"]
            try:
                change = _price_change(b, a)
            except ValueError as exc:
                output["gaps"].append(str(exc))
            else:
                query = re.sub("[-_]", " ", question.casefold())
                bases = set(
                    re.findall(
                        r"\b(?:split adjusted|total return(?: adjusted)?|unadjusted|adjusted)\b", query
                    )
                )
                basis = change["basis"].replace("_", " ")
                if any(
                    b == "adjusted"
                    and basis == "unadjusted"
                    or b != "adjusted"
                    and (b if b != "total return" else "total return adjusted") != basis
                    for b in bases
                ):
                    output["gaps"].append(
                        "The retained adjustment basis differs from the requested price window."
                    )
                    return output
                output["calculation"] = change
                if not output["gaps"]:
                    output["status"] = "ok"
        return output
    finally:
        if standalone:
            db.rollback()


def price_window(db, instrument_id, start, end, benchmark_id=None):
    if _date(start) >= _date(end) or benchmark_id == instrument_id:
        raise ValueError("Choose ordered session dates and a distinct benchmark listing.")
    with write(db) as seq:
        listing = universe.instrument(db, instrument_id)
        body = _body()
        names = [listing] + ([universe.instrument(db, benchmark_id)] if benchmark_id else [])
        subject_result = None
        for item in names:
            left, lreason = _close(db, item, start)
            right, rreason = _close(db, item, end)
            for day, p, reason in ((start, left, lreason), (end, right, rreason)):
                if p:
                    _claim(
                        body,
                        f"{item['ticker']} {day} official close: {p['financial']['value']} {p['financial']['unit']}.",
                        p,
                    )
                else:
                    body["gaps"].append(f"{item['ticker']} {day}: {reason}")
            if left and right:
                try:
                    change = _price_change(right, left)
                    body["calculations"].append(change)
                    if item["id"] == instrument_id:
                        subject_result = change
                except ValueError as exc:
                    body["gaps"].append(str(exc))
        body["window"] = {"start": start, "end": end, "benchmark_id": benchmark_id}
        if any(c["origin"] == "operator_market_file" for c in body["citations"]):
            body["gaps"].append(
                "The closing prices and session metadata came from the operator’s market file. The desk has no independent publisher or entitlement check for this series."
            )
        results = body["calculations"]
        if len(results) == 2:
            a, b = results
            if a["basis"] == b["basis"] and all(r["percent_change"] is not None for r in results):
                body["window"]["benchmark_spread_percentage_points"] = str(
                    Decimal(a["percent_change"]) - Decimal(b["percent_change"])
                )
            else:
                body["gaps"].append(
                    "Benchmark-relative change requires matching adjustment bases and usable denominators."
                )
        summary = (
            f"{listing['ticker']} changed by {subject_result['difference']} {subject_result['unit']} from {start} to {end}."
            if subject_result
            else f"The {listing['ticker']} market move from {start} to {end} remains unverified."
        )
        body["alternatives"].append(
            "A same-window price move can reflect broad market conditions or unrelated company developments."
        )
        body["next_observations"].append(
            "Check the comparable benchmark and the timing of the primary announcement before interpreting a market response."
        )
        return _save(db, seq, listing, "price_window.v1", "Market-session price window", summary, body)


def freeze_cohort(db, owner_id, metric, baseline_end, decision_at, outcome_end):
    """Enroll the entire active list on one rule before reading any outcome rows."""
    baseline_end, outcome_end = _date(baseline_end), _date(outcome_end)
    cutoff = instant(decision_at)
    if metric not in METRICS or cutoff > now() or not baseline_end <= cutoff[:10] < outcome_end:
        raise ValueError("Declare a known decision time between the baseline and later outcome period end.")
    if metric == "close_price" and cutoff[:10] != baseline_end:
        raise ValueError("Use the decision time on the baseline close date for a prospective price window.")
    with write(db) as seq:
        universe.instrument(db, owner_id)
        roster = universe.universe(db)["instruments"]
        if len(roster) > 500:
            raise ValueError("This local method supports watchlists up to 500 listings.")
        members = []
        for i in roster:
            if metric == "close_price":
                base, reason = _close(db, i, baseline_end, cutoff)
                options = [base] if base else []
            else:
                options = _numbers(db, i, metric=metric, end=baseline_end, cutoff=cutoff, limit=201)
                base, reason = _unique_value(options)
            if len(options) > 200:
                base, reason = None, "Ambiguous source coverage exceeds the local method bound."
            members.append(
                {
                    "instrument_id": i["id"],
                    "ticker": i["ticker"] or i["raw_label"],
                    "baseline_id": base["id"] if base else None,
                    "exclusion": reason,
                    "candidate_ids": [p["id"] for p in options],
                }
            )
        rule = {
            "metric": metric,
            "baseline_end": baseline_end,
            "decision_at": cutoff,
            "outcome_end": outcome_end,
            "universe": "Entire active watchlist captured at enrollment. Historical membership is unverified.",
            "selection": "One unambiguous reported financial basis available at the decision cutoff.",
            "window": "From the declared baseline period end to the specified later fiscal period end.",
            "estimator": "Equal-weight median within common monetary/financial semantics; fractional change uses absolute baseline.",
            "benchmark": "Within-listing prior reported period; no market-price benchmark or return."
            if metric != "close_price"
            else "Within-listing starting close. Compare only consistent sessions, adjustments and series.",
        }
        ident = uid("cohort")
        db.execute(
            "INSERT INTO method_cohorts VALUES(?,?,?,?,?,?)",
            (ident, owner_id, _encode(rule), _encode(members), now(), seq),
        )
        return ident


def evaluate_cohort(db, cohort_id):
    with write(db) as seq:
        c = db.execute("SELECT * FROM method_cohorts WHERE id=?", (cohort_id,)).fetchone()
        if not c:
            raise ValueError("Unknown declared cohort.")
        listing = universe.instrument(db, c["owner_id"], active=False)
        rule = json.loads(c["rule"])
        body = _body()
        body["cohort"] = {"id": c["id"], "frozen_at": c["frozen_at"], "rule": rule, "members": []}
        normalized = {}
        for member in json.loads(c["members"]):
            row = {**member, "outcome_id": None, "status": "excluded" if member["exclusion"] else "missing"}
            body["cohort"]["members"].append(row)
            if member["exclusion"]:
                continue
            i = universe.instrument(db, member["instrument_id"], active=False)
            baseline = _get(db, i, member["baseline_id"], current=False)
            is_price = rule["metric"] == "close_price"
            base_label = (
                f"{baseline['financial']['value']} {baseline['financial']['unit']}"
                if is_price
                else _fiscal_value(baseline)
            )
            _claim(body, f"{member['ticker']} baseline: {base_label}.", baseline)
            if is_price:
                outcome, reason = _close(db, i, rule["outcome_end"])
                options = [outcome] if outcome else []
            else:
                options = _numbers(db, i, metric=rule["metric"], end=rule["outcome_end"], limit=201)
                outcome, reason = _unique_value(options)
            if len(options) > 200:
                outcome, reason = None, "Ambiguous source coverage exceeds the local method bound."
            if not outcome:
                row["reason"] = reason
                row["candidate_ids_at_outcome"] = [p["id"] for p in options]
                continue
            if not is_price and outcome["financial"]["period_start"] <= rule["decision_at"][:10]:
                row.update(
                    status="excluded", reason="Outcome period began before or on the declared decision day."
                )
                continue
            try:
                result = (
                    _price_change(outcome, baseline)
                    if is_price
                    else evidence.compare(outcome, baseline, "period_trend")
                )
            except ValueError as exc:
                row.update(status="excluded", reason=str(exc))
                continue
            body["calculations"].append(result)
            row.update(
                status="observed",
                outcome_id=outcome["id"],
                percent_change=result["percent_change"],
                difference=result["difference"],
                warnings=result["warnings"],
            )
            outcome_label = (
                f"{outcome['financial']['value']} {outcome['financial']['unit']}"
                if is_price
                else _fiscal_value(outcome)
            )
            _claim(body, f"{member['ticker']} outcome: {outcome_label}.", outcome)
            if result["percent_change"] is not None:
                f = outcome["financial"]
                fields = (
                    ("metric", "adjustment", "session", "currency")
                    if is_price
                    else ("metric", "basis", "duration", "share_basis")
                )
                basis = " | ".join(f[k] for k in fields)
                normalized.setdefault(basis, []).append(Decimal(result["percent_change"]))
        members = body["cohort"]["members"]
        observed = sum(r["status"] == "observed" for r in members)
        missing = sum(r["status"] == "missing" for r in members)
        groups = {
            key: {
                "n": len(v),
                "median_percent": str(median(v)),
                "minimum_percent": str(min(v)),
                "maximum_percent": str(max(v)),
                "negative": sum(x < 0 for x in v),
                "flat": sum(x == 0 for x in v),
                "positive": sum(x > 0 for x in v),
            }
            for key, v in normalized.items()
        }
        body["cohort"]["groups"] = groups
        if any(c["origin"] == "operator_market_file" for c in body["citations"]):
            body["gaps"].append(
                "Market-session observations came from operator-supplied files. The desk has no independent publisher or entitlement verification for these closes."
            )
        if missing:
            body["gaps"].append(f"{missing} enrolled listings have no usable outcome observation.")
        if not observed:
            body["gaps"].append("No compatible outcomes are available for this cohort.")
        summary = f"{observed} observed, {missing} missing and {len(members) - observed - missing} excluded across {len(members)} declared listings."
        body["alternatives"].append(
            "Sector mix, reporting conventions, small samples and a present-day watchlist limit historical inference."
        )
        body["next_observations"].append(
            "Obtain the missing releases and rerun the frozen selection; a new definition needs a separate cohort."
        )
        return _save(
            db,
            seq,
            listing,
            "historical_cohort.v1",
            "Historical financial cohort",
            summary,
            body,
            scope=cohort_id,
        )


def dashboard(db, instrument_id=None):
    roster = universe.universe(db)["instruments"]
    listing = universe.instrument(db, instrument_id) if instrument_id else (roster[0] if roster else None)
    view = {
        "listings": roster,
        "listing": listing,
        "financials": [],
        "events": [],
        "reports": [],
        "cohorts": [],
        "metrics": METRICS,
        "peer_financials": [],
        "foci": FOCI,
        "price_fields": ",".join(PRICE_FIELDS),
    }
    if not listing:
        return view
    view["financials"] = _numbers(db, listing, limit=32)
    for role in EXPECTATIONS[:-1]:
        view["financials"].extend(_numbers(db, listing, role=role, limit=8))
    for peer_listing in roster:
        if peer_listing["company_id"] != listing["company_id"]:
            for p in _numbers(db, peer_listing, limit=8):
                view["peer_financials"].append({"label": peer_listing["ticker"], "passage": p})
        if len(view["peer_financials"]) >= 80:
            break
    view["events"] = [
        dict(r)
        for r in db.execute(
            """SELECT e.*,p.text AS excerpt FROM event_versions e
       JOIN evidence_passages p ON p.id=e.source_ref WHERE e.instrument_id=? AND NOT EXISTS
       (SELECT 1 FROM event_versions n WHERE n.event_id=e.event_id AND n.commit_seq>e.commit_seq)
       ORDER BY e.commit_seq DESC LIMIT 100""",
            (listing["id"],),
        )
    ]
    view["reports"] = [
        export(db, r["id"])
        for r in db.execute(
            "SELECT id FROM method_reports WHERE instrument_id=? ORDER BY commit_seq DESC LIMIT 20",
            (listing["id"],),
        )
    ]
    view["cohorts"] = [
        {**dict(c), "rule": json.loads(c["rule"])}
        for c in db.execute(
            "SELECT id,rule,frozen_at FROM method_cohorts WHERE owner_id=? ORDER BY commit_seq DESC LIMIT 40",
            (listing["id"],),
        )
    ]
    return view


def action(db, action, data):
    def field(key):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise ValueError("Complete all required method inputs.")
        return value.strip()

    instrument_id = field("instrument_id")
    universe.instrument(db, instrument_id)
    if action in ("method-event", "method-freeze"):
        version = field("event_version_id")
        if _event(db, version)["instrument_id"] != instrument_id:
            raise ValueError("Choose an event for this listing.")
    if action == "method-event":
        result = event_report(db, version, focus=data.get("focus") or None)
    elif action == "method-dossier":
        result = dossier(db, instrument_id)
    elif action == "method-freeze":
        freeze_expectation(
            db,
            version,
            field("passage_id"),
            value=data.get("value"),
            start=data.get("start"),
            end=data.get("end"),
        )
        result = event_report(db, version, focus="expectations")
    elif action == "method-valuation":
        result = valuation(
            db, instrument_id, field("passage_id"), field("low"), field("high"), field("growth")
        )
    elif action == "method-price":
        result = price_window(
            db, instrument_id, field("start"), field("end"), data.get("benchmark_id") or None
        )
    elif action == "method-price-import":
        import_prices(db, instrument_id, field("publisher"), field("series"), data.get("rows"))
        return f"/methods?instrument_id={instrument_id}#prices"
    elif action == "method-peer":
        peer_id, sep, baseline = field("peer_ref").partition("/")
        if not sep:
            raise ValueError("Choose a peer observation.")
        result = peer(db, instrument_id, field("passage_id"), peer_id, baseline)
    elif action == "method-cohort-declare":
        freeze_cohort(
            db,
            instrument_id,
            field("metric"),
            field("baseline_end"),
            field("decision_at"),
            field("outcome_end"),
        )
        return f"/methods?instrument_id={instrument_id}#cohort"
    elif action == "method-cohort-run":
        c = db.execute("SELECT owner_id FROM method_cohorts WHERE id=?", (field("cohort_id"),)).fetchone()
        if not c or c[0] != instrument_id:
            raise ValueError("Choose a cohort declared from this listing.")
        result = evaluate_cohort(db, field("cohort_id"))
    else:
        raise ValueError("Unknown research method.")
    return f"/methods?instrument_id={instrument_id}#{result['id']}"
