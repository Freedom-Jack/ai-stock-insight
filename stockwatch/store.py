"""A local inbox. Each source batch and the decisions it caused commit together."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import Observation, utc
from .relevance import Watchlist, _distance_km


RULE = "foundry-quake/1"
WINDOW = timedelta(hours=24)
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
    id TEXT, revision TEXT, occurred_at TEXT NOT NULL, seen_at TEXT NOT NULL,
    source TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
    facts TEXT NOT NULL, fingerprint TEXT NOT NULL, rule TEXT NOT NULL,
    watchlist_hash TEXT NOT NULL, decision TEXT NOT NULL, PRIMARY KEY(id, revision)
);
CREATE INDEX IF NOT EXISTS receipts ON observations(seen_at);
CREATE TABLE IF NOT EXISTS inbox (
    sequence INTEGER PRIMARY KEY, incident TEXT NOT NULL, status TEXT NOT NULL,
    id TEXT NOT NULL, revision TEXT NOT NULL, links TEXT NOT NULL,
    UNIQUE(id, revision), FOREIGN KEY(id, revision) REFERENCES observations(id, revision)
);
CREATE INDEX IF NOT EXISTS incident_entries ON inbox(incident, sequence);
CREATE TABLE IF NOT EXISTS feed_health (
    source TEXT PRIMARY KEY, attempt TEXT NOT NULL, last_ok TEXT,
    generated TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS issuer_documents (
    edition INTEGER PRIMARY KEY, doc_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
    published_at TEXT NOT NULL, first_seen TEXT NOT NULL, url TEXT NOT NULL,
    title TEXT NOT NULL, excerpt TEXT NOT NULL, event_date TEXT,
    UNIQUE(doc_key, fingerprint)
);
CREATE TABLE IF NOT EXISTS issuer_reviews (
    sequence INTEGER PRIMARY KEY, edition INTEGER NOT NULL REFERENCES issuer_documents(edition),
    decided_at TEXT NOT NULL, reason TEXT NOT NULL, incident TEXT
);
CREATE INDEX IF NOT EXISTS issuer_decisions ON issuer_reviews(edition, sequence);
CREATE TABLE IF NOT EXISTS source_gaps (
    source TEXT PRIMARY KEY, noticed TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL
);
"""


def connect(path: Path, mode: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        with db:
            db.execute("INSERT OR IGNORE INTO settings VALUES ('mode', ?)", (mode,))
            actual = db.execute("SELECT value FROM settings WHERE name='mode'").fetchone()[0]
            if actual != mode:
                raise ValueError(f"database belongs to {actual} mode, requested {mode}")
    except Exception:
        db.close()
        raise
    return db


def _json(value) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(obs: Observation) -> str:
    # Receipt can change on a retry. The source's version must stay identical.
    content = [obs.source, obs.kind, obs.occurred_at, obs.url, obs.title, obs.facts]
    return hashlib.sha256(_json(content).encode()).hexdigest()


def _identities(links: list[dict]) -> set[tuple]:
    return {(link["ticker"], link["supplier"], link["site"]) for link in links}


ENTRY = """
SELECT i.incident, i.sequence, i.status, i.links, o.*
FROM inbox AS i JOIN observations AS o USING(id, revision)
"""


def _operator_decision(obs, prev):
    incident = obs.facts["incident_id"]
    if not prev:
        raise ValueError(f"unknown watch {incident}; ingest the triggering event first")
    links = json.loads(prev["links"])
    if {x["supplier"] for x in links} != {obs.facts["supplier"]}:
        raise ValueError(f"operator does not cover the supplier in {incident}")
    if prev["kind"] == "operator_update":
        if obs.revision < prev["revision"]:
            return "older operator statement", None
        if obs.revision == prev["revision"] and obs.facts["status"] != prev["status"]:
            raise ValueError("conflicting operator assessments at the same source time; review the statements")
    elif obs.revision < prev["occurred_at"]:
        raise ValueError("operator statement predates the triggering event")
    return "operator statement", (incident, obs.facts["status"], links)


def _quake_decision(db, obs, watchlist, prev):
    incident = obs.id
    if obs.kind not in ("earthquake", "withdrawn"):
        raise ValueError(f"unsupported observation kind {obs.kind}")
    newer = db.execute("SELECT MAX(revision) FROM observations WHERE id=?", (obs.id,)).fetchone()[0]
    if newer and obs.revision < newer:
        return "older source revision", None
    if prev and prev["kind"] == "operator_update":
        return "operational watch now follows operator evidence", None

    links = []
    if obs.kind == "earthquake":
        if prev:
            # A later settings change or evidence expiry cannot retract an
            # earlier observation. Re-screen revisions against the frozen sites.
            original = db.execute(ENTRY + " WHERE incident=? ORDER BY sequence LIMIT 1", (incident,)).fetchone()
            prior_links = json.loads(original["links"])
            if any("screen_latitude" not in link for link in prior_links):
                if original["watchlist_hash"] != watchlist.fingerprint:
                    return "legacy screen parameters unavailable for revision; review", None
                identities = _identities(prior_links)
                links = [link for link in watchlist.match(obs.facts, obs.occurred_at)
                         if (link["ticker"], link["supplier"], link["site"]) in identities]
            else:
                for link in prior_links:
                    distance = _distance_km(obs.facts["latitude"], obs.facts["longitude"],
                                            link["screen_latitude"], link["screen_longitude"])
                    if obs.facts["magnitude"] >= link["min_magnitude"] and distance <= link["radius_km"]:
                        links.append({**link, "distance_km": round(distance)})
        else:
            active = _identities(watchlist.match(obs.facts, obs.seen_at))
            links = [link for link in watchlist.match(obs.facts, obs.occurred_at)
                     if (link["ticker"], link["supplier"], link["site"]) in active]
    if not links:
        if prev and prev["status"] != "withdrawn":
            return "screen no longer matches", (incident, "withdrawn", json.loads(prev["links"]))
        return "outside active screen", None
    if prev and prev["status"] != "withdrawn" and _identities(links) == _identities(json.loads(prev["links"])):
        return "same exposure", None
    if (not prev or prev["status"] == "withdrawn") and (
        datetime.fromisoformat(obs.seen_at) - datetime.fromisoformat(obs.occurred_at) > WINDOW
    ):
        return "discovery window elapsed", None
    return "geographic and supplier match", (incident, "watch", links)


def record_health(db, source: str, when: str, generated: str | None = None,
                  error: str | None = None):
    """Update one source checkpoint inside the caller's transaction."""
    when = utc(when)
    generated = utc(generated) if generated else None
    previous = db.execute("SELECT * FROM feed_health WHERE source=?", (source,)).fetchone()
    if previous and when < previous["attempt"]:
        return
    if previous and previous["last_ok"] and not error:
        if generated and previous["generated"] and generated < previous["generated"]:
            raise ValueError(f"{source} snapshot regressed behind the last valid edition")
        gap = None
        if source == "USGS":
            covered_from = utc((datetime.fromisoformat(when) - timedelta(days=1)).isoformat())
            if previous["last_ok"] < covered_from:
                gap = (previous["last_ok"], covered_from)
        if source == "TSMC" and generated and previous["generated"]:
            taipei = timezone(timedelta(hours=8))
            first = datetime.fromisoformat(previous["generated"]).astimezone(taipei).date() + timedelta(days=1)
            last = datetime.fromisoformat(generated).astimezone(taipei).date() - timedelta(days=1)
            if first <= last:
                gap = (first.isoformat(), last.isoformat())
        if gap:
            db.execute("INSERT INTO source_gaps VALUES (?,?,?,?) ON CONFLICT(source) DO UPDATE SET "
                       "noticed=excluded.noticed, start=excluded.start, end=excluded.end", (source, when, *gap))
    # A slower overlapping poll must not overwrite a newer health result.
    db.execute("""
        INSERT INTO feed_health VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET attempt=excluded.attempt,
            last_ok=coalesce(excluded.last_ok, feed_health.last_ok),
            generated=coalesce(excluded.generated, feed_health.generated), error=excluded.error
        WHERE excluded.attempt >= feed_health.attempt
    """, (source, when, None if error else when, generated, error))


def coverage_gaps(db, as_of=None) -> list[str]:
    """Latest possible hole per rolling source, including after service recovers."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_gaps'").fetchone():
        return []
    messages = []
    for row in db.execute("SELECT * FROM source_gaps WHERE (? IS NULL OR noticed<=?) ORDER BY source",
                          (as_of, utc(as_of) if as_of else None)):
        if row["source"] == "USGS":
            messages.append(f"Possible USGS gap from {row['start']} to {row['end']}. "
                            "Successful receipts were more than 24 hours apart.")
        else:
            messages.append(f"Possible TWSE gap on Taipei report dates {row['start']} through {row['end']}. "
                            "Stockwatch did not capture these daily editions. Quiet days are possible.")
    return messages


def last_evidence_receipt(db):
    return db.execute("""
        SELECT MAX(stamp) FROM (
            SELECT MAX(seen_at) AS stamp FROM observations UNION ALL
            SELECT MAX(first_seen) FROM issuer_documents UNION ALL
            SELECT MAX(decided_at) FROM issuer_reviews
        )
    """).fetchone()[0]


def failed_poll(db, when: str, error: str, *, source: str = "USGS") -> None:
    with db:
        record_health(db, source, when, error=error)


def ingest(db, observations: list[Observation], watchlist: Watchlist | None = None,
           *, poll: tuple[str, str] | None = None) -> tuple[int, int]:
    """Counts new observations and inbox entries. Repeating a batch is a no-op."""
    added = entries = 0
    with db:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        latest_receipt = last_evidence_receipt(db)
        for obs in sorted(observations, key=lambda o: (o.seen_at, o.kind != "earthquake", o.revision, o.id)):
            fingerprint = _fingerprint(obs)
            old = db.execute("SELECT fingerprint FROM observations WHERE id=? AND revision=?",
                             (obs.id, obs.revision)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError(f"conflicting contents for {obs.id} at {obs.revision}")
                continue
            if latest_receipt and obs.seen_at < latest_receipt:
                raise ValueError("new observation would backdate the ledger; check the receipt clock")
            incident = obs.facts.get("incident_id", obs.id)
            # Discovery adds a reading item while the last assessed watch state
            # continues to govern source corrections and subsequent assessments.
            prev = db.execute(ENTRY + " WHERE incident=? AND kind!='issuer_candidate' ORDER BY sequence DESC LIMIT 1",
                              (incident,)).fetchone()
            if obs.kind == "operator_update":
                reason, update = _operator_decision(obs, prev)
                config_hash = prev["watchlist_hash"]
            elif obs.kind == "issuer_candidate":
                if not prev or prev["status"] in {"closed", "withdrawn"}:
                    raise ValueError("issuer candidate requires an open watch")
                reason = "issuer statement for review; operational assessment unchanged"
                update = (incident, prev["status"], json.loads(prev["links"]))
                config_hash = prev["watchlist_hash"]
            else:
                if watchlist is None:
                    raise ValueError("earthquake screening requires a watchlist")
                reason, update = _quake_decision(db, obs, watchlist, prev)
                config_hash = prev["watchlist_hash"] if prev else watchlist.fingerprint
            db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (obs.id, obs.revision, obs.occurred_at, obs.seen_at, obs.source, obs.url,
                        obs.title, obs.kind, _json(obs.facts), fingerprint, RULE, config_hash, reason))
            added += 1
            if update:
                incident, status, links = update
                db.execute("INSERT INTO inbox(incident,status,id,revision,links) VALUES (?,?,?,?,?)",
                           (incident, status, obs.id, obs.revision, _json(links)))
                entries += 1
        if poll:
            record_health(db, "USGS", *poll)
    return added, entries


def timeline(db, as_of: str, *, history: bool, after_sequence=0) -> list:
    rows = db.execute(ENTRY + " WHERE seen_at<=? AND sequence>? ORDER BY seen_at, sequence",
                      (utc(as_of), after_sequence)).fetchall()
    if history:
        return rows
    latest = {row["incident"]: row for row in rows}
    return sorted(latest.values(), key=lambda row: row["seen_at"], reverse=True)
