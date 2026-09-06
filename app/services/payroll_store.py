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

def replace_payroll_import(
    db: Session,
    workload_records: list[dict],
    projection_records: list[dict],
    audit_records: list[dict],
) -> None:
    try:
        db.query(PayrollAuditRecord).delete()
        db.query(PayrollProjectionRecord).delete()
        db.query(PayrollWorkloadAssignment).delete()

        for record in workload_records:
            db.add(PayrollWorkloadAssignment(**record))

        for record in projection_records:
            db.add(PayrollProjectionRecord(**record))

        for record in audit_records:
            db.add(
                PayrollAuditRecord(
                    source_row=record["source_row"],
                    payroll_number=record.get("number"),
                    match_status=record["match_status"],
                    match_reason=record["match_reason"],
                )
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
