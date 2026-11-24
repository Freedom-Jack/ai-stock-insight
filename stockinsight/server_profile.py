"""Readiness checks and opt-in operational hooks for one private Linux server."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from . import backup, delivery
from .db import now

PROFILE = "server_single_node"


def pulse(db):
    if os.environ.get("STOCKINSIGHT_PROFILE") != PROFILE:
        return
    main = db.execute("PRAGMA database_list").fetchone()["file"]
    if main:
        (Path(main).parent / "scheduler-pulse").touch(mode=0o600)


def _integrity(path):
    with closing(
        sqlite3.connect(
            (path / "research.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
        )
    ) as db:
        return db.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok" and bool(
            db.execute("SELECT 1 FROM installation WHERE mode='local_trial'").fetchone()
        )


def _port():
    value = os.environ.get("STOCKINSIGHT_DESK_PORT", "8765")
    if not value.isascii() or not value.isdecimal() or not 1024 <= int(value) <= 65535:
        raise ValueError("Set a valid private desk port.")
    return int(value)


def _listener(port=None):
    port = port or _port()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        conn.request("GET", "/status")
        res = conn.getresponse()
        return (
            res.status == 401
            and res.getheader("WWW-Authenticate")
            == f'Basic realm="Stock Insight {port}"'
        )
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _observer_url():
    endpoint = urlsplit(os.environ.get("STOCKINSIGHT_HEARTBEAT_URL", ""))
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or not endpoint.path.strip("/")
        or endpoint.fragment
    ):
        raise ValueError("Configure an independent private HTTPS heartbeat URL.")
    return endpoint


def health(workspace, *, port=None):
    try:
        valid = _integrity(workspace)
    except (sqlite3.Error, OSError):
        valid = False
    try:
        age = time.time() - (workspace / "scheduler-pulse").stat().st_mtime
    except OSError:
        age = None
    return {
        "workspace_integrity": valid,
        "loopback_authentication_challenge": _listener(port),
        "scheduler_recent": age is not None and 0 <= age <= 150,
    }


def heartbeat(workspace):
    verdict = health(workspace)
    if not all(verdict.values()):
        raise ValueError(
            "Heartbeat withheld: local desk, database or scheduler check failed."
        )
    endpoint = _observer_url()
    connection = http.client.HTTPSConnection(
        endpoint.hostname, endpoint.port or 443, timeout=5
    )
    try:
        # No local event, ticker, credential, report, or identifying payload.
        target = endpoint.path + ("?" + endpoint.query if endpoint.query else "")
        connection.request("POST", target, body=b"")
        if connection.getresponse().status != 200:
            raise ValueError("Independent observer did not acknowledge the heartbeat.")
    except (OSError, http.client.HTTPException):
        raise ValueError("Independent observer was unreachable.") from None
    finally:
        connection.close()
    return verdict


def preflight(workspace):
    linux = sys.platform.startswith("linux")
    restrictions = False
    if linux and workspace.is_dir():
        mode = workspace.stat()
        restrictions = mode.st_uid == os.geteuid() and mode.st_mode & 0o077 == 0
    try:
        observer = bool(_observer_url())
    except ValueError:
        observer = False
    return {
        "profile": PROFILE,
        "linux": linux,
        "nonroot": linux and os.geteuid() != 0,
        "private_service_directory": restrictions,
        "no_hosted_model_billing": not any(
            os.environ.get(key)
            for key in (
                "STOCKINSIGHT_OPENAI_API_KEY",
                "OPENAI_API_KEY",
                "STOCKINSIGHT_API_BILLING",
            )
        ),
        "executor": "service-recorded public research functions",
        "notification_configured": delivery._channel() == "ntfy"
        and delivery._available("ntfy"),
        "observer_configured": observer,
        "commissioned": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path("/var/lib/stockinsight/workspace")
    )
    cmds = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "guard", "heartbeat", "health"):
        cmds.add_parser(command)
    snapshot = cmds.add_parser("backup")
    snapshot.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command in ("preflight", "guard"):
            if args.command == "guard":
                args.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
            report = preflight(args.workspace)
            if args.command == "guard" and (
                os.environ.get("STOCKINSIGHT_PROFILE") != PROFILE
                or not all(
                    report[k]
                    for k in (
                        "linux",
                        "nonroot",
                        "private_service_directory",
                        "no_hosted_model_billing",
                    )
                )
            ):
                raise ValueError(
                    "Server service requires its private dedicated Linux identity and no hosted model credentials."
                )
        elif args.command == "backup":
            target = args.destination / ("snapshot-" + now().replace(":", "-"))
            backup.create(args.workspace / "research.sqlite3", target)
            report = {"local_snapshot": str(target), "off_host_restore_verified": False}
        else:
            report = (
                heartbeat(args.workspace)
                if args.command == "heartbeat"
                else health(args.workspace)
            )
        print(json.dumps(report, indent=2))
        return int(args.command == "health" and not all(report.values()))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
