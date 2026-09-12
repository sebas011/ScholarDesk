"""Grant Tracker-only application entry routes.

This router deliberately owns the packaged release's root page. Keeping it
separate from the unfinished payroll launcher prevents payroll imports and
their spreadsheet-processing dependencies from entering the release graph.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templates_config import templates


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def grant_tracker_launcher(request: Request) -> HTMLResponse:
    """Render the Grant Tracker landing page without importing payroll code."""
    return templates.TemplateResponse(request, "launcher.html", {"show_navigation": False})
