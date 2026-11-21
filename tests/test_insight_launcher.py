"""Exercise launcher profile isolation, verified restore and pre-upgrade recovery."""

import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from stockinsight import db, launcher, universe


class LauncherWorkspaceTests(unittest.TestCase):
    def test_version_two_upgrade_saves_restorable_original_and_never_overwrites_another_profile(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as scratch,
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            root = Path(scratch) / "profiles"
            path = root / "personal/research.sqlite3"
            with (
                patch.object(db, "migrations", return_value=db.migrations()[:2]),
                closing(db.connect(path)) as old,
            ):
                universe.import_snapshot(old, b"MSFT", complete=True)

            def start(args):
                self.assertIn("serve", args)
                with closing(db.connect(path, fixture=False)) as conn:
                    self.assertEqual(
                        conn.execute("SELECT max(version) FROM migrations").fetchone()[
                            0
                        ],
                        3,
                    )
                return 0

            with patch.object(launcher.cli, "main", side_effect=start):
                self.assertEqual(launcher.main(["--root", str(root)]), 0)
            (backup,) = (root / "backups").iterdir()
            with closing(sqlite3.connect(backup / "research.sqlite3")) as original:
                self.assertEqual(
                    original.execute("SELECT max(version) FROM migrations").fetchone()[
                        0
                    ],
                    2,
                )
            self.assertEqual(
                launcher.main(
                    ["--demo", "--root", str(root), "--restore", str(backup)]
                ),
                1,
            )
            self.assertFalse((root / "demo").exists())
            self.assertEqual(
                launcher.main(["--root", str(root), "--restore", str(backup)]), 1
            )
            new_root = Path(scratch) / "recovered"
            self.assertEqual(
                launcher.main(["--root", str(new_root), "--restore", str(backup)]), 0
            )
            with closing(
                db.connect(new_root / "personal/research.sqlite3")
            ) as restored:
                self.assertEqual(
                    universe.universe(restored)["instruments"][0]["ticker"], "MSFT"
                )
