from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
import json
import time

# ------------------------------------------------------------------
# Log directory
# ------------------------------------------------------------------
# Same reasoning as app/database.py: a relative "logs" path resolves
# against the current working directory, which is NOT guaranteed to be
# the .exe's folder when double-clicked from Explorer. Anchor to the
# executable's folder (frozen) or the project root (normal run) so
# logs always land next to the app, not wherever it happened to launch
# from.
if getattr(sys, "frozen", False):
    _app_dir = Path(sys.executable).parent
else:
    _app_dir = Path(__file__).resolve().parent.parent.parent

LOG_DIR = _app_dir / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "grant_tracker.log"

class JsonFormatter(logging.Formatter):
    """Serialize application logs as one JSON object per line."""

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)

def configure_logging() -> logging.Logger:
    """
    Configure the application's logger.

    Safe to call multiple times.
    """

    logger = logging.getLogger("grant_tracker")

    # Prevent duplicate handlers if called more than once.
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = JsonFormatter()

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # Prevent messages from also being sent to the root logger.
    logger.propagate = False

    return logger


logger = configure_logging()
