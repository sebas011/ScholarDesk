"""
Department assignment business logic - mirrors modDepartmentAssignments.bas.
No IsPrimary anywhere: "primary" assignment is defined once, here, as
the earliest by id. That's the only definition in the whole codebase -
the exact discipline the VBA version lost when three modules each had
their own opinion about what "primary" meant.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import DepartmentAssignment, Scholar
from app.utils.dates import range_active_in_year


def list_for_scholar(db: Session, scholar_id: int) -> list[DepartmentAssignment]:
    return (
        db.query(DepartmentAssignment)
        .filter(DepartmentAssignment.scholar_id == scholar_id)
        .order_by(DepartmentAssignment.id)
        .all()
    )


def get_assignment(db: Session, assignment_id: int) -> DepartmentAssignment | None:
    return db.get(DepartmentAssignment, assignment_id)


def get_primary_assignment(db: Session, scholar_id: int) -> DepartmentAssignment | None:
    """The one and only definition of 'primary': earliest assignment by id."""
    return (
        db.query(DepartmentAssignment)
        .filter(DepartmentAssignment.scholar_id == scholar_id)
        .order_by(DepartmentAssignment.id)
        .first()
    )


def active_in_year(assignment: DepartmentAssignment, year: int) -> bool:
    """True if this assignment counts as active in the given year.
    Delegates to the shared range rule in app.utils.dates so this and
    Grant.active_in_year can't drift apart."""
    return range_active_in_year(assignment.date_started, assignment.date_ended, year)


def create_assignment(
    db: Session,
    scholar_id: int,
    department: str,
    rank: str | None,
    tenure: str | None,
    date_started: date | None,
    date_ended: date | None,
) -> DepartmentAssignment:
    if db.get(Scholar, scholar_id) is None:
        raise ValueError(f"Scholar {scholar_id} not found.")
    department = (department or "").strip()
    if not department:
        raise ValueError("Department is required.")

    assignment = DepartmentAssignment(
        scholar_id=scholar_id,
        department=department,
        rank=(rank or "").strip() or None,
        tenure=(tenure or "").strip() or None,
        date_started=date_started,
        date_ended=date_ended,
    )
    db.add(assignment)
    db.flush()
    return assignment


def update_assignment(
    db: Session,
    assignment_id: int,
    department: str,
    rank: str | None,
    tenure: str | None,
    date_started: date | None,
    date_ended: date | None,
) -> DepartmentAssignment:
    assignment = db.get(DepartmentAssignment, assignment_id)
    if assignment is None:
        raise ValueError(f"Assignment {assignment_id} not found.")

    department = (department or "").strip()
    if not department:
        raise ValueError("Department is required.")

    assignment.department = department
    assignment.rank = (rank or "").strip() or None
    assignment.tenure = (tenure or "").strip() or None
    assignment.date_started = date_started
    assignment.date_ended = date_ended
    return assignment


def delete_assignment(db: Session, assignment_id: int) -> None:
    assignment = db.get(DepartmentAssignment, assignment_id)
    if assignment is None:
        raise ValueError(f"Assignment {assignment_id} not found.")
    db.delete(assignment)
