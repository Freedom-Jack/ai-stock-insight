"""Operator-selected, named public sources and Fiscal.ai preflight operations."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import HTTPException, HTTPSConnection
from importlib import util
from ipaddress import ip_address
import json
import os
import queue
import re
import socket
import ssl
import threading
import time

from .db import is_fixture, now, uid, write

ISSUER_HOST = "nvidianews.nvidia.com"
ISSUER_PATH = "/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025"
SEC_HOST = "data.sec.gov"
FISCAL_HOST = "api.fiscal.ai"
SEC_TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"
_DNS_SLOTS = threading.BoundedSemaphore(4)
SCHEMA = """
CREATE TABLE provider_attempts (
    id TEXT PRIMARY KEY, operation TEXT NOT NULL, instrument_id TEXT REFERENCES instruments(id),
    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
    observation TEXT, response_hash TEXT, commit_seq INTEGER NOT NULL
);
CREATE TABLE provider_catalogs (
    id TEXT PRIMARY KEY, provider TEXT NOT NULL, protocol TEXT NOT NULL, schema_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL, schemas TEXT NOT NULL, attempt_id TEXT NOT NULL REFERENCES provider_attempts(id),
    commit_seq INTEGER NOT NULL, UNIQUE(provider,schema_hash,protocol)
);
"""


def sec_contact():
    value = os.environ.get("STOCKINSIGHT_SEC_CONTACT", "")
    if re.fullmatch(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}", value):
        return value
    return None


def _fiscal_key():
    if os.environ.get("STOCKINSIGHT_FISCAL_INCLUDED") != "1":
        return None
    key = os.environ.get("STOCKINSIGHT_FISCAL_KEY", "")
    return key if re.fullmatch(r"[\x21-\x7e]{1,512}", key) else None


def capabilities(conn=None):
    entries = [
        {
            "id": "issuer",
            "provider": "NVIDIA Newsroom",
            "operation": "dated_gaap_revenue",
            "configured": True,
            "coverage": "Resolved NVIDIA only; Q2 and Q1 FY25. One historical release.",
            "cadence": "Operator or investigator request; reuse successful checks for one hour.",
            "source_url": "https://" + ISSUER_HOST + ISSUER_PATH,
            "retention": "table excerpts and raw hash",
        },
        {
            "id": "sec",
            "provider": "SEC EDGAR",
            "operation": "xbrl.companyconcept",
            "configured": bool(sec_contact()),
            "coverage": "Reported standalone quarterly USD revenue; 10-Q/K and amendments.",
            "source_url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
            "cadence": "At most one request per second; one-hour success cache; honor Retry-After.",
            "requires": "Identified STOCKINSIGHT_SEC_CONTACT email",
            "retention": "public source bytes",
        },
        {
            "id": "fiscal",
            "provider": "Fiscal.ai",
            "operation": "v3/company/profile",
            "configured": bool(_fiscal_key()),
            "mcp_sdk_installed": bool(util.find_spec("mcp")),
            "entitlement": "requires endpoint-specific observation",
            "coverage": "NVDA/MSFT profile probe and operator catalog discovery only",
            "quota": "Four preflight operations per UTC day; account limits unverified.",
            "source_url": "https://docs.fiscal.ai/docs/api-reference",
            "retention": "schema, hash and projected identity only",
        },
        {
            "id": "historical_consensus",
            "configured": False,
            "coverage": "Verified pre-release Street snapshot unavailable",
        },
        {
            "id": "market_price",
            "configured": False,
            "coverage": "No verified interval, session, adjustment basis or delay",
        },
        {
            "id": "issuer_news",
            "provider": "NVIDIA Newsroom",
            "operation": "press_release_feed",
            "configured": True,
            "coverage": "Published NVIDIA announcements in the current rolling feed.",
            "source_url": "https://nvidianews.nvidia.com/rss",
            "cadence": "Opt-in foreground schedule with a one-hour success cache.",
            "retention": "headline, official URL, publication timestamp and feed hash",
        },
    ]
    if conn is not None:
        for entry in (e for e in entries if e["id"] in ("issuer", "issuer_news", "sec")):
            row = conn.execute(
                """SELECT id AS receipt_id,instrument_id,started_at,finished_at,status,document_id,retry_at
                   FROM source_checks WHERE provider=? ORDER BY started_at DESC LIMIT 1""",
                (entry["id"],),
            ).fetchone()
            entry["last_check"] = dict(row) if row else None
        observed = conn.execute(
            """SELECT id AS receipt_id,instrument_id,operation,status,started_at,finished_at,response_hash
               FROM provider_attempts ORDER BY started_at DESC LIMIT 1"""
        ).fetchone()
        catalog = conn.execute(
            "SELECT protocol,schema_hash,observed_at FROM provider_catalogs ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        entries[2]["last_check"] = dict(observed) if observed else None
        entries[2]["last_catalog"] = dict(catalog) if catalog else None
    return entries


class SourceError(ValueError):
    def __init__(self, status, message, retry_at=None):
        super().__init__(message)
        self.status = status
        self.retry_at = retry_at


def _public_addresses(host):
    # System DNS resolvers need not respect a socket timeout. Bound both the caller's
    # wait and the number of outstanding lookups if the operating system stalls.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise SourceError("unavailable", "Source name resolution is busy.")
    outcome = queue.Queue(maxsize=1)

    def resolve():
        try:
            outcome.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            outcome.put([])
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = outcome.get(timeout=4)
    except queue.Empty:
        raise SourceError("unavailable", "Source name resolution timed out.") from None
    if not addresses or any(
        not ip_address(entry[4][0]).is_global or ip_address(entry[4][0]).is_multicast for entry in addresses
    ):
        raise SourceError("unavailable", "The source did not resolve exclusively to public addresses.")
    return addresses


def _retry_at(value):
    from email.utils import parsedate_to_datetime

    start = datetime.now(timezone.utc)
    try:
        candidate = (
            start + timedelta(seconds=int(value))
            if value and value.isdigit()
            else parsedate_to_datetime(value)
        )
    except (TypeError, ValueError, OverflowError):
        candidate = start + timedelta(minutes=1)
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return (
        max(start, candidate)
        .astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _fetch(host, path, *, headers=None, limit=2_000_000):
    """No proxy, redirects or DNS re-resolution after address validation. TLS uses the original hostname."""
    if host not in (ISSUER_HOST, SEC_HOST, FISCAL_HOST):
        raise ValueError("Unsupported public source.")
    connection = HTTPSConnection(host, timeout=10)
    try:
        deadline = time.monotonic() + 18
        entry = _public_addresses(host)[0]
        with socket.socket(entry[0], entry[1], entry[2]) as sock:
            sock.settimeout(10)
            sock.connect(entry[4])
            connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            connection.request("GET", path, headers={"User-Agent": "StockInsight/1.0", **(headers or {})})
            response = connection.getresponse()
            if response.status != 200:
                status = {
                    401: "unavailable",
                    403: "not_entitled" if host == FISCAL_HOST else "unavailable",
                    404: "unsupported",
                    429: "rate_limited",
                }.get(response.status, "error")
                raise SourceError(
                    status,
                    f"Source returned HTTP {response.status}.",
                    _retry_at(response.getheader("Retry-After")) if response.status in (429, 503) else None,
                )
            chunks = bytearray()
            while len(chunks) <= limit:
                if time.monotonic() > deadline:
                    raise SourceError("unavailable", "Source exceeded its time budget.")
                chunk = response.read1(min(65536, limit + 1 - len(chunks)))
                if not chunk:
                    return bytes(chunks)
                chunks.extend(chunk)
            raise SourceError("error", "Source exceeded the response size limit.")
    except (OSError, HTTPException):
        raise SourceError("unavailable", "Verified HTTPS request failed or timed out.") from None
    finally:
        connection.close()


def _begin_fiscal(conn, operation, instrument_id=None):
    # Reserve before I/O, including failed/disconnected attempts, across concurrent processes.
    instant = now()
    with write(conn) as seq:
        limited = conn.execute(
            "SELECT 1 FROM provider_attempts WHERE json_extract(observation,'$.retry_at')>? LIMIT 1",
            (instant,),
        ).fetchone()
        if limited:
            raise SourceError("rate_limited", "The provider retry deadline is active.")
        used = conn.execute(
            "SELECT COUNT(*) FROM provider_attempts WHERE substr(started_at,1,10)=?", (instant[:10],)
        ).fetchone()[0]
        if used >= 4:
            raise SourceError(
                "rate_limited", "Daily local limit of four Fiscal preflight operations reached."
            )
        attempt = uid("probe")
        conn.execute(
            "INSERT INTO provider_attempts VALUES (?,?,?,?,NULL,'running',NULL,NULL,?)",
            (attempt, operation, instrument_id, instant, seq),
        )
    return attempt


def _finish_fiscal(conn, attempt, status, observation, digest=None):
    with write(conn) as seq:
        conn.execute(
            "UPDATE provider_attempts SET finished_at=?,status=?,observation=?,response_hash=?,commit_seq=? WHERE id=?",
            (now(), status, json.dumps(observation, sort_keys=True), digest, seq, attempt),
        )
    return {"status": status, "receipt_id": attempt, **observation}


def probe_fiscal(conn, instrument):
    """Probe one named read. Dataset names advertised by a profile do not prove endpoint access."""
    from .universe import instrument as lookup

    instrument = lookup(conn, instrument["id"])
    if is_fixture(conn):
        return {"status": "unavailable", "message": "Live provider probes require a local trial workspace."}
    key = _fiscal_key()
    if not key:
        return {
            "status": "unavailable",
            "message": "Configure an explicitly included Fiscal entitlement and key.",
        }
    ticker = instrument.get("ticker")
    cik = {"MSFT": "0000789019", "NVDA": "0001045810"}.get(ticker)
    if not cik or str(instrument.get("cik")).zfill(10) != cik:
        return {"status": "unsupported", "message": "Select a resolved supported NASDAQ listing."}
    try:
        attempt = _begin_fiscal(conn, "GET /v3/company/profile", instrument["id"])
    except SourceError as exc:
        return {"status": exc.status, "message": str(exc)}
    try:
        raw = _fetch(
            FISCAL_HOST,
            "/v3/company/profile?ticker=" + ticker + "&exchange=NASDAQ",
            headers={"X-Api-Key": key},
            limit=256_000,
        )
        profile = json.loads(raw)
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("primaryListing"), dict)
            or str(profile.get("cik")).zfill(10) != cik
            or profile["primaryListing"].get("ticker") != ticker
            or profile["primaryListing"].get("exchangeCode") != "NASDAQ"
        ):
            raise ValueError
    except SourceError as exc:
        return _finish_fiscal(conn, attempt, exc.status, {"message": str(exc), "retry_at": exc.retry_at})
    except (ValueError, RecursionError):
        return _finish_fiscal(
            conn, attempt, "error", {"message": "Profile response failed identity or schema validation."}
        )
    return _finish_fiscal(
        conn,
        attempt,
        "ok",
        {
            "ticker": ticker,
            "cik": cik,
            "exchange": "NASDAQ",
            "coverage": "Company profile only; price and consensus access remain unverified.",
        },
        hashlib.sha256(raw).hexdigest(),
    )


async def _mcp_catalog(key, *, transport=None):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    import mcp.types as types

    # Pin the address through transport while checking the certificate and sending Host
    # for the original hostname. No DNS re-resolution or environment proxy gets the key.
    addresses = await asyncio.to_thread(_public_addresses, FISCAL_HOST)
    pinned_ip = addresses[0][4][0]
    remaining_bytes = 2_000_000
    requests = 0
    failure = None

    class BoundedBody(httpx.AsyncByteStream):
        def __init__(self, stream):
            self.stream = stream

        async def __aiter__(self):
            nonlocal remaining_bytes
            async for chunk in self.stream:
                remaining_bytes -= len(chunk)
                if remaining_bytes < 0:
                    raise ValueError("MCP response budget exceeded.")
                yield chunk

        async def aclose(self):
            await self.stream.aclose()

    async def validate_request(request):
        nonlocal requests
        if (
            request.url.scheme != "https"
            or request.url.host != FISCAL_HOST
            or request.url.port not in (None, 443)
            or request.url.path != "/mcp"
            or request.url.query
        ):
            raise ValueError("MCP route outside the configured endpoint.")
        requests += 1
        if requests > 6:
            raise ValueError("MCP preflight exceeded its request budget.")
        request.url = request.url.copy_with(host=pinned_ip)
        request.extensions["sni_hostname"] = FISCAL_HOST
        request.headers["Host"] = FISCAL_HOST
        request.headers["Accept-Encoding"] = "identity"

    async def validate_response(response):
        nonlocal failure
        if response.status_code in (401, 403, 429, 503):
            status = {401: "unavailable", 403: "not_entitled", 429: "rate_limited", 503: "unavailable"}[
                response.status_code
            ]
            retry = (
                _retry_at(response.headers.get("retry-after")) if response.status_code in (429, 503) else None
            )
            failure = SourceError(status, f"Fiscal returned HTTP {response.status_code}.", retry)
            raise failure
        if response.is_redirect or response.headers.get("content-encoding", "identity") != "identity":
            raise ValueError("Unsupported MCP response encoding or redirect.")
        response.stream = BoundedBody(response.stream)

    try:
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + key},
            timeout=10,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
            event_hooks={"request": [validate_request], "response": [validate_response]},
        ) as http:
            async with streamable_http_client("https://" + FISCAL_HOST + "/mcp", http_client=http) as (
                reader,
                writer,
                _,
            ):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    page = await session.list_tools(params=types.PaginatedRequestParams())
                    tools = [
                        {
                            "name": tool.name,
                            "inputSchema": tool.inputSchema,
                            "outputSchema": tool.outputSchema,
                        }
                        for tool in page.tools
                    ]
                    return initialized.protocolVersion, tools, bool(page.nextCursor)
    finally:
        if failure is not None:
            raise failure


def discover_fiscal(conn):
    if is_fixture(conn):
        return {
            "status": "unavailable",
            "message": "Live catalog discovery requires a local trial workspace.",
        }
    key = _fiscal_key()
    if not key or not util.find_spec("mcp"):
        return {
            "status": "unavailable",
            "message": "Requires the optional MCP SDK and explicit included-access configuration.",
        }
    try:
        attempt = _begin_fiscal(conn, "MCP tools/list")
    except SourceError as exc:
        return {"status": exc.status, "message": str(exc)}
    try:
        protocol, tools, more = asyncio.run(asyncio.wait_for(_mcp_catalog(key), timeout=20))
        schemas = json.dumps(tools, sort_keys=True, separators=(",", ":"))
        if len(tools) > 512 or len(schemas) > 2_000_000 or key in schemas:
            raise ValueError
    except SourceError as exc:
        return _finish_fiscal(conn, attempt, exc.status, {"message": str(exc), "retry_at": exc.retry_at})
    except Exception:
        # The SDK may include a request/header in exceptions. Retain only the safe diagnostic.
        return _finish_fiscal(
            conn,
            attempt,
            "unavailable",
            {"message": "Fiscal MCP negotiation or bounded catalog retrieval failed."},
        )
    digest = hashlib.sha256(schemas.encode()).hexdigest()
    with write(conn) as seq:
        conn.execute(
            "INSERT OR IGNORE INTO provider_catalogs VALUES (?,?,?,?,?,?,?,?)",
            (uid("catalog"), "Fiscal.ai", protocol, digest, now(), schemas, attempt, seq),
        )
        status = "partial" if more else "ok"
        observation = {
            "schema_hash": digest,
            "tool_count": len(tools),
            "more_pages": more,
            "coverage": "Observed catalog only. Each endpoint requires separate entitlement and semantic verification.",
        }
        conn.execute(
            "UPDATE provider_attempts SET finished_at=?,status=?,observation=?,response_hash=?,commit_seq=? WHERE id=?",
            (now(), status, json.dumps(observation), digest, seq, attempt),
        )
    return {"status": status, "receipt_id": attempt, **observation}
