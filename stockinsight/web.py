"""Private foreground browser UI. Workers reach the application through Bridge only."""

import hmac
import json
import secrets
from base64 import b64encode
from contextlib import asynccontextmanager, closing
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from . import assistant_mcp, agenda, delivery, evidence, exposure, goals, journal, local_research, memory, methods, monitor, ownership, providers, research, sources_calendar, universe, workspace
from .db import connect, is_fixture, uid

TEMPLATES = Jinja2Templates(directory=Path(__file__).with_name("templates"))
MAX_FORM = 3 * universe.MAX_BYTES + 4096


def same(a, b):
    return isinstance(a, str) and hmac.compare_digest(a.encode(), b.encode())


def application(path, port, login_code, *, request_stop=None):
    @asynccontextmanager
    async def foreground(app):
        stop = Event()
        worker = Thread(target=monitor.run_foreground, args=(path, stop), daemon=True)
        with ownership.scheduler(path):
            worker.start()
            try:
                yield
            finally:
                stop.set()
                await run_in_threadpool(worker.join)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=foreground)
    host = f"127.0.0.1:{port}"
    origin = f"http://{host}"
    # HTTP authentication is scoped to an origin (including its port).
    # Chromium performs the challenge/response in its native credential dialog.
    authorization = "Basic " + b64encode(f"research:{login_code}".encode()).decode("ascii")
    csrf = secrets.token_urlsafe(32)

    def render(req, view, **values):
        return TEMPLATES.TemplateResponse(
            request=req,
            name="desk.html",
            context={"view": view, "csrf": csrf, **values},
        )

    @app.middleware("http")
    async def private(req, call_next):
        if req.headers.getlist("host") != [host]:
            return PlainTextResponse("Unrecognized host", status_code=403)
        if req.url.path == "/mcp":
            return await assistant_mcp.endpoint(req, path)
        if req.method not in ("GET", "POST"):
            return PlainTextResponse("Unsupported method", status_code=405)
        if req.method == "POST" and req.headers.getlist("origin") != [origin]:
            return PlainTextResponse("Unrecognized browser origin", status_code=403)
        credentials = req.headers.getlist("authorization")
        if len(credentials) != 1 or not same(credentials[0], authorization):
            response = PlainTextResponse(
                "Enter username research and the password from this desk's terminal.",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="Stock Insight {port}"'},
            )
        else:
            response = await call_next(req)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "same-origin",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    async def fields(req):
        if req.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise ValueError("Expected a browser form")
        raw = bytearray()
        async for chunk in req.stream():
            if len(raw) + len(chunk) > MAX_FORM:
                raise ValueError("Form exceeds the import limit")
            raw.extend(chunk)
        pairs = parse_qsl(
            raw.decode(), keep_blank_values=True, max_num_fields=12, errors="strict", strict_parsing=True
        )
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Repeated form field")
        if not same(data.pop("csrf", None), csrf):
            raise PermissionError
        return data

    @app.exception_handler(ValueError)
    async def invalid(req, exc):
        # Parsing errors may contain raw form fields. Render only a safe diagnostic.
        return PlainTextResponse("Invalid request. Check the instrument, question and form fields.", 400)

    @app.exception_handler(PermissionError)
    async def forbidden(req, exc):
        return PlainTextResponse("Browser session verification failed", 403)

    def page(req, db, view, **kw):
        fixture = is_fixture(db)
        return render(req, view, fixture=fixture, device_ready=not fixture and local_research.model_available(),
                      request_key=uid("request"), **kw)

    @app.get("/")
    def home(req: Request):
        with closing(connect(path)) as db:
            return page(req, db, "research", cases=workspace.cases(db), universe=universe.universe(db))

    @app.get("/today")
    def today(req: Request):
        with closing(connect(path)) as db:
            unread = db.execute(
                """SELECT b.case_id,b.revision,c.question,i.ticker FROM inbox n JOIN briefs b ON b.id=n.brief_id
                   JOIN cases c ON c.id=b.case_id JOIN instruments i ON i.id=c.instrument_id
                   WHERE n.reviewed_at IS NULL ORDER BY b.commit_seq DESC LIMIT 25"""
            ).fetchall()
            return page(req, db, "today", unread=unread, goals=goals.dashboard(db), journal=journal.dashboard(db),
                        monitor=monitor.dashboard(db), universe=universe.universe(db))

    @app.get("/monitor")
    def monitoring(req: Request):
        with closing(connect(path)) as db:
            return page(req, db, "monitor", monitor=monitor.dashboard(db), universe=universe.universe(db))

    @app.get("/events/{version}")
    def event_observation(req:Request,version:str):
        with closing(connect(path)) as db:
            row=db.execute("SELECT * FROM event_versions WHERE id=?",(version,)).fetchone()
            if not row:
                raise ValueError("Unknown event edition")
            return page(req,db,"event",event=dict(row),source=evidence.get(db,row["instrument_id"],row["source_ref"],fixture=is_fixture(db)))

    @app.get("/goals")
    def standing(req: Request):
        with closing(connect(path)) as db:
            return page(req, db, "goals", goals=goals.dashboard(db), universe=universe.universe(db))

    @app.get("/agenda")
    def agenda_view(req:Request):
        with closing(connect(path)) as db:
            return page(req,db,"agenda",agenda=agenda.dashboard(db))

    @app.get("/exposures")
    def exposure_view(req:Request):
        with closing(connect(path)) as db:
            return page(req,db,"exposure",exposure=exposure.dashboard(db))

    @app.get("/goals/reports/{report_id}")
    def alert_report(req: Request, report_id: str):
        with closing(connect(path)) as db:
            result = goals.report(db,report_id)
            method = methods.export(db,result["method_report"]) if result["method_report"] else None
            link = db.execute("SELECT case_id FROM assistant_jobs WHERE dispatch_id=? LIMIT 1",(report_id,)).fetchone()
            history = [json.loads(r[0]) for r in db.execute("SELECT result FROM assistant_jobs WHERE case_id=? AND state='accepted' ORDER BY rowid",(link[0],))] if link else []
            return page(req,db,"goal_report",report=result,method=method,assistant_history=history)

    @app.get("/methods")
    def workbench(req: Request, instrument_id: str | None = None):
        with closing(connect(path)) as db:
            return page(req,db,"methods",methods=methods.dashboard(db,instrument_id),universe=universe.universe(db))

    @app.get("/methods/reports/{report_id}.json")
    def method_export(report_id: str):
        with closing(connect(path)) as db:
            return JSONResponse(methods.export(db,report_id),headers={"Content-Disposition":'attachment; filename="research-method.json"'})

    @app.get("/journal")
    @app.get("/upcoming")
    def notebook(req: Request):
        with closing(connect(path)) as db:
            return page(req, db, req.url.path[1:], journal=journal.dashboard(db))

    @app.get("/universe")
    def lists(req: Request):
        with closing(connect(path)) as db:
            return page(req, db, "universe", universe=universe.universe(db))

    @app.get("/companies/{instrument_id}")
    def company(req: Request, instrument_id: str):
        with closing(connect(path)) as db:
            item = universe.instrument(db, instrument_id, active=False)
            return page(
                req,
                db,
                "company",
                instrument=item,
                imported=memory.recall(db,instrument_id)["imports"],
                public_routes={k:v for k,v in sources_calendar.ROUTE_LABELS.items() if sources_calendar.eligible(item,k)},
                passages=evidence.search(db, instrument_id, fixture=is_fixture(db)),
                cases=[c for c in workspace.cases(db) if c["instrument_id"] == instrument_id],
            )

    @app.get("/cases/{case_id}")
    def detail(req: Request, case_id: str):
        with closing(connect(path)) as db:
            case=workspace.case_detail(db,case_id)
            return page(req, db, "case", case=case, memory=memory.case_context(db,case),
                        case_notes=journal.case_notes(db, case_id))

    @app.get("/cases/{case_id}/export")
    def export_case(case_id:str):
        with closing(connect(path)) as db:
            return JSONResponse(memory.export_case(db,case_id),headers={"Content-Disposition":'attachment; filename="stock-insight-case.json"'})

    @app.get("/memory/{record_id}")
    def selected_history(req:Request,record_id:str):
        with closing(connect(path)) as db:
            return page(req,db,"memory",record=memory.get_import(db,record_id))

    @app.get("/sources/{instrument_id}/{document_id}")
    def source(instrument_id: str, document_id: str):
        with closing(connect(path)) as db:
            payload = evidence.document_bytes(db, instrument_id, document_id)
        return Response(
            payload,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="source.json"'},
        )

    @app.get("/status")
    def status(req: Request):
        with closing(connect(path)) as db:
            return page(
                req,
                db,
                "status",
                delivery=delivery.dashboard(db),
                assistant_state=assistant_mcp.status(db),
                can_stop=request_stop is not None,
                providers=providers.capabilities(db),
                states=db.execute("SELECT state,count(*) AS n FROM jobs GROUP BY state").fetchall(),
            )

    def mutate(action, data):
        with closing(connect(path)) as db:
            if action.startswith("agenda-"):
                return agenda.action(db,action,data)
            if action.startswith("exposure-"):
                return exposure.action(db,action,data)
            if action.startswith("memory-"):
                return memory.action(db,action,data)
            if action.startswith("goal-"):
                return goals.action(db,action,data)
            if action.startswith("delivery-") and delivery._channel() == "ntfy":
                return delivery.action(db,action,data)
            if action.startswith("method-"):
                return methods.action(db,action,data)
            if action.startswith("monitor-"):
                return monitor.action(db, action, data)
            if action.startswith("journal-"):
                return journal.action(db, action, data)
            if action == "import":
                universe.import_snapshot(
                    db, data.get("entries", "").encode(), complete=data.get("complete") == "yes"
                )
                return "/universe"
            if action == "accept":
                universe.accept_candidate(db, data.get("snapshot", ""))
                return "/universe"
            if action == "review":
                research.review(db, data.get("brief", ""))
                return (
                    "/cases/"
                    + db.execute("SELECT case_id FROM briefs WHERE id=?", (data["brief"],)).fetchone()[0]
                )
            if action == "theme":
                universe.create_theme(db, data.get("name", ""), data.get("question", ""))
                return "/universe"
            if action == "link-theme":
                universe.link_theme(
                    db, data["theme"], instrument_id=data.get("instrument_id"), reason=data.get("reason", "")
                )
                return "/universe"
            if action == "capture":
                if is_fixture(db):
                    raise ValueError("Public capture requires a local trial workspace")
                item = universe.instrument(db, data.get("instrument_id", ""))
                result = evidence.capture_public(db, item, provider=data.get("provider", "issuer"))
                return (
                    "/companies/"
                    + item["id"]
                    + "?capture="
                    + ("ok" if result["status"] == "ok" else "unavailable")
                )
            engine = data.get("engine") or ("device" if not is_fixture(db) and local_research.model_available() else "local")
            if engine not in ("local", "device"):
                raise ValueError("Choose a local research method")
            if action == "ask":
                key = data.get("key", "")
                if not key.startswith("request_") or len(key) != 32:
                    raise ValueError("Invalid question form")
                job_id = research.ask(
                    db,
                    data.get("instrument_id", ""),
                    data.get("question", ""),
                    cutoff=data.get("cutoff"),
                    request_key=key,
                )
            elif action == "continue":
                key = data.get("key", "")
                if not key.startswith("request_") or len(key) != 32:
                    raise ValueError("Invalid continuation form")
                job_id = research.continuation(
                    db,
                    data.get("case", ""),
                    request_key=key,
                    expected_revision=int(data.get("base_revision", "")),
                )
            elif action == "run":
                job_id = data.get("job", "")
            else:
                raise ValueError("Unknown operation")
            row = db.execute("SELECT case_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job")
            try:
                research.run_job(db, job_id, engine=engine)
            except ValueError:
                # The durable case shows the execution outcome, including blocked and queued work.
                pass
            return "/cases/" + row["case_id"]

    @app.post("/actions/{action}")
    async def action(req: Request, action: str):
        data = await fields(req)
        if action == "stop" and request_stop and data.get("confirm") == "yes":
            request_stop()
            return PlainTextResponse("Stock Insight is stopping. Run the Windows launcher to reopen your workspace.")
        destination = await run_in_threadpool(mutate, action, data)
        return RedirectResponse(destination, 303)

    return app
