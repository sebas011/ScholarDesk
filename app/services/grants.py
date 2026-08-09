"""
Grant business logic - mirrors modGrants.bas.
"""

from sqlalchemy.orm import Session

from app.models import Grant, Scholar

VALID_STATUSES = ["Active", "Completed", "Cancelled", "Pending", "On Hold", "Withdrawn"]


def list_for_scholar(db: Session, scholar_id: int) -> list[Grant]:
    return db.query(Grant).filter(Grant.scholar_id == scholar_id).order_by(Grant.id).all()


def get_grant(db: Session, grant_id: int) -> Grant | None:
    return db.get(Grant, grant_id)


def active_in_year(grant: Grant, year: int) -> bool:
    """True if this grant counts as active in the given year, using
    start_year/end_year (plain integers) rather than date_started/
    date_ended (free text now, so no longer safe to read a date out
    of - see app/models.py for why the two are separate).

    No start_year recorded -> can't place it in any year -> False.
    No end_year -> treated as still ongoing."""
    if grant.start_year is None:
        return False
    if year < grant.start_year:
        return False
    if grant.end_year is not None and year > grant.end_year:
        return False
    return True


def create_grant(
    db: Session,
    scholar_id: int,
    program_applied: str,
    type_of_grant: str | None,
    delivering_hei: str | None,
    date_started: str | None,
    date_ended: str | None,
    start_year: int | None,
    end_year: int | None,
    extension: str | None,
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
        date_started=(date_started or "").strip() or None,
        date_ended=(date_ended or "").strip() or None,
        start_year=start_year,
        end_year=end_year,
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
    date_started: str | None,
    date_ended: str | None,
    start_year: int | None,
    end_year: int | None,
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
    grant.date_started = (date_started or "").strip() or None
    grant.date_ended = (date_ended or "").strip() or None
    grant.start_year = start_year
    grant.end_year = end_year
    grant.extension = (extension or "").strip() or None
    grant.status = status
    grant.remarks = (remarks or "").strip() or None
    return grant


def delete_grant(db: Session, grant_id: int) -> None:
    grant = db.get(Grant, grant_id)
    if grant is None:
        raise ValueError(f"Grant {grant_id} not found.")
    db.delete(grant)
