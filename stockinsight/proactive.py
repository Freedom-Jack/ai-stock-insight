"""Dispatch standing goals from watchlist evidence and persist independent delivery work."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from . import (
    assistant,
    delivery,
    exposure,
    goal_schedule,
    goals,
    local_model,
    methods,
    monitor,
    sources_calendar,
    universe,
)
from .db import instant, is_fixture, now, uid, write

GLOBAL_DAILY_LIMIT = 24
FOCI = {
    "disclosure": "Identify what the issuer or public authority actually disclosed and what remains unknown.",
    "expectations": "Compare the reported event with dated prior expectations and comparable financial periods.",
    "exposure": "Trace supported links between the event and the watched business, including alternative mechanisms.",
}
EVENT_WORDS = {
    "earnings": r"earnings|quarterly results|financial results|guidance|profit|revenue",
    "policy": r"policy|monetary|regulat|export|interest rates|fomc|tariff",
    "corporate": r"acqui[rs]|merger|supply chain|shareholder|investor|capital expenditure|financial community",
}


def _shift(stamp, **delta):
    return instant((datetime.fromisoformat(stamp) + timedelta(**delta)).isoformat())


def _event_zone(event):
    try:
        return goal_schedule.zone(event["source_timezone"])
    except ValueError:
        # The latest civil timezone gives a conservative boundary when the publisher supplies none.
        return timezone(timedelta(hours=-12))


def _decision(plan, e, stamp):
    day = (e["scheduled_start"] or e["occurred_at"] or "")[:10]
    age = (datetime.fromisoformat(stamp).date() - datetime.fromisoformat(day).date()).days if day else None
    if e["state"] == "occurred" and (age is None or age > 7):
        return (
            "suppress",
            "Historical observation retained for context outside the seven-day discovery window.",
            0,
            None,
        )
    text = (e["kind"].replace("_", " ") + " " + e["text"]).casefold()
    topics = {name for name, pattern in EVENT_WORDS.items() if re.search(pattern, text)}
    requested = {name for name, pattern in EVENT_WORDS.items() if re.search(pattern, plan["objective"], re.I)}
    if requested and not requested.intersection(topics):
        return (
            "suppress",
            "The observed subject falls outside this goal's research topics.",
            0,
            None,
        )
    if e["supersedes"]:
        return (
            "investigate",
            "The named source revised an earlier watchlist event. Compare both editions.",
            100,
            None,
        )
    if e["state"] in ("confirmed", "tentative", "postponed") and age is not None:
        end = e["scheduled_end"] or e["scheduled_start"]
        clock = datetime.fromisoformat(stamp)
        publisher_zone = _event_zone(e)
        age = (clock.astimezone(publisher_zone).date() - datetime.fromisoformat(day).date()).days
        if len(end) == 10:
            past = clock.astimezone(publisher_zone).date() > datetime.fromisoformat(end).date()
        else:
            past = clock > datetime.fromisoformat(end)
        if past:
            return (
                "suppress",
                "The scheduled date has passed. A published outcome is still required.",
                0,
                None,
            )
        if age < -30:
            due = goal_schedule.civil(
                datetime.fromisoformat(day).date() - timedelta(days=30), "00:00", publisher_zone
            ).isoformat()
            return (
                "later",
                "Prepare when the event enters the thirty-day horizon.",
                10,
                instant(due),
            )
        return (
            "prepare",
            "A sourced watchlist event is within the thirty-day preparation window.",
            85,
            None,
        )
    if topics or e["kind"] in ("earnings_release", "financial_filing"):
        return (
            "investigate",
            "Primary-source development for a watched listing: "
            + ", ".join(sorted(topics) or ["filing"])
            + ".",
            75,
            None,
        )
    # Specific subjects in the operator's goal may warrant a read without matching a financial category.
    stop = {
        "keep",
        "prepared",
        "important",
        "developments",
        "affecting",
        "these",
        "companies",
        "watchlist",
        "monitor",
        "research",
        "about",
        "report",
        "notify",
        "please",
        "weekly",
        "daily",
        "watch",
        "updates",
        "news",
        "company",
    }
    terms = {t for t in re.findall(r"[a-z]{4,}", plan["objective"].casefold()) if t not in stop}
    matching = sorted(terms.intersection(re.findall(r"[a-z]{4,}", text)))
    if matching:
        return (
            "investigate",
            "The primary observation matches the adopted subject: " + ", ".join(matching[:4]) + ".",
            60,
            None,
        )
    return (
        "suppress",
        "Logged in watchlist coverage. No specific material change was identified for this goal.",
        0,
        None,
    )


def _queue(db, plan_id, key, kind, ready, decision=None):
    db.execute(
        """INSERT OR IGNORE INTO goal_dispatch(id,plan_id,trigger_key,kind,state,ready_at,decision_id)
                  VALUES(?,?,?,?,'ready',?,?)""",
        (uid("dispatch"), plan_id, key, kind, ready, decision),
    )
    return db.execute("SELECT id FROM goal_dispatch WHERE trigger_key=?", (key,)).fetchone()[0]


def _discover(db, plan, stamp):
    for item in goals.listings(db, plan["scope"]):
        rows = db.execute(
            """SELECT e.*,p.text,r.id AS known FROM event_versions e
            JOIN evidence_passages p ON p.id=e.source_ref
            LEFT JOIN goal_relevance r ON r.event_version_id=e.id AND r.plan_id=?
            WHERE e.instrument_id=? AND (r.id IS NULL OR (r.decision='later' AND r.next_check<=?))
            AND NOT EXISTS(SELECT 1 FROM event_versions n WHERE n.supersedes=e.id)
            ORDER BY e.commit_seq DESC LIMIT 64""",
            (plan["id"], item["id"], stamp),
        ).fetchall()
        if not rows:
            continue
        with write(db):
            for e in rows:
                decision, reason, priority, when = _decision(plan, e, stamp)
                ident = e["known"] or uid("relevance")
                if e["known"]:
                    db.execute(
                        "UPDATE goal_relevance SET decision=?,reason=?,priority=?,next_check=? WHERE id=?",
                        (decision, reason, priority, when, ident),
                    )
                else:
                    changed = db.execute(
                        """INSERT OR IGNORE INTO goal_relevance VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            ident,
                            plan["id"],
                            e["id"],
                            item["id"],
                            decision,
                            reason,
                            priority,
                            stamp,
                            when,
                        ),
                    ).rowcount
                    if not changed:
                        continue
                if e["supersedes"]:
                    db.execute(
                        """UPDATE goal_dispatch SET state='superseded',ended_at=? WHERE state IN ('ready','running','awaiting_assistant')
                        AND decision_id IN (SELECT r.id FROM goal_relevance r JOIN event_versions v ON v.id=r.event_version_id
                        WHERE r.plan_id=? AND v.event_id=? AND v.id<>?)""",
                        (stamp, plan["id"], e["event_id"], e["id"]),
                    )
                    db.execute("""UPDATE assistant_jobs SET state='superseded' WHERE state IN ('pending','running')
                               AND event_id=? AND method_id IN (SELECT id FROM method_reports WHERE event_version_id<>?)""",
                               (e["event_id"],e["id"]))
                if decision in ("investigate", "prepare"):
                    _queue(
                        db,
                        plan["id"],
                        f"{plan['id']}:{e['id']}:event",
                        "event",
                        stamp,
                        ident,
                    )
                    if e["state"] in ("cancelled", "postponed") and e["supersedes"]:
                        delivery.enqueue(
                            db,
                            key="event-revision:" + e["id"],
                            title="Watchlist calendar changed",
                            message="A source revised a scheduled event. The dated observation is ready to inspect.",
                            report_path="/events/" + e["id"],
                            at=stamp,
                        )
                    if e["scheduled_start"] and e["state"] in (
                        "confirmed",
                        "tentative",
                        "postponed",
                    ):
                        # A date-only source supplies no intraday moment. Check after the full local date.
                        end = e["scheduled_end"] or e["scheduled_start"]
                        if len(end) == 10:
                            tz = _event_zone(e)
                            end = goal_schedule.civil(
                                datetime.fromisoformat(end).date() + timedelta(days=1),
                                "00:00",
                                tz,
                            ).isoformat()
                        _queue(
                            db,
                            plan["id"],
                            f"{plan['id']}:{e['id']}:follow",
                            "followthrough",
                            _shift(end, hours=1),
                            ident,
                        )


def _linked(db, plan, stamp):
    watched = {i["id"]: i for i in goals.listings(db, plan["scope"])}
    for subject, item in watched.items():
        rows = db.execute(
            """SELECT DISTINCT e.id,e.instrument_id FROM exposure_proposals p
            JOIN exposure_decisions a ON a.proposal_id=p.id AND a.state='approved'
            JOIN event_versions e ON e.kind=p.trigger_kind AND (e.instrument_id=p.instrument_id OR e.instrument_id=p.counterparty_id)
            WHERE p.instrument_id=? AND NOT EXISTS(SELECT 1 FROM exposure_decisions x WHERE x.proposal_id=p.id AND x.state='revoked')
              AND NOT EXISTS(SELECT 1 FROM event_versions n WHERE n.supersedes=e.id)
              AND substr(coalesce(e.occurred_at,e.scheduled_start),1,10) BETWEEN ? AND ?
              AND NOT EXISTS(SELECT 1 FROM goal_impacts x JOIN goal_relevance r ON r.id=x.relevance_id WHERE
                   x.proposal_id=p.id AND r.plan_id=? AND r.event_version_id=e.id)
            ORDER BY e.commit_seq DESC LIMIT 48""",
            (
                subject,
                _shift(stamp, days=-7)[:10],
                _shift(stamp, days=30)[:10],
                plan["id"],
            ),
        ).fetchall()
        for e in rows:
            links = exposure.for_event(db, item, e["id"])
            if not links:
                continue
            with write(db):
                r = db.execute(
                    "SELECT * FROM goal_relevance WHERE plan_id=? AND event_version_id=?",
                    (plan["id"], e["id"]),
                ).fetchone()
                reason = "Approved watchlist exposure to " + links[0]["entity"] + ". " + links[0]["reason"]
                ident = r["id"] if r else uid("relevance")
                if not r:
                    db.execute(
                        "INSERT INTO goal_relevance VALUES(?,?,?,?,?,?,?,?,NULL)",
                        (
                            ident,
                            plan["id"],
                            e["id"],
                            subject,
                            "linked",
                            reason,
                            90,
                            stamp,
                        ),
                    )
                elif r["decision"] in ("suppress", "later"):
                    db.execute(
                        "UPDATE goal_relevance SET decision='linked',reason=?,priority=90,instrument_id=?,next_check=NULL WHERE id=?",
                        (reason, subject, ident),
                    )
                db.executemany(
                    "INSERT OR IGNORE INTO goal_impacts VALUES(?,?,?,?)",
                    [(ident, link["id"], subject, stamp) for link in links],
                )
                _queue(
                    db,
                    plan["id"],
                    f"{plan['id']}:{e['id']}:event",
                    "event",
                    stamp,
                    ident,
                )


def _deadlines(db, plan, stamp):
    today = (
        datetime.fromisoformat(stamp)
        .astimezone(
            goal_schedule.zone(
                "America/New_York" if plan["cadence"] in ("closing", "premarket") else plan["timezone"]
            )
        )
        .date()
    )
    horizon = (today + timedelta(days=14)).isoformat()
    expansion_due = plan["expand_on"] <= horizon and (
        plan["cadence"] not in ("closing", "premarket") or int(plan["expand_on"][:4]) in goal_schedule.CLOSED
    )
    if (
        not expansion_due
        and not db.execute(
            """SELECT 1 FROM goal_deadlines WHERE plan_id=? AND
        ((state='pending' AND start_at<=?) OR (state='started' AND due_at<? AND ?='report_by')) LIMIT 1""",
            (plan["id"], stamp, stamp, plan["intent"]),
        ).fetchone()
    ):
        return
    with write(db):
        goal_schedule.expand(db, plan, stamp)
        # A report-by target cannot be rendered timely by starting after its deadline.
        # A start-at target cares when work was first dispatched.
        overdue = db.execute(
            """SELECT * FROM goal_deadlines WHERE plan_id=? AND state IN ('pending','started')
            AND due_at<? AND (state='pending' OR ?='report_by') ORDER BY due_at""",
            (
                plan["id"],
                _shift(stamp, seconds=-60) if plan["intent"] == "start_at" else stamp,
                plan["intent"],
            ),
        ).fetchall()
        if overdue:
            key = f"{plan['id']}:catch-up:{overdue[-1]['due_at']}"
            work = _queue(db, plan["id"], key, "recovery", stamp)
            for d in overdue:
                if d["report_id"]:
                    db.execute(
                        """UPDATE goal_dispatch SET state='superseded',ended_at=?,detail='Original deadline missed'
                                WHERE id=? AND state IN ('ready','running')""",
                        (stamp, d["report_id"]),
                    )
                db.execute(
                    "UPDATE goal_deadlines SET state='missed',report_id=? WHERE id=?",
                    (work, d["id"]),
                )
        for d in db.execute(
            """SELECT * FROM goal_deadlines WHERE plan_id=? AND state='pending' AND report_id IS NULL
                            AND start_at<=? ORDER BY due_at""",
            (plan["id"], stamp),
        ).fetchall():
            work = _queue(
                db,
                plan["id"],
                f"{plan['id']}:deadline:{d['due_at']}",
                "scheduled",
                stamp,
            )
            db.execute("UPDATE goal_deadlines SET report_id=? WHERE id=?", (work, d["id"]))


def _claim(db, stamp):
    midnight = stamp[:10]
    if not db.execute(
        """SELECT 1 FROM goal_dispatch WHERE
           (state='ready' AND ready_at<=?) OR (state='running' AND lease_until<=?) LIMIT 1""",
        (stamp, stamp),
    ).fetchone():
        return None
    with write(db):
        db.execute(
            """UPDATE goal_dispatch SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'ready' END,
                      detail='Worker lease expired' WHERE state='running' AND lease_until<=?""",
            (stamp,),
        )
        candidates = db.execute(
            """SELECT d.*,p.goal_id,p.objective,p.scope,p.daily_limit,
            r.event_version_id,r.instrument_id,r.priority,r.reason,r.decision FROM goal_dispatch d JOIN goal_plans p ON p.id=d.plan_id
            LEFT JOIN goal_relevance r ON r.id=d.decision_id
            WHERE p.ended_at IS NULL AND d.state='ready' AND d.ready_at<=?
            ORDER BY (d.decision_id IS NULL) DESC, r.priority DESC, d.ready_at,d.rowid LIMIT 200""",
            (stamp,),
        ).fetchall()
        for work in candidates:
            if work["decision_id"]:
                if not _eligible_work(db, work, stamp):
                    db.execute(
                        "UPDATE goal_dispatch SET state='superseded',ended_at=?,detail='Event or scope changed before dispatch' WHERE id=?",
                        (stamp, work["id"]),
                    )
                    continue
                used, personal = db.execute(
                    """SELECT count(*),coalesce(sum(p.goal_id=?),0) FROM goal_runtime_usage u
                    JOIN goal_dispatch d ON d.id=u.dispatch_id JOIN goal_plans p ON p.id=d.plan_id WHERE u.started_at>=?""",
                    (work["goal_id"], midnight),
                ).fetchone()
                if used >= GLOBAL_DAILY_LIMIT or personal >= work["daily_limit"]:
                    db.execute(
                        "UPDATE goal_dispatch SET ready_at=?,detail='Daily research budget reached' WHERE id=?",
                        (_shift(midnight + "T00:00:00Z", days=1), work["id"]),
                    )
                    continue
            lease = uid("lease")
            db.execute(
                """UPDATE goal_dispatch SET state='running',attempts=attempts+1,lease_id=?,lease_until=?,detail=NULL
                          WHERE id=?""",
                (lease, _shift(stamp, minutes=5), work["id"]),
            )
            if work["kind"] == "scheduled":
                db.execute(
                    """UPDATE goal_deadlines SET state='started',started_at=coalesce(started_at,?)
                              WHERE report_id=? AND state='pending'""",
                    (stamp, work["id"]),
                )
            if work["decision_id"]:
                db.execute(
                    "INSERT INTO goal_runtime_usage VALUES(?,?,?,?)",
                    (
                        work["id"],
                        work["attempts"] + 1,
                        stamp,
                        "connected_assistant" if assistant.profile(db)["enabled"] else
                        "fixture" if is_fixture(db) else "on_device" if local_model.available() else "local",
                    ),
                )
            return {**dict(work), "lease_id": lease}
    return None


def _eligible_work(db, work, stamp):
    if work["instrument_id"] not in {i["id"] for i in goals.listings(db, work["scope"])}:
        return False
    event = db.execute(
        """SELECT v.* FROM event_versions v WHERE v.id=? AND NOT EXISTS
                     (SELECT 1 FROM event_versions n WHERE n.supersedes=v.id)""",
        (work["event_version_id"],),
    ).fetchone()
    if event is None or (
        work["decision"] == "linked" and not exposure.for_event(db, work["instrument_id"], event["id"])
    ):
        return False
    if work["kind"] == "event" and event["state"] == "occurred" and not event["supersedes"]:
        return bool(event["occurred_at"] and event["occurred_at"][:10] >= _shift(stamp, days=-7)[:10])
    return True


def _run(db, work, stamp):
    prior, method_id, runtime = [], None, {}
    if work["decision_id"]:
        prior = db.execute(
            """SELECT f.* FROM goal_followups f JOIN goal_dispatch d ON d.id=f.report_id
            JOIN goal_plans p ON p.id=d.plan_id WHERE p.goal_id=? AND f.instrument_id=?
            ORDER BY f.created_at DESC,f.id LIMIT 2""",
            (work["goal_id"], work["instrument_id"]),
        ).fetchall()
        source = db.execute(
            """SELECT p.text,v.kind,v.instrument_id,d.origin FROM event_versions v JOIN evidence_passages p ON p.id=v.source_ref
                            JOIN documents d ON d.id=p.document_id
                            WHERE v.id=?""",
            (work["event_version_id"],),
        ).fetchone()
        task = work["objective"] + "\nObserved source: " + source["text"][:650]
        followthrough = None
        if work["kind"] == "followthrough":
            task += "\nCheck what the scheduled outcome established; the original schedule alone cannot prove it occurred."
            listing = universe.instrument(db, source["instrument_id"])
            if source["origin"] in sources_calendar.ROUTE_LABELS and sources_calendar.eligible(
                listing, source["origin"]
            ):
                checked = monitor._capture(db, listing, source["origin"])
                followthrough = {
                    k: checked.get(k)
                    for k in (
                        "status",
                        "receipt_id",
                        "document_id",
                        "cached",
                        "checked_at",
                    )
                }
            else:
                followthrough = {"status": "no eligible update route"}
        for f in prior:
            task += "\nPrior open question: " + f["question"][:240]
        if not is_fixture(db) and local_model.available():
            focus, runtime = local_model.choose(task[:2000], FOCI)
        else:
            focus = "expectations" if "earn" in source["kind"] else "disclosure"
            runtime = {
                "mode": "fixture" if is_fixture(db) else "local_source_tools",
                "selected_plan": focus,
            }
        result = methods.event_report(
            db,
            work["event_version_id"],
            goal_id=work["goal_id"],
            instrument_id=work["instrument_id"],
            objective=task[:3000],
            focus=focus,
            request_key=work["id"],
        )
        method_id = result["id"]
        impacts = []
        for item in goals.listings(db, work["scope"]):
            impacts.extend(
                {**link, "ticker": item["ticker"]}
                for link in exposure.for_event(db, item, work["event_version_id"])
            )
        body = {
            "title": result["title"],
            "summary": result["summary"],
            "status": result["status"],
            "exposures": impacts,
            "next_observations": result["body"]["next_observations"],
            "citations": result["body"]["citations"],
            "gaps": result["body"]["gaps"],
        }
        if followthrough is not None:
            body.update(
                title="Outcome check · " + result["title"],
                status="partial",
                followthrough=followthrough,
                summary="The scheduled window has ended. The retained event edition does not establish an outcome.",
                gaps=[
                    *body["gaps"],
                    "A dated account of what occurred is still required.",
                ],
            )
    else:
        plan = db.execute("SELECT * FROM goal_plans WHERE id=?", (work["plan_id"],)).fetchone()
        deadlines = db.execute(
            "SELECT due_at,state FROM goal_deadlines WHERE report_id=? ORDER BY due_at",
            (work["id"],),
        ).fetchall()
        since = max(plan["created_at"], _shift(deadlines[0][0] if deadlines else stamp, days=-1))
        checked = goals.coverage(db, plan, since, stamp)
        records = db.execute(
            """SELECT id,body FROM goal_dispatch WHERE plan_id=? AND decision_id IS NOT NULL
                             AND state='complete' AND ended_at BETWEEN ? AND ? ORDER BY ended_at DESC LIMIT 30""",
            (work["plan_id"], since, stamp),
        ).fetchall()
        ok = sum(c["state"] == "ok" for c in checked)
        body = {
            "title": "Recovery update" if work["kind"] == "recovery" else "Scheduled research update",
            "summary": f"{len(records)} completed event investigations in the coverage interval. {ok} of {len(checked)} required source checks have a successful receipt.",
            "coverage": checked,
            "interval": [since, stamp],
            "reports": [{"id": r["id"], "title": json.loads(r["body"])["title"]} for r in records],
            "status": "complete" if checked and ok == len(checked) else "partial",
            "missed": sum(d["state"] == "missed" for d in deadlines),
            "gaps": [],
            "next_observations": [],
        }
    return body, method_id, runtime, prior


def _notify(db, work, finished):
    group = work["id"]
    if work["decision_id"]:
        common = db.execute(
            """SELECT c.origin_group,c.subject,c.signature FROM event_versions e JOIN calendar_reports c
            ON c.source_ref=e.source_ref WHERE e.id=? AND c.provider IN ('fed_calendar','bls_calendar')""",
            (work["event_version_id"],),
        ).fetchone()
        if common:
            group = hashlib.sha256(json.dumps([work["plan_id"], work["kind"], *common]).encode()).hexdigest()
    first = db.execute(
        "SELECT notice_id FROM goal_report_delivery WHERE group_key=? LIMIT 1", (group,)
    ).fetchone()
    notice = (
        first[0]
        if first
        else delivery.enqueue(
            db,
            key="goal:" + work["id"],
            title=(assistant.profile(db)["label"]+" · research update") if assistant.profile(db)["replay_clock"] else "Stock Insight research update",
            message="A research report is ready in your private desk.",
            report_path="/goals/reports/" + work["id"],
            at=finished,
        )
    )
    db.execute("INSERT INTO goal_report_delivery VALUES(?,?,?)", (work["id"], notice, group))


def tick(db, *, at=None):
    stamp = instant(at or now())
    plans = goals.active(db)
    goals.reconcile_sources(db, plans, stamp)
    for plan in plans:
        _discover(db, plan, stamp)
        _linked(db, plan, stamp)
        _deadlines(db, plan, stamp)
    work = _claim(db, stamp)
    if not work:
        return None
    try:
        if work["decision_id"] and assistant.profile(db)["enabled"]:
            assistant.enqueue(db, work, stamp)
            return work["id"]
        body, method_id, runtime, prior = _run(db, work, stamp)
    except (ValueError, OSError) as exc:
        with write(db):
            db.execute(
                """UPDATE goal_dispatch SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'ready' END,
                ready_at=?,detail=? WHERE id=? AND state='running' AND lease_id=?""",
                (
                    _shift(stamp, minutes=5),
                    str(exc)[:240] if isinstance(exc, ValueError) else "Source unavailable",
                    work["id"],
                    work["lease_id"],
                ),
            )
        return work["id"]
    finished = instant(at or now())
    with write(db):
        if work["decision_id"] and not _eligible_work(db, work, finished):
            db.execute(
                """UPDATE goal_dispatch SET state='superseded',ended_at=?,detail='Event or scope changed during research'
                        WHERE id=? AND state='running' AND lease_id=?""",
                (finished, work["id"], work["lease_id"]),
            )
            return work["id"]
        changed = db.execute(
            """UPDATE goal_dispatch SET state='complete',ended_at=?,method_report=?,body=?,runtime=?
            WHERE id=? AND state='running' AND lease_id=? AND lease_until>? AND EXISTS(
            SELECT 1 FROM goal_plans p WHERE p.id=plan_id AND p.ended_at IS NULL) AND
            (kind<>'scheduled' OR EXISTS(SELECT 1 FROM goal_deadlines g WHERE g.report_id=goal_dispatch.id AND g.state='started'))""",
            (
                finished,
                method_id,
                json.dumps(body),
                json.dumps(runtime),
                work["id"],
                work["lease_id"],
                finished,
            ),
        ).rowcount
        if changed:
            for f in prior:
                db.execute("INSERT INTO goal_context_reads VALUES(?,?)", (work["id"], f["id"]))
            for question in body["next_observations"]:
                db.execute(
                    "INSERT OR IGNORE INTO goal_followups VALUES(?,?,?,?,?)",
                    (
                        uid("followup"),
                        work["id"],
                        work["instrument_id"],
                        question,
                        finished,
                    ),
                )
            db.execute(
                """UPDATE goal_deadlines SET state=CASE WHEN state='missed' OR (due_at<? AND
                (SELECT intent FROM goal_plans WHERE id=plan_id)='report_by') THEN 'missed' ELSE 'completed' END,
                finished_at=? WHERE report_id=?""",
                (finished, finished, work["id"]),
            )
            _notify(db, work, finished)
    return work["id"]
