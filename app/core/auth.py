"""
Single shared username/password gate for the whole app, via HTTP Basic
Auth (the browser's built-in login prompt - no custom login page or
session handling needed).

Credentials live in a plain-text file next to grants.db, not an
environment variable - this app is meant to be handed to non-technical
people, and "edit this text file" is a much lower bar than "set a
Windows environment variable." Auto-generated with an obvious default
on first run so the app works out of the box, paired with a startup
check (see app/main.py) that refuses to bind to anything but localhost
until that default is changed.
"""
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.database import app_dir

CREDENTIALS_FILE = app_dir / "auth.txt"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "changeme"

security = HTTPBasic()


def _ensure_credentials_file() -> None:
    if not CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.write_text(
            f"username={DEFAULT_USERNAME}\npassword={DEFAULT_PASSWORD}\n",
            encoding="utf-8",
        )


def load_credentials() -> tuple[str, str]:
    """Re-read on every request (not cached) so editing auth.txt while
    the app is running takes effect without a restart."""
    _ensure_credentials_file()
    values: dict[str, str] = {}
    for line in CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return (
        values.get("username", DEFAULT_USERNAME),
        values.get("password", DEFAULT_PASSWORD),
    )


def using_default_password() -> bool:
    _, password = load_credentials()
    return password == DEFAULT_PASSWORD


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    correct_username, correct_password = load_credentials()
    # secrets.compare_digest instead of == - avoids leaking timing
    # information about how many characters matched, standard practice
    # for comparing secrets even in a low-stakes local-network app.
    is_valid_username = secrets.compare_digest(credentials.username, correct_username)
    is_valid_password = secrets.compare_digest(credentials.password, correct_password)
    if not (is_valid_username and is_valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
