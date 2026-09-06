"""SQLAlchemy models for imported payroll workload data."""

from decimal import Decimal
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.payroll_database import PayrollBase


class PayrollWorkloadAssignment(PayrollBase):
    __tablename__ = "payroll_workload_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    college: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    program: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    campus: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    faculty: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    designation: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    course_code: Mapped[str] = mapped_column(String(100), nullable=False)
    course_title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    section: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    lecture: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    lab: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    load_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source_total_teaching_load: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    source_no_of_preps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_etu: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    source_total_workload: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    source_overload: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class PayrollProjectionRecord(PayrollBase):
    __tablename__ = "payroll_projection_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    campus: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    college: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    program: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    teaching_load: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    preps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excess_hours_per_week: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    total_weeks: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    weeks_absent: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    net_overload_weeks: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    hours_overload: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    salary_rate_month: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    salary_rate_hour: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    withholding_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )
    withholding_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    net_amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    semester_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class PayrollAuditRecord(PayrollBase):
    __tablename__ = "payroll_audit_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    payroll_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unresolved")
    match_reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
