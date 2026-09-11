"""Separate SQLite database wiring for payroll data."""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


if getattr(sys, "frozen", False):
    app_dir = Path(sys.executable).parent
else:
    app_dir = Path(__file__).parent.parent

PAYROLL_DATABASE_URL = os.environ.get(
    "PAYROLL_DATABASE_URL",
    f"sqlite:///{app_dir / 'payroll.db'}",
)
SQLITE_LOCK_TIMEOUT_SECONDS = 5.0

_payroll_engine_options: dict[str, object] = {
    "connect_args": {
        "check_same_thread": False,
        "timeout": SQLITE_LOCK_TIMEOUT_SECONDS,
    },
}
if PAYROLL_DATABASE_URL == "sqlite://":
    _payroll_engine_options["poolclass"] = StaticPool

payroll_engine = create_engine(
    PAYROLL_DATABASE_URL,
    **_payroll_engine_options,
)


@event.listens_for(payroll_engine, "connect")
def _set_payroll_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


PayrollSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=payroll_engine,
)

PayrollBase = declarative_base()


def get_payroll_db():
    """FastAPI dependency for one payroll DB session per request."""
    db = PayrollSessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_payroll_database() -> None:
    """Create payroll tables without touching the grants database."""
    from app import payroll_models  # noqa: F401

    PayrollBase.metadata.create_all(bind=payroll_engine)
