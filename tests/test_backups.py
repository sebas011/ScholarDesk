import sqlite3
import sys

import pytest

from app import admin
from app.backups import (
    DatabaseBackupError,
    backup_database,
    restore_database,
    run_backup_restore_drill,
)


def test_backup_database_captures_committed_data(tmp_path):
    database_path = tmp_path / "grants.db"
    backup_directory = tmp_path / "backups"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("INSERT INTO scholars (name) VALUES (?)", ("Backup Scholar",))

    backup_path = backup_database(database_path, backup_directory)

    assert backup_path.parent == backup_directory
    assert backup_path.is_file()
    with sqlite3.connect(backup_path) as backup_connection:
        assert backup_connection.execute("SELECT name FROM scholars").fetchall() == [
            ("Backup Scholar",)
        ]
        assert backup_connection.execute("PRAGMA quick_check").fetchone() == ("ok",)


def test_backup_database_refuses_missing_source_without_creating_destination(tmp_path):
    with pytest.raises(DatabaseBackupError, match="Database not found"):
        backup_database(tmp_path / "missing.db", tmp_path / "backups")

    assert not (tmp_path / "backups").exists()


def test_backup_database_removes_output_after_integrity_check_failure(tmp_path, monkeypatch):
    database_path = tmp_path / "grants.db"
    backup_directory = tmp_path / "backups"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")

    def fail_integrity_check(_backup_path):
        raise sqlite3.DatabaseError("Backup integrity check failed.")

    monkeypatch.setattr("app.backups._verify_backup_integrity", fail_integrity_check)

    with pytest.raises(DatabaseBackupError, match="Backup integrity check failed"):
        backup_database(database_path, backup_directory)

    assert list(backup_directory.glob("*.db")) == []


def test_backup_restore_drill_preserves_schema_and_data(tmp_path):
    database_path = tmp_path / "grants.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE grants (id INTEGER PRIMARY KEY, scholar_id INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO scholars (name) VALUES (?)", ("Recovery Scholar",))
        connection.execute("INSERT INTO grants (scholar_id) VALUES (?)", (1,))

    backup_path = run_backup_restore_drill(database_path, tmp_path / "backups")

    assert backup_path.is_file()
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("SELECT name FROM scholars").fetchall() == [("Recovery Scholar",)]
        assert connection.execute("SELECT scholar_id FROM grants").fetchall() == [(1,)]


def test_restore_database_refuses_to_overwrite_an_existing_file(tmp_path):
    backup_path = tmp_path / "backup.db"
    destination_path = tmp_path / "grants.db"
    with sqlite3.connect(backup_path) as connection:
        connection.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY)")
    destination_path.write_bytes(b"do not overwrite")

    with pytest.raises(DatabaseBackupError, match="Restore destination already exists"):
        restore_database(backup_path, destination_path)

    assert destination_path.read_bytes() == b"do not overwrite"


def test_admin_exposes_backup_restore_drill(tmp_path, monkeypatch):
    database_path = tmp_path / "grants.db"
    called_with: dict[str, object] = {}

    def verify(database, backup_directory):
        called_with["database"] = database
        called_with["backup_directory"] = backup_directory
        return tmp_path / "backups" / "grants.backup.db"

    monkeypatch.setattr(admin, "run_backup_restore_drill", verify)
    monkeypatch.setattr(
        sys,
        "argv",
        ["admin", "--verify-backup-restore", "--database", str(database_path)],
    )

    admin.main()

    assert called_with["database"] == database_path
    assert called_with["backup_directory"] == admin.app_dir / "backups"
