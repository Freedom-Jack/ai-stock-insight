"""Join a regional hazard to dated issuer evidence and optional local positions."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from .model import utc


LINK_FIELDS = {"ticker", "filed_on", "source_url", "locator", "scope", "limit"}


def _read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def _text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected a nonempty {key}")
    return value


def _url(data, key):
    value = _text(data, key)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Expected an HTTPS source in {key}")
    return value


def _rows(data, key):
    rows = data.get(key)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"Expected a list of records in {key}")
    return rows


def _number(data, key, low, high):
    value = data.get(key)
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"{key} must be a number between {low} and {high}")
    return value


def _ticker(row):
    value = _text(row, "ticker")
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,11}", value):
        raise ValueError("Expected an uppercase stock ticker")
    return value


def _distance_km(lat1, lon1, lat2, lon2):
    """Great-circle surface distance on a sphere of mean Earth radius 6371 km."""
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2
    a += math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * (
        math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(min(1, a)))


@dataclass
class Watchlist:
    min_magnitude: float
    radius_km: float
    sites: list
    fingerprint: str

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(sorted({link["ticker"] for site in self.sites for edition in site["editions"]
                             for link in edition["relationships"]}))

    def coverage_gaps(self, as_of: str) -> list[str]:
        active = list(self._active(as_of))
        covered_sites = {site["site"] for site, edition in active}
        covered_tickers = {link["ticker"] for site, edition in active for link in edition["relationships"]}
        gaps = [f"{site['site']} has no active evidence at this cutoff"
                for site in self.sites if site["site"] not in covered_sites]
        missing = sorted(set(self.tickers) - covered_tickers)
        if missing:
            gaps.append(f"No active supplier relationship for {', '.join(missing)}")
        return gaps

    def _active(self, as_of):
        day = utc(as_of)[:10]
        for site in self.sites:
            for edition in site["editions"]:
                if edition["checked_on"] <= day < edition["review_by"]:
                    yield site, edition

    def coverage(self, as_of: str) -> str:
        active = {site["site"]: edition for site, edition in self._active(as_of)}
        coverage = []
        for site in self.sites:
            name = site["site"]
            if name in active:
                edition = active[name]
                tickers = ", ".join(sorted(link["ticker"] for link in edition["relationships"]))
                coverage.append(f"{name}: {tickers} (review by {edition['review_by']} UTC)")
            else:
                coverage.append(f"{name}: unavailable (no active evidence at cutoff)")
        return " | ".join(coverage)

    def match(self, facts: dict, as_of: str) -> list[dict]:
        magnitude = _number(facts, "magnitude", -10, 15)
        lat = _number(facts, "latitude", -90, 90)
        lon = _number(facts, "longitude", -180, 180)
        matches = []
        if magnitude < self.min_magnitude:
            return matches
        for site, edition in self._active(as_of):
            distance = _distance_km(lat, lon, site["latitude"], site["longitude"])
            if distance <= self.radius_km:
                for link in edition["relationships"]:
                    matches.append({
                        **link,
                        "supplier": site["supplier"], "site": site["site"],
                        "distance_km": round(distance), "site_url": edition["site_url"],
                        "screen_latitude": site["latitude"], "screen_longitude": site["longitude"],
                        "min_magnitude": self.min_magnitude, "radius_km": self.radius_km,
                        "site_locator": edition["site_locator"],
                        "coordinate_basis": site["coordinate_basis"],
                        "coordinates_url": site["coordinates_url"],
                        "coordinate_locator": site["coordinate_locator"],
                        "checked_on": edition["checked_on"], "review_by": edition["review_by"],
                    })
        return matches


def load_watchlist(path, *, tickers=None, min_magnitude=None, radius_km=None) -> Watchlist:
    data = _read(path)
    sites = _rows(data, "sites")
    site_names = set()
    for site in sites:
        name = _text(site, "site")
        if name in site_names:
            raise ValueError("Repeated site name")
        site_names.add(name)
        if _text(site, "supplier") != "TSMC":
            raise ValueError("This playbook supports only the TSMC operator")
        for key in ("coordinate_basis", "coordinate_locator"):
            _text(site, key)
        _url(site, "coordinates_url")
        _number(site, "latitude", -90, 90)
        _number(site, "longitude", -180, 180)
        previous_end = date.min
        for edition in _rows(site, "editions"):
            checked = date.fromisoformat(_text(edition, "checked_on"))
            end = date.fromisoformat(_text(edition, "review_by"))
            if checked < previous_end or not timedelta(0) < end - checked <= timedelta(days=100):
                raise ValueError("Use ordered, disjoint evidence windows of at most 100 days")
            previous_end = end
            edition["checked_on"], edition["review_by"] = checked.isoformat(), end.isoformat()
            _url(edition, "site_url")
            _text(edition, "site_locator")
            edition_tickers = set()
            for link in _rows(edition, "relationships"):
                if link.keys() != LINK_FIELDS:
                    raise ValueError("Watchlist relationships accept only public evidence fields")
                ticker = _ticker(link)
                filed = date.fromisoformat(_text(link, "filed_on"))
                # A date-only filing becomes eligible the next UTC day.
                if ticker in edition_tickers or filed >= checked:
                    raise ValueError("Repeated ticker or evidence unavailable at the start of its window")
                edition_tickers.add(ticker)
                _url(link, "source_url")
                for key in ("scope", "limit", "locator"):
                    _text(link, key)
            if not edition_tickers:
                raise ValueError("Each watchlist edition needs a documented relationship")
    if not sites:
        raise ValueError("Expected at least one monitored site")
    if not any(site["editions"] for site in sites):
        raise ValueError("Expected at least one dated edition with a documented relationship")
    if tickers is not None:
        if not isinstance(tickers, (list, tuple)) or not tickers or not all(isinstance(t, str) for t in tickers):
            raise ValueError("Select one or more ticker symbols")
        selected = set(tickers)
        available = {link["ticker"] for site in sites for edition in site["editions"] for link in edition["relationships"]}
        unsupported = selected - available
        if unsupported:
            raise ValueError(f"No documented relationship for {', '.join(sorted(unsupported))}. "
                             f"Available tickers: {', '.join(sorted(available))}. "
                             "Use --watchlist with dated evidence to add a company.")
        for site in sites:
            for edition in site["editions"]:
                edition["relationships"] = [link for link in edition["relationships"] if link["ticker"] in selected]
            site["editions"] = [edition for edition in site["editions"] if edition["relationships"]]
        sites = data["sites"] = [site for site in sites if site["editions"]]
    if min_magnitude is not None:
        data["min_magnitude"] = min_magnitude
    if radius_km is not None:
        data["radius_km"] = radius_km
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # The live summary excludes smaller events, whatever a user asks to screen.
    return Watchlist(_number(data, "min_magnitude", 4.5, 12),
                     _number(data, "radius_km", 0, 20015), sites, fingerprint)


def _money(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,2})?", value):
        raise ValueError(f"{key} must be a nonnegative USD decimal string with at most two cents digits")
    return Decimal(value)


def portfolio_context(path, tickers, as_of: str) -> str:
    """Display private, direct capital at the supplied cutoff; the caller never persists this."""
    snapshot = _read(path)
    if snapshot.get("currency") != "USD" or type(snapshot.get("hypothetical")) is not bool:
        raise ValueError("Specify USD and whether this snapshot is hypothetical")
    _text(snapshot, "account_scope")
    scenario = snapshot.get("kind") == "sample_allocation"
    if scenario and (not snapshot["hypothetical"] or "valued_at" in snapshot or "available_at" in snapshot):
        raise ValueError("A sample allocation needs hypothetical fixed amounts without snapshot dates")
    cutoff = utc(as_of)
    positions = {}
    for row in _rows(snapshot, "positions"):
        ticker = _ticker(row)
        if row.get("type") != "stock" or ticker in positions:
            raise ValueError("Expected unique tickers for directly held common stock")
        positions[ticker] = _money(row, "value")
    total = _money(snapshot, "total")
    if total <= 0 or _money(snapshot, "cash") + sum(positions.values()) != total:
        raise ValueError("Cash and positions must reconcile to a positive account total")
    if scenario:
        label = "Hypothetical sample allocation, fixed USD amounts"
    else:
        valued_at = utc(_text(snapshot, "valued_at"))
        available_at = utc(_text(snapshot, "available_at"))
        if available_at < valued_at:
            raise ValueError("Portfolio availability predates the valuation")
        if available_at > cutoff:
            return "Watchlist only. The portfolio snapshot was available after this cutoff."
        age = datetime.fromisoformat(cutoff) - datetime.fromisoformat(valued_at)
        if age > timedelta(days=7):
            return f"Watchlist only. The {valued_at[:10]} portfolio valuation is older than seven days."
        label = ("Hypothetical" if snapshot["hypothetical"] else "Local") + f" USD account at {valued_at}"
    linked = {ticker: positions[ticker] for ticker in set(tickers) & positions.keys()}
    capital = sum(linked.values(), Decimal(0))
    breakdown = ", ".join(f"{ticker} ${value:,.2f}" for ticker, value in
                          sorted(linked.items(), key=lambda item: (-item[1], item[0])))
    return (
        f"{label}: ${capital:,.2f} of ${total:,.2f} "
        f"({capital * 100 / total:.2f}%) in direct holdings for review. "
        + (f"Held names: {breakdown}." if linked else "No directly held names matched.")
    )
