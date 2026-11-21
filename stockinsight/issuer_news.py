"""The metadata projection of NVIDIA Newsroom's named public press-release feed."""

import json
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

from . import events
from .db import instant

PATH = "/cats/press_release.xml"
HOST = "nvidianews.nvidia.com"
MAX_BYTES = 1_200_000
MAX_ITEMS = 40


def rows(raw, received):
    if (
        len(raw) > MAX_BYTES
        or b"\x00" in raw
        or re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", raw, re.IGNORECASE)
    ):
        raise ValueError("Unsupported RSS format or feed size.")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise ValueError("Invalid issuer feed XML.") from None
    if (
        root.tag != "rss"
        or root.findtext("channel/title") != "Press Release - NVIDIA Newsroom"
    ):
        raise ValueError("Unexpected issuer feed identity.")
    items = {}
    for node in root.findall("channel/item")[:MAX_ITEMS]:
        title = " ".join((node.findtext("title") or "").split())
        link = (node.findtext("link") or "").strip()
        url = urlsplit(link)
        if not (
            0 < len(title) <= 512
            and len(link) <= 512
            and url.scheme == "https"
            and url.netloc == HOST
            and re.fullmatch(r"/news/[a-zA-Z0-9._~%-]+", url.path)
            and not url.query
            and not url.fragment
        ):
            # Some issuer feeds also syndicate external links. Only retain local newsroom entries.
            continue
        try:
            observed = parsedate_to_datetime(node.findtext("pubDate") or "")
            if observed.tzinfo is None:
                raise ValueError
            published = instant(observed.isoformat())
        except (TypeError, ValueError, OverflowError):
            raise ValueError(
                "Issuer feed item requires an explicit publication time and offset."
            ) from None
        if published > instant(received):
            continue
        item = (title, published)
        if link in items and items[link] != item:
            raise ValueError("Conflicting metadata for an issuer announcement.")
        items[link] = item
    return [
        (
            json.dumps({"link": link, "published_at": published}, sort_keys=True),
            title,
            received,
            None,
        )
        for link, (title, published) in items.items()
    ]


def observe(db, instrument_id, doc_id):
    for item in db.execute(
        """SELECT p.id,p.locator,p.text FROM evidence_passages p JOIN documents d ON d.id=p.document_id
           WHERE d.instrument_id=? AND d.id=? AND d.origin='issuer_news' ORDER BY p.id""",
        (instrument_id, doc_id),
    ):
        meta = json.loads(item["locator"])
        previous = db.execute(
            """SELECT e.id,e.occurred_at,p.text FROM event_versions e JOIN evidence_passages p ON p.id=e.source_ref
               WHERE e.instrument_id=? AND e.kind='issuer_announcement' AND
                  CASE WHEN json_valid(p.locator) THEN json_extract(p.locator,'$.link') END=?
               ORDER BY e.commit_seq DESC LIMIT 1""",
            (instrument_id, meta["link"]),
        ).fetchone()
        if previous and (previous["occurred_at"], previous["text"]) == (
            meta["published_at"],
            item["text"],
        ):
            continue
        events.append_event(
            db,
            instrument_id,
            kind="issuer_announcement",
            state="occurred",
            source_ref=item["id"],
            precision="instant",
            occurred_at=meta["published_at"],
            supersedes=previous["id"] if previous else None,
        )
