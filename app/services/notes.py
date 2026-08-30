"""
ScholarNote business logic. Previously constructed and written to
directly from app/routers/records.py, unlike every other entity
(Scholar, DepartmentAssignment, Grant), which all validate and write
through a service module. Moved here to match that pattern - same
contract as the others: validate, write, return the object, or raise
InvalidScholarError/ScholarNotFoundError with a user-facing message.
"""
from sqlalchemy.orm import Session

from app.models import ScholarNote
from app.core.exceptions import InvalidScholarError, ScholarNotFoundError

CONTENT_MAX_LENGTH = 2000


def add_note(db: Session, scholar_id: int, content: str) -> ScholarNote:
    from app.services.scholars import get_scholar

    if get_scholar(db, scholar_id) is None:
        raise ScholarNotFoundError("Scholar not found.")

    content = (content or "").strip()
    if not content:
        raise InvalidScholarError("Note cannot be empty.")
    if len(content) > CONTENT_MAX_LENGTH:
        raise InvalidScholarError(f"Note is too long (max {CONTENT_MAX_LENGTH} characters).")

    note = ScholarNote(scholar_id=scholar_id, content=content)
    db.add(note)
    db.flush()  # populate note.id without committing - caller controls the transaction
    return note


def delete_note(db: Session, scholar_id: int, note_id: int) -> None:
    note = db.get(ScholarNote, note_id)
    if not note or note.scholar_id != scholar_id:
        raise ScholarNotFoundError("Note not found.")
    db.delete(note)
