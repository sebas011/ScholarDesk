"""Fail-safe schema-version tracking and migrations for the SQLite database.

Existing unversioned databases are intentionally not modified: an explicit,
backup-backed baseline is required before startup can apply a migration.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from sqlalchemy import Engine, inspect, text

from app.backups import DatabaseBackupError, backup_database
from app.core.logging import logger

BASELINE_SCHEMA_VERSION = 1
CURRENT_SCHEMA_VERSION = 5
MIGRATION_TABLE = "schema_migrations"
ForeignKeyDefinition = tuple[str, str, str, str]
ACTIVITY_LOG_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_activity_logs_scholar_id "
    "ON activity_logs (scholar_id)"
)
ACTIVITY_LOG_ACTOR_COLUMN_SQL = (
    "ALTER TABLE activity_logs "
    "ADD COLUMN actor_username VARCHAR(200) NOT NULL DEFAULT 'legacy'"
)
CASCADE_DELETE_REBUILD_SQL = (
    "CREATE TABLE department_assignments_v5 ("
    "id INTEGER NOT NULL PRIMARY KEY, scholar_id INTEGER NOT NULL, "
    "department VARCHAR(100) NOT NULL, rank VARCHAR(100), tenure VARCHAR(100), "
    "date_started DATE, date_ended DATE, "
    "FOREIGN KEY(scholar_id) REFERENCES scholars(id) ON DELETE CASCADE)",
    "INSERT INTO department_assignments_v5 "
    "SELECT id, scholar_id, department, rank, tenure, date_started, date_ended "
    "FROM department_assignments",
    "DROP TABLE department_assignments",
    "ALTER TABLE department_assignments_v5 RENAME TO department_assignments",
    "CREATE INDEX ix_department_assignments_scholar_id "
    "ON department_assignments (scholar_id)",
    "CREATE INDEX ix_department_assignments_date_started "
    "ON department_assignments (date_started)",
    "CREATE INDEX ix_department_assignments_date_ended "
    "ON department_assignments (date_ended)",
    "CREATE TABLE grants_v5 ("
    "id INTEGER NOT NULL PRIMARY KEY, scholar_id INTEGER NOT NULL, "
    "program_applied VARCHAR(300) NOT NULL, type_of_grant VARCHAR(150), "
    "delivering_hei VARCHAR(200), date_started VARCHAR(100), date_ended VARCHAR(100), "
    "start_year INTEGER, end_year INTEGER, extension VARCHAR(200), "
    "status VARCHAR(50) NOT NULL, remarks TEXT, "
    "FOREIGN KEY(scholar_id) REFERENCES scholars(id) ON DELETE CASCADE)",
    "INSERT INTO grants_v5 "
    "SELECT id, scholar_id, program_applied, type_of_grant, delivering_hei, "
    "date_started, date_ended, start_year, end_year, extension, status, remarks FROM grants",
    "DROP TABLE grants",
    "ALTER TABLE grants_v5 RENAME TO grants",
    "CREATE INDEX ix_grants_scholar_id ON grants (scholar_id)",
    "CREATE INDEX ix_grants_start_year ON grants (start_year)",
    "CREATE INDEX ix_grants_end_year ON grants (end_year)",
    "CREATE TABLE scholar_notes_v5 ("
    "id INTEGER NOT NULL PRIMARY KEY, scholar_id INTEGER NOT NULL, content TEXT NOT NULL, "
    "created_at DATETIME, FOREIGN KEY(scholar_id) REFERENCES scholars(id) ON DELETE CASCADE)",
    "INSERT INTO scholar_notes_v5 SELECT id, scholar_id, content, created_at FROM scholar_notes",
    "DROP TABLE scholar_notes",
    "ALTER TABLE scholar_notes_v5 RENAME TO scholar_notes",
    "CREATE INDEX ix_scholar_notes_scholar_id ON scholar_notes (scholar_id)",
    "CREATE TABLE activity_logs_v5 ("
    "id INTEGER NOT NULL PRIMARY KEY, scholar_id INTEGER, category VARCHAR(50) NOT NULL, "
    "description TEXT NOT NULL, actor_username VARCHAR(200) NOT NULL, created_at DATETIME, "
    "FOREIGN KEY(scholar_id) REFERENCES scholars(id) ON DELETE CASCADE)",
    "INSERT INTO activity_logs_v5 "
    "SELECT id, scholar_id, category, description, actor_username, created_at FROM activity_logs",
    "DROP TABLE activity_logs",
    "ALTER TABLE activity_logs_v5 RENAME TO activity_logs",
    "CREATE INDEX ix_activity_logs_scholar_id ON activity_logs (scholar_id)",
)


class SchemaVersionError(RuntimeError):
    """Raised when a database cannot safely run the installed application."""


def _expected_schema(version: int = CURRENT_SCHEMA_VERSION) -> tuple[
    dict[str, set[str]], dict[str, set[str]], set[ForeignKeyDefinition]
]:
    """Derive required schema objects for a known schema version from the ORM."""
    from app import models  # noqa: F401
    from app.database import Base

    columns_by_table: dict[str, set[str]] = {}
    indexes_by_table: dict[str, set[str]] = {}
    foreign_keys: set[ForeignKeyDefinition] = set()
    for table in Base.metadata.tables.values():
        columns_by_table[table.name] = {column.name for column in table.columns}
        indexes_by_table[table.name] = {index.name for index in table.indexes if index.name}
        for foreign_key in table.foreign_keys:
            foreign_keys.add(
                (
                    table.name,
                    foreign_key.parent.name,
                    foreign_key.column.table.name,
                    foreign_key.column.name,
                )
            )

    if version < 2:
        indexes_by_table["activity_logs"].discard("ix_activity_logs_scholar_id")
    if version < 4:
        columns_by_table["activity_logs"].discard("actor_username")
    return columns_by_table, indexes_by_table, foreign_keys


def _validate_schema_connection(
    connection: sqlite3.Connection, *, version: int = CURRENT_SCHEMA_VERSION
) -> None:
    expected_columns, expected_indexes, expected_foreign_keys = _expected_schema(version)
    actual_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_tables = set(expected_columns) - actual_tables
    if missing_tables:
        raise SchemaVersionError(f"Missing required tables: {', '.join(sorted(missing_tables))}.")

    actual_foreign_keys: set[ForeignKeyDefinition] = set()
    for table_name, required_columns in expected_columns.items():
        actual_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")
        }
        missing_columns = required_columns - actual_columns
        if missing_columns:
            raise SchemaVersionError(
                f"Table {table_name} is missing columns: {', '.join(sorted(missing_columns))}."
            )

        actual_indexes = {
            row[1] for row in connection.execute(f"PRAGMA index_list({table_name})")
        }
        missing_indexes = expected_indexes[table_name] - actual_indexes
        if missing_indexes:
            raise SchemaVersionError(
                f"Table {table_name} is missing indexes: {', '.join(sorted(missing_indexes))}."
            )

        for row in connection.execute(f"PRAGMA foreign_key_list({table_name})"):
            actual_foreign_keys.add((table_name, row[3], row[2], row[4]))

    missing_foreign_keys = expected_foreign_keys - actual_foreign_keys
    if missing_foreign_keys:
        raise SchemaVersionError("Database is missing required foreign-key constraints.")

    if version >= 5:
        from app.database import Base

        expected_delete_actions = {
            (table.name, foreign_key.parent.name): (foreign_key.ondelete or "NO ACTION").upper()
            for table in Base.metadata.tables.values()
            for foreign_key in table.foreign_keys
        }
        actual_delete_actions = {
            (table_name, row[3]): row[6].upper()
            for table_name in expected_columns
            for row in connection.execute(f"PRAGMA foreign_key_list({table_name})")
        }
        mismatched_delete_actions = {
            key: expected_action
            for key, expected_action in expected_delete_actions.items()
            if actual_delete_actions.get(key) != expected_action
        }
        if mismatched_delete_actions:
            raise SchemaVersionError(
                "Database foreign-key delete actions do not match this release."
            )

    quick_check = [row[0] for row in connection.execute("PRAGMA quick_check")]
    if quick_check != ["ok"]:
        raise SchemaVersionError(f"SQLite integrity check failed: {quick_check}.")
    foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_violations:
        raise SchemaVersionError("SQLite foreign-key check found invalid rows.")


def baseline_legacy_database(database_path: Path, backup_directory: Path) -> Path:
    """Validate, back up, and explicitly mark one recognized legacy database as v1.

    The caller must ensure ScholarDesk is stopped. The SQLite backup API captures
    the validated pre-baseline state before ``BEGIN IMMEDIATE`` acquires the
    write lock; the schema is then validated again before the version is written.
    """
    database_path = database_path.resolve()
    backup_directory = backup_directory.resolve()
    if not database_path.is_file():
        raise SchemaVersionError(f"Database not found: {database_path}")

    with closing(sqlite3.connect(database_path, timeout=5)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            migration_table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (MIGRATION_TABLE,),
            ).fetchone()
            if migration_table_exists:
                raise SchemaVersionError("Database is already migration-managed; baseline refused.")

            _validate_schema_connection(connection, version=BASELINE_SCHEMA_VERSION)
            try:
                backup_path = backup_database(database_path, backup_directory)
            except DatabaseBackupError as error:
                raise SchemaVersionError(f"Baseline backup failed: {error}") from error

            connection.execute("BEGIN IMMEDIATE")
            migration_table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (MIGRATION_TABLE,),
            ).fetchone()
            if migration_table_exists:
                raise SchemaVersionError("Database became migration-managed; baseline refused.")
            _validate_schema_connection(connection, version=BASELINE_SCHEMA_VERSION)
            connection.execute(
                "CREATE TABLE schema_migrations ("
                "version INTEGER NOT NULL PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (BASELINE_SCHEMA_VERSION,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return backup_path


def existing_table_names(engine: Engine) -> set[str]:
    """Read the database state before metadata creation changes it."""
    with engine.connect() as connection:
        return set(inspect(connection).get_table_names())


def get_schema_version(engine: Engine) -> int | None:
    """Return the latest recorded migration version, if tracking exists."""
    with engine.connect() as connection:
        if MIGRATION_TABLE not in inspect(connection).get_table_names():
            return None
        return connection.execute(
            text(f"SELECT MAX(version) FROM {MIGRATION_TABLE}")
        ).scalar_one()


def _database_path(engine: Engine) -> Path:
    """Return the file path required for a backup-backed SQLite migration."""
    database = engine.url.database
    if engine.dialect.name != "sqlite" or database in (None, "", ":memory:"):
        raise SchemaVersionError("Schema migrations require a file-backed SQLite database.")
    return Path(database)


def _apply_cascade_delete_migration(engine: Engine) -> None:
    """Rebuild SQLite child tables so scholar deletion is database-enforced cascade."""
    with engine.connect() as connection:
        connection.commit()
        dbapi_connection = connection.connection.driver_connection
        dbapi_connection.execute("PRAGMA foreign_keys = OFF")
        try:
            dbapi_connection.execute("BEGIN IMMEDIATE")
            for statement in CASCADE_DELETE_REBUILD_SQL:
                dbapi_connection.execute(statement)
            dbapi_connection.execute(
                f"INSERT INTO {MIGRATION_TABLE} (version) VALUES (?)", (5,)
            )
            dbapi_connection.commit()
        except Exception:
            dbapi_connection.rollback()
            raise
        finally:
            dbapi_connection.execute("PRAGMA foreign_keys = ON")


def _apply_pending_migrations(engine: Engine, version: int, backup_directory: Path) -> int:
    """Back up and atomically apply every migration after ``version``."""
    database_path = _database_path(engine)
    try:
        backup_path = backup_database(database_path, backup_directory)
    except DatabaseBackupError as error:
        raise SchemaVersionError(f"Migration backup failed: {error}") from error

    legacy_target_version = min(CURRENT_SCHEMA_VERSION, 4)
    if version < legacy_target_version:
        with engine.begin() as connection:
            current_version = connection.execute(
                text(f"SELECT MAX(version) FROM {MIGRATION_TABLE}")
            ).scalar_one()
            if current_version != version:
                raise SchemaVersionError("Database schema version changed during migration.")

            for target_version in range(version + 1, legacy_target_version + 1):
                if target_version in (2, 3):
                    connection.execute(text(ACTIVITY_LOG_INDEX_SQL))
                elif target_version == 4:
                    existing_columns = {
                        row[1]
                        for row in connection.execute(text("PRAGMA table_info(activity_logs)"))
                    }
                    if "actor_username" not in existing_columns:
                        connection.execute(text(ACTIVITY_LOG_ACTOR_COLUMN_SQL))
                else:
                    raise SchemaVersionError(
                        f"No migration is registered for version {target_version}."
                    )
                connection.execute(
                    text(f"INSERT INTO {MIGRATION_TABLE} (version) VALUES (:version)"),
                    {"version": target_version},
                )
        version = legacy_target_version

    if version < 5 <= CURRENT_SCHEMA_VERSION:
        _apply_cascade_delete_migration(engine)

    logger.info(
        "Migrated database schema from version %s to %s; backup created at %s.",
        version,
        CURRENT_SCHEMA_VERSION,
        backup_path,
    )
    return CURRENT_SCHEMA_VERSION


def ensure_schema_version(
    engine: Engine,
    *,
    database_was_empty: bool,
    backup_directory: Path | None = None,
) -> int | None:
    """Initialize new databases or safely upgrade recognized schema versions."""
    version = get_schema_version(engine)
    if version is not None:
        if version > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema version {version} is newer than this application "
                f"(supports {CURRENT_SCHEMA_VERSION})."
            )
        if version < CURRENT_SCHEMA_VERSION:
            if backup_directory is None:
                raise SchemaVersionError("A backup directory is required before schema migration.")
            version = _apply_pending_migrations(engine, version, backup_directory)

        # A recorded current version is not proof that the database still has
        # every object the application needs. Verify it before serving traffic.
        with closing(engine.raw_connection()) as connection:
            _validate_schema_connection(connection, version=version)
        return version

    if not database_was_empty:
        # Recognize the legacy schema without altering it, then fail closed.
        # A current application cannot safely serve an older unversioned
        # database because later migrations may add columns and indexes used
        # by normal write paths.
        with closing(engine.raw_connection()) as connection:
            _validate_schema_connection(connection, version=BASELINE_SCHEMA_VERSION)
        raise SchemaVersionError(
            "Database has no schema version record. Run ScholarDeskAdmin "
            "--baseline-database before starting ScholarDesk."
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER NOT NULL PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT OR IGNORE INTO schema_migrations (version) "
                "VALUES (:version)"
            ),
            {"version": CURRENT_SCHEMA_VERSION},
        )
    return CURRENT_SCHEMA_VERSION
