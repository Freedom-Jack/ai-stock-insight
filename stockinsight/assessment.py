"""Build an assessment from retrieved observations and recorded calculations.

The investigator selects source and receipt IDs. The service describes their
meaning and verifies the same selection again inside the submission transaction.
"""

import json
import re
from dataclasses import dataclass, replace
from datetime import date

from . import evidence
from .db import is_fixture

_METRICS = {
    "revenue_per_share": r"(?:revenue|sales) per share",
    "dividend_yield": r"dividend yield",
    "shares_outstanding": r"(?:weighted average )?shares outstanding",
    "share_repurchases": r"share repurchases|stock repurchases|buybacks",
    "revenue": r"revenue[s]?|sales",
    "dividend_per_share": r"(?:dividends?|payout)(?: (?:paid|declared))? per (?:common |ordinary )?share|per share dividends?",
    "total_dividends": r"(?:total|aggregate) (?:cash )?dividends?|dividends?(?: (?:paid|declared))? in (?:total|aggregate)",
    "dividend": r"dividends?",
    "operating_margin": r"operating margins?",
    "gross_margin": r"gross margins?",
    "net_income": r"net income|net profit",
    "earnings_per_share": r"earnings per share|eps",
    "free_cash_flow": r"free cash flow",
}
_QUARTERS = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_FY = r"\b(?:fy\s*|fiscal (?:year )?)(20\d\d|\d\d)\b"
_QUARTER = r"\bq([1-4])\b|\b(first|second|third|fourth)[ -]quarter\b"
_RANGE = r"\b(\d{4}-\d\d-\d\d)\s+(?:to|through|and)\s+(\d{4}-\d\d-\d\d)\b"
_CURRENCIES = {
    "USD": r"usd|us dollars?",
    "EUR": r"eur|euros?",
    "GBP": r"gbp|pounds?",
    "JPY": r"jpy|yen",
    "CAD": r"cad|canadian dollars?",
    "CNY": r"cny|yuan",
}


@dataclass(frozen=True)
class Dimensions:
    basis: str
    currency: str
    unit_scale: str
    duration: str
    share_basis: str


@dataclass(frozen=True)
class Objective(Dimensions):
    metrics: tuple
    periods: tuple
    trend: str
    checks: tuple
    requirements: tuple
    bindings_complete: bool
    scoped_dimensions: dict
    latest_requirements: tuple

    def dimensions_for(self, metric, period):
        return self.scoped_dimensions.get((metric, period), self)


@dataclass(frozen=True)
class Clause:
    text: str
    metrics: tuple
    years: tuple
    quarters: tuple
    ranges: tuple
    residual: str


def _clause(text):
    remaining = text
    metrics = []
    for metric, pattern in _METRICS.items():
        remaining, count = re.subn(r"\b(?:" + pattern + r")\b", " ", remaining)
        if count:
            metrics.append(metric)
    years = list(dict.fromkeys("FY" + y[-2:] for y in re.findall(_FY, text)))
    quarters = ["Q" + (digit or _QUARTERS[ordinal]) for digit, ordinal in re.findall(_QUARTER, text)]
    dates = [start + " to " + end for start, end in re.findall(_RANGE, text)]
    return Clause(text, tuple(metrics), tuple(years), tuple(quarters), tuple(dates), remaining)


def _bindings(q):
    # An explicit coordination boundary separates predicates and dates. A
    # unique shared year or metric can qualify abbreviated adjacent clauses.
    # There is no distance heuristic and no cross-product of independent clauses.
    normalized = re.sub(_RANGE, r"\1 to \2", q.replace("per-share", "per share"))
    clauses = [
        _clause(part)
        for part in re.split(
            r"[,;&?!]|\b(?:and|or|versus|vs|but)\b|\b(?:to|with)\s+(?=(?:q[1-4]|fy\s*\d))", normalized
        )
    ]
    # The noun can appear once for several coordinated measures, for example
    # "total and per-share dividends" or "dividends per share and in total".
    dividend_subject = any(
        name in {"dividend", "dividend_per_share", "total_dividends"}
        for clause in clauses
        for name in clause.metrics
    )
    if dividend_subject:
        for index, clause in enumerate(clauses):
            if clause.metrics and clause.metrics != ("dividend",):
                continue
            qualifier = re.search(
                r"\bper (?:common |ordinary |basic |diluted )?share\b|\b(?:total|aggregate)\b", clause.text
            )
            if qualifier:
                measure = "dividend_per_share" if qualifier.group().startswith("per ") else "total_dividends"
                clauses[index] = replace(clause, metrics=(measure,))
    metrics = tuple(dict.fromkeys(m for clause in clauses for m in clause.metrics))
    years = {y for clause in clauses for y in clause.years}
    named_quarters = {n for clause in clauses for n in clause.quarters}
    bindings, periods, complete = [], [], True
    groups = []
    for clause in clauses:
        quarters = clause.quarters
        if (
            not quarters
            and not clause.metrics
            and clause.years
            and len(named_quarters) == 1
            and len(metrics) == 1
        ):
            quarters = list(named_quarters)
        if quarters:
            available_years = clause.years or (list(years) if len(years) == 1 else [])
            if len(available_years) > 1 or (not available_years and len(years) > 1):
                complete = False
            year = " " + available_years[0] if len(available_years) == 1 else ""
            local_periods = [quarter + year for quarter in quarters]
        else:
            local_periods = list(clause.years)
        local_periods.extend(clause.ranges)
        groups.append((clause.metrics, local_periods, clause.text))
        periods.extend(local_periods)
    periods = tuple(dict.fromkeys(periods))
    for names, local_periods, original in groups:
        if not names and local_periods and len(metrics) > 1 and len(periods) > 1:
            complete = False
        if names and not local_periods and len(periods) > 1 and len(metrics) > 1:
            complete = False
        local_latest = _latest_saved(original)[0]
        applicable = names or (metrics if local_latest or (len(metrics) == 1 and local_periods) else ())
        dates = local_periods or (
            periods if not local_latest and (len(metrics) == 1 or len(periods) == 1) else ()
        )
        bindings.extend(((name, p), original) for name in applicable for p in (dates or ("unspecified",)))
    return metrics, periods, tuple(dict.fromkeys(bindings)), complete, " ".join(c.residual for c in clauses)


def objective(question):
    q = question.casefold()
    metrics, periods, clauses, bindings_complete, remaining = _bindings(q)
    decision = re.search(r"\b(?:buy|buying|sell|selling|purchase|invest in)\b", q)
    # Accounting subjects such as shares outstanding and earnings per share
    # were consumed above. A remaining tradable-share subject needs market
    # evidence regardless of the verb or a second, accounting-related clause.
    price = decision or re.search(r"\b(?:shares|stock|prices?|market reaction)\b", remaining)
    event_clauses = re.split(r"\b(?:after|before|following|despite|upon)\b", q, maxsplit=1)
    # A ticker/name can stand for its shares. An unsupported market-reaction
    # predicate cannot be answered by a metric in the event clause alone.
    main_clause = event_clauses[0] or event_clauses[-1].partition(",")[2]
    market_predicate = re.search(
        r"\b(?:fall|fell|fallen|rise|rose|drop(?:ped)?|rall(?:y|ied)|trade[d]?|trading|"
        r"react(?:ed)?|recover(?:ed)?|move[d]?|outperform(?:ed)?|underperform(?:ed)?)\b",
        main_clause,
    )
    if len(event_clauses) == 2 and market_predicate and not _clause(main_clause).metrics:
        price = True
    elif not metrics and re.search(
        r"\b(?:nvda|nvidia|msft|microsoft)\s+(?:has\s+)?(?:fallen|fell|rose|rallied)\b", q
    ):
        price = True
    consensus = decision or re.search(r"\b(?:consensus|surprise|expectations?|street estimates?)\b", q)
    checks = tuple(
        name for name, needed in (("historical_consensus", consensus), ("price_context", price)) if needed
    )
    trend = ""
    financial_predicate = main_clause if price else q
    measured_change = re.search(
        r"\b(?:compare[d]?|comparison|trend|growth|grew|increas(?:e|ed)|declin(?:e|ed)|"
        r"change[d]?|fall|fell|fallen|rose|rise|drop(?:ped)?|higher|lower|down|up)\b",
        financial_predicate,
    )
    if re.search(r"\byoy\b|year[ -]over[ -]year|year[ -]on[ -]year|same quarter (?:last|prior) year", q):
        trend = "year_over_year"
    elif re.search(r"\bqoq\b|quarter[ -]over[ -]quarter|sequential", q) or (
        re.search(r"compare|change|increas|declin|growth", q)
        and re.search(r"prior quarter|previous quarter", q)
    ):
        trend = "sequential"
    elif measured_change and (not price or _clause(financial_predicate).metrics):
        trend = "period_trend"
    global_dims = _dimensions(q)
    scoped = {}
    latest = []
    for key, original in clauses:
        # A single metric may have a shared currency or scale after a series
        # of periods. A unit attached to a different metric stays with it.
        local = _dimensions(original)
        row = {}
        for name in Dimensions.__dataclass_fields__:
            value = getattr(local, name)
            if not value and len(metrics) == 1:
                value = getattr(global_dims, name)
            row[name] = value
        if key[1].startswith("Q") and not row["duration"]:
            row["duration"] = "standalone_quarter"
        if key[0] == "total_dividends":
            row["share_basis"] = "total"
        dimensions = Dimensions(**row)
        if key in scoped and scoped[key] != dimensions:
            bindings_complete = False
        scoped[key] = dimensions
        if _latest_saved(original)[0]:
            latest.append(key)
    if _latest_saved(q)[0] and not latest:
        latest = list(scoped)
    return Objective(
        **vars(global_dims),
        metrics=metrics,
        periods=periods,
        checks=checks,
        trend=trend,
        requirements=tuple(scoped),
        bindings_complete=bindings_complete,
        scoped_dimensions=scoped,
        latest_requirements=tuple(dict.fromkeys(latest)),
    )


def _dimensions(q):
    basis = "non-GAAP" if re.search(r"adjusted|non[ -]?gaap", q) else "US GAAP" if "gaap" in q else ""
    currencies = [code for code, names in _CURRENCIES.items() if re.search(r"\b(?:" + names + r")\b", q)]
    scale = re.search(r"\b(thousand|million|billion|trillion)s?\b", q)
    horizon = q.replace("full-year demand", "").replace("full year demand", "")
    duration = ""
    if re.search(r"annual|full[ -]year", horizon):
        duration = "annual"
    elif re.search(r"\bytd\b|year[ -]to[ -]date", horizon):
        duration = "year_to_date"
    elif re.search(_QUARTER, q) or re.search(r"\bquarter\w*\b", horizon):
        duration = "standalone_quarter"
    return Dimensions(
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
    supported_periods = {"unspecified", "Q1 FY25", "Q2 FY25", "Q1", "Q2"}
    coverage = [
        m == "revenue"
        and p in supported_periods
        and matches_dimensions(
            {
                "basis": "US GAAP",
                "duration": "standalone_quarter",
                "currency": "USD",
                "unit": "USD million",
                "share_basis": "total",
            },
            intent.dimensions_for(m, p),
        )
        for m, p in intent.requirements
    ]
    # Mixed questions can retain a supported component and request a gap for
    # each missing input. An unknown standalone question remains outside the demo.
    if coverage and any(coverage) and (not all(coverage) or intent.checks):
        return intent.bindings_complete and intent.trend != "year_over_year"
    return bool(
        (words <= _FIXTURE_WORDS or intent.checks == ("price_context",))
        and intent.bindings_complete
        and (intent.metrics or intent.checks or "results" in words)
        and all(coverage)
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


def matches_requirement(fact, intent, metric, period):
    return (
        fact["metric"] == metric
        and period_matches(fact, period)
        and matches_dimensions(fact, intent.dimensions_for(metric, period))
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
    for names in _CURRENCIES.values():
        q = re.sub(r"\b(?:" + names + r")\b", " ", q)
    q = re.sub(r"\b(?:thousand|million|billion|trillion)s?\b", " ", q)
    common = (_FIXTURE_WORDS - {"fy25", "fy2025", "nvidia", "nvda", "year", "full", "yield"}) | set(
        """amount according across calculate captured company current dated declare declared different difference
        basic diluted during each ended ending equity financials figures filed filings find figure had latest last most over
        paid pay payout per period periods prior provide recent record recorded retained sequentially standalone
        stood stored successive trend versus vs within yoy qoq total values workspace""".split()
    )
    return set(re.findall(r"[a-z]+[0-9]*|[0-9]+", q)) <= common


def _latest_saved(question):
    local = r"(?:saved|retained|recorded|stored|workspace)"
    scopes = []
    for clause in re.split(r"[,;?!]|\b(?:and|but|or|versus|vs)\b", question.casefold()):
        relative = "last|this"
        # A date can anchor a previous period in this clause only.
        if not re.search(_QUARTER + "|" + _FY + r"|\b\d{4}-\d{2}-\d{2}\b", clause):
            relative += "|previous|prior"
        period = rf"(?:{relative})\s+(?:(?:reported|completed|fiscal|calendar|reporting|{local})\s+)*(?:quarter|year|period)"
        horizon = rf"\b(?:latest|newest|most recent|current(?:ly)?|as of today|{period})\b"
        for match in re.finditer(horizon, clause):
            rest = re.split(r"\b(?:than|compared)\b", clause[match.end() :], maxsplit=1)[0]
            explicit = re.search(rf"\b{local}\b", match.group()) or re.match(rf"\s+{local}\b", rest)
            if match.group() in ("latest", "newest", "most recent"):
                explicit = explicit or re.search(rf"\b(?:in|from|among|of) (?:the |our |my )?{local}\b", rest)
            scopes.append(bool(explicit))
    return bool(scopes), bool(scopes) and all(scopes)


def _ids(value):
    if not isinstance(value, list) or len(value) > 32 or any(not isinstance(i, str) for i in value):
        raise ValueError("Expected a bounded list of evidence or receipt IDs")
    if len(set(value)) != len(value):
        raise ValueError("Duplicate assessment reference")
    return value


def render(context, selection, calls):
    """Derive canonical human-readable fields, plus machine-readable support."""
    from . import announcement_research

    if context.get("method") == announcement_research.METHOD:
        return announcement_research.render(context, selection, calls)
    intent = objective(context["question"])
    latest, saved = _latest_saved(context["question"])
    latest = latest or bool(intent.latest_requirements)
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
    if not set(intent.checks).issubset({name for name, _ in calls}):
        raise ValueError("Missing required price or expectation coverage receipt")
    # This accounting method can record a market-data limitation. It has no
    # validated event-window prices or dated Street estimates to assert.
    documented_limits = {name for gid, (name, _) in gaps.items() if gid in outstanding}
    for capability in intent.checks:
        if capability not in documented_limits:
            raise ValueError(f"{capability} needs scoped market evidence or a recorded limitation")
    required = intent.requirements
    missing = [
        (m, p) for m, p in required if not any(matches_requirement(f, intent, m, p) for f in facts.values())
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
    answered_trends = set()
    supported_changes = []
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
        percent = f" ({result['percent_change']}%)" if result["percent_change"] is not None else ""
        changes.append(
            f"{listing['ticker']} {current['basis']} {current['metric']} changed from "
            f"{baseline['value']} {baseline['unit']} in {baseline['period_label']} "
            f"to {current['value']} {current['unit']} in {current['period_label']}. "
            f"The difference was {result['difference']} {result['unit']}{percent}."
        )
        targeted = [(m, p) for m, p in required if m == current["metric"]]
        if (
            (not required or targeted)
            and _fits_trend((current, baseline), intent.trend)
            and all(
                any(matches_requirement(f, intent, m, p) for f in (current, baseline)) for m, p in targeted
            )
        ):
            answered_trends.add(current["metric"])
            supported_changes.append(changes[-1])
    prior_comparison = bool(supported_changes)
    if selection["status"] == "complete":
        if not intent.bindings_complete or not _scope_supported(context["question"], listing):
            raise ValueError(
                "The selected method cannot establish all requested entities, metrics or horizons"
            )
        if not intent.metrics and not intent.checks:
            raise ValueError("The question requires a supported metric or a specific coverage gap")
        if intent.trend and not set(intent.metrics).issubset(answered_trends):
            raise ValueError("The requested comparison requires the matching periods and calculation")
        if latest and not saved:
            raise ValueError(
                "Current coverage is unverified. Review the dated observations or ask about the latest saved period."
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
        dims = intent.dimensions_for(metric, period)
        summaries.append(
            f"The requested {metric.replace('_', ' ')} is unavailable"
            + (f" for {period}" if period != "unspecified" else "")
            + (f" in {dims.currency}" if dims.currency else "")
            + (f" ({dims.unit_scale})" if dims.unit_scale else "")
            + "."
        )
    summaries.extend(supported_changes)
    for f in facts.values():
        if f["metric"] not in answered_trends and (
            not required or any(matches_requirement(f, intent, m, p) for m, p in required)
        ):
            summaries.append(
                f"{listing['ticker']} reported {f['basis']} {f['metric'].replace('_', ' ')} of {f['value']} "
                f"{f['unit']} for {f['period_label']}."
            )
    if not summaries:
        summaries.append("The requested conclusion is unresolved with the available evidence.")
    pages = [out["data"] for name, out in calls if name in ("search_evidence", "next_evidence_page")]
    if gap_ids and pages and pages[-1].get("has_more"):
        summaries.append(
            "Additional saved evidence remains beyond the last retrieved page. Missing inputs refer to the reviewed passages."
        )
    if latest:
        summaries.append("Coverage is limited to saved observations and their reporting dates.")
        if not saved:
            summaries.append("Coverage of the issuer's latest reporting period remains unverified.")
    if selection["status"] != "complete" and not _scope_supported(context["question"], listing):
        summaries.insert(
            0,
            f"The full question remains unresolved. The following evidence covers only {listing['ticker']}.",
        )
    if not intent.bindings_complete:
        summaries.insert(
            0,
            "The fiscal-year or metric grouping remains ambiguous. Clarify the period for each requested measure.",
        )
    if "dividend" in intent.metrics:
        summaries.append(
            "Specify whether the dividend question concerns a total cash amount or an amount per share."
        )
    notes = []
    financial_docs = {passages[p]["document_id"] for p in facts}
    qualifications = [
        passages[p] for p in ids if p not in facts and passages[p]["document_id"] in financial_docs
    ]
    for passage in qualifications:
        summaries.append(f"The source qualification or accompanying note reads “{passage['text']}”")
    if financial_docs - {p["document_id"] for p in qualifications}:
        notes.append(
            "The retained financial cells establish the amounts. Review the full disclosure for qualifications before interpreting their cause."
        )
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
    intent = objective(context["question"])
    for metric, period in intent.latest_requirements:
        selected = [
            a["period_end"]
            for a in assertions
            if a["kind"] == "observation" and matches_requirement(a, intent, metric, period)
        ]
        if not selected:
            # A partial can explicitly leave this metric unanswered. render()
            # has already checked the missing requirement and its receipt.
            continue
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
                and matches_requirement(fact, intent, metric, period)
                and evidence.still_supported(db, passage, context["cutoff"])
            ):
                raise ValueError("Read the latest eligible saved reporting period before submission")
    doc_notes = {}
    for item in assertions:
        if item["kind"] != "observation":
            continue
        doc = item["document_id"]
        if doc not in doc_notes:
            doc_notes[doc] = [r["id"] for r in evidence.source_context(db, doc, context["cutoff"])]
        if not set(doc_notes[doc]).issubset(selection["passage_ids"]):
            raise ValueError(
                "Retrieve and cite the source context and qualifications alongside the observation"
            )
        item["context_passage_ids"] = doc_notes[doc]
    for key in expected:
        if expected[key] != body[key]:
            raise ValueError(f"Unsupported assessment field: {key}")
    return assertions
