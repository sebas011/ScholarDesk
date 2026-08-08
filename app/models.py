"""
ORM models. Mirrors the three Excel tables (Scholars, Departments, Grants)
but with real foreign keys instead of a shared EmployeeID string, and
DepartmentAssignment now carries date_started/date_ended - the field the
VBA version was missing, which is why "which year is this assignment
active in" was never answerable there.
"""
from datetime import date

from sqlalchemy import String, Integer, Boolean, Date, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Scholar(Base):
    __tablename__ = "scholars"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_degree: Mapped[str | None] = mapped_column(String(300), nullable=True)
    missing_requirements: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    assignments: Mapped[list["DepartmentAssignment"]] = relationship(
        back_populates="scholar", cascade="all, delete-orphan", order_by="DepartmentAssignment.id"
    )
    grants: Mapped[list["Grant"]] = relationship(
        back_populates="scholar", cascade="all, delete-orphan", order_by="Grant.id"
    )


class DepartmentAssignment(Base):
    __tablename__ = "department_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    rank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tenure: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_started: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_ended: Mapped[date | None] = mapped_column(Date, nullable=True)

    scholar: Mapped["Scholar"] = relationship(back_populates="assignments")


class Grant(Base):
    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    program_applied: Mapped[str] = mapped_column(String(300), nullable=False)
    type_of_grant: Mapped[str | None] = mapped_column(String(150), nullable=True)
    delivering_hei: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_started: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_ended: Mapped[date | None] = mapped_column(Date, nullable=True)
    extension: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="Active", nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    scholar: Mapped["Scholar"] = relationship(back_populates="grants")
