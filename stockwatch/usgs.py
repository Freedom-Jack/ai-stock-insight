"""Read USGS's public, rolling 24-hour M4.5+ GeoJSON summary feed."""

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .model import Observation, utc


FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
MAX_BYTES = 2 * 1024 * 1024
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_feed() -> bytes:
    """One bounded request. Leave retries and health reporting to the caller."""
    request = Request(FEED_URL, headers={"User-Agent": "ai-stock-insight/0.1"})
    with build_opener(_NoRedirect()).open(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"USGS returned HTTP {response.status}")
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("USGS response exceeds the size limit")
    return payload


def _instant(milliseconds: int) -> str:
    if type(milliseconds) is not int:
        raise ValueError("expected an integer Unix timestamp in milliseconds")
    try:
        return utc((EPOCH + timedelta(milliseconds=milliseconds)).isoformat())
    except OverflowError as exc:
        raise ValueError("timestamp out of range") from exc


def _collection(payload: bytes) -> tuple[list, str]:
    if len(payload) > MAX_BYTES:
        raise ValueError("USGS response exceeds the size limit")
    try:
        doc = json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid USGS JSON") from exc
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise ValueError("expected a USGS FeatureCollection")
    meta, features = doc.get("metadata"), doc.get("features")
    if not isinstance(meta, dict) or not isinstance(features, list):
        raise ValueError("USGS metadata or feature list missing")
    if (meta.get("status") != 200 or type(meta.get("count")) is not int
            or meta["count"] != len(features)):
        raise ValueError("USGS status or feature count mismatch")
    return features, _instant(meta.get("generated"))


def generated_at(payload: bytes) -> str:
    """UTC creation time of this feed, including valid, empty feeds."""
    return _collection(payload)[1]


def _number(value, low, high, field):
    # A range check also rejects NaN and infinity. bool subclasses int.
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"invalid {field}")
    return value


def _observation(feature, seen_at, generated):
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise ValueError("expected a GeoJSON Feature")
    event_id = feature.get("id")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", event_id):
        raise ValueError("invalid event ID")
    properties = feature.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("type"), str):
        raise ValueError("missing event properties or type")
    deleted = properties.get("status") == "deleted"
    if properties["type"] != "earthquake" and not deleted:
        return None
    occurred = _instant(properties.get("time"))
    revision = _instant(properties.get("updated"))
    if not occurred <= revision <= generated:
        raise ValueError("inconsistent event, revision and feed times")
    url, title = properties.get("url"), properties.get("title")
    if not isinstance(url, str) or not url.isascii() or not url.isprintable():
        raise ValueError("invalid USGS evidence URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "earthquake.usgs.gov" or " " in url:
        raise ValueError("invalid USGS evidence URL")
    if not isinstance(title, str) or not title.strip() or not title.isprintable():
        raise ValueError("invalid event title")
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise ValueError("expected epicenter point")
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) != 3:
        raise ValueError("invalid epicenter coordinates")
    return Observation(
        id=f"usgs:{event_id}",
        source="USGS",
        kind="withdrawn" if deleted else "earthquake",
        occurred_at=occurred,
        revision=revision,
        seen_at=seen_at,
        url=url,
        title=title,
        facts={
            "longitude": _number(coords[0], -180, 180, "longitude"),
            "latitude": _number(coords[1], -90, 90, "latitude"),
            "magnitude": _number(properties.get("mag"), -5, 12, "magnitude"),
        },
    )


def parse_feed(payload: bytes, seen_at: str) -> list[Observation]:
    """Normalize a complete poll. Any malformed earthquake fails the batch."""
    features, generated = _collection(payload)
    seen_at = utc(seen_at)
    if generated > seen_at:
        raise ValueError("USGS feed generated after the observation time")
    observations = []
    for i, feature in enumerate(features):
        try:
            observation = _observation(feature, seen_at, generated)
        except ValueError as exc:
            raise ValueError(f"USGS feature {i}: {exc}") from exc
        if observation is not None:
            observations.append(observation)
    return observations
