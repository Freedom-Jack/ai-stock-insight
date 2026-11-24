"""Rehearse loopback liveness, interruption, restart and backup in an empty private workspace."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import backup, server_profile


def rehearse():
    with tempfile.TemporaryDirectory(prefix="stockinsight-server-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        env = {
            k: os.environ[k]
            for k in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG")
            if k in os.environ
        }
        env.update(
            STOCKINSIGHT_PROFILE=server_profile.PROFILE,
            STOCKINSIGHT_DESK_PORT=str(port),
            STOCKINSIGHT_NOTIFICATION_CHANNEL="unconfigured",
            PYTHONDONTWRITEBYTECODE="1",
        )

        def start():
            return subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "stockinsight",
                    "--data-dir",
                    str(workspace),
                    "serve",
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        def await_ready(proc):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline and proc.poll() is None:
                current = server_profile.health(workspace, port=port)
                if all(current.values()):
                    return current
                time.sleep(0.25)
            raise RuntimeError(
                "The isolated desk did not pass its liveness and worker checks."
            )

        first = start()
        try:
            initial = await_ready(first)
        finally:
            first.kill()
            first.wait(timeout=10)
        interrupted = server_profile.health(workspace, port=port)
        if interrupted["loopback_authentication_challenge"]:
            raise RuntimeError("Unexpected listener on the disposable rehearsal port.")
        # Require a new pulse from the restarted worker.
        (workspace / "scheduler-pulse").unlink()
        second = start()
        try:
            restarted = await_ready(second)
            stored = backup.create(
                workspace / "research.sqlite3", root / "local-backup"
            )
            restored = backup.create(stored / "research.sqlite3", root / "restored")
        finally:
            second.terminate()
            second.wait(timeout=10)
        return {
            "isolated_local_workspace": True,
            "initial": initial,
            "interrupted": interrupted,
            "restarted": restarted,
            "restored_database_integrity": server_profile._integrity(restored),
            "systemd_on_target": False,
            "external_observer_contacted": False,
            "off_host_restore": False,
            "commissioned": False,
        }


if __name__ == "__main__":
    print(json.dumps(rehearse(), indent=2))
