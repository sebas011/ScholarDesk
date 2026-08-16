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
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Scholar

from app.core.logging import logger
from app.core.exceptions import (
    ScholarNotFoundError,
)

ROWS_SHOWN_BY_DEFAULT = 10


def build_detail_context(
    db: Session,
    scholar: Scholar | None,
    show_all_assignments: bool = False,
    show_all_grants: bool = False,
    error: str | None = None,
    notice: str | None = None,
) -> dict:
    """The one place that builds the scholar_detail.html template
    context. Every route that renders that template must go through
    this instead of hand-building the dict - five near-identical
    copies of this logic already existed across scholars.py and
    records.py, and a missing key in one of them already shipped a
    real crash (assignments_total undefined) once. One function means
    one place to get it right."""
    if scholar is None:
        return {"scholar": None, "error": error, "notice": notice}

    from app.services import departments as dept_service
    from app.services import grants as grant_service

    all_assignments = dept_service.list_for_scholar(db, scholar.id)
    all_grants = grant_service.list_for_scholar(db, scholar.id)
    return {
        "scholar": scholar,
        "assignments": all_assignments
        if show_all_assignments
        else all_assignments[:ROWS_SHOWN_BY_DEFAULT],
        "assignments_total": len(all_assignments),
        "show_all_assignments": show_all_assignments,
        "grants": all_grants if show_all_grants else all_grants[:ROWS_SHOWN_BY_DEFAULT],
        "grants_total": len(all_grants),
        "show_all_grants": show_all_grants,
        "error": error,
        "notice": notice,
    }


def get_full_scholar_data(db: Session) -> list[dict]:
    """Every scholar with all their assignments and grants, grouped -
    the data behind the /dashboard wide table. Three queries total
    (all scholars, all assignments, all grants), grouped in Python by
    scholar_id, rather than one query per scholar - the same N+1
    pattern the rest of the app avoids. Lives here rather than in the
    router so /dashboard follows the same router -> service -> model
    pattern every other route does."""
    from app.models import DepartmentAssignment, Grant

    all_scholars = db.query(Scholar).order_by(Scholar.name).all()
    all_assignments = db.query(DepartmentAssignment).order_by(DepartmentAssignment.id).all()
    all_grants = db.query(Grant).order_by(Grant.id).all()

    assignments_by_scholar: dict[int, list] = {}
    for a in all_assignments:
        assignments_by_scholar.setdefault(a.scholar_id, []).append(a)

    grants_by_scholar: dict[int, list] = {}
    for g in all_grants:
        grants_by_scholar.setdefault(g.scholar_id, []).append(g)

    return [
        {
            "scholar": s,
            "assignments": assignments_by_scholar.get(s.id, []),
            "grants": grants_by_scholar.get(s.id, []),
        }
        for s in all_scholars
    ]


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
    or grant overlapping that year. Filtered entirely in SQL via two
    subqueries rather than loading every assignment/grant row into
    Python - the range check (start <= year <= end, or end is None for
    "still ongoing") matches the same rule active_in_year() encodes
    elsewhere, just expressed as a query instead of a Python loop."""
    query = db.query(Scholar)
    if search:
        query = query.filter(Scholar.name.ilike(f"%{search}%"))

    if year is not None:
        from app.models import DepartmentAssignment, Grant

        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)

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
            Grant.start_year <= year,
            or_(Grant.end_year.is_(None), Grant.end_year >= year),
        )
        query = query.filter(
            or_(
                Scholar.id.in_(dept_scholar_ids),
                Scholar.id.in_(grant_scholar_ids),
            )
        )

    total = query.count()
    results = query.order_by(Scholar.name).offset(offset).limit(limit).all()
    return results, total


def get_scholar(db: Session, scholar_id: int) -> Scholar | None:
    return db.get(Scholar, scholar_id)


def find_scholar_by_name(db: Session, name: str) -> Scholar | None:
    """Case-insensitive exact match - used for the duplicate-name warning."""
    return db.query(Scholar).filter(Scholar.name.ilike(name.strip())).first()


NAME_MAX_LENGTH = 200
PREVIOUS_DEGREE_MAX_LENGTH = 300
AGE_MIN = 15
AGE_MAX = 100


def _validate_age(age: int | None) -> None:
    """Shared by create_scholar and update_scholar. The form already
    rejects non-digit input, but doesn't stop something like 99999 -
    this is a sanity range, not a strict legal-eligibility rule, so
    it's intentionally generous (covers any realistic scholar)."""
    if age is not None and not (AGE_MIN <= age <= AGE_MAX):
        raise ValueError(f"Age must be between {AGE_MIN} and {AGE_MAX}.")


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
    if len(name) > NAME_MAX_LENGTH:
        raise ValueError(f"Scholar name is too long (max {NAME_MAX_LENGTH} characters).")
    previous_degree = (previous_degree or "").strip()
    if len(previous_degree) > PREVIOUS_DEGREE_MAX_LENGTH:
        raise ValueError(
            f"Previous degree is too long (max {PREVIOUS_DEGREE_MAX_LENGTH} characters)."
        )
    _validate_age(age)

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
    if len(name) > NAME_MAX_LENGTH:
        raise ValueError(f"Scholar name is too long (max {NAME_MAX_LENGTH} characters).")
    previous_degree = (previous_degree or "").strip()
    if len(previous_degree) > PREVIOUS_DEGREE_MAX_LENGTH:
        raise ValueError(
            f"Previous degree is too long (max {PREVIOUS_DEGREE_MAX_LENGTH} characters)."
        )
    _validate_age(age)

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
