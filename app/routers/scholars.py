from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.templates_config import templates
from app.services import scholars as scholar_service
from app.services import departments as dept_service
from app.services import grants as grant_service
from app.core.exceptions import (
    InvalidScholarError,
    ScholarNotFoundError,
)

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
    year = _parse_year(year) # type: ignore
    from app.services import stats as stats_service
    from datetime import date as _date

    available_years = stats_service.years_with_data(db)
    selected_year = year  # any valid year is honored, even one with no data yet - it should show 0, not silently fall back to all-time totals

    if selected_year:
        total = stats_service.total_scholars_active_in_year(db, selected_year) # type: ignore
        dept_dist = stats_service.department_distribution(db, year=selected_year) # type: ignore
    else:
        total = stats_service.total_scholars(db)
        dept_dist = stats_service.department_distribution(db)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "total_scholars": total,
            "dept_distribution": dept_dist,
            "available_years": available_years,
            "selected_year": selected_year,
            "current_year": _date.today().year,
        },
    )


@router.get("/scholars", response_class=HTMLResponse)
def scholars_page(
    request: Request, q: str | None = None, year: str | None = None, db: Session = Depends(get_db)
):
    year = _parse_year(year) # type: ignore
    from app.services import stats as stats_service

    scholars, total = scholar_service.list_scholars(db, search=q, year=year, limit=100, offset=0) # type: ignore
    return templates.TemplateResponse(
        request,
        "scholars.html",
        {
            "scholars": scholars,
            "total": total,
            "q": q or "",
            "year": year,
            "available_years": stats_service.years_with_data(db),
            "offset": 0,
            "limit": 100,
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
    year = _parse_year(year)  # pyright: ignore[reportAssignmentType]
    scholars, total = scholar_service.list_scholars(
        db, search=q, year=year, limit=limit, offset=offset  # pyright: ignore[reportArgumentType]
    )
    return templates.TemplateResponse(
        request,
        "partials/scholar_list.html",
        {
            "scholars": scholars,
            "total": total,
            "q": q or "",
            "year": year,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit,
            "has_more": offset + len(scholars) < total,
            "append": offset > 0,  # Load More appends instead of replacing
        },
    )


@router.get("/scholars/new", response_class=HTMLResponse)
def new_scholar_form(request: Request):
    return templates.TemplateResponse(
        request, "partials/scholar_detail.html", {"scholar": None, "error": None}
    )


@router.get("/scholars/{scholar_id}", response_class=HTMLResponse)
def scholar_detail(request: Request, scholar_id: int, db: Session = Depends(get_db)):
    scholar = scholar_service.get_scholar(db, scholar_id)
    if scholar is None:
        return templates.TemplateResponse(
            request,
            "partials/scholar_detail.html",
            {"scholar": None, "error": "Scholar not found."},
        )
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {
            "scholar": scholar,
            "assignments": dept_service.list_for_scholar(db, scholar_id),
            "grants": grant_service.list_for_scholar(db, scholar_id),
            "error": None,
        },
    )


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
                db, scholar.id, department, rank, tenure, date.today(), None
            )
        db.commit()
        db.refresh(scholar)
    except (ScholarNotFoundError, InvalidScholarError) as e:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "partials/scholar_detail.html",
            {"scholar": None, "error": str(e)},
        )

    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {
            "scholar": scholar,
            "assignments": dept_service.list_for_scholar(db, scholar.id),
            "grants": [],
            "error": None,
            "notice": f"Scholar added (ID {scholar.id})."
            + (f" Note: a scholar named '{name}' already existed (ID {existing.id})." if existing else ""),
        },
    )


@router.post("/scholars/{scholar_id}", response_class=HTMLResponse)
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
        db.commit()
        db.refresh(scholar)
    except (ScholarNotFoundError, InvalidScholarError) as e:
        db.rollback()
        scholar = scholar_service.get_scholar(db, scholar_id)
        return templates.TemplateResponse(
            request,
            "partials/scholar_detail.html",
            {
                "scholar": scholar,
                "assignments": dept_service.list_for_scholar(db, scholar_id) if scholar else [],
                "grants": grant_service.list_for_scholar(db, scholar_id) if scholar else [],
                "error": str(e),
            },
        )

    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {
            "scholar": scholar,
            "assignments": dept_service.list_for_scholar(db, scholar_id),
            "grants": grant_service.list_for_scholar(db, scholar_id),
            "error": None,
            "notice": "Scholar updated.",
        },
    )


@router.delete("/scholars/{scholar_id}", response_class=HTMLResponse)
def delete_scholar(request: Request, scholar_id: int, db: Session = Depends(get_db)):
    try:
        scholar_service.delete_scholar(db, scholar_id)
        db.commit()
    except (ScholarNotFoundError, InvalidScholarError) as e:
        db.rollback()
        # Previously this fell straight through to the empty-panel return
        # below even on failure, so a delete that didn't happen still
        # looked like it had - re-render the (still-present) detail panel
        # with the error instead of silently no-oping.
        return templates.TemplateResponse(
            request,
            "partials/scholar_detail.html",
            {
                "scholar": scholar_service.get_scholar(db, scholar_id),
                "assignments": dept_service.list_for_scholar(db, scholar_id),
                "grants": grant_service.list_for_scholar(db, scholar_id),
                "error": str(e),
            },
        )
    return HTMLResponse("")  # htmx swaps the detail panel to empty on delete
