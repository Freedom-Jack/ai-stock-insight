"""Persist an issuer index snapshot and attach possible follow-ups to open watches."""

import hashlib
from http.client import HTTPException
import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone

from . import issuer
from .model import Observation, now, utc
from .operator import document_url
from .store import ENTRY, failed_poll, ingest, last_evidence_receipt, record_health


SOURCE = "TSMC"
TAIPEI = timezone(timedelta(hours=8))
LOOKBACK = timedelta(days=30)


def _watches(db):
    # Use the latest assessed status, and the latest origin coordinates.
    # Include closed watches in the ambiguity check: a bulletin about two
    # same-day incidents cannot safely be assigned to the one still open.
    rows = db.execute(ENTRY + """
        WHERE sequence = (SELECT MAX(ii.sequence) FROM inbox ii
            JOIN observations oo USING(id, revision) WHERE ii.incident=i.incident AND oo.kind!='issuer_candidate')
    """)
    watches = []
    for row in rows:
        origin = db.execute("SELECT occurred_at, facts FROM observations WHERE id=? "
                            "ORDER BY revision DESC LIMIT 1", (row["incident"],)).fetchone()
        geo = json.loads(origin["facts"])
        if not (20 <= geo["latitude"] <= 27 and 118 <= geo["longitude"] <= 124):
            continue
        date = datetime.fromisoformat(origin["occurred_at"]).astimezone(TAIPEI).date().isoformat()
        watches.append((date, origin["occurred_at"], row))
    return watches


def _assess(db, doc, watches):
    if doc["event_date"] is None:
        return "issuer did not identify one Taiwan earthquake date", None
    matches = [row for day, origin, row in watches
               if day == doc["event_date"] and origin <= doc["published_at"]]
    if not matches:
        return "no watch matches the stated Taiwan date and publication time", None
    if len(matches) > 1:
        return "multiple regional watches share the stated earthquake date", None
    watch = matches[0]
    if watch["status"] in {"closed", "withdrawn"}:
        return "matching watch already closed or withdrawn", None
    assessed = db.execute("""
        SELECT o.url, o.seen_at, o.revision FROM inbox i JOIN observations o USING (id, revision)
        WHERE i.incident=? AND o.kind='operator_update'
    """, (watch["incident"],))
    previous_edition = db.execute("SELECT 1 FROM issuer_documents WHERE doc_key=? AND edition<? LIMIT 1",
                                  (doc["doc_key"], doc["edition"])).fetchone()
    for row in assessed:
        if document_url(row["url"]) != document_url(doc["url"]):
            continue
        # A revised public passage seen after a review merits another read.
        if previous_edition and row["seen_at"] < doc["first_seen"]:
            continue
        # A daily index can contain several filings with exactly the same title.
        if issuer.is_bulletin_url(doc["url"]) and row["revision"] != doc["published_at"]:
            continue
        return "source document already assessed by operator import", None
    return "review possible issuer follow-up", watch["incident"]


def _capture(db, bulletins, seen):
    inserted = 0
    for bulletin in bulletins:
        published = utc(bulletin.published_at)
        if published > seen:
            raise ValueError("issuer document postdates receipt")
        fields = [published, bulletin.url, bulletin.title, bulletin.excerpt, bulletin.event_date]
        digest = hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()
        inserted += db.execute("""
            INSERT INTO issuer_documents(doc_key, fingerprint, first_seen, published_at, url, title, excerpt, event_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(doc_key, fingerprint) DO NOTHING
        """, (bulletin.key, digest, seen, *fields)).rowcount
    return inserted


def _review(db, seen):
    cutoff = utc((datetime.fromisoformat(seen) - LOOKBACK).isoformat())
    # Reconsider unmatched recent documents if the hazard arrives on a later
    # cycle. Superseded editions remain available for point-in-time audit.
    pending = db.execute("""
        SELECT d.* FROM issuer_documents d WHERE d.published_at>=?
        AND d.edition=(SELECT edition FROM issuer_documents newer WHERE newer.doc_key=d.doc_key
                       ORDER BY published_at DESC, edition DESC LIMIT 1)
        AND NOT EXISTS (SELECT 1 FROM issuer_reviews r WHERE r.edition=d.edition AND r.incident IS NOT NULL)
        ORDER BY d.published_at, d.edition
    """, (cutoff,)).fetchall()
    if not pending:
        return []
    watches = _watches(db)
    candidates = []
    for doc in pending:
        reason, incident = _assess(db, doc, watches)
        previous = db.execute("SELECT reason FROM issuer_reviews WHERE edition=? ORDER BY sequence DESC LIMIT 1",
                              (doc["edition"],)).fetchone()
        if previous and previous["reason"] == reason:
            continue
        db.execute("INSERT INTO issuer_reviews(edition, decided_at, reason, incident) VALUES (?,?,?,?)",
                   (doc["edition"], seen, reason, incident))
        if incident:
            key = hashlib.sha256(doc["doc_key"].encode()).hexdigest()
            candidates.append(Observation(
                id=f"issuer:{key}:{doc['fingerprint']}", revision=doc["published_at"], occurred_at=doc["published_at"],
                seen_at=seen, source=SOURCE, url=doc["url"], title=doc["title"], kind="issuer_candidate",
                facts={"supplier": SOURCE, "incident_id": incident, "excerpt": doc["excerpt"],
                       "event_date": doc["event_date"], "published_at": doc["published_at"],
                       "first_seen": doc["first_seen"],
                       "uncertainty": "The date mentioned by TSMC matches the watch's Taiwan-local earthquake date. "
                                      "The exact incident, operational effects and customer allocation require review.",
                       "next_check": "Read the issuer statement and record a reviewed operational assessment."},
            ))
    return candidates


def poll_issuer(db, *, clock=now, fetch=None):
    """Return (new public bulletins, new inbox entries). On failure persist health, then raise."""
    fetch = issuer.fetch_bulletins if fetch is None else fetch
    db.execute("BEGIN IMMEDIATE")
    try:
        snapshot = fetch(clock())
        seen = utc(clock())
        previous = last_evidence_receipt(db)
        if previous and seen < previous:
            raise ValueError("issuer receipt would backdate the ledger; check the receipt clock")
        added = _capture(db, snapshot.bulletins, seen)
        candidates = _review(db, seen)
        # ingest commits the captured documents, dispositions, health and alerts
        # together; its own conflict checks apply to these local inbox entries.
        report_day = date.fromisoformat(snapshot.report_date)
        midnight = datetime.combine(report_day, time.min, tzinfo=TAIPEI)
        record_health(db, SOURCE, seen, utc(midnight.isoformat()))
        _, entries = ingest(db, candidates)
        return added, entries
    except (ValueError, OSError, HTTPException, sqlite3.Error) as exc:
        db.rollback()
        failed_poll(db, clock(), str(exc), source=SOURCE)
        raise
    finally:
        # A Ctrl+C between capture, correlation and commit must leave the
        # document available for the next complete pass.
        if db.in_transaction:
            db.rollback()


def unlinked(db, cutoff, *, after_edition=0, limit=50):
    """Unassigned versions at the cutoff. Views cap the list, delivery drains it."""
    when = utc(cutoff)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='issuer_documents'").fetchone():
        return []
    return db.execute("""
        SELECT d.*, coalesce(r.reason, 'outside recent discovery window') AS reason
        FROM issuer_documents d LEFT JOIN issuer_reviews r ON r.sequence=(
            SELECT MAX(rr.sequence) FROM issuer_reviews rr WHERE rr.edition=d.edition AND rr.decided_at<=?
        )
        WHERE d.first_seen<=? AND r.incident IS NULL AND d.edition>?
        AND d.edition=(SELECT edition FROM issuer_documents newer WHERE newer.doc_key=d.doc_key AND newer.first_seen<=?
                       ORDER BY published_at DESC, edition DESC LIMIT 1)
        ORDER BY d.published_at DESC, d.edition DESC LIMIT ?
    """, (when, when, after_edition, when, limit)).fetchall()
