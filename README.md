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
```

Keep backups outside the release folder when possible. Never commit `auth.txt`,
`grants.db`, or backup files to Git.

### Restore

1. Stop ScholarDesk.
2. Copy a known-good backup over the active `grants.db`.
3. Start ScholarDesk and verify the data.

Keep the original database until the restored copy has been validated.

## Working folders

The project uses separate folders for source development, isolated Git worktrees,
and the runnable Windows release:

| Folder | Purpose |
| --- | --- |
| `C:\Users\rodia\Desktop\ScholarDesk` | Main Git checkout. Make code changes, run tests, commit, and push here. |
| `C:\Users\rodia\Desktop\ScholarDesk.worktrees` | Git-managed worktrees for isolated branches or tasks. Do not delete a worktree manually; use `git worktree list` and `git worktree remove`. |
| `C:\Users\rodia\Desktop\ScholarDesk-release` | Private deployment copy. Run `ScholarDesk.exe` here; do not use it for source development. |

The release folder contains runtime state beside the executable:

- `ScholarDesk.exe` — packaged application
- `grants.db` — live SQLite data
- `auth.txt` — local Basic Auth credentials
- `network.txt` — network binding configuration
- `logs\` — runtime logs
- `SHA256SUMS.txt` — executable integrity record

The release folder and its database and credentials must remain private. The
default configuration is localhost-only (`allow_lan=false`).

## Audit and production-hardening summary

The completed audit validated the application for trusted, single-machine
Windows use:

- Authentication and default localhost binding were tested, including invalid
  credentials returning `401 Unauthorized`.
- LAN access was made explicit and remains disabled unless deliberately enabled
  after changing the default password.
- Notes and grant-review routes were wired through their service-layer functions.
- Service, router, authentication, networking, logging, startup, and error paths
  received regression coverage.
- The final test suite passed with 127 tests and 100% application coverage.
- Ruff checks, `pip check`, and `pip-audit` passed.
- CI was hardened for dependency verification, security scanning, Linux tests,
  and Windows PyInstaller builds.
- Database backup and restore procedures were documented and rehearsed.
- The packaged executable was tested for startup, authentication, CRUD behavior,
  export, restart, logging, and clean shutdown.
- Runtime ACLs were restricted for `auth.txt` and `grants.db`.
- The final executable hash was recorded as:

  `058496013D76A0FCC5022C15499C80EF47746A14A51A5572BF9A7F08CE99164C`

This validation does not make ScholarDesk suitable for public internet exposure
or an untrusted multi-user deployment. Those environments require stronger
identity management, encrypted transport, and additional operational controls.

## Release checklist

Before distributing a new Windows release:

1. Run the tests and build from the main checkout with `build.bat`.
2. Stop any running packaged application before copying database files.
3. Keep `auth.txt`, `network.txt`, and `grants.db` private.
4. Verify the executable hash with `Get-FileHash`.
5. Start the copied release and test login and data persistence.
6. Stop the app and remove transient `grants.db-shm`, `grants.db-wal`, and
   development logs before delivery.
7. Keep a timestamped database backup and retain the previous known-good release.