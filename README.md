# Grant Tracking System (local web app)

Successor to the Excel/VBA scholar-grant tracker. Single-user, runs entirely
on your own machine, no cloud dependency.

## Stack

FastAPI (Python) + SQLite + server-rendered HTML/htmx (no JS build step).

## Run it

**Option A - as a standalone .exe (recommended, no Python needed to run it):**

```powershell
pip install -r requirements.txt
build.bat
```

This produces `dist\ScholarDesk.exe` - a single file. Copy it anywhere
(a folder, a USB drive, wherever) and double-click it. It opens your
browser to the app automatically. `grants.db` is created next to the
`.exe` the first time you run it, and stays there across runs.

Verified end to end in this session: the built binary was moved to a
directory with no Python and no source code, run standalone, and put
through a full create/read cycle with zero errors.

You only need Python installed on the machine that *builds* the .exe
(once). The .exe itself needs nothing installed to run.

**Option B - run from source (if you're actively developing):**

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>

The database is a single file, `grants.db`, created automatically next to
the app on first run. Back it up the same way you'd back up the old `.xlsx`

- it's just a file.

## Run the tests

```bash
pytest
```

## What's implemented

- Scholars: create, edit, delete (cascades to their assignments and grants)
- Department assignments and Grants, nested under a scholar
- Multi-year grants handled correctly (a single grant spanning several
  years shows as one record, not duplicated per year - see
  `app/services/grants.py::active_in_year`)
- Dashboard: total scholar count, department distribution, both filterable
  by school year (dropdown only shows years that actually have data)
- Scholar list: searchable, filterable by year, paginated ("Load more")
  so it stays fast at 1,000+ scholars
- Duplicate-name warning on create (doesn't block, matches old VBA behavior)
- Legacy data import (`import_from_excel.py`) - reads the old VBA workbook's
  Scholars/Departments/Grants sheets and writes them in through the same
  service-layer functions the app itself uses, so imported data gets the
  same validation as anything entered by hand. Rows that can't be matched
  (e.g. a department assignment referencing a scholar that doesn't exist)
  are reported and skipped, never silently dropped or guessed at.

  Usage:

  ```bash
  python import_from_excel.py "C:\path\to\your\workbook.xlsm"
  ```

  Expects sheets named `Scholars`, `Departments`, `Grants` with the same
  column headers the VBA app used. If your actual headers differ, it'll
  tell you which ones it couldn't find rather than importing silently
  wrong data.

## Known gaps / next steps

- Schema changes only ever `CREATE TABLE IF NOT EXISTS` on startup - no
  migration tool yet. Fine while the schema is still moving; add Alembic
  before this is considered fully "done"
- No auth / access control - acceptable for a local single-user tool,
  not acceptable if this ever leaves your machine

## Project layout

```
app/
  main.py              FastAPI app + startup + validation error handling
  database.py          SQLite engine/session
  models.py            ORM models (Scholar, DepartmentAssignment, Grant)
  services/            Business logic - one file per entity, mirrors the
                        old VBA mod* modules on purpose
  routers/              HTTP layer - thin, delegates to services
  templates/            Jinja2 + htmx partials
tests/
  test_smoke.py         Automated version of the manual test cycle used
                         during development
```
