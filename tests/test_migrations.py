import sqlite3

import pytest
from sqlalchemy import create_engine, text

from app.backups import DatabaseBackupError
from app.database import Base
from app.migrations import (
    BASELINE_SCHEMA_VERSION,
    CURRENT_SCHEMA_VERSION,
    MIGRATION_TABLE,
    SchemaVersionError,
    baseline_legacy_database,
    ensure_schema_version,
    existing_table_names,
    get_schema_version,
)


def _create_legacy_v1_database(database_path):
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        from app import models  # noqa: F401

        Base.metadata.create_all(bind=engine)
    finally:
        engine.dispose()


def test_new_database_receives_initial_schema_version(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    try:
        assert existing_table_names(engine) == set()

        assert ensure_schema_version(engine, database_was_empty=True) == CURRENT_SCHEMA_VERSION
        assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
    finally:
        engine.dispose()


def test_existing_unversioned_database_is_not_silently_baselined(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE scholars (id INTEGER PRIMARY KEY)"))

        assert ensure_schema_version(engine, database_was_empty=False) is None
        assert MIGRATION_TABLE not in existing_table_names(engine)
    finally:
        engine.dispose()


def test_newer_database_schema_refuses_startup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'newer.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)"))
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": CURRENT_SCHEMA_VERSION + 1},
            )

        try:
            ensure_schema_version(engine, database_was_empty=False)
        except SchemaVersionError as error:
            assert "newer than this application" in str(error)
        else:
            raise AssertionError("Expected a newer schema version to refuse startup.")
    finally:
        engine.dispose()


def test_current_version_database_missing_index_refuses_startup(tmp_path):
    database_path = tmp_path / "missing-index.db"
    _create_legacy_v1_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_activity_logs_scholar_id"))
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations ("
                    "version INTEGER NOT NULL PRIMARY KEY, "
                    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": CURRENT_SCHEMA_VERSION},
            )

        with pytest.raises(SchemaVersionError, match="missing indexes"):
            ensure_schema_version(engine, database_was_empty=False)
    finally:
        engine.dispose()


def test_baseline_legacy_database_creates_backup_then_records_version(tmp_path):
    database_path = tmp_path / "legacy.db"
    backup_directory = tmp_path / "backups"
    _create_legacy_v1_database(database_path)

    backup_path = baseline_legacy_database(database_path, backup_directory)

    engine = create_engine(f"sqlite:///{database_path}")
    backup_engine = create_engine(f"sqlite:///{backup_path}")
    try:
        assert backup_path.parent == backup_directory
        assert get_schema_version(engine) == BASELINE_SCHEMA_VERSION
        assert MIGRATION_TABLE not in existing_table_names(backup_engine)
    finally:
        engine.dispose()
        backup_engine.dispose()


def test_baseline_refuses_unrecognized_database_without_creating_backup(tmp_path):
    database_path = tmp_path / "invalid.db"
    backup_directory = tmp_path / "backups"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY)")

    try:
        baseline_legacy_database(database_path, backup_directory)
    except SchemaVersionError as error:
        assert "Missing required tables" in str(error)
    else:
        raise AssertionError("Expected an unrecognized database to be refused.")
    assert not backup_directory.exists()


def test_baseline_refuses_when_verified_backup_fails(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    backup_directory = tmp_path / "backups"
    _create_legacy_v1_database(database_path)

    def fail_backup(*_args):
        raise DatabaseBackupError("storage unavailable")

    monkeypatch.setattr("app.migrations.backup_database", fail_backup)

    with pytest.raises(SchemaVersionError, match="Baseline backup failed: storage unavailable"):
        baseline_legacy_database(database_path, backup_directory)

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        assert MIGRATION_TABLE not in existing_table_names(engine)
    finally:
        engine.dispose()
    assert not backup_directory.exists()


def test_version_one_database_receives_activity_log_index_migration(tmp_path):
    database_path = tmp_path / "version-one.db"
    backup_directory = tmp_path / "backups"
    _create_legacy_v1_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_activity_logs_scholar_id"))
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations ("
                    "version INTEGER NOT NULL PRIMARY KEY, "
                    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": BASELINE_SCHEMA_VERSION},
            )

        assert ensure_schema_version(
            engine,
            database_was_empty=False,
            backup_directory=backup_directory,
        ) == CURRENT_SCHEMA_VERSION
        assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
        with engine.connect() as connection:
            indexes = {
                row[1]
                for row in connection.execute(text("PRAGMA index_list('activity_logs')"))
            }
        assert "ix_activity_logs_scholar_id" in indexes
        backups = list(backup_directory.glob("version-one.backup-*.db"))
        assert len(backups) == 1

        backup_engine = create_engine(f"sqlite:///{backups[0]}")
        try:
            with backup_engine.connect() as connection:
                backup_indexes = {
                    row[1]
                    for row in connection.execute(text("PRAGMA index_list('activity_logs')"))
                }
            assert "ix_activity_logs_scholar_id" not in backup_indexes
        finally:
            backup_engine.dispose()
    finally:
        engine.dispose()


def test_version_two_database_repairs_missing_activity_log_index(tmp_path):
    database_path = tmp_path / "version-two.db"
    backup_directory = tmp_path / "backups"
    _create_legacy_v1_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_activity_logs_scholar_id"))
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations ("
                    "version INTEGER NOT NULL PRIMARY KEY, "
                    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            for version in (BASELINE_SCHEMA_VERSION, 2):
                connection.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": version},
                )

        assert ensure_schema_version(
            engine,
            database_was_empty=False,
            backup_directory=backup_directory,
        ) == CURRENT_SCHEMA_VERSION
        assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
        with engine.connect() as connection:
            indexes = {
                row[1]
                for row in connection.execute(text("PRAGMA index_list('activity_logs')"))
            }
        assert "ix_activity_logs_scholar_id" in indexes
        assert len(list(backup_directory.glob("version-two.backup-*.db"))) == 1
    finally:
        engine.dispose()


def test_version_three_database_receives_actor_attribution_column(tmp_path):
    database_path = tmp_path / "version-three.db"
    backup_directory = tmp_path / "backups"
    _create_legacy_v1_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_activity_logs_scholar_id"))
            connection.execute(text("DROP TABLE activity_logs"))
            connection.execute(
                text(
                    "CREATE TABLE activity_logs ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "scholar_id INTEGER NULL, "
                    "category VARCHAR(50), "
                    "description TEXT NOT NULL, "
                    "created_at DATETIME, "
                    "FOREIGN KEY(scholar_id) REFERENCES scholars(id) ON DELETE SET NULL)"
                )
            )
            connection.execute(
                text("CREATE INDEX ix_activity_logs_scholar_id ON activity_logs (scholar_id)")
            )
            connection.execute(
                text(
                    "INSERT INTO activity_logs (category, description) "
                    "VALUES ('system', 'legacy event')"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations ("
                    "version INTEGER NOT NULL PRIMARY KEY, "
                    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            for version in (BASELINE_SCHEMA_VERSION, 2, 3):
                connection.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": version},
                )

        assert ensure_schema_version(
            engine,
            database_was_empty=False,
            backup_directory=backup_directory,
        ) == CURRENT_SCHEMA_VERSION
        with engine.connect() as connection:
            actor_username = connection.execute(
                text("SELECT actor_username FROM activity_logs")
            ).scalar_one()

        assert actor_username == "legacy"
        assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
        assert len(list(backup_directory.glob("version-three.backup-*.db"))) == 1
    finally:
        engine.dispose()


def test_version_four_database_rebuilds_scholar_related_foreign_keys_with_cascade(tmp_path):
    database_path = tmp_path / "version-four.db"
    backup_directory = tmp_path / "backups"
    _create_legacy_v1_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO scholars (id, name, missing_requirements) "
                    "VALUES (1, 'Cascade Scholar', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO department_assignments (scholar_id, department) "
                    "VALUES (1, 'CCS')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO grants (id, scholar_id, program_applied, status) "
                    "VALUES (1, 1, 'Cascade Grant', 'Active')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO grant_reviews (grant_id, decision, created_at) "
                    "VALUES (1, 'approved', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO scholar_notes (scholar_id, content, created_at) "
                    "VALUES (1, 'Cascade note', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO activity_logs "
                    "(scholar_id, category, description, actor_username, created_at) "
                    "VALUES (1, 'scholar', 'Cascade activity', 'admin', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations ("
                    "version INTEGER NOT NULL PRIMARY KEY, "
                    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            for version in (BASELINE_SCHEMA_VERSION, 2, 3, 4):
                connection.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": version},
                )

        assert ensure_schema_version(
            engine,
            database_was_empty=False,
            backup_directory=backup_directory,
        ) == CURRENT_SCHEMA_VERSION
        with engine.begin() as connection:
            delete_actions = {
                (table_name, row[3]): row[6]
                for table_name in (
                    "department_assignments",
                    "grants",
                    "scholar_notes",
                    "activity_logs",
                )
                for row in connection.execute(text(f"PRAGMA foreign_key_list({table_name})"))
            }
            assert all(
                delete_actions[(table_name, "scholar_id")] == "CASCADE"
                for table_name in (
                    "department_assignments",
                    "grants",
                    "scholar_notes",
                    "activity_logs",
                )
            )
            connection.execute(text("DELETE FROM scholars WHERE id = 1"))
            for table_name in (
                "department_assignments",
                "grants",
                "grant_reviews",
                "scholar_notes",
                "activity_logs",
            ):
                assert connection.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                ).scalar_one() == 0

        assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
        assert len(list(backup_directory.glob("version-four.backup-*.db"))) == 1
    finally:
        engine.dispose()
