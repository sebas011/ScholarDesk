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

(.venv) C:\Users\rodia\Desktop\ScholarDesk>git status
On branch feat/ui/status-pill-scholar-detail
Your branch is up to date with 'origin/feat/ui/status-pill-scholar-detail'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
        modified:   app/routers/scholars.py
        modified:   app/templates/base.html
        modified:   app/templates/dashboard.html
        modified:   app/templates/index.html
        modified:   app/templates/partials/assignment_edit_row.html
        modified:   app/templates/partials/grant_edit_row.html
        modified:   app/templates/partials/scholar_detail.html
        modified:   app/templates/partials/scholar_list.html
        modified:   app/templates/scholar_new.html
        modified:   app/templates/scholar_profile.html
        modified:   app/templates/scholars.html

no changes added to commit (use "git add" and/or "git commit -a")

(.venv) C:\Users\rodia\Desktop\ScholarDesk>git add app/templates/partials/scholar_detail.html
warning: in the working copy of 'app/templates/partials/scholar_detail.html', LF will be replaced by CRLF the next time Git touches it

(.venv) C:\Users\rodia\Desktop\ScholarDesk>git commit -m "Update scholar_detail.html to new Tailwind component classes (fixes styling gap from redesign)"
[feat/ui/status-pill-scholar-detail 4f360e6] Update scholar_detail.html to new Tailwind component classes (fixes styling gap from redesign)
 1 file changed, 207 insertions(+), 151 deletions(-)

(.venv) C:\Users\rodia\Desktop\ScholarDesk>git push
Enumerating objects: 11, done.
Counting objects: 100% (11/11), done.
Delta compression using up to 8 threads
Compressing objects: 100% (6/6), done.
Writing objects: 100% (6/6), 1.93 KiB | 330.00 KiB/s, done.
Total 6 (delta 5), reused 0 (delta 0), pack-reused 0 (from 0)
remote: Resolving deltas: 100% (5/5), completed with 5 local objects.
To <https://github.com/sebas011/ScholarDesk.git>
   2f4dbd7..4f360e6  feat/ui/status-pill-scholar-detail -> feat/ui/status-pill-scholar-detail

(.venv) C:\Users\rodia\Desktop\ScholarDesk>git log --oneline
4f360e6 (HEAD -> feat/ui/status-pill-scholar-detail, origin/feat/ui/status-pill-scholar-detail) Update scholar_detail.html to new Tailwind component classes (fixes styling gap from redesign)
2f4dbd7 Fix stale test assertions after Home page redesign; fix trailing newline
12634c9 Fix misplaced RedirectResponse in create_scholar_page (Task 2 bugfix)
8635f73 Add dedicated /scholars/{id} profile page (Task 2 of navigation refactor)
8b57894 Add dedicated /scholars/new page (Task 1 of navigation refactor)
ebbf901 Made some changes to the template and ui, files edited are base.html, scholar_detail.html, and a new file tmp_scholars.html
852c81b feat(ui): render grant status as colored pill in scholar detail
ceea4e2 (origin/main, origin/HEAD, main) Extract repeated inline styles into named CSS classes
fa8213c Ignore .coverage data file
9cb7fa8 Add pytest-cov: report test coverage in CI
44a2026 Add age bounds validation (15-100)
a5a1bb3 Add Subresource Integrity hash to htmx CDN script
fa077a9 Add htmx loading indicator styling to buttons
0c185ca Add server-side length limits for grant text fields
57f791d Add server-side length limits for department, rank, and tenure
47c313e Add server-side length limits for scholar name and previous_degree
876caaa Ignore .vscode editor folder
1e0f31e Move dashboard_page's queries into the service layer
fc0320d Add indexes on Grant.start_year/end_year and DepartmentAssignment.date_started/date_ended
1136b40 Add CRUD error-path test coverage for assignments and grants, plus dashboard smoke test
18edd25 Remove unused grant_service import and dead duplicate code block in scholars_page
dee8296 Fix year param type-reassignment smell: use separate variable names instead of type: ignore
44660b2 Add build_detail_context helper; use it in records.py's shared render function
e297767 Add catch-all exception handler for unhandled errors
49b4ea5 Add GitHub Actions CI: lint and test on every push/PR
7adce53 Fix dashboard scholar links: open full styled page instead of unstyled fragment
857e96e Add dashboard_page query: all scholars grouped with their assignments and grants
05107cf Add Dashboard nav tab (placeholder) and Add Scholar button on Home
cb87fc5 Cap assignments/grants tables at 10 rows with Show all toggle
de1c759 Catch ValueError in scholar create/update/delete routes; fix 500 crash on whitespace-only name
5466691 Push department_distribution year-filtered branch into SQL
cfe2c6c Push total_grants, active_grants_count, total_scholars_active_in_year into SQL
ea6e9a4 Push list_scholars year filtering into SQL instead of loading all rows
01e5b1f Polish scholar list filter bar and detail page section separation
88d31d5 Polish dashboard layout: responsive stat boxes, aligned table
0ae5faa Polish visual foundation: typography, spacing, color depth
bf2d643 Add edit capability for grants
5beff90 Broaden gitignore pattern to cover all .db.backup* files
c6919ae Add edit capability for department assignments
daaecd8 Fix assignment edit Save: remove invalid form-in-tr, fix outerHTML swap bug
235250d Add edit capability for department assignments
6c37668 Add sample data seed script for demos and testing
