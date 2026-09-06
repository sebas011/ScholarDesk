from decimal import Decimal
import re


def parse_lab_units(value) -> Decimal:
    text = str(value or "").strip()
    parenthesized = re.search(r"\(\s*(\d+(?:\.\d+)?)\s*\)", text)

    if parenthesized:
        number = Decimal(parenthesized.group(1))
    else:
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return Decimal("0")
        number = Decimal(match.group())

    return number * Decimal("0.75") if number == number.to_integral_value() else number


def threshold_for_preps(no_of_preps) -> Decimal:
    try:
        preps = int(no_of_preps)
    except (TypeError, ValueError):
        return Decimal("18")

    return Decimal("21") if preps in {1, 2} else Decimal("18")


def calculate_payroll(
    *,
    lecture,
    lab,
    etu,
    no_of_preps,
    total_no_of_weeks,
    weeks_absent,
    salary_rate_per_hour,
    withholding_rate,
) -> dict:
    lecture_value = Decimal(str(lecture or 0))
    lab_units = parse_lab_units(lab)
    teaching_load = lecture_value + lab_units
    total_workload = teaching_load + Decimal(str(etu or 0))
    threshold = threshold_for_preps(no_of_preps)
    excess = max(Decimal("0"), total_workload - threshold)
    net_weeks = max(
        Decimal("0"),
        Decimal(str(total_no_of_weeks or 0)) - Decimal(str(weeks_absent or 0)),
    )
    hours_overload = excess * net_weeks
    amount_due = hours_overload * Decimal(str(salary_rate_per_hour or 0))
    withholding = amount_due * Decimal(str(withholding_rate or 0))

    return {
        "total_teaching_load": teaching_load,
        "total_workload": total_workload,
        "threshold": threshold,
        "excess_hours_per_week": excess,
        "net_overload_weeks": net_weeks,
        "hours_overload": hours_overload,
        "amount_due": amount_due,
        "withholding_amount": withholding,
        "net_amount_due": amount_due - withholding,
        "semester_salary": hours_overload * Decimal(str(salary_rate_per_hour or 0)) * Decimal("18"),
        "overload_cap_flag": total_workload >= Decimal("30"),
    }
