import shutil
import sqlite3
from pathlib import Path


DB_PATH = Path("grants.db")
BACKUP_PATH = Path("grants.db.backup.pre-activity-log-migration")


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    if BACKUP_PATH.exists():
        raise SystemExit(
            f"Backup already exists: {BACKUP_PATH}\n"
            "Remove or rename it manually before running this migration again."
        )

    shutil.copy2(DB_PATH, BACKUP_PATH)

    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")

        conn.execute(
            """
            CREATE TABLE activity_logs_new (
                id INTEGER NOT NULL PRIMARY KEY,
                scholar_id INTEGER NULL,
                category VARCHAR(50) NOT NULL,
                description TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(scholar_id)
                    REFERENCES scholars(id)
                    ON DELETE SET NULL
            )
            """
        )

        conn.execute(
            """
            INSERT INTO activity_logs_new (
                id,
                scholar_id,
                category,
                description,
                created_at
            )
            SELECT
                id,
                scholar_id,
                category,
                description,
                created_at
            FROM activity_logs
            """
        )

        conn.execute("DROP TABLE activity_logs")
        conn.execute(
            "ALTER TABLE activity_logs_new RENAME TO activity_logs"
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    # Verify using a fresh connection with FK enforcement enabled.
    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("PRAGMA foreign_keys = ON")

        fk = conn.execute(
            "PRAGMA foreign_key_list(activity_logs)"
        ).fetchall()

        columns = conn.execute(
            "PRAGMA table_info(activity_logs)"
        ).fetchall()

        violations = conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print("activity_logs foreign keys:")
        for row in fk:
            print(row)

        print("\nactivity_logs columns:")
        for row in columns:
            print(row)

        if violations:
            raise RuntimeError(
                f"Foreign-key violations found: {violations}"
            )

        print("\nMigration completed successfully.")
        print(f"Backup: {BACKUP_PATH}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
