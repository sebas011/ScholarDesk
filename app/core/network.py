"""
Whether the server listens on localhost only, or on the network (so
other PCs on the same LAN can reach it). A plain-text file next to
grants.db, same reasoning as app/core/auth.py: editing a text file is
a much lower bar for a non-technical person than setting an
environment variable.

Read once at startup (unlike auth.txt, which is re-read on every
request) - changing this requires restarting the app to take effect,
same as any other host-binding change would with uvicorn.
"""

from app.database import app_dir

NETWORK_CONFIG_FILE = app_dir / "network.txt"
DEFAULT_ALLOW_LAN = False


def _ensure_config_file() -> None:
    if not NETWORK_CONFIG_FILE.exists():
        NETWORK_CONFIG_FILE.write_text(
            "# Set to true to let other computers on your network reach this app.\n"
            "# Requires changing the default password in auth.txt first - the app\n"
            "# will refuse network access and stay on localhost otherwise.\n"
            f"allow_lan={'true' if DEFAULT_ALLOW_LAN else 'false'}\n",
            encoding="utf-8",
        )


def allow_lan() -> bool:
    _ensure_config_file()
    for line in NETWORK_CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "allow_lan":
            return value.strip().lower() == "true"
    return DEFAULT_ALLOW_LAN
