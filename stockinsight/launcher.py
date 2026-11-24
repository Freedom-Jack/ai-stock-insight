"""Start the Windows personal desk from any working directory."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import webbrowser
from contextlib import closing, contextmanager
from pathlib import Path

from . import __main__ as cli
from . import backup, db


@contextmanager
def background_session(folder, port, code):
    from .assistant_events import _protect
    session = folder / "desk-session.dpapi"
    payload = _protect(json.dumps({"port": port, "pid": os.getpid(), "password": code}).encode())
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as staging:
        staging.write(payload)
    temp = Path(staging.name)
    try:
        temp.replace(session)
        yield
    finally:
        temp.unlink(missing_ok=True)
        if session.exists() and session.read_bytes() == payload:
            session.unlink()


def existing_session(folder, port):
    from .assistant_events import _protect
    session = folder / "desk-session.dpapi"
    if not session.is_file():
        return None
    data = json.loads(_protect(session.read_bytes(), decrypt=True))
    if data["port"] == port:
        netstat = Path(os.environ["SystemRoot"]) / "System32" / "netstat.exe"
        rows = subprocess.check_output([str(netstat), "-ano", "-p", "TCP"], timeout=10,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        endpoint = f"127.0.0.1:{port}".encode()
        owner = str(data["pid"]).encode()
        for line in rows.splitlines():
            fields = line.split()
            if len(fields) == 5 and fields[1:3] == [endpoint, b"0.0.0.0:0"] and fields[-1] == owner:
                return data
    return None


def start_tray_desk(folder, port):
    import win32event
    import win32process

    # Match the sign-in entry: use the real GUI executable and keep this venv.
    pythonw = Path(sys.base_prefix) / "pythonw.exe"
    env = {**os.environ, "__PYVENV_LAUNCHER__": str(Path(sys.executable).with_name("pythonw.exe"))}
    args = [str(pythonw), "-B", "-m", "stockinsight.launcher", "--background",
            "--root", str(folder.parent), "--port", str(port)]
    process, thread, _, _ = win32process.CreateProcess(
        str(pythonw), subprocess.list2cmdline(args), None, None, False, subprocess.DETACHED_PROCESS,
        env, str(Path(__file__).resolve().parents[1]), win32process.STARTUPINFO(),
    )
    thread.Close()
    with closing(process):
        until = time.monotonic() + 60
        while time.monotonic() < until:
            session = existing_session(folder, port)
            if session:
                return session
            if win32event.WaitForSingleObject(process, 250) == win32event.WAIT_OBJECT_0:
                break
    raise OSError("Could not open the personal desk in the Windows taskbar. Check the desktop session and port.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", action="store_true", help="Run with a Windows taskbar icon")
    parser.add_argument(
        "--demo", action="store_true", help="Open the separate synthetic demo"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the address without opening a tab",
    )
    parser.add_argument(
        "--port", type=int, help="Loopback port (personal 8765, demo 8766)"
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Parent directory containing separate personal and demo folders",
    )
    copies = parser.add_mutually_exclusive_group()
    copies.add_argument(
        "--backup",
        type=Path,
        help="Save the chosen workspace to a new destination and exit",
    )
    copies.add_argument(
        "--restore",
        type=Path,
        help="Restore a verified backup into a new workspace and exit",
    )
    args = parser.parse_args(argv)
    if args.background:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")
    root = args.root or (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "StockInsight"
    )
    folder = root.resolve() / ("demo" if args.demo else "personal")
    path = folder / "research.sqlite3"
    try:
        if args.backup:
            print("Verified workspace backup", backup.create(path, args.backup))
            return 0
        if args.restore:
            original = (args.restore / "research.sqlite3").resolve()
            with closing(
                sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)
            ) as conn:
                if db.is_fixture(conn) != args.demo:
                    raise ValueError(
                        "Choose the workspace type matching the saved backup."
                    )
            root.mkdir(parents=True, exist_ok=True)
            print("Restored workspace", backup.create(original, folder))
            return 0
        port = args.port if args.port is not None else 8766 if args.demo else 8765
        entry = existing_session(folder, port)
        if entry is None and os.name == "nt" and not (args.background or args.no_browser or args.demo):
            entry = start_tray_desk(folder, port)
        if entry:
            if not args.background:
                url = f"http://127.0.0.1:{port}/today"
                print(f"Open {url}\nUsername: research\nTerminal password: {entry['password']}", flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
            return 0
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                version = conn.execute(
                    "SELECT max(version) FROM migrations"
                ).fetchone()[0]
            if version < len(db.migrations()):
                destination = (
                    root / "backups" / (folder.name + "-" + db.uid(f"v{version}"))
                )
                destination.parent.mkdir(exist_ok=True)
                print("Pre-upgrade backup", backup.create(path, destination))
        options = ["--data-dir", str(folder)]
        if args.demo:
            options.append("--fixture")
            if not path.exists() and cli.main([*options, "demo"]):
                return 1
        print("Workspace", folder, flush=True)
        return cli.main(
            [
                *options,
                "serve",
                "--port",
                str(port),
                *(["--background"] if args.background else [] if args.no_browser else ["--open"]),
            ]
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print("Stock Insight could not open the workspace:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
