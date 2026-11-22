"""Explicit Windows delivery check. Generates one private generic notification."""

import argparse
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from . import delivery, windows_notice
from .db import connect, uid


def observe(db, notice_id):
    row = db.execute(
        """SELECT n.id,n.state,n.accepted_at,n.shown_at,n.open_requested_at,a.observation
                        FROM delivery_notices n LEFT JOIN delivery_attempts a ON n.active_attempt=a.id
                        WHERE n.id=?""",
        (notice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Unknown notice.")
    recorded = json.loads(row["observation"] or "{}")
    checked = (
        windows_notice.observe(recorded["hwnd"], recorded["pid"])
        if recorded.get("channel") == "windows_user_session"
        else None
    )
    return {
        k: row[k]
        for k in ("id", "state", "accepted_at", "shown_at", "open_requested_at")
    } | {
        "independent_window_probe": checked,
        "human_seen": "unknown",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Read an existing workspace if verifying its pending/recent notice.",
    )
    parser.add_argument(
        "--notice-id", help="ID of the notice in the existing workspace. Sends nothing."
    )
    args = parser.parse_args()
    if bool(args.workspace) != bool(args.notice_id):
        parser.error("Supply --workspace and --notice-id together.")
    if args.workspace:
        path = args.workspace.resolve() / "research.sqlite3"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            proof = observe(db, args.notice_id)
    else:
        # The child holds a DB connection while the notice can be opened. Keep
        # this explicit check's directory for the notice lifetime on Windows.
        with (
            tempfile.TemporaryDirectory(prefix="stockinsight-notice-") as temp,
            closing(connect(Path(temp) / "research.sqlite3")) as db,
        ):
            if delivery._channel() != "windows":
                parser.error("The test requires the windows route.")
            ident = delivery.enqueue(
                db,
                key=uid("operator_test"),
                title="Operator test",
                message="Delivery check.",
                report_path="/status",
            )
            delivery.tick(db)
            proof = observe(db, ident)
            print(json.dumps(proof, indent=2), flush=True)
            if proof["state"] == "shown":
                time.sleep(37)
            return int(not proof["independent_window_probe"])
    print(json.dumps(proof, indent=2))
    return int(not proof["independent_window_probe"])


if __name__ == "__main__":
    raise SystemExit(main())
