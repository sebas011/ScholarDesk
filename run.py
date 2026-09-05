"""
Entry point for both development and PyInstaller builds.
"""

import sys
import uvicorn

# CRITICAL: This forces PyInstaller to bundle the entire app package
import app.main  # noqa: F401
from app.core.auth import using_default_password
from app.core.network import allow_lan


def _resolve_host() -> str:
    """Localhost-only unless network.txt explicitly opts in - and even
    then, refuses to bind wider than localhost while auth.txt still
    has the default admin/changeme password. Fails safe: the app still
    starts and works locally, it just doesn't expose itself, rather
    than crashing outright over a config mistake."""
    if not allow_lan():
        return "127.0.0.1"
    if using_default_password():
        print(
            "WARNING: network.txt has allow_lan=true, but auth.txt still has "
            "the default password. Refusing to expose this app to your network "
            "until the password in auth.txt is changed. Starting on localhost "
            "only for now."
        )
        return "127.0.0.1"
    return "0.0.0.0"


def main():
    url = "http://127.0.0.1:8000"
    # Auto-open browser when running from .exe (frozen)
    if getattr(sys, "frozen", False):
        import threading
        import webbrowser

        print(f"Starting ScholarDesk at {url}")
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    kwargs = {
        "host": _resolve_host(),
        "port": 8000,
        "log_level": "info",
        "reload": not getattr(sys, "frozen", False),
    }
    if getattr(sys, "frozen", False):
        kwargs["log_config"] = None
    uvicorn.run("app.main:app", **kwargs)


if __name__ == "__main__":
    main()
