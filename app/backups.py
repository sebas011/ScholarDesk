"""Consistent, local SQLite backups for ScholarDesk databases."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


class DatabaseBackupError(RuntimeError):
    """Raised when a requested database cannot safely be backed up."""


DatabaseSignature = tuple[tuple[tuple[str, str], ...], tuple[tuple[str, int], ...]]
MAX_BACKUP_PATH_RESERVATION_ATTEMPTS = 100


def _verify_backup_integrity(backup_path: Path) -> None:
    """Reject a backup SQLite cannot read back successfully."""
    backup_uri = f"file:{backup_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(backup_uri, uri=True, timeout=5)) as backup_connection:
        if backup_connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise sqlite3.DatabaseError("Backup integrity check failed.")


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _database_signature(database_path: Path) -> DatabaseSignature:
    """Return a compact, data-safe comparison signature for a SQLite database."""
    database_uri = f"file:{database_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True, timeout=5)) as connection:
        objects = tuple(
            connection.execute(
                """
                SELECT type, name
                FROM sqlite_master
                WHERE type IN ('index', 'table', 'trigger', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            )
        )
        table_counts = tuple(
            (
                name,
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(name)}"
                ).fetchone()[0],
            )
            for object_type, name in objects
            if object_type == "table"
        )
    return objects, table_counts


def _reserve_backup_path(source_path: Path, destination_directory: Path) -> Path:
    """Create an empty backup file exclusively, never replacing an existing backup."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for sequence in range(MAX_BACKUP_PATH_RESERVATION_ATTEMPTS):
        suffix = "" if sequence == 0 else f"-{sequence}"
        backup_path = destination_directory / f"{source_path.stem}.backup-{timestamp}{suffix}.db"
        try:
            with backup_path.open("xb"):
                pass
        except FileExistsError:
            continue
        return backup_path
    raise DatabaseBackupError("Could not reserve a unique backup file name.")


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

    backup_path: Path | None = None

    try:
        destination_directory.mkdir(parents=True, exist_ok=True)
        backup_path = _reserve_backup_path(source_path, destination_directory)
        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=5)) as source_connection:
            with closing(sqlite3.connect(backup_path)) as backup_connection:
                source_connection.backup(backup_connection)
        _verify_backup_integrity(backup_path)
    except (OSError, sqlite3.Error) as error:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)
        raise DatabaseBackupError(f"Backup failed: {error}") from error

    return backup_path


def restore_database(backup_path: Path, destination_path: Path) -> Path:
    """Restore a backup into a new database path without replacing live data."""
    source_path = backup_path.resolve()
    target_path = destination_path.resolve()

    if not source_path.is_file():
        raise DatabaseBackupError(f"Backup not found: {source_path}")
    if source_path == target_path:
        raise DatabaseBackupError("Restore destination must differ from the backup source.")
    if target_path.exists():
        raise DatabaseBackupError(f"Restore destination already exists: {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=5)) as source_connection:
            with closing(sqlite3.connect(target_path)) as target_connection:
                source_connection.backup(target_connection)
        _verify_backup_integrity(target_path)
    except (OSError, sqlite3.Error) as error:
        target_path.unlink(missing_ok=True)
        raise DatabaseBackupError(f"Restore failed: {error}") from error

    return target_path


def run_backup_restore_drill(database_path: Path, backup_directory: Path) -> Path:
    """Prove a new backup restores correctly without modifying the live database."""
    backup_path = backup_database(database_path, backup_directory)
    try:
        with TemporaryDirectory(prefix="scholardesk-restore-drill-") as temporary_directory:
            restored_path = Path(temporary_directory) / "restored-grants.db"
            restore_database(backup_path, restored_path)
            if _database_signature(backup_path) != _database_signature(restored_path):
                raise DatabaseBackupError(
                    "Restore drill failed: restored data does not match backup."
                )
    except (OSError, sqlite3.Error) as error:
        raise DatabaseBackupError(f"Restore drill failed: {error}") from error

    return backup_path
