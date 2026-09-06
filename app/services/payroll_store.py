from sqlalchemy.orm import Session

from app.payroll_models import PayrollProjectionRecord, PayrollWorkloadAssignment


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
