"""
Entry point for both development and PyInstaller builds.
"""

import os
import sys
import threading
import webbrowser

import uvicorn

# CRITICAL: This forces PyInstaller to bundle the entire app package.
from app.main import app as web_app


HEADLESS_SMOKE_TEST_ENVIRONMENT = "SCHOLARDESK_HEADLESS"


def _resolve_host() -> str:
    """Keep the application private; a same-machine TLS proxy owns LAN access."""
    return "127.0.0.1"


def _is_headless_smoke_test() -> bool:
    """Allow CI to exercise the frozen server without opening a browser."""
    return os.environ.get(HEADLESS_SMOKE_TEST_ENVIRONMENT) == "1"


def main():
    url = "http://127.0.0.1:8000"
    frozen = getattr(sys, "frozen", False)

    kwargs = {
        "host": _resolve_host(),
        "port": 8000,
        "log_level": "info",
        "reload": not frozen,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
    }
    if frozen:
        kwargs["log_config"] = None

    if not frozen:
        uvicorn.run("app.main:app", **kwargs)
        return

    config = uvicorn.Config("app.main:app", **kwargs)
    server = uvicorn.Server(config)
    web_app.state.host_shutdown_callback = lambda: setattr(server, "should_exit", True)

    if _is_headless_smoke_test():
        server.run()
        return

    # ``webbrowser`` delegates to Windows' configured default browser. Unlike
    # a dedicated Edge app window, there is no portable way to monitor a
    # browser tab's lifetime, so the server remains available until the user
    # closes ScholarDesk itself.
    threading.Timer(1.5, lambda: webbrowser.open(url, new=1)).start()
    server.run()


if __name__ == "__main__":
    main()
