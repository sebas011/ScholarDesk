"""
Scholar business logic. This module is the direct descendant of
modScholars.bas - same responsibilities (validate, write, return a
clear result), same shape, on purpose so the VBA->web port stayed a
translation exercise rather than a redesign.

Every write function returns the ORM object or raises ValueError with
a message meant to be shown directly to the user - the same contract
the VBA (ok As Boolean, outMsg As String) pattern had, just using
exceptions instead of out-parameters because that's idiomatic here.
"""
from sqlalchemy.orm import Session

from app.models import Scholar

from app.core.logging import logger
from app.core.exceptions import (
    ScholarNotFoundError,
)


def list_scholars(
    db: Session,
    search: str | None = None,
    year: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Scholar], int]:
    """Capped at `limit` (default 100) so the sidebar list stays fast at
    1,000+ scholars - without this, every keystroke in search re-renders
    every row in the table. Returns (page_of_results, total_matching_count)
    so the UI can show 'X of Y' and a Load More button.

    `year`, when set, restricts to scholars with at least one assignment
    or grant overlapping that year - reuses the same active_in_year()
    rule as the dashboard, so the list and the stats never disagree."""
    query = db.query(Scholar)
    if search:
        query = query.filter(Scholar.name.ilike(f"%{search}%"))

    if year is not None:
        from app.models import DepartmentAssignment, Grant
        from app.services.departments import active_in_year as assignment_active_in_year
        from app.services.grants import active_in_year as grant_active_in_year

        matching_ids: set[int] = set()
        for a in db.query(DepartmentAssignment).all():
            if assignment_active_in_year(a, year):
                matching_ids.add(a.scholar_id)
        for g in db.query(Grant).all():
            if grant_active_in_year(g, year):
                matching_ids.add(g.scholar_id)
        query = (
            query.filter(Scholar.id.in_(matching_ids))
            if matching_ids
            else query.filter(Scholar.id == None)  # noqa: E711 - SQLAlchemy needs `== None` to build IS NULL; `is None` would do a Python identity check, not build SQL, and silently return no filter at all.
        )

    total = query.count()
    results = query.order_by(Scholar.name).offset(offset).limit(limit).all()
    return results, total


def get_scholar(db: Session, scholar_id: int) -> Scholar | None:
    return db.get(Scholar, scholar_id)


def find_scholar_by_name(db: Session, name: str) -> Scholar | None:
    """Case-insensitive exact match - used for the duplicate-name warning."""
    return db.query(Scholar).filter(Scholar.name.ilike(name.strip())).first()


def create_scholar(
    db: Session,
    name: str,
    age: int | None,
    previous_degree: str | None,
    missing_requirements: bool,
) -> Scholar:
    name = (name or "").strip()
    if not name:
        raise ValueError("Scholar name is required.")

    scholar = Scholar(
        name=name,
        age=age,
        previous_degree=(previous_degree or "").strip() or None,
        missing_requirements=missing_requirements,
    )
    try:
        db.add(scholar)
        db.flush()  # populate scholar.id without committing yet - caller controls the transaction
        logger.info(
            "Created scholar '%s'.",
            scholar.name,
        )
    except Exception:
        logger.exception(
            "Unexpected error while creating scholar '%s'.",
            name,
        )
        raise
    return scholar


def update_scholar(
    db: Session,
    scholar_id: int,
    name: str,
    age: int | None,
    previous_degree: str | None,
    missing_requirements: bool,
) -> Scholar:
    scholar = get_scholar(db, scholar_id)
    if scholar is None:
        raise ScholarNotFoundError("Scholar not found.")

    name = (name or "").strip()
    if not name:
        raise ValueError("Scholar name is required.")

    try:
        scholar.name = name
        scholar.age = age
        scholar.previous_degree = (
            (previous_degree or "").strip() or None
        )
        scholar.missing_requirements = missing_requirements

        logger.info(
            "Updated scholar id=%s.",
            scholar.id,
        )

    except Exception:
        logger.exception(
            "Unexpected error while updating scholar id=%s.",
            scholar_id,
        )
        raise

    return scholar


def delete_scholar(db: Session, scholar_id: int) -> None:
    """Cascade-deletes assignments and grants via the relationship's
    cascade="all, delete-orphan" - no manual multi-table loop needed,
    unlike the VBA version's hand-rolled cascade in cmdDelete_Click."""
    scholar = get_scholar(db, scholar_id)
    if scholar is None:
        logger.warning(
            "Attempted to delete non-existent scholar id=%s.",
            scholar_id,
        )
        raise ScholarNotFoundError("Scholar not found.")

    try:
        db.delete(scholar)

        logger.info(
            "Deleted scholar id=%s.",
            scholar_id,
        )

    except Exception:
        logger.exception(
            "Unexpected error while deleting scholar id=%s.",
            scholar_id,
        )
        raise
