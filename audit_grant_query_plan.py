from sqlalchemy import text

from app.database import engine


with engine.connect() as conn:
    print("Indexes:")
    for row in conn.execute(text("PRAGMA index_list('grants')")):
        print(row)

    print("Plan:")
    query = text(
        """
        EXPLAIN QUERY PLAN
        SELECT count(*)
        FROM grants
        WHERE status = 'Active'
          AND start_year IS NOT NULL
          AND start_year <= 2026
          AND (end_year IS NULL OR end_year >= 2026)
        """
    )
    for row in conn.execute(query):
        print(row)
