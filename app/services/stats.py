"""
Dashboard stats - mirrors modHomeStats.bas. One query instead of a
per-scholar Excel-range walk; the database does the counting.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Scholar, DepartmentAssignment, Grant
from app.services.departments import active_in_year as assignment_active_in_year
from app.services.grants import active_in_year as grant_active_in_year

KNOWN_DEPARTMENTS = {"CAS", "CBMA", "COED", "CIT", "COE", "CCS", "CCJ"}
OTHER_LABEL = "Admin Staff"


def total_scholars(db: Session) -> int:
    return db.query(func.count(Scholar.id)).scalar() or 0


def total_scholars_active_in_year(db: Session, year: int) -> int:
    """A scholar counts as 'active' in a year if they have at least one
    assignment or grant overlapping that year - reuses the exact same
    active_in_year() rule the service layer already uses elsewhere, so
    there's still only one definition of what a year filter means."""
    scholar_ids: set[int] = set()
    for a in db.query(DepartmentAssignment).all():
        if assignment_active_in_year(a, year):
            scholar_ids.add(a.scholar_id)
    for g in db.query(Grant).all():
        if grant_active_in_year(g, year):
            scholar_ids.add(g.scholar_id)
    return len(scholar_ids)


def years_with_data(db: Session) -> list[int]:
    """Every year touched by any assignment or grant's start/end range,
    used to populate the year-filter dropdown so it only ever shows
    years that actually have something in them."""
    years: set[int] = set()
    for a in db.query(DepartmentAssignment).all():
        if a.date_started:
            end_year = a.date_ended.year if a.date_ended else a.date_started.year
            years.update(range(a.date_started.year, end_year + 1))
    for g in db.query(Grant).all():
        if g.date_started:
            end_year = g.date_ended.year if g.date_ended else g.date_started.year
            years.update(range(g.date_started.year, end_year + 1))
    return sorted(years, reverse=True)


def department_distribution(db: Session, year: int | None = None) -> dict[str, int]:
    """Each scholar counted under their PRIMARY (earliest) assignment only,
    so the totals sum to total_scholars() - same rule the VBA version used,
    now expressed as one query instead of a per-scholar lookup loop.

    With `year` set, only counts assignments active in that year (and
    within that, still the earliest-in-year one per scholar), instead of
    each scholar's all-time first assignment - so switching the year
    filter reflects who was actually where that year."""
    if year is None:
        primary_ids = select(func.min(DepartmentAssignment.id)).group_by(
            DepartmentAssignment.scholar_id
        )
        relevant_assignments = (
            db.query(DepartmentAssignment).filter(DepartmentAssignment.id.in_(primary_ids)).all()
        )
    else:
        by_scholar: dict[int, DepartmentAssignment] = {}
        for a in db.query(DepartmentAssignment).order_by(DepartmentAssignment.id).all():
            if assignment_active_in_year(a, year) and a.scholar_id not in by_scholar:
                by_scholar[a.scholar_id] = a
        relevant_assignments = list(by_scholar.values())

    counts: dict[str, int] = {}
    assigned_scholar_ids = set()
    for a in relevant_assignments:
        assigned_scholar_ids.add(a.scholar_id)
        dept_key = (a.department or "").strip().upper()
        if dept_key not in KNOWN_DEPARTMENTS:
            dept_key = OTHER_LABEL
        counts[dept_key] = counts.get(dept_key, 0) + 1

    if year is None:
        unassigned = total_scholars(db) - len(assigned_scholar_ids)
        if unassigned > 0:
            counts[OTHER_LABEL] = counts.get(OTHER_LABEL, 0) + unassigned

    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
