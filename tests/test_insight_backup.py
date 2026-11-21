"""A live workspace, closed backup and fresh restore contain the same frozen evidence."""

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from stockinsight import backup, db, evidence, research, universe
from tests.test_insight_evidence import workspace


class BackupTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.source = self.root / "workspace" / "research.sqlite3"
        self.archive = self.root / "backup"
        self.restore = self.root / "restored"

    def open_workspace(self):
        connection, listings = workspace(fixture=True, path=self.source)
        self.addCleanup(connection.close)
        item = listings["NVDA"]["id"]
        return connection, item, evidence.seed_fixture(connection, item)[0]

    def test_wal_snapshot_even_as_source_advances_then_restore_without_recapturing(
        self,
    ):
        conn, item, passage = self.open_workspace()
        self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        question = "How did the two quarters compare?"
        research.ask(conn, item, question)
        (self.source.parent / ".env").write_text("private")
        (self.source.parent / "documents" / ("a" * 64)).write_bytes(b"unreferenced")
        original = evidence.document_bytes(conn, item, passage["document_id"])
        copy_documents = backup._copy_documents

        def capture_after_snapshot(snapshot, directory):
            with db.write(conn) as seq:
                raw = b"arrived later"
                staged = evidence._stage(conn, "full", raw)
                evidence._save(
                    conn,
                    seq,
                    item,
                    "test",
                    "fixture:later",
                    "Later evidence",
                    staged,
                    [],
                    db.now(),
                    published=None,
                    precision="unknown",
                    retention="full",
                    fixture=True,
                )
            universe.create_theme(conn, "New theme", "Added after the SQLite snapshot.")
            copy_documents(snapshot, directory)

        with patch.object(backup, "_copy_documents", capture_after_snapshot):
            self.assertEqual(backup.create(self.source, self.archive), self.archive)
        self.assertEqual(
            sorted(
                p.relative_to(self.archive).as_posix() for p in self.archive.rglob("*")
            ),
            ["documents", "documents/" + passage["version_hash"], "research.sqlite3"],
        )
        self.assertEqual(
            backup.create(self.archive / "research.sqlite3", self.restore), self.restore
        )
        with closing(
            db.connect(self.restore / "research.sqlite3", fixture=True)
        ) as restored:
            self.assertEqual(
                evidence.document_bytes(restored, item, passage["document_id"]),
                original,
            )
            self.assertEqual(
                restored.execute("SELECT question FROM cases").fetchone()[0], question
            )
            self.assertEqual(
                restored.execute("SELECT count(*) FROM themes").fetchone()[0], 0
            )
            self.assertEqual(
                restored.execute("SELECT count(*) FROM documents").fetchone()[0], 1
            )
            self.assertEqual(
                restored.execute("PRAGMA foreign_key_check").fetchall(), []
            )
            self.assertEqual(universe.instrument(restored, item)["ticker"], "NVDA")

    def test_schema_v2_archive_is_unmodified_and_restore_migrates_only_when_opened(
        self,
    ):
        old = db.migrations()[:2]
        with patch.object(db, "migrations", return_value=old):
            conn, item, passage = self.open_workspace()
            raw = evidence.document_bytes(conn, item, passage["document_id"])
            # Older snapshots could hold a full body in SQLite.
            conn.execute(
                "UPDATE documents SET body=? WHERE id=?", (raw, passage["document_id"])
            )
            (self.source.parent / "documents" / passage["version_hash"]).unlink()
        backup.create(self.source, self.archive)
        self.assertFalse((self.archive / "documents").exists())
        backup.create(self.archive / "research.sqlite3", self.restore)
        with closing(db.connect(self.restore / "research.sqlite3")) as restored:
            self.assertEqual(
                len(restored.execute("SELECT * FROM migrations").fetchall()),
                len(db.migrations()),
            )
            self.assertEqual(
                restored.execute("SELECT count(*) FROM monitor_occurrences").fetchone()[
                    0
                ],
                0,
            )
            self.assertEqual(
                evidence.document_bytes(restored, item, passage["document_id"]), raw
            )
        with closing(sqlite3.connect(self.archive / "research.sqlite3")) as archived:
            self.assertEqual(
                conn.execute("SELECT max(version) FROM migrations").fetchone()[0], 2
            )
            self.assertEqual(
                archived.execute("SELECT max(version) FROM migrations").fetchone()[0], 2
            )

    def test_missing_corrupt_or_malformed_document_never_publishes_and_leaves_no_staging(
        self,
    ):
        conn, _, p = self.open_workspace()
        blob = self.source.parent / "documents" / p["version_hash"]
        good = blob.read_bytes()
        blob.unlink()
        with self.assertRaises((OSError, ValueError)):
            backup.create(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        blob.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "integrity"):
            backup.create(self.source, self.archive)
        blob.write_bytes(good)
        conn.execute("UPDATE documents SET version_hash='../../wrong'")
        with self.assertRaisesRegex(ValueError, "digest"):
            backup.create(self.source, self.archive)
        conn.execute(
            "UPDATE documents SET version_hash=?,body=?",
            (hashlib.sha256(good).hexdigest(), b"corrupt embedded bytes"),
        )
        with self.assertRaisesRegex(ValueError, "integrity"):
            backup.create(self.source, self.archive)
        self.assertEqual(list(self.root.iterdir()), [self.source.parent])

    def test_invalid_source_existing_destination_overlaps_and_parallel_publication_fail_safely(
        self,
    ):
        conn, _, _ = self.open_workspace()
        for path in (self.source.parent / "backup", self.source.parent, self.root):
            with self.assertRaisesRegex(ValueError, "outside"):
                backup.create(self.source, path)
        self.archive.mkdir()
        with self.assertRaises(FileExistsError):
            backup.create(self.source, self.archive)
        self.assertEqual(list(self.archive.iterdir()), [])
        self.archive.rmdir()
        publish = backup._publish_new

        def race(staging, destination):
            destination.mkdir()
            publish(staging, destination)

        with patch.object(backup, "_publish_new", race), self.assertRaises(OSError):
            backup.create(self.source, self.archive)
        self.assertTrue(self.archive.is_dir())
        self.assertEqual(list(self.archive.iterdir()), [])
        self.assertEqual(list(self.root.glob(".stockinsight-backup-*")), [])
        conn.execute("UPDATE migrations SET sha256='tampered' WHERE version=1")
        with self.assertRaisesRegex(ValueError, "migration history"):
            backup.create(self.source, self.restore)
        self.assertFalse(self.restore.exists())
        missing = self.source.parent / "does-not-exist.sqlite3"
        with self.assertRaises(ValueError):
            backup.create(missing, self.restore)
        self.assertFalse(missing.exists())
