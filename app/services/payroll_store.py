from sqlalchemy.orm import Session

from app.payroll_models import (
    PayrollAuditRecord,
    PayrollProjectionRecord,
    PayrollWorkloadAssignment,
)

def replace_workload_assignments(
    db: Session,
    records: list[dict],
) -> int:
    db.query(PayrollWorkloadAssignment).delete()

    for record in records:
        db.add(PayrollWorkloadAssignment(**record))

    db.commit()
    return len(records)


def replace_payroll_projections(
    db: Session,
    records: list[dict],
) -> int:
    db.query(PayrollProjectionRecord).delete()

    for record in records:
        db.add(PayrollProjectionRecord(**record))

    db.commit()
    return len(records)

def replace_payroll_audits(
    db: Session,
    records: list[dict],
) -> int:
    db.query(PayrollAuditRecord).delete()

    for record in records:
        db.add(
            PayrollAuditRecord(
                source_row=record["source_row"],
                payroll_number=record.get("number"),
                match_status=record["match_status"],
                match_reason=record["match_reason"],
            )
        )

    db.commit()
    return len(records)
