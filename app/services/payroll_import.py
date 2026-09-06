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

PAYROLL_SHEET = "Consolidated - Alphabetical"


def load_payroll_projection(path: str | Path) -> list[dict]:
    frame = pd.read_excel(path, sheet_name=PAYROLL_SHEET, header=5)
    frame.columns = [" ".join(_text(column).split()) for column in frame.columns]

    required = {
        "No.",
        "Name",
        "Position",
        "Campus",
        "College",
        "Program",
        "No. of Hrs. Teaching Load",
        "No. of Prep",
        "No. of Excess Hrs./Wk",
        "Total No. of Wks.",
        "No. of Weeks Absent",
        "Net No. of Overload Wks.",
        "No. of Hours Overload",
        "Salary Rate/Month",
        "Salary Rate/Hr",
        "Amount Due",
        "Withholding Tax Rate",
        "Withholding Tax",
        "Net Amount Due",
        "Semester Salary",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing payroll columns: {sorted(missing)}")

    records = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=7):
        name = _text(row.get("Name"))
        number = _integer(row.get("No."))
        if not name and number is None:
            continue

        records.append(
            {
                "source_row": row_number,
                "number": number,
                "name": name,
                "position": _text(row.get("Position")),
                "campus": _text(row.get("Campus")),
                "college": _text(row.get("College")),
                "program": _text(row.get("Program")),
                "teaching_load": _decimal(
                    row.get("No. of Hrs. Teaching Load")
                ),
                "preps": _integer(row.get("No. of Prep")),
                "excess_hours_per_week": _decimal(
                    row.get("No. of Excess Hrs./Wk")
                ),
                "total_weeks": _decimal(row.get("Total No. of Wks.")),
                "weeks_absent": _decimal(row.get("No. of Weeks Absent")),
                "net_overload_weeks": _decimal(
                    row.get("Net No. of Overload Wks.")
                ),
                "hours_overload": _decimal(
                    row.get("No. of Hours Overload")
                ),
                "salary_rate_month": _decimal(row.get("Salary Rate/Month")),
                "salary_rate_hour": _decimal(row.get("Salary Rate/Hr")),
                "amount_due": _decimal(row.get("Amount Due")),
                "withholding_tax_rate": _decimal(
                    row.get("Withholding Tax Rate")
                ),
                "withholding_tax": _decimal(row.get("Withholding Tax")),
                "net_amount_due": _decimal(row.get("Net Amount Due")),
                "semester_salary": _decimal(row.get("Semester Salary")),
            }
        )

    return records


def audit_payroll_projection(
    records: list[dict],
    workload_faculty_names: set[str],
) -> list[dict]:
    known_names = {
        name.strip().casefold()
        for name in workload_faculty_names
        if name.strip()
    }
    audited = []

    for record in records:
        name = record["name"].strip()
        normalized_name = name.casefold()

        if not name:
            status = "unresolved"
            reason = "Faculty name is blank in the source workbook."
        elif normalized_name not in known_names:
            status = "unresolved"
            reason = "Faculty name was not found in the workload workbook."
        else:
            status = "matched"
            reason = ""

        audited.append(
            {
                **record,
                "match_status": status,
                "match_reason": reason,
            }
        )

    return audited
