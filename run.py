"""
Entry point for both development and PyInstaller builds.
"""
import sys
import uvicorn

# CRITICAL: This forces PyInstaller to bundle the entire app package
import app.main  # noqa: F401

def main():
    url = "http://127.0.0.1:8000"
    # Auto-open browser when running from .exe (frozen)
    if getattr(sys, "frozen", False):
        import threading
        import webbrowser
        print(f"Starting ScholarDesk at {url}")
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    kwargs = {
        "host": "127.0.0.1",
        "port": 8000,
        "log_level": "info",
        "reload": not getattr(sys, "frozen", False),
    }
    if getattr(sys, "frozen", False):
        kwargs["log_config"] = None
    uvicorn.run("app.main:app", **kwargs)

if __name__ == "__main__":
    main()
