"""Consistent, local SQLite backups for ScholarDesk databases."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class DatabaseBackupError(RuntimeError):
    """Raised when a requested database cannot safely be backed up."""


def _verify_backup_integrity(backup_path: Path) -> None:
    """Reject a backup SQLite cannot read back successfully."""
    backup_uri = f"file:{backup_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(backup_uri, uri=True, timeout=5)) as backup_connection:
        if backup_connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise sqlite3.DatabaseError("Backup integrity check failed.")


def backup_database(database_path: Path, backup_directory: Path) -> Path:
    """Create a timestamped, transactionally consistent SQLite backup.

    SQLite's backup API captures committed WAL data as one database file, so
    callers do not copy a potentially inconsistent ``.db``, ``-wal``, and
    ``-shm`` file set. The source database is opened read-only and never
    modified.
    """
    source_path = database_path.resolve()
    destination_directory = backup_directory.resolve()

    if not source_path.is_file():
        raise DatabaseBackupError(f"Database not found: {source_path}")

    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = destination_directory / f"{source_path.stem}.backup-{timestamp}.db"

    try:
        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=5)) as source_connection:
            with closing(sqlite3.connect(backup_path)) as backup_connection:
                source_connection.backup(backup_connection)
        _verify_backup_integrity(backup_path)
    except sqlite3.Error as error:
        backup_path.unlink(missing_ok=True)
        raise DatabaseBackupError(f"Backup failed: {error}") from error

    return backup_path
