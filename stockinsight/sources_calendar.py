"""Official issuer and central-bank source projections for the personal watchlist."""

import calendar
import itertools
import json
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime
from html import unescape
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from . import bls_calendar, events
from .db import instant, is_fixture, write

SCHEMA = """
CREATE TABLE calendar_reports (
    instrument_id TEXT NOT NULL REFERENCES instruments, provider TEXT NOT NULL, subject TEXT NOT NULL,
    origin_group TEXT NOT NULL, source_ref TEXT NOT NULL REFERENCES evidence_passages,
    event_id TEXT, signature TEXT NOT NULL, title TEXT NOT NULL, relevance TEXT NOT NULL,
    document_seq INTEGER NOT NULL REFERENCES commits, commit_seq INTEGER NOT NULL REFERENCES commits,
    PRIMARY KEY(instrument_id,provider,subject,document_seq)
);
CREATE INDEX calendar_subject ON calendar_reports(instrument_id,subject,document_seq);
CREATE TABLE source_retries (
    occurrence_id TEXT PRIMARY KEY REFERENCES monitor_occurrences,
    original_id TEXT NOT NULL REFERENCES monitor_occurrences,
    attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 2), UNIQUE(original_id,attempt)
);
CREATE TABLE source_comparisons (
    id INTEGER PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments,
    left_ref TEXT NOT NULL REFERENCES evidence_passages, right_ref TEXT NOT NULL REFERENCES evidence_passages,
    judgment TEXT NOT NULL CHECK(judgment IN ('same_account','disagree','different_subjects')),
    reason TEXT NOT NULL, observed_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits,
    UNIQUE(left_ref,right_ref,judgment,reason)
);
"""

MICROSOFT = "0000789019"
NVIDIA = "0001045810"
FED_HOST = "www.federalreserve.gov"
MSFT_HOST = "www.microsoft.com"
CMA_HOST = "www.gov.uk"
CMA_PATH = "/api/search.json?filter_organisations=competition-and-markets-authority&filter_format=press_release&order=-public_timestamp&count=20&fields=title,link,public_timestamp,organisations&q="
PACIFIC = "America/Los_Angeles"
FED_TZ = "America/New_York"
ROUTES = {
    "msft_calendar": (MSFT_HOST, "/en-us/investor/annual-meeting", "Microsoft annual shareholder meeting"),
    "msft_calendar_faq": (MSFT_HOST, "/en-us/investor/faq", "Microsoft Investor Relations meeting FAQ"),
    "msft_release": (
        MSFT_HOST,
        "/en-us/investor/earnings/fy-2027-q1/press-release-webcast",
        "Microsoft FY27 Q1 earnings release",
    ),
    "fed_calendar": (FED_HOST, "/monetarypolicy/fomccalendars.htm", "Federal Reserve FOMC meeting calendar"),
    "bls_calendar": (bls_calendar.HOST, bls_calendar.PATH, "BLS CPI and employment release calendar"),
    "cma_news": (CMA_HOST, CMA_PATH, "UK Competition and Markets Authority notices"),
}
CALENDARS = {"msft_calendar", "msft_calendar_faq", "fed_calendar", "bls_calendar"}
ROUTE_LABELS = {
    "issuer_news": "NVIDIA Newsroom press releases",
    "issuer": "NVIDIA historical issuer release",
    "sec": "SEC quarterly revenue",
    "sec_filing": "SEC filed 8-K passages",
    **{key: row[2] for key, row in ROUTES.items()},
}


def eligible(listing, route):
    cik = listing.get("cik")
    if route in ("issuer", "issuer_news"):
        return cik == NVIDIA
    if route in ("msft_calendar", "msft_calendar_faq", "msft_release"):
        return cik == MICROSOFT
    if route == "cma_news":
        return cik in (MICROSOFT, NVIDIA)
    if route in ("fed_calendar", "bls_calendar"):
        return bool(
            (cik or listing.get("resolution_status") == "identified_listing")
            and listing.get("currency") == "USD"
            and listing.get("listing_exchange")
            in ("NASDAQ", "NYSE", "AMEX", "NYSEAMERICAN", "ARCA", "NYSEARCA", "BATS", "CBOE")
        )
    return route in ("sec", "sec_filing") and bool(cik)


def recommended(listing):
    from . import providers

    cadence = {
        "issuer_news": 240,
        "msft_calendar": 1440,
        "msft_release": 10080,
        "fed_calendar": 1440,
        "cma_news": 1440,
    }
    if providers.sec_contact():
        cadence["sec"] = 1440
        cadence["sec_filing"] = 1440
    return {route: minutes for route, minutes in cadence.items() if eligible(listing, route)}


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.current = []
        elif tag == "br" and self.current is not None:
            self.current.append(" ")

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.current is not None:
            self.paragraphs.append(" ".join("".join(self.current).split()))
            self.current = None


def _pacific_time(day, hour, minute, suffix):
    if not 1 <= hour <= 12 or not 0 <= minute < 60:
        raise ValueError("Invalid publisher time.")
    local = datetime.combine(day, datetime.min.time()).replace(
        hour=hour % 12 + 12 * (suffix == "pm"), minute=minute
    )
    zone = ZoneInfo(PACIFIC)
    first, other = local.replace(tzinfo=zone), local.replace(tzinfo=zone, fold=1)
    if (
        first.utcoffset() != other.utcoffset()
        or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local
    ):
        raise ValueError("The issuer supplied a nonexistent or ambiguous local time.")
    return instant(first.isoformat())


def _calendar_row(meta, text, received):
    return json.dumps(meta, sort_keys=True), text, received, None


def _msft_calendar(raw, received):
    parser = _Paragraphs()
    parser.feed(raw)
    rows = {}
    for text in parser.paragraphs:
        year = re.search(r"\b(20\d{2}) annual shareholders[’']? meeting\b", text, re.IGNORECASE)
        if not year or len(text) > 500:
            continue
        if not re.search(
            r"\b(will be|scheduled|tentative|postponed|cancell?ed|yet to be announced)\b", text, re.IGNORECASE
        ):
            continue
        subject = "msft:annual:" + year[1]
        state = "confirmed"
        for flag, pattern in (
            ("cancelled", r"\bcancell?ed\b"),
            ("postponed", r"\bpostponed\b"),
            ("tentative", r"\btentative(?:ly)?\b"),
            ("unknown", r"yet to be announced"),
        ):
            if re.search(pattern, text, re.IGNORECASE):
                state = flag
                break
        start = None
        precision = "unknown"
        date_matches = re.findall(r"\b([A-Z][a-z]+ \d{1,2}, 20\d{2})\b", text)
        if state not in ("cancelled", "unknown") and date_matches:
            if len(date_matches) != 1:
                raise ValueError("Ambiguous issuer calendar date.")
            day = datetime.strptime(date_matches[0], "%B %d, %Y").date()
            start, precision = day.isoformat(), "day"
            clock = re.search(
                r"\bat (\d{1,2}):(\d\d)\s*([ap])\.?m\.?\s*(?:PT|Pacific Time)\b", text, re.IGNORECASE
            )
            if clock:
                start = _pacific_time(day, int(clock[1]), int(clock[2]), clock[3].lower() + "m")
                precision = "instant"
            elif re.search(r"\d:\d{2}", text):
                raise ValueError("Unrecognized issuer time or timezone.")
        if start is None and state in ("confirmed", "tentative"):
            raise ValueError("Meeting date unavailable.")
        meta = {
            "subject": subject,
            "kind": "shareholder_meeting",
            "title": year[1] + " Microsoft annual shareholder meeting",
            "state": state,
            "precision": precision,
            "start": start,
            "end": None,
            "timezone": PACIFIC,
            "origin": "Microsoft Investor Relations",
            "relevance": "Direct issuer governance event. Review the proxy agenda and voting outcomes for Microsoft.",
        }
        row = _calendar_row(meta, text, received)
        if subject in rows and rows[subject] != row:
            raise ValueError("Conflicting issuer calendar entries in one edition.")
        rows[subject] = row
    return list(rows.values())


def _plain(raw):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def _fed_calendar(raw, received):
    year_now = int(received[:4])
    month_numbers = {m.casefold(): i for i, m in enumerate(calendar.month_name) if i}
    month_numbers.update({m.casefold(): i for i, m in enumerate(calendar.month_abbr) if i})
    sections = re.split(r"\b(20\d{2}) FOMC Meetings\s*</a>", raw, flags=re.IGNORECASE)
    rows = []
    for year_text, section in zip(sections[1::2], sections[2::2]):
        year = int(year_text)
        if not year_now <= year <= year_now + 1:
            continue
        listings = re.findall(
            r'class="[^"]*\bfomc-meeting__month\b[^"]*"[^>]*>(.*?)</div>\s*<div class="[^"]*\bfomc-meeting__date\b[^"]*"[^>]*>(.*?)</div>(.*?)(?=class="[^"]*\bfomc-meeting__month\b|\Z)',
            section,
            re.DOTALL | re.IGNORECASE,
        )
        periods = []
        for month_html, day_html, body in listings:
            month, day = _plain(month_html), _plain(day_html).strip("* ")
            if "unscheduled" in (month + " " + day).casefold() or "conference call" in day.casefold():
                continue
            names = [x.strip().casefold() for x in re.split(r"[/–-]", month)]
            days = re.fullmatch(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?", day)
            if not days or not 1 <= len(names) <= 2 or any(n not in month_numbers for n in names):
                raise ValueError("Unrecognized regular FOMC meeting date.")
            begin = date(year, month_numbers[names[0]], int(days[1]))
            end = date(year, month_numbers[names[-1]], int(days[2] or days[1]))
            if not 0 <= (end - begin).days <= 3:
                raise ValueError("Unexpected FOMC meeting span.")
            periods.append((begin, end, "Monetary Policy Strategy Meeting" in _plain(body)))
        # The Fed publishes eight regular meetings per year. Never shift keys when a
        # partial page or special intermeeting announcement changes the row count.
        if len(periods) != 8 or any(a[0] >= b[0] for a, b in itertools.pairwise(periods)):
            raise ValueError("Incomplete regular FOMC calendar.")
        for slot, (begin, end, strategy) in enumerate(periods, 1):
            title = "FOMC monetary policy strategy meeting" if strategy else "FOMC meeting"
            # The publisher describes upcoming dates as tentative until confirmed at
            # the preceding meeting. This calendar alone cannot establish confirmation.
            meta = {
                "subject": f"fomc:{year}:{slot}",
                "kind": "monetary_policy_meeting",
                "title": title,
                "state": "tentative",
                "precision": "day",
                "start": begin.isoformat(),
                "end": end.isoformat(),
                "timezone": FED_TZ,
                "origin": "Federal Reserve",
                "relevance": "US policy-rate decisions can change financing and discount-rate assumptions for this US-listed USD instrument.",
            }
            rows.append(
                _calendar_row(meta, f"{title} · {begin} to {end}. Source calendar, date precision.", received)
            )
    return rows


def _msft_release(raw, received):
    from . import evidence

    parser = evidence._Tables()
    parser.feed(raw)
    tables = [
        t
        for t in parser.tables
        if ["INCOME STATEMENTS"] in t
        and ["(In millions, except per share amounts) (Unaudited)"] in t
        and ["MICROSOFT CORPORATION", "", "", ""] in t
        and ["", "Three Months Ended September 30,"] in t
        and ["", "2026", "", "2025"] in t
    ]
    if len(tables) != 1 or not re.search(r"October 28, 2026", raw):
        raise ValueError("Expected dated Microsoft FY27 Q1 income statement.")
    values = [r for r in tables[0] if len(r) == 4 and r[0] == "Total revenue" and not r[2]]
    if len(values) != 1:
        raise ValueError("Missing total revenue row.")
    rows = []
    for col, year, fy in ((1, 2026, 27), (3, 2025, 26)):
        cell = values[0][col]
        if not re.fullmatch(r"\$?(?:\d+|\d{1,3}(?:,\d{3})+)", cell):
            raise ValueError("Invalid Microsoft revenue cell.")
        fact = evidence.revenue(
            "CIK" + MICROSOFT,
            f"Q1 FY{fy}",
            f"{year}-07-01",
            f"{year}-09-30",
            cell.strip("$").replace(",", ""),
        )
        locator = f"Income Statements / three months ended September 30, {year} / Total revenue"
        rows.append((locator, f"{locator} · USD million · {cell}", received, fact))
    paragraphs = _Paragraphs()
    paragraphs.feed(raw)
    outlook = [
        p
        for p in paragraphs.paragraphs
        if p.startswith("Microsoft will provide forward-looking guidance") and len(p) <= 500
    ]
    if len(outlook) != 1:
        raise ValueError("Missing Microsoft outlook qualification.")
    rows.append(("Business Outlook / webcast guidance", outlook[0], received, None))
    return rows


def _cma(raw, received, cik):
    company = {MICROSOFT: "Microsoft", NVIDIA: "NVIDIA"}[cik]
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise TypeError("Invalid government search results.")
    records = {}
    for item in data["results"][:20]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("title"), str)
            or not isinstance(item.get("link"), str)
        ):
            raise TypeError("Invalid government news record.")
        title = " ".join(unescape(item["title"]).split())
        if len(title) > 400 or not re.search(r"\b" + company + r"\b", title, re.IGNORECASE):
            continue
        if not any(
            isinstance(org, dict) and org.get("content_id") == "957eb4ec-089b-4f71-ba2a-dc69ac8919ea"
            for org in item.get("organisations", [])
        ):
            continue
        if not re.fullmatch(r"/government/news/[a-z0-9-]{1,220}", item["link"]):
            continue
        stamp = instant(item["public_timestamp"])
        if stamp > received:
            continue
        url = "https://" + CMA_HOST + item["link"]
        meta = {
            "subject": "cma:" + item["link"],
            "kind": "regulatory_notice",
            "title": title,
            "state": "occurred",
            "precision": "instant",
            "start": None,
            "end": None,
            "reported": stamp,
            "timezone": "UTC",
            "origin": "UK Competition and Markets Authority",
            "link": url,
            "relevance": f"The regulator names {company} in its published headline. Check the notice for the action and its stage.",
        }
        row = _calendar_row(meta, title, received)
        if url in records and records[url] != row:
            raise ValueError("Conflicting government records for one official notice.")
        records[url] = row
    return list(records.values())


def rows(provider, payload, received, *, cik=None):
    raw = payload.decode("utf-8-sig")
    if provider == "cma_news":
        return _cma(raw, received, cik)
    if provider == "bls_calendar":
        return bls_calendar.rows(raw, received)
    if provider == "fed_calendar":
        return _fed_calendar(raw, received)
    if provider in ("msft_calendar", "msft_calendar_faq"):
        return _msft_calendar(raw, received)
    if provider == "msft_release":
        return _msft_release(raw, received)
    raise ValueError("Unknown registered source.")


def observe(conn, listing_id, provider, doc_id, *, _commit_seq=None):
    from . import universe

    if _commit_seq is not None and not conn.in_transaction:
        raise ValueError("A source projection requires the document's active transaction.")
    with write(conn) if _commit_seq is None else nullcontext(_commit_seq) as seq:
        universe.instrument(conn, listing_id)
        doc = conn.execute(
            "SELECT * FROM documents WHERE id=? AND instrument_id=? AND origin=? AND fixture=?",
            (doc_id, listing_id, provider, is_fixture(conn)),
        ).fetchone()
        if not doc:
            return
        for item in conn.execute("SELECT id,locator FROM evidence_passages WHERE document_id=?", (doc_id,)):
            meta = json.loads(item["locator"])
            subject = meta["subject"]
            previous = conn.execute(
                """SELECT * FROM calendar_reports WHERE instrument_id=? AND provider=? AND subject=?
                                   ORDER BY document_seq DESC LIMIT 1""",
                (listing_id, provider, subject),
            ).fetchone()
            if previous and previous["document_seq"] >= doc["commit_seq"]:
                continue
            if previous and provider == "bls_calendar":
                old_meta = json.loads(
                    conn.execute(
                        "SELECT locator FROM evidence_passages WHERE id=?", (previous["source_ref"],)
                    ).fetchone()[0]
                )
                if old_meta["uid"] == meta["uid"] and old_meta["sequence"] > meta["sequence"]:
                    continue
            signature = json.dumps(
                [meta.get(k) for k in ("title", "state", "precision", "start", "end", "timezone", "reported")]
            )
            primary = provider != "msft_calendar_faq"
            event_id = previous["event_id"] if previous else None
            if primary and (not previous or previous["signature"] != signature):
                last = events.at_commit(conn, event_id) if event_id else None
                event = events.append_event(
                    conn,
                    listing_id,
                    kind=meta["kind"],
                    state=meta["state"],
                    source_ref=item["id"],
                    precision=meta["precision"],
                    scheduled_start=meta["start"],
                    scheduled_end=meta["end"],
                    occurred_at=meta.get("reported"),
                    source_timezone=meta["timezone"],
                    supersedes=last["id"] if last else None,
                    _commit_seq=seq,
                )
                event_id = event["event_id"]
            conn.execute(
                "INSERT INTO calendar_reports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    listing_id,
                    provider,
                    subject,
                    meta["origin"],
                    item["id"],
                    event_id,
                    signature,
                    meta["title"],
                    meta["relevance"],
                    doc["commit_seq"],
                    seq,
                ),
            )


def coverage(conn):
    reports = conn.execute("""SELECT r.*,d.title AS publication,d.source_url,i.ticker FROM calendar_reports r
               JOIN instruments i ON i.id=r.instrument_id JOIN evidence_passages p ON p.id=r.source_ref
               JOIN documents d ON d.id=p.document_id
               WHERE EXISTS(SELECT 1 FROM source_memberships m WHERE m.instrument_id=i.id AND m.status='active')
               AND NOT EXISTS(SELECT 1 FROM calendar_reports newer WHERE newer.instrument_id=r.instrument_id AND
                     newer.provider=r.provider AND newer.subject=r.subject AND newer.document_seq>r.document_seq)
               ORDER BY r.instrument_id,r.subject,r.provider""")
    groups = {}
    for row in reports:
        key = row["instrument_id"], row["subject"]
        _, state, _, start, end, _, _ = json.loads(row["signature"])
        groups.setdefault(key, []).append(
            {
                **dict(row),
                "display_state": state,
                "display_date": " to ".join(s for s in (start, end) if s) or "Date unconfirmed",
            }
        )
    result = []
    for entries in groups.values():
        if len(entries) > 1:
            result.append(
                {
                    "title": entries[0]["title"],
                    "ticker": entries[0]["ticker"],
                    "reports": entries,
                    "origin_count": len({e["origin_group"] for e in entries}),
                    "disagreement": len({e["signature"] for e in entries}) > 1,
                }
            )
    return result


def author_group(source):
    if source["origin"] in (
        "issuer",
        "issuer_news",
        "msft_release",
        "msft_calendar",
        "msft_calendar_faq",
        "sec",
        "sec_filing",
    ):
        # EDGAR distributes an issuer's own filing. The distributor does not add an independent analyst.
        return "Issuer " + source["ticker"]
    return {
        "cma_news": "UK Competition and Markets Authority",
        "fed_calendar": "Federal Reserve",
        "bls_calendar": "US Bureau of Labor Statistics",
    }.get(source["origin"])


def compare_reports(conn, left, right, judgment, rationale):
    from .db import now
    from .universe import instrument

    if (
        left == right
        or judgment not in ("same_account", "disagree", "different_subjects")
        or not isinstance(rationale, str)
        or not 1 <= len(rationale.strip()) <= 500
    ):
        raise ValueError("Choose two distinct passages, a relationship and a short explanation.")
    left, right = sorted((left, right))
    with write(conn) as seq:
        papers = conn.execute(
            """SELECT d.instrument_id,d.id FROM evidence_passages p JOIN documents d ON d.id=p.document_id
                             WHERE p.id IN (?,?) AND d.fixture=?""",
            (left, right, is_fixture(conn)),
        ).fetchall()
        if (
            len(papers) != 2
            or papers[0]["instrument_id"] != papers[1]["instrument_id"]
            or papers[0]["id"] == papers[1]["id"]
        ):
            raise ValueError("Compare different publications for the same watched listing.")
        listing = papers[0]["instrument_id"]
        instrument(conn, listing)
        conn.execute(
            """INSERT INTO source_comparisons(instrument_id,left_ref,right_ref,judgment,reason,observed_at,commit_seq)
                     VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (listing, left, right, judgment, rationale.strip(), now(), seq),
        )


def report_comparisons(conn):
    sections = []
    for comparison in conn.execute("SELECT * FROM source_comparisons ORDER BY commit_seq DESC LIMIT 40"):
        sources = [
            dict(p)
            for p in conn.execute(
                """SELECT p.id,p.text,d.origin,d.source_url,d.title,d.received_at,d.version_hash,i.ticker FROM evidence_passages p
                  JOIN documents d ON d.id=p.document_id JOIN instruments i ON i.id=d.instrument_id WHERE p.id IN (?,?) ORDER BY p.id""",
                (comparison["left_ref"], comparison["right_ref"]),
            )
        ]
        groups = {author_group(p) for p in sources}
        sections.append(
            {
                **dict(comparison),
                "sources": sources,
                "origins": sorted(g for g in groups if g),
                "unknown_origin": None in groups,
            }
        )
    return sections
