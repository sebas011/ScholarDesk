from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.database import Base, engine
from app.routers import scholars, records
from app.templates_config import templates

from app.core.logging import configure_logging
from app.core.logging import logger

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize the portable app database and release connections on shutdown."""
    Base.metadata.create_all(bind=engine)
    logger.info("Grant Tracker started successfully.")
    try:
        yield
    finally:
        engine.dispose()
        logger.info("Grant Tracker stopped.")


app = FastAPI(title="Grant Tracking System", lifespan=lifespan)

app.include_router(scholars.router)
app.include_router(records.router)


@app.exception_handler(RequestValidationError)
def on_validation_error(request: Request, exc: RequestValidationError):
    """A blank/malformed required field (e.g. Name left empty) would
    otherwise return raw FastAPI JSON straight into an htmx swap target,
    which just dumps '{"detail": ...}' text into the page. Render the
    same styled error partial every other failure path uses instead."""
    missing = [".".join(str(p) for p in err["loc"] if p != "body") for err in exc.errors()]
    message = f"Please fill in: {', '.join(missing)}" if missing else "Invalid submission."
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {"scholar": None, "error": message},
        status_code=422,
    )


@app.exception_handler(Exception)
def on_unhandled_exception(request: Request, exc: Exception):
    """Last-resort safety net: anything that isn't RequestValidationError
    or already caught by a route's own try/except lands here instead of
    a raw framework 500. Logs the real exception for debugging, shows
    the user a generic message - never the exception text itself, since
    an unexpected exception (unlike our own ValueError messages) hasn't
    been vetted as safe to display."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return templates.TemplateResponse(
        request,
        "partials/scholar_detail.html",
        {"scholar": None, "error": "Something went wrong. Please try again."},
        status_code=500,
    )
