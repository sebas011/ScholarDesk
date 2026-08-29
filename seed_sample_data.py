"""
Populates grants.db with sample scholars, department assignments, and
grants - for demoing or testing the UI with realistic-looking data
without hand-typing it every time.

Goes through the same service-layer functions the app itself uses for
every write, so seeded data gets identical validation to anything
entered by hand (same reasoning as import_from_excel.py).

Safe to run multiple times - it always adds new scholars rather than
checking for existing ones, so running it twice just doubles the
sample data. If you want a clean slate first, delete grants.db (or
back it up first: `copy grants.db grants.db.backup`) before running.

Usage:
    python seed_sample_data.py
"""

from datetime import date

from app.database import Base, engine, SessionLocal
from app.services import scholars as scholar_service
from app.services import departments as dept_service
from app.services import grants as grant_service

SAMPLE_SCHOLARS = [
    {
        "name": "Maria Santos",
        "age": 29,
        "previous_degree": "BS Computer Science",
        "missing_requirements": False,
        "assignments": [
            {
                "department": "CCS",
                "rank": "Instructor I",
                "tenure": "Probationary",
                "date_started": date(2022, 6, 1),
                "date_ended": None,
            },
        ],
        "grants": [
            {
                "program_applied": "CHED Merit Scholarship",
                "type_of_grant": "Faculty Development",
                "delivering_hei": "University of the Philippines",
                "date_started": "June 2022",
                "date_ended": "May 2026",
                "start_year": 2022,
                "end_year": 2026,
                "extension": None,
                "status": "Active",
                "remarks": "Pursuing PhD in Computer Science.",
            },
        ],
    },
    {
        "name": "Juan Dela Cruz",
        "age": 34,
        "previous_degree": "MA Education",
        "missing_requirements": True,
        "assignments": [
            {
                "department": "COED",
                "rank": "Assistant Professor",
                "tenure": "Permanent",
                "date_started": date(2019, 8, 15),
                "date_ended": None,
            },
        ],
        "grants": [
            {
                "program_applied": "DOST-SEI Graduate Scholarship",
                "type_of_grant": "Graduate Study",
                "delivering_hei": "Ateneo de Manila University",
                "date_started": "AY 2020-2021",
                "date_ended": "AY 2023-2024",
                "start_year": 2020,
                "end_year": 2024,
                "extension": "1 year, due to pandemic delays",
                "status": "Completed",
                "remarks": "Completed EdD, currently on faculty.",
            },
        ],
    },
    {
        "name": "Angela Reyes",
        "age": 26,
        "previous_degree": "BS Civil Engineering",
        "missing_requirements": False,
        "assignments": [
            {
                "department": "CIT",
                "rank": "Instructor II",
                "tenure": "Probationary",
                "date_started": date(2023, 1, 10),
                "date_ended": None,
            },
        ],
        "grants": [
            {
                "program_applied": "CHED K-12 Transition Faculty Grant",
                "type_of_grant": "Faculty Development",
                "delivering_hei": "De La Salle University",
                "date_started": "early 2023",
                "date_ended": None,
                "start_year": 2023,
                "end_year": None,
                "extension": None,
                "status": "Active",
                "remarks": "Rough dates - original records incomplete.",
            },
        ],
    },
    {
        "name": "Ramon Villanueva",
        "age": 41,
        "previous_degree": "MS Mathematics",
        "missing_requirements": False,
        "assignments": [
            {
                "department": "CAS",
                "rank": "Associate Professor",
                "tenure": "Permanent",
                "date_started": date(2015, 6, 1),
                "date_ended": None,
            },
            {
                "department": "COE",
                "rank": "Part-time Lecturer",
                "tenure": "Part-time",
                "date_started": date(2021, 6, 1),
                "date_ended": date(2022, 5, 31),
            },
        ],
        "grants": [],
    },
]


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        created = 0
        for entry in SAMPLE_SCHOLARS:
            scholar = scholar_service.create_scholar(
                db,
                name=entry["name"],
                age=entry["age"],
                previous_degree=entry["previous_degree"],
                missing_requirements=entry["missing_requirements"],
            )
            for a in entry["assignments"]:
                dept_service.create_assignment(
                    db,
                    scholar.id,
                    a["department"],
                    a["rank"],
                    a["tenure"],
                    a["date_started"],
                    a["date_ended"],
                )
            for g in entry["grants"]:
                grant_service.create_grant(
                    db,
                    scholar.id,
                    g["program_applied"],
                    g["type_of_grant"],
                    g["delivering_hei"],
                    g["date_started"],
                    g["date_ended"],
                    g["start_year"],
                    g["end_year"],
                    g["extension"],
                    g["status"],
                    g["remarks"],
                )
            created += 1
        db.commit()
        print(f"Seeded {created} sample scholars.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
