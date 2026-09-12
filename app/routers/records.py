"""
Grant and DepartmentAssignment endpoints. Both are always scoped under
a scholar_id, so they live in one router rather than mirroring three
top-level VBA modules 1:1 - the HTTP shape doesn't need to match the
VBA file layout, only the business-logic layer does.
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.templates_config import templates
from app.services import notes as note_service

from app.models import ActivityLog
from app.services import departments as dept_service
from app.services import grants as grant_service
from app.core.exceptions import InvalidScholarError, ScholarNotFoundError
from app.utils.dates import parse_date

router = APIRouter()

def _log_activity(
    request: Request, db: Session, scholar_id: int, category: str, description: str
) -> None:
    actor_username = request.state.authenticated_user
    db.add(
        ActivityLog(
            scholar_id=scholar_id,
            category=category,
            description=description,
            actor_username=actor_username,
        )
    )

def _parse_optional_date(value: str, field_name: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None

    parsed = parse_date(normalized)
    if parsed is None:
        raise ValueError(f"{field_name} must be a valid date (YYYY-MM-DD).")
    return parsed

def _parse_optional_year(value: str, field_name: str) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    if not (normalized.isdigit() and 1900 <= int(normalized) <= 9999):
        raise ValueError(f"{field_name} must be a four-digit year between 1900 and 9999.")
    return int(normalized)

def _render_scholar_detail(
    request: Request,
    db: Session,
    scholar_id: int,
    error=None,
    notice=None,
    show_all_assignments: bool = False,
    show_all_grants: bool = False,
    status_code: int = 200,
):
    from app.services import scholars as scholar_service

    scholar = scholar_service.get_scholar(db, scholar_id)
    context = scholar_service.build_detail_context(
        db, scholar, show_all_assignments, show_all_grants, error, notice
    )
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        context,
        status_code=status_code,
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
            _parse_optional_date(date_started, "Start date"),
            _parse_optional_date(date_ended, "End date"),
        )
        _log_activity(request, db, scholar_id, "assignment", f"Assignment added: {department}")
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Assignment added.")


@router.get("/scholars/{scholar_id}/assignments/{assignment_id}/edit", response_class=HTMLResponse)
def edit_assignment_form(
    request: Request, scholar_id: int, assignment_id: int, db: Session = Depends(get_db)
):
    assignment = dept_service.get_assignment(db, assignment_id)
    if assignment is None or assignment.scholar_id != scholar_id:
        return HTMLResponse(status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/assignment_edit_row.html",
        {"assignment": assignment, "scholar_id": scholar_id, "error": None},
    )


@router.post("/scholars/{scholar_id}/assignments/{assignment_id}", response_class=HTMLResponse)
def update_assignment_route(
    request: Request,
    scholar_id: int,
    assignment_id: int | None = None,
    department: str = Form(...),
    rank: str = Form(""),
    tenure: str = Form(""),
    date_started: str = Form(""),
    date_ended: str = Form(""),
    db: Session = Depends(get_db),
):
    if assignment_id is None:
        return _render_scholar_detail(
            request, db, scholar_id, error="Assignment ID is required."
        )

    assignment = dept_service.get_assignment(db, assignment_id)
    try:
        dept_service.update_assignment(
            db,
            scholar_id,
            assignment_id,
            department,
            rank,
            tenure,
            _parse_optional_date(date_started, "Start date"),
            _parse_optional_date(date_ended, "End date"),
        )
        _log_activity(request, db, scholar_id, "assignment", f"Assignment updated: {department}")
        db.commit()
    except ValueError as e:
        db.rollback()
        if assignment is None or assignment.scholar_id != scholar_id:
            return _render_scholar_detail(
                request, db, scholar_id, error=str(e), status_code=404
            )
        return templates.TemplateResponse(
            request,
            "partials/assignment_edit_row.html",
            {"assignment": assignment, "scholar_id": scholar_id, "error": str(e)},
        )
    return _render_scholar_detail(request, db, scholar_id, notice="Assignment updated.")


@router.delete("/scholars/{scholar_id}/assignments/{assignment_id}", response_class=HTMLResponse)
def delete_assignment(
    request: Request,
    scholar_id: int,
    assignment_id: int | None = None,
    db: Session = Depends(get_db),
):
    if assignment_id is None:
        return _render_scholar_detail(
            request, db, scholar_id, error="Assignment ID is required."
        )

    assignment = dept_service.get_assignment(db, assignment_id)
    if assignment is None or assignment.scholar_id != scholar_id:
        return _render_scholar_detail(
            request, db, scholar_id, error="Assignment not found.", status_code=404
        )

    try:
        dept_service.delete_assignment(db, scholar_id, assignment_id)
        _log_activity(request, db, scholar_id, "assignment", "Assignment deleted")
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
        parsed_start_year = _parse_optional_year(start_year, "Start year")
        parsed_end_year = _parse_optional_year(end_year, "End year")
        grant_service.create_grant(
            db,
            scholar_id,
            program_applied,
            type_of_grant,
            delivering_hei,
            date_started,
            date_ended,
            parsed_start_year,
            parsed_end_year,
            extension,
            status,
            remarks,
        )
        _log_activity(request, db, scholar_id, "grant", f"Grant added: {program_applied}")
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
    if grant is None or grant.scholar_id != scholar_id:
        return HTMLResponse(status_code=404)

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
    grant = grant_service.get_grant(db, grant_id)
    error_message = None
    try:
        parsed_start_year = _parse_optional_year(start_year, "Start year")
        parsed_end_year = _parse_optional_year(end_year, "End year")
        grant_service.update_grant(
            db,
            scholar_id,
            grant_id,
            program_applied,
            type_of_grant,
            delivering_hei,
            date_started,
            date_ended,
            parsed_start_year,
            parsed_end_year,
            extension,
            status,
            remarks,
        )
        _log_activity(request, db, scholar_id, "grant", f"Grant updated: {program_applied}")
        db.commit()
    except ValueError as exc:
        db.rollback()
        error_message = str(exc)
    if grant is None or grant.scholar_id != scholar_id:
        return _render_scholar_detail(
            request, db, scholar_id, error=error_message, status_code=404
        )
    if error_message:
        return templates.TemplateResponse(
            request,
            "partials/grant_edit_row.html",
            {"grant": grant, "scholar_id": scholar_id, "error": error_message},
        )
    return _render_scholar_detail(request, db, scholar_id, notice="Grant updated.")


@router.delete("/grants/{grant_id}", response_class=HTMLResponse)
def delete_grant(request: Request, grant_id: int, scholar_id: int, db: Session = Depends(get_db)):
    grant = grant_service.get_grant(db, grant_id)
    if grant is None or grant.scholar_id != scholar_id:
        return _render_scholar_detail(
            request, db, scholar_id, error="Grant not found.", status_code=404
        )

    try:
        grant_service.delete_grant(db, scholar_id, grant_id)
        _log_activity(request, db, scholar_id, "grant", "Grant deleted")
        db.commit()
    except ValueError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Grant deleted.")


@router.post("/scholars/{scholar_id}/notes", response_class=HTMLResponse)
def add_scholar_note(
    request: Request,
    scholar_id: int,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        note_service.add_note(db, scholar_id, content)
        _log_activity(request, db, scholar_id, "note", "Note added by user")
        db.commit()
    except (InvalidScholarError, ScholarNotFoundError) as exc:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(exc))
    return _render_scholar_detail(request, db, scholar_id, notice="Note added.")


@router.delete("/scholars/{scholar_id}/notes/{note_id}", response_class=HTMLResponse)
def delete_scholar_note(
    request: Request,
    scholar_id: int,
    note_id: int,
    db: Session = Depends(get_db),
):
    try:
        note_service.delete_note(db, scholar_id, note_id)
        _log_activity(request, db, scholar_id, "note", "Note deleted")
        db.commit()
    except ScholarNotFoundError as e:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(e))
    return _render_scholar_detail(request, db, scholar_id, notice="Note deleted.")


@router.post("/grants/{grant_id}/reviews", response_class=HTMLResponse)
def add_grant_review(
    request: Request,
    grant_id: int,
    scholar_id: int,
    decision: str = Form(...),
    reviewer: str = Form(""),
    comments: str = Form(""),
    db: Session = Depends(get_db),
):
    grant = grant_service.get_grant(db, grant_id)
    if grant is None or grant.scholar_id != scholar_id:
        return _render_scholar_detail(
            request, db, scholar_id, error="Grant not found.", status_code=404
        )

    try:
        grant_service.add_review(db, scholar_id, grant_id, decision, reviewer, comments)
        _log_activity(
            request, db, scholar_id, "grant_review", f"Grant review recorded: {decision}"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error=str(exc))

    return _render_scholar_detail(request, db, scholar_id, notice="Review recorded.")
