"""
Grant and DepartmentAssignment endpoints. Both are always scoped under
a scholar_id, so they live in one router rather than mirroring three
top-level VBA modules 1:1 - the HTTP shape doesn't need to match the
VBA file layout, only the business-logic layer does.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.templates_config import templates
from app.services import departments as dept_service
from app.services import grants as grant_service
from app.utils.dates import parse_date

router = APIRouter()

def _render_scholar_detail(request: Request, db: Session, scholar_id: int, error=None, notice=None):
    from app.services import scholars as scholar_service

    scholar = scholar_service.get_scholar(db, scholar_id)
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {
            "scholar": scholar,
            "assignments": dept_service.list_for_scholar(db, scholar_id),
            "grants": grant_service.list_for_scholar(db, scholar_id),
            "error": error,
            "notice": notice,
        },
    )


@router.post("/scholars/{scholar_id}/assignments", response_class=HTMLResponse)
def add_assignment(
    request: Request,
    scholar_id: int,
    department: str = Form(...),
    rank: str = Form(""),
    tenure: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        dept_service.create_assignment(
            db,
            scholar_id,
            department,
            rank,
            tenure,
            parse_date(date_started),
            parse_date(date_ended),
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Assignment added.")


@router.get("/assignments/{assignment_id}/edit", response_class=HTMLResponse)
def edit_assignment_form(
    request: Request, assignment_id: int, scholar_id: int, db: Session = Depends(get_db)
):
    assignment = dept_service.get_assignment(db, assignment_id)
    return templates.TemplateResponse(
        request,
        "partials/assignment_edit_row.html",
        {"assignment": assignment, "scholar_id": scholar_id, "error": None},
    )


@router.post("/assignments/{assignment_id}", response_class=HTMLResponse)
def update_assignment_route(
    request: Request,
    assignment_id: int,
    scholar_id: int,
    department: str = Form(...),
    rank: str = Form(""),
    tenure: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        dept_service.update_assignment(
            db,
            assignment_id,
            department,
            rank,
            tenure,
            parse_date(date_started),
            parse_date(date_ended),
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Assignment updated.")


@router.delete("/assignments/{assignment_id}", response_class=HTMLResponse)
def delete_assignment(
    request: Request, assignment_id: int, scholar_id: int, db: Session = Depends(get_db)
):
    try:
        dept_service.delete_assignment(db, assignment_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Assignment deleted.")


@router.post("/scholars/{scholar_id}/grants", response_class=HTMLResponse)
def add_grant(
    request: Request,
    scholar_id: int,
    program_applied: str = Form(...),
    type_of_grant: str = Form(""),
    delivering_hei: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    start_year: str = Form(""),
    end_year: str = Form(""),
    extension: str = Form(""),
    status: str = Form("Active"),
    remarks: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        grant_service.create_grant(
            db,
            scholar_id,
            program_applied,
            type_of_grant,
            delivering_hei,
            date_started,
            date_ended,
            int(start_year) if start_year.strip().isdigit() else None,
            int(end_year) if end_year.strip().isdigit() else None,
            extension,
            status,
            remarks,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Grant added.")


@router.get("/grants/{grant_id}/edit", response_class=HTMLResponse)
def edit_grant_form(
    request: Request, grant_id: int, scholar_id: int, db: Session = Depends(get_db)
):
    grant = grant_service.get_grant(db, grant_id)
    return templates.TemplateResponse(
        request,
        "partials/grant_edit_row.html",
        {"grant": grant, "scholar_id": scholar_id, "error": None},
    )


@router.post("/grants/{grant_id}", response_class=HTMLResponse)
def update_grant_route(
    request: Request,
    grant_id: int,
    scholar_id: int,
    program_applied: str = Form(...),
    type_of_grant: str = Form(""),
    delivering_hei: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    start_year: str = Form(""),
    end_year: str = Form(""),
    extension: str = Form(""),
    status: str = Form("Active"),
    remarks: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        grant_service.update_grant(
            db,
            grant_id,
            program_applied,
            type_of_grant,
            delivering_hei,
            date_started,
            date_ended,
            int(start_year) if start_year.strip().isdigit() else None,
            int(end_year) if end_year.strip().isdigit() else None,
            extension,
            status,
            remarks,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Grant updated.")


@router.delete("/grants/{grant_id}", response_class=HTMLResponse)
def delete_grant(request: Request, grant_id: int, scholar_id: int, db: Session = Depends(get_db)):
    try:
        grant_service.delete_grant(db, grant_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Grant deleted.")
