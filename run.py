"""
Entry point for running ScholarDesk as a standalone app - both as a
normal `python run.py` and as a PyInstaller-frozen .exe.

Why this exists instead of just `uvicorn app.main:app`: the uvicorn CLI
with --reload spawns a subprocess and re-imports the app by module
string, which doesn't work once everything is bundled into a single
frozen executable (there's no separate `app.main` module for the
subprocess to import - it's all baked into the one binary). Running
uvicorn programmatically, in-process, with reload off, sidesteps that.
"""
import webbrowser
import threading
import time

import uvicorn

from app.main import app

HOST = "127.0.0.1"
PORT = 8000


def _open_browser():
    time.sleep(1.2)  # give uvicorn a moment to bind before we navigate to it
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, reload=False, log_level="info")
