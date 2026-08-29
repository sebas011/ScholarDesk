"""
One-time migration: converts the `grants.extension` column from
BOOLEAN to free text, for an existing grants.db created before this
change. Safe to run multiple times (checks column type first).

Base.metadata.create_all() only ever CREATEs tables, never ALTERs
them (see app/main.py), so a schema change to an existing column
needs this instead - SQLite doesn't support ALTER COLUMN TYPE
directly, so we rebuild the column the standard SQLite way: add a
new column, copy/convert data, drop the old one.

Usage:
    python migrate_extension_to_text.py [path/to/grants.db]

Defaults to ./grants.db if no path given.
"""

import sqlite3
import sys


def main(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(grants)")
    columns = {row[1]: row[2] for row in cur.fetchall()}

    if "extension" not in columns:
        print("No 'extension' column found - nothing to migrate.")
        conn.close()
        return

    if columns["extension"].upper() in ("VARCHAR(200)", "TEXT"):
        print("'extension' column is already text - nothing to migrate.")
        conn.close()
        return

    print(f"Migrating 'extension' column from {columns['extension']} to VARCHAR(200)...")

    cur.execute("ALTER TABLE grants ADD COLUMN extension_new VARCHAR(200)")
    # Old boolean values: 1 -> "Yes", 0/NULL -> NULL (nothing meaningful to
    # carry forward as text, so this just preserves "there was an
    # extension" as a starting point you can edit with real detail later).
    cur.execute("UPDATE grants SET extension_new = 'Yes' WHERE extension = 1")
    cur.execute("ALTER TABLE grants DROP COLUMN extension")
    cur.execute("ALTER TABLE grants RENAME COLUMN extension_new TO extension")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "grants.db"
    main(db_path)
