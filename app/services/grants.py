"""
Grant business logic - mirrors modGrants.bas.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import Grant, Scholar
from app.utils.dates import range_active_in_year

VALID_STATUSES = ["Active", "Completed", "Cancelled", "Pending", "On Hold", "Withdrawn"]


def list_for_scholar(db: Session, scholar_id: int) -> list[Grant]:
    return db.query(Grant).filter(Grant.scholar_id == scholar_id).order_by(Grant.id).all()


def active_in_year(grant: Grant, year: int) -> bool:
    """Same rule as departments.active_in_year - one grant row can span
    multiple years (e.g. a 3-year graduate award), so it must show up
    in every year it overlaps, not just the year it started. Delegates
    to the shared range rule in app.utils.dates so the two record
    types can't drift apart."""
    return range_active_in_year(grant.date_started, grant.date_ended, year)


def create_grant(
    db: Session,
    scholar_id: int,
    program_applied: str,
    type_of_grant: str | None,
    delivering_hei: str | None,
    date_started: date | None,
    date_ended: date | None,
    extension: bool,
    status: str,
    remarks: str | None,
) -> Grant:
    if db.get(Scholar, scholar_id) is None:
        raise ValueError(f"Scholar {scholar_id} not found.")
    program_applied = (program_applied or "").strip()
    if not program_applied:
        raise ValueError("Program applied is required.")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    grant = Grant(
        scholar_id=scholar_id,
        program_applied=program_applied,
        type_of_grant=(type_of_grant or "").strip() or None,
        delivering_hei=(delivering_hei or "").strip() or None,
        date_started=date_started,
        date_ended=date_ended,
        extension=(extension or "").strip() or None,
        status=status,
        remarks=(remarks or "").strip() or None,
    )
    db.add(grant)
    db.flush()
    return grant


def update_grant(
    db: Session,
    grant_id: int,
    program_applied: str,
    type_of_grant: str | None,
    delivering_hei: str | None,
    date_started: date | None,
    date_ended: date | None,
    extension: str | None,
    status: str,
    remarks: str | None,
) -> Grant:
    grant = db.get(Grant, grant_id)
    if grant is None:
        raise ValueError(f"Grant {grant_id} not found.")

    program_applied = (program_applied or "").strip()
    if not program_applied:
        raise ValueError("Program applied is required.")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    grant.program_applied = program_applied
    grant.type_of_grant = (type_of_grant or "").strip() or None
    grant.delivering_hei = (delivering_hei or "").strip() or None
    grant.date_started = date_started
    grant.date_ended = date_ended
    grant.extension = (extension or "").strip() or None
    grant.status = status
    grant.remarks = (remarks or "").strip() or None
    return grant


def delete_grant(db: Session, grant_id: int) -> None:
    grant = db.get(Grant, grant_id)
    if grant is None:
        raise ValueError(f"Grant {grant_id} not found.")
    db.delete(grant)
