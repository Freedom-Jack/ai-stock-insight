"""TSMC's material disclosures in the Taiwan Stock Exchange daily open-data file."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
import ssl
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .model import utc


FEED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
TAIPEI = timezone(timedelta(hours=8))
MAX_BYTES = 8 * 1024 * 1024
QUAKE = re.compile(r"地震|強震|餘震")
# Only an explicitly dated quake can link to a watch. The filing's separate
# "date of occurrence" field can instead be the date of the board's update.
QUAKE_DATE = re.compile(
    r"(?<![0-9/])(?:(?P<year>[0-9]{2,4})[年/])?"
    r"(?P<month>[0-9]{1,2})[月/](?P<day>[0-9]{1,2})日?"
    r"(?:台灣|臺灣|花蓮|嘉義|發生|發生的|之|的|大|強烈|規模[0-9.]+)*(?:地震|強震|餘震)"
)
OPERATIONS = re.compile(r"晶圓|廠區|復原|恢復|生產線|停工|受損|疏散|營運|設備|供電")
TAIWAN = r"(?:[台臺]灣|花蓮|嘉義|[台臺]南|宜蘭|新竹|[台臺]中|[台臺]東|南投|高雄|屏東)"
TAIWAN_QUAKE = re.compile(TAIWAN + r"[^。！？；，]{0,36}?(?:地震|強震|餘震)" +
                          r"|(?:地震|強震|餘震)(?:發生|震央)(?:於|在|位於)" + TAIWAN)
OVERSEAS_QUAKE = re.compile(r"(?:海外|境外|外國|日本|熊本|美國|美國亞利桑那|中國大陸|德國|印度|菲律賓)"
                            r"[^。！？；，]{0,36}(?:地震|強震|餘震)")


@dataclass(frozen=True)
class Bulletin:
    key: str
    url: str
    published_at: str
    title: str
    excerpt: str
    event_date: str | None


@dataclass(frozen=True)
class IssuerSnapshot:
    report_date: str  # TWSE edition, Taipei calendar day. No intraday generation clock.
    bulletins: list[Bulletin]


def _roc_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{7}", value):
        raise ValueError("TWSE date must be a seven-digit Republic of China date")
    return date(1911 + int(value[:3]), int(value[3:5]), int(value[5:]))


def _archive_url(day: date, title: str) -> str:
    params = {"firstin": "true", "TYPEK": "all", "year": day.year - 1911, "month": f"{day.month:02}",
              "b_date": f"{day.day:02}", "e_date": f"{day.day:02}", "step": "1", "off": "1", "co_id": "2330"}
    # TWSE omits the individual MOPS sequence number. The date+issuer search
    # lists the official timestamp, title and button opening the full statement.
    return MOPS_URL + "?" + urlencode(params) + "#:~:text=" + quote(title, safe="")


def is_bulletin_url(url: str) -> bool:
    """Only issuer 2330's single-day historical lookup or an individual filing."""
    if not isinstance(url, str) or not url.isascii() or not url.isprintable():
        return False
    try:
        parts = urlsplit(url)
        params = parse_qs(parts.query, strict_parsing=True, keep_blank_values=True)
        if (parts.scheme != "https" or parts.netloc != "mopsov.twse.com.tw" or
                parts.path != "/mops/web/ajax_t05st01" or any(len(v) != 1 for v in params.values())):
            return False
        args = {key: values[0] for key, values in params.items()}
        if args.get("co_id") != "2330" or args.get("firstin") != "true":
            return False
        if args.get("step") == "1":
            if (set(args) != {"firstin", "TYPEK", "year", "month", "b_date", "e_date", "step", "off", "co_id"}
                    or args["TYPEK"] != "all" or args["off"] != "1" or args["b_date"] != args["e_date"]
                    or not re.fullmatch(r"[0-9]{3}", args["year"])
                    or not re.fullmatch(r"[0-9]{2}", args["month"])
                    or not re.fullmatch(r"[0-9]{2}", args["b_date"])):
                return False
            _roc_date(args["year"] + args["month"] + args["b_date"])
            return True
        if (set(args) != {"firstin", "TYPEK", "co_id", "step", "spoke_date", "spoke_time", "seq_no"}
                or args["step"] != "2" or args["TYPEK"] != "sii" or not re.fullmatch(r"[1-9][0-9]*", args["seq_no"])
                or not re.fullmatch(r"[0-9]{8}", args["spoke_date"]) or not re.fullmatch(r"[0-9]{6}", args["spoke_time"])):
            return False
        datetime.strptime(args["spoke_date"] + args["spoke_time"], "%Y%m%d%H%M%S")
        return True
    except (ValueError, OverflowError):
        return False


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing TWSE {key} field")
    cleaned = " ".join(value.split())
    if not cleaned.isprintable():
        raise ValueError("invalid control character in TWSE disclosure")
    # Reassemble Chinese words broken across wrap columns on MOPS.
    return re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", cleaned)


def _quake_day(text: str, filing_day: date) -> str | None:
    days = set()
    for match in QUAKE_DATE.finditer(text):
        if re.search(r"去年|前年|往年|多年前", text[max(0, match.start() - 8):match.start()]):
            return None
        year = int(match["year"]) if match["year"] else filing_day.year
        if match["year"] and len(match["year"]) < 4:
            year += 1911
        try:
            day = date(year, int(match["month"]), int(match["day"]))
            if not match["year"] and day > filing_day:
                day = day.replace(year=year - 1)
        except ValueError:
            return None
        if day > filing_day or (not match["year"] and (filing_day - day).days > 45):
            return None
        days.add(day.isoformat())
    return next(iter(days)) if len(days) == 1 else None


def _bulletin(row: dict, filing_day: date, seen_at: str) -> Bulletin | None:
    title = _text(row, "主旨")
    if len(title) > 1000:
        raise ValueError("TWSE filing title is too long for a traceable source locator")
    body = _text(row, "說明")
    clock = _text(row, "發言時間")
    if not re.fullmatch(r"[0-9]{1,6}", clock):
        raise ValueError("invalid TWSE filing time")
    clock = clock.zfill(6)  # 7:00:04 is "70004" in the JSON.
    published = datetime.combine(filing_day, datetime.strptime(clock, "%H%M%S").time(), tzinfo=TAIPEI)
    published_at = utc(published.isoformat())
    if published_at > seen_at:
        raise ValueError("TWSE filing time is in the future")
    statement = title + "。" + body
    event_date = _quake_day(statement, filing_day)
    if not QUAKE.search(title) and not (event_date and OPERATIONS.search(body)):
        return None
    if not TAIWAN_QUAKE.search(statement) or OVERSEAS_QUAKE.search(statement):
        event_date = None
    sentences = re.split(r"(?<=[。！？])", body)
    # Use a source passage about operations, avoiding the filing form preamble.
    # A form may contain the entire first paragraph before its first full stop.
    excerpts = [s.strip() for s in sentences if OPERATIONS.search(s)]
    excerpt = title
    if excerpts:
        excerpt = excerpts[0]
        if "其他應敘明事項" in excerpt:
            excerpt = excerpt.rsplit("：", 1)[-1].strip() or title
    if len(excerpt) > 240:
        excerpt = excerpt[:239] + "…"
    return Bulletin(f"twse:2330:{filing_day:%Y%m%d}T{clock}", _archive_url(filing_day, title),
                    published_at, title, excerpt, event_date)


def parse_bulletins(payload: bytes, seen_at: str) -> IssuerSnapshot:
    if len(payload) > MAX_BYTES:
        raise ValueError("TWSE response exceeds the size limit")
    seen_at = utc(seen_at)
    today = datetime.fromisoformat(seen_at).astimezone(TAIPEI).date()
    try:
        rows = json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid TWSE JSON") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("expected a nonempty dated TWSE daily disclosure file")
    edition = None
    bulletins = {}
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise ValueError("invalid TWSE record")
        # TWSE currently publishes "主旨 " with a trailing space.
        row = {k.strip(): v for k, v in raw_row.items()}
        if (len(row) != len(raw_row) or
                not {"出表日期", "發言日期", "發言時間", "公司代號", "主旨", "說明"} <= row.keys()):
            raise ValueError("unrecognized TWSE daily disclosure schema")
        report_date = _roc_date(row.get("出表日期"))
        if not 0 <= (today - report_date).days <= 1:
            raise ValueError(f"TWSE daily edition {report_date} is stale or future-dated in Taipei")
        if edition and edition != report_date:
            raise ValueError("mixed TWSE daily editions")
        edition = report_date
        day = _roc_date(row.get("發言日期"))
        if day > report_date:
            raise ValueError("TWSE filing day is later than the daily edition")
        if _text(row, "公司代號") != "2330":
            continue
        bulletin = _bulletin(row, day, seen_at)
        if bulletin:
            if bulletin.key in bulletins and bulletins[bulletin.key] != bulletin:
                raise ValueError("conflicting TWSE issuer filings with the same publication second")
            bulletins[bulletin.key] = bulletin
    return IssuerSnapshot(edition.isoformat(), list(bulletins.values()))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_bulletins(seen_at: str) -> IssuerSnapshot:
    """Read the fixed public API, verifying TLS with the local trust store."""
    request = Request(FEED_URL, headers={"User-Agent": "Stockwatch/1.0 (public issuer monitor)",
                                         "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError(f"TWSE returned HTTP {response.status}")
            payload = response.read(MAX_BYTES + 1)
    except URLError as exc:
        # Python 3.13+ OpenSSL can reject TWSE's legacy intermediate. The OS
        # TLS client (Schannel on Windows) can validate the same host and chain.
        if not isinstance(exc.reason, ssl.SSLCertVerificationError) or (
                exc.reason.verify_message != "Missing Subject Key Identifier"):
            raise
        try:
            result = subprocess.run(
                ["curl", "--disable", "--silent", "--show-error", "--fail", "--proto", "=https",
                 "--max-time", "15", "--max-filesize", str(MAX_BYTES),
                 "--write-out", "\nSTOCKWATCH_HTTP %{http_code} %header{retry-after}",
                 "--user-agent", request.get_header("User-agent"), FEED_URL],
                capture_output=True, timeout=17, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as curl_error:
            raise OSError("TWSE TLS compatibility check requires a working system curl") from curl_error
        payload, separator, trailer = result.stdout.rpartition(b"\nSTOCKWATCH_HTTP ")
        code, _, hint = trailer.partition(b" ")
        if separator and code.isdigit() and 300 <= int(code) <= 599:
            headers = {"Retry-After": hint.decode("ascii", errors="replace").strip()} if hint else {}
            error = HTTPError(FEED_URL, int(code), "TWSE request failed", headers, None)
            error.close()  # This synthetic HTTPError has no response body to read.
            raise error
        if result.returncode or not separator or code != b"200":
            raise OSError(f"TWSE system HTTPS request failed (curl {result.returncode})")
    return parse_bulletins(payload, seen_at)
