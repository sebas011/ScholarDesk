from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd


WORKLOAD_SHEET = "Consolidated"


def _decimal(value) -> Decimal:
    if value is None or pd.isna(value):
        return Decimal("0")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def _integer(value):
    if value is None or pd.isna(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def load_workload_assignments(path: str | Path) -> list[dict]:
    frame = pd.read_excel(path, sheet_name=WORKLOAD_SHEET, header=2)
    frame.columns = [" ".join(_text(column).split()) for column in frame.columns]

    required = {
        "College",
        "Program",
        "Campus",
        "Faculty",
        "Academic Rank",
        "Designation/ Other Assignments",
        "Course Code",
        "Descriptive Title",
        "Program/ Year/ Section",
        "Lec",
        "Lab",
        "Type of Load",
        "No. of Preps",
        "ETU for Designation/ Assignment",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing workload columns: {sorted(missing)}")

    grouped_columns = [
        "College",
        "Program",
        "Campus",
        "Faculty",
        "Academic Rank",
        "Designation/ Other Assignments",
    ]
    frame[grouped_columns] = frame[grouped_columns].ffill()

    assignments = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=4):
        course_code = _text(row.get("Course Code"))
        faculty = _text(row.get("Faculty"))

        if not course_code:
            continue

        assignments.append(
            {
                "source_row": row_number,
                "college": _text(row.get("College")),
                "program": _text(row.get("Program")),
                "campus": _text(row.get("Campus")),
                "faculty": faculty,
                "position": _text(row.get("Academic Rank")),
                "designation": _text(row.get("Designation/ Other Assignments")),
                "course_code": course_code,
                "course_title": _text(row.get("Descriptive Title")),
                "section": _text(row.get("Program/ Year/ Section")),
                "lecture": _decimal(row.get("Lec")),
                "lab": _decimal(row.get("Lab")),
                "load_type": _text(row.get("Type of Load")),
                "source_total_teaching_load": _decimal(row.get("Total Teaching Load")),
                "source_no_of_preps": _integer(row.get("No. of Preps")),
                "source_etu": _decimal(row.get("ETU for Designation/ Assignment")),
                "source_total_workload": _decimal(row.get("Total Workload")),
                "source_overload": _decimal(row.get("Over-load")),
                "remarks": _text(row.get("Remarks")),
            }
        )

    return assignments
