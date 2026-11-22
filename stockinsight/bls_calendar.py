"""Two named BLS releases from the agency's published iCalendar schedule."""

import json
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .db import instant

HOST = "www.bls.gov"
PATH = "/schedule/news_release/bls.ics"
ZONE = "America/New_York"


def _time(field, default_zone):
    params, value = field
    if params.get("VALUE") == "DATE" or re.fullmatch(r"[0-9]{8}", value):
        return datetime.strptime(value, "%Y%m%d").date().isoformat(), "day", None
    clock = datetime.strptime(value.removesuffix("Z"), "%Y%m%dT%H%M%S")
    label = "UTC" if value.endswith("Z") else params.get("TZID", default_zone)
    if label not in ("America/New_York", "US/Eastern", "Eastern Standard Time", "UTC"):
        raise ValueError("The BLS release time requires an explicit recognized timezone.")
    zone = ZoneInfo("UTC" if label == "UTC" else ZONE)
    first = clock.replace(tzinfo=zone)
    if (
        first.utcoffset() != first.replace(fold=1).utcoffset()
        or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != clock
    ):
        raise ValueError("Ambiguous or nonexistent local BLS release time.")
    return instant(first.isoformat()), "instant", zone.key


def rows(raw, received):
    unfolded = re.sub(r"\r?\n[ \t]", "", raw)
    if not unfolded.startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in unfolded:
        raise ValueError("Invalid BLS calendar container.")
    timezone_line = re.search(r"^X-WR-TIMEZONE:([^\r\n]+)", unfolded, re.MULTILINE)
    default_zone = timezone_line[1] if timezone_line else None
    entries = {}
    records = re.findall(r"^BEGIN:VEVENT\r?\n(.*?)^END:VEVENT\s*$", unfolded, re.DOTALL | re.MULTILINE)
    if len(records) > 1500:
        raise ValueError("BLS calendar exceeds the bounded release count.")
    for record in records:
        fields = {}
        for line in record.splitlines():
            head, sep, value = line.partition(":")
            if not sep:
                continue
            key, *params = head.split(";")
            if key not in ("SUMMARY", "UID", "DTSTART", "DTEND", "STATUS", "SEQUENCE"):
                continue
            if key in fields:
                raise ValueError("Duplicate calendar field.")
            fields[key] = (
                {k: v.strip('"') for param in params for k, eq, v in [param.partition("=")] if eq},
                value,
            )
        summary = fields.get("SUMMARY", ({}, ""))[1]
        match = re.fullmatch(
            r"(Consumer Price Index|Employment Situation)\s+(?:for\s+)?([A-Za-z]+)\s+(20\d{2})",
            summary.strip(),
            re.IGNORECASE,
        )
        if not match:
            continue
        period = datetime.strptime(match[2] + " " + match[3], "%B %Y").strftime("%Y-%m")
        series = "cpi" if match[1].casefold().startswith("consumer") else "employment"
        uid = fields.get("UID", ({}, ""))[1]
        if not uid or len(uid) > 512:
            raise ValueError("Missing BLS calendar identity.")
        state = {"CONFIRMED": "confirmed", "TENTATIVE": "tentative", "CANCELLED": "cancelled"}.get(
            fields.get("STATUS", ({}, "CONFIRMED"))[1]
        )
        if not state:
            raise ValueError("Unrecognized BLS publication status.")
        start = end = tz = None
        precision = "unknown"
        if "DTSTART" in fields and state != "cancelled":
            start, precision, tz = _time(fields["DTSTART"], default_zone)
            if "DTEND" in fields:
                end, end_precision, _ = _time(fields["DTEND"], default_zone)
                if end_precision != precision or end < start:
                    raise ValueError("Invalid BLS release interval.")
                # RFC 5545 DTEND for a date is exclusive, while the desk stores inclusive calendar days.
                if precision == "day":
                    end = (datetime.fromisoformat(end) - timedelta(days=1)).date().isoformat()
                    if end < start:
                        raise ValueError("Empty all-day BLS release interval.")
        elif state != "cancelled":
            raise ValueError("Published BLS release has no scheduled time.")
        subject = f"bls:{series}:{period}"
        sequence = int(fields.get("SEQUENCE", ({}, "0"))[1])
        if not 0 <= sequence <= 2**31 - 1:
            raise ValueError("Invalid iCalendar sequence.")
        meta = {
            "subject": subject,
            "kind": "inflation_release" if series == "cpi" else "employment_release",
            "state": state,
            "precision": precision,
            "start": start,
            "end": end,
            "timezone": tz,
            "origin": "US Bureau of Labor Statistics",
            "title": summary,
            "relevance": "US inflation can change discount-rate assumptions."
            if series == "cpi"
            else "US employment informs economic demand and policy expectations.",
            "uid": uid,
            "sequence": sequence,
        }
        observation = (json.dumps(meta, sort_keys=True), summary, received, None)
        if subject in entries:
            old_seq, prior = entries[subject]
            if sequence < old_seq:
                continue
            if sequence == old_seq and observation != prior:
                raise ValueError("Conflicting BLS calendar observations at the same sequence.")
        entries[subject] = (sequence, observation)
    return [row for _, row in entries.values()]
