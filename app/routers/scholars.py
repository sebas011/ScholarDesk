from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse
import csv
import io
from datetime import datetime

from app.database import get_db
from app.templates_config import templates
from app.services import scholars as scholar_service
from app.services import departments as dept_service
from app.services import grants as grant_service
from sqlalchemy import and_, func, or_, select
from app.models import DepartmentAssignment, Grant, Scholar, ActivityLog
from app.core.exceptions import (
    InvalidScholarError,
    ScholarNotFoundError,
)
from app.utils.dates import parse_date


def _log_activity(db: Session, scholar_id: int, category: str, description: str) -> None:
    db.add(ActivityLog(scholar_id=scholar_id, category=category, description=description))


def _csv_cell(value: object | None) -> str:
    """Return a CSV-safe text cell for spreadsheet applications."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _parse_year(year: str | None) -> int | None:
    """Query params arrive as strings. The 'All Years' option in the
    filter dropdown submits year='' rather than omitting the param
    entirely, and int | None as a param type rejects '' with a 422 -
    so empty string must be normalized to None before FastAPI's
    validation ever sees it."""
    if year is None or year.strip() == "":
        return None
    try:
        return int(year)
    except ValueError:
        return None

def _parse_optional_age(value: str) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.isdigit():
        raise ValueError("Age must be a whole number.")
    return int(normalized)

def _parse_optional_assignment_date(value: str, field_name: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None

    parsed = parse_date(normalized)
    if parsed is None:
        raise ValueError(f"{field_name} must be a valid date (YYYY-MM-DD).")
    return parsed

router = APIRouter()

def _parse_optional_grant_year(value: str, field_name: str) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    if not (normalized.isdigit() and 1900 <= int(normalized) <= 9999):
        raise ValueError(f"{field_name} must be a four-digit year between 1900 and 9999.")
    return int(normalized)

@router.get("/home", response_class=HTMLResponse)
def home(
    request: Request,
    year: str | None = Query(
        default=None,
        pattern=r"^(|19[0-9]{2}|[2-9][0-9]{3})$",
    ),
    db: Session = Depends(get_db),
):
    from app.services import stats as stats_service
    from datetime import date as _date

    available_years = stats_service.years_with_data(db)
    # Any valid year is honored, even one with no data yet - it should
    # show 0, not silently fall back to all-time totals.
    selected_year: int | None = _parse_year(year)

    if selected_year:
        total = stats_service.total_scholars_active_in_year(db, selected_year)
        dept_dist = stats_service.department_distribution(db, year=selected_year)
    else:
        total = stats_service.total_scholars(db)
        dept_dist = stats_service.department_distribution(db)

    total_grants = stats_service.total_grants(db, year=selected_year)
    active_grants = stats_service.active_grants_count(db, year=selected_year)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "total_scholars": total,
            "dept_distribution": dept_dist,
            "available_years": available_years,
            "selected_year": selected_year,
            "current_year": _date.today().year,
            "total_grants": total_grants,
            "active_grants": active_grants,
        },
    )


def _enrich_scholars(db: Session, scholars: list):
    """Attach primary assignment and latest grant status for each scholar.

    Includes dept, rank, and status for the directory table.
    """
    scholar_ids = [s.id for s in scholars]
    enriched = {s.id: {"dept": "—", "rank": "—", "status": "—"} for s in scholars}

    if scholar_ids:
        # Primary assignment = lowest assignment ID per scholar.
        primary_assignments = (
            db.query(
                DepartmentAssignment.scholar_id,
                func.min(DepartmentAssignment.id).label("assignment_id"),
            )
            .filter(DepartmentAssignment.scholar_id.in_(scholar_ids))
            .group_by(DepartmentAssignment.scholar_id)
            .subquery()
        )
        assignments = (
            db.query(DepartmentAssignment)
            .join(
                primary_assignments,
                DepartmentAssignment.id == primary_assignments.c.assignment_id,
            )
            .all()
        )
        for assignment in assignments:
            enriched[assignment.scholar_id]["dept"] = assignment.department
            enriched[assignment.scholar_id]["rank"] = assignment.rank or "—"
        # Latest grant status = greatest start_year, then greatest ID.
        ranked_grants = (
            db.query(
                Grant.id.label("grant_id"),
                func.row_number()
                .over(
                    partition_by=Grant.scholar_id,
                    order_by=(Grant.start_year.desc(), Grant.id.desc()),
                )
                .label("position"),
            )
            .filter(Grant.scholar_id.in_(scholar_ids))
            .subquery()
        )
        grants = (
            db.query(Grant)
            .join(ranked_grants, Grant.id == ranked_grants.c.grant_id)
            .filter(ranked_grants.c.position == 1)
            .all()
        )
        for grant in grants:
            enriched[grant.scholar_id]["status"] = grant.status

    return enriched


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    year: str | None = Query(
    default=None,
    pattern=r"^(|19[0-9]{2}|[2-9][0-9]{3})$",
    ),
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from app.services import stats as stats_service

    parsed_year: int | None = _parse_year(year)
    scholars, total = scholar_service.list_scholars(
        db, search=q, year=parsed_year, limit=per_page, offset=(page - 1) * per_page
    )

    enriched = _enrich_scholars(db, scholars)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    context = {
        "scholars": scholars,
        "total": total,
        "q": q or "",
        "year": parsed_year,
        "available_years": stats_service.years_with_data(db),
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "enriched": enriched,
    }

    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "partials/dashboard_content.html", context)
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/scholars", response_class=HTMLResponse)
def scholars_page(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    year: str | None = Query(
    default=None,
    pattern=r"^(|19[0-9]{2}|[2-9][0-9]{3})$",
    ),
    scholar_id: int | None = None,
    db: Session = Depends(get_db),
):
    # If no query params, redirect to the new Directory
    if not q and not year and not scholar_id:
        return RedirectResponse(url="/dashboard", status_code=302)

    from app.services import stats as stats_service

    parsed_year: int | None = _parse_year(year)
    scholars, total = scholar_service.list_scholars(
        db, search=q, year=parsed_year, limit=100, offset=0
    )

    detail_context = {"scholar": None, "error": None}
    selected_id = None
    if scholar_id is not None:
        selected = scholar_service.get_scholar(db, scholar_id)
        selected_id = scholar_id if selected else None
        detail_context = scholar_service.build_detail_context(
            db, selected, error=None if selected else "Scholar not found."
        )

    return templates.TemplateResponse(
        request,
        "scholars.html",
        {
            "scholars": scholars,
            "total": total,
            "q": q or "",
            "year": parsed_year,
            "available_years": stats_service.years_with_data(db),
            "offset": 0,
            "limit": 100,
            "detail_context": detail_context,
            "selected_id": selected_id,
        },
    )


@router.get("/scholars/list", response_class=HTMLResponse)
def scholars_list_partial(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    year: str | None = Query(
    default=None,
    pattern=r"^(|19[0-9]{2}|[2-9][0-9]{3})$",
    ),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=50, ge=1, le=100),
    selected_id: int | None = None,
    db: Session = Depends(get_db),
):
    """htmx endpoint: re-renders the <ul> (or appends to it, for Load More)
    as the user types in search, changes the year filter, or paginates.

    selected_id (optional) is the scholar currently shown in the detail
    panel at the time the sidebar was last rendered - threaded through
    so the "active" highlight survives a list refresh instead of
    disappearing every time this endpoint's own response replaces the
    <li> elements. Reflects state as of the last full page load, not
    necessarily whatever the user has clicked since (see scholars.html)."""
    parsed_year: int | None = _parse_year(year)
    scholars, total = scholar_service.list_scholars(
        db, search=q, year=parsed_year, limit=limit, offset=offset
    )
    return templates.TemplateResponse(
        request,
        "partials/scholar_list.html",
        {
            "scholars": scholars,
            "total": total,
            "q": q or "",
            "year": parsed_year,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit,
            "has_more": offset + len(scholars) < total,
            "append": offset > 0,  # Load More appends instead of replacing
            "selected_id": selected_id,
        },
    )


@router.get("/scholars/new", response_class=HTMLResponse)
def new_scholar_form(request: Request):
    """Serves two different things from one URL, told apart by the
    HX-Request header htmx sends automatically on every request it
    makes: an htmx swap (e.g. the old sidebar's '+ New Scholar' button)
    gets just the form partial to swap into its target; a normal
    browser navigation gets the real, dedicated full page. Without this
    branch, a plain page visit would try to render a bare form fragment
    with no header/nav/styles at all - the same class of bug fixed
    earlier for /scholars/{id}."""
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request, "partials/scholar_detail.html", {"scholar": None, "error": None}
        )
    return templates.TemplateResponse(request, "scholar_new.html", {"error": None, "form": {}})


@router.post("/scholars/new", response_class=HTMLResponse)
def create_scholar_page(
    request: Request,
    name: str = Form(...),
    age: str = Form(""),
    previous_degree: str = Form(""),
    missing_requirements: bool = Form(False),
    department: str = Form(""),
    rank: str = Form(""),
    tenure: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    program_applied: str = Form(""),
    type_of_grant: str = Form(""),
    delivering_hei: str = Form(""),
    grant_date_started: str = Form(""),
    grant_date_ended: str = Form(""),
    start_year: str = Form(""),
    end_year: str = Form(""),
    grant_status: str = Form("Active"),
    extension: str = Form(""),
    remarks: str = Form(""),
    db: Session = Depends(get_db),
):
    """Dedicated create page's submit target. Unlike POST /scholars
    (used by the old sidebar's htmx swap), this is a normal HTML form
    post - success redirects to a real new URL (a full page reload,
    not an in-place swap); failure re-renders this same page with the
    error and the entered values preserved, at 400, per spec."""
    error = None
    try:
        scholar = scholar_service.create_scholar(
            db,
            name=name,
            age=_parse_optional_age(age),
            previous_degree=previous_degree,
            missing_requirements=missing_requirements,
        )
        if department.strip():
            dept_service.create_assignment(
                db,
                scholar.id,
                department,
                rank,
                tenure,
                _parse_optional_assignment_date(date_started, "Start date") or date.today(),
                _parse_optional_assignment_date(date_ended, "End date"),
            )
        grant_details_entered = any(
            value.strip()
            for value in (
                type_of_grant,
                delivering_hei,
                grant_date_started,
                grant_date_ended,
                start_year,
                end_year,
                extension,
                remarks,
            )
        )

        if grant_details_entered and not program_applied.strip():
            raise ValueError("Program applied is required when adding an initial grant.")

        parsed_start_year = _parse_optional_grant_year(start_year, "Start year")
        parsed_end_year = _parse_optional_grant_year(end_year, "End year")

        if program_applied.strip():
            grant_service.create_grant(
                db,
                scholar.id,
                program_applied,
                type_of_grant,
                delivering_hei,
                grant_date_started,
                grant_date_ended,
                parsed_start_year,
                parsed_end_year,
                extension,
                grant_status,
                remarks,
            )

            _log_activity(
                db,
                scholar.id,
                "grant",
                f"Initial grant added: {program_applied.strip()}",
            )
        _log_activity(db, scholar.id, "scholar", f"Scholar '{scholar.name}' created")
        db.commit()
        db.refresh(scholar)
    except (ScholarNotFoundError, InvalidScholarError, ValueError) as e:
        db.rollback()
        error = str(e)

    if error:
        return templates.TemplateResponse(
            request,
            "scholar_new.html",
            {
                "error": error,
                "form": {
                    "name": name,
                    "age": age,
                    "previous_degree": previous_degree,
                    "department": department,
                    "rank": rank,
                    "tenure": tenure,
                    "program_applied": program_applied,
                    "type_of_grant": type_of_grant,
                    "delivering_hei": delivering_hei,
                    "grant_date_started": grant_date_started,
                    "grant_date_ended": grant_date_ended,
                    "start_year": start_year,
                    "end_year": end_year,
                    "grant_status": grant_status,
                    "extension": extension,
                    "remarks": remarks,
                    "date_started": date_started,
                    "date_ended": date_ended,
                },
            },
            status_code=400,
        )

    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/scholars/{scholar_id}", response_class=HTMLResponse)
def scholar_detail(
    request: Request,
    scholar_id: int,
    show_all_assignments: bool = False,
    show_all_grants: bool = False,
    db: Session = Depends(get_db),
):
    scholar = scholar_service.get_scholar(db, scholar_id)
    if scholar is None:
        context = {"scholar": None, "error": "Scholar not found."}
    else:
        context = scholar_service.build_detail_context(
            db, scholar, show_all_assignments, show_all_grants
        )
    # Same HX-Request branching as /scholars/new: an htmx swap (e.g. the
    # old sidebar's click-a-name, or an edit row's Cancel/"Show all"
    # link) gets the partial to swap into its target; a normal browser
    # navigation gets the real, dedicated full profile page.
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "partials/scholar_detail.html", context)
    return templates.TemplateResponse(request, "scholar_profile.html", context)


@router.post("/scholars", response_class=HTMLResponse)
def create_scholar(
    request: Request,
    name: str = Form(...),
    age: str = Form(""),
    previous_degree: str = Form(""),
    missing_requirements: bool = Form(False),
    department: str = Form(""),
    rank: str = Form(""),
    tenure: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        existing = scholar_service.find_scholar_by_name(db, name)
        scholar = scholar_service.create_scholar(
            db,
            name=name,
            age=_parse_optional_age(age),
            previous_degree=previous_degree,
            missing_requirements=missing_requirements,
        )
        if department.strip():
            dept_service.create_assignment(
                db,
                scholar.id,
                department,
                rank,
                tenure,
                _parse_optional_assignment_date(date_started, "Start date") or date.today(),
                _parse_optional_assignment_date(date_ended, "End date"),
            )
        db.commit()
        db.refresh(scholar)
    except (ScholarNotFoundError, InvalidScholarError, ValueError) as e:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "partials/scholar_detail.html",
            {"scholar": None, "error": str(e)},
        )

    context = scholar_service.build_detail_context(
        db,
        scholar,
        notice=(
            f"Scholar added (ID {scholar.id})."
            + (
                f" Note: a scholar named '{name}' already existed (ID {existing.id})."
                if existing
                else ""
            )
        ),
    )
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        context,
        headers={"HX-Trigger": "scholar-changed"},
    )


@router.put("/scholars/{scholar_id}", response_class=HTMLResponse)
def update_scholar(
    request: Request,
    scholar_id: int,
    name: str = Form(...),
    age: str = Form(""),
    previous_degree: str = Form(""),
    missing_requirements: bool = Form(False),
    db: Session = Depends(get_db),
):
    try:
        scholar = scholar_service.update_scholar(
            db,
            scholar_id,
            name=name,
            age=_parse_optional_age(age),
            previous_degree=previous_degree,
            missing_requirements=missing_requirements,
        )
        _log_activity(db, scholar_id, "scholar", f"Scholar '{scholar.name}' updated")
        db.commit()
        db.refresh(scholar)
    except (ScholarNotFoundError, InvalidScholarError, ValueError) as e:
        db.rollback()
        scholar = scholar_service.get_scholar(db, scholar_id)
        context = scholar_service.build_detail_context(db, scholar, error=str(e))
        return templates.TemplateResponse(request, "partials/scholar_detail.html", context)

    context = scholar_service.build_detail_context(db, scholar, notice="Scholar updated.")
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        context,
        headers={"HX-Trigger": "scholar-changed"},
    )


@router.delete("/scholars/{scholar_id}", response_class=HTMLResponse)
def delete_scholar(request: Request, scholar_id: int, db: Session = Depends(get_db)):
    try:
        _log_activity(
        db,
        scholar_id,
        "scholar",
        "Scholar deleted",
        )

        scholar_service.delete_scholar(db, scholar_id)

        db.commit()
    except (ScholarNotFoundError, InvalidScholarError, ValueError) as e:
        db.rollback()
        scholar = scholar_service.get_scholar(db, scholar_id)
        context = scholar_service.build_detail_context(db, scholar, error=str(e))
        return templates.TemplateResponse(request, "partials/scholar_detail.html", context)
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {"scholar": None, "error": None, "notice": "Scholar deleted."},
        headers={"HX-Trigger": "scholar-changed", "HX-Redirect": "/dashboard"},
    )


@router.get("/dashboard/export")
def dashboard_export(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    year: str | None = Query(
    default=None,
    pattern=r"^(|19[0-9]{2}|[2-9][0-9]{3})$",
    ),
    db: Session = Depends(get_db),
):
    """Export every scholar, with one row per matching grant and blank grant
columns where no grant exists. Respects dashboard search and year filters."""

    parsed_year = _parse_year(year)

    grant_join_conditions = [Grant.scholar_id == Scholar.id]
    eligible_scholar_filter = None

    if parsed_year is not None:
        year_start = date(parsed_year, 1, 1)
        year_end = date(parsed_year, 12, 31)

        dept_scholar_ids = db.query(DepartmentAssignment.scholar_id).filter(
            DepartmentAssignment.date_started.isnot(None),
            DepartmentAssignment.date_started <= year_end,
            or_(
                DepartmentAssignment.date_ended.is_(None),
                DepartmentAssignment.date_ended >= year_start,
            ),
        )
        grant_scholar_ids = db.query(Grant.scholar_id).filter(
            Grant.start_year.isnot(None),
            Grant.start_year <= parsed_year,
            or_(Grant.end_year.is_(None), Grant.end_year >= parsed_year),
        )
        eligible_scholar_filter = or_(
            Scholar.id.in_(dept_scholar_ids),
            Scholar.id.in_(grant_scholar_ids),
        )
        grant_join_conditions.extend(
            (
                Grant.start_year.isnot(None),
                Grant.start_year <= parsed_year,
                or_(Grant.end_year.is_(None), Grant.end_year >= parsed_year),
            )
        )

    primary_assignment_id = (
        select(DepartmentAssignment.id)
        .where(DepartmentAssignment.scholar_id == Scholar.id)
        .order_by(DepartmentAssignment.id)
        .limit(1)
        .correlate(Scholar)
        .scalar_subquery()
    )
    query = (
        db.query(Scholar, Grant, DepartmentAssignment)
        .outerjoin(Grant, and_(*grant_join_conditions))
        .outerjoin(
            DepartmentAssignment,
            DepartmentAssignment.id == primary_assignment_id,
        )
        .order_by(Scholar.name, Scholar.id, Grant.id)
    )
    if q:
        query = query.filter(Scholar.name.ilike(f"%{q}%"))

    if eligible_scholar_filter is not None:
        query = query.filter(eligible_scholar_filter)

    def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        rows_in_chunk = 0

        writer.writerow(
            [
                "Name",
                "Rank",
                "Department",
                "Age",
                "Tenure",
                "Previous Degree",
                "Program Applied",
                "Delivering HEI",
                "Type of Grant",
                "Date Started",
                "Date Ended",
                "Extension",
                "Status",
                "Remarks",
            ]
        )
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for scholar, grant, assignment in query.yield_per(500):
            writer.writerow(
                [
                    _csv_cell(value)
                    for value in (
                        scholar.name,
                        assignment.rank if assignment else "",
                        assignment.department if assignment else "",
                        scholar.age,
                        assignment.tenure if assignment else "",
                        scholar.previous_degree,
                        grant.program_applied if grant else "",
                        grant.delivering_hei if grant else "",
                        grant.type_of_grant if grant else "",
                        grant.date_started if grant else "",
                        grant.date_ended if grant else "",
                        grant.extension if grant else "",
                        grant.status if grant else "",
                        grant.remarks if grant else "",
                    )
                ]
            )
            rows_in_chunk += 1

            if rows_in_chunk == 500:
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
                rows_in_chunk = 0

        if output.tell():
            yield output.getvalue()

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"scholars_export_{date_str}.csv"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
