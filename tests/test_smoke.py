"""
Automated version of the manual curl smoke test run during development.
Uses an isolated in-memory SQLite DB per test run (via dependency
override) so tests never touch grants.db.

Run with: pytest
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from app.core import auth
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import date
from app.utils.dates import parse_date, range_active_in_year
from app.core import network
from app.database import _set_sqlite_pragmas
from app.services import grants as grant_service
from app.models import DepartmentAssignment, Grant, GrantReview, Scholar
from app.services import scholars as scholar_service
from app.services.scholars import ScholarNotFoundError
from app.services import departments as dept_service
from app.services import notes as note_service
from app.services.notes import InvalidScholarError
from app.services import stats as stats_service
from app.main import app
from unittest.mock import Mock
from app.database import Base, get_db
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from unittest.mock import patch

import json
import logging

from app.core.logging import JsonFormatter
from app.core.auth import verify_credentials

from app.main import on_unhandled_exception

# StaticPool keeps a single connection alive for the whole test run -

# StaticPool keeps a single connection alive for the whole test run -
# without it, every new session opens a *new* in-memory DB (SQLite's
# :memory: is per-connection), and tables "disappear" between requests.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine)

@pytest.fixture
def db_session():
    db = TestSession()
    try:
        yield db
    finally:
        db.rollback()
        db.close()

def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def override_verify_credentials():
    """Bypass the Basic Auth gate entirely for tests - same reasoning
    as overriding get_db above: tests must never depend on, or write
    to, the real auth.txt file next to the real grants.db. Without
    this, running pytest would create a stray auth.txt in the repo
    root, and tests would silently start failing on any machine where
    the real password had been changed from the default."""
    return "test-user"


app.dependency_overrides[verify_credentials] = override_verify_credentials


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_home_starts_empty(client):
    resp = client.get("/home")
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

    dash = client.get("/home")
    assert '<div class="text-3xl font-bold text-navy-900">1</div>' in dash.text

    del_resp = client.delete("/scholars/1")
    assert del_resp.status_code == 200

    dash_after = client.get("/home")
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


def test_parse_date_whitespace_returns_none():
    assert parse_date("   ") is None


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

    with patch("app.main.logger.warning") as warning:
        response = on_unhandled_exception(request, error)

    warning.assert_called_once_with(
    "SQLite lock timeout on %s %s",
    "POST",
    "/scholars",
    exc_info=(type(error), error, error.__traceback__),
)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert b"Database is busy. Please try again shortly." in response.body

def test_json_formatter_emits_parseable_utc_log_record():
    record = logging.LogRecord(
        name="grant_tracker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Scholar %s updated",
        args=(123,),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["timestamp"].endswith("Z")
    assert payload["level"] == "INFO"
    assert payload["logger"] == "grant_tracker"
    assert payload["message"] == "Scholar 123 updated"

def test_auth_accepts_credentials_from_file(tmp_path, monkeypatch):
    credentials_file = tmp_path / "auth.txt"
    credentials_file.write_text("username=test-user\npassword=test-pass\n", encoding="utf-8")
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = HTTPBasicCredentials(username="test-user", password="test-pass")

    assert auth.verify_credentials(credentials) == "test-user"


def test_auth_accepts_valid_credentials(tmp_path, monkeypatch):
    credentials_file = tmp_path / "auth.txt"
    credentials_file.write_text(
        "username=test-user\npassword=test-pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = HTTPBasicCredentials(username="test-user", password="test-pass")

    assert auth.verify_credentials(credentials) == "test-user"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("wrong-user", "test-pass"),
        ("test-user", "wrong-pass"),
    ],
)
def test_auth_rejects_invalid_credentials(tmp_path, monkeypatch, username, password):
    credentials_file = tmp_path / "auth.txt"
    credentials_file.write_text(
        "username=test-user\npassword=test-pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = HTTPBasicCredentials(username=username, password=password)

    with pytest.raises(HTTPException) as error:
        auth.verify_credentials(credentials)

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Basic"}


def test_auth_creates_default_credentials_file(tmp_path, monkeypatch):
    credentials_file = tmp_path / "auth.txt"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    assert auth.load_credentials() == ("admin", "changeme")
    assert credentials_file.exists()

def test_parse_date_handles_valid_blank_and_invalid_values():
    assert parse_date("2025-01-01") == date(2025, 1, 1)
    assert parse_date(" 2025-01-01 ") == date(2025, 1, 1)
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("not-a-date") is None


@pytest.mark.parametrize(
    ("start", "end", "year", "expected"),
    [
        (None, None, 2025, False),
        (date(2026, 1, 1), None, 2025, False),
        (date(2025, 1, 1), None, 2026, True),
        (date(2025, 1, 1), date(2025, 12, 31), 2026, False),
        (date(2025, 1, 1), date(2026, 12, 31), 2026, True),
    ],
)
def test_range_active_in_year(start, end, year, expected):
    assert range_active_in_year(start, end, year) is expected

def test_allow_lan_creates_safe_default_config(tmp_path, monkeypatch):
    config_file = tmp_path / "network.txt"
    monkeypatch.setattr(network, "NETWORK_CONFIG_FILE", config_file)

    assert network.allow_lan() is False
    assert config_file.exists()


def test_allow_lan_accepts_true(tmp_path, monkeypatch):
    config_file = tmp_path / "network.txt"
    config_file.write_text("allow_lan=true\n", encoding="utf-8")
    monkeypatch.setattr(network, "NETWORK_CONFIG_FILE", config_file)

    assert network.allow_lan() is True


@pytest.mark.parametrize("value", ["false", "yes", "1", "unexpected"])
def test_allow_lan_rejects_non_true_values(tmp_path, monkeypatch, value):
    config_file = tmp_path / "network.txt"
    config_file.write_text(f"allow_lan={value}\n", encoding="utf-8")
    monkeypatch.setattr(network, "NETWORK_CONFIG_FILE", config_file)

    assert network.allow_lan() is False


def test_sqlite_pragma_hook_enables_foreign_keys():
    with engine.raw_connection() as connection:
        cursor = connection.cursor()
        _set_sqlite_pragmas(connection, None)
        cursor.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()
        assert result is not None
        assert result[0] == 1
        cursor.close()
        connection.close()

def test_get_db_closes_session(monkeypatch):
    created = []

    class TrackingSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def factory():
        session = TrackingSession()
        created.append(session)
        return session

    monkeypatch.setattr("app.database.SessionLocal", factory)

    database = get_db()
    session = next(database)
    database.close()

    assert getattr(session, "closed", False) is True

def test_create_grant_rejects_invalid_status(db_session):
    scholar = Scholar(name="Grant Validation Scholar")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(ValueError, match="Invalid status"):
        grant_service.create_grant(
            db_session, scholar.id, "Test Grant", None, None, None, None,
            None, None, None, "Unknown", None,
        )


def test_create_grant_rejects_overlong_program(db_session):
    scholar = Scholar(name="Grant Length Scholar")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(ValueError, match="Program applied is too long"):
        grant_service.create_grant(
            db_session, scholar.id, "x" * 301, None, None, None, None,
            None, None, None, "Active", None,
        )


def test_update_and_delete_grant(db_session):
    scholar = Scholar(name="Grant Update Scholar")
    db_session.add(scholar)
    db_session.commit()

    grant = grant_service.create_grant(
        db_session, scholar.id, "Original Grant", None, None, None, None,
        2024, None, None, "Active", None,
    )
    db_session.commit()

    updated = grant_service.update_grant(
        db_session, grant.id, " Updated Grant ", None, None, None, None,
        2025, 2026, None, "Completed", " Updated remarks ",
    )
    assert updated.program_applied == "Updated Grant"
    assert updated.start_year == 2025
    assert updated.end_year == 2026
    assert updated.status == "Completed"
    assert updated.remarks == "Updated remarks"

    grant_service.delete_grant(db_session, grant.id)
    db_session.commit()
    assert db_session.get(Grant, grant.id) is None


def test_review_sets_decided_at_for_non_pending_decision(db_session):
    scholar = Scholar(name="Grant Review Date Scholar")
    db_session.add(scholar)
    db_session.commit()

    grant = grant_service.create_grant(
        db_session, scholar.id, "Review Grant", None, None, None, None,
        None, None, None, "Active", None,
    )
    db_session.commit()

    review = grant_service.add_review(
        db_session, grant.id, "approved", None, None
    )

    assert review.decided_at is not None

@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("type_of_grant", "x" * 151, "Type of grant is too long"),
        ("delivering_hei", "x" * 201, "Delivering HEI is too long"),
        ("date_started", "x" * 101, "Started is too long"),
        ("date_ended", "x" * 101, "Ended is too long"),
        ("extension", "x" * 201, "Extension is too long"),
    ],
)
def test_create_grant_rejects_overlong_optional_fields(
    db_session, field, value, message
):
    scholar = Scholar(name="Grant Field Length Scholar")
    db_session.add(scholar)
    db_session.commit()

    values = {
        "type_of_grant": None,
        "delivering_hei": None,
        "date_started": None,
        "date_ended": None,
        "extension": None,
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        grant_service.create_grant(
            db_session,
            scholar.id,
            "Test Grant",
            values["type_of_grant"],
            values["delivering_hei"],
            values["date_started"],
            values["date_ended"],
            None,
            None,
            values["extension"],
            "Active",
            None,
        )


def test_update_grant_rejects_missing_grant(db_session):
    with pytest.raises(ValueError, match="Grant 999 not found"):
        grant_service.update_grant(
            db_session, 999, "Test Grant", None, None, None, None,
            None, None, None, "Active", None,
        )


def test_delete_grant_rejects_missing_grant(db_session):
    with pytest.raises(ValueError, match="Grant 999 not found"):
        grant_service.delete_grant(db_session, 999)

def test_active_in_year_rejects_after_end_year():
    grant = Grant(start_year=2024, end_year=2025)
    assert grant_service.active_in_year(grant, 2026) is False


def test_create_grant_rejects_missing_scholar(db_session):
    with pytest.raises(ValueError, match="Scholar 999 not found"):
        grant_service.create_grant(
            db_session, 999, "Test Grant", None, None, None, None,
            None, None, None, "Active", None,
        )


def test_update_grant_rejects_invalid_status(db_session):
    scholar = Scholar(name="Update Status Scholar")
    db_session.add(scholar)
    db_session.commit()

    grant = grant_service.create_grant(
        db_session, scholar.id, "Test Grant", None, None, None, None,
        None, None, None, "Active", None,
    )

    with pytest.raises(ValueError, match="Invalid status"):
        grant_service.update_grant(
            db_session, grant.id, "Test Grant", None, None, None, None,
            None, None, None, "Unknown", None,
        )


def test_active_in_year_rejects_before_start():
    grant = Grant(start_year=2025, end_year=None)

    assert grant_service.active_in_year(grant, 2024) is False


def test_add_review_rejects_missing_grant(db_session):
    with pytest.raises(ValueError, match="Grant not found"):
        grant_service.add_review(
            db_session, 999, "approved", None, None
        )


def test_add_review_rejects_invalid_decision(db_session):
    scholar = Scholar(name="Invalid Review Scholar")
    db_session.add(scholar)
    db_session.commit()

    grant = grant_service.create_grant(
        db_session,
        scholar.id,
        "Review Grant",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "Active",
        None,
    )
    db_session.commit()

    with pytest.raises(ValueError, match="Invalid review decision"):
        grant_service.add_review(
            db_session, grant.id, "invalid", None, None
        )


def test_create_scholar_rejects_blank_name(db_session):
    with pytest.raises(ValueError, match="Scholar name is required"):
        scholar_service.create_scholar(db_session, "   ", None, None, False)


def test_create_scholar_rejects_invalid_age(db_session):
    with pytest.raises(ValueError, match="Age must be between"):
        scholar_service.create_scholar(db_session, "Age Test", 101, None, False)


def test_update_scholar_rejects_missing_scholar(db_session):
    with pytest.raises(ScholarNotFoundError, match="Scholar not found"):
        scholar_service.update_scholar(db_session, 999, "Updated", None, None, False)


def test_delete_scholar_rejects_missing_scholar(db_session):
    with pytest.raises(ScholarNotFoundError, match="Scholar not found"):
        scholar_service.delete_scholar(db_session, 999)


def test_list_scholars_search_and_limit(db_session):
    db_session.add_all([
        Scholar(name="Alice Researcher"),
        Scholar(name="Bob Researcher"),
    ])
    db_session.commit()

    results, total = scholar_service.list_scholars(
        db_session, search="alice", limit=1
    )

    assert total == 1
    assert [scholar.name for scholar in results] == ["Alice Researcher"]


def test_list_scholars_filters_by_grant_year(db_session):
    scholar = Scholar(name="Grant Year Scholar")
    other = Scholar(name="Other Year Scholar")
    db_session.add_all([scholar, other])
    db_session.commit()

    db_session.add(
        Grant(
            scholar_id=scholar.id,
            program_applied="Year Grant",
            start_year=2025,
            end_year=None,
            status="Active",
        )
    )
    db_session.commit()

    results, total = scholar_service.list_scholars(db_session, year=2025)

    assert total == 1
    assert results[0].id == scholar.id


def test_get_full_scholar_data_groups_related_records(db_session):
    scholar = Scholar(name="Dashboard Scholar")
    db_session.add(scholar)
    db_session.commit()

    db_session.add(
        Grant(
            scholar_id=scholar.id,
            program_applied="Dashboard Grant",
            start_year=2025,
            status="Active",
        )
    )
    db_session.commit()

    rows = scholar_service.get_full_scholar_data(db_session)

    row = next(item for item in rows if item["scholar"].id == scholar.id)
    assert len(row["grants"]) == 1
    assert row["grants"][0].program_applied == "Dashboard Grant"
    assert row["assignments"] == []


def test_build_detail_context_includes_latest_grant_review(db_session):
    scholar = Scholar(name="Context Review Scholar")
    db_session.add(scholar)
    db_session.commit()

    grant = Grant(
        scholar_id=scholar.id,
        program_applied="Context Grant",
        status="Active",
    )
    db_session.add(grant)
    db_session.commit()

    review = GrantReview(
        grant_id=grant.id,
        decision="approved",
        reviewer="Reviewer",
        comments="Approved",
    )
    db_session.add(review)
    db_session.commit()

    context = scholar_service.build_detail_context(db_session, scholar)

    assert context["grant_reviews"][grant.id].id == review.id
    assert context["grant_reviews"][grant.id].decision == "approved"


def test_get_full_scholar_data_groups_assignments(db_session):
    scholar = Scholar(name="Assignment Group Scholar")
    db_session.add(scholar)
    db_session.commit()

    assignment = DepartmentAssignment(
        scholar_id=scholar.id,
        department="CIT",
        date_started=date(2025, 1, 1),
    )
    db_session.add(assignment)
    db_session.commit()

    rows = scholar_service.get_full_scholar_data(db_session)

    row = next(item for item in rows if item["scholar"].id == scholar.id)
    assert [item.id for item in row["assignments"]] == [assignment.id]


def test_create_scholar_rejects_long_previous_degree(db_session):
    with pytest.raises(ValueError, match="Previous degree is too long"):
        scholar_service.create_scholar(
            db_session,
            "Long Degree Scholar",
            None,
            "x" * 301,
            False,
        )


def test_update_scholar_rejects_blank_name(db_session):
    scholar = scholar_service.create_scholar(
        db_session,
        "Update Validation Scholar",
        None,
        None,
        False,
    )

    with pytest.raises(ValueError, match="Scholar name is required"):
        scholar_service.update_scholar(
            db_session, scholar.id, "   ", None, None, False
        )


def test_update_scholar_rejects_invalid_age(db_session):
    scholar = scholar_service.create_scholar(
        db_session,
        "Update Age Scholar",
        None,
        None,
        False,
    )

    with pytest.raises(ValueError, match="Age must be between"):
        scholar_service.update_scholar(
            db_session, scholar.id, "Updated", 101, None, False
        )


def test_update_scholar_rejects_long_previous_degree(db_session):
    scholar = scholar_service.create_scholar(
        db_session,
        "Update Degree Scholar",
        None,
        None,
        False,
    )

    with pytest.raises(ValueError, match="Previous degree is too long"):
        scholar_service.update_scholar(
            db_session, scholar.id, "Updated", None, "x" * 301, False
        )


def test_create_assignment_rejects_missing_scholar(db_session):
    with pytest.raises(ValueError, match="Scholar 999 not found"):
        dept_service.create_assignment(
            db_session, 999, "CIT", None, None, None, None
        )


def test_create_assignment_rejects_blank_department(db_session):
    scholar = Scholar(name="Assignment Validation Scholar")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(ValueError, match="Department is required"):
        dept_service.create_assignment(
            db_session, scholar.id, "   ", None, None, None, None
        )


def test_update_assignment_and_delete_assignment(db_session):
    scholar = Scholar(name="Assignment Update Scholar")
    db_session.add(scholar)
    db_session.commit()

    assignment = dept_service.create_assignment(
        db_session,
        scholar.id,
        "CIT",
        "Instructor",
        "Permanent",
        date(2024, 1, 1),
        None,
    )
    db_session.commit()

    updated = dept_service.update_assignment(
        db_session,
        assignment.id,
        "CCS",
        "Professor",
        "Tenured",
        date(2025, 1, 1),
        date(2026, 12, 31),
    )

    assert updated.department == "CCS"
    assert updated.rank == "Professor"
    assert updated.date_started == date(2025, 1, 1)

    dept_service.delete_assignment(db_session, assignment.id)
    db_session.commit()

    assert db_session.get(DepartmentAssignment, assignment.id) is None


def test_assignment_active_in_year_uses_shared_range_rule():
    assignment = DepartmentAssignment(
        date_started=date(2024, 1, 1),
        date_ended=date(2025, 12, 31),
    )

    assert dept_service.active_in_year(assignment, 2024) is True
    assert dept_service.active_in_year(assignment, 2026) is False


def test_create_assignment_rejects_long_rank_and_tenure(db_session):
    scholar = Scholar(name="Assignment Length Scholar")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(ValueError, match="Rank is too long"):
        dept_service.create_assignment(
            db_session, scholar.id, "CIT", "x" * 101, None, None, None
        )

    with pytest.raises(ValueError, match="Tenure is too long"):
        dept_service.create_assignment(
            db_session, scholar.id, "CIT", None, "x" * 101, None, None
        )


def test_get_primary_assignment_returns_earliest(db_session):
    scholar = Scholar(name="Primary Assignment Scholar")
    db_session.add(scholar)
    db_session.commit()

    first = dept_service.create_assignment(
        db_session, scholar.id, "First", None, None, None, None
    )
    dept_service.create_assignment(
        db_session, scholar.id, "Second", None, None, None, None
    )
    db_session.commit()

    primary_assignment = dept_service.get_primary_assignment(db_session, scholar.id)
    assert primary_assignment is not None
    assert primary_assignment.id == first.id


def test_update_assignment_rejects_missing_assignment(db_session):
    with pytest.raises(ValueError, match="Assignment 999 not found"):
        dept_service.update_assignment(
            db_session, 999, "CIT", None, None, None, None
        )


def test_add_note_rejects_missing_scholar(db_session):
    with pytest.raises(ScholarNotFoundError, match="Scholar not found"):
        note_service.add_note(db_session, 999, "Test note")


def test_add_note_rejects_overlong_content(db_session):
    scholar = Scholar(name="Long Note Scholar")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(InvalidScholarError, match="Note is too long"):
        note_service.add_note(db_session, scholar.id, "x" * 2001)


def test_add_note_rejects_empty_content_in_service(db_session):
    scholar = Scholar(name="Empty Note Scholar")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(InvalidScholarError, match="Note cannot be empty"):
        note_service.add_note(db_session, scholar.id, "   ")


def test_create_scholar_reraises_database_error(db_session, monkeypatch):
    def fail_flush():
        raise RuntimeError("flush failed")

    monkeypatch.setattr(db_session, "flush", fail_flush)

    with pytest.raises(RuntimeError, match="flush failed"):
        scholar_service.create_scholar(
            db_session,
            "Flush Failure Scholar",
            None,
            None,
            False,
        )


def test_update_scholar_rejects_name_that_is_too_long(db_session):
    scholar = Scholar(name="Update Target")
    db_session.add(scholar)
    db_session.commit()

    with pytest.raises(ValueError, match="Scholar name is too long"):
        scholar_service.update_scholar(
            db_session,
            scholar.id,
            "N" * (scholar_service.NAME_MAX_LENGTH + 1),
            None,
            None,
            False,
        )


def test_update_scholar_reraises_unexpected_error(db_session, monkeypatch):
    scholar = Scholar(name="Update Error Scholar")
    db_session.add(scholar)
    db_session.commit()

    def fail_log(*args, **kwargs):
        raise RuntimeError("update log failed")

    monkeypatch.setattr(scholar_service.logger, "info", fail_log)

    with pytest.raises(RuntimeError, match="update log failed"):
        scholar_service.update_scholar(
            db_session,
            scholar.id,
            "Updated Name",
            None,
            None,
            False,
        )


def test_delete_scholar_reraises_unexpected_error(db_session, monkeypatch):
    scholar = Scholar(name="Delete Error Scholar")
    db_session.add(scholar)
    db_session.commit()

    def fail_log(*args, **kwargs):
        raise RuntimeError("delete log failed")

    monkeypatch.setattr(scholar_service.logger, "info", fail_log)

    with pytest.raises(RuntimeError, match="delete log failed"):
        scholar_service.delete_scholar(db_session, scholar.id)


def test_update_scholar_returns_updated_scholar(db_session):
    scholar = Scholar(name="Original Name")
    db_session.add(scholar)
    db_session.commit()

    updated = scholar_service.update_scholar(
        db_session,
        scholar.id,
        "Updated Name",
        35,
        "Master's Degree",
        True,
    )

    assert updated is scholar
    assert updated.name == "Updated Name"
    assert updated.age == 35
    assert updated.previous_degree == "Master's Degree"
    assert updated.missing_requirements is True


def test_total_grants_and_active_grants_support_year_filter(db_session):
    scholar = Scholar(name="Grant Scholar")
    db_session.add(scholar)
    db_session.commit()

    grant = Grant(
    scholar_id=scholar.id,
    program_applied="Test Program",
    status="Active",
    start_year=2024,
    end_year=2024,
    )
    db_session.add(grant)
    db_session.commit()

    assert stats_service.total_grants(db_session, year=2024) == 1
    assert stats_service.active_grants_count(db_session, year=2024) == 1
    assert stats_service.total_grants(db_session, year=2023) == 0


def test_department_distribution_buckets_unknown_department(db_session):
    scholar = Scholar(name="Unknown Department Scholar")
    db_session.add(scholar)
    db_session.commit()

    db_session.add(
        DepartmentAssignment(
            scholar_id=scholar.id,
            department="Unlisted Department",
        )
    )
    db_session.commit()

    distribution = stats_service.department_distribution(db_session)
    assert distribution[stats_service.OTHER_LABEL] == 1


def test_add_assignment_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Assignment Route Scholar", "department": "CCS"},
    )

    response = client.post(
        "/scholars/1/assignments",
        data={
            "department": "CAS",
            "rank": "Instructor",
            "tenure": "Permanent",
            "date_started": "2024-01-01",
            "date_ended": "",
        },
    )

    assert response.status_code == 200
    assert "Assignment added." in response.text


def test_update_assignment_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Edit Assignment Scholar", "department": "CCS"},
    )

    response = client.post(
        "/assignments/1?scholar_id=1",
        data={
            "department": "CAS",
            "rank": "Associate Professor",
            "tenure": "Permanent",
            "date_started": "2024-01-01",
            "date_ended": "",
        },
    )

    assert response.status_code == 200
    assert "Assignment updated." in response.text


def test_delete_assignment_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Delete Assignment Scholar", "department": "CCS"},
    )

    response = client.delete("/assignments/1?scholar_id=1")

    assert response.status_code == 200
    assert "Assignment deleted." in response.text


def test_edit_grant_form_returns_edit_partial(client):
    client.post(
        "/scholars",
        data={"name": "Edit Grant Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Test Grant"},
    )

    response = client.get("/grants/1/edit?scholar_id=1")

    assert response.status_code == 200
    assert "Test Grant" in response.text


def test_update_grant_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Update Grant Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Original Grant"},
    )

    response = client.post(
        "/grants/1?scholar_id=1",
        data={"program_applied": "Updated Grant"},
    )

    assert response.status_code == 200
    assert "Grant updated." in response.text


def test_delete_grant_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Delete Grant Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Grant To Delete"},
    )

    response = client.delete("/grants/1?scholar_id=1")

    assert response.status_code == 200
    assert "Grant deleted." in response.text


def test_add_scholar_note_missing_scholar_shows_error(client):
    response = client.post(
        "/scholars/999/notes",
        data={"content": "Note for missing scholar"},
    )

    assert response.status_code == 200
    assert "Scholar not found." in response.text


def test_add_scholar_note_unexpected_error_shows_generic_error(client, monkeypatch):
    client.post(
        "/scholars",
        data={"name": "Note Error Scholar", "department": "CCS"},
    )

    def fail_add_note(*args, **kwargs):
        raise RuntimeError("unexpected note failure")

    monkeypatch.setattr(note_service, "add_note", fail_add_note)

    response = client.post(
        "/scholars/1/notes",
        data={"content": "Test note"},
    )

    assert response.status_code == 200
    assert "Could not add note - scholar may not exist." in response.text


def test_add_grant_review_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Review Route Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Review Grant"},
    )

    response = client.post(
        "/grants/1/reviews?scholar_id=1",
        data={
            "decision": "approved",
            "reviewer": "Reviewer One",
            "comments": "Looks good.",
        },
    )

    assert response.status_code == 200
    assert "Review recorded." in response.text


def test_add_grant_review_unexpected_error_shows_generic_error(client, monkeypatch):
    client.post(
        "/scholars",
        data={"name": "Review Error Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Review Error Grant"},
    )

    def fail_add_review(*args, **kwargs):
        raise RuntimeError("unexpected review failure")

    monkeypatch.setattr(grant_service, "add_review", fail_add_review)

    response = client.post(
        "/grants/1/reviews?scholar_id=1",
        data={
            "decision": "approved",
            "reviewer": "Reviewer One",
            "comments": "Test failure path.",
        },
    )

    assert response.status_code == 200
    assert "Could not record review." in response.text


def test_add_grant_review_invalid_decision_shows_error(client):
    client.post(
        "/scholars",
        data={"name": "Invalid Review Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={"program_applied": "Invalid Review Grant"},
    )

    response = client.post(
        "/grants/1/reviews?scholar_id=1",
        data={
            "decision": "invalid",
            "reviewer": "Reviewer One",
            "comments": "Invalid decision test.",
        },
    )

    assert response.status_code == 200
    assert "Invalid review decision: invalid" in response.text


def test_edit_assignment_form_returns_edit_partial(client):
    client.post(
        "/scholars",
        data={"name": "Edit Assignment Form Scholar", "department": "CCS"},
    )

    response = client.get("/assignments/1/edit?scholar_id=1")

    assert response.status_code == 200
    assert "CCS" in response.text


def test_dashboard_invalid_year_falls_back_to_all_time(client):
    response = client.get("/dashboard?year=not-a-year")

    assert response.status_code == 200
    assert "Invalid year" not in response.text


def test_home_with_valid_year_uses_year_filtered_stats(client):
    response = client.get("/home?year=2024")

    assert response.status_code == 200
    assert "Active in 2024" in response.text


def test_dashboard_enriches_scholar_with_latest_grant_status(client):
    client.post(
        "/scholars",
        data={"name": "Grant Status Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={
            "program_applied": "Status Grant",
            "status": "Active",
        },
    )

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Active" in response.text


def test_new_scholar_form_htmx_returns_partial(client):
    response = client.get(
        "/scholars/new",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Add Scholar" in response.text


def test_new_scholar_form_normal_request_returns_full_page(client):
    response = client.get("/scholars/new")

    assert response.status_code == 200
    assert "<html" in response.text
    assert "Add Scholar" in response.text


def test_create_scholar_page_success_redirects_to_profile(client):
    response = client.post(
        "/scholars/new",
        data={
            "name": "Dedicated Create Scholar",
            "age": "30",
            "previous_degree": "Master's Degree",
            "department": "CCS",
            "rank": "Instructor",
            "tenure": "Permanent",
            "date_started": "2024-01-01",
            "date_ended": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/scholars/1"


def test_create_scholar_page_validation_error_rerenders_form(client):
    response = client.post(
        "/scholars/new",
        data={
            "name": "   ",
            "age": "",
            "previous_degree": "",
            "department": "",
            "rank": "",
            "tenure": "",
            "date_started": "",
            "date_ended": "",
        }
    )

    assert response.status_code == 400
    assert "Scholar name is required." in response.text


def test_scholar_detail_normal_request_returns_profile(client):
    client.post(
        "/scholars",
        data={"name": "Profile Scholar", "department": "CCS"},
    )

    response = client.get("/scholars/1")

    assert response.status_code == 200
    assert "<html" in response.text
    assert "Profile Scholar" in response.text


def test_scholar_detail_htmx_missing_scholar_returns_partial(client):
    response = client.get(
        "/scholars/999",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Scholar not found." in response.text


def test_update_scholar_route_success(client):
    client.post(
        "/scholars",
        data={"name": "Original Scholar", "department": "CCS"},
    )

    response = client.put(
        "/scholars/1",
        data={
            "name": "Updated Scholar",
            "age": "35",
            "previous_degree": "Master's Degree",
        },
    )

    assert response.status_code == 200
    assert "Scholar updated." in response.text
    assert "Updated Scholar" in response.text
    assert response.headers["HX-Trigger"] == "scholar-changed"


def test_dashboard_export_returns_csv_for_matching_grant(client):
    client.post(
        "/scholars",
        data={"name": "Export Scholar", "department": "CCS"},
    )
    client.post(
        "/scholars/1/grants",
        data={
            "program_applied": "Export Grant",
            "status": "Active",
            "start_year": "2024",
            "end_year": "2024",
        },
    )

    response = client.get("/dashboard/export?q=Export&year=2024")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    assert "Export Scholar" in response.text
    assert "Export Grant" in response.text


def test_using_default_password_reflects_auth_file(tmp_path, monkeypatch):
    credentials_file = tmp_path / "auth.txt"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials_file.write_text(
        "username=admin\npassword=changeme\n",
        encoding="utf-8",
    )
    assert auth.using_default_password() is True

    credentials_file.write_text(
        "username=admin\npassword=changed-password\n",
        encoding="utf-8",
    )
    assert auth.using_default_password() is False


def test_logging_uses_executable_directory_when_frozen(monkeypatch, tmp_path):
    import importlib
    import sys

    from app.core import logging as app_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScholarDesk.exe"))

    reloaded = importlib.reload(app_logging)

    assert reloaded.LOG_DIR == tmp_path / "logs"

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    importlib.reload(app_logging)


def test_allow_lan_uses_default_when_setting_is_missing(tmp_path, monkeypatch):
    from app.core import network

    config_file = tmp_path / "network.txt"
    config_file.write_text("# comment only\nother_setting=value\n", encoding="utf-8")
    monkeypatch.setattr(network, "NETWORK_CONFIG_FILE", config_file)

    assert network.allow_lan() is network.DEFAULT_ALLOW_LAN


def test_database_uses_executable_directory_when_frozen(monkeypatch, tmp_path):
    import runpy
    import sys
    from pathlib import Path

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScholarDesk.exe"))

    namespace = runpy.run_path(
        str(Path("app/database.py").resolve()),
        run_name="test_database_frozen",
    )

    assert namespace["app_dir"] == tmp_path


def test_payroll_placeholder_route_returns_page(client):
    response = client.get("/payroll")

    assert response.status_code == 200
    assert "Payroll" in response.text


@pytest.mark.anyio
async def test_lifespan_initializes_and_disposes_database(monkeypatch):
    from app import main

    create_all = Mock()
    dispose = Mock()
    info = Mock()

    monkeypatch.setattr(main.Base.metadata, "create_all", create_all)
    monkeypatch.setattr(main.engine, "dispose", dispose)
    monkeypatch.setattr(main.logger, "info", info)

    async with main.lifespan(main.app):
        create_all.assert_called_once_with(bind=main.engine)
        info.assert_any_call("Grant Tracker started successfully.")

    dispose.assert_called_once_with()
    info.assert_any_call("Grant Tracker stopped.")


def test_is_sqlite_lock_error_rejects_non_operational_error():
    from app import main

    assert main._is_sqlite_lock_error(RuntimeError("database is locked")) is False


def test_unhandled_exception_returns_generic_500_response():
    from app import main
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/unexpected",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
        }
    )

    response = main.on_unhandled_exception(
        request,
        RuntimeError("internal implementation detail"),
    )

    assert response.status_code == 500
    assert response.body is not None
    assert b"Something went wrong. Please try again." in response.body
    assert b"internal implementation detail" not in response.body
