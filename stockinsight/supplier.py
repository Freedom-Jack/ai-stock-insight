"""TSMC supplier watches in the desk's scheduler, evidence and notification outbox."""

import hashlib
import json
from datetime import datetime, timedelta
from http.client import HTTPException
from urllib.error import HTTPError

from stockwatch import followup, issuer, operator, store, usgs
from stockwatch.config import EXAMPLES
from stockwatch.monitor import DEFAULT_INTERVAL, ISSUER_INTERVAL, _retry_after
from stockwatch.relevance import load_watchlist

from . import delivery, events, evidence, universe
from .db import instant, is_fixture, now, write


SCHEMA = store.SUPPLIER_SCHEMA + """
CREATE TABLE supplier_monitor (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    commit_seq INTEGER NOT NULL REFERENCES commits
);
CREATE TABLE supplier_due (source TEXT PRIMARY KEY, due_at TEXT NOT NULL);
CREATE TABLE supplier_event_links (
    entry_sequence INTEGER NOT NULL REFERENCES supplier_watch_entries(sequence),
    instrument_id TEXT NOT NULL REFERENCES instruments,
    version_id TEXT NOT NULL UNIQUE REFERENCES event_versions,
    PRIMARY KEY(entry_sequence, instrument_id)
);
"""
INTERVALS = {"USGS": DEFAULT_INTERVAL, "TSMC": ISSUER_INTERVAL}
CIKS = {"AMD": "0000002488", "NVDA": "0001045810"}
WATCHLIST = EXAMPLES / "watchlist.json"
QUAKE = "supplier_earthquake_watch"
DISCLOSURE = "supplier_disclosure"
ASSESSMENT = "supplier_assessment"
ENTRIES = store.entry_query(embedded=True)
SOURCE_ERRORS = (ValueError, OSError, HTTPException)


def _scope(db):
    active = {}
    for item in universe.universe(db)["instruments"]:
        ticker = item["ticker"]
        if (
            ticker in CIKS
            and item["cik"] in (None, CIKS[ticker])
            and (item["listing_exchange"], item["security_type"], item["currency"])
            == ("NASDAQ", "STK", "USD")
        ):
            active.setdefault(ticker, []).append(item["id"])
    return active


def _configuration(db):
    return db.execute("SELECT enabled,commit_seq FROM supplier_monitor WHERE singleton=1").fetchone()


def set_enabled(db, enabled):
    if type(enabled) is not bool or is_fixture(db):
        raise ValueError("Use the supplier monitor in a personal workspace.")
    with write(db) as seq:
        old = _configuration(db)
        if old is None or bool(old["enabled"]) != enabled:
            db.execute(
                """INSERT INTO supplier_monitor VALUES(1,?,?)
                   ON CONFLICT(singleton) DO UPDATE SET enabled=excluded.enabled,commit_seq=excluded.commit_seq""",
                (enabled, seq),
            )


def _due(db, stamp):
    times = dict(db.execute("SELECT source,due_at FROM supplier_due"))
    due = [(times.get(source, ""), source) for source in INTERVALS if times.get(source, "") <= stamp]
    return min(due, key=lambda entry: entry[0])[1] if due else None


def _advance(db, source, stamp, seconds, retry_at=None):
    regular = instant((datetime.fromisoformat(stamp) + timedelta(seconds=seconds)).isoformat())
    db.execute(
        """INSERT INTO supplier_due VALUES(?,?)
           ON CONFLICT(source) DO UPDATE SET due_at=excluded.due_at""",
        (source, max(regular, retry_at or regular)),
    )


def _cursor(db):
    return db.execute("SELECT coalesce(max(sequence),0) FROM supplier_watch_entries").fetchone()[0]


def _previous_quake(db, incident):
    return {
        r["instrument_id"]: r
        for r in db.execute(
            """SELECT e.id,e.state,e.instrument_id FROM supplier_watch_entries w
               JOIN supplier_event_links l ON l.entry_sequence=w.sequence
               JOIN event_versions e ON e.id=l.version_id
               WHERE w.incident=? AND e.kind=? ORDER BY w.sequence""",
            (incident, QUAKE),
        )
    }


def incident_events(db, version_id):
    """Keep a listing's distinct public disclosures together without superseding an earthquake."""
    return [row[0] for row in db.execute("""
        SELECT DISTINCT e.event_id FROM supplier_event_links original
        JOIN supplier_watch_entries w ON w.sequence=original.entry_sequence
        JOIN supplier_watch_entries next ON next.incident=w.incident
        JOIN supplier_event_links l ON l.entry_sequence=next.sequence AND l.instrument_id=original.instrument_id
        JOIN event_versions e ON e.id=l.version_id WHERE original.version_id=?""", (version_id,))]


def public_links(db, ref):
    """Return the public relationship and location references frozen with this observation."""
    row = db.execute("""SELECT w.links,i.ticker FROM event_versions e
        JOIN supplier_event_links l ON l.version_id=e.id JOIN supplier_watch_entries w ON w.sequence=l.entry_sequence
        JOIN instruments i ON i.id=l.instrument_id WHERE e.source_ref=?""", (ref,)).fetchone()
    fields = ("site", "site_url", "site_locator", "coordinates_url", "coordinate_locator",
              "source_url", "locator", "scope", "limit", "distance_km", "checked_on")
    if not row:
        return []
    return [{k: link[k] for k in fields if k in link} for link in json.loads(row["links"])
            if link["ticker"] == row["ticker"]]


def source_health(db):
    settings = _configuration(db)
    if not settings or not settings["enabled"]:
        return []
    return [dict(row) for row in db.execute("""
        SELECT d.source AS provider, CASE WHEN h.error IS NOT NULL THEN 'error'
            WHEN h.last_ok IS NOT NULL THEN 'ok' ELSE 'pending' END AS status,
            h.attempt AS finished_at,h.last_ok,d.due_at AS next_at
        FROM supplier_due d LEFT JOIN feed_health h USING(source) ORDER BY d.source""")]


def _quake_text(entry, links, withdrawn):
    if withdrawn:
        return (
            f"{entry['title']}. The latest USGS edition withdrew this TSMC geographic watch "
            "or moved it outside its screening threshold."
        )
    relationships = " ".join(
        f"{link['site']} is about {link['distance_km']} km from the epicenter. "
        f"{link['scope']} {link['limit']}"
        for link in links
    )
    return (
        f"{entry['title']}. TSMC supply chain watch. {relationships} "
        "Geographic proximity alone cannot establish facility disruption or customer impact. "
        "Look for a dated TSMC operating update."
    )


def _publish(db, seq, entry, listing_id, links, previous):
    facts = json.loads(entry["facts"])
    actual = entry["occurred_at"]
    state = "occurred"
    if entry["kind"] == "issuer_candidate":
        kind = DISCLOSURE
        origin = "tsmc_earthquake_disclosure"
        text = (
            f"{entry['title']}\n{facts['excerpt']}\n"
            f"TSMC supply chain follow-up. {facts['uncertainty']} {facts['next_check']}"
        )
    elif entry["kind"] == "operator_update":
        kind = ASSESSMENT
        origin = "supplier_operator_assessment"
        text = (
            f"Reviewed TSMC supply chain assessment · {entry['status']}. {facts['locator']}\n"
            f"{facts['uncertainty']} {facts['next_check']}"
        )
    else:
        kind = QUAKE
        origin = "usgs_earthquake"
        withdrawn = entry["status"] == "withdrawn" or not links
        if withdrawn:
            state, actual = "cancelled", None
        text = _quake_text(entry, links, withdrawn)
    stamp = entry["seen_at"]
    projection = json.dumps(
        {
            "source_fingerprint": entry["fingerprint"], "watchlist": entry["watchlist_hash"],
            "incident": entry["incident"], "facts": facts, "links": links, "text": text,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode()
    # Multiple notices can cite the same exchange URL and timestamp. Keep one
    # ordered, immutable projection per source record instead of conflating them.
    retention = "supplier_observation_and_hash"
    document = evidence._save(
        db, seq, listing_id, origin, entry["url"], entry["title"],
        (hashlib.sha256(projection).hexdigest(), None),
        [(f"{entry['id']} @ {entry['revision']}", text, stamp, None)], stamp,
        published=entry["revision"], precision="instant", retention=retention,
    )
    ref = db.execute("SELECT id FROM evidence_passages WHERE document_id=?", (document,)).fetchone()[0]
    event = events.append_event(
        db, listing_id, kind=kind, state=state, occurred_at=actual,
        precision="instant" if actual else "unknown", source_ref=ref,
        supersedes=previous["id"] if previous else None, _commit_seq=seq,
    )
    db.execute(
        "INSERT INTO supplier_event_links VALUES(?,?,?)",
        (entry["sequence"], listing_id, event["id"]),
    )
    return event["id"]


def _project(db, seq, after, scope):
    entries = db.execute(ENTRIES + " WHERE sequence>? ORDER BY sequence", (after,)).fetchall()
    for index, entry in enumerate(entries):
        if index:
            seq = db.execute("INSERT INTO commits(committed_at) VALUES(?)", (now(),)).lastrowid
        targets = {}
        for link in json.loads(entry["links"]):
            for listing_id in scope.get(link["ticker"], ()):
                targets.setdefault(listing_id, []).append(link)
        previous = {}
        if entry["kind"] in ("earthquake", "withdrawn"):
            previous = _previous_quake(db, entry["incident"])
            for listing_ids in scope.values():
                for listing_id in listing_ids:
                    if listing_id in previous and previous[listing_id]["state"] != "cancelled":
                        targets.setdefault(listing_id, [])
        versions = [
            _publish(db, seq, entry, listing_id, links, previous.get(listing_id))
            for listing_id, links in targets.items()
        ]
        if versions and entry["kind"] != "operator_update":
            delivery.enqueue(
                db, key=f"supplier:{entry['sequence']}", title="Stock Insight supplier watch",
                message="A supplier watch update is ready in your private desk.",
                report_path="/events/" + versions[0], at=entry["seen_at"],
            )


def tick(db, *, clock=now):
    """Run one due shared source check outside the research database write lock."""
    configured = _configuration(db)
    if is_fixture(db) or configured is None or not configured["enabled"]:
        return None
    source = _due(db, instant(clock()))
    if not source or not _scope(db):
        return None
    error, retry_at = None, None
    retry_interval = DEFAULT_INTERVAL
    try:
        if source == "USGS":
            payload = usgs.fetch_feed()
            stamp = instant(clock())
            generated = usgs.generated_at(payload)
            age = datetime.fromisoformat(stamp) - datetime.fromisoformat(generated)
            if age < timedelta(0):
                # A source clock a few seconds ahead can otherwise fail at the same
                # point in every five-minute cycle. Keep the original receipt time.
                retry_interval += 30
                raise ValueError("USGS feed generated after the observation time")
            if age > timedelta(minutes=15):
                raise ValueError("USGS feed is over 15 minutes old.")
            batch = usgs.parse_feed(payload, stamp)
            watchlist = load_watchlist(WATCHLIST)
        else:
            batch = issuer.fetch_bulletins(instant(clock()))
            stamp = instant(clock())
        with write(db) as seq:
            if _configuration(db) != configured or _due(db, stamp) != source:
                return None
            after = _cursor(db)
            if source == "USGS":
                store.save_observations(db, batch, watchlist, poll=(stamp, generated), embedded=True)
            else:
                followup.save_snapshot(db, batch, stamp, embedded=True)
            _project(db, seq, after, _scope(db))
            _advance(db, source, stamp, INTERVALS[source])
    except SOURCE_ERRORS as exc:
        stamp = instant(clock())
        error = str(exc)
        retry_at = _retry_after(exc, stamp)
        if isinstance(exc, HTTPError):
            exc.close()
    if error is not None:
        with write(db):
            if _configuration(db) != configured or _due(db, stamp) != source:
                return None
            store.record_health(db, source, stamp, error=error or "Source check failed.")
            _advance(db, source, stamp, retry_interval, retry_at)
    return source


_REVIEWABLE = """
 WHERE o.kind='issuer_candidate'
   AND EXISTS(SELECT 1 FROM supplier_event_links l JOIN source_memberships m USING(instrument_id)
              WHERE l.entry_sequence=i.sequence AND m.status='active')
   AND (SELECT w.status FROM supplier_watch_entries w JOIN observations p USING(id,revision)
        WHERE w.incident=i.incident AND p.kind!='issuer_candidate' ORDER BY w.sequence DESC LIMIT 1)
       NOT IN ('withdrawn','closed')
   AND NOT EXISTS(SELECT 1 FROM observations p
                  WHERE p.kind='operator_update' AND p.url=o.url AND p.revision=o.revision
                    AND json_extract(p.facts,'$.incident_id')=i.incident)
"""


def review(db, data, *, at=None):
    """Record a user's assessment of a read disclosure, tied to its original evidence."""
    if is_fixture(db):
        raise ValueError("Use the supplier monitor in a personal workspace.")
    stamp = instant(at or now())
    with write(db) as seq:
        candidate = db.execute(
            ENTRIES + _REVIEWABLE + " AND i.sequence=?", (data.get("entry"),),
        ).fetchone()
        if candidate is None:
            raise ValueError("Select a current TSMC disclosure awaiting review.")
        fields = {"locator": 500, "uncertainty": 350, "next_check": 350, "status": 16}
        assessment = {key: data.get(key, "").strip() for key in fields}
        if any(not value or len(value) > fields[key] for key, value in assessment.items()):
            raise ValueError("Supply the source passage, uncertainty and next check.")
        packet = {
            **assessment,
            "incident_id": candidate["incident"], "supplier": "TSMC",
            "published_at": candidate["revision"], "clock_basis": "TWSE disclosure time in Taipei",
            "url": candidate["url"], "title": candidate["title"],
        }
        after = _cursor(db)
        observations = operator.parse_updates(json.dumps([packet]).encode(), stamp)
        store.save_observations(db, observations, embedded=True)
        _project(db, seq, after, _scope(db))


def dashboard(db, cutoff):
    configured = _configuration(db)
    scope = _scope(db)
    watchlist = load_watchlist(WATCHLIST, tickers=sorted(scope) or None)
    return {
        "enabled": bool(configured and configured["enabled"]),
        "tickers": sorted(scope),
        "magnitude": watchlist.min_magnitude,
        "radius": watchlist.radius_km,
        "coverage": watchlist.coverage(cutoff) if scope else "",
        "gaps": store.coverage_gaps(db, cutoff),
        "sources": [
            {
                "name": row["source"], "due_at": row["due_at"], "last_ok": row["last_ok"],
                "error": row["error"],
            }
            for row in db.execute("""
                SELECT d.source,d.due_at,h.last_ok,h.error FROM supplier_due d
                LEFT JOIN feed_health h USING(source) ORDER BY d.source
            """)
        ],
        "review": [
            {**dict(r), "excerpt": json.loads(r["facts"])["excerpt"]}
            for r in db.execute(ENTRIES + _REVIEWABLE + " ORDER BY i.sequence DESC LIMIT 15")
        ],
        "unlinked": followup.unlinked(db, cutoff, limit=15),
    }
