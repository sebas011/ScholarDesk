"""Local HTTP Basic authentication and credential administration helpers.

Passwords written by the administrator helper use PBKDF2-HMAC-SHA256. Legacy
``password=`` files are deliberately rejected at runtime; running
``python -m app.admin`` replaces them with a non-reversible hash.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections import OrderedDict, deque
from collections.abc import Callable
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.database import app_dir
from app.core.logging import logger

CREDENTIALS_FILE = app_dir / "auth.txt"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "changeme"
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
PASSWORD_MAX_LENGTH = 128
USERNAME_MAX_LENGTH = 200
MAX_FAILED_LOGIN_ATTEMPTS = 5
FAILED_LOGIN_WINDOW_SECONDS = 60
MAX_TRACKED_LOGIN_CLIENTS = 1_024

security = HTTPBasic()


class FailedLoginRateLimiter:
    """Thread-safe, bounded failed-login limiter keyed by the client address."""

    def __init__(
        self,
        max_attempts: int = MAX_FAILED_LOGIN_ATTEMPTS,
        window_seconds: int = FAILED_LOGIN_WINDOW_SECONDS,
        max_clients: int = MAX_TRACKED_LOGIN_CLIENTS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._attempts_by_client: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def register_attempt(self, client_address: str) -> int | None:
        """Record an attempt or return seconds until this client may retry."""
        now = self._clock()
        with self._lock:
            attempts = self._attempts_by_client.get(client_address)
            if attempts is None:
                if len(self._attempts_by_client) >= self._max_clients:
                    self._attempts_by_client.pop(next(iter(self._attempts_by_client)))
                attempts = deque()
                self._attempts_by_client[client_address] = attempts

            while attempts and attempts[0] <= now - self._window_seconds:
                attempts.popleft()

            if len(attempts) >= self._max_attempts:
                return max(1, ceil(self._window_seconds - (now - attempts[0])))

            attempts.append(now)
            self._attempts_by_client.move_to_end(client_address)
            return None

    def clear(self, client_address: str) -> None:
        """Clear a client's failed attempts after a successful login."""
        with self._lock:
            self._attempts_by_client.pop(client_address, None)


failed_login_limiter = FailedLoginRateLimiter()


def _ensure_credentials_file() -> None:
    """Create a fail-closed setup file; never generate a plaintext password."""
    if not CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.write_text(
            "# Set credentials with: python -m app.admin\n"
            f"username={DEFAULT_USERNAME}\n"
            "password_hash=\n",
            encoding="utf-8",
        )


def _load_credential_values() -> dict[str, str]:
    _ensure_credentials_file()
    values: dict[str, str] = {}
    for line in CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def load_credentials() -> tuple[str, str]:
    """Return the configured username and stored credential value.

    This preserves the previous return type for callers. The second value is
    always the configured password hash; legacy plaintext values are excluded.
    """
    values = _load_credential_values()
    return values.get("username", ""), values.get("password_hash", "")


def _validate_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise ValueError("Username is required.")
    if len(username) > USERNAME_MAX_LENGTH:
        raise ValueError(f"Username is too long (max {USERNAME_MAX_LENGTH} characters).")
    if any(character in username for character in "\r\n="):
        raise ValueError("Username contains unsupported characters.")
    return username


def _validate_password(password: str) -> str:
    if not password:
        raise ValueError("Password is required.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password is too long (max {PASSWORD_MAX_LENGTH} characters).")
    return password


def hash_password(password: str) -> str:
    """Create a PBKDF2-HMAC-SHA256 record suitable for ``auth.txt``."""
    password = _validate_password(password)
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_key = base64.urlsafe_b64encode(derived_key).decode("ascii")
    return f"{PASSWORD_HASH_SCHEME}${PASSWORD_HASH_ITERATIONS}${encoded_salt}${encoded_key}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Safely verify a supported PBKDF2 record, returning False if malformed."""
    try:
        scheme, iterations_text, encoded_salt, encoded_key = stored_hash.split("$", 3)
        iterations = int(iterations_text)
        if scheme != PASSWORD_HASH_SCHEME or iterations != PASSWORD_HASH_ITERATIONS:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected_key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
        actual_key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
    except (UnicodeEncodeError, ValueError):
        return False
    return secrets.compare_digest(actual_key, expected_key)


def _is_supported_password_hash(stored_hash: str) -> bool:
    """Return whether a credential has the exact PBKDF2 record shape we support."""
    try:
        scheme, iterations_text, encoded_salt, encoded_key = stored_hash.split("$", 3)
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
    except (UnicodeEncodeError, ValueError):
        return False
    return (
        scheme == PASSWORD_HASH_SCHEME
        and iterations == PASSWORD_HASH_ITERATIONS
        and bool(salt)
        and bool(key)
    )


def set_hashed_credentials(username: str, password: str) -> None:
    """Atomically replace ``auth.txt`` with one PBKDF2-protected account."""
    username = _validate_username(username)
    password_hash = hash_password(password)
    replacement_file = CREDENTIALS_FILE.with_name(f".{CREDENTIALS_FILE.name}.new")
    replacement_file.write_text(
        "# Managed by python -m app.admin. Do not store plaintext passwords here.\n"
        f"username={username}\n"
        f"password_hash={password_hash}\n",
        encoding="utf-8",
    )
    replacement_file.replace(CREDENTIALS_FILE)


def _load_auth_record() -> tuple[str, str, bool]:
    values = _load_credential_values()
    password_hash = values.get("password_hash", "")
    if password_hash:
        return values.get("username", ""), password_hash, True
    return values.get("username", ""), values.get("password", ""), False


def using_default_password() -> bool:
    username, credential, is_hashed = _load_auth_record()
    return not username or not credential or not is_hashed


def verify_credentials(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    correct_username, stored_credential, is_hashed = _load_auth_record()
    if not correct_username or not is_hashed or not _is_supported_password_hash(stored_credential):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured. Reset credentials with ScholarDeskAdmin.",
        )

    client_address = request.client.host if request.client is not None else "unknown"
    retry_after = failed_login_limiter.register_attempt(client_address)
    if retry_after is not None:
        logger.warning("Authentication rate limit reached.")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    is_valid_username = secrets.compare_digest(credentials.username, correct_username)
    is_valid_password = verify_password(credentials.password, stored_credential)
    if not (is_valid_username and is_valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    failed_login_limiter.clear(client_address)
    return credentials.username
