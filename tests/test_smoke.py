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

from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.main import on_unhandled_exception

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


def test_scholar_detail_page_with_grants_renders_without_context_forwarding_crash(client):
    """Regression test: build_detail_context() started returning three
    new keys (notes, activity_logs, grant_reviews) for the GMS/XRM
    features, but scholars.html's {% with %} block that forwards
    context into scholar_detail.html wasn't updated to pass them
    through - any scholar-with-grants page reached via the Directory
    table (?scholar_id=) crashed with UndefinedError: 'grant_reviews'
    is undefined."""
    client.post("/scholars", data={"name": "Context Forward Scholar", "department": "CCS"})
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Context Test Grant", "start_year": "2024"},
    )
    resp = client.get("/scholars", params={"scholar_id": 1})
    assert resp.status_code == 200
    assert "Context Test Grant" in resp.text
    assert "Grant Governance" in resp.text


def test_dashboard_htmx_partial_renders_without_dept_by_scholar_crash(client):
    """Regression test: dashboard_content.html (the htmx-swapped partial
    used for pagination/search) referenced dept_by_scholar, a variable
    dashboard_page() never provided - any htmx GET to /dashboard (e.g.
    clicking Next/Previous, or typing a search term) 500'd with
    UndefinedError. The full-page load (dashboard.html) used a
    different, working variable (enriched) and so never caught this."""
    client.post("/scholars", data={"name": "Dashboard Partial Scholar", "department": "CIT"})
    resp = client.get("/dashboard", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Dashboard Partial Scholar" in resp.text
    assert "CIT" in resp.text


def test_delete_nonexistent_note_shows_error_not_silent_success(client):
    """Regression test: delete_scholar_note only acted (db.delete + commit)
    inside `if note and note.scholar_id == scholar_id`, but returned the
    same 'Note deleted.' success notice unconditionally afterward - a
    missing note_id, or one belonging to a different scholar, silently
    did nothing while reporting success. Also confirms a real delete
    still works, so the fix doesn't just report errors for everything."""
    client.post("/scholars", data={"name": "Note Delete Scholar"})

    missing_resp = client.delete("/scholars/1/notes/999")
    assert missing_resp.status_code == 200
    assert "not found" in missing_resp.text.lower()

    client.post("/scholars/1/notes", data={"content": "A real note"})

    from app.models import ScholarNote

    db = TestSession()
    real_note = db.query(ScholarNote).filter_by(scholar_id=1).first()
    assert real_note is not None
    note_id = real_note.id
    db.close()

    real_delete_resp = client.delete(f"/scholars/1/notes/{note_id}")
    assert real_delete_resp.status_code == 200
    assert "note deleted" in real_delete_resp.text.lower()

    db = TestSession()
    assert db.get(ScholarNote, note_id) is None
    db.close()


def test_department_distribution_includes_grant_only_scholars_in_year_filter(client):
    """Regression test: department_distribution's year-filtered branch only
    counted scholars with a DEPARTMENT ASSIGNMENT active in that year,
    silently excluding scholars who are active that year purely via a
    grant (no assignment) - unlike the all-time branch, which already
    buckets any scholar with no assignment under 'Admin Staff'. Result:
    the home page's 'Active in <year>' stat card and the department
    breakdown table below it could show different totals, with no row
    explaining the gap."""
    from app.services import stats as stats_service

    client.post(
        "/scholars",
        data={"name": "Assignment Scholar", "department": "CCS", "date_started": "2024-01-01"},
    )
    client.post("/scholars", data={"name": "Grant Only Scholar"})
    client.post(
        "/scholars/2/grants",
        data={"program_applied": "Grant Only", "start_year": "2024"},
    )
    # Scholar 1: assignment dated into 2024. Scholar 2: no department
    # assignment at all - active in 2024 purely through the grant above.

    db = TestSession()
    headline = stats_service.total_scholars_active_in_year(db, 2024)
    dist = stats_service.department_distribution(db, year=2024)
    db.close()

    assert headline == 2
    assert sum(dist.values()) == headline
    assert dist.get("Admin Staff") == 1

def test_blank_name_on_new_scholar_page_renders_that_page(client):
    resp = client.post(
        "/scholars/new",
        data={
            "name": "",
            "age": "28",
            "previous_degree": "BS Computer Science",
        },
    )

    assert resp.status_code == 422
    assert "Add Scholar" in resp.text
    assert "Please fill in" in resp.text
    assert 'value="28"' in resp.text
    assert 'value="BS Computer Science"' in resp.text

def test_sqlite_lock_returns_retryable_response():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/scholars",
            "headers": [],
        }
    )
    error = OperationalError(
        "INSERT INTO scholars",
        {},
        Exception("database is locked"),
    )

    response = on_unhandled_exception(request, error)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert b"Database is busy. Please try again shortly." in response.body
