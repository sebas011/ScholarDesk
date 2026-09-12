"""Local HTTP Basic authentication and credential administration helpers.

Passwords written by the administrator helper use PBKDF2-HMAC-SHA256. Legacy
``password=`` files are deliberately rejected at runtime; running
``python -m app.admin`` replaces them with a non-reversible hash.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from collections import OrderedDict, deque
from collections.abc import Callable
from contextlib import contextmanager
from math import ceil
from pathlib import Path
from threading import Lock
from time import monotonic

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.database import app_dir
from app.core.logging import logger

CREDENTIALS_FILE = app_dir / "auth.txt"
USERS_FILE_NAME = "users.json"
USERS_LOCK_FILE_NAME = "users.json.lock"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "changeme"
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
USERNAME_MAX_LENGTH = 200
# Used only to make unknown-user attempts perform the same PBKDF2 work as
# incorrect-password attempts. It is not an account credential.
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$DWHTXQv0vA8OlA5z-srD8w==$"
    "NAa6CYLnIicHiANh7q7U1wUjWf4_C14VBtiybM3aQnU="
)
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

    def _retry_after(self, attempts: deque[float], now: float) -> int | None:
        while attempts and attempts[0] <= now - self._window_seconds:
            attempts.popleft()
        if len(attempts) < self._max_attempts:
            return None
        return max(1, ceil(self._window_seconds - (now - attempts[0])))

    def retry_after(self, client_address: str) -> int | None:
        """Return a current block period without recording a new attempt."""
        now = self._clock()
        with self._lock:
            attempts = self._attempts_by_client.get(client_address)
            if attempts is None:
                return None
            retry_after = self._retry_after(attempts, now)
            if attempts:
                self._attempts_by_client.move_to_end(client_address)
            else:
                self._attempts_by_client.pop(client_address, None)
            return retry_after

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

            retry_after = self._retry_after(attempts, now)
            if retry_after is not None:
                return retry_after

            attempts.append(now)
            self._attempts_by_client.move_to_end(client_address)
            return self._retry_after(attempts, now)

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
    if password.isspace():
        raise ValueError("Password cannot contain only whitespace.")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
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


def _users_file() -> Path:
    return CREDENTIALS_FILE.with_name(USERS_FILE_NAME)


@contextmanager
def _user_registry_write_lock():
    """Serialize account changes across local administrator processes."""
    lock_file_path = CREDENTIALS_FILE.with_name(USERS_LOCK_FILE_NAME)
    with lock_file_path.open("a+b") as lock_file:
        lock_file.seek(0, 2)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_users(users: dict[str, str]) -> None:
    users_file = _users_file()
    replacement = users_file.with_name(f".{users_file.name}.new")
    replacement.write_text(json.dumps({"version": 1, "users": users}, indent=2), encoding="utf-8")
    replacement.replace(users_file)


def _load_users_file() -> dict[str, str] | None:
    users_file = _users_file()
    if not users_file.exists():
        return None
    try:
        payload = json.loads(users_file.read_text(encoding="utf-8"))
        users = payload["users"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}
    return {
        username: password_hash
        for username, password_hash in users.items()
        if isinstance(username, str)
        and isinstance(password_hash, str)
        and _is_supported_password_hash(password_hash)
    }


def _legacy_users() -> dict[str, str]:
    username, password_hash, is_hashed = _load_auth_record()
    if username and is_hashed and _is_supported_password_hash(password_hash):
        return {username: password_hash}
    return {}


def load_users() -> dict[str, str]:
    users = _load_users_file()
    if users is not None:
        return users

    with _user_registry_write_lock():
        users = _load_users_file()
        if users is not None:
            return users
        users = _legacy_users()
        if users:
            _write_users(users)
        return users


def set_user_password(username: str, password: str) -> None:
    username = _validate_username(username)
    with _user_registry_write_lock():
        users = _load_users_file()
        if users is None:
            users = _legacy_users()
        users[username] = hash_password(password)
        _write_users(users)


def list_usernames() -> list[str]:
    """Return local administrator usernames without exposing password hashes."""
    return sorted(load_users())


def remove_user(username: str) -> None:
    """Revoke one local administrator while preserving a recovery account."""
    username = _validate_username(username)
    with _user_registry_write_lock():
        users = _load_users_file()
        if users is None:
            users = _legacy_users()
        if username not in users:
            raise ValueError(f"User '{username}' was not found.")
        if len(users) == 1:
            raise ValueError("Cannot remove the final administrator account.")

        del users[username]
        _write_users(users)


def _load_auth_record() -> tuple[str, str, bool]:
    values = _load_credential_values()
    password_hash = values.get("password_hash", "")
    if password_hash:
        return values.get("username", ""), password_hash, True
    return values.get("username", ""), values.get("password", ""), False


def using_default_password() -> bool:
    return not load_users()


def verify_credentials(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    users = load_users()
    if not users:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured. Reset credentials with ScholarDeskAdmin.",
        )

    client_address = request.client.host if request.client is not None else "unknown"
    retry_after = failed_login_limiter.retry_after(client_address)
    if retry_after is not None:
        logger.warning("Authentication rate limit reached.")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    stored_credential = users.get(credentials.username)
    password_is_valid = verify_password(
        credentials.password,
        stored_credential or DUMMY_PASSWORD_HASH,
    )
    if stored_credential is None or not password_is_valid:
        retry_after = failed_login_limiter.register_attempt(client_address)
        if retry_after is not None:
            logger.warning("Authentication rate limit reached.")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    failed_login_limiter.clear(client_address)
    request.state.authenticated_user = credentials.username
    return credentials.username
