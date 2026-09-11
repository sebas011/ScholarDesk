"""Local administrator helper for setting the ScholarDesk login password."""

from __future__ import annotations

import getpass

from app.core.auth import DEFAULT_USERNAME, set_hashed_credentials


def main() -> None:
    """Prompt locally and write a PBKDF2 password hash without echoing it."""
    username = input(f"Username [{DEFAULT_USERNAME}]: ").strip() or DEFAULT_USERNAME
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match; auth.txt was not changed.")

    try:
        set_hashed_credentials(username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("Credentials saved securely. Restart ScholarDesk if it is running.")


if __name__ == "__main__":
    main()
