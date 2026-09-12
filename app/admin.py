"""Local administrator helper for setting the ScholarDesk login password."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sqlite3

from app.core.auth import DEFAULT_USERNAME, set_hashed_credentials
from app.backups import DatabaseBackupError, backup_database
from app.database import app_dir
from app.migrations import SchemaVersionError, baseline_legacy_database


def _set_password() -> None:
    """Prompt locally and write a PBKDF2 password hash without echoing it."""
    username = input(f"Username [{DEFAULT_USERNAME}]: ").strip() or DEFAULT_USERNAME
    password = getpass.getpass("New password (at least 12 characters): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match; auth.txt was not changed.")

    try:
        set_hashed_credentials(username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("Credentials saved securely. Restart ScholarDesk if it is running.")


def _baseline_database(database_path: Path) -> None:
    confirmation = input(
        "Stop ScholarDesk first. Type BASELINE to validate, back up, and mark this database: "
    )
    if confirmation != "BASELINE":
        raise SystemExit("Baseline cancelled; the database was not changed.")
    try:
        backup_path = baseline_legacy_database(database_path, app_dir / "backups")
    except (SchemaVersionError, sqlite3.Error) as error:
        raise SystemExit(f"Baseline refused: {error}") from error
    print(f"Database marked as schema version 1. Backup created: {backup_path}")


def _backup_database(database_path: Path) -> None:
    """Write a consistent local backup without changing the source database."""
    try:
        backup_path = backup_database(database_path, app_dir / "backups")
    except DatabaseBackupError as error:
        raise SystemExit(f"Backup failed: {error}") from error
    print(f"Backup created: {backup_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ScholarDesk local administrator utility.")
    database_action = parser.add_mutually_exclusive_group()
    database_action.add_argument(
        "--baseline-database",
        action="store_true",
        help="validate and baseline an existing grants.db after creating a backup",
    )
    database_action.add_argument(
        "--backup-database",
        action="store_true",
        help="create a consistent SQLite backup without modifying the database",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=app_dir / "grants.db",
        help="database to baseline; defaults to grants.db beside this utility",
    )
    arguments = parser.parse_args()
    if arguments.baseline_database:
        _baseline_database(arguments.database)
        return
    if arguments.backup_database:
        _backup_database(arguments.database)
        return
    _set_password()


if __name__ == "__main__":
    main()
