import sqlite3

import pytest

from app.backups import DatabaseBackupError, backup_database


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
