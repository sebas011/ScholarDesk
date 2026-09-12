import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import DepartmentAssignment, Grant, Scholar
from app.core.auth import require_authenticated_session


@pytest.fixture(scope="session")
def performance_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def performance_db(performance_engine):
    Session = sessionmaker(bind=performance_engine)
    db = Session()

    try:
        yield db
    finally:
        db.rollback()
        db.close()
        with performance_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def performance_client(performance_db):
    def override_get_db():
        yield performance_db

    def override_authenticated_session():
        return "performance-test-user"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_authenticated_session] = override_authenticated_session

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_authenticated_session, None)


@pytest.fixture
def query_counter(performance_engine):
    state = {"count": 0, "total_seconds": 0.0}

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        state["started"] = time.perf_counter()

    def after_execute(conn, cursor, statement, parameters, context, executemany):
        state["count"] += 1
        state["total_seconds"] += time.perf_counter() - state["started"]

    event.listen(performance_engine, "before_cursor_execute", before_execute)
    event.listen(performance_engine, "after_cursor_execute", after_execute)

    try:
        yield state
    finally:
        event.remove(performance_engine, "before_cursor_execute", before_execute)
        event.remove(performance_engine, "after_cursor_execute", after_execute)


@pytest.fixture
def populate_scholars(performance_db):
    def populate(count: int):
        scholars = [
            Scholar(
                name=f"Scholar {i:05d}",
                age=25 + (i % 20),
                previous_degree="Bachelor's Degree",
                missing_requirements=(i % 10 == 0),
            )
            for i in range(1, count + 1)
        ]

        performance_db.add_all(scholars)
        performance_db.flush()

        scholar_ids = [s.id for s in scholars]

        assignments = [
            DepartmentAssignment(
                scholar_id=scholar_id,
                department=["CCS", "COED", "CAS", "CIT"][i % 4],
                rank=["Instructor I", "Instructor II", "Assistant Professor"][i % 3],
            )
            for i, scholar_id in enumerate(scholar_ids)
        ]

        grants = [
            Grant(
                scholar_id=scholar_id,
                program_applied=f"Grant Program {(i % 10) + 1}",
                type_of_grant="Regular",
                start_year=2024 + (i % 3),
                end_year=2027 + (i % 3),
                status=["Active", "Completed", "Pending"][i % 3],
            )
            for i, scholar_id in enumerate(scholar_ids)
        ]

        performance_db.bulk_save_objects(assignments)
        performance_db.bulk_save_objects(grants)
        performance_db.commit()

    return populate
