"""Immutable source versions, scoped passage retrieval and financial comparisons."""

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from html.parser import HTMLParser
from pathlib import Path

from . import providers
from .db import is_fixture, now, uid, write


SCHEMA = (
    """
CREATE TABLE documents (
    id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments(id),
    origin TEXT NOT NULL, source_url TEXT, title TEXT NOT NULL, version_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL, previous_version_id TEXT REFERENCES documents(id),
    published_at TEXT, precision TEXT NOT NULL, received_at TEXT NOT NULL,
    retention TEXT NOT NULL, body BLOB, fixture INTEGER NOT NULL,
    commit_seq INTEGER NOT NULL REFERENCES commits(seq)
);
CREATE TABLE evidence_passages (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
    locator TEXT NOT NULL, text TEXT NOT NULL, available_at TEXT NOT NULL,
    financial TEXT, UNIQUE(document_id, locator)
);
CREATE VIRTUAL TABLE passage_search USING fts5(passage_id UNINDEXED, text);
CREATE INDEX evidence_documents_by_instrument ON documents(instrument_id, commit_seq DESC);
CREATE TABLE source_checks (
    id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments(id),
    provider TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
    detail TEXT, document_id TEXT REFERENCES documents(id), retry_at TEXT, commit_seq INTEGER NOT NULL
);
CREATE INDEX source_checks_by_provider ON source_checks(provider, started_at DESC);
"""
    + providers.SCHEMA
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "examples/stockinsight/evidence/nvda-synthetic-release.json"
)
MAX_DOCUMENT_BYTES = 2_000_000


def utc(value):
    """Canonical UTC including fractions for exact replay boundaries."""
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("An explicit timestamp with timezone is required.") from None
    return instant.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def revenue(company, label, start, end, value, unit="USD million"):
    return {
        "company": company,
        "metric": "revenue",
        "period_label": label,
        "period_start": start,
        "period_end": end,
        "duration": "standalone_quarter",
        "basis": "US GAAP",
        "unit": unit,
        "currency": "USD",
        "share_basis": "total",
        "role": "actual",
        "value": value,
    }


def _blob_directory(conn):
    database = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    return Path(database).parent / "documents" if database else None


def _is_link(metadata):
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _read_blob(path):
    meta = path.lstat()
    if _is_link(meta) or not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Invalid snapshot file type or size.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Invalid snapshot file type.")
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Snapshot exceeds its size limit.")
    return raw


def _flush_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish(staging, destination):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        # Same-volume replacement and write-through before SQLite may refer to the file.
        if not move(str(staging), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(staging, destination)
        _flush_directory(destination.parent)


def _stage(conn, retention, raw):
    """Prepare full content before its short SQL transaction; published orphans are reusable."""
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Source exceeds the snapshot size limit.")
    digest = hashlib.sha256(raw).hexdigest()
    if retention != "full":
        return digest, None
    directory = _blob_directory(conn)
    if directory is None:
        return digest, raw
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        if _is_link(directory.lstat()) or not directory.is_dir():
            raise ValueError("Snapshot storage requires a private regular directory.")
        _flush_directory(directory.parent)
        destination = directory / digest
        try:
            if hashlib.sha256(_read_blob(destination)).hexdigest() == digest:
                return digest, None
        except FileNotFoundError:
            pass
        staging = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".stage-", delete=False) as stream:
                staging = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            _publish(staging, destination)
        finally:
            if staging is not None:
                staging.unlink(missing_ok=True)
    except OSError:
        raise ValueError("Full snapshot storage is unavailable.") from None
    return digest, None


def document_bytes(conn, instrument_id, document_id):
    """Read an exact permitted version, including bodies embedded by older databases."""
    row = conn.execute(
        "SELECT retention,version_hash,body FROM documents WHERE instrument_id=? AND id=?",
        (instrument_id, document_id),
    ).fetchone()
    if not row or row["retention"] != "full":
        raise ValueError("Full source bytes are unavailable for this instrument and version.")
    digest = row["version_hash"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid saved source version hash.")
    raw = row["body"]
    if raw is None:
        directory = _blob_directory(conn)
        try:
            if directory is None or _is_link(directory.lstat()):
                raise ValueError("Snapshot directory is unavailable.")
            raw = _read_blob(directory / digest)
        except OSError:
            raise ValueError("Saved source file is missing or unreadable.") from None
    if len(raw) > MAX_DOCUMENT_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Saved source fails its SHA-256 integrity check.")
    return raw


def verify_documents(conn, *, after="", limit=16):
    """Verify a bounded page of full-body references in insertion order."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Verification page size must be between 1 and 50.")
    position = 0
    if after:
        cursor = conn.execute("SELECT rowid FROM documents WHERE id=?", (after,)).fetchone()
        if not cursor:
            raise ValueError("Unknown document verification cursor.")
        position = cursor[0]
    rows = conn.execute(
        "SELECT id,instrument_id FROM documents WHERE retention='full' AND rowid>? ORDER BY rowid LIMIT ?",
        (position, limit + 1),
    ).fetchall()
    problems = []
    for doc in rows[:limit]:
        try:
            document_bytes(conn, doc["instrument_id"], doc["id"])
        except ValueError as exc:
            problems.append({"document_id": doc["id"], "message": str(exc)})
    return {
        "checked": min(len(rows), limit),
        "problems": problems,
        "next_after": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


def _save(
    conn,
    seq,
    instrument_id,
    origin,
    url,
    title,
    staged,
    rows,
    received,
    *,
    published,
    precision,
    retention,
    fixture=False,
):
    digest, embedded = staged
    previous = conn.execute(
        "SELECT id,version_hash FROM documents WHERE instrument_id=? AND origin=? AND source_url=? ORDER BY commit_seq DESC LIMIT 1",
        (instrument_id, origin, url),
    ).fetchone()
    if previous and previous["version_hash"] == digest:
        return previous["id"]
    doc_id = uid("doc")
    conn.execute(
        """INSERT INTO documents
           (id,instrument_id,origin,source_url,title,version_hash,parser_version,previous_version_id,
            published_at,precision,received_at,retention,body,fixture,commit_seq)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc_id,
            instrument_id,
            origin,
            url,
            title,
            digest,
            origin + ".v1",
            previous[0] if previous else None,
            published,
            precision,
            received,
            retention,
            embedded,
            int(fixture),
            seq,
        ),
    )
    for locator, text, available, financial in rows:
        passage_id = uid("passage")
        conn.execute(
            "INSERT INTO evidence_passages VALUES (?,?,?,?,?,?)",
            (
                passage_id,
                doc_id,
                locator,
                text,
                utc(available),
                json.dumps(financial, sort_keys=True) if financial else None,
            ),
        )
        conn.execute("INSERT INTO passage_search(passage_id,text) VALUES (?,?)", (passage_id, text))
    return doc_id


def seed_fixture(conn, instrument_id):
    from .universe import instrument

    if not is_fixture(conn):
        raise ValueError("Use a dedicated fixture workspace.")
    identity = instrument(conn, instrument_id)
    if str(identity.get("cik") or "").zfill(10) != "0001045810":
        raise ValueError("The synthetic exercise requires the resolved NVIDIA listing.")
    raw = FIXTURE_PATH.read_bytes()
    packet = json.loads(raw)
    published = packet["published_at"]
    rows = []
    for index, period in enumerate(packet["periods"]):
        fact = revenue("CIK0001045810", period["label"], period["start"], period["end"], period["revenue"])
        rows.append((f"/periods/{index}/text", period["text"], published, fact))
    rows.append(("/qualification", packet["qualification"], published, None))
    staged = _stage(conn, "full", raw)
    with write(conn) as seq:
        _save(
            conn,
            seq,
            instrument_id,
            "synthetic",
            "fixture:nvda-synthetic-release",
            packet["title"],
            staged,
            rows,
            utc(now()),
            published=published,
            precision="second (simulated)",
            retention="full",
            fixture=True,
        )
    return search(conn, instrument_id, fixture=True)


_SELECT = """
SELECT p.id,p.text,p.document_id,p.locator,p.available_at,p.financial,
       d.instrument_id,d.version_hash,d.title,d.source_url,d.published_at,d.origin,
       d.precision,d.received_at,d.fixture,d.retention,d.parser_version,d.commit_seq,d.previous_version_id
FROM evidence_passages p JOIN documents d ON p.document_id=d.id
"""


def _read(
    conn,
    instrument_id,
    cutoff,
    fixture,
    commit_seq,
    passage_id=None,
    query=None,
    limit=50,
    offset=0,
    origin=None,
    financial_documents=False,
):
    if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or offset < 0:
        raise ValueError("Invalid evidence search window.")
    conditions = ["d.instrument_id=?"]
    args = [instrument_id]
    if financial_documents:
        if cutoff:
            conditions.append(
                "EXISTS (SELECT 1 FROM evidence_passages f WHERE f.document_id=d.id AND f.financial IS NOT NULL AND f.available_at<=?)"
            )
            args.append(utc(cutoff))
        else:
            conditions.append(
                "EXISTS (SELECT 1 FROM evidence_passages f WHERE f.document_id=d.id AND f.financial IS NOT NULL)"
            )
    if origin is not None:
        conditions.append("d.origin=?")
        args.append(origin)
    if cutoff:
        conditions.append("p.available_at<=?")
        args.append(utc(cutoff))
    if fixture is not None:
        conditions.append("d.fixture=?")
        args.append(int(fixture))
    if commit_seq is not None:
        conditions.append("d.commit_seq<=?")
        args.append(commit_seq)
    if passage_id is not None:
        conditions.append("p.id=?")
        args.append(passage_id)
    else:
        # Search the current edition of each source at this boundary. Exact ID retrieval
        # still resolves superseded passages cited by an earlier brief.
        newer = [
            "n.instrument_id=d.instrument_id",
            "n.origin=d.origin",
            "n.source_url=d.source_url",
            "n.commit_seq>d.commit_seq",
        ]
        if cutoff:
            newer.append(
                "EXISTS (SELECT 1 FROM evidence_passages v WHERE v.document_id=n.id AND v.available_at<=?)"
            )
            args.append(utc(cutoff))
        if commit_seq is not None:
            newer.append("n.commit_seq<=?")
            args.append(commit_seq)
        conditions.append("NOT EXISTS (SELECT 1 FROM documents n WHERE " + " AND ".join(newer) + ")")
    if query:
        terms = re.findall(r"\w+", query[:256])[:10]
        if not terms:
            return []
        conditions.append("p.id IN (SELECT passage_id FROM passage_search WHERE passage_search MATCH ?)")
        args.append(" AND ".join(f'"{term}"' for term in terms))
    sql = _SELECT + " WHERE " + " AND ".join(conditions)
    sql += """ ORDER BY d.commit_seq DESC, (p.financial IS NULL),
               json_extract(p.financial,'$.period_end') DESC, p.locator, d.id, p.id LIMIT ? OFFSET ?"""
    args.extend((limit, offset))
    records = []
    for row in conn.execute(sql, args):
        result = dict(row)
        result["fixture"] = bool(result["fixture"])
        result["financial"] = json.loads(result["financial"]) if result["financial"] else None
        records.append(result)
    return records


def search(
    conn,
    instrument_id,
    cutoff=None,
    *,
    query=None,
    fixture=None,
    commit_seq=None,
    limit=50,
    offset=0,
    origin=None,
    financial_documents=False,
):
    return _read(
        conn,
        instrument_id,
        cutoff,
        fixture,
        commit_seq,
        query=query,
        limit=limit,
        offset=offset,
        origin=origin,
        financial_documents=financial_documents,
    )


def source_context(conn, document_id, cutoff):
    """Retained narrative accompanying the cells, bounded by public availability."""
    return conn.execute(
        """SELECT id,locator,text FROM evidence_passages WHERE document_id=? AND financial IS NULL
           AND (? IS NULL OR available_at<=?) ORDER BY locator""",
        (document_id, cutoff, cutoff),
    ).fetchall()


def still_supported(conn, passage, cutoff):
    """Check the source's latest eligible edition inside the submission transaction."""
    rows = conn.execute(
        """
        SELECT p.locator,p.text,p.financial FROM evidence_passages p WHERE p.document_id=(
            SELECT d.id FROM documents d
            WHERE d.instrument_id=? AND d.origin=? AND d.source_url=? AND d.fixture=?
              AND d.commit_seq>? AND EXISTS (SELECT 1 FROM evidence_passages v WHERE v.document_id=d.id
                                             AND (? IS NULL OR v.available_at<=?))
            ORDER BY d.commit_seq DESC LIMIT 1
        ) AND (? IS NULL OR p.available_at<=?)
        """,
        (
            passage["instrument_id"],
            passage["origin"],
            passage["source_url"],
            int(passage["fixture"]),
            passage["commit_seq"],
            cutoff,
            cutoff,
            cutoff,
            cutoff,
        ),
    ).fetchall()
    if not rows:
        return True
    if passage["financial"]:
        # Compare the full retained context, even if a footnote uses a new locator.
        # The financial cell itself may have moved without changing its meaning.
        original_notes = {
            (r["locator"], r["text"]) for r in source_context(conn, passage["document_id"], cutoff)
        }
        latest_notes = {(r["locator"], r["text"]) for r in rows if r["financial"] is None}
        return original_notes == latest_notes and any(
            r["financial"]
            and json.loads(r["financial"]) == passage["financial"]
            and r["text"] == passage["text"]
            for r in rows
        )
    return any(r["locator"] == passage["locator"] and r["text"] == passage["text"] for r in rows)


def get(conn, instrument_id, passage_id, cutoff=None, *, fixture=None, commit_seq=None):
    rows = _read(conn, instrument_id, cutoff, fixture, commit_seq, passage_id=passage_id)
    if not rows:
        raise ValueError("Passage unavailable in this instrument, information cutoff or evidence mode.")
    return rows[0]


def _number(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError("Missing or non-decimal financial value.")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid financial value.") from None
    if not amount.is_finite() or abs(amount.adjusted()) > 32 or len(amount.as_tuple().digits) > 32:
        raise ValueError("Unsupported financial precision or magnitude.")
    return amount


def _period(fact):
    try:
        start, end = (date.fromisoformat(fact[key]) for key in ("period_start", "period_end"))
    except (TypeError, ValueError, KeyError):
        raise ValueError("Both financial periods need exact dates.") from None
    if start > end:
        raise ValueError("Invalid period order.")
    return start, end


def supports_actual(fact, cik):
    """Check the financial meaning of one observation before it supports an assessment."""
    if not cik or fact.get("company") != "CIK" + cik or fact.get("role") != "actual":
        return False
    try:
        _number(fact.get("value"))
        _period(fact)
    except ValueError:
        return False
    if not all(fact.get(k) for k in ("period_label", "duration", "basis", "unit", "share_basis")):
        return False
    metric, unit, basis = fact.get("metric", ""), fact["unit"].casefold(), fact["share_basis"].casefold()
    currency = (fact.get("currency") or "").casefold()
    if metric in {"gross_margin", "operating_margin", "dividend_yield"}:
        return unit in {"%", "percent", "percentage", "ratio"} and basis == "total"
    if metric == "shares_outstanding":
        return unit in {"shares", "thousand shares", "million shares", "billion shares"}
    if not re.fullmatch(r"[a-z]{3}", currency):
        return False
    if metric in {"earnings_per_share", "dividend_per_share", "revenue_per_share"}:
        return unit in {currency + " per share", currency + "/share", currency + "/shares"} and basis in {
            "basic",
            "diluted",
            "common share",
            "per share",
        }
    if metric in {"revenue", "net_income", "free_cash_flow", "share_repurchases", "total_dividends"}:
        return basis == "total" and unit in {
            currency,
            *(f"{currency} {scale}" for scale in ("thousand", "million", "billion", "trillion")),
        }
    return False


def compare(current, baseline, kind):
    """Two observed values on one declared basis. Percent difference is relative to |baseline|."""
    actual, other = current.get("financial"), baseline.get("financial")
    if not actual or not other or current["id"] == baseline["id"]:
        raise ValueError("Choose two distinct financial passages.")
    if current["fixture"] != baseline["fixture"]:
        raise ValueError("Synthetic and public evidence cannot be compared.")
    for key in ("metric", "basis", "unit", "currency", "duration", "share_basis"):
        if not actual.get(key) or actual[key] != other.get(key):
            raise ValueError(f"Incompatible financial {key}.")
    a_period, b_period = _period(actual), _period(other)
    if not actual.get("company") or not other.get("company"):
        raise ValueError("The company identity is required.")
    same_company = actual["company"] == other["company"]
    if actual.get("role") != "actual":
        raise ValueError("The current input must be an actual observation.")
    if kind == "actual_vs_expectation":
        if (
            not same_company
            or a_period != b_period
            or other.get("role") not in ("issuer_guidance", "street_consensus", "model_estimate")
        ):
            raise ValueError("Expected and reported metrics must describe the same company and period.")
        # The dated baseline must precede the result's publication, not merely its later retrieval.
        if not current.get("published_at") or not baseline.get("available_at"):
            raise ValueError("The expectation's pre-release availability is unverified.")
        if utc(baseline["available_at"]) >= utc(current["published_at"]):
            raise ValueError("The expectation must have been publicly available before the result.")
    elif kind == "period_trend":
        if not same_company or other.get("role") != "actual" or b_period[1] >= a_period[0]:
            raise ValueError("Trend requires earlier and later nonoverlapping actuals for the same company.")
        if abs((a_period[1] - a_period[0]).days - (b_period[1] - b_period[0]).days) > 7:
            raise ValueError("Periods differ in duration by more than a calendar week.")
    elif kind == "peer_comparison":
        if same_company or a_period != b_period or other.get("role") != "actual":
            raise ValueError("Peer comparison requires different companies with aligned periods.")
    else:
        raise ValueError("Unknown comparison kind.")
    a, b = _number(actual.get("value")), _number(other.get("value"))
    with localcontext() as ctx:
        ctx.prec = 80
        delta = a - b
        small_base = abs(b) <= Decimal("0.000001")
        percent = None if small_base else (delta / abs(b) * 100).quantize(Decimal("0.0001"))
    return {
        "kind": kind,
        "method": "compare_financials.v1",
        "metric": actual["metric"],
        "unit": actual["unit"],
        "basis": actual["basis"],
        "current_value": str(a),
        "baseline_value": str(b),
        "current_period": actual["period_label"],
        "baseline_period": other["period_label"],
        "baseline_role": other["role"],
        "difference": format(delta, "f"),
        "percent_change": format(percent.normalize(), "f") if percent is not None else None,
        "percent_definition": "(current - baseline) / abs(baseline) * 100",
        "warnings": [
            "Baseline magnitude <= 0.000001 reported units; only the absolute difference is meaningful."
        ]
        if small_base
        else [],
        "input_ids": [current["id"], baseline["id"]],
        "version_ids": [current["document_id"], baseline["document_id"]],
    }


class _Tables(HTMLParser):
    """Extract the cells as displayed, without interpreting scripts or following embedded links."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = self.row = self.cell = None


def _issuer_rows(raw, received):
    source = raw.decode("utf-8")
    if not re.search("NVIDIA Announces Financial Results for Second Quarter Fiscal 2025", source, re.I):
        raise ValueError("Expected dated issuer release missing.")
    parser = _Tables()
    parser.feed(source)
    parser.close()
    header = ["($ in millions, except earnings per share)", "Q2 FY25", "Q1 FY25", "Q2 FY24", "Q/Q", "Y/Y"]
    tables = [t for t in parser.tables if len(t) >= 3 and t[0] == ["GAAP"] and t[1] == header]
    if len(tables) != 1:
        raise ValueError("Expected one GAAP table with the reviewed units and fiscal periods.")
    matches = [row for row in tables[0][2:] if len(row) == len(header) and row[0] == "Revenue"]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous GAAP revenue row.")
    periods = (("2024-04-29", "2024-07-28"), ("2024-01-29", "2024-04-28"))
    rows = []
    for column, (start, end) in enumerate(periods, 1):
        cell = matches[0][column]
        if not re.fullmatch(r"\$(?:\d+|\d{1,3}(?:,\d{3})+)", cell):
            raise ValueError("Unexpected GAAP revenue cell.")
        number = cell[1:].replace(",", "")
        fact = revenue("CIK0001045810", header[column], start, end, number)
        locator = f"GAAP / {header[0]} / Revenue / {header[column]}"
        rows.append((locator, locator + " / " + cell, received, fact))
    return rows


def _sec_rows(raw, received, cik):
    body = json.loads(raw, parse_float=Decimal)
    if (
        not isinstance(body, dict)
        or str(body.get("cik")).zfill(10) != cik
        or body.get("taxonomy") != "us-gaap"
        or body.get("tag") != providers.SEC_TAG
    ):
        raise ValueError("Unexpected EDGAR entity, taxonomy or concept.")
    units = body.get("units")
    if not isinstance(units, dict) or not isinstance(units.get("USD"), list):
        raise ValueError("Missing USD facts.")
    latest = {}
    for index, row in enumerate(units["USD"]):
        if not isinstance(row, dict):
            raise ValueError("Invalid XBRL fact shape.")
        if row.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
            continue
        start, end, filed = (date.fromisoformat(row[k]) for k in ("start", "end", "filed"))
        if not 80 <= (end - start).days + 1 <= 100:
            continue
        if not re.fullmatch(
            r"[0-9]{10}-[0-9]{2}-[0-9]{6}", row.get("accn", "")
        ) or not end <= filed <= date.fromisoformat(received[:10]):
            raise ValueError("Invalid accession or filing chronology.")
        value = row["val"]
        if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
            raise ValueError("Invalid XBRL numeric value.")
        number = str(_number(str(value)))
        fact = revenue("CIK" + cik, f"{start} to {end}", str(start), str(end), number, unit="USD")
        fact.update(
            {
                "filed": str(filed),
                "filed_precision": "day",
                "accession": row["accn"],
                "tag": providers.SEC_TAG,
            }
        )
        item = (filed, row["accn"], index, fact)
        key = (start, end)
        if key not in latest or item[:2] > latest[key][:2]:
            latest[key] = item
        elif item[:2] == latest[key][:2] and number != latest[key][3]["value"]:
            raise ValueError("Conflicting values for the same filing period.")
    rows = []
    for key in sorted(latest, reverse=True)[:12]:
        _, _, index, fact = latest[key]
        # The cited cell is retrievable from the exact stored JSON bytes.
        rows.append((f"/units/USD/{index}/val", fact["value"], received, fact))
    return rows


def claim_public(conn, instrument_id, provider, host):
    """Claim one bounded publisher access slot shared by all registered routes on that host."""
    from . import sources_calendar
    from .universe import instrument

    if is_fixture(conn):
        raise ValueError("A public source requires an ordinary workspace.")
    routes_by_host = {
        providers.ISSUER_HOST: ["issuer", "issuer_news", "nvda_excerpt"],
        providers.SEC_HOST: ["sec", "sec_filing"],
        sources_calendar.MSFT_HOST: ["msft_excerpt"],
        providers.MSFT_CDN_HOST: ["msft_transcript"],
    }
    for name, (hostname, _, _) in sources_calendar.ROUTES.items():
        routes_by_host.setdefault(hostname, []).append(name)
    routes = routes_by_host.get(host, [])
    if provider not in routes:
        raise ValueError("Choose a registered provider and publisher host.")
    with write(conn) as seq:
        instrument(conn,instrument_id)
        # The source route identifies the cached document and the receipt. The
        # publisher's hostname determines who must observe a transport cooldown.
        started = utc(now())
        stamp = datetime.fromisoformat(started)
        minute_ago = utc((stamp - timedelta(minutes=1)).isoformat())
        placeholders = ",".join("?" for _ in routes)
        bounds = conn.execute(
            f"""SELECT max(retry_at), max(CASE WHEN provider='sec_filing' THEN coalesce(finished_at,started_at) ELSE started_at END),
                max(CASE WHEN status='running' THEN started_at END)
                FROM source_checks WHERE provider IN ({placeholders}) AND (retry_at>? OR started_at>? OR finished_at>?)""",
            (*routes, started, minute_ago, minute_ago),
        ).fetchone()
        deadline, latest_start, in_flight = bounds
        if latest_start:
            spacing = utc((datetime.fromisoformat(latest_start) + timedelta(seconds=1)).isoformat())
            deadline = max(deadline or "", spacing)
        if (deadline and deadline > started) or (in_flight and in_flight > minute_ago):
            return {
                "status": "rate_limited",
                "message": "An in-progress check or source retry deadline is active.",
                "retry_at": deadline if deadline and deadline > started else None,
                "evidence_ids": [],
            }
        check_id = uid("check")
        conn.execute(
            """INSERT INTO source_checks(id,instrument_id,provider,started_at,status,commit_seq)
                        VALUES (?,?,?,?,'running',?)""",
            (check_id, instrument_id, provider, started, seq),
        )
    return {"receipt_id":check_id}


def capture_public(conn, instrument, provider="issuer"):
    from . import filing_passages, issuer_news, sources_calendar
    from .universe import instrument as lookup

    if is_fixture(conn):
        return {
            "status": "unsupported",
            "message": "Use a local trial workspace for public captures.",
            "evidence_ids": [],
        }
    identity = lookup(conn, instrument["id"])
    instrument_id = identity["id"]
    cik = identity.get("cik")
    market_calendar = provider in ("fed_calendar", "bls_calendar") and sources_calendar.eligible(identity, provider)
    if not market_calendar and (not cik or not re.fullmatch(r"\d{10}", cik)):
        return {
            "status": "unsupported",
            "message": "Source capture requires a resolved issuer CIK.",
            "evidence_ids": [],
        }
    headers = {}
    if provider == "issuer" and cik == "0001045810":
        host, path = providers.ISSUER_HOST, providers.ISSUER_PATH
        title = "NVIDIA Q2 FY25 earnings release · GAAP revenue table"
        retention, published, precision = "selected_cells_and_hash", "2024-08-28", "day (publisher)"
    elif provider == "issuer_news" and cik == "0001045810":
        host, path = providers.ISSUER_HOST, issuer_news.PATH
        title = "NVIDIA Newsroom press releases"
        retention, published, precision = "rss_metadata_and_hash", None, "publisher timestamps per item"
    elif provider in sources_calendar.ROUTES and sources_calendar.eligible(identity, provider):
        host, path, title = sources_calendar.ROUTES[provider]
        if provider == "cma_news":
            path += {sources_calendar.MICROSOFT: "Microsoft", sources_calendar.NVIDIA: "NVIDIA"}[cik]
        retention = (
            "calendar_observations_and_hash"
            if provider in sources_calendar.CALENDARS
            else "selected_cells_and_hash"
        )
        if provider == "cma_news":
            retention = "regulator_headlines_and_hash"
        published = "2026-10-28" if provider == "msft_release" else None
        precision = "day (publisher)" if published else "publisher precision per event"
    elif provider in ("sec", "sec_filing"):
        contact = providers.sec_contact()
        if not contact:
            return {
                "status": "unavailable",
                "message": "Set STOCKINSIGHT_SEC_CONTACT to an authorized contact email.",
                "evidence_ids": [],
            }
        headers = {"User-Agent": "StockInsight/1.0 " + contact}
        host = providers.SEC_HOST
        path = f"/api/xbrl/companyconcept/CIK{cik}/us-gaap/{providers.SEC_TAG}.json"
        title = "SEC EDGAR reported revenue · " + identity["ticker"]
        retention, published, precision = "full", None, "filing dates per fact"
        if provider == "sec_filing":
            path = f"/submissions/CIK{cik}.json"
            title = "SEC filed 8-K passages · " + identity["ticker"]
            precision = "day (SEC filing index)"
    else:
        return {"status": "unsupported", "message": "No matching named issuer source.", "evidence_ids": []}
    url = f"https://{host}{path}"
    started = utc(now())
    # Validate a stored full version before serving a cache hit. Reacquiring identical
    # bytes repairs a missing/corrupt file; a changed answer gets a distinct version.
    cached = conn.execute(
        """SELECT id,document_id,finished_at FROM source_checks WHERE instrument_id=? AND provider=? AND status='ok'
           AND julianday(?) - julianday(finished_at) BETWEEN 0 AND 1.0/24 ORDER BY finished_at DESC LIMIT 1""",
        (instrument_id, provider, started),
    ).fetchone()
    if cached:
        if retention == "full":
            try:
                document_bytes(conn, instrument_id, cached["document_id"])
            except ValueError:
                cached = None
        if cached:
            ids = [
                r[0]
                for r in conn.execute("SELECT id FROM evidence_passages WHERE document_id=?", (cached[1],))
            ]
            return {
                "status": "ok",
                "cached": True,
                "checked_at": cached[2],
                "receipt_id": cached[0],
                "document_id": cached[1],
                "message": "Using the last successful source check.",
                "evidence_ids": ids,
            }
    claim = claim_public(conn, instrument_id, provider, host)
    if "receipt_id" not in claim:
        return claim
    check_id = claim["receipt_id"]
    status, message, document_id, ids, retry_at = "ok", "Dated public facts captured.", None, [], None
    try:
        options = {"limit": issuer_news.MAX_BYTES} if provider == "issuer_news" else {}
        if provider == "sec_filing":
            raw, rows, received, url, published = filing_passages.fetch(path, cik, headers)
        else:
            raw = providers._fetch(host, path, headers=headers, **options)
            received = utc(now())
        if provider == "sec_filing":
            message = f"Retained {len(rows)} passages from SEC filed items."
        elif provider == "issuer_news":
            rows = issuer_news.rows(raw, received)
            if not rows:
                raise providers.SourceError("partial", "The feed returned no qualifying issuer announcements.")
            message = f"Read {len(rows)} dated issuer announcements."
        elif provider in sources_calendar.ROUTES:
            rows = sources_calendar.rows(provider, raw, received, cik=cik)
            if not rows and provider != "cma_news":
                raise providers.SourceError(
                    "partial", "No recognizable observations in the named source edition."
                )
            message = (
                f"Read {len(rows)} observations from {title}."
                if rows
                else "No directly named issuer headline in the 20 checked regulator results."
            )
        elif provider == "issuer":
            rows = _issuer_rows(raw, received)
        else:
            rows = _sec_rows(raw, received, cik)
        if not rows and provider != "cma_news":
            raise providers.SourceError(
                "partial", "No qualifying reported standalone quarterly USD facts in the response."
            )
    except providers.SourceError as exc:
        status, message, retry_at = exc.status, str(exc), exc.retry_at
    except (ValueError, KeyError, TypeError, RecursionError):
        status, message = "error", "Source content failed schema, identity or period validation."
    if status == "ok":
        try:
            staged = _stage(conn, retention, raw)
        except ValueError as exc:
            status, message = "error", str(exc)
    with write(conn) as seq:
        if status == "ok":
            try:
                lookup(conn,instrument_id)
            except ValueError:
                status, message = "unavailable", "The listing left the active watchlist during this source check."
        if status == "ok":
            document_id = _save(
                conn,
                seq,
                instrument_id,
                provider,
                url,
                title,
                staged,
                rows,
                received,
                published=published,
                precision=precision,
                retention=retention,
            )
            ids = [
                r[0]
                for r in conn.execute("SELECT id FROM evidence_passages WHERE document_id=?", (document_id,))
            ]
            if provider in sources_calendar.CALENDARS or provider == "cma_news":
                sources_calendar.observe(conn,instrument_id,provider,document_id,_commit_seq=seq)
        conn.execute(
            """UPDATE source_checks SET finished_at=?,status=?,detail=?,document_id=?,retry_at=?,commit_seq=? WHERE id=?""",
            (utc(now()), status, message, document_id, retry_at, seq, check_id),
        )
    return {
        "status": status,
        "message": message,
        "receipt_id": check_id,
        "document_id": document_id,
        "retry_at": retry_at,
        "evidence_ids": ids,
        "cached": False,
    }


capabilities = providers.capabilities
