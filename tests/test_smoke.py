"""
Automated version of the manual curl smoke test run during development.
Uses an isolated in-memory SQLite DB per test run (via dependency
override) so tests never touch grants.db.

Run with: pytest
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db

# StaticPool keeps a single connection alive for the whole test run -
# without it, every new session opens a *new* in-memory DB (SQLite's
# :memory: is per-connection), and tables "disappear" between requests.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_home_starts_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<div class="num">0</div>' in resp.text


def test_empty_year_param_does_not_422(client):
    """Regression test: the year-filter dropdown's 'All Years' option
    submits year='' rather than omitting the param entirely. All three
    routes that accept `year` used to declare it as int | None, which
    FastAPI rejects with a 422 the moment it sees an empty string -
    instead of treating it as 'no filter applied'."""
    for url in ("/", "/scholars", "/scholars/list"):
        resp = client.get(url, params={"year": ""})
        assert resp.status_code == 200, f"{url}?year= returned {resp.status_code}, expected 200"


def test_create_scholar_with_assignment(client):
    resp = client.post(
        "/scholars",
        data={"name": "Juan Dela Cruz", "age": "27", "department": "CCS", "rank": "Instructor I"},
    )
    assert resp.status_code == 200
    assert "Scholar added" in resp.text
    assert "CCS" in resp.text


def test_blank_name_rejected_with_html_error_not_json(client):
    resp = client.post("/scholars", data={"name": "", "department": "CCS"})
    assert resp.status_code == 422
    assert "text/html" in resp.headers["content-type"]
    assert "error" in resp.text.lower()


def test_multi_year_grant_active_across_its_full_span(client):
    from datetime import date
    from app.services import grants as grant_service
    from app.models import Grant

    grant = Grant(
        scholar_id=1,
        program_applied="CHED Merit",
        date_started=date(2024, 6, 1),
        date_ended=date(2027, 5, 31),
    )
    assert grant_service.active_in_year(grant, 2024) is True
    assert grant_service.active_in_year(grant, 2026) is True  # the case that broke per-year sheets
    assert grant_service.active_in_year(grant, 2028) is False


def test_delete_scholar_cascades_to_assignments_and_grants(client):
    client.post("/scholars", data={"name": "Temp Scholar", "department": "CIT"})
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Test Grant", "date_started": "2025-01-01"},
    )

    dash = client.get("/")
    assert '<div class="num">1</div>' in dash.text

    del_resp = client.delete("/scholars/1")
    assert del_resp.status_code == 200

    dash_after = client.get("/")
    assert '<div class="num">0</div>' in dash_after.text


def test_delete_nonexistent_scholar_reports_error_not_silent_success(client):
    """Regression test: deleting an id that doesn't exist used to fall
    through to the same empty-panel response as a real delete, so the
    UI looked like it had succeeded even though nothing happened."""
    resp = client.delete("/scholars/999")
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()


def test_duplicate_name_warns_but_does_not_block(client):
    client.post("/scholars", data={"name": "Ana Reyes", "department": "COED"})
    resp = client.post("/scholars", data={"name": "Ana Reyes", "department": "CAS"})
    assert resp.status_code == 200
    assert "already existed" in resp.text
