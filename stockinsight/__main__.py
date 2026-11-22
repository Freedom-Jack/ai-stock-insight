"""Foreground operator commands for the private Stock Insight research desk."""

import argparse
import json
import os
import secrets
import socket
import sqlite3
import sys
import webbrowser
from contextlib import closing
from pathlib import Path

from . import delivery, evidence, executor, local_research, memory, proactive, providers, research, sources_calendar, universe, workspace
from .db import connect, is_fixture

EXAMPLE = Path(__file__).with_name("fixtures") / "training-list.csv"
DEMO_QUESTION = "NVIDIA has fallen. Does the available evidence support buying after the release?"
DEMO_CUTOFF = "2024-08-29T12:00:00Z"


def display(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=True))


def select(db, value):
    options = universe.universe(db)["instruments"]
    exact = [i for i in options if i["id"] == value]
    if exact:
        return exact[0]
    matches = [i for i in options if i["ticker"] == value.upper()]
    if len(matches) != 1:
        raise ValueError("Select a unique active listing by the ID shown in universe")
    return matches[0]


def print_case(record):
    print(record["question"])
    print(f"Case {record['id']} | {record['instrument']['ticker']} | {record['jobs'][0]['state']}")
    if record["cutoff"]:
        print("Public-information cutoff", record["cutoff"])
    if not record["briefs"]:
        print(record["jobs"][0]["detail"] or "No accepted interpretation")
        return
    brief = record["briefs"][0]
    body = brief["body"]
    print(f"Revision {brief['revision']} | {brief['as_of']} | {brief['method']}")
    print(body["conclusion"])
    for item in body["claims"]:
        print(f"  [{item['type']}] {item['text']}")
        for ref in item["evidence_refs"]:
            p = brief["sources"][ref]
            print(f"    {p['title']} | {p['locator']} | {p['version_hash'][:12]} | {p['source_url']}")
    for g in record["gaps"]:
        if g["id"] in body["gaps"]:
            print("Gap:", g["impact"])
    for item in body["alternative_explanations"]:
        print("Alternative:", item)
    for item in body["next_steps"]:
        print("Next check:", item)


def demo(db):
    snap = universe.import_snapshot(db, EXAMPLE.read_bytes(), complete=True, source_id="demo")
    if snap["state"] != "complete":
        raise ValueError("Example list requires review in the fixture workspace")
    item = select(db, "NVDA")
    evidence.seed_fixture(db, item["id"])
    job = research.ask(db, item["id"], DEMO_QUESTION, cutoff=DEMO_CUTOFF, request_key="nvidia-demo-v1")
    row = db.execute("SELECT state,case_id FROM jobs WHERE id=?", (job,)).fetchone()
    if row["state"] in ("ready", "leased"):
        research.run_job(db, job)
    record = workspace.case_detail(db, row["case_id"])
    print("Offline fixture investigation")
    print_case(record)
    return 0 if record["briefs"] else 1


def build_parser():
    app = argparse.ArgumentParser(description=__doc__)
    app.add_argument("--data-dir", type=Path, help="Private workspace directory")
    app.add_argument("--fixture", action="store_true", help="Use the isolated fixture workspace")
    actions = app.add_subparsers(required=True, dest="action")
    for name in ("demo", "doctor", "universe", "cases", "fiscal-discover"):
        actions.add_parser(name)
    verify = actions.add_parser("verify-sources")
    verify.add_argument("--after", default="", help="Continue a previous page of verification")
    for name, field in (
        ("accept", "snapshot_id"),
        ("case", "case_id"),
        ("run-job", "job_id"),
        ("continue", "case_id"),
        ("review", "brief_id"),
        ("fiscal-probe", "listing"),
    ):
        command = actions.add_parser(name)
        command.add_argument(field)
        if name in ("continue", "run-job"):
            command.add_argument("--engine", choices=("local", "device", "responses"))
    file = actions.add_parser("import-list")
    file.add_argument("file", type=Path)
    file.add_argument("--source", default="personal")
    file.add_argument("--complete", action="store_true", help="Declare this a full replacement snapshot")
    cap = actions.add_parser("capture")
    cap.add_argument("listing")
    cap.add_argument("--provider", choices=tuple(sources_calendar.ROUTE_LABELS), default="issuer")
    archive=actions.add_parser("export-case")
    archive.add_argument("case_id")
    archive.add_argument("file",type=Path)
    history=actions.add_parser("import-research")
    history.add_argument("listing")
    history.add_argument("file",type=Path)
    history.add_argument("--kind",choices=("case","conversation"),required=True)
    history.add_argument("--title",default="")
    lookup = actions.add_parser("passages")
    lookup.add_argument("listing")
    lookup.add_argument("--query")
    lookup.add_argument("--cutoff")
    lookup.add_argument("--at-commit", type=int, help="System-state replay through this local commit")
    comparison = actions.add_parser("compare")
    comparison.add_argument("listing")
    comparison.add_argument("current", help="Exact passage ID or unique fiscal-period label")
    comparison.add_argument("baseline", help="Exact passage ID or unique fiscal-period label")
    ask = actions.add_parser("ask")
    ask.add_argument("listing")
    ask.add_argument("question")
    ask.add_argument("--engine", choices=("local", "device", "responses"))
    ask.add_argument("--cutoff", help="Historical public-information cutoff with UTC offset")
    ask.add_argument("--queue", action="store_true", help="Save for later execution")
    server = actions.add_parser("serve", aliases=["run"])
    server.add_argument("--port", type=int, default=8765, choices=range(1024, 65536), metavar="PORT")
    server.add_argument("--open", action="store_true")
    return app


def operate(db, args):
    name = args.action
    if name == "demo":
        return demo(db)
    if name=="export-case":
        data=json.dumps(memory.export_case(db,args.case_id),ensure_ascii=False,separators=(",",":"))
        with args.file.open("x",encoding="utf-8") as output:
            output.write(data)
        return 0
    if name=="import-research":
        if not args.file.is_file() or args.file.stat().st_size>memory.LIMIT:
            raise ValueError("Select a bounded JSON research file")
        print(memory.import_record(db,select(db,args.listing)["id"],args.file.read_text(encoding="utf-8-sig"),args.kind,args.title))
        return 0
    if name == "import-list":
        result = universe.import_file(db, args.file, complete=args.complete, source_id=args.source)
        display(result)
        return int(result["state"] == "rejected")
    if name == "accept":
        candidate = universe.accept_candidate(db, args.snapshot_id)
        display(candidate)
        return int(candidate["state"] == "rejected")
    elif name == "verify-sources":
        result = evidence.verify_documents(db, after=args.after)
        display(result)
        return int(bool(result["problems"]))
    elif name == "doctor":
        channel=delivery.dashboard(db)
        display(
            {
                "profile": "fixture" if is_fixture(db) else "local_trial",
                "python": sys.version.split()[0],
                "sqlite": sqlite3.sqlite_version,
                "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
                "schema": db.execute("SELECT max(version) FROM migrations").fetchone()[0],
                "integrity": db.execute("PRAGMA quick_check").fetchone()[0],
                "runtime": {"local_financial_tools": True, "on_device_model": local_research.model_available(),
                            "hosted_responses": executor.preflight()},
                "providers": providers.capabilities(db),
                "monitoring": "foreground while serve is running",
                  "notification_route":{k:channel[k] for k in ("channel","enabled","available")},
                  "limits":{"autonomous_attempts_per_utc_day":proactive.GLOBAL_DAILY_LIMIT,
                            "active_goals":db.execute("SELECT count(*) FROM goal_plans WHERE ended_at IS NULL").fetchone()[0],
                            "auto_corrections_per_utc_day":memory.DAILY_LIMIT},
            }
        )
    elif name == "universe":
        display(universe.universe(db))
    elif name == "cases":
        display(workspace.cases(db))
    elif name == "case":
        print_case(workspace.case_detail(db, args.case_id))
    elif name == "passages":
        item = select(db, args.listing)
        display(
            evidence.search(
                db,
                item["id"],
                args.cutoff,
                query=args.query,
                commit_seq=args.at_commit,
                fixture=is_fixture(db),
            )
        )
    elif name == "capture":
        result = evidence.capture_public(db, select(db, args.listing), provider=args.provider)
        display(result)
        return int(result["status"] != "ok")
    elif name == "compare":
        item = select(db, args.listing)
        periods = evidence.search(db, item["id"], fixture=is_fixture(db))

        def observation(value):
            matches = [
                p
                for p in periods
                if p["financial"] and (p["id"] == value or p["financial"]["period_label"] == value)
            ]
            if len(matches) != 1:
                raise ValueError("Select a unique observation from passages for this listing")
            return matches[0]

        display(evidence.compare(observation(args.current), observation(args.baseline), "period_trend"))
    elif name in ("fiscal-discover", "fiscal-probe"):
        result = (
            providers.discover_fiscal(db)
            if name == "fiscal-discover"
            else providers.probe_fiscal(db, select(db, args.listing))
        )
        display(result)
        return int(result["status"] != "ok")
    elif name == "review":
        research.review(db, args.brief_id)
    elif name in ("run-job", "ask", "continue"):
        if name == "ask":
            job = research.ask(db, select(db, args.listing)["id"], args.question, cutoff=args.cutoff)
        elif name == "continue":
            job = research.continuation(db, args.case_id)
        else:
            job = args.job_id
        row = db.execute("SELECT case_id FROM jobs WHERE id=?", (job,)).fetchone()
        if not row:
            raise ValueError("Unknown job")
        print("Saved case", row[0], "| Job", job)
        if name == "ask" and args.queue:
            return 0
        engine = args.engine or ("device" if not is_fixture(db) and local_research.model_available() else "local")
        brief = research.run_job(db, job, engine=engine)
        print_case(workspace.case_detail(db, row[0]))
        return int(brief is None)
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    fixture = args.fixture or args.action == "demo"
    folder = args.data_dir or Path(".stockinsight-demo" if fixture else ".stockinsight")
    path = folder / "research.sqlite3"
    try:
        with closing(connect(path, fixture=fixture)) as db:
            if args.action not in ("serve", "run"):
                return operate(db, args)
        from .web import application
        import uvicorn

        code = secrets.token_urlsafe(24)
        os.environ["STOCKINSIGHT_DESK_PORT"] = str(args.port)
        url = f"http://127.0.0.1:{args.port}"
        with closing(socket.socket()) as listener:
            listener.bind(("127.0.0.1", args.port))
            listener.listen()
            def request_stop():
                server.should_exit = True

            config = uvicorn.Config(
                application(path, args.port, code, request_stop=request_stop),
                host="127.0.0.1",
                port=args.port,
                proxy_headers=False,
                access_log=False,
                server_header=False,
            )
            server = uvicorn.Server(config)
            print(
                f"Open {url}\nUsername: research\nTerminal password: {code}\nCtrl+C stops the private desk.",
                flush=True,
            )
            if args.open:
                webbrowser.open(url + "/today")
            server.run(sockets=[listener])
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
