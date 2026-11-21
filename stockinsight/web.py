"""Private foreground browser UI. Workers reach the application through Bridge only."""

import hmac
import secrets
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from . import evidence, executor, providers, research, universe, workspace
from .db import connect, is_fixture, uid

TEMPLATES = Jinja2Templates(directory=Path(__file__).with_name("templates"))
MAX_FORM = 3 * universe.MAX_BYTES + 4096


def same(a, b):
    return isinstance(a, str) and hmac.compare_digest(a.encode(), b.encode())


def application(path, port, login_code):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    host = f"127.0.0.1:{port}"
    origin = f"http://{host}"
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    def render(req, view, **values):
        return TEMPLATES.TemplateResponse(
            request=req,
            name="desk.html",
            context={"view": view, "csrf": csrf if view != "login" else "", **values},
        )

    @app.middleware("http")
    async def private(req, call_next):
        if req.headers.getlist("host") != [host]:
            return PlainTextResponse("Unrecognized host", status_code=403)
        if req.method not in ("GET", "POST"):
            return PlainTextResponse("Unsupported method", status_code=405)
        if req.method == "POST" and req.headers.getlist("origin") != [origin]:
            return PlainTextResponse("Unrecognized browser origin", status_code=403)
        logged_in = same(req.cookies.get("insight_session"), session)
        if not logged_in and req.url.path != "/login":
            response = (
                RedirectResponse("/login", 303)
                if req.method == "GET"
                else PlainTextResponse("Sign in first", 401)
            )
        else:
            response = await call_next(req)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    async def fields(req, *, login=False):
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
        if not login and not same(data.pop("csrf", None), csrf):
            raise PermissionError
        return data

    @app.exception_handler(ValueError)
    async def invalid(req, exc):
        # Parsing errors may contain raw form fields. Render only a safe diagnostic.
        return PlainTextResponse("Invalid request. Check the instrument, question and form fields.", 400)

    @app.exception_handler(PermissionError)
    async def forbidden(req, exc):
        return PlainTextResponse("Browser session verification failed", 403)

    @app.get("/login")
    def login(req: Request):
        return render(req, "login")

    @app.post("/login")
    async def authenticate(req: Request):
        data = await fields(req, login=True)
        if not same(data.get("code"), login_code):
            return PlainTextResponse("Incorrect sign-in code", 403)
        resp = RedirectResponse("/", 303)
        resp.set_cookie("insight_session", session, httponly=True, samesite="strict", path="/")
        return resp

    def page(req, db, view, **kw):
        return render(req, view, fixture=is_fixture(db), request_key=uid("request"), **kw)

    @app.get("/")
    def home(req: Request):
        with closing(connect(path)) as db:
            return page(req, db, "research", cases=workspace.cases(db), universe=universe.universe(db))

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
                passages=evidence.search(db, instrument_id, fixture=is_fixture(db)),
                cases=[c for c in workspace.cases(db) if c["instrument_id"] == instrument_id],
            )

    @app.get("/cases/{case_id}")
    def detail(req: Request, case_id: str):
        with closing(connect(path)) as db:
            return page(req, db, "case", case=workspace.case_detail(db, case_id))

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
                runtime=executor.preflight(),
                providers=providers.capabilities(db),
                states=db.execute("SELECT state,count(*) AS n FROM jobs GROUP BY state").fetchall(),
            )

    def mutate(action, data):
        with closing(connect(path)) as db:
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
                job_id = research.continuation(db, data.get("case", ""))
            elif action == "run":
                job_id = data.get("job", "")
            else:
                raise ValueError("Unknown operation")
            row = db.execute("SELECT case_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job")
            try:
                research.run_job(db, job_id)
            except ValueError:
                # The durable case shows the execution outcome, including blocked and queued work.
                pass
            return "/cases/" + row["case_id"]

    @app.post("/actions/{action}")
    async def action(req: Request, action: str):
        data = await fields(req)
        destination = await run_in_threadpool(mutate, action, data)
        return RedirectResponse(destination, 303)

    return app
