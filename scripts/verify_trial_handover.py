"""Stop a disposable launcher across a real deadline, then restore the same records under a new owner."""

import argparse
import json
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from verify_windows_trial import REPO, launcher

sys.path.insert(0, str(REPO))
from stockinsight import backup, db, delivery, goals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-verification", required=True, type=Path)
    parser.add_argument("--output-parent", required=True, type=Path)
    args = parser.parse_args()
    source = args.source_verification
    previous = json.loads((source / "verification.json").read_text())
    root = Path(tempfile.mkdtemp(prefix="deadline-handover-", dir=args.output_parent)).resolve()
    trial = root / "old"
    trial.mkdir()
    workspace = backup.create(source / "personal/research.sqlite3", trial / "personal")
    path = workspace / "research.sqlite3"
    with closing(db.connect(path)) as conn:
        delivery.action(conn, "delivery-configure", {"enabled": "0"})
        for plan in goals.active(conn):
            goals.action(conn, "goal-stop", {"plan": plan["id"]})
    with launcher(trial), closing(db.connect(path)) as conn:
        target = (datetime.now(UTC) + timedelta(seconds=80)).replace(second=0, microsecond=0)
        if (target - datetime.now(UTC)).total_seconds() < 30:
            target += timedelta(minutes=1)
        # Preserve the report deadline even when no source check ran during the outage.
        plan = goals.save(
            conn,
            {
                "objective": "Start work on my watchlist each day",
                "key": "real-handover",
                "clock": target.strftime("%H:%M"),
                "timezone": "UTC",
                "cadence": "daily",
                "intent": "start_at",
            },
        )
        notice = delivery.enqueue(
            conn,
            key="handover-check",
            title="Handover rehearsal",
            message="Pending delivery rehearsal.",
            report_path="/today",
        )
    stopped = db.now()
    assert stopped < db.instant(target.isoformat())
    archive = backup.create(path, root / "backup")
    dest = root / "new"
    dest.mkdir()
    restored = backup.create(archive / "research.sqlite3", dest / "personal") / "research.sqlite3"
    print(
        "Old launcher stopped; new owner will start after",
        target.isoformat(),
        flush=True,
    )
    while datetime.now(UTC) < target + timedelta(seconds=62):
        time.sleep(0.5)
    resumed = db.now()
    with launcher(dest), closing(db.connect(restored)) as conn:
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            row = conn.execute(
                """SELECT d.id,g.due_at,g.finished_at,d.body FROM goal_deadlines g JOIN goal_dispatch d ON d.id=g.report_id
                WHERE g.plan_id=? AND g.state='missed' AND d.state='complete' AND d.kind='recovery'""",
                (plan,),
            ).fetchone()
            if row:
                break
            time.sleep(0.5)
        assert row and row["finished_at"] >= resumed
        assert (
            conn.execute(
                "SELECT count(*) FROM goal_dispatch WHERE plan_id=? AND kind='recovery'",
                (plan,),
            ).fetchone()[0]
            == 1
        )
        assert conn.execute(
            "SELECT reviewed_at FROM goal_dispatch WHERE id=?", (previous["report_id"],)
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM delivery_notices WHERE notice_key=?",
                ("goal:" + previous["report_id"],),
            ).fetchone()[0]
            == 1
        )
        n = conn.execute("SELECT id,state FROM delivery_notices WHERE notice_key='handover-check'").fetchone()
        assert n["id"] == notice and n["state"] == "pending"
        assert (
            conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            and not conn.execute("PRAGMA foreign_key_check").fetchall()
        )
        proof = {
            "old_stopped_at": stopped,
            "expected_start": row["due_at"],
            "new_started_at": resumed,
            "recovery_id": row["id"],
            "completed_at": row["finished_at"],
            "recovery": json.loads(row["body"]),
            "unread_delivery_preserved": n["id"],
            "preserved_reviewed_report": previous["report_id"],
            "off_host": False,
        }
    (root / "verification.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(root, proof["recovery_id"], proof["completed_at"])


if __name__ == "__main__":
    main()
