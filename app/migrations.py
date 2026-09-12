"""Minimal, fail-safe schema-version tracking for the SQLite database.

Version records are created only for databases that contained no application
tables before startup. Existing unversioned databases are intentionally not
modified: an explicit, backup-backed migration must baseline them later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sqlalchemy import Engine, inspect, text

from app.core.logging import logger

CURRENT_SCHEMA_VERSION = 1
MIGRATION_TABLE = "schema_migrations"
ForeignKeyDefinition = tuple[str, str, str, str]


class SchemaVersionError(RuntimeError):
    """Raised when a database cannot safely run the installed application."""


def _expected_schema() -> tuple[
    dict[str, set[str]], dict[str, set[str]], set[ForeignKeyDefinition]
]:
    """Derive the required v1 table, index, and foreign-key names from the ORM."""
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
    return columns_by_table, indexes_by_table, foreign_keys


def _validate_schema_connection(connection: sqlite3.Connection) -> None:
    expected_columns, expected_indexes, expected_foreign_keys = _expected_schema()
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

    with sqlite3.connect(database_path, timeout=5) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            migration_table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (MIGRATION_TABLE,),
            ).fetchone()
            if migration_table_exists:
                raise SchemaVersionError("Database is already migration-managed; baseline refused.")

            _validate_schema_connection(connection)
            backup_directory.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_directory / f"{database_path.stem}.pre-baseline-{timestamp}.db"
            with sqlite3.connect(backup_path) as backup_connection:
                connection.backup(backup_connection)

            connection.execute("BEGIN IMMEDIATE")
            migration_table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (MIGRATION_TABLE,),
            ).fetchone()
            if migration_table_exists:
                raise SchemaVersionError("Database became migration-managed; baseline refused.")
            _validate_schema_connection(connection)
            connection.execute(
                "CREATE TABLE schema_migrations ("
                "version INTEGER NOT NULL PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (CURRENT_SCHEMA_VERSION,),
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


def ensure_schema_version(engine: Engine, *, database_was_empty: bool) -> int | None:
    """Create version 1 only for a new database and reject future versions."""
    version = get_schema_version(engine)
    if version is not None:
        if version > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema version {version} is newer than this application "
                f"(supports {CURRENT_SCHEMA_VERSION})."
            )
        if version < CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema version {version} requires migration to "
                f"{CURRENT_SCHEMA_VERSION} before startup."
            )
        return version

    if not database_was_empty:
        logger.warning(
            "Database has no schema version record; preserving it without automatic migration."
        )
        return None

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
