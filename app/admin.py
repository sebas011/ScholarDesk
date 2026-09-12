"""Local administrator helper for setting the ScholarDesk login password."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sqlite3

from app.core.auth import DEFAULT_USERNAME, list_usernames, remove_user, set_user_password
from app.backups import DatabaseBackupError, backup_database, run_backup_restore_drill
from app.database import app_dir
from app.migrations import SchemaVersionError, baseline_legacy_database


def _set_password() -> None:
    """Prompt locally and write a PBKDF2 password hash without echoing it."""
    username = input(f"Username [{DEFAULT_USERNAME}]: ").strip() or DEFAULT_USERNAME
    password = getpass.getpass("New password (at least 12 characters): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match; user accounts were not changed.")

    try:
        set_user_password(username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("User account saved securely. Restart ScholarDesk if it is running.")


def _list_users() -> None:
    """Show local administrator names without exposing authentication material."""
    usernames = list_usernames()
    if not usernames:
        raise SystemExit("No administrator accounts are configured.")
    print("Local administrator accounts:")
    for username in usernames:
        print(f"- {username}")


def _remove_user(username: str) -> None:
    """Require an explicit local confirmation before revoking an account."""
    confirmation = input(f"Type {username} to permanently remove this administrator: ")
    if confirmation != username:
        raise SystemExit("Account removal cancelled; no accounts were changed.")
    try:
        remove_user(username)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"Administrator '{username}' was removed. Restart ScholarDesk if it is running.")


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


def _verify_backup_restore(database_path: Path) -> None:
    """Create a backup and prove it restores without changing the live database."""
    try:
        backup_path = run_backup_restore_drill(database_path, app_dir / "backups")
    except DatabaseBackupError as error:
        raise SystemExit(f"Backup restore drill failed: {error}") from error
    print(f"Backup restore drill passed. Verified backup: {backup_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ScholarDesk local administrator utility.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--baseline-database",
        action="store_true",
        help="validate and baseline an existing grants.db after creating a backup",
    )
    action.add_argument(
        "--backup-database",
        action="store_true",
        help="create a consistent SQLite backup without modifying the database",
    )
    action.add_argument(
        "--verify-backup-restore",
        action="store_true",
        help="create a backup and verify it restores into a disposable copy",
    )
    action.add_argument(
        "--list-users",
        action="store_true",
        help="list local administrator usernames without revealing passwords",
    )
    action.add_argument(
        "--remove-user",
        metavar="USERNAME",
        help="permanently revoke one local administrator after confirmation",
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
    if arguments.verify_backup_restore:
        _verify_backup_restore(arguments.database)
        return
    if arguments.list_users:
        _list_users()
        return
    if arguments.remove_user:
        _remove_user(arguments.remove_user)
        return
    _set_password()


if __name__ == "__main__":
    main()
