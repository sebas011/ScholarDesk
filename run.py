"""
Entry point for both development and PyInstaller builds.
"""

import sys
import shutil
import subprocess
import tempfile
import threading
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
    frozen = getattr(sys, "frozen", False)

    kwargs = {
        "host": _resolve_host(),
        "port": 8000,
        "log_level": "info",
        "reload": not frozen,
    }
    if frozen:
        kwargs["log_config"] = None

    if not frozen:
        uvicorn.run("app.main:app", **kwargs)
        return

    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    profile_dir = tempfile.mkdtemp(prefix="scholardesk-edge-")
    config = uvicorn.Config("app.main:app", **kwargs)
    server = uvicorn.Server(config)

    def launch_and_monitor_browser():
        try:
            browser = subprocess.Popen(
                [
                    edge,
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--app={url}",
                ]
            )
            browser.wait()
            server.should_exit = True
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)

    threading.Timer(1.5, launch_and_monitor_browser).start()
    server.run()


if __name__ == "__main__":
    main()
