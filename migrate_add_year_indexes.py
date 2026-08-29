"""
One-time migration for an existing grants.db: adds indexes on the four
columns the SQL-based year filtering actually queries against
(Grant.start_year/end_year, DepartmentAssignment.date_started/date_ended).

Base.metadata.create_all() only ever CREATEs tables, never ALTERs or
adds indexes to existing ones (see app/main.py) - so a fresh grants.db
gets these automatically from the model definitions, but an existing
one needs this. Safe to run multiple times (CREATE INDEX IF NOT EXISTS).

Usage:
    python migrate_add_year_indexes.py [path/to/grants.db]

Defaults to ./grants.db if no path given.
"""

import sqlite3
import sys


def main(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    indexes = [
        ("ix_grants_start_year", "grants", "start_year"),
        ("ix_grants_end_year", "grants", "end_year"),
        ("ix_department_assignments_date_started", "department_assignments", "date_started"),
        ("ix_department_assignments_date_ended", "department_assignments", "date_ended"),
    ]

    for index_name, table, column in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})")
        print(f"Ensured index {index_name} on {table}.{column}")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "grants.db"
    main(db_path)
