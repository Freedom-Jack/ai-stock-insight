"""Rank open work for adopted scopes. Refresh at most one local dossier per hour."""

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import evidence, goals, methods
from .db import instant, is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE agenda_revisions(
 id TEXT PRIMARY KEY, prior_id TEXT UNIQUE REFERENCES agenda_revisions, items TEXT NOT NULL,
 created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits);
CREATE TABLE agenda_refreshes(
 id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments, source_id TEXT NOT NULL REFERENCES evidence_passages,
 started_at TEXT NOT NULL, state TEXT NOT NULL, report_id TEXT REFERENCES method_reports, detail TEXT NOT NULL,
 attempts INTEGER NOT NULL, UNIQUE(instrument_id,source_id));
CREATE INDEX agenda_refresh_time ON agenda_refreshes(started_at);
CREATE TABLE agenda_method_versions(
 id TEXT PRIMARY KEY, prior_id TEXT UNIQUE REFERENCES agenda_method_versions, proposal_id TEXT NOT NULL,
 edition INTEGER NOT NULL, report_id TEXT NOT NULL REFERENCES method_reports, hypothesis TEXT NOT NULL,
 next_observation TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('proposed','adopted','declined','retired')),
 author TEXT NOT NULL CHECK(author IN ('desk','operator')), reason TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
 request_hash TEXT NOT NULL, created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits,
 UNIQUE(proposal_id,edition));
"""

AGENDA_LIMIT = 8
REFRESH_HOURS = 1
LISTING_HOURS = 24
STALE_DAYS = 30


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _scopes(db):
    scoped = {}
    rosters = {}
    for plan in goals.active(db):
        scope = plan["scope"]
        if scope not in rosters:
            rosters[scope] = goals.listings(db, scope)
        for listing in rosters[scope]:
            item = scoped.setdefault(listing["id"], {"listing": listing, "plans": {}})
            item["plans"][plan["id"]] = plan["goal_id"]
    return scoped


def _report_url(instrument_id, report_id=None):
    url = "/methods?instrument_id=" + instrument_id
    return url + "#" + report_id if report_id else url


def _current_dossier(db, listing_id):
    return db.execute(
        """SELECT id,created_at,commit_seq FROM method_reports WHERE instrument_id=? AND method='dossier.v1'
           ORDER BY commit_seq DESC LIMIT 1""",
        (listing_id,),
    ).fetchone()


def _new_observation(db, listing, since):
    # Dossier reads scoped actuals and dated issuer headlines. A fetch, empty
    # document, operator note or future intention does not meet that contract.
    rows = db.execute(
        """SELECT p.id,p.financial,d.origin,d.title,d.commit_seq FROM documents d JOIN evidence_passages p
           ON p.document_id=d.id WHERE d.instrument_id=? AND d.fixture=? AND d.commit_seq>?
           AND (d.origin='issuer_news' OR json_extract(p.financial,'$.role')='actual')
           AND NOT EXISTS(SELECT 1 FROM documents newer WHERE newer.instrument_id=d.instrument_id
             AND newer.origin=d.origin AND newer.source_url=d.source_url AND newer.fixture=d.fixture
             AND newer.commit_seq>d.commit_seq AND EXISTS(SELECT 1 FROM evidence_passages np WHERE np.document_id=newer.id))
           ORDER BY d.commit_seq DESC,p.locator LIMIT 160""",
        (listing["id"], int(is_fixture(db)), since),
    )
    for row in rows:
        if row["origin"] == "issuer_news" or evidence.supports_actual(
            json.loads(row["financial"]), listing.get("cik")
        ):
            return row
    return None


def _item(rank, kind, source, question, reason, method, observation, href):
    return {
        "priority": rank,
        "kind": kind,
        "source_id": source,
        "question": question,
        "reason": reason,
        "method": method,
        "next_observation": observation,
        "href": href,
    }


def _questions(db, listing_id, plans, day):
    rows = db.execute(
        """SELECT n.* FROM journal_entries n LEFT JOIN jobs j ON j.request_key=n.launch_key
           WHERE n.kind='question' AND n.instrument_id=? AND j.id IS NULL
           ORDER BY n.review_on IS NULL,n.review_on,n.commit_seq DESC LIMIT 3""",
        (listing_id,),
    )
    for q in rows:
        due = q["review_on"]
        yield _item(
            10 if due and due <= day else 30,
            "planned_question",
            q["id"],
            q["body"],
            "You saved this question" + (" for review on " + due if due else "") + ".",
            "Investigate the saved journal question using the listing’s dated primary evidence.",
            q["condition_text"]
            or "Look for a dated disclosure that directly addresses the saved question.",
            "/upcoming#" + q["id"],
        )
    for q in db.execute(
        """SELECT c.id,c.question,j.state FROM cases c JOIN jobs j ON j.id=(
            SELECT x.id FROM jobs x WHERE x.case_id=c.id ORDER BY x.rowid DESC LIMIT 1)
           WHERE c.instrument_id=? AND c.revision=0 ORDER BY c.commit_seq DESC LIMIT 3""",
        (listing_id,),
    ):
        yield _item(
            28,
            "open_case",
            q["id"],
            q["question"],
            "This investigation has no accepted brief. Latest job: " + q["state"] + ".",
            "Inspect the investigation’s current run and any missing input.",
            "Check for its first accepted source-backed brief or a recorded blocker.",
            "/cases/" + q["id"],
        )
    rows = db.execute(
        """SELECT c.id,c.question,g.id AS gap,g.impact,g.remedy FROM cases c JOIN capability_gaps g
           ON g.case_id=c.id WHERE c.instrument_id=? AND g.lifecycle='open'
           ORDER BY g.commit_seq DESC,g.id LIMIT 3""",
        (listing_id,),
    )
    for q in rows:
        yield _item(
            20,
            "case_gap",
            q["gap"],
            q["question"],
            q["impact"],
            "Reopen the investigation and verify the missing source in scope.",
            q["remedy"],
            "/cases/" + q["id"],
        )
    followups = db.execute(
        """SELECT f.*,p.goal_id FROM goal_followups f JOIN goal_dispatch d ON d.id=f.report_id
           JOIN goal_plans p ON p.id=d.plan_id WHERE f.instrument_id=? AND p.goal_id IN
           (SELECT value FROM json_each(?)) ORDER BY f.created_at DESC,f.id LIMIT 3""",
        (listing_id, _encode(sorted(set(plans.values())))),
    )
    for q in followups:
        yield _item(
            35,
            "goal_followup",
            q["id"],
            q["question"],
            "A saved report for this standing goal requested this follow-up.",
            "Revisit the source and comparison in the original goal report.",
            q["question"],
            "/goals/reports/" + q["report_id"],
        )


def _events(db, listing_id, stamp):
    day = date.fromisoformat(stamp[:10])
    rows = db.execute(
        """SELECT e.*,p.text,d.source_url FROM event_versions e JOIN evidence_passages p ON p.id=e.source_ref
           JOIN documents d ON d.id=p.document_id
           WHERE e.instrument_id=? AND e.state IN ('confirmed','tentative','postponed')
           AND substr(e.scheduled_start,1,10) BETWEEN ? AND ?
           AND (e.precision='day' OR coalesce(e.scheduled_end,e.scheduled_start)>=?)
           AND NOT EXISTS(SELECT 1 FROM event_versions n WHERE n.supersedes=e.id)
           ORDER BY e.scheduled_start,e.id LIMIT 3""",
        (listing_id, day.isoformat(), (day + timedelta(days=30)).isoformat(), stamp),
    )
    for event in rows:
        title = event["kind"].replace("_", " ")
        near = date.fromisoformat(event["scheduled_start"][:10]) <= day + timedelta(
            days=7
        )
        item = _item(
            15 if near else 40,
            "upcoming_event",
            event["id"],
            f"What should be checked before the {title}?",
            f"The saved {event['state']} schedule gives {event['scheduled_start']}.",
            "Read the event edition and freeze available expectations before the release.",
            f"Check for a revised schedule or a dated issuer disclosure confirming the {title}.",
            "/events/" + event["id"],
        )
        item["deadline"] = event["scheduled_start"]
        item["source_ref"] = event["source_ref"]
        item["excerpt"] = event["text"][:500]
        if (event["source_url"] or "").startswith("https://"):
            item["source_url"] = event["source_url"]
        yield item


def _latest_versions(db):
    return db.execute(
        """SELECT v.*,r.instrument_id,r.title,i.ticker FROM agenda_method_versions v
           JOIN method_reports r ON r.id=v.report_id JOIN instruments i ON i.id=r.instrument_id
           WHERE NOT EXISTS(SELECT 1 FROM agenda_method_versions n WHERE n.prior_id=v.id)
           ORDER BY v.commit_seq DESC,v.id"""
    )


def _rank(db, scopes, stamp):
    items, refreshable = [], []
    for ident, scope in scopes.items():
        listing, plans = scope["listing"], scope["plans"]
        rows = list(_questions(db, ident, plans, stamp[:10]))
        rows.extend(_events(db, ident, stamp))
        for update in db.execute(
            """SELECT u.id,c.id AS case_id,c.question,u.rationale FROM case_updates u JOIN cases c ON c.id=u.case_id
               WHERE c.instrument_id=? AND u.state IN ('pending','queued','needs_review')
               ORDER BY u.commit_seq DESC LIMIT 2""",
            (ident,),
        ):
            rows.append(
                _item(
                    5,
                    "correction",
                    update["id"],
                    update["question"],
                    update["rationale"],
                    "Compare the changed source edition to the cited claim.",
                    "Review the replacement passage and the affected case revision.",
                    "/cases/" + update["case_id"],
                )
            )
        report = _current_dossier(db, ident)
        checked = (
            db.execute(
                """SELECT max(d.commit_seq) FROM agenda_refreshes a JOIN evidence_passages p
                 ON p.id=a.source_id JOIN documents d ON d.id=p.document_id
                 WHERE a.instrument_id=? AND a.state='saved'""",
                (ident,),
            ).fetchone()[0]
            or 0
        )
        source = _new_observation(
            db, listing, max(checked, report["commit_seq"] if report else 0)
        )
        old = (
            report
            and (
                datetime.fromisoformat(stamp)
                - datetime.fromisoformat(report["created_at"])
            ).days
            >= STALE_DAYS
        )
        if source or not report or old:
            if source:
                reason = f"A new saved observation in “{source['title']}” is available for the dossier."
                next_check = "Compare that dated observation with the figures and caveats in the last dossier."
                refreshable.append(
                    (report is not None, source["commit_seq"], ident, source["id"])
                )
            else:
                reason = (
                    "The last dossier is at least 30 days old."
                    if report
                    else "This listing has no saved dossier."
                )
                next_check = "Wait for a verified reported figure or dated issuer headline for this listing."
            rows.append(
                _item(
                    45 if source else 65,
                    "dossier",
                    source["id"] if source else (report["id"] if report else ident),
                    f"What changed in the saved evidence for {listing['ticker'] or listing['raw_label']}?",
                    reason,
                    "Rebuild the company dossier from dated, scoped source passages.",
                    next_check,
                    _report_url(ident, report["id"] if report else None),
                )
            )
        items.extend(
            dict(
                r,
                instrument_id=ident,
                ticker=listing["ticker"] or listing["raw_label"],
                plans=sorted(plans),
            )
            for r in rows
        )
    for v in _latest_versions(db):
        if v["status"] == "adopted" and v["instrument_id"] in scopes:
            ident = v["instrument_id"]
            i = _item(
                38,
                "adopted_hypothesis",
                v["id"],
                v["hypothesis"],
                "You adopted this research question: " + v["reason"],
                "Test the hypothesis against the predeclared observation.",
                v["next_observation"],
                _report_url(ident, v["report_id"]),
            )
            items.append(
                dict(
                    i,
                    instrument_id=ident,
                    ticker=v["ticker"],
                    plans=sorted(scopes[ident]["plans"]),
                )
            )
    items.sort(
        key=lambda r: (
            r["priority"],
            r.get("deadline", ""),
            r["ticker"],
            r["source_id"],
        )
    )
    # The same open question may recur in successive dispatches. Keep one entry.
    unique = {}
    for item in items:
        unique.setdefault((item["instrument_id"], item["question"], item["kind"]), item)
    return list(unique.values())[:AGENDA_LIMIT], sorted(refreshable)


def _record(db, items, stamp):
    payload = _encode(items)

    def prior():
        return db.execute(
            "SELECT id,items FROM agenda_revisions ORDER BY commit_seq DESC LIMIT 1"
        ).fetchone()

    previous = prior()
    if (previous["items"] if previous else "[]") == payload:
        return
    with write(db) as seq:
        previous = prior()
        if (previous["items"] if previous else "[]") != payload:
            db.execute(
                "INSERT INTO agenda_revisions VALUES(?,?,?,?,?)",
                (
                    uid("agenda"),
                    previous["id"] if previous else None,
                    payload,
                    stamp,
                    seq,
                ),
            )


def _candidate(db, candidates, stamp):
    at = datetime.fromisoformat(stamp)
    latest = db.execute("SELECT max(started_at) FROM agenda_refreshes").fetchone()[0]
    if latest and at - datetime.fromisoformat(latest) < timedelta(hours=REFRESH_HOURS):
        return None
    for _, _, listing, source in candidates:
        recent = db.execute(
            "SELECT max(started_at) FROM agenda_refreshes WHERE instrument_id=?",
            (listing,),
        ).fetchone()[0]
        if recent and at - datetime.fromisoformat(recent) < timedelta(
            hours=LISTING_HOURS
        ):
            continue
        prior = db.execute(
            "SELECT * FROM agenda_refreshes WHERE instrument_id=? AND source_id=?",
            (listing, source),
        ).fetchone()
        if not prior or (prior["state"] != "saved" and prior["attempts"] < 3):
            return listing, source
    return None


def _recover_refresh(db, stamp):
    """Settle an interrupted reservation after its worker's bounded local call."""
    threshold = instant(
        (datetime.fromisoformat(stamp) - timedelta(hours=REFRESH_HOURS)).isoformat()
    )
    pending = db.execute(
        """SELECT a.id,a.instrument_id,a.source_id,p.document_id,d.commit_seq FROM agenda_refreshes a
           JOIN evidence_passages p ON p.id=a.source_id JOIN documents d ON d.id=p.document_id
           WHERE a.state='running' AND a.started_at<=? ORDER BY a.started_at LIMIT 1""",
        (threshold,),
    ).fetchone()
    if not pending:
        return
    # A complete dossier may have committed immediately before the process died.
    # A report that cites the triggering document proves this edition was retained.
    with write(db):
        report = db.execute(
            """SELECT m.id FROM method_reports m WHERE m.instrument_id=? AND m.method='dossier.v1'
               AND m.commit_seq>? AND EXISTS(SELECT 1 FROM json_each(m.body,'$.citations') c
                 WHERE json_extract(c.value,'$.document_id')=?) ORDER BY m.commit_seq LIMIT 1""",
            (pending["instrument_id"], pending["commit_seq"], pending["document_id"]),
        ).fetchone()
        db.execute(
            """UPDATE agenda_refreshes SET state=?,report_id=?,detail=? WHERE id=? AND state='running'""",
            (
                "saved" if report else "deferred",
                report[0] if report else None,
                "Recovered a saved dossier."
                if report
                else "Interrupted before a matching dossier was saved.",
                pending["id"],
            ),
        )


def _refresh(db, candidates, stamp):
    if not candidates or not _candidate(db, candidates, stamp):
        return None
    with write(db):
        candidate = _candidate(db, candidates, stamp)
        if not candidate or candidate[0] not in _scopes(db):
            return None
        listing, source = candidate
        db.execute(
            """INSERT INTO agenda_refreshes VALUES(?,?,?,?,'running',NULL,'',1)
                   ON CONFLICT(instrument_id,source_id) DO UPDATE SET state='running',started_at=excluded.started_at,
                   detail='',attempts=attempts+1""",
            (uid("refresh"), listing, source, stamp),
        )
    try:
        report = methods.dossier(db, listing)
    except ValueError as exc:
        state, report_id, detail = "deferred", None, str(exc)[:300]
    else:
        state, report_id, detail = "saved", report["id"], ""
    with write(db):
        db.execute(
            "UPDATE agenda_refreshes SET state=?,report_id=?,detail=? WHERE instrument_id=? AND source_id=?",
            (state, report_id, detail, listing, source),
        )
    return report_id


def _version(
    db,
    seq,
    key,
    digest,
    report_id,
    hypothesis,
    observation,
    status,
    author,
    reason,
    stamp,
    prior=None,
):
    ident = uid("proposal_version")
    db.execute(
        "INSERT INTO agenda_method_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            prior["id"] if prior else None,
            prior["proposal_id"] if prior else uid("proposal"),
            prior["edition"] + 1 if prior else 1,
            report_id,
            hypothesis,
            observation,
            status,
            author,
            reason,
            key,
            digest,
            stamp,
            seq,
        ),
    )
    return ident


def _suggest(db, scopes, stamp):
    # Only the predeclared owner's observed pair can motivate its suggestion.
    # A positive peer or excluded/uncited member cannot supply it.
    if not scopes:
        return
    for row in db.execute(
        """SELECT r.id,r.instrument_id,r.body FROM method_reports r
           WHERE r.instrument_id IN (SELECT value FROM json_each(?)) AND r.method='historical_cohort.v1'
           AND NOT EXISTS(SELECT 1 FROM method_reports newer WHERE newer.prior_id=r.id)
           AND NOT EXISTS(SELECT 1 FROM agenda_method_versions m WHERE m.request_key='cohort:'||json_extract(r.body,'$.cohort.id'))
           AND EXISTS(SELECT 1 FROM json_each(r.body,'$.cohort.members') m
             WHERE m.value->>'instrument_id'=r.instrument_id AND m.value->>'status'='observed'
             AND cast(m.value->>'percent_change' AS REAL)>0)
           ORDER BY r.commit_seq DESC LIMIT 16""",
        (_encode(sorted(scopes)),),
    ):
        body = json.loads(row["body"])
        cohort = body["cohort"]
        member = next(
            (
                m
                for m in cohort["members"]
                if m["instrument_id"] == row["instrument_id"]
            ),
            None,
        )
        if (
            not member
            or member["status"] != "observed"
            or member["percent_change"] is None
            or Decimal(member["percent_change"]) <= 0
        ):
            continue
        citations = {p["id"] for p in body["citations"]}
        if not {member["baseline_id"], member["outcome_id"]} <= citations:
            continue
        metric = cohort["rule"]["metric"].replace("_", " ")
        question = f"Does the positive {metric} change observed for {member['ticker']} recur in a separately declared period?"
        observation = f"Freeze a new period before observing its outcome, retain missing members and compare {metric} on the original basis."
        key = "cohort:" + cohort["id"]
        with write(db) as seq:
            if (
                row["instrument_id"] in _scopes(db)
                and not db.execute(
                    "SELECT 1 FROM agenda_method_versions WHERE request_key=?", (key,)
                ).fetchone()
            ):
                _version(
                    db,
                    seq,
                    key,
                    key,
                    row["id"],
                    question,
                    observation,
                    "proposed",
                    "desk",
                    "One observed historical pair motivates a replication question.",
                    stamp,
                )
        return


def tick(db, *, at=None):
    stamp = instant(at or now())
    _recover_refresh(db, stamp)
    scopes = _scopes(db)
    items, candidates = _rank(db, scopes, stamp)
    _record(db, items, stamp)
    _suggest(db, scopes, stamp)
    return _refresh(db, candidates, stamp)


def dashboard(db):
    scopes = _scopes(db)
    revisions = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM agenda_revisions ORDER BY commit_seq DESC LIMIT 12"
        )
    ]
    for revision in revisions:
        revision["items"] = [
            i
            for i in json.loads(revision["items"])
            if i["instrument_id"] in scopes
            and set(i["plans"]) & scopes[i["instrument_id"]]["plans"].keys()
        ]
    reports = [
        dict(r)
        for r in db.execute(
            """SELECT id,instrument_id,title,created_at FROM method_reports
        WHERE instrument_id IN (SELECT value FROM json_each(?)) ORDER BY commit_seq DESC LIMIT 40""",
            (_encode(sorted(scopes)),),
        )
    ]
    proposals = []
    for v in _latest_versions(db):
        if v["instrument_id"] not in scopes:
            continue
        item = dict(v)
        item.update(
            href=_report_url(v["instrument_id"], v["report_id"]),
            history=[
                dict(r)
                for r in db.execute(
                    """SELECT edition,status,reason,author,created_at
                           FROM agenda_method_versions WHERE proposal_id=? ORDER BY edition DESC""",
                    (v["proposal_id"],),
                )
            ],
        )
        proposals.append(item)
    refreshes = [
        dict(r)
        for r in db.execute(
            """SELECT a.*,i.ticker FROM agenda_refreshes a JOIN instruments i ON i.id=a.instrument_id
              WHERE a.instrument_id IN (SELECT value FROM json_each(?)) ORDER BY a.started_at DESC LIMIT 10""",
            (_encode(sorted(scopes)),),
        )
    ]
    return {
        "items": revisions[0]["items"] if revisions else [],
        "proposals": proposals,
        "reports": reports,
        "revisions": revisions,
        "refreshes": refreshes,
    }


def _text(data, field, limit):
    value = data.get(field, "")
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Enter a valid " + field.replace("_", " ") + ".")
    return value.strip()


def action(db, action, data):
    if action not in ("agenda-propose", "agenda-decide"):
        raise ValueError("Unknown research agenda action.")
    key = _text(data, "key", 160)
    if not re.fullmatch(r"[\w-]+", key):
        raise ValueError("Reload the research agenda form.")
    fields = (
        ("report_id", "hypothesis", "next_observation")
        if action == "agenda-propose"
        else ("revision", "decision", "reason")
    )
    values = [_text(data, k, 1000) for k in fields]
    key = action + ":" + key
    digest = hashlib.sha256(_encode(values).encode()).hexdigest()
    with write(db) as seq:
        existing = db.execute(
            "SELECT request_hash FROM agenda_method_versions WHERE request_key=?",
            (key,),
        ).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError(
                    "This form was already submitted with different instructions."
                )
            return "/agenda"
        prior = None
        if action == "agenda-propose":
            report, question, observation = values
            status, reason = (
                "proposed",
                "Operator proposed a source-linked research hypothesis.",
            )
        else:
            revision, status, reason = values
            prior = db.execute(
                """SELECT * FROM agenda_method_versions v WHERE id=? AND
                   NOT EXISTS(SELECT 1 FROM agenda_method_versions n WHERE n.prior_id=v.id)""",
                (revision,),
            ).fetchone()
            if not prior or (prior["status"], status) not in {
                ("proposed", "adopted"),
                ("proposed", "declined"),
                ("adopted", "retired"),
            }:
                raise ValueError(
                    "Reload the current proposal and choose an available decision."
                )
            report, question, observation = (
                prior[k] for k in ("report_id", "hypothesis", "next_observation")
            )
        owner = db.execute(
            "SELECT instrument_id FROM method_reports WHERE id=?", (report,)
        ).fetchone()
        if not owner or owner[0] not in _scopes(db):
            raise ValueError("Choose a report in an active standing goal’s scope.")
        _version(
            db,
            seq,
            key,
            digest,
            report,
            question,
            observation,
            status,
            "operator",
            reason,
            now(),
            prior,
        )
    return "/agenda"
