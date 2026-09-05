"""
Platform launcher - the first page after logging in. Picks between the
apps living under this one shared login/deployment (scholar tracking,
and, in progress, faculty workload/payroll). Its own tiny router
rather than folded into scholars.py, since it isn't scholar-specific
and payroll will need the same "which app" concept once it exists.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templates_config import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def launcher(request: Request):
    return templates.TemplateResponse(request, "launcher.html", {})


@router.get("/payroll", response_class=HTMLResponse)
def payroll_placeholder(request: Request):
    """Placeholder until the Faculty Workload & Payroll module exists -
    keeps the launcher's link from 404ing in the meantime."""
    return templates.TemplateResponse(request, "payroll_placeholder.html", {})
