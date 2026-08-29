"""
ORM models. Mirrors the three Excel tables (Scholars, Departments, Grants)
but with real foreign keys instead of a shared EmployeeID string, and
DepartmentAssignment now carries date_started/date_ended - the field the
VBA version was missing, which is why "which year is this assignment
active in" was never answerable there.
"""

from datetime import date, datetime

from sqlalchemy import String, Integer, Boolean, Date, DateTime, ForeignKey, Text, func
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
    # No cascade here on purpose. ActivityLog is meant to survive a
    # scholar's deletion as an audit trail (the FK below already uses
    # ondelete="SET NULL" for exactly this reason) - "all, delete-orphan"
    # would make SQLAlchemy delete these rows itself before the database's
    # SET NULL constraint ever gets a chance to run, silently destroying
    # the audit history the whole table exists to preserve.
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        back_populates="scholar", order_by="ActivityLog.id.desc()"
    )
    notes: Mapped[list["ScholarNote"]] = relationship(
        back_populates="scholar", cascade="all, delete-orphan", order_by="ScholarNote.id.desc()"
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
    # Indexed - these are the columns list_scholars/total_scholars_active_in_year/
    # department_distribution filter on via SQL WHERE clauses (see
    # app/services/stats.py's _assignments_active_in_year_filter). Without
    # an index, every one of those queries is a full table scan.
    date_started: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    date_ended: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

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
    date_started: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_ended: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    end_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    extension: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="Active", nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    scholar: Mapped["Scholar"] = relationship(back_populates="grants")
    reviews: Mapped[list["GrantReview"]] = relationship(
        back_populates="grant", cascade="all, delete-orphan", order_by="GrantReview.id.desc()"
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int | None] = mapped_column(
        ForeignKey("scholars.id", ondelete="SET NULL"), index=True, nullable=True
    )
    category: Mapped[str] = mapped_column(String(50), default="system")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    scholar: Mapped["Scholar"] = relationship(back_populates="activity_logs")


class ScholarNote(Base):
    __tablename__ = "scholar_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    scholar: Mapped["Scholar"] = relationship(back_populates="notes")


class GrantReview(Base):
    __tablename__ = "grant_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("grants.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(50), default="pending")
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    grant: Mapped["Grant"] = relationship(back_populates="reviews")
