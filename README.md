# ScholarDesk

Local desktop app for tracking **scholars**, **department assignments**, and **grants**.

ScholarDesk is a single-user FastAPI + SQLite web app, packaged as a Windows executable (`ScholarDesk.exe`). It is a relational rewrite of a VBA/Excel grant tracker: real foreign keys instead of a shared `EmployeeID` string, date ranges on assignments, and year-based filtering that actually answers "who was active in this year?"

The server always binds to `127.0.0.1` and requires HTTP Basic Auth. It is not a LAN-facing web server.

## LAN access through a TLS proxy

To serve other computers, run a TLS-terminating reverse proxy on the same Windows machine. Configure the proxy to listen on the LAN over HTTPS and forward only to `http://127.0.0.1:8000`.

Keep port 8000 blocked from the LAN. ScholarDesk deliberately ignores `network.txt`; it must remain loopback-only so HTTP Basic credentials and scholar data cannot be sent across the network without TLS.

### Cathedra Caddy deployment

The included [Caddy configuration](deployment/Caddyfile.cathedra.vpaa) serves
`https://cathedra.vpaa` with Caddy's internal certificate authority and proxies
only to ScholarDesk on `127.0.0.1:8000`.

Before enabling it:

1. Create an internal DNS record for `cathedra.vpaa` pointing to the Windows
   host running ScholarDesk and Caddy.
2. Install Caddy on that host and start it with the included configuration.
3. Trust Caddy's internal root certificate on every authorized client device.
4. Allow inbound TCP port 443 to Caddy; do not allow inbound TCP port 8000.
5. Verify `https://cathedra.vpaa` shows a valid trusted certificate, then test
   ScholarDesk login, create, edit, export, and logout flows through that URL.

Do not expose ScholarDesk directly with `http://cathedra.vpaa:8000`.

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

- Python 3.11+ for source development and tests; Python 3.13 for the validated portable Windows build
- Windows if you want the `.exe` build (`build.bat` + PyInstaller)

Install dependencies:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

To build the Windows executables, install the additional Windows-only build tools:

```powershell
pip install -r requirements.windows.lock.txt
```

---

## Running

**Standalone .exe (Windows, no Python needed to run it):**

```powershell
build.bat
```

Produces `dist\ScholarDesk.exe` and `dist\ScholarDeskAdmin.exe`. Keep both files in the same private release folder. On first use, run `ScholarDeskAdmin.exe` to set the local username and password, then start `ScholarDesk.exe`; the admin tool requires new passwords to contain at least 12 characters and stores only password hashes. Existing valid `auth.txt` credentials migrate automatically to `users.json` on first login, and later administrator runs can add or reset named local accounts. ScholarDesk rejects legacy plaintext `password=` files and returns a configuration error until the administrator helper resets the credentials. The fifth consecutive failed login attempt from one client within one minute receives `429 Too Many Requests`. Once blocked, every login attempt from that client, including one with the correct password, must wait for the supplied `Retry-After` period; an unblocked successful login clears that client's failure history immediately.
The build uses only the project's `.venv` tools and an isolated temporary workspace for Python, pytest, and PyInstaller. It removes that workspace after success or failure, so repeated builds do not accumulate stale build output in `%TEMP%`.
Close the dedicated ScholarDesk window to stop the background server completely. The packaged app uses a temporary Edge profile and does not leave the server listening after the window closes. `grants.db` is created next to the `.exe` the first time you run it, and stays there across runs.
The Grant Tracker browser assets are bundled into the executable, so normal use does not require Internet access.

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

- Fresh databases record the current schema version on startup. Existing databases are never
  silently baselined; unversioned databases must match the recognized legacy schema or startup
  fails safely. Use the administrator command below before startup applies a pending migration.
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
local credential files `auth.txt` and `users.json` are stored in the same directory.

### Local administrator accounts

Use the administrator utility to add or reset an account. After the first successful
login, a valid legacy `auth.txt` account is migrated to `users.json`, which supports
multiple local administrators.

```powershell
.\ScholarDeskAdmin.exe
.\ScholarDeskAdmin.exe --list-users
.\ScholarDeskAdmin.exe --remove-user departing-admin
```

Account removal asks you to type the username again and refuses to remove the final
administrator. Keep at least one separately stored recovery account.

### Release-folder permissions

Before distributing or exposing a release through the TLS proxy, verify that broad
local Windows groups cannot read its folder, database, or credential registry:

```powershell
.\ScholarDeskAdmin.exe --check-release-permissions
```

This is a read-only diagnostic. It rejects access granted to Everyone,
Authenticated Users, BUILTIN\\Users, or BUILTIN\\Guests; use your organization’s
Windows ACL process to grant access only to the required administrators and service
accounts.

Stop ScholarDesk before copying or restoring the database.

### Backup

Create a timestamped, SQLite-consistent backup from the release folder:

```powershell
.\ScholarDeskAdmin.exe --backup-database
```

This uses SQLite's backup API, so it captures committed data correctly even when
`grants.db` is in WAL mode. It does not modify the live database and writes the
backup to `backups\`. From source, run `python -m app.admin --backup-database`.
Keep backups outside the release folder when possible. Never commit `auth.txt`,
`users.json`, `grants.db`, or backup files to Git.

### Backup restore drill

Run this regularly after confirming ScholarDesk is open or closed as usual:

```powershell
.\ScholarDeskAdmin.exe --verify-backup-restore
```

The drill creates a normal timestamped backup in `backups\`, restores that backup
only into a disposable temporary database, and verifies its schema and row counts.
It never overwrites or modifies the live `grants.db`. From source, run
`python -m app.admin --verify-backup-restore`.

### Health check

`GET /health` requires the same local credentials as the rest of ScholarDesk.
It returns `{"status":"ok"}` only after a lightweight read from the core
`scholars` table succeeds; otherwise it returns `503` with
`{"status":"unavailable"}` and records the underlying failure in the application log.

### Baseline an existing database

After upgrading to the versioned-schema release, stop ScholarDesk and run this
once from the release folder:

```powershell
.\ScholarDeskAdmin.exe --baseline-database
```

Type `BASELINE` only after confirming the app is closed. The command validates
the required tables, columns, indexes, foreign keys, and SQLite integrity; it
then saves a timestamped copy in `backups\` before recording schema version `1`.
On the next ScholarDesk startup, the application creates a second backup and applies
any pending migrations before opening the database. If validation or migration fails,
the database is not changed after the failed step and the backup remains available.

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
- `ScholarDeskAdmin.exe` — local password-reset utility; keep private
- `grants.db` — live SQLite data
- `auth.txt` — legacy single-account credentials retained for migration
- `users.json` — local multi-user Basic Auth credential registry
- `logs\` — runtime logs
- `SHA256SUMS.txt` — executable integrity record

The release folder and its database and credentials must remain private.
ScholarDesk always remains localhost-only; a TLS proxy is required for LAN use.

After copying a release, run the following and compare the two hash values with
`SHA256SUMS.txt` before starting either executable:

```powershell
Get-FileHash .\ScholarDesk.exe, .\ScholarDeskAdmin.exe -Algorithm SHA256
```

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
3. Keep `auth.txt`, `users.json`, and `grants.db` private.
4. Verify the executable hash with `Get-FileHash`.
5. Start the copied release and test login and data persistence.
6. Stop the app and remove transient `grants.db-shm`, `grants.db-wal`, and
   development logs before delivery.
7. Keep a timestamped database backup and retain the previous known-good release.
