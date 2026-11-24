"""Resolve a bounded, named SEC submissions entry and retain passages from its filed 8-K."""

import hashlib
import json
import re
import time
from datetime import date
from html.parser import HTMLParser

from . import providers
from .db import now

ARCHIVE_HOST = "www.sec.gov"
ITEMS = {"1.01", "2.02", "5.07", "7.01", "8.01"}
INDEX_LIMIT = 1_800_000
FILING_LIMIT = 2_000_000


def select(raw, cik, received):
    obj = json.loads(raw)
    if not isinstance(obj, dict) or str(obj.get("cik")).zfill(10) != cik:
        raise ValueError("Unexpected SEC submissions entity.")
    file = obj["filings"]["recent"]
    keys = ("form", "items", "accessionNumber", "filingDate", "primaryDocument")
    if any(not isinstance(file[k], list) for k in keys) or len({len(file[k]) for k in keys}) != 1:
        raise ValueError("Invalid SEC submissions index.")
    candidates = []
    for form, items, accession, day, name in zip(*(file[k][:250] for k in keys)):
        if form not in ("8-K", "8-K/A") or not (set(re.findall(r"\b\d\.\d\d\b", items)) & ITEMS):
            continue
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(
            r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,118}\.html?", name, re.IGNORECASE
        ):
            raise ValueError("Unrecognized SEC filing identifier or primary document.")
        if date.fromisoformat(day).isoformat() != day or date.fromisoformat(day) > date.fromisoformat(
            received[:10]
        ):
            continue
        candidates.append((day, accession, name))
    if not candidates:
        raise providers.SourceError(
            "partial", "No qualifying 8-K items in the 250 newest submission records."
        )
    return max(candidates)


class _Blocks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.text = []
        self.cik = False
        self.identities = []
        self.ignored = 0

    def flush(self):
        text = " ".join("".join(self.text).split())
        if text:
            self.blocks.append(text)
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignored += 1
        if self.ignored:
            return
        if tag in ("p", "div", "tr"):
            self.flush()
        elif tag in ("br", "td", "th"):
            self.text.append(" ")
        if tag == "ix:nonnumeric" and dict(attrs).get("name", "").lower() == "dei:entitycentralindexkey":
            self.cik = True

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignored:
            self.ignored -= 1
        elif not self.ignored and tag in ("p", "div", "tr"):
            self.flush()
        if tag == "ix:nonnumeric":
            self.cik = False

    def handle_data(self, data):
        if self.cik and data.strip():
            self.identities.append(data.strip().zfill(10))
        if not self.ignored:
            self.text.append(data)


def passages(raw, cik, filing, index_hash, received):
    parser = _Blocks()
    parser.feed(raw.decode("utf-8-sig"))
    parser.flush()
    if set(parser.identities) != {cik}:
        raise ValueError("The primary filing does not identify exactly the expected registrant.")
    day, accession, _ = filing
    active = None
    rows = []
    for i, block in enumerate(parser.blocks):
        heading = re.match(r"^Item\s+(\d\.\d\d)\b", block, re.IGNORECASE)
        if heading:
            active = heading[1] if heading[1] in ITEMS else None
            continue
        if re.match(r"^signatures?\b", block, re.IGNORECASE):
            active = None
        if not active or len(block) < 40 or len(block) > 2400:
            continue
        locator = json.dumps(
            {
                "accession": accession,
                "filing_date": day,
                "item": active,
                "block": i,
                "index_hash": index_hash,
            },
            sort_keys=True,
        )
        rows.append((locator, block, received, None))
        if len(rows) >= 6:
            break
    if not rows:
        raise providers.SourceError(
            "partial", "No qualifying narrative paragraphs in the selected filed items."
        )
    return rows


def fetch(index_path, cik, headers):
    index = providers._fetch(providers.SEC_HOST, index_path, headers=headers, limit=INDEX_LIMIT)
    filing = select(index, cik, now())
    day, accession, name = filing
    path = f"/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{name}"
    # These are two separately published resources under one SEC fair-access limit.
    time.sleep(1.05)
    document = providers._fetch(ARCHIVE_HOST, path, headers=headers, limit=FILING_LIMIT)
    received = now()
    rows = passages(document, cik, filing, hashlib.sha256(index).hexdigest(), received)
    return document, rows, received, "https://" + ARCHIVE_HOST + path, day
