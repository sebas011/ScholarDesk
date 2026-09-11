"""
Dashboard stats - mirrors modHomeStats.bas. One query instead of a
per-scholar Excel-range walk; the database does the counting.
"""

from datetime import date

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Scholar, DepartmentAssignment, Grant

KNOWN_DEPARTMENTS = {"CAS", "CBMA", "COED", "CIT", "COE", "CCS", "CCJ"}
OTHER_LABEL = "Admin Staff"


def total_scholars(db: Session) -> int:
    return db.query(func.count(Scholar.id)).scalar() or 0


def _grants_active_in_year_filter(year: int):
    """SQL WHERE-clause equivalent of grants.active_in_year(), so
    "active in year" can be filtered by the database instead of
    loading every grant row into Python to check in a loop."""
    return (
        Grant.start_year.isnot(None),
        Grant.start_year <= year,
        or_(Grant.end_year.is_(None), Grant.end_year >= year),
    )


def _assignments_active_in_year_filter(year: int):
    """SQL WHERE-clause equivalent of departments.active_in_year()."""
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    return (
        DepartmentAssignment.date_started.isnot(None),
        DepartmentAssignment.date_started <= year_end,
        or_(
            DepartmentAssignment.date_ended.is_(None),
            DepartmentAssignment.date_ended >= year_start,
        ),
    )


def total_grants(db: Session, year: int | None = None) -> int:
    """Total grant records, optionally restricted to those active in a
    given year (same active_in_year rule used everywhere else, applied
    as a SQL filter instead of a Python loop over every grant)."""
    query = db.query(func.count(Grant.id))
    if year is not None:
        query = query.filter(*_grants_active_in_year_filter(year))
    return query.scalar() or 0


def active_grants_count(db: Session, year: int | None = None) -> int:
    """Grants with status == 'Active', optionally also restricted to a
    given year - i.e. 'how many grants are currently in progress'."""
    query = db.query(Grant).filter(Grant.status == "Active")
    if year is not None:
        query = query.filter(*_grants_active_in_year_filter(year))
    return query.count()


def total_scholars_active_in_year(db: Session, year: int) -> int:
    """A scholar counts as 'active' in a year if they have at least one
    assignment or grant overlapping that year. Filtered entirely in SQL
    via subqueries rather than loading every assignment/grant row into
    Python - same rule active_in_year() encodes elsewhere, expressed as
    a query instead of a loop."""
    dept_scholar_ids = db.query(DepartmentAssignment.scholar_id).filter(
        *_assignments_active_in_year_filter(year)
    )
    grant_scholar_ids = db.query(Grant.scholar_id).filter(*_grants_active_in_year_filter(year))
    return (
        db.query(func.count(func.distinct(Scholar.id)))
        .filter(
            or_(
                Scholar.id.in_(dept_scholar_ids),
                Scholar.id.in_(grant_scholar_ids),
            )
        )
        .scalar()
        or 0
    )


def years_with_data(db: Session) -> list[int]:
    """Every year touched by any assignment or grant's start/end range,
    used to populate the year-filter dropdown. Years are clamped to a
    reasonable window to prevent garbage data (e.g. 1900-2100) from
    creating an unusable dropdown."""
    from datetime import date

    current_year = date.today().year
    min_year = current_year - 50
    max_year = current_year + 5

    years: set[int] = set()
    for date_started, date_ended in (
        db.query(DepartmentAssignment.date_started, DepartmentAssignment.date_ended)
        .filter(DepartmentAssignment.date_started.isnot(None))
        .all()
    ):
        end_year = date_ended.year if date_ended else date_started.year
        start = max(date_started.year, min_year)
        end = min(end_year, max_year)
        if start <= end:
            years.update(range(start, end + 1))

    for start_year, end_year in (
        db.query(Grant.start_year, Grant.end_year)
        .filter(Grant.start_year.isnot(None))
        .all()
    ):
        final_end = end_year if end_year else start_year
        start = max(start_year, min_year)
        end = min(final_end, max_year)
        if start <= end:
            years.update(range(start, end + 1))

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
        relevant_assignment_ids = (
            select(func.min(DepartmentAssignment.id))
            .group_by(DepartmentAssignment.scholar_id)
        )
    else:
        relevant_assignment_ids = (
            select(func.min(DepartmentAssignment.id))
            .where(*_assignments_active_in_year_filter(year))
            .group_by(DepartmentAssignment.scholar_id)
        )

    department_key = func.upper(func.trim(DepartmentAssignment.department))
    department_bucket = case(
        (department_key.in_(KNOWN_DEPARTMENTS), department_key),
        else_=OTHER_LABEL,
    )

    rows = (
        db.query(
            department_bucket.label("department"),
            func.count(DepartmentAssignment.id).label("count"),
        )
        .filter(DepartmentAssignment.id.in_(relevant_assignment_ids))
        .group_by(department_bucket)
        .all()
    )

    counts = {department: count for department, count in rows}
    assigned_count = sum(counts.values())

    # Whichever headline total index.html is showing (all-time count, or
    # count active in the selected year) should always equal the sum of
    # this table - otherwise a scholar counted as "active" up top can
    # silently vanish from the breakdown below with no row explaining
    # why, if their only activity that year was a grant, not an
    # assignment.
    total_for_bucket = (
        total_scholars(db) if year is None else total_scholars_active_in_year(db, year)
    )
    unassigned = total_for_bucket - assigned_count
    if unassigned > 0:
        counts[OTHER_LABEL] = counts.get(OTHER_LABEL, 0) + unassigned

    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
