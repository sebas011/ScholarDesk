"""Browser session login and logout routes."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.auth import authenticate_user
from app.templates_config import templates


router = APIRouter()


def _safe_next_path(value: str | None) -> str:
    """Allow only local, absolute redirect destinations after login."""
    if not value:
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return "/"
    return value


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = None) -> HTMLResponse:
    if request.session.get("username"):
        return RedirectResponse(url=_safe_next_path(next), status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "username": "", "next": _safe_next_path(next), "show_navigation": False},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
) -> HTMLResponse:
    destination = _safe_next_path(next)
    try:
        authenticated_username = authenticate_user(request, username, password)
    except HTTPException as error:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": str(error.detail),
                "username": username.strip(),
                "next": destination,
                "show_navigation": False,
            },
            status_code=error.status_code,
            headers=error.headers,
        )

    request.session.clear()
    request.session["username"] = authenticated_username
    return RedirectResponse(url=destination, status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
