import sqlite3

from sqlalchemy import create_engine, text

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
