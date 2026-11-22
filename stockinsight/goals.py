"""Versioned standing research instructions, their coverage and their report deadlines."""

import json
import re
from datetime import datetime, timedelta

from . import goal_schedule, monitor, universe
from .db import instant, is_fixture, now, uid, write

SCHEMA = """
CREATE TABLE goal_plans(
 id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, version INTEGER NOT NULL, request_key TEXT NOT NULL UNIQUE,
 objective TEXT NOT NULL, scope TEXT NOT NULL, cadence TEXT NOT NULL, clock TEXT NOT NULL, timezone TEXT NOT NULL,
 intent TEXT NOT NULL, daily_limit INTEGER NOT NULL, created_at TEXT NOT NULL, ended_at TEXT,
 expand_on TEXT NOT NULL, commit_seq INTEGER NOT NULL REFERENCES commits, UNIQUE(goal_id,version)
);
CREATE UNIQUE INDEX goal_active ON goal_plans(goal_id) WHERE ended_at IS NULL;
CREATE TABLE goal_deadlines(
 id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES goal_plans, start_at TEXT NOT NULL,due_at TEXT NOT NULL,
 state TEXT NOT NULL,started_at TEXT,finished_at TEXT,report_id TEXT,UNIQUE(plan_id,due_at)
);
CREATE TABLE goal_auto_sources(schedule_id INTEGER PRIMARY KEY REFERENCES monitor_schedules);
CREATE TABLE goal_relevance(
 id TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES goal_plans,event_version_id TEXT NOT NULL REFERENCES event_versions,
 instrument_id TEXT NOT NULL REFERENCES instruments, decision TEXT NOT NULL, reason TEXT NOT NULL, priority INTEGER NOT NULL,
 observed_at TEXT NOT NULL, next_check TEXT, UNIQUE(plan_id,event_version_id)
);
CREATE TABLE goal_dispatch(
 id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES goal_plans, decision_id TEXT REFERENCES goal_relevance,
 trigger_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, ready_at TEXT NOT NULL,
 lease_id TEXT,lease_until TEXT,attempts INTEGER NOT NULL DEFAULT 0, ended_at TEXT,
 method_report TEXT, body TEXT, runtime TEXT, reviewed_at TEXT, detail TEXT
);
CREATE INDEX goal_dispatch_due ON goal_dispatch(state,ready_at);
CREATE TABLE goal_followups(
 id TEXT PRIMARY KEY,report_id TEXT NOT NULL REFERENCES goal_dispatch, instrument_id TEXT NOT NULL REFERENCES instruments,
 question TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(report_id,question)
);
CREATE TABLE goal_context_reads(
 report_id TEXT NOT NULL REFERENCES goal_dispatch,followup_id TEXT NOT NULL REFERENCES goal_followups,
 PRIMARY KEY(report_id,followup_id)
);
CREATE TABLE goal_runtime_usage(
 dispatch_id TEXT NOT NULL REFERENCES goal_dispatch,attempt INTEGER NOT NULL,started_at TEXT NOT NULL,
 engine TEXT NOT NULL,PRIMARY KEY(dispatch_id,attempt)
);
"""


def listings(db, scope):
    items = universe.universe(db)["instruments"]
    if scope == "watchlist":
        return items
    kind, _, key = scope.partition(":")
    if kind == "listing":
        return [i for i in items if i["id"] == key]
    if kind == "theme":
        # Include only explicit accepted listing links or watched listings of accepted companies.
        linked = db.execute(
            "SELECT instrument_id,company_id FROM theme_memberships WHERE status='accepted' AND theme_id=?", (key,)
        ).fetchall()
        return [i for i in items if any(i["id"] == m[0] or (m[1] and i["company_id"] == m[1]) for m in linked)]
    return []


def save(db, data, *, at=None):
    stamp = instant(at or now())
    objective = data.get("objective", "").strip()
    scope = data.get("scope", "watchlist")
    key = data.get("key", "")
    if not 5 <= len(objective) <= 1500 or not re.fullmatch(r"[\w-]{1,128}", key):
        raise ValueError("Enter a standing objective and use a fresh form")
    if scope != "watchlist" and not listings(db, scope):
        raise ValueError("Choose an active listing or a theme with active listings")
    schedule = goal_schedule.interpret(objective, timezone=data.get("timezone") or "America/Toronto",
                                       cadence=data.get("cadence") or "auto", clock=data.get("clock", ""),
                                       intent=data.get("intent") or "auto")
    limit = int(data.get("daily_limit") or 3)
    if not 1 <= limit <= 12:
        raise ValueError("Choose one to twelve event investigations per goal per UTC day")
    with write(db) as seq:
        previous = db.execute("SELECT * FROM goal_plans WHERE request_key=?", (key,)).fetchone()
        if previous:
            if (previous["objective"],previous["scope"],previous["daily_limit"]) != (objective,scope,limit) or any(
                previous[k] != v for k,v in schedule.items()
            ):
                raise ValueError("Goal form already submitted with different instructions")
            return previous["id"]
        old_id = data.get("plan")
        if old_id:
            prior = _end(db,old_id,stamp)
            goal_id, version = prior["goal_id"], prior["version"]+1
        else:
            goal_id, version = uid("goal"), 1
        plan_id = uid("plan")
        day = datetime.fromisoformat(stamp).astimezone(goal_schedule.zone(schedule["timezone"])).date()
        db.execute(
            """INSERT INTO goal_plans(id,goal_id,version,request_key,objective,scope,cadence,clock,timezone,
               intent,daily_limit,created_at,expand_on,commit_seq)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (plan_id, goal_id, version, key, objective, scope, schedule["cadence"],schedule["clock"],
             schedule["timezone"],schedule["intent"],limit,stamp,day.isoformat(),seq),
        )
        goal_schedule.expand(db,db.execute("SELECT * FROM goal_plans WHERE id=?",(plan_id,)).fetchone(),stamp)
    return plan_id


def _end(db, plan_id, stamp):
    plan = db.execute("SELECT * FROM goal_plans WHERE id=? AND ended_at IS NULL",(plan_id,)).fetchone()
    if not plan:
        raise ValueError("Goal changed. Reload its current instructions.")
    goal_schedule.expand(db,plan,stamp)
    db.execute("UPDATE goal_plans SET ended_at=? WHERE id=?", (stamp,plan_id))
    db.execute("""UPDATE goal_deadlines SET state=CASE WHEN due_at<? THEN 'missed' ELSE 'cancelled' END,
                  finished_at=? WHERE plan_id=? AND state IN ('pending','started')""",(stamp,stamp,plan_id))
    db.execute("UPDATE goal_dispatch SET state='cancelled',ended_at=? WHERE plan_id=? AND state IN ('ready','running')",
               (stamp,plan_id))
    return plan


def action(db, command, data):
    if command == "goal-save":
        save(db,data)
    elif command == "goal-stop":
        with write(db):
            _end(db,data["plan"],now())
    elif command == "goal-review":
        with write(db):
            if not db.execute("""UPDATE goal_dispatch SET reviewed_at=coalesce(reviewed_at,?)
                                 WHERE id=? AND state='complete'""",(now(),data["report"])).rowcount:
                raise ValueError("Choose a completed goal report")
        return "/goals/reports/" + data["report"]
    else:
        raise ValueError("Unknown goal operation")
    return "/goals"


def routes(db, listing):
    from . import sources_calendar

    if is_fixture(db):
        return {"issuer": 1440}
    return sources_calendar.recommended(listing)


def reconcile_sources(db, plans, stamp):
    desired = {}
    for plan in plans:
        for item in listings(db,plan["scope"]):
            for provider, interval in routes(db,item).items():
                desired[(item["id"],provider)] = interval
    current = {(r["instrument_id"],r["provider"]):r for r in db.execute(
        """SELECT s.*,a.schedule_id AS managed FROM monitor_schedules s
           LEFT JOIN goal_auto_sources a ON a.schedule_id=s.id WHERE s.superseded_at IS NULL""")}
    for key, interval in desired.items():
        old = current.get(key)
        if old is None or (old["managed"] and not old["enabled"]):
            _configure(db,key,interval,True,stamp,old)
    for key,old in current.items():
        if old["managed"] and old["enabled"] and key not in desired:
            _configure(db,key,old["interval_minutes"],False,stamp,old)


def _configure(db, key, interval, enabled, stamp, old):
    try:
        monitor.configure(db,*key,interval,enabled,at=stamp,expected_id=old["id"] if old else None,goal_managed=True)
    except ValueError:
        return  # Membership or a manual schedule changed during reconciliation.


def coverage(db, plan, start, stamp):
    entries = []
    for item in listings(db,plan["scope"]):
        required = routes(db,item)
        if not is_fixture(db) and "sec_filing" not in required and re.search(r"\b(?:filings?|8-k|10-[kq]|sec)\b",plan["objective"],re.I):
            entries.append({"ticker":item["ticker"],"provider":"SEC filings","state":"unavailable (eligible identity and SEC contact required)"})
        if not required:
            entries.append({"ticker":item["ticker"],"provider":"issuer identity or source access","state":"unavailable"})
        for provider, interval in required.items():
            row = db.execute("""SELECT id,status,finished_at,document_id FROM source_checks
                WHERE instrument_id=? AND provider=? AND finished_at BETWEEN ? AND ?
                ORDER BY finished_at DESC LIMIT 1""",(item["id"],provider,start,stamp)).fetchone()
            schedule = db.execute("SELECT enabled FROM monitor_schedules WHERE instrument_id=? AND provider=? AND superseded_at IS NULL",
                                  (item["id"],provider)).fetchone()
            entries.append({"ticker":item["ticker"],"provider":provider,"state":row["status"] if row else "unchecked",
                            "enabled":bool(schedule and schedule[0]), "interval_minutes":interval,
                            "receipt":dict(row) if row else None})
    return entries


def active(db):
    return db.execute("SELECT * FROM goal_plans WHERE ended_at IS NULL ORDER BY created_at,id").fetchall()


def dashboard(db):
    return {
        "plans":[dict(p) for p in active(db)],
        "reports":[dict(r) for r in db.execute("""SELECT d.*,p.objective,json_extract(d.body,'$.title') AS title FROM goal_dispatch d JOIN goal_plans p ON p.id=d.plan_id
                    ORDER BY coalesce(d.ended_at,d.ready_at) DESC,d.rowid DESC LIMIT 80""")],
        "deadlines":[dict(r) for r in db.execute("""SELECT p.objective,g.* FROM goal_deadlines g JOIN goal_plans p ON p.id=g.plan_id
                    WHERE g.state<>'pending' OR g.due_at=(SELECT min(x.due_at) FROM goal_deadlines x WHERE x.plan_id=g.plan_id AND x.state='pending')
                    ORDER BY g.due_at DESC LIMIT 60""")],
        "decisions":[dict(r) for r in db.execute("SELECT * FROM goal_relevance ORDER BY rowid DESC LIMIT 60")],
        "versions":[dict(r) for r in db.execute("SELECT * FROM goal_plans WHERE ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 30")],
        "usage":db.execute("SELECT count(*) FROM goal_runtime_usage WHERE started_at>=?",(now()[:10],)).fetchone()[0],
    }


def report(db, report_id):
    row = db.execute("""SELECT d.*,p.objective,r.reason,r.instrument_id,r.event_version_id FROM goal_dispatch d
        JOIN goal_plans p ON p.id=d.plan_id LEFT JOIN goal_relevance r ON r.id=d.decision_id WHERE d.id=?""",(report_id,)).fetchone()
    if not row or row["state"] != "complete":
        raise ValueError("Unknown completed goal report")
    result = dict(row)
    result.update(body=json.loads(row["body"]),runtime=json.loads(row["runtime"] or "{}"),
                  followups=[dict(f) for f in db.execute("SELECT * FROM goal_followups WHERE report_id=?",(report_id,))],
                  context_reads=[dict(f) for f in db.execute("""SELECT f.* FROM goal_followups f JOIN goal_context_reads r
                                 ON r.followup_id=f.id WHERE r.report_id=?""",(report_id,))])
    return result
