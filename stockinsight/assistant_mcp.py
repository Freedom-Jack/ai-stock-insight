"""Private Streamable HTTP MCP endpoint for a single-user Stock Insight desk."""

import argparse
import hmac
import json
import os
import secrets
import sqlite3
import shutil
import re
import http.client
import subprocess
from contextlib import closing
from pathlib import Path

from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import assistant, assistant_events, backup, evidence, goals, ownership, sources_calendar, universe
from .db import connect, is_fixture, now


def status(db):
    config = assistant.profile(db)
    states = {r[0]: r[1] for r in db.execute("SELECT state,count(*) FROM assistant_jobs GROUP BY state")}
    events = {r[0]: r[1] for r in db.execute("SELECT state,count(*) FROM assistant_events GROUP BY state")}
    active = db.execute("SELECT count(*) FROM assistant_subscriptions WHERE expires>?", (now(),)).fetchone()[
        0
    ]
    storage = db.execute("PRAGMA database_list").fetchone()[2]
    prepared = bool(storage and Path(storage).with_name("assistant-key.dpapi").is_file())
    return {
        "enabled": bool(config["enabled"]),
        "prepared": prepared,
        "label": config["label"],
        "subscriptions": active,
        "jobs": states,
        "platform_events": events,
        "presentation": "requires independent observation",
    }


def watchlist(db):
    return [
        {k: i[k] for k in ("id", "ticker", "listing_exchange", "currency", "resolution_status")}
        for i in goals.listings(db, "watchlist")
    ]


def health(db):
    result = status(db)
    result["sources"] = [
        dict(r)
        for r in db.execute(
            "SELECT provider,status,finished_at FROM source_checks ORDER BY rowid DESC LIMIT 12"
        )
    ]
    result["interrupted_attempts"] = db.execute("SELECT count(*) FROM assistant_interruptions").fetchone()[0]
    result["pending"] = []
    for row in db.execute(
        "SELECT id,case_id FROM assistant_jobs WHERE state IN ('pending','running') ORDER BY rowid LIMIT 40"
    ):
        try:
            assistant._item(db, row["id"])
        except ValueError:
            continue
        result["pending"].append({"job_id": row["id"], "case_id": row["case_id"]})
    return result


def capture(db, job_id, worker_key, provider):
    job = assistant._authorize(db, job_id, worker_key)
    if is_fixture(db) or assistant.profile(db)["replay_clock"]:
        raise ValueError("Historical research can only read its frozen packet.")
    listing = universe.instrument(db, job["instrument_id"])
    if provider not in assistant.PUBLIC or not sources_calendar.eligible(listing, provider):
        raise ValueError("Source unavailable for this instrument.")
    receipt = evidence.capture_public(db, listing, provider)
    return {k: receipt.get(k) for k in ("status", "receipt_id", "document_id", "cached", "checked_at")} | {
        "next": "Newly acquired evidence is available to a subsequent same-case investigation."
    }


TOOLS = {
    "watchlist": (watchlist, (), "Read active instrument identities."),
    "monitor_health": (health, (), "Read coverage, delivery and pending research job IDs."),
    "read_case": (assistant.case, ("case_id",), "Read accepted revisions, citations, gaps and open work."),
    "request_followup": (
        assistant.follow_up,
        ("case_id", "question", "request_key"),
        "Queue a deeper question on this case. Reuse the key on retry.",
    ),
    "claim_research": (
        assistant.claim,
        ("job_id", "worker_key"),
        "Begin or resume one research job using a random per-job key of at least 16 characters.",
    ),
    "list_evidence": (
        assistant.sources,
        ("job_id", "worker_key"),
        "Find passages at the assigned information cutoff.",
    ),
    "read_evidence": (
        assistant.read,
        ("job_id", "worker_key", "passage_id"),
        "Read a permitted passage with its source, time and hash.",
    ),
    "compare_financials": (
        assistant.compare,
        ("job_id", "worker_key", "current", "baseline"),
        "Calculate a like-for-like change from two exact financial passages.",
    ),
    "capture_public": (
        capture,
        ("job_id", "worker_key", "provider"),
        "Acquire a named eligible public source for later research on a live case.",
    ),
    "accept_research": (
        assistant.accept,
        ("job_id", "worker_key", "passage_ids", "calculation_ids", "hypothesis", "alternative", "next_check"),
        "Submit read citations and calculation receipts, a conditional mechanism and horizon, a competing interpretation, and the next check. Source facts come from the returned evidence.",
    ),
}


def schema(keys):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(keys),
        "properties": {
            k: (
                {"type": "array", "items": {"type": "string"}, "maxItems": 8}
                if k in ("passage_ids", "calculation_ids")
                else {"type": "string"}
            )
            for k in keys
        },
    }


def rpc(db, method, params):
    if not assistant.profile(db)["enabled"] and method not in (
        "initialize",
        "ping",
        "tools/list",
        "events/list",
    ):
        raise ValueError("Assistant research is awaiting local allowance verification and activation.")
    if method == "initialize":
        supported = ("2025-11-25", "2025-06-18", "2025-03-26")
        version = params.get("protocolVersion")
        return {
            "protocolVersion": version if version in supported else supported[0],
            "capabilities": {"tools": {}, "events": {}},
            "serverInfo": {"name": "Stock Insight", "version": "1.0"},
            "instructions": "On research.requested, claim the job, read the case and frozen evidence, use applicable analysis tools and submit a result. Present the accepted event, relevance, uncertainty and case ID. For a follow-up queue a question once and report its job ID.",
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {
            "tools": [
                {"name": n, "description": d, "inputSchema": schema(keys)}
                for n, (_, keys, d) in TOOLS.items()
            ]
        }
    if method == "events/list":
        return {
            "events": [
                {
                    "name": assistant_events.EVENT,
                    "description": "An adopted goal or explicit follow-up needs one investigation.",
                    "delivery": ["webhook"],
                    "inputSchema": schema(()),
                    "payloadSchema": schema(("case_id", "job_id", "label")),
                }
            ]
        }
    if method in ("events/subscribe", "events/unsubscribe"):
        return assistant_events.subscription(db, params, remove=method == "events/unsubscribe")
    if method != "tools/call":
        raise KeyError("Unknown method")
    tool = TOOLS.get(params.get("name"))
    args = params.get("arguments", {})
    if tool is None or not isinstance(args, dict) or set(args) != set(tool[1]):
        raise ValueError("Unknown tool or arguments.")
    for k, v in args.items():
        if k not in ("passage_ids", "calculation_ids") and (not isinstance(v, str) or len(v) > 1800):
            raise ValueError("Invalid tool argument.")
    try:
        data = tool[0](db, **args)
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": False}
    except (ValueError, TypeError) as exc:
        return {"content": [{"type": "text", "text": str(exc)[:260]}], "isError": True}


def token(path, create=False):
    path = Path(path).with_name("assistant-key.dpapi")
    if create and not path.exists():
        protected = assistant_events._protect(secrets.token_urlsafe(36).encode())
        try:
            with path.open("xb") as stream:
                stream.write(protected)
        except FileExistsError:
            pass
    if not path.is_file():
        return None
    return assistant_events._protect(path.read_bytes(), decrypt=True).decode()


async def endpoint(req, path):
    if req.method != "POST":
        return Response(status_code=405, headers={"Allow": "POST"})
    supplied = req.headers.getlist("x-stockinsight-key")
    expected = token(path)
    if (
        req.headers.getlist("origin")
        or not expected
        or len(supplied) != 1
        or not hmac.compare_digest(expected.encode(), supplied[0].encode())
    ):
        return Response(status_code=403)
    if req.headers.get("content-type", "").split(";")[0] != "application/json":
        return Response(status_code=415)
    raw = bytearray()
    async for chunk in req.stream():
        if len(raw) + len(chunk) > 32768:
            return Response(status_code=413)
        raw.extend(chunk)
    ident = None
    msg = None
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            raise ValueError("Invalid RPC envelope")
        ident = msg.get("id")
        if "id" not in msg:
            if msg["method"] == "notifications/initialized":
                return Response(status_code=202)
            raise ValueError("Request ID required")
        if type(ident) not in (int, str) or not isinstance(msg.get("params", {}), dict):
            raise ValueError("Invalid RPC request")

        def run():
            with closing(connect(path)) as db:
                return rpc(db, msg["method"], msg.get("params", {}))

        result = await run_in_threadpool(run)
        reply = {"result": result}
    except KeyError:
        reply = {"error": {"code": -32601, "message": "Unknown method"}}
    except (ValueError, TypeError, OSError, sqlite3.Error):
        callback = isinstance(msg, dict) and msg.get("method") == "events/subscribe"
        reply = (
            {
                "error": {
                    "code": -32015,
                    "message": "Callback verification failed",
                    "data": {"reason": "challenge_failed"},
                }
            }
            if callback
            else {"error": {"code": -32602, "message": "Invalid request"}}
        )
    return JSONResponse({"jsonrpc": "2.0", "id": ident, **reply}, headers={"Cache-Control": "no-store"})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("prepare", "enable", "status", "tunnel"))
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--client", help="Installed official tunnel-client executable")
    p.add_argument("--port", type=int, default=8765, help="Port of this running loopback desk")
    args = p.parse_args(argv)
    path = backup._local_path(args.directory / "research.sqlite3")
    if not path.is_file():
        p.error("Start the intended desk once before connecting it.")
    if args.action in ("prepare", "enable"):
        with ownership.scheduler(path):
            return setup(path, args.action)
    elif args.action == "status":
        return show_status(path)
    else:
        return tunnel(path, args, p)


def setup(path, action):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as old:
        version = old.execute("SELECT max(version) FROM migrations").fetchone()[0]
    from . import db as database

    if version < len(database.migrations()):
        backup.create(path, path.parent.parent / ("pre-assistant-" + database.uid("backup")))
    with closing(connect(path)) as db:
        token(path, create=True)
        if action == "enable":
            assistant.configure(db)
        elif not goals.active(db) and not is_fixture(db):
            goals.save(
                db,
                {
                    "key": "assistant-personal-monitoring",
                    "objective": "Prepare for material earnings disclosures and monetary policy events affecting my watchlist.",
                },
            )
        print(json.dumps(status(db)))
    return 0


def show_status(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='assistant_profile'").fetchone():
            print("Local investigator; assistant setup pending.")
        else:
            print(json.dumps(status(db)))
    return 0


def tunnel(path, args, p):
    key = token(path)
    tunnel_id = os.environ.get("CONTROL_PLANE_TUNNEL_ID", "")
    if (
        not key
        or not os.environ.get("CONTROL_PLANE_API_KEY")
        or not re.fullmatch(r"tunnel_[A-Za-z0-9_-]{8,128}", tunnel_id)
    ):
        p.error("Prepare this workspace and supply its authorized tunnel ID and runtime credential locally.")
    if not 1024 <= args.port <= 65535:
        p.error("Choose this desk's loopback port.")
    local = (
        Path(__file__).resolve().parents[1] / ".stockinsight/tools/tunnel-client-v0.0.21/tunnel-client.exe"
    )
    client = args.client or (str(local) if local.is_file() else shutil.which("tunnel-client"))
    if not client:
        p.error("Install the official tunnel client or supply --client.")
    # Verify desk identity before opening the outbound transport.
    conn = http.client.HTTPConnection("127.0.0.1", args.port, timeout=3)
    try:
        conn.request(
            "POST",
            "/mcp",
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            {"Content-Type": "application/json", "X-StockInsight-Key": key},
        )
        reply = conn.getresponse()
        if (
            reply.status != 200
            or json.loads(reply.read(12000)).get("result", {}).get("serverInfo", {}).get("name")
            != "Stock Insight"
        ):
            p.error("The selected desk is not serving its authenticated MCP endpoint on that port.")
    finally:
        conn.close()
    env = {
        **{
            n: v
            for n, v in os.environ.items()
            if not n.startswith(
                ("MCP_", "TUNNEL_CLIENT_", "CONTROL_PLANE_", "CLOUDFLARED_", "OPENAI_", "STOCKINSIGHT_")
            )
        },
        "CONTROL_PLANE_API_KEY": os.environ["CONTROL_PLANE_API_KEY"],
        "STOCKINSIGHT_TUNNEL_AUTH": key,
        "MCP_EXTRA_HEADERS": "X-StockInsight-Key: env:STOCKINSIGHT_TUNNEL_AUTH",
        "MCP_DISCOVERY_EXTRA_HEADERS": "X-StockInsight-Key: env:STOCKINSIGHT_TUNNEL_AUTH",
        "MCP_OAUTH_DISCOVERY": "disabled",
    }
    return subprocess.call(
        [
            client,
            "run",
            "--control-plane.tunnel-id",
            tunnel_id,
            "--mcp.server-url",
            f"http://127.0.0.1:{args.port}/mcp",
            "--mcp.oauth-discovery=disabled",
        ],
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
