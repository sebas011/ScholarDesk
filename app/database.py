"""
Database engine + session setup.

SQLite, single file, stored next to the app (grants.db). WAL mode is
enabled because it lets reads happen while a write is in progress -
irrelevant for true single-user use, but free insurance if you ever
open two browser tabs at once.
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# A relative "./grants.db" depends on the current working directory,
# which is NOT guaranteed to be the .exe's folder when double-clicked
# from Explorer (it depends on how it's launched - desktop shortcut,
# taskbar pin, etc. can all set a different cwd). Anchor explicitly to
# the folder containing the executable (frozen) or this source file
# (normal run) so the database always lands in the same predictable
# place next to the app, not wherever Explorer happened to launch from.
if getattr(sys, "frozen", False):
    app_dir = Path(sys.executable).parent
else:
    app_dir = Path(__file__).parent.parent

DATABASE_URL = f"sqlite:///{app_dir / 'grants.db'}"

SQLITE_LOCK_TIMEOUT_SECONDS = 5.0

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": SQLITE_LOCK_TIMEOUT_SECONDS,
    },
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores FKs unless told otherwise
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one DB session per request, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
