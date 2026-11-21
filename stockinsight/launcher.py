"""Start the Windows personal desk from any working directory."""

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from . import __main__ as cli
from . import backup, db


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
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
        port = args.port if args.port is not None else 8766 if args.demo else 8765
        print("Workspace", folder, flush=True)
        return cli.main(
            [
                *options,
                "serve",
                "--port",
                str(port),
                *([] if args.no_browser else ["--open"]),
            ]
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print("Stock Insight could not open the workspace:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
