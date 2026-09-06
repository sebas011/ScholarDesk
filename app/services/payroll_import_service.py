from pathlib import Path

from sqlalchemy.orm import Session

from app.services.payroll_import import (
    audit_payroll_projection,
    load_payroll_projection,
    load_workload_assignments,
)
from app.services.payroll_store import (
    replace_payroll_audits,
    replace_payroll_projections,
    replace_workload_assignments,
)


def import_payroll_workbooks(
    db: Session,
    workload_path: str | Path,
    projection_path: str | Path,
) -> dict:
    workload_records = load_workload_assignments(workload_path)
    projection_records = load_payroll_projection(projection_path)

    workload_names = {
        record["faculty"]
        for record in workload_records
        if record["faculty"].strip()
    }
    audited_records = audit_payroll_projection(
        projection_records,
        workload_names,
    )

    replace_workload_assignments(db, workload_records)
    replace_payroll_projections(db, projection_records)
    replace_payroll_audits(db, audited_records)

    matched = sum(
        record["match_status"] == "matched"
        for record in audited_records
    )

    return {
        "workload_records": len(workload_records),
        "projection_records": len(projection_records),
        "matched_records": matched,
        "unresolved_records": len(audited_records) - matched,
    }
