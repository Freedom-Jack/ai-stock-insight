"""Watchlist-scoped research with dated primary sources and host-checked financial facts."""

from . import announcement_research, assessment, evidence, providers
from .executor import ExecutorError, Result

PLANS = {
    "reported_figures": "Investigate reported financial figures and compare matching accounting periods.",
    "market_context": "Check market prices or pre-release expectations before interpreting company results.",
    "issuer_disclosure": "Find the issuer's dated disclosures and read the accompanying qualifications.",
}
NEWS_PLANS = {
    "issuer_disclosure": "Check the official issuer's public feed first, then retrieve dated headlines.",
    "saved_headlines": "Read the saved feed first, then check its public source for changes.",
}


def model_available():
    from . import local_model

    return local_model.available()


def _comparison_pair(candidates, intent, metric, periods):
    ordered = sorted(
        candidates, key=lambda p: p["financial"]["period_end"], reverse=True
    )
    fallback = None
    for current in ordered:
        if current["financial"]["period_end"] != ordered[0]["financial"]["period_end"]:
            break
        for baseline in ordered:
            facts = (current["financial"], baseline["financial"])
            if facts[0]["period_end"] <= facts[1][
                "period_end"
            ] or not assessment._fits_trend(facts, intent.trend):
                continue
            if not all(
                any(assessment.matches_requirement(f, intent, metric, p) for f in facts)
                for p in periods
            ):
                continue
            if fallback is None:
                fallback = (current, baseline)
            try:
                evidence.compare(current, baseline, "period_trend")
            except ValueError:
                continue
            return current, baseline
    return fallback


def _choose_observations(rows, intent, cik):
    facts = sorted(
        (p for p in rows if evidence.supports_actual(p.get("financial") or {}, cik)),
        key=lambda p: p["financial"]["period_end"],
        reverse=True,
    )
    selected, pairs, missing = {}, [], []
    for metric in intent.metrics:
        periods = [period for m, period in intent.requirements if m == metric]
        candidates = {}
        for period in periods:
            matches = [
                p
                for p in facts
                if assessment.matches_requirement(
                    p["financial"], intent, metric, period
                )
            ]
            if not matches:
                missing.append((metric, period))
                continue
            selected[matches[0]["id"]] = matches[0]
            for p in matches:
                candidates[p["id"]] = p
        if intent.trend:
            pair = _comparison_pair(candidates.values(), intent, metric, periods)
            if pair:
                current, baseline = pair
                selected.update({current["id"]: current, baseline["id"]: baseline})
                pairs.append((current["id"], baseline["id"]))
    if not intent.metrics and intent.checks and facts:
        selected[facts[0]["id"]] = facts[0]
    return selected, pairs, missing


def execute(context, call, *, on_device=False, runtime=None):
    question = context["question"]
    intent = assessment.objective(question)
    listing = context["instrument"]
    calls = []
    if runtime is None:
        runtime = {}
    runtime.update(
        adapter="local-source-research/1",
        actual_model=None,
        billing_mode="local_no_provider_charges",
        requests_attempted=0,
    )

    def check(name, args=None):
        result = call(name, args or {})
        calls.append((name, result))
        return result

    if on_device:
        from . import local_model

        menu = (
            NEWS_PLANS
            if context.get("method") == announcement_research.METHOD
            else PLANS
        )
        plan, metadata = local_model.choose(question, menu)
        runtime.update(metadata)
        runtime["adapter"] = "on-device-source-research/1"
    else:
        if context.get("method") == announcement_research.METHOD:
            plan = "issuer_disclosure"
        else:
            plan = "market_context" if intent.checks else "reported_figures"
    runtime["research_plan"] = plan
    if context.get("method") == announcement_research.METHOD:
        return announcement_research.execute(context, call, runtime)
    if not intent.metrics and not intent.checks:
        raise ExecutorError(
            "question_scope",
            "This method supports reported financial observations and "
            "market-context checks. Try a dated revenue question or save this as a research plan.",
        )
    if plan == "market_context":
        for name in intent.checks:
            check(name)

    # A named issuer release covers only two historic quarters. A recent SEC
    # request must never be answered by calling that old release current.
    named_quarters = bool(intent.periods) and set(intent.periods) <= {
        "Q1 FY25",
        "Q2 FY25",
        "Q1",
        "Q2",
    }
    historical_route = named_quarters or (
        not intent.periods and not providers.sec_contact()
    )
    provider = (
        "issuer"
        if listing.get("cik") == "0001045810"
        and historical_route
        and not intent.latest_requirements
        else "sec"
    )
    if listing.get("cik") == "0000789019" and not intent.latest_requirements and (
        bool(intent.periods) and set(intent.periods) <= {"Q1 FY27", "Q1 FY26", "Q1"}
        or not intent.periods and not providers.sec_contact()
    ):
        provider = "msft_release"
    if plan == "issuer_disclosure":
        check("capture_public", {"provider": provider})
    search = check("search_evidence")
    rows = list(search["data"]["passages"])
    if plan != "issuer_disclosure" and (
        not rows or _choose_observations(rows, intent, listing.get("cik"))[2]
    ):
        check("capture_public", {"provider": provider})
        search = check("search_evidence")
        rows = list(search["data"]["passages"])
    # Page discovery uses the assignment's frozen search boundary. Leave room
    # in its twenty-call budget for exact reads, checks and calculations.
    for _ in range(4):
        if not search["data"]["has_more"]:
            break
        search = check("next_evidence_page", {"cursor": search["data"]["next_cursor"]})
        rows.extend(search["data"]["passages"])
    selected, pairs, missing = _choose_observations(rows, intent, listing.get("cik"))
    documents = {p["document_id"] for p in selected.values()}
    for p in rows:
        if p["document_id"] in documents and not p.get("financial"):
            selected[p["id"]] = p
    for ref in context.get("source_updates",{}):
        selected.setdefault(ref,None)
    for ref in selected:
        check("get_evidence", {"id": ref})
    for metric, period in missing:
        check(
            "record_gap",
            {
                "metric": metric,
                "period": period,
                "attempt_receipt_id": search["receipt_id"],
            },
        )
    calculations = []
    for current, baseline in pairs:
        outcome = check(
            "compare_financials",
            {"current": current, "baseline": baseline, "kind": "period_trend"},
        )
        if outcome["status"] == "ok":
            calculations.append(outcome["receipt_id"])
    if plan != "market_context":
        for name in intent.checks:
            check(name)
    outstanding = calls[-1][1]["outstanding_gap_ids"]
    status = ("partial" if outstanding else "complete") if selected else "blocked"
    body, _ = assessment.render(
        context,
        {
            "status": status,
            "passage_ids": list(selected),
            "calculations": calculations,
            "gaps": outstanding,
        },
        calls,
    )
    return Result(body, runtime)
