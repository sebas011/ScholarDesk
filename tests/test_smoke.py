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
    assert '<div class="text-3xl font-bold text-navy-900">0</div>' in resp.text


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
    from app.services import grants as grant_service
    from app.models import Grant

    grant = Grant(
        scholar_id=1,
        program_applied="CHED Merit",
        date_started="June 2024",
        date_ended="May 2027",
        start_year=2024,
        end_year=2027,
    )
    assert grant_service.active_in_year(grant, 2024) is True
    assert grant_service.active_in_year(grant, 2026) is True  # the case that broke per-year sheets
    assert grant_service.active_in_year(grant, 2028) is False


def test_grant_with_no_start_year_excluded_from_year_filter(client):
    """A grant with only free-text dates and no start_year (e.g. entered
    before this field existed, or truly unknown) shouldn't crash the
    year filter - it just can't be placed in any year."""
    from app.services import grants as grant_service
    from app.models import Grant

    grant = Grant(
        scholar_id=1,
        program_applied="Legacy Grant",
        date_started="sometime in the early 2000s",
    )
    assert grant_service.active_in_year(grant, 2024) is False


def test_delete_scholar_cascades_to_assignments_and_grants(client):
    client.post("/scholars", data={"name": "Temp Scholar", "department": "CIT"})
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Test Grant", "date_started": "2025-01-01"},
    )

    dash = client.get("/")
    assert '<div class="text-3xl font-bold text-navy-900">1</div>' in dash.text

    del_resp = client.delete("/scholars/1")
    assert del_resp.status_code == 200

    dash_after = client.get("/")
    assert '<div class="text-3xl font-bold text-navy-900">0</div>' in dash_after.text


def test_delete_nonexistent_scholar_reports_error_not_silent_success(client):
    """Regression test: deleting an id that doesn't exist used to fall
    through to the same empty-panel response as a real delete, so the
    UI looked like it had succeeded even though nothing happened."""
    resp = client.delete("/scholars/999")
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()


def test_update_scholar_with_whitespace_only_name_shows_error_not_500(client):
    """Regression test: a name of only spaces satisfies the HTML `required`
    attribute (so the browser lets the form submit) but fails our own
    validation once .strip()'d - the service layer raises a plain
    ValueError for this, which the route's except clause didn't catch,
    causing an uncaught 500 instead of the intended inline error."""
    client.post("/scholars", data={"name": "Real Name", "department": "CCS"})
    resp = client.put("/scholars/1", data={"name": "   "})
    assert resp.status_code == 200
    assert "required" in resp.text.lower()


def test_duplicate_name_warns_but_does_not_block(client):
    client.post("/scholars", data={"name": "Ana Reyes", "department": "COED"})
    resp = client.post("/scholars", data={"name": "Ana Reyes", "department": "CAS"})
    assert resp.status_code == 200
    assert "already existed" in resp.text


def test_scholar_name_too_long_shows_error_not_silently_truncated(client):
    """SQLite doesn't enforce VARCHAR(n) column limits, so without an
    explicit check a name longer than the declared 200 chars would be
    silently accepted and stored in full rather than rejected."""
    resp = client.post("/scholars", data={"name": "A" * 201})
    assert resp.status_code == 200
    assert "too long" in resp.text.lower()


def test_absurd_age_shows_error_not_silently_accepted(client):
    resp = client.post("/scholars", data={"name": "Age Test Scholar", "age": "99999"})
    assert resp.status_code == 200
    assert "age must be between" in resp.text.lower()


def test_add_assignment_with_blank_department_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Assignment Test Scholar"})
    resp = client.post("/scholars/1/assignments", data={"department": "   "})
    assert resp.status_code == 200
    assert "required" in resp.text.lower()


def test_assignment_department_too_long_shows_error_not_silently_truncated(client):
    client.post("/scholars", data={"name": "Long Department Scholar"})
    resp = client.post("/scholars/1/assignments", data={"department": "D" * 101})
    assert resp.status_code == 200
    assert "too long" in resp.text.lower()


def test_update_assignment_with_blank_department_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Update Assignment Scholar", "department": "CCS"})
    resp = client.post("/assignments/1?scholar_id=1", data={"department": "   "})
    assert resp.status_code == 200
    assert "required" in resp.text.lower()


def test_delete_nonexistent_assignment_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Delete Assignment Scholar"})
    resp = client.delete("/assignments/999?scholar_id=1")
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()


def test_add_grant_with_blank_program_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Grant Test Scholar"})
    resp = client.post(
        "/scholars/1/grants",
        data={"program_applied": "   ", "start_year": "2024"},
    )
    assert resp.status_code == 200
    assert "required" in resp.text.lower()


def test_grant_program_applied_too_long_shows_error_not_silently_truncated(client):
    client.post("/scholars", data={"name": "Long Grant Scholar"})
    resp = client.post(
        "/scholars/1/grants",
        data={"program_applied": "P" * 301, "start_year": "2024"},
    )
    assert resp.status_code == 200
    assert "too long" in resp.text.lower()



def test_add_grant_with_invalid_status_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Grant Status Test Scholar"})
    resp = client.post(
        "/scholars/1/grants",
        data={
            "program_applied": "Test Grant",
            "status": "Not A Real Status",
            "start_year": "2024",
        },
    )
    assert resp.status_code == 200
    assert "invalid status" in resp.text.lower()


def test_update_grant_with_blank_program_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Update Grant Scholar"})
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Original Grant", "start_year": "2024"},
    )
    resp = client.post(
        "/grants/1?scholar_id=1", data={"program_applied": "   ", "status": "Active"}
    )
    assert resp.status_code == 200
    assert "required" in resp.text.lower()


def test_delete_nonexistent_grant_shows_error_not_500(client):
    client.post("/scholars", data={"name": "Delete Grant Scholar"})
    resp = client.delete("/grants/999?scholar_id=1")
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()


def test_dashboard_page_loads_with_data(client):
    client.post("/scholars", data={"name": "Dashboard Test Scholar", "department": "CAS"})
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Dashboard Test Scholar" in resp.text
    assert "CAS" in resp.text
