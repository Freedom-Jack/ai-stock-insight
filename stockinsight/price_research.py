"""Receipt-backed close-to-close questions for one selected listing and two explicit session dates."""

import re

from . import methods

METHOD = "dated_listing_closes.v1"
_DATE = r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])"
_CLOSE_VOCABULARY = """a an the what was were is are did how much by of its it my our company listing between from to on for
    at prices price stock share shares close closes closed closing regular session sessions market change changes changed
    move moves moved movement gain gains gained rise rose increase increased fall fell decline declined decrease decreased
    return returns percent percentage difference absolute compare comparison in over during period dates
    starting ending initial final end start quoted adjusted unadjusted split total exchange us dollar dollars
    show give calculate me this that two value values per"""
_WORDS = frozenset(_CLOSE_VOCABULARY.split())


def accepts(question):
    if not isinstance(question, str) or len(re.findall(_DATE, question)) != 2:
        return False
    if re.search(
        r"\b(revenue|sales|margin|dividend|eps|income|ebitda|valuation|shares outstanding|return on equity)\b",
        question,
        re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(
            r"\b(price|prices|close|closed|closing|return|returns)\b|\b(stock|shares)\b.*\b(rose|fall|fell|move|rise|change)\b",
            question,
            re.IGNORECASE,
        )
    )


def scoped(question, listing):
    q = re.sub(_DATE, " sessiondate ", question.casefold().replace("’", "'")).strip().rstrip("?.!")
    # "And" may join the two dates (or the two arithmetic outputs); a new
    # clause asks an additional question and needs its own evidence.
    q = re.sub(r"\bsessiondate\s+(?:and|to|through)\s+sessiondate\b", " ", q)
    q = re.sub(r"\babsolute and percent(?:age)?\b", " ", q)
    if re.search(r"[?;=!<>€£¥]|\b(?:and|or)\b", q):
        return False
    name = (listing.get("company_name") or "").casefold()
    short = re.sub(r"\s+(corporation|corp\.?|inc\.?)$", "", name)
    for token in (name, short, (listing["ticker"] or "").casefold(), (listing["currency"] or "").casefold()):
        if token:
            q = re.sub(r"\b" + re.escape(token) + r"(?:'s)?\b", " ", q)
    return set(re.findall(r"[^\W_]+", q)) <= _WORDS


def window(db, context):
    p = methods.price_context(db, context["instrument"]["id"], context["question"], context.get("cutoff"))
    if p is None:
        return {
            "status": "partial",
            "gaps": ["Choose two ordered, exact ISO session dates."],
            "passages": [],
            "evidence_ids": [],
            "calculation": None,
            "warnings": [],
        }
    if not scoped(context["question"], context["instrument"]):
        p["status"] = "partial"
        p["gaps"].append(
            "Only the selected listing’s dated market closes are covered. Other issuers, periods, metrics, forecasts or causes remain unresolved."
        )
    return p


def render(context, selection, calls):
    ops = [out for name, out in calls if name == "price_context"]
    if not ops or context["method"] != METHOD:
        raise ValueError("Obtain the assigned price-window receipt.")
    receipt = ops[-1]
    data = receipt["data"]
    ids = data["evidence_ids"]
    reads = {
        out["data"]["id"]: out["data"]
        for name, out in calls
        if name == "get_evidence" and out["status"] == "ok"
    }
    if selection["passage_ids"] != ids or any(reads.get(p["id"]) != p for p in data["passages"]):
        raise ValueError("Read each exact market close returned by this run.")
    pending = calls[-1][1]["outstanding_gap_ids"]
    status = ("partial" if pending else "complete") if ids else "blocked"
    calc = data["calculation"]
    if calc and (len(ids) != 2 or methods._price_change(reads[ids[1]], reads[ids[0]]) != calc):
        raise ValueError("The market-window arithmetic differs from its source observations.")
    if status == "complete" and (
        not calc or receipt["status"] != "ok" or not scoped(context["question"], context["instrument"])
    ):
        raise ValueError("A complete price result requires a supported, unambiguous market-close question.")
    calc_ids = [receipt["receipt_id"]] if calc else []
    if (selection["status"], selection["gaps"], selection["calculations"]) != (status, pending, calc_ids):
        raise ValueError("Retain the recorded price calculation and coverage limitations.")
    symbol = context["instrument"]["ticker"]
    conclusion = f"The requested market move for {symbol} remains unverified."
    if calc:
        start, end = calc["session_window"]
        pct = f" ({calc['percent_change']}%)" if calc["percent_change"] is not None else ""
        security = f"{symbol} · {context['instrument']['listing_exchange']}"
        first, last = (reads[i]["financial"] for i in ids)
        conclusion = (
            f"{security} closed at {calc['baseline_value']} {calc['unit']} on {start} and "
            f"{calc['current_value']} {calc['unit']} on {end}. Its {calc['basis'].replace('_', ' ')} change "
            f"was {calc['difference']} {calc['unit']}{pct}. "
            f"The source names {first.get('publisher') or reads[ids[0]]['origin']} and series {first['series_id']}, with stated delays of "
            f"{first['delay_seconds']} and {last['delay_seconds']} seconds."
        )
    conclusion += " " + " ".join(data["warnings"] + data["gaps"])
    if context.get("cutoff"):
        conclusion += f" Public-information cutoff {context['cutoff']}."
    claims = [{"text": reads[i]["text"], "type": "fact", "evidence_refs": [i]} for i in ids]
    assertions = [
        {
            "kind": "market_close_observation",
            "passage_id": i,
            "document_id": reads[i]["document_id"],
            "version_hash": reads[i]["version_hash"],
            "origin": reads[i]["origin"],
            "received_at": reads[i]["received_at"],
            "available_at": reads[i]["available_at"],
            **reads[i]["financial"],
        }
        for i in ids
    ]
    if calc:
        assertions.append({**calc, "kind": "market_close_calculation", "receipt_id": receipt["receipt_id"]})
    return {
        "status": status,
        "conclusion": conclusion.strip(),
        "changes": [],
        "claims": claims,
        "calculations": calc_ids,
        "gaps": pending,
        "alternative_explanations": [
            "Two session closes measure a price change. Company-specific and market-wide explanations require additional observations."
        ],
        "next_steps": [
            "Check a benchmark on matching session dates and adjustment basis."
            if calc
            else "Import the named sessions and their currency, regular-close, source, delay and adjustment metadata on the research methods page."
        ],
    }, assertions


def execute(context, call, runtime):
    from .executor import Result

    calls = []
    receipt = call("price_context", {})
    calls.append(("price_context", receipt))
    ids = receipt["data"]["evidence_ids"]
    for ref in ids:
        calls.append(("get_evidence", call("get_evidence", {"id": ref})))
    pending = calls[-1][1]["outstanding_gap_ids"]
    selection = {
        "status": ("partial" if pending else "complete") if ids else "blocked",
        "gaps": pending,
        "passage_ids": ids,
        "calculations": [receipt["receipt_id"]] if receipt["data"]["calculation"] else [],
    }
    body, _ = render(context, selection, calls)
    return Result(body, runtime)
