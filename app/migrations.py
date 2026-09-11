"""Minimal, fail-safe schema-version tracking for the SQLite database.

Version records are created only for databases that contained no application
tables before startup. Existing unversioned databases are intentionally not
modified: an explicit, backup-backed migration must baseline them later.
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from app.core.logging import logger

CURRENT_SCHEMA_VERSION = 1
MIGRATION_TABLE = "schema_migrations"


class SchemaVersionError(RuntimeError):
    """Raised when a database cannot safely run the installed application."""


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
