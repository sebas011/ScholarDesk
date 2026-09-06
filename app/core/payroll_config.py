from decimal import Decimal
import os

SEMESTER_WEEKS = Decimal(os.getenv("PAYROLL_SEMESTER_WEEKS", "18"))
STANDARD_WEEKLY_HOURS = Decimal(os.getenv("PAYROLL_STANDARD_WEEKLY_HOURS", "40"))
NET_PAY_TOLERANCE = Decimal(os.getenv("PAYROLL_NET_PAY_TOLERANCE", "1.00"))
HOURS_TOLERANCE = Decimal(os.getenv("PAYROLL_HOURS_TOLERANCE", "0.05"))
