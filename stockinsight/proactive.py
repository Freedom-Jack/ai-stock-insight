"""Dispatch standing goals from watchlist evidence and persist independent delivery work."""

import json
import re
from datetime import UTC, datetime, timedelta

from . import delivery, goal_schedule, goals, local_model, methods
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


def _decision(plan, e, stamp):
    if e["supersedes"]:
        return "investigate", "The named source revised an earlier watchlist event. Compare both editions.", 100, None
    day = (e["scheduled_start"] or e["occurred_at"] or "")[:10]
    age = (datetime.fromisoformat(stamp).date() - datetime.fromisoformat(day).date()).days if day else None
    if e["state"] == "occurred" and (age is None or age > 7):
        return "suppress", "Historical observation retained for context outside the seven-day discovery window.", 0, None
    if e["state"] in ("confirmed","tentative","postponed") and age is not None:
        if age > 0:
            return "suppress", "The scheduled date has passed. A published outcome is still required.", 0, None
        if age < -30:
            due = (datetime.fromisoformat(day).replace(tzinfo=UTC) - timedelta(days=30)).isoformat()
            return "later", "Prepare when the event enters the thirty-day horizon.", 10, instant(due)
        return "prepare", "A sourced watchlist event is within the thirty-day preparation window.", 85, None
    text = (e["kind"].replace("_"," ") + " " + e["text"]).casefold()
    topics = {name for name,pattern in EVENT_WORDS.items() if re.search(pattern,text)}
    requested = {name for name,pattern in EVENT_WORDS.items() if re.search(pattern,plan["objective"],re.I)}
    if requested and not requested.intersection(topics):
        return "suppress", "The observed subject falls outside this goal's research topics.", 0, None
    if topics or e["kind"] in ("earnings_release","financial_filing"):
        return "investigate", "Primary-source development for a watched listing: " + ", ".join(sorted(topics) or ["filing"]) + ".", 75, None
    # Specific subjects in the operator's goal may warrant a read without matching a financial category.
    stop = {"keep","prepared","important","developments","affecting","these","companies","watchlist",
            "monitor","research","about","report","notify","please","weekly","daily","watch","updates","news","company"}
    terms = {t for t in re.findall(r"[a-z]{4,}",plan["objective"].casefold()) if t not in stop}
    matching = sorted(terms.intersection(re.findall(r"[a-z]{4,}",text)))
    if matching:
        return "investigate", "The primary observation matches the adopted subject: "+", ".join(matching[:4])+".", 60,None
    return "suppress", "Logged in watchlist coverage. No specific material change was identified for this goal.", 0,None


def _queue(db, plan_id, key, kind, ready, decision=None):
    db.execute("""INSERT OR IGNORE INTO goal_dispatch(id,plan_id,trigger_key,kind,state,ready_at,decision_id)
                  VALUES(?,?,?,?,'ready',?,?)""",(uid("dispatch"),plan_id,key,kind,ready,decision))
    return db.execute("SELECT id FROM goal_dispatch WHERE trigger_key=?", (key,)).fetchone()[0]


def _discover(db, plan, stamp):
    for item in goals.listings(db,plan["scope"]):
        rows = db.execute("""SELECT e.*,p.text,r.id AS known FROM event_versions e
            JOIN evidence_passages p ON p.id=e.source_ref
            LEFT JOIN goal_relevance r ON r.event_version_id=e.id AND r.plan_id=?
            WHERE e.instrument_id=? AND (r.id IS NULL OR (r.decision='later' AND r.next_check<=?))
            AND NOT EXISTS(SELECT 1 FROM event_versions n WHERE n.supersedes=e.id)
            ORDER BY e.commit_seq DESC LIMIT 64""",(plan["id"],item["id"],stamp)).fetchall()
        if not rows:
            continue
        with write(db):
            for e in rows:
                decision,reason,priority,when = _decision(plan,e,stamp)
                ident = e["known"] or uid("relevance")
                if e["known"]:
                    db.execute("UPDATE goal_relevance SET decision=?,reason=?,priority=?,next_check=? WHERE id=?",
                               (decision,reason,priority,when,ident))
                else:
                    changed = db.execute("""INSERT OR IGNORE INTO goal_relevance VALUES(?,?,?,?,?,?,?,?,?)""",
                        (ident,plan["id"],e["id"],item["id"],decision,reason,priority,stamp,when)).rowcount
                    if not changed:
                        continue
                if e["supersedes"]:
                    db.execute("""UPDATE goal_dispatch SET state='superseded',ended_at=? WHERE state IN ('ready','running')
                        AND decision_id IN (SELECT r.id FROM goal_relevance r JOIN event_versions v ON v.id=r.event_version_id
                        WHERE r.plan_id=? AND v.event_id=? AND v.id<>?)""",(stamp,plan["id"],e["event_id"],e["id"]))
                if decision in ("investigate","prepare"):
                    _queue(db,plan["id"],f"{plan['id']}:{e['id']}:event","event",stamp,ident)
                    if e["scheduled_start"] and e["state"] in ("confirmed","tentative","postponed"):
                        # A date-only source supplies no intraday moment. Check after the full local date.
                        end = e["scheduled_end"] or e["scheduled_start"]
                        if len(end) == 10:
                            tz = goal_schedule.zone(e["source_timezone"] or plan["timezone"])
                            end = goal_schedule.civil(datetime.fromisoformat(end).date()+timedelta(days=1),"00:00",tz).isoformat()
                        _queue(db,plan["id"],f"{plan['id']}:{e['id']}:follow","followthrough",_shift(end,hours=1),ident)


def _deadlines(db, plan, stamp):
    today = datetime.fromisoformat(stamp).astimezone(goal_schedule.zone(plan["timezone"])).date()
    horizon = (today + timedelta(days=14)).isoformat()
    expansion_due = plan["expand_on"] <= horizon and (
        plan["cadence"] not in ("closing","premarket") or int(plan["expand_on"][:4]) in goal_schedule.CLOSED)
    if not expansion_due and not db.execute("""SELECT 1 FROM goal_deadlines WHERE plan_id=? AND
        ((state='pending' AND start_at<=?) OR (state='started' AND due_at<? AND ?='report_by')) LIMIT 1""",
        (plan["id"],stamp,stamp,plan["intent"])).fetchone():
        return
    with write(db):
        goal_schedule.expand(db,plan,stamp)
        # A report-by target cannot be rendered timely by starting after its deadline.
        # A start-at target cares when work was first dispatched.
        overdue = db.execute("""SELECT * FROM goal_deadlines WHERE plan_id=? AND state IN ('pending','started')
            AND due_at<? AND (state='pending' OR ?='report_by') ORDER BY due_at""",
            (plan["id"],_shift(stamp,seconds=-60) if plan["intent"]=="start_at" else stamp,plan["intent"])).fetchall()
        if overdue:
            key = f"{plan['id']}:catch-up:{overdue[-1]['due_at']}"
            work = _queue(db,plan["id"],key,"recovery",stamp)
            for d in overdue:
                if d["report_id"]:
                    db.execute("UPDATE goal_dispatch SET state='superseded' WHERE id=? AND state='ready'",(d["report_id"],))
                db.execute("UPDATE goal_deadlines SET state='missed',report_id=? WHERE id=?",(work,d["id"]))
        for d in db.execute("""SELECT * FROM goal_deadlines WHERE plan_id=? AND state='pending'
                            AND start_at<=? ORDER BY due_at""",(plan["id"],stamp)).fetchall():
            work = _queue(db,plan["id"],f"{plan['id']}:deadline:{d['due_at']}","scheduled",stamp)
            db.execute("UPDATE goal_deadlines SET state='started',started_at=?,report_id=? WHERE id=?",
                       (stamp,work,d["id"]))


def _claim(db, stamp):
    midnight = stamp[:10]
    if not db.execute("""SELECT 1 FROM goal_dispatch WHERE
           (state='ready' AND ready_at<=?) OR (state='running' AND lease_until<=?) LIMIT 1""",(stamp,stamp)).fetchone():
        return None
    with write(db):
        db.execute("""UPDATE goal_dispatch SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'ready' END,
                      detail='Worker lease expired' WHERE state='running' AND lease_until<=?""",(stamp,))
        candidates = db.execute("""SELECT d.*,p.goal_id,p.objective,p.scope,p.daily_limit,
            r.event_version_id,r.instrument_id,r.priority,r.reason FROM goal_dispatch d JOIN goal_plans p ON p.id=d.plan_id
            LEFT JOIN goal_relevance r ON r.id=d.decision_id
            WHERE p.ended_at IS NULL AND d.state='ready' AND d.ready_at<=?
            ORDER BY (d.decision_id IS NULL) DESC, r.priority DESC, d.ready_at,d.rowid LIMIT 200""",(stamp,)).fetchall()
        for work in candidates:
            if work["decision_id"]:
                if not _eligible_work(db,work,stamp):
                    db.execute("UPDATE goal_dispatch SET state='superseded',ended_at=?,detail='Event or scope changed before dispatch' WHERE id=?",
                               (stamp,work["id"]))
                    continue
                used, personal = db.execute("""SELECT count(*),coalesce(sum(p.goal_id=?),0) FROM goal_runtime_usage u
                    JOIN goal_dispatch d ON d.id=u.dispatch_id JOIN goal_plans p ON p.id=d.plan_id WHERE u.started_at>=?""",
                    (work["goal_id"],midnight)).fetchone()
                if used >= GLOBAL_DAILY_LIMIT or personal >= work["daily_limit"]:
                    db.execute("UPDATE goal_dispatch SET ready_at=?,detail='Daily research budget reached' WHERE id=?",
                               (_shift(midnight+"T00:00:00Z",days=1),work["id"]))
                    continue
            lease = uid("lease")
            db.execute("""UPDATE goal_dispatch SET state='running',attempts=attempts+1,lease_id=?,lease_until=?,detail=NULL
                          WHERE id=?""",(lease,_shift(stamp,minutes=5),work["id"]))
            if work["decision_id"]:
                db.execute("INSERT INTO goal_runtime_usage VALUES(?,?,?,?)",(work["id"],work["attempts"]+1,stamp,
                           "fixture" if is_fixture(db) else "on_device" if local_model.available() else "local"))
            return {**dict(work),"lease_id":lease}
    return None


def _eligible_work(db,work,stamp):
    if work["instrument_id"] not in {i["id"] for i in goals.listings(db,work["scope"])}:
        return False
    event=db.execute("""SELECT v.* FROM event_versions v WHERE v.id=? AND NOT EXISTS
                     (SELECT 1 FROM event_versions n WHERE n.supersedes=v.id)""",(work["event_version_id"],)).fetchone()
    if event is None:
        return False
    if work["kind"]=="event" and event["state"]=="occurred" and not event["supersedes"]:
        return bool(event["occurred_at"] and event["occurred_at"][:10]>=_shift(stamp,days=-7)[:10])
    return True


def _run(db, work, stamp):
    prior, method_id, runtime = [], None, {}
    if work["decision_id"]:
        prior = db.execute("""SELECT f.* FROM goal_followups f JOIN goal_dispatch d ON d.id=f.report_id
            JOIN goal_plans p ON p.id=d.plan_id WHERE p.goal_id=? AND f.instrument_id=?
            ORDER BY f.created_at DESC,f.id LIMIT 2""",(work["goal_id"],work["instrument_id"])).fetchall()
        source = db.execute("""SELECT p.text,v.kind FROM event_versions v JOIN evidence_passages p ON p.id=v.source_ref
                            WHERE v.id=?""",(work["event_version_id"],)).fetchone()
        task = work["objective"] + "\nObserved source: " + source["text"][:650]
        if work["kind"] == "followthrough":
            task += "\nCheck what the scheduled outcome established; the original schedule alone cannot prove it occurred."
        for f in prior:
            task += "\nPrior open question: " + f["question"][:240]
        if not is_fixture(db) and local_model.available():
            focus,runtime = local_model.choose(task[:2000],FOCI)
        else:
            focus = "expectations" if "earn" in source["kind"] else "disclosure"
            runtime = {"mode":"fixture" if is_fixture(db) else "local_source_tools","selected_plan":focus}
        result = methods.event_report(db,work["event_version_id"],goal_id=work["goal_id"],
                                      objective=task[:3000],focus=focus,request_key=work["id"])
        method_id = result["id"]
        body = {"title":result["title"],"summary":result["summary"],"status":result["status"],
                "next_observations":result["body"]["next_observations"],
                "citations":result["body"]["citations"],"gaps":result["body"]["gaps"]}
    else:
        plan = db.execute("SELECT * FROM goal_plans WHERE id=?",(work["plan_id"],)).fetchone()
        deadlines = db.execute("SELECT due_at,state FROM goal_deadlines WHERE report_id=? ORDER BY due_at",(work["id"],)).fetchall()
        since = max(plan["created_at"], _shift(deadlines[0][0] if deadlines else stamp,days=-1))
        checked = goals.coverage(db,plan,since,stamp)
        records = db.execute("""SELECT id,body FROM goal_dispatch WHERE plan_id=? AND decision_id IS NOT NULL
                             AND state='complete' AND ended_at BETWEEN ? AND ? ORDER BY ended_at DESC LIMIT 30""",
                             (work["plan_id"],since,stamp)).fetchall()
        ok = sum(c["state"] == "ok" for c in checked)
        body = {"title":"Recovery update" if work["kind"]=="recovery" else "Scheduled research update",
                "summary":f"{len(records)} completed event investigations in the coverage interval. {ok} of {len(checked)} required source checks have a successful receipt.",
                "coverage":checked,"interval":[since,stamp],"reports":[{"id":r["id"],"title":json.loads(r["body"])["title"]} for r in records],
                "status":"complete" if checked and ok == len(checked) else "partial",
                "missed":sum(d["state"]=="missed" for d in deadlines),"gaps":[],"next_observations":[]}
    return body,method_id,runtime,prior


def tick(db, *, at=None):
    stamp = instant(at or now())
    plans = goals.active(db)
    goals.reconcile_sources(db,plans,stamp)
    for plan in plans:
        _discover(db,plan,stamp)
        _deadlines(db,plan,stamp)
    work = _claim(db,stamp)
    if not work:
        return None
    try:
        body,method_id,runtime,prior = _run(db,work,stamp)
    except (ValueError,OSError) as exc:
        with write(db):
            db.execute("""UPDATE goal_dispatch SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'ready' END,
                ready_at=?,detail=? WHERE id=? AND state='running' AND lease_id=?""",
                (_shift(stamp,minutes=5),str(exc)[:240] if isinstance(exc,ValueError) else "Source unavailable",
                 work["id"],work["lease_id"]))
        return work["id"]
    finished = instant(at or now())
    with write(db):
        if work["decision_id"] and not _eligible_work(db,work,finished):
            db.execute("""UPDATE goal_dispatch SET state='superseded',ended_at=?,detail='Event or scope changed during research'
                        WHERE id=? AND state='running' AND lease_id=?""",(finished,work["id"],work["lease_id"]))
            return work["id"]
        changed = db.execute("""UPDATE goal_dispatch SET state='complete',ended_at=?,method_report=?,body=?,runtime=?
            WHERE id=? AND state='running' AND lease_id=? AND lease_until>? AND EXISTS(
            SELECT 1 FROM goal_plans p WHERE p.id=plan_id AND p.ended_at IS NULL)""",
            (finished,method_id,json.dumps(body),json.dumps(runtime),work["id"],work["lease_id"],finished)).rowcount
        if changed:
            for f in prior:
                db.execute("INSERT INTO goal_context_reads VALUES(?,?)",(work["id"],f["id"]))
            for question in body["next_observations"]:
                db.execute("INSERT OR IGNORE INTO goal_followups VALUES(?,?,?,?,?)",
                           (uid("followup"),work["id"],work["instrument_id"],question,finished))
            db.execute("""UPDATE goal_deadlines SET state=CASE WHEN state='missed' OR (due_at<? AND
                (SELECT intent FROM goal_plans WHERE id=plan_id)='report_by') THEN 'missed' ELSE 'completed' END,
                finished_at=? WHERE report_id=?""",(finished,finished,work["id"]))
            delivery.enqueue(db,key="goal:"+work["id"],title="Stock Insight research update",
                             message="A research report is ready in your private desk.",
                             report_path="/goals/reports/"+work["id"],at=finished)
    return work["id"]
