"""SQLAlchemy models for imported payroll workload data."""

from decimal import Decimal

from sqlalchemy import Numeric, String, Integer
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