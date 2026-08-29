"""
Application-specific exceptions.

These exceptions represent business/domain errors and should be raised
by the service layer instead of generic ValueError.
"""


class AppError(Exception):
    """Base class for all application exceptions."""


# ---------------------------------------------------------------------
# Scholar Exceptions
# ---------------------------------------------------------------------


class ScholarError(AppError):
    """Base class for scholar-related errors."""


class ScholarNotFoundError(ScholarError):
    """Raised when a scholar cannot be found."""


class DuplicateScholarError(ScholarError):
    """Raised when attempting to create a duplicate scholar."""


class InvalidScholarError(ScholarError):
    """Raised when scholar data fails validation."""


# ---------------------------------------------------------------------
# Department Exceptions
# ---------------------------------------------------------------------


class DepartmentError(AppError):
    """Base class for department assignment errors."""


class AssignmentNotFoundError(DepartmentError):
    """Raised when an assignment cannot be found."""


class AssignmentOverlapError(DepartmentError):
    """Raised when assignments overlap."""


# ---------------------------------------------------------------------
# Grant Exceptions
# ---------------------------------------------------------------------


class GrantError(AppError):
    """Base class for grant-related errors."""


class GrantNotFoundError(GrantError):
    """Raised when a grant cannot be found."""
