from sqlalchemy import create_engine, text

from app.migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATION_TABLE,
    SchemaVersionError,
    ensure_schema_version,
    existing_table_names,
    get_schema_version,
)


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
