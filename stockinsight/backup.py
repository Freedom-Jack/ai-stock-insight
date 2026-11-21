"""Verified, restorable backups of a running private Stock Insight workspace."""

import ctypes
import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from . import db, evidence


def _local_path(value):
    # Resolve '..' only after checking the caller's path components. A junction
    # at any level must not turn a private backup into an unrelated file copy.
    path = Path(value).absolute()
    if os.name == "nt" and (
        path.drive.startswith("\\\\")
        or ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4
    ):
        raise ValueError("Choose a local source and destination drive.")
    for part in (*reversed(path.parents), path):
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            continue
        if evidence._is_link(metadata):
            raise ValueError(
                "Backup paths must be regular local files and directories."
            )
    return path.resolve(strict=False)


def _validate(snapshot):
    tables = {
        row[0]
        for row in snapshot.execute("SELECT name FROM sqlite_schema WHERE type='table'")
    }
    if (
        not {"migrations", "installation", "documents", "instruments", "commits"}
        <= tables
    ):
        raise ValueError("Choose an existing Stock Insight research database.")
    applied = list(
        snapshot.execute("SELECT version,sha256 FROM migrations ORDER BY version")
    )
    scripts = db.migrations()
    expected = [
        (i, hashlib.sha256(sql.encode()).hexdigest())
        for i, sql in enumerate(scripts[: len(applied)], 1)
    ]
    if not applied or list(map(tuple, applied)) != expected:
        raise ValueError("Unrecognized research database migration history.")
    if [r[0] for r in snapshot.execute("PRAGMA integrity_check")] != [
        "ok"
    ] or snapshot.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Research database failed its SQLite integrity check.")


def _copy_documents(snapshot, source_directory):
    """Use only immutable digests enumerated by the SQLite backup's own frozen read-set."""
    rows = snapshot.execute(
        """SELECT id,instrument_id,version_hash,body IS NULL AS external,length(body) AS bytes
           FROM documents WHERE retention='full' ORDER BY id"""
    )
    copied = set()
    for doc in rows:
        digest = doc["version_hash"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid referenced document digest.")
        if doc["external"] and digest not in copied:
            payload = evidence._read_blob(
                _local_path(source_directory / "documents" / digest)
            )
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(
                    "Referenced document failed its SHA-256 integrity check."
                )
            evidence._stage(snapshot, "full", payload)
            copied.add(digest)
        if doc["bytes"] and doc["bytes"] > evidence.MAX_DOCUMENT_BYTES:
            raise ValueError("Embedded document exceeds the permitted size.")
        # Reopen the copy, including bodies embedded by older releases.
        evidence.document_bytes(snapshot, doc["instrument_id"], doc["id"])


def _publish_new(staging, destination):
    """Atomically rename the complete directory without replacing a racing caller's destination."""
    if os.name == "nt":
        os.rename(staging, destination)  # Windows refuses an existing destination.
    else:
        libc = ctypes.CDLL(None, use_errno=True)
        old, new = os.fsencode(staging), os.fsencode(destination)
        if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            # AT_FDCWD, RENAME_NOREPLACE
            result = libc.renameat2(-100, old, -100, new, 1)
        elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
            result = libc.renamex_np(old, new, 4)  # RENAME_EXCL
        else:
            raise ValueError(
                "This filesystem platform lacks exclusive directory publication."
            )
        if result:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number), destination)
    evidence._flush_directory(destination.parent)


def create(source_db_path, new_destination_dir) -> Path:
    """Return a new workspace directory; use this same function to restore into another location."""
    source, destination = _local_path(source_db_path), _local_path(new_destination_dir)
    if destination.is_relative_to(source.parent) or source.parent.is_relative_to(
        destination
    ):
        raise ValueError("Choose a backup directory outside the source workspace.")
    if not source.is_file() or not destination.parent.is_dir():
        raise ValueError(
            "Choose an existing source database and an existing destination parent."
        )
    if destination.exists():
        raise FileExistsError("Backup destination already exists.")
    # A private staging parent remains in our exclusive ownership even after the
    # child directory is renamed. Cleanup cannot delete an unrelated destination.
    with tempfile.TemporaryDirectory(
        prefix=".stockinsight-backup-", dir=destination.parent
    ) as holding:
        staging = Path(holding) / "workspace"
        staging.mkdir(mode=0o700)
        target = staging / "research.sqlite3"
        target.touch(mode=0o600, exist_ok=False)
        with (
            closing(
                sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)
            ) as live,
            closing(sqlite3.connect(target, isolation_level=None)) as snapshot,
        ):
            live.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 180

            def progress(_status, _remaining, _total):
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "Database backup timed out. Retry when the workspace is quieter."
                    )

            live.backup(snapshot, pages=256, sleep=0.05, progress=progress)
            snapshot.row_factory = sqlite3.Row
            # The archive is self-contained even when the original used WAL.
            snapshot.execute("PRAGMA journal_mode=DELETE")
            _validate(snapshot)
            _copy_documents(snapshot, source.parent)
        with target.open("rb+") as stream:
            os.fsync(stream.fileno())
        evidence._flush_directory(staging)
        _publish_new(staging, destination)
    return destination
