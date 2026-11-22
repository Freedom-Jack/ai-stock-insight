"""Civil report deadlines. Market-relative schedules use the published NYSE calendar."""

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import instant

CALENDAR = "NYSE-US-equities-2026-2028.1"
SOURCE = "https://www.nyse.com/trade/hours-calendars"
CLOSED = {
    2026: "01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25",
    2027: "01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24",
    2028: "01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25",
}
EARLY = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("Choose an installed IANA reporting timezone.") from None


def civil(day, clock, tz):
    """Earlier fold on overlap, first valid minute following a gap."""
    wall = datetime.combine(day, time.fromisoformat(clock))
    for offset in range(24 * 60 + 1):
        trial = wall + timedelta(minutes=offset)
        utc = trial.replace(tzinfo=tz, fold=0).astimezone(UTC)
        if utc.astimezone(tz).replace(tzinfo=None) == trial:
            return utc
    raise ValueError("No eligible local time for this date")


def interpret(text, *, timezone="America/Toronto", cadence="auto", clock="", intent="auto"):
    zone(timezone)
    words = text.casefold()
    if cadence == "auto":
        if re.search(r"after (?:the )?(?:market )?close|closing review|market close", words):
            cadence = "closing"
        elif "pre-market" in words or "premarket" in words or "before the market opens" in words:
            cadence = "premarket"
        else:
            named = [d for d in DAYS if re.search(rf"\b{d}s?\b", words)]
            cadence = named[0] if len(named) == 1 else "sunday" if "weekly" in words else (
                "daily" if re.search(r"\bevery day\b|\bdaily\b", words) else "weekdays")
    if cadence not in (*DAYS, "weekdays", "daily", "closing", "premarket"):
        raise ValueError("Unsupported report frequency")
    if not clock:
        match = re.search(r"\b(?:by|at)\s+(\d{1,2})(?::(\d\d))?\s*(am|pm)?\b", words)
        if match:
            hour, minute, suffix = int(match[1]), int(match[2] or 0), match[3]
            if suffix:
                if not 1 <= hour <= 12:
                    raise ValueError("Invalid local hour")
                hour = hour % 12 + 12 * (suffix == "pm")
            clock = f"{hour:02}:{minute:02}"
        else:
            clock = "16:30" if cadence == "closing" else "18:00" if cadence in DAYS else "08:30"
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ValueError("Choose a 24-hour local time")
    if intent == "auto":
        intent = "start_at" if re.search(r"\b(?:start|begin)(?: checking| research| work)? at\b", words) else "report_by"
    if intent not in ("start_at", "report_by"):
        raise ValueError("Choose start time or report deadline")
    return {"timezone": timezone, "cadence": cadence, "clock": clock, "intent": intent}


def occurrence(day, plan):
    cadence = plan["cadence"]
    if cadence in DAYS and day.weekday() != DAYS.index(cadence):
        return None
    if cadence == "weekdays" and day.weekday() >= 5:
        return None
    clock = plan["clock"]
    tz = zone(plan["timezone"])
    if cadence in ("premarket", "closing"):
        if day.year not in CLOSED:
            raise ValueError("Market calendar coverage ends in 2028. Update the edition before scheduling.")
        if day.weekday() >= 5 or day.strftime("%m-%d") in CLOSED[day.year].split():
            return None
        # Session-relative clocks stay in the exchange zone even when the operator travels.
        tz = zone("America/New_York")
        if cadence == "closing" and day.isoformat() in EARLY:
            clock = (datetime.combine(day, time.fromisoformat(clock)) - timedelta(hours=3)).strftime("%H:%M")
    deadline = civil(day, clock, tz)
    start = deadline - timedelta(minutes=15) if plan["intent"] == "report_by" else deadline
    return instant(start.isoformat()), instant(deadline.isoformat())


def expand(db, plan, at):
    today = datetime.fromisoformat(at).astimezone(zone(plan["timezone"])).date()
    day = date.fromisoformat(plan["expand_on"])
    end = today + timedelta(days=14)
    if day > end:
        return
    slots = []
    while day <= end:
        if plan["cadence"] in ("premarket", "closing") and day.year not in CLOSED:
            break
        pair = occurrence(day, plan)
        if pair and pair[1] >= plan["created_at"]:
            slots.append((plan["id"], *pair))
        day += timedelta(days=1)
    db.executemany(
        "INSERT OR IGNORE INTO goal_deadlines(plan_id,start_at,due_at,state) VALUES(?,?,?,'pending')", slots
    )
    db.execute("UPDATE goal_plans SET expand_on=? WHERE id=?", (day.isoformat(),plan["id"]))
