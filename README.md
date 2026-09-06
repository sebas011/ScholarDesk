# ScholarDesk

Local desktop app for tracking **scholars**, **department assignments**, and **grants**.

ScholarDesk is a single-user FastAPI + SQLite web app, packaged as a Windows executable (`ScholarDesk.exe`). It is a relational rewrite of a VBA/Excel grant tracker: real foreign keys instead of a shared `EmployeeID` string, date ranges on assignments, and year-based filtering that actually answers "who was active in this year?"

The server binds to `127.0.0.1` by default and requires HTTP Basic Auth. LAN access is opt-in through `network.txt` after changing the default password.

## Optional LAN access

The app listens on `127.0.0.1` by default. To allow access from other computers on the same LAN, set `allow_lan=true` in the generated `network.txt` after changing the default password in `auth.txt`. Restart the app after changing `network.txt`.

---

## Features

- Scholar directory with search, year filter, and pagination
- Scholar profiles: assignments, grants, notes, activity log, grant reviews
- Dashboard stats: scholar counts, department distribution, grant totals
- Year filter that treats an assignment or grant as active if it overlaps that year
- Excel import from the legacy workbook (same validation as the UI)
- Sample-data seeder for demos
- Windowed Windows build via PyInstaller (no console window)

---

## Requirements

- Python 3.11+ (CI uses 3.13)
- Windows if you want the `.exe` build (`build.bat` + PyInstaller)

Install dependencies:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running

**Standalone .exe (Windows, no Python needed to run it):**

```powershell
build.bat
```

Produces `dist\ScholarDesk.exe` — a single file. Copy it anywhere (a folder, a USB drive, wherever) and double-click it; it opens your browser to the app automatically. `grants.db` is created next to the `.exe` the first time you run it, and stays there across runs.

**From source:**

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>

The database is a single file, `grants.db`, created automatically next to the app on first run. Back it up the same way you'd back up the old `.xlsx` — it's just a file.

---

## Tests

```bash
pytest
```

---

## Known gaps

- Schema changes only ever `CREATE TABLE IF NOT EXISTS` on startup — no migration tool yet. Fine while the schema is still moving; add Alembic before this is considered fully "done"
- HTTP Basic Auth and optional LAN binding — suitable for trusted local networks only, not a substitute for production identity and access management

---

## Project layout

```text
app/
  main.py              FastAPI app + startup + validation error handling
  database.py          SQLite engine/session
  models.py            ORM models (Scholar, DepartmentAssignment, Grant,
                        ActivityLog, ScholarNote, GrantReview)
  services/            Business logic - one file per entity, mirrors the
                        old VBA mod* modules on purpose
  routers/              HTTP layer - thin, delegates to services
  templates/            Jinja2 + htmx partials
tests/
  test_smoke.py         Automated version of the manual test cycle used
                         during development
```
## Database, Backups, and Migrations

ScholarDesk stores its SQLite database in `grants.db`, next to the executable. The
local configuration files `auth.txt` and `network.txt` are stored in the same
directory.

Stop ScholarDesk before copying or restoring the database.

### Backup

Create a timestamped backup from the application directory:

```powershell
New-Item -ItemType Directory -Force backups
Copy-Item grants.db "backups\grants-$(Get-Date -Format yyyyMMdd-HHmmss).db"