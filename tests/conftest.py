import os

# Must run before pytest imports app.payroll_database.
os.environ["PAYROLL_DATABASE_URL"] = "sqlite://"
