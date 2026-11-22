"""Verify one operator-selected passage against an approved issuer document."""

import hashlib
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree import ElementTree

from . import evidence, filing_passages, providers, sources_calendar, universe
from .db import instant, is_fixture, now, write

TRANSCRIPT_URL = "https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/TranscriptQandAFY27Q1.docx"
MSFT_RELEASE_URL = "https://" + sources_calendar.MSFT_HOST + sources_calendar.ROUTES["msft_release"][1]
NVDA_RELEASE_URL = "https://" + providers.ISSUER_HOST + providers.ISSUER_PATH


def _normal(value):
    return " ".join(value.split())


def sources(db, instrument_id):
    listing = universe.instrument(db, instrument_id)
    output = {}
    if listing["cik"] == "0000789019":
        output[TRANSCRIPT_URL] = (
            "Microsoft FY27 Q1 earnings call transcript",
            "msft_transcript",
            "2026-10-28",
        )
        output[MSFT_RELEASE_URL] = ("Microsoft FY27 Q1 earnings release", "msft_excerpt", "2026-10-28")
    elif listing["cik"] == "0001045810":
        output[NVDA_RELEASE_URL] = ("NVIDIA Q2 FY25 earnings release", "nvda_excerpt", "2024-08-28")
        feed = db.execute(
            """SELECT p.locator,p.text FROM evidence_passages p JOIN documents d ON d.id=p.document_id
               WHERE d.instrument_id=? AND d.fixture=? AND d.origin='issuer_news' AND d.source_url=?
               ORDER BY d.commit_seq DESC,p.locator LIMIT 400""",
            (instrument_id, int(is_fixture(db)), "https://nvidianews.nvidia.com/cats/press_release.xml"),
        )
        for row in feed:
            meta = json.loads(row["locator"])
            link = meta["link"]
            if re.fullmatch(r"https://nvidianews\.nvidia\.com/news/[A-Za-z0-9_-]+", link):
                output.setdefault(link, (row["text"], "nvda_excerpt", instant(meta["published_at"])))
    if listing["cik"]:
        archives = db.execute(
            """SELECT title,source_url,published_at FROM documents WHERE instrument_id=? AND fixture=?
               AND origin='sec_filing' AND retention='full' ORDER BY commit_seq DESC LIMIT 32""",
            (instrument_id, int(is_fixture(db))),
        )
        prefix = f"https://www.sec.gov/Archives/edgar/data/{int(listing['cik'])}/"
        for row in archives:
            if re.fullmatch(re.escape(prefix) + r"\d{18}/[\w-][\w.-]{0,120}\.html?", row["source_url"]):
                output.setdefault(row["source_url"], (row["title"], "retained_filing", row["published_at"]))
    return [{"url": url, "title": v[0], "route": v[1], "published_at": v[2]} for url, v in output.items()]


class _Paragraphs(HTMLParser):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.path = []
        self.current = None
        self.paragraphs = []
        self.regions = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        parent = self.path[-1][1] if self.path else "outside"
        marker = (
            values.get("id") == "pressreleasecontent"
            if self.kind == "msft_excerpt"
            else "article-body" in (values.get("class") or "").split()
        )
        state = "article" if marker else parent
        if marker:
            self.regions += 1
        if (
            parent == "hidden"
            or tag in ("script", "style", "header", "nav", "footer", "noscript")
            or "hidden" in values
            or values.get("aria-hidden") == "true"
        ):
            state = "hidden"
        if tag == "br" and state == "article" and self.current is not None:
            self.current.append(" ")
        if tag in (
            "br",
            "hr",
            "img",
            "meta",
            "link",
            "input",
            "source",
            "wbr",
            "area",
            "base",
            "embed",
            "col",
            "param",
            "track",
        ):
            return
        self.path.append((tag, state))
        if len(self.path)>512:
            raise ValueError("The issuer page exceeds the supported disclosure nesting.")
        if state == "article" and tag in ("p", "li", "blockquote", "td"):
            self.flush()
            self.current = []

    def flush(self):
        if self.current:
            value = _normal("".join(self.current))
            if value:
                self.paragraphs.append(value)
        self.current = None

    def handle_endtag(self, tag):
        for i in range(len(self.path) - 1, -1, -1):
            if self.path[i][0] == tag:
                if any(t in ("p", "li", "blockquote", "td") and s == "article" for t, s in self.path[i:]):
                    self.flush()
                del self.path[i:]
                break

    def handle_data(self, data):
        if self.current is not None and self.path and self.path[-1][1] == "article":
            self.current.append(data)


def _contents(raw, route, listing, source_url):
    if route == "retained_filing":
        p = filing_passages._Blocks()
        p.feed(raw.decode("utf-8-sig"))
        p.flush()
        if set(p.identities) != {listing["cik"]}:
            raise ValueError("The saved filing identifies a different registrant.")
        enabled = False
        blocks = []
        for line in p.blocks:
            heading = re.match(r"^Item\s+(\d\.\d\d)\b", line, re.IGNORECASE)
            if heading:
                enabled = heading[1] in filing_passages.ITEMS
            elif re.match(r"^signatures?\b", line, re.IGNORECASE):
                enabled = False
            elif enabled:
                blocks.append(line)
        return blocks
    if route == "msft_transcript":
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                documents = [item for item in archive.infolist() if item.filename == "word/document.xml"]
                if len(documents) != 1 or len(archive.infolist()) > 256 or documents[0].file_size > 1_600_000:
                    raise ValueError("Unexpected transcript document structure.")
                with archive.open(documents[0]) as stream:
                    data = stream.read(1_600_001)
            if (
                len(data) > 1_600_000
                or b"\0" in data
                or re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", data, re.IGNORECASE)
            ):
                raise ValueError("Invalid transcript document XML.")
            root = ElementTree.fromstring(data)
        except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError, NotImplementedError):
            raise ValueError("Unable to verify the issuer transcript.") from None
        paragraphs = [
            _normal("".join(t.text or "" for t in p.findall(".//w:t", ns)))
            for p in root.findall("w:body/w:p", ns)
        ]
        if (
            not paragraphs
            or paragraphs[0] != "Microsoft FY27 First Quarter Earnings Conference Call"
            or "Wednesday October 28, 2026" not in paragraphs[:5]
        ):
            raise ValueError("The document is not the named Microsoft earnings call.")
        return paragraphs[3:]
    p = _Paragraphs(route)
    text = raw.decode("utf-8-sig")
    p.feed(text)
    p.close()
    p.flush()
    if p.regions != 1 or (route == "msft_excerpt" and "October 28, 2026" not in " ".join(p.paragraphs)):
        raise ValueError("The issuer page lacks an unambiguous disclosure body.")
    if (
        source_url == NVDA_RELEASE_URL
        and "NVIDIA Announces Financial Results for Second Quarter Fiscal 2025" not in text
    ):
        raise ValueError("The historical NVIDIA release identity differs.")
    return p.paragraphs


def _locate(blocks, quote):
    count = 0
    index = None
    for i, block in enumerate(blocks):
        offset=block.find(quote)
        if offset>=0:
            index = i
            count+=1
            if block.find(quote,offset+1)>=0 or count>1:
                raise ValueError("Select an exact, unique excerpt from one issuer paragraph.")
    if count != 1:
        raise ValueError("Select an exact, unique excerpt from one issuer paragraph.")
    return f"Disclosure body / paragraph {index + 1} / normalized exact excerpt"


def capture(db, instrument_id, source_url, quote):
    listing = universe.instrument(db, instrument_id)
    selected = next((s for s in sources(db, instrument_id) if s["url"] == source_url), None)
    if not selected:
        raise ValueError("Select an approved issuer document for this listing.")
    if not isinstance(quote, str) or len(quote) > 1200:
        raise ValueError("Choose a short, exact excerpt.")
    quote = _normal(quote)
    if not 20 <= len(quote) <= 400:
        raise ValueError("Use between 20 and 400 normalized characters.")
    route = selected["route"]
    # Separate excerpt streams preserve their own immutable commit boundary even
    # when several different selections come from the very same publisher bytes.
    origin = route + "." + hashlib.sha256(quote.encode()).hexdigest()
    stamp = now()
    cached = db.execute(
        """SELECT p.id FROM documents d JOIN evidence_passages p ON p.document_id=d.id
        WHERE d.instrument_id=? AND d.fixture=? AND d.source_url=? AND d.origin=?
        AND julianday(?) - julianday(d.received_at) BETWEEN 0 AND 1.0/24 ORDER BY d.commit_seq DESC LIMIT 1""",
        (instrument_id, int(is_fixture(db)), source_url, origin, stamp),
    ).fetchone()
    if cached:
        return cached["id"]
    receipt = None
    url = urlsplit(source_url)
    stored = db.execute(
        """SELECT id FROM documents WHERE instrument_id=? AND fixture=? AND source_url=?
            AND retention='full' AND (origin IN ('sec_filing','issuer','msft_release','msft_transcript')
            OR (fixture=1 AND origin='synthetic'))
            ORDER BY commit_seq DESC LIMIT 1""",
        (instrument_id, int(is_fixture(db)), source_url),
    ).fetchone()
    if not stored:
        if is_fixture(db) or route == "retained_filing":
            raise ValueError("No eligible, complete source version is retained in this workspace.")
        claim = evidence.claim_public(db, instrument_id, route, url.hostname)
        if not claim.get("receipt_id"):
            raise ValueError(claim["message"])
        receipt = claim["receipt_id"]
    try:
        raw = (
            evidence.document_bytes(db, instrument_id, stored["id"])
            if stored
            else providers._fetch(url.hostname, url.path, limit=evidence.MAX_DOCUMENT_BYTES)
        )
        locator = _locate(_contents(raw, route, listing, source_url), quote)
        received = now()
        staged = evidence._stage(db, "verified_excerpt_and_hash", raw)
        with write(db) as seq:
            universe.instrument(db, instrument_id)
            doc = evidence._save(
                db,
                seq,
                instrument_id,
                origin,
                source_url,
                selected["title"],
                staged,
                [(locator, quote, received, None)],
                received,
                published=selected["published_at"],
                precision="publisher date"
                if len(selected["published_at"] or "") == 10
                else "publisher timestamp",
                retention="verified_excerpt_and_hash",
                fixture=is_fixture(db),
            )
            result = db.execute(
                "SELECT id FROM evidence_passages WHERE document_id=? AND locator=?", (doc, locator)
            ).fetchone()["id"]
            if receipt:
                db.execute(
                    "UPDATE source_checks SET status='ok',detail=?,finished_at=?,document_id=?,commit_seq=? WHERE id=?",
                    ("Verified one selected issuer excerpt.", received, doc, seq, receipt),
                )
        return result
    except (OSError, ValueError, UnicodeError) as exc:
        if receipt:
            status = exc.status if isinstance(exc, providers.SourceError) else "error"
            retry = exc.retry_at if isinstance(exc, providers.SourceError) else None
            with write(db) as seq:
                db.execute(
                    "UPDATE source_checks SET status=?,detail=?,finished_at=?,retry_at=?,commit_seq=? WHERE id=?",
                    (
                        status,
                        "The selected issuer excerpt could not be verified.",
                        now(),
                        retry,
                        seq,
                        receipt,
                    ),
                )
        raise ValueError(str(exc)) from None
