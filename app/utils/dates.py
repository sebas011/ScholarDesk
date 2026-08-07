from __future__ import annotations

from datetime import date, datetime


def parse_date(value: str | None) -> date | None:
    """
    Parse an ISO date string (YYYY-MM-DD).

    Returns
    -------
    date | None
        Parsed date if valid, otherwise None.

    Examples
    --------
    >>> parse_date("2025-01-01")
    datetime.date(2025, 1, 1)

    >>> parse_date("")
    None

    >>> parse_date(None)
    None

    >>> parse_date("not-a-date")
    None
    """

    if not value:
        return None

    value = value.strip()

    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()

    except ValueError:
        return None

def range_active_in_year(
    start,
    end,
    year: int,
) -> bool:
    """Shared rule for "does a [start, end] span count as active in
    `year`?" - used by DepartmentAssignment.active_in_year and
    Grant.active_in_year so the two record types can't quietly drift
    into different definitions of "active".

    No start date -> can't place it in any year -> False.
    No end date -> treated as still ongoing.
    """
    if start is None:
        return False
    if year < start.year:
        return False
    if end is not None and year > end.year:
        return False
    return True
