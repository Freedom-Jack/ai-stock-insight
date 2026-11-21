"""Build an assessment from retrieved observations and recorded calculations.

The investigator selects source and receipt IDs. The service describes their
meaning and verifies the same selection again inside the submission transaction.
"""

import json
import re
from dataclasses import dataclass
from datetime import date

from . import evidence
from .db import is_fixture

_METRICS = {
    "revenue_per_share": r"(?:revenue|sales) per share",
    "dividend_yield": r"dividend yield",
    "shares_outstanding": r"(?:weighted average )?shares outstanding",
    "share_repurchases": r"share repurchases|stock repurchases|buybacks",
    "revenue": r"revenue[s]?|sales",
    "dividend_per_share": r"dividends?|dividend per share|payout per share",
    "operating_margin": r"operating margins?",
    "gross_margin": r"gross margins?",
    "net_income": r"net income|net profit",
    "earnings_per_share": r"earnings per share|eps",
    "free_cash_flow": r"free cash flow",
}
_QUARTERS = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_FY = r"\b(?:fy\s*|fiscal (?:year )?)(20\d\d|\d\d)\b"
_QUARTER = r"\bq([1-4])\b|\b(first|second|third|fourth)[ -]quarter\b"


@dataclass(frozen=True)
class Objective:
    metrics: tuple
    periods: tuple
    trend: str
    checks: tuple
    basis: str
    currency: str
    unit_scale: str
    duration: str
    share_basis: str


def objective(question):
    q = question.casefold()
    remaining = q.replace("per-share", "per share")
    metrics = []
    for metric, pattern in _METRICS.items():
        remaining, count = re.subn(r"\b(?:" + pattern + r")\b", " ", remaining)
        if count:
            metrics.append(metric)
    decision = re.search(r"\b(?:buy|buying|sell|selling|purchase|invest in)\b", q)
    moves = r"(?:fell|fallen|falling|rallied|rally|rose|rise|move[d]?|tanked|tanks|sold off|decline[d]?|drop[p]?ed|gained|lost)"
    price = decision or re.search(r"\b(?:share price|stock price|price[s]?|market reaction)\b", q)
    if re.search(r"\b(?:shares|stock)\b[^.!?]{0,28}\b" + moves + r"\b", q):
        price = True
    if not metrics and re.search(r"\b(?:nvda|nvidia|msft|microsoft)\s+(?:has\s+)?" + moves + r"\b", q):
        price = True
    consensus = decision or re.search(r"\b(?:consensus|surprise|expectations?|street estimates?)\b", q)
    checks = tuple(
        name for name, needed in (("historical_consensus", consensus), ("price_context", price)) if needed
    )
    fy = list(re.finditer(_FY, q))
    quarters = list(re.finditer(_QUARTER, q))
    periods = []
    for quarter in quarters:
        num = quarter.group(1) or _QUARTERS[quarter.group(2)]
        # Pair the adjacent quarter/year in either source order. A shared
        # fiscal year may qualify more than one quarter.
        year = min(
            fy,
            key=lambda y: min(abs(y.start() - quarter.end()), abs(y.end() - quarter.start())),
            default=None,
        )
        periods.append("Q" + num + (" FY" + year.group(1)[-2:] if year else ""))
    if not quarters:
        periods.extend("FY" + y.group(1)[-2:] for y in fy)
    ranges = re.findall(r"\b(\d{4}-\d\d-\d\d)\s+(?:to|through|and)\s+(\d{4}-\d\d-\d\d)\b", q)
    periods.extend(start + " to " + end for start, end in ranges)
    trend = ""
    if re.search(r"\byoy\b|year[ -]over[ -]year|year[ -]on[ -]year|same quarter (?:last|prior) year", q):
        trend = "year_over_year"
    elif re.search(r"\bqoq\b|quarter[ -]over[ -]quarter|sequential|prior quarter|previous quarter", q):
        trend = "sequential"
    elif re.search(r"\b(?:compare|comparison|trend|growth|grew|increase[d]?|decline[d]?|change[d]?)\b", q):
        trend = "period_trend"
    basis = "non-GAAP" if re.search(r"adjusted|non[ -]?gaap", q) else "US GAAP" if "gaap" in q else ""
    currency_names = {
        "USD": r"usd|us dollars?",
        "EUR": r"eur|euros?",
        "GBP": r"gbp|pounds?",
        "JPY": r"jpy|yen",
        "CAD": r"cad|canadian dollars?",
        "CNY": r"cny|yuan",
    }
    currencies = [code for code, names in currency_names.items() if re.search(r"\b(?:" + names + r")\b", q)]
    scale = re.search(r"\b(thousand|million|billion|trillion)s?\b", q)
    horizon = q.replace("full-year demand", "").replace("full year demand", "")
    duration = ""
    if re.search(r"annual|full[ -]year", horizon):
        duration = "annual"
    elif re.search(r"\bytd\b|year[ -]to[ -]date", horizon):
        duration = "year_to_date"
    elif quarters or re.search(r"\bquarter\w*\b", horizon):
        duration = "standalone_quarter"
    return Objective(
        tuple(metrics),
        tuple(dict.fromkeys(periods)),
        trend,
        checks,
        basis,
        ",".join(currencies),
        scale.group(1) if scale else "",
        duration,
        "diluted" if re.search(r"\bdiluted\b", q) else "basic" if re.search(r"\bbasic\b", q) else "",
    )


def required_checks(question):
    return list(objective(question).checks)


# This local teaching packet contains only these two quarters and the issuer's
# shipment qualification. Admit questions written in its supported vocabulary.
_FIXTURE_WORDS = set(
    """
    a about actually after an and are as at available before between by can change changed changes
    compare compared comparing comparison conclusion could decision decline declined demand did difference
    disclosure do does drop dropped earnings establish established evidence expectations fall fallen fell filing
    first for from full fy25 fy2025 gaap go greater grew grow growing growth guarantee guarantees has have
    headline how i in increase increased into is it its last limit limits management me mean million more move
    moved much nvidia nvda of on or outlook percentage price prior purchase q1 q2 quarter quarterly quarters
    rally rallied release report reported reports result results revenue revenues said sales says second sell
    selling sequential share shares shipment shipments should show shown stock stronger support supported
    tell than that the their these this timing to two usd us using value was were what whether which why with
    year yield buy buying financial saved dollar dollars point points as of we our outlook interpret interpretation
""".split()
)


def fixture_supported(question):
    intent = objective(question)
    words = set(re.findall(r"[a-z]+[0-9]*|[0-9]+", question.casefold()))
    return bool(
        words <= _FIXTURE_WORDS
        and (intent.metrics or intent.checks or "results" in words)
        and set(intent.metrics) <= {"revenue"}
        and intent.trend != "year_over_year"
        and set(intent.periods) <= {"Q1 FY25", "Q2 FY25", "Q1", "Q2"}
        and intent.duration in ("", "standalone_quarter")
        and intent.basis in ("", "US GAAP")
        and intent.currency in ("", "USD")
        and intent.unit_scale in ("", "million")
    )


def period_matches(fact, period):
    if not period or period == "unspecified":
        return True
    label = fact["period_label"].upper()
    if re.fullmatch(r"Q[1-4]", period):
        return label.startswith(period + " ")
    return label == period.upper() or period == f"{fact['period_start']} to {fact['period_end']}"


def matches_dimensions(fact, intent):
    return (
        (not intent.basis or intent.basis == fact["basis"])
        and (not intent.duration or intent.duration == fact["duration"])
        and (not intent.currency or intent.currency == fact["currency"])
        and (not intent.unit_scale or intent.unit_scale in fact["unit"].casefold().split())
        and (not intent.share_basis or intent.share_basis == fact["share_basis"].casefold())
    )


def _fits_trend(facts, kind):
    if not kind or kind == "period_trend":
        return True
    if not all(f["duration"] == "standalone_quarter" for f in facts):
        return False
    days = (date.fromisoformat(facts[0]["period_end"]) - date.fromisoformat(facts[1]["period_end"])).days
    return 350 <= days <= 378 if kind == "year_over_year" else 80 <= days <= 100


def _scope_supported(question, listing):
    """Conservative positive vocabulary for the supported accounting method.

    An unrecognized business metric, issuer, or time qualifier leaves the
    question open. Each displayed value still comes from a typed observation.
    """
    q = question.casefold().replace("’", "'")
    for entity in (listing.get("ticker"), listing.get("company_name")):
        if entity:
            q = re.sub(r"\b" + re.escape(entity.casefold()) + r"(?:'s)?\b", " ", q)
            name = re.sub(r"\s+(?:corporation|corp\.?|inc\.?)$", "", entity.casefold())
            q = re.sub(r"\b" + re.escape(name) + r"(?:'s)?\b", " ", q)
    q = re.sub(r"\bfull[ -]year demand\b", "demand", q)
    q = re.sub(r"\b(?:year[ -](?:over|on)[ -]year|quarter[ -]over[ -]quarter)\b", "trend", q)
    q = re.sub(_FY, "", q)
    q = re.sub(_QUARTER, "", q)
    q = re.sub(r"\b\d{4}-\d\d-\d\d\s+(?:to|through|and)\s+\d{4}-\d\d-\d\d\b", "", q)
    for pattern in _METRICS.values():
        q = re.sub(r"\b(?:" + pattern + r")\b", " ", q)
    common = (_FIXTURE_WORDS - {"fy25", "fy2025", "nvidia", "nvda", "year", "full", "yield"}) | set(
        """amount according across calculate captured company current dated declare declared different difference
        basic diluted during each ended ending equity financials figures filed filings find figure had latest last most over
        payout per period periods prior provide recent record recorded retained sequentially standalone
        stood stored successive trend versus vs within yoy qoq total values workspace""".split()
    )
    return set(re.findall(r"[a-z]+[0-9]*|[0-9]+", q)) <= common


def _latest_saved(question):
    latest = bool(re.search(r"\b(?:latest|most recent|current)\b", question, re.IGNORECASE))
    saved = bool(re.search(r"\b(?:saved|retained|recorded|workspace|stored)\b", question, re.IGNORECASE))
    return latest, saved


def _ids(value):
    if not isinstance(value, list) or len(value) > 32 or any(not isinstance(i, str) for i in value):
        raise ValueError("Expected a bounded list of evidence or receipt IDs")
    if len(set(value)) != len(value):
        raise ValueError("Duplicate assessment reference")
    return value


def render(context, selection, calls):
    """Derive canonical human-readable fields, plus machine-readable support."""
    intent = objective(context["question"])
    listing = context["instrument"]
    passages, comparisons, gaps = {}, {}, {}
    final_gaps = None
    for name, output in calls:
        if "outstanding_gap_ids" in output:
            final_gaps = set(output["outstanding_gap_ids"])
        for item in output.get("outstanding_inputs", ()):
            gaps[item["gap_id"]] = (item["tool"], item)
        data = output["data"]
        if name == "get_evidence" and output["status"] == "ok":
            passages[data["id"]] = data
        if name == "compare_financials" and output["status"] == "ok":
            comparisons[output["receipt_id"]] = data
        if output.get("gap_id"):
            gaps[output["gap_id"]] = (name, data)
    gap_ids = _ids(selection["gaps"])
    outstanding = final_gaps if final_gaps is not None else set(gaps)
    if set(gap_ids) != outstanding:
        raise ValueError("Assessment must name the outstanding gaps")
    receipt_ids = _ids(selection["calculations"])
    if not set(receipt_ids) <= comparisons.keys():
        raise ValueError("Assessment calculation references must identify successful receipts")
    ids = _ids(selection["passage_ids"])
    if not set(ids) <= passages.keys():
        raise ValueError("Assessment refers to a passage that was not retrieved")
    if selection["status"] not in ("complete", "partial", "blocked"):
        raise ValueError("Invalid assessment status")
    if (selection["status"] == "complete") == bool(gap_ids):
        raise ValueError("Assessment status must reflect outstanding inputs")
    if not ids and selection["status"] != "blocked":
        raise ValueError("An answered assessment requires retained evidence")

    # Source quotes are always full passages. A bare numeric cell cannot
    # carry financial meaning on its own; keep its structured fields attached.
    facts, claims, assertions, summaries, changes = {}, [], [], [], []
    for pid in ids:
        passage = passages[pid]
        fact = passage.get("financial")
        if passage["instrument_id"] != listing["id"]:
            raise ValueError("Financial assertion refers to another instrument")
        claims.append({"type": "issuer_statement", "text": passage["text"], "evidence_refs": [pid]})
        source = {"passage_id": pid, "document_id": passage["document_id"], "instrument_id": listing["id"]}
        if fact:
            if not evidence.supports_actual(fact, listing.get("cik")):
                raise ValueError(
                    "Financial observation has an unsupported issuer, role, value, period or unit basis"
                )
            assertions.append({"kind": "observation", **source, **fact})
            facts[pid] = fact
        else:
            assertions.append({"kind": "source_statement", **source})
    fits = [fact for fact in facts.values() if matches_dimensions(fact, intent)]
    required = [(m, p) for m in intent.metrics for p in (intent.periods or ("unspecified",))]
    missing = [
        (m, p) for m, p in required if not any(f["metric"] == m and period_matches(f, p) for f in fits)
    ]
    declarations = {
        (g.get("metric"), g.get("period"))
        for gid, (name, g) in gaps.items()
        if gid in outstanding and name == "record_gap"
    }
    search_empty = not ids and any(
        gid in outstanding and name == "search_evidence" for gid, (name, _) in gaps.items()
    )
    for metric, period in missing:
        if (metric, period) not in declarations and not search_empty:
            raise ValueError(f"Record the missing {metric} input for {period}")
    prior_comparison = False
    for rid in receipt_ids:
        result = comparisons[rid]
        input_ids = result["input_ids"]
        if len(input_ids) != 2 or not set(input_ids) <= facts.keys():
            raise ValueError("A comparison requires both retrieved, cited financial observations")
        current, baseline = (facts[pid] for pid in input_ids)
        if evidence.compare(passages[input_ids[0]], passages[input_ids[1]], result["kind"]) != result:
            raise ValueError("Calculation differs from its versioned financial inputs")
        assertions.append(
            {
                **result,
                "comparison_kind": result["kind"],
                "kind": "calculation",
                "receipt_id": rid,
                "company": current["company"],
                "instrument_id": listing["id"],
            }
        )
        relevant = (
            (not intent.metrics or current["metric"] in intent.metrics)
            and matches_dimensions(current, intent)
            and _fits_trend((current, baseline), intent.trend)
        )
        if relevant and (
            not intent.periods
            or all(period_matches(current, p) or period_matches(baseline, p) for p in intent.periods)
        ):
            prior_comparison = True
        percent = f" ({result['percent_change']}%)" if result["percent_change"] is not None else ""
        changes.append(
            f"{listing['ticker']} {current['basis']} {current['metric']} changed from "
            f"{baseline['value']} {baseline['unit']} in {baseline['period_label']} "
            f"to {current['value']} {current['unit']} in {current['period_label']}. "
            f"The difference was {result['difference']} {result['unit']}{percent}."
        )
    if selection["status"] == "complete":
        if not _scope_supported(context["question"], listing):
            raise ValueError(
                "The selected method cannot establish all requested entities, metrics or horizons"
            )
        if not intent.metrics and not intent.checks:
            raise ValueError("The question requires a supported metric or a specific coverage gap")
        if intent.trend and intent.metrics and not prior_comparison:
            raise ValueError("The requested comparison requires the matching periods and calculation")
        latest, saved = _latest_saved(context["question"])
        if latest and not saved:
            raise ValueError(
                "Current coverage is unverified. Ask about the latest saved period or record a freshness gap."
            )
    if intent.trend and intent.metrics and not prior_comparison and not missing and facts:
        technical_gap = any(
            gid in outstanding
            and (
                name == "compare_financials"
                or (name == "record_gap" and data.get("metric") in intent.metrics)
            )
            for gid, (name, data) in gaps.items()
        )
        if not technical_gap:
            raise ValueError(
                "The requested comparison needs a compatible calculation or its own missing-input gap"
            )
        summaries.append("The available periods do not support the requested comparison.")
    for metric, period in missing:
        summaries.append(
            f"The requested {metric.replace('_', ' ')} is unavailable"
            + (f" for {period}" if period != "unspecified" else "")
            + (f" in {intent.currency}" if intent.currency else "")
            + (f" ({intent.unit_scale})" if intent.unit_scale else "")
            + "."
        )
    if changes and prior_comparison:
        summaries.extend(changes)
    else:
        for f in fits:
            if (not intent.metrics or f["metric"] in intent.metrics) and (
                not intent.periods or any(period_matches(f, p) for p in intent.periods)
            ):
                summaries.append(
                    f"{listing['ticker']} reported {f['basis']} {f['metric']} of {f['value']} "
                    f"{f['unit']} for {f['period_label']}."
                )
    if not summaries:
        summaries.append("The requested conclusion is unresolved with the available evidence.")
    if _latest_saved(context["question"])[0]:
        summaries.append("Coverage is limited to saved observations and their reporting dates.")
    if selection["status"] != "complete" and not _scope_supported(context["question"], listing):
        summaries.insert(
            0,
            f"The full question remains unresolved. The following evidence covers only {listing['ticker']}.",
        )
    notes = []
    qualifications = [passages[p] for p in ids if passages[p]["locator"] == "/qualification"]
    for passage in qualifications:
        summaries.append(f"The issuer qualification reads “{passage['text']}”")
        notes.append("This disclosure leaves open the contribution of other factors to the change.")
    if prior_comparison and re.search(r"\bfull[ -]year demand\b", context["question"], re.IGNORECASE):
        summaries.append(
            "The quarter-to-quarter figures alone do not establish a change in full-year demand."
        )
    for gid in gap_ids:
        name, _ = gaps.get(gid, ("", {}))
        if name == "price_context":
            summaries.append("The share-price move and its observation interval remain unverified.")
        if name == "historical_consensus":
            summaries.append("A pre-release Street comparison is unavailable.")
    if gap_ids and set(intent.checks) == {"price_context", "historical_consensus"}:
        summaries.append("The data are insufficient for the purchase or sale decision.")
    notes.append(
        "Reported financial observations alone cannot establish the cause of a market move."
        if "price_context" in intent.checks
        else "A reported period alone cannot establish future performance."
    )
    next_steps = [
        "Obtain the missing inputs identified in the coverage record."
        if gap_ids
        else "Check the next comparable disclosure for revisions or qualifications."
    ]
    body = {
        "status": selection["status"],
        "conclusion": " ".join(summaries),
        "changes": changes,
        "claims": claims,
        "calculations": receipt_ids,
        "alternative_explanations": notes,
        "gaps": gap_ids,
        "next_steps": next_steps,
    }
    return body, assertions


def validate_assessment(db, run, body, receipts):
    context = json.loads(run["context"])
    calls = []
    for row in receipts:
        output = json.loads(row["output"])
        if row["tool"] == "get_evidence" and row["status"] == "ok":
            pid = output["data"]["id"]
            output["data"] = evidence.get(
                db, context["instrument"]["id"], pid, context["cutoff"], fixture=is_fixture(db)
            )
        calls.append((row["tool"], output))
    selection = {k: body[k] for k in ("status", "gaps", "calculations")}
    selection["passage_ids"] = [ref for claim in body["claims"] for ref in claim["evidence_refs"]]
    expected, assertions = render(context, selection, calls)
    if _latest_saved(context["question"]) == (True, True) and body["status"] == "complete":
        intent = objective(context["question"])
        for metric in intent.metrics:
            selected = [
                a["period_end"]
                for a in assertions
                if a["kind"] == "observation"
                and a["metric"] == metric
                and matches_dimensions(a, intent)
                and (not intent.periods or any(period_matches(a, p) for p in intent.periods))
            ]
            if not selected:
                raise ValueError("Missing latest eligible reporting period")
            rows = db.execute(
                """SELECT p.id FROM evidence_passages p JOIN documents d ON d.id=p.document_id
                   WHERE d.instrument_id=? AND d.fixture=? AND json_extract(p.financial,'$.metric')=?
                   AND json_extract(p.financial,'$.period_end')>? AND (? IS NULL OR p.available_at<=?)""",
                (
                    context["instrument"]["id"],
                    is_fixture(db),
                    metric,
                    max(selected),
                    context["cutoff"],
                    context["cutoff"],
                ),
            )
            for row in rows:
                passage = evidence.get(
                    db, context["instrument"]["id"], row[0], context["cutoff"], fixture=is_fixture(db)
                )
                fact = passage["financial"]
                if (
                    evidence.supports_actual(fact, context["instrument"].get("cik"))
                    and matches_dimensions(fact, intent)
                    and (not intent.periods or any(period_matches(fact, p) for p in intent.periods))
                    and evidence.still_supported(db, passage, context["cutoff"])
                ):
                    raise ValueError("Read the latest eligible saved reporting period before submission")
    for item in assertions:
        if item["kind"] == "observation":
            qualifiers = db.execute(
                "SELECT id FROM evidence_passages WHERE document_id=? AND locator='/qualification'",
                (item["document_id"],),
            )
            if any(r[0] not in selection["passage_ids"] for r in qualifiers):
                raise ValueError("Retrieve and cite the source qualification alongside its observation")
    for key in expected:
        if expected[key] != body[key]:
            raise ValueError(f"Unsupported assessment field: {key}")
    return assertions
