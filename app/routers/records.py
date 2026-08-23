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
from datetime import datetime

from app.models import GrantReview, ScholarNote, ActivityLog
from app.services import departments as dept_service
from app.services import grants as grant_service
from app.utils.dates import parse_date


def _log_activity(db: Session, scholar_id: int, category: str, description: str) -> None:
    db.add(ActivityLog(scholar_id=scholar_id, category=category, description=description))

router = APIRouter()


def _render_scholar_detail(
    request: Request,
    db: Session,
    scholar_id: int,
    error=None,
    notice=None,
    show_all_assignments: bool = False,
    show_all_grants: bool = False,
):
    from app.services import scholars as scholar_service

    scholar = scholar_service.get_scholar(db, scholar_id)
    context = scholar_service.build_detail_context(
        db, scholar, show_all_assignments, show_all_grants, error, notice
    )
    return templates.TemplateResponse(request, "partials/scholar_detail.html", context)


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
        _log_activity(db, scholar_id, "assignment", f"Assignment added: {department}")
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
    assignment = dept_service.get_assignment(db, assignment_id)
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
        _log_activity(db, scholar_id, "assignment", f"Assignment updated: {department}")
        db.commit()
    except ValueError as e:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "partials/assignment_edit_row.html",
            {"assignment": assignment, "scholar_id": scholar_id, "error": str(e)},
        )
    return _render_scholar_detail(request, db, scholar_id, notice="Assignment updated.")


@router.delete("/assignments/{assignment_id}", response_class=HTMLResponse)
def delete_assignment(
    request: Request, assignment_id: int, scholar_id: int, db: Session = Depends(get_db)
):
    try:
        dept_service.delete_assignment(db, assignment_id)
        _log_activity(db, scholar_id, "assignment", "Assignment deleted")
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
        _log_activity(db, scholar_id, "grant", f"Grant added: {program_applied}")
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
    grant = grant_service.get_grant(db, grant_id)
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
        _log_activity(db, scholar_id, "grant", f"Grant updated: {program_applied}")
        db.commit()
    except ValueError as e:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "partials/grant_edit_row.html",
            {"grant": grant, "scholar_id": scholar_id, "error": str(e)},
        )
    return _render_scholar_detail(request, db, scholar_id, notice="Grant updated.")


@router.delete("/grants/{grant_id}", response_class=HTMLResponse)
def delete_grant(request: Request, grant_id: int, scholar_id: int, db: Session = Depends(get_db)):
    try:
        grant_service.delete_grant(db, grant_id)
        _log_activity(db, scholar_id, "grant", "Grant deleted")
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
    content = content.strip()
    if not content:
        return _render_scholar_detail(request, db, scholar_id, error="Note cannot be empty.")

    try:
        note = ScholarNote(scholar_id=scholar_id, content=content)
        db.add(note)
        _log_activity(db, scholar_id, "note", "Note added by user")
        db.commit()
    except Exception:
        db.rollback()
        return _render_scholar_detail(
            request, db, scholar_id, error="Could not add note - scholar may not exist."
        )
    return _render_scholar_detail(request, db, scholar_id, notice="Note added.")


@router.delete("/scholars/{scholar_id}/notes/{note_id}", response_class=HTMLResponse)
def delete_scholar_note(
    request: Request,
    scholar_id: int,
    note_id: int,
    db: Session = Depends(get_db),
):
    note = db.get(ScholarNote, note_id)
    if not note or note.scholar_id != scholar_id:
        return _render_scholar_detail(request, db, scholar_id, error="Note not found.")
    db.delete(note)
    db.commit()
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
    if decision not in {"pending", "approved", "rejected", "deferred"}:
        return _render_scholar_detail(
            request, db, scholar_id, error="Invalid review decision."
        )

    if grant_service.get_grant(db, grant_id) is None:
        return _render_scholar_detail(request, db, scholar_id, error="Grant not found.")

    try:
        review = GrantReview(
            grant_id=grant_id,
            decision=decision,
            reviewer=reviewer.strip() or None,
            comments=comments.strip() or None,
            decided_at=datetime.now() if decision != "pending" else None,
        )
        db.add(review)
        _log_activity(db, scholar_id, "grant_review", f"Grant review recorded: {decision}")
        db.commit()
    except Exception:
        db.rollback()
        return _render_scholar_detail(request, db, scholar_id, error="Could not record review.")
    return _render_scholar_detail(request, db, scholar_id, notice="Review recorded.")
