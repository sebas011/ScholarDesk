import sys
from pathlib import Path
from fastapi.templating import Jinja2Templates

# PyInstaller extracts bundled data files (like our templates/) to a
# temp folder at runtime and exposes it as sys._MEIPASS. Path(__file__)
# still points at the source location, which doesn't exist inside a
# frozen .exe - so this has to branch, or the packaged app 500s on
# every page load the instant it's not run from source.
if getattr(sys, "frozen", False):
    base_dir = Path(sys._MEIPASS) / "app"
else:
    base_dir = Path(__file__).parent

templates = Jinja2Templates(directory=str(base_dir / "templates"))
