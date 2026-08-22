from datetime import date

from fastapi import APIRouter, Depends, Form, Request
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
from sqlalchemy import or_
from app.models import DepartmentAssignment, Grant, Scholar, ActivityLog
from app.core.exceptions import (
    InvalidScholarError,
    ScholarNotFoundError,
)
from app.utils.dates import parse_date


def _log_activity(db: Session, scholar_id: int, category: str, description: str) -> None:
    db.add(ActivityLog(scholar_id=scholar_id, category=category, description=description))


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

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, year: str | None = None, db: Session = Depends(get_db)):
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
        # Primary assignment = earliest id per scholar
        assignments = (
            db.query(DepartmentAssignment)
            .filter(DepartmentAssignment.scholar_id.in_(scholar_ids))
            .order_by(DepartmentAssignment.id)
            .all()
        )
        seen = set()
        for a in assignments:
            if a.scholar_id not in seen:
                enriched[a.scholar_id]["dept"] = a.department
                enriched[a.scholar_id]["rank"] = a.rank or "—"
                seen.add(a.scholar_id)

        # Latest grant status = most recent start_year, then highest id
        grants = (
            db.query(Grant)
            .filter(Grant.scholar_id.in_(scholar_ids))
            .order_by(Grant.start_year.desc(), Grant.id.desc())
            .all()
        )
        seen = set()
        for g in grants:
            if g.scholar_id not in seen:
                enriched[g.scholar_id]["status"] = g.status
                seen.add(g.scholar_id)

    return enriched


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    q: str | None = None,
    year: str | None = None,
    page: int = 1,
    per_page: int = 25,
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
    q: str | None = None,
    year: str | None = None,
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
    q: str | None = None,
    year: str | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """htmx endpoint: re-renders the <ul> (or appends to it, for Load More)
    as the user types in search, changes the year filter, or paginates."""
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
    db: Session = Depends(get_db),
):
    """Dedicated create page's submit target. Unlike POST /scholars
    (used by the old sidebar's htmx swap), this is a normal HTML form
    post - success redirects to a real new URL (a full page reload,
    not an in-place swap); failure re-renders this same page with the
    error and the entered values preserved, at 400, per spec."""
    try:
        scholar = scholar_service.create_scholar(
            db,
            name=name,
            age=int(age) if age.strip().isdigit() else None,
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
                parse_date(date_started) or date.today(),
                parse_date(date_ended),
            )
        _log_activity(db, scholar.id, "scholar", f"Scholar '{scholar.name}' created")
        db.commit()
        db.refresh(scholar)
    except (ScholarNotFoundError, InvalidScholarError, ValueError) as e:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "scholar_new.html",
            {
                "error": str(e),
                "form": {
                    "name": name,
                    "age": age,
                    "previous_degree": previous_degree,
                    "department": department,
                    "rank": rank,
                    "tenure": tenure,
                },
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/scholars/{scholar.id}", status_code=303)


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
            age=int(age) if age.strip().isdigit() else None,
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
                parse_date(date_started) or date.today(),
                parse_date(date_ended),
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
            age=int(age) if age.strip().isdigit() else None,
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
        scholar_service.delete_scholar(db, scholar_id)
        _log_activity(db, scholar_id, "scholar", "Scholar deleted")
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
        headers={"HX-Trigger": "scholar-changed"},
    )

@router.get("/dashboard/export")
def dashboard_export(
    request: Request,
    q: str | None = None,
    year: str | None = None,
    db: Session = Depends(get_db),
):
    """Export one row per grant with scholar and primary assignment details.
    Respects the same search and year filters as the dashboard."""

    parsed_year: int | None = _parse_year(year)

    # Query grants (not scholars) so every grant becomes a CSV row
    query = db.query(Grant).join(Scholar).order_by(Scholar.name, Grant.id)

    if q:
        query = query.filter(Scholar.name.ilike(f"%{q}%"))

    if parsed_year is not None:
        query = query.filter(
            Grant.start_year.isnot(None),
            Grant.start_year <= parsed_year,
            or_(Grant.end_year.is_(None), Grant.end_year >= parsed_year),
        )

    grants = query.all()

    # Batch-load primary assignments
    scholar_ids = list({g.scholar_id for g in grants})
    assignments_by_scholar: dict[int, DepartmentAssignment] = {}
    if scholar_ids:
        assignments = (
            db.query(DepartmentAssignment)
            .filter(DepartmentAssignment.scholar_id.in_(scholar_ids))
            .order_by(DepartmentAssignment.id)
            .all()
        )
        for a in assignments:
            if a.scholar_id not in assignments_by_scholar:
                assignments_by_scholar[a.scholar_id] = a

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Rank", "Department", "Age", "Tenure", "Previous Degree",
        "Program Applied", "Delivering HEI", "Type of Grant", "Date Started",
        "Date Ended", "Extension", "Status", "Remarks",
    ])

    for g in grants:
        s = g.scholar
        a = assignments_by_scholar.get(s.id)
        writer.writerow([
            s.name,
            a.rank if a else "",
            a.department if a else "",
            s.age or "",
            a.tenure if a else "",
            s.previous_degree or "",
            g.program_applied,
            g.delivering_hei or "",
            g.type_of_grant or "",
            g.date_started or "",
            g.date_ended or "",
            g.extension or "",
            g.status,
            g.remarks or "",
        ])

    output.seek(0)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"scholars_export_{date_str}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
