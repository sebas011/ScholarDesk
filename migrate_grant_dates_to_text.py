"""
One-time migration for an existing grants.db:
  - date_started/date_ended: DATE -> TEXT (converted to ISO strings,
    so old values display exactly as they did before, just as text now)
  - adds start_year/end_year, backfilled from the old date columns

Base.metadata.create_all() only ever CREATEs tables, never ALTERs them
(see app/main.py), so this hand-rolled migration exists for the same
reason migrate_extension_to_text.py does. Safe to run multiple times.

Usage:
    python migrate_grant_dates_to_text.py [path/to/grants.db]

Defaults to ./grants.db if no path given.
"""
import sqlite3
import sys


def main(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(grants)")
    columns = {row[1]: row[2] for row in cur.fetchall()}

    if "date_started" not in columns:
        print("No 'date_started' column found - nothing to migrate.")
        conn.close()
        return

    if columns["date_started"].upper() in ("VARCHAR(100)", "TEXT"):
        print("Grant date columns are already text - nothing to migrate.")
        conn.close()
        return

    print("Migrating grant date columns to text + adding start_year/end_year...")

    cur.execute("ALTER TABLE grants ADD COLUMN date_started_new VARCHAR(100)")
    cur.execute("ALTER TABLE grants ADD COLUMN date_ended_new VARCHAR(100)")
    cur.execute("ALTER TABLE grants ADD COLUMN start_year INTEGER")
    cur.execute("ALTER TABLE grants ADD COLUMN end_year INTEGER")

    cur.execute("UPDATE grants SET date_started_new = date_started")
    cur.execute("UPDATE grants SET date_ended_new = date_ended")
    cur.execute(
        "UPDATE grants SET start_year = CAST(substr(date_started, 1, 4) AS INTEGER) "
        "WHERE date_started IS NOT NULL"
    )
    cur.execute(
        "UPDATE grants SET end_year = CAST(substr(date_ended, 1, 4) AS INTEGER) "
        "WHERE date_ended IS NOT NULL"
    )

    cur.execute("ALTER TABLE grants DROP COLUMN date_started")
    cur.execute("ALTER TABLE grants DROP COLUMN date_ended")
    cur.execute("ALTER TABLE grants RENAME COLUMN date_started_new TO date_started")
    cur.execute("ALTER TABLE grants RENAME COLUMN date_ended_new TO date_ended")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "grants.db"
    main(db_path)