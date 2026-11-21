"""Dated publisher-headline lookup for a resolved issuer's saved feed."""

import json
import re
from urllib.parse import urlsplit

from . import issuer_news
from .db import instant
from .executor import ExecutorError, Result

METHOD = "issuer_announcement_lookup.v1"
MAX_HEADLINES = 5
_ISSUER = r"(?:nvidia(?: corporation)?|nvda)(?:'s)?"
_COUNT = r"(?:one|two|three|four|five|[1-5])"
_SUBJECT = r"(?:press releases?|news releases?|headlines?|announcements?)"
_EDITION = r"(?:saved|retained|captured|stored)"
_FEED = (
    rf"(?:(?:the|our|my) )?(?:(?:{_EDITION} )?(?:{_ISSUER} )?|{_ISSUER} {_EDITION} )"
    rf"(?:newsroom |press release |issuer )?feed"
)
_QUALIFIER = rf"(?:(?:the|a|dated|(?:most )?recent|latest|newest|{_EDITION}|(?:up to )?{_COUNT}) )*"
_LIST = re.compile(
    rf"(?:list|show(?: me)?|give me|which|what(?: are)?) "
    rf"{_QUALIFIER}(?:{_ISSUER} )?(?:newsroom |issuer )?(?P<subject>{_SUBJECT})"
    rf"(?: (?:from|for|by) {_ISSUER})?(?: (?:are |were )?(?:in|from|on) {_FEED})?"
)
_ANNOUNCED = re.compile(rf"what did {_ISSUER} announce in {_FEED}")


def _question(question):
    return " ".join(question.casefold().strip().rstrip("?.").replace("’", "'").split())


def accepts(question, listing):
    if not isinstance(question, str) or listing.get("cik") != "0001045810":
        return False
    text = _question(question)
    if not (_LIST.fullmatch(text) or _ANNOUNCED.fullmatch(text)):
        return False
    if not re.search(rf"\b(?:{_ISSUER}|{_EDITION}|newsroom|feed)\b", text):
        return False
    if re.search(r"\b(?:recent|latest|newest)\b", text) and not re.search(
        rf"\b{_EDITION}\b", text
    ):
        return False
    return len(re.findall(rf"\b{_COUNT}\b", text)) <= 1


def _limit(question):
    text = _question(question)
    match = re.search(rf"\b{_COUNT}\b", text)
    if not match:
        subject = _LIST.fullmatch(text)
        return 1 if subject and not subject["subject"].endswith("s") else MAX_HEADLINES
    count = match.group()
    return (
        int(count)
        if count.isdigit()
        else ("one", "two", "three", "four", "five").index(count) + 1
    )


def _entry(passage, context):
    if (
        passage.get("origin") != "issuer_news"
        or passage.get("instrument_id") != context["instrument"]["id"]
        or passage.get("source_url") != f"https://{issuer_news.HOST}{issuer_news.PATH}"
        or passage.get("retention") != "rss_metadata_and_hash"
        or passage.get("financial")
        or passage.get("fixture")
    ):
        raise ValueError(
            "Announcement citation requires the assigned public newsroom projection."
        )
    meta = json.loads(passage["locator"])
    if not isinstance(meta, dict) or set(meta) != {"link", "published_at"}:
        raise ValueError("Invalid saved newsroom item metadata.")
    url = urlsplit(meta["link"])
    if (
        url.scheme != "https"
        or url.netloc != issuer_news.HOST
        or url.query
        or url.fragment
        or not re.fullmatch(r"/news/[a-zA-Z0-9._~%-]+", url.path)
    ):
        raise ValueError(
            "Announcement requires the original publisher's checked article link."
        )
    published = instant(meta["published_at"])
    available = instant(passage["available_at"])
    if (
        published != meta["published_at"]
        or published > available
        or (context.get("cutoff") and available > instant(context["cutoff"]))
    ):
        raise ValueError(
            "Announcement is outside the eligible publication or capture interval."
        )
    if (
        not isinstance(passage["text"], str)
        or not 1 <= len(passage["text"].strip()) <= 512
    ):
        raise ValueError("Announcement requires the full retained headline.")
    return {
        "kind": "issuer_announcement",
        "passage_id": passage["id"],
        "document_id": passage["document_id"],
        "instrument_id": passage["instrument_id"],
        "headline": passage["text"],
        "published_at": published,
        "source_url": meta["link"],
        "captured_at": instant(passage["received_at"]),
    }


def _catalog(context, calls):
    pages = []
    for name, out in calls:
        if name == "search_evidence":
            pages = [out["data"]]
        elif name == "next_evidence_page":
            pages.append(out["data"])
    if not pages or pages[-1]["has_more"]:
        raise ValueError("The saved feed catalogue was not fully read.")
    by_link = {}
    for index, page in enumerate(pages, 1):
        if (
            page["page"] != index
            or page["evidence_commit_seq"] != pages[0]["evidence_commit_seq"]
        ):
            raise ValueError(
                "Newsroom pages must share the same retained search boundary."
            )
        for row in page["passages"]:
            entry = _entry(row, context)
            if entry["source_url"] in by_link and entry != by_link[entry["source_url"]]:
                raise ValueError("Conflicting entries in the saved newsroom edition.")
            by_link[entry["source_url"]] = entry
    entries = sorted(
        by_link.values(),
        key=lambda entry: (entry["published_at"], entry["source_url"]),
        reverse=True,
    )
    if (
        len({item["document_id"] for item in entries}) > 1
        or len(entries) > issuer_news.MAX_ITEMS
    ):
        raise ValueError(
            "Expected the bounded contents of a single eligible newsroom edition."
        )
    return entries


def render(context, selection, calls):
    if context["method"] != METHOD or not accepts(
        context["question"], context["instrument"]
    ):
        raise ValueError("This method supports dated NVIDIA Newsroom headline lookups.")
    captures = [
        out
        for name, out in calls
        if name == "capture_public" and out["data"].get("provider") == "issuer_news"
    ]
    if not captures:
        raise ValueError("Missing the scoped newsroom acquisition receipt.")
    entries = _catalog(context, calls)
    question = _question(context["question"])
    limit = _limit(question)
    chosen = entries[:limit]
    if (
        chosen
        and not context.get("cutoff")
        and captures[-1]["status"] == "ok"
        and chosen[0]["document_id"] != captures[-1]["data"]["document_id"]
    ):
        raise ValueError(
            "The researched edition differs from the successful newsroom check."
        )
    if selection["calculations"] or selection["passage_ids"] != [
        item["passage_id"] for item in chosen
    ]:
        raise ValueError(
            "Select the dated headlines in publication order from the saved feed."
        )
    read = {
        out["data"]["id"]: _entry(out["data"], context)
        for name, out in calls
        if name == "get_evidence" and out["status"] == "ok"
    }
    if any(read.get(item["passage_id"]) != item for item in chosen):
        raise ValueError(
            "Retrieve each exact newsroom headline and its publication metadata."
        )
    outstanding = calls[-1][1]["outstanding_gap_ids"]
    status = ("partial" if outstanding else "complete") if chosen else "blocked"
    shortfall = (
        bool(re.search(rf"\b{_COUNT}\b", question))
        and "up to " not in question
        and len(entries) < limit
    )
    if shortfall and not outstanding:
        raise ValueError(
            f"The saved feed has {len(entries)} eligible headlines. Ask for up to {limit} to "
            "review the available entries."
        )
    if not chosen and not outstanding:
        raise ValueError(
            "No eligible saved newsroom edition was found for the assigned information cutoff."
        )
    if selection["gaps"] != outstanding or selection["status"] != status:
        raise ValueError(
            "The newsroom assessment must disclose the retained coverage gaps."
        )

    if not chosen:
        conclusion = "No eligible NVIDIA Newsroom headlines were available in the saved feed for this question."
    else:
        noun = "headline" if len(entries) == 1 else "headlines"
        conclusion = (
            f"The NVIDIA Newsroom feed edition captured at {chosen[0]['captured_at']} "
            f"contains {len(entries)} eligible {noun}."
        )
        if len(chosen) < len(entries):
            conclusion += f" This sample shows the {len(chosen)} most recent by publisher timestamp."
    if captures[-1]["status"] != "ok":
        conclusion += " The newsroom source check was unsuccessful."
    if shortfall:
        conclusion += f" The question requested {limit} headlines and only {len(entries)} were available."
    if context.get("cutoff"):
        conclusion += f" The research information cutoff was {context['cutoff']}."
    return {
        "status": status,
        "conclusion": conclusion,
        "changes": [
            f"{item['published_at']} · NVIDIA Newsroom published “{item['headline']}”."
            for item in chosen
        ],
        "claims": [
            {
                "type": "issuer_statement",
                "text": item["headline"],
                "evidence_refs": [item["passage_id"]],
            }
            for item in chosen
        ],
        "calculations": [],
        "gaps": list(outstanding),
        "alternative_explanations": [
            (
                "An issuer headline establishes what the newsroom published. Article details, subsequent developments "
                "and market effects require separate evidence."
            )
        ],
        "next_steps": [
            "Open the linked publisher announcements for the full disclosures."
            if chosen
            else "Review the source check and retry when an eligible newsroom edition is available."
        ],
    }, chosen


def execute(context, call, runtime):
    if context["method"] != METHOD or not accepts(
        context["question"], context["instrument"]
    ):
        raise ExecutorError(
            "question_scope",
            "Choose a saved-feed NVIDIA press-release or headline question.",
        )
    calls = []

    def check(name, args):
        output = call(name, args)
        calls.append((name, output))
        return output

    page = None
    if runtime.get("research_plan") != "issuer_disclosure":
        page = check("search_evidence", {})
    capture = check("capture_public", {"provider": "issuer_news"})
    if page is None or (
        capture["status"] == "ok"
        and not any(
            p["document_id"] == capture["data"]["document_id"]
            for p in page["data"]["passages"]
        )
    ):
        page = check("search_evidence", {})
    # Up to 40 items at 24 per page in the fixed-format named feed.
    if page["data"]["has_more"]:
        check("next_evidence_page", {"cursor": page["data"]["next_cursor"]})
    chosen = _catalog(context, calls)[: _limit(context["question"])]
    ids = [item["passage_id"] for item in chosen]
    for passage_id in ids:
        check("get_evidence", {"id": passage_id})
    pending = calls[-1][1]["outstanding_gap_ids"]
    if not ids and not pending:
        raise ExecutorError(
            "issuer_feed_unavailable",
            "No eligible saved issuer feed was available for this cutoff.",
        )
    status = ("partial" if pending else "complete") if ids else "blocked"
    body, _ = render(
        context,
        {"status": status, "passage_ids": ids, "gaps": pending, "calculations": []},
        calls,
    )
    return Result(body, runtime)
