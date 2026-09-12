from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from urllib.parse import urlsplit
import secrets
from app.core.request_limits import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from app.database import Base, app_dir, engine
from app.migrations import ensure_schema_version, existing_table_names
from app.routers import scholars, records, launcher
from app.templates_config import STATIC_DIRECTORY, templates

from fastapi import Depends

from app.core.logging import configure_logging
from app.core.logging import logger

from app.core.auth import verify_credentials

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize the portable app database and release connections on shutdown."""
    database_was_empty = not existing_table_names(engine)
    if database_was_empty:
        Base.metadata.create_all(bind=engine)
    ensure_schema_version(
        engine,
        database_was_empty=database_was_empty,
        backup_directory=app_dir / "backups",
    )
    logger.info("Grant Tracker started successfully.")
    try:
        yield
    finally:
        engine.dispose()
        logger.info("Grant Tracker stopped.")

app = FastAPI(
    title="Grant Tracking System",
    lifespan=lifespan,
    dependencies=[Depends(verify_credentials)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
app.include_router(scholars.router)
app.include_router(records.router)
app.include_router(launcher.router)


@app.get("/health", dependencies=[Depends(verify_credentials)])
def health_check() -> JSONResponse:
    """Report whether this process can read Grant Tracker's core table."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM scholars LIMIT 1"))
    except SQLAlchemyError:
        logger.exception("Health check database probe failed.")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ok"})

PAYROLL_PATH_PREFIX = "/payroll"
UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_COOKIE_NAME = "scholardesk_csrf"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
VENDORED_STATIC_PATH_PREFIX = "/static/vendor/"

@app.middleware("http")
async def apply_security_headers_and_hide_payroll(request: Request, call_next):
    if request.url.path.startswith(VENDORED_STATIC_PATH_PREFIX):
        response = await call_next(request)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
    should_set_csrf_cookie = csrf_token is None
    csp_nonce = secrets.token_urlsafe(24)

    if csrf_token is None:
        csrf_token = secrets.token_urlsafe(32)

    request.state.csrf_token = csrf_token
    request.state.csp_nonce = csp_nonce

    if request.url.path == PAYROLL_PATH_PREFIX or request.url.path.startswith(
        f"{PAYROLL_PATH_PREFIX}/"
    ):
        response = HTMLResponse(status_code=404)
    elif request.method in UNSAFE_HTTP_METHODS:
        origin = request.headers.get("origin")
        origin_host = urlsplit(origin).netloc.lower() if origin else ""
        request_host = request.headers.get("host", "").lower()

        submitted_token = request.headers.get(CSRF_HEADER_NAME)
        if submitted_token is None:
            form = await request.form()
            submitted_token = form.get(CSRF_FORM_FIELD)

        if (
            origin
            and (not request_host or origin_host != request_host)
        ) or (
            not isinstance(submitted_token, str)
            or not secrets.compare_digest(submitted_token, csrf_token)
        ):
            response = HTMLResponse(status_code=403)
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)

    if should_set_csrf_cookie:
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_token,
            httponly=False,
            samesite="strict",
            path="/",
        )

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        f"script-src 'self' 'nonce-{csp_nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response

app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=MAX_REQUEST_BODY_BYTES,
)

def _render_error(request: Request, message: str, status_code: int, headers: dict | None = None):
    """Render a generic HTML error message for both standard and htmx requests."""
    try:
        template_name = (
            "partials/generic_error.html"
        if request.headers.get("HX-Request") == "true"
        else "error.html"
)
        return templates.TemplateResponse(
    request,
    template_name,
            {"error": message},
            status_code=status_code,
            headers=headers or {},
        )
    except Exception:
        response = HTMLResponse(
            content=f"<div class='error'>{message}</div>",
            status_code=status_code,
        )
        if headers:
            for key, value in headers.items():
                response.headers[key] = value
        return response


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    """A blank/malformed required field (e.g. Name left empty) would
    otherwise return raw FastAPI JSON straight into an htmx swap target,
    which just dumps '{"detail": ...}' text into the page. Render the
    same styled error partial every other failure path uses instead."""
    missing = [".".join(str(p) for p in err["loc"] if p != "body") for err in exc.errors()]
    message = f"Please fill in: {', '.join(missing)}" if missing else "Invalid submission."
    if request.method == "POST" and request.url.path == "/scholars/new":
        form = await request.form()
        return templates.TemplateResponse(
            request,
            "scholar_new.html",
            {
                "error": message,
                "form": {
                    "name": str(form.get("name", "")),
                    "age": str(form.get("age", "")),
                    "previous_degree": str(form.get("previous_degree", "")),
                    "department": str(form.get("department", "")),
                    "rank": str(form.get("rank", "")),
                    "tenure": str(form.get("tenure", "")),
                },
            },
            status_code=422,
        )

    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
        request,
        "partials/generic_error.html",
        {"error": message},
        status_code=422,
    )
    return _render_error(request, message, status_code=422)


def _is_sqlite_lock_error(exc: Exception) -> bool:
    """Return whether SQLAlchemy wrapped a transient SQLite lock failure."""
    if not isinstance(exc, OperationalError):
        return False

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "database schema is locked",
        )
    )


@app.exception_handler(Exception)
def on_unhandled_exception(request: Request, exc: Exception):
    """Last-resort safety net: anything that isn't RequestValidationError
    or already caught by a route's own try/except lands here instead of
    a raw framework 500. Logs the real exception for debugging, shows
    the user a generic message - never the exception text itself, since
    an unexpected exception (unlike our own ValueError messages) hasn't
    been vetted as safe to display."""
    if _is_sqlite_lock_error(exc):
        logger.warning(
            "SQLite lock timeout on %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _render_error(
    request,
    "Database is busy. Please try again shortly.",
    status_code=503,
    headers={"Retry-After": "1"},
)
    logger.error(
    "Unhandled exception on %s %s",
    request.method,
    request.url.path,
    exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _render_error(
    request,
    "Something went wrong. Please try again.",
    status_code=500,
)
