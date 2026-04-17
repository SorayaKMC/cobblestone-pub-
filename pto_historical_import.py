"""One-time importer for historical PTO data from the V4 spreadsheet.

Reads pto_historical_data.json (bundled with the app) and populates:
  - employee_categories (for departed employees Daisy + Marino)
  - pto_manual_adjustments (starting balance carry-over from old system)
  - pto_accruals (week-by-week from the V4 spreadsheet)
  - pto_taken (from the Days Taken sheet)
"""

import json
import os
from datetime import datetime, timedelta
import db


HISTORICAL_JSON = os.path.join(os.path.dirname(__file__), "pto_historical_data.json")

# Departed employees that need placeholder employee_categories entries
DEPARTED_EMPLOYEES = {
    "__DAISY_KEOGH__": ("Daisy", "Keogh", "Staff"),
    "__MARINO_PORCARI__": ("Marino", "Porcari", "Staff"),
}


def load_historical_data():
    with open(HISTORICAL_JSON) as f:
        return json.load(f)


def ensure_departed_employees_exist():
    """Create employee_categories rows for departed staff so PTO history is preserved."""
    existing = {r["team_member_id"] for r in db.get_employee_categories()}
    for tm_id, (first, last, cat) in DEPARTED_EMPLOYEES.items():
        if tm_id not in existing:
            db.update_employee_category(tm_id, first, last, cat, 0, 0, "hourly")


def import_starting_balances(data):
    """For each employee, create a manual adjustment for their starting carryover.

    Starting balance carryover comes from the V4 spreadsheet (in days, pre-computed).
    Use 2026-01-01 as the effective date (before any 2026 accruals).
    """
    count = 0
    for tm_id, emp in data["employees"].items():
        start_days = emp.get("starting_balance_days", 0)
        if start_days <= 0:
            continue
        # Clear any existing adjustment with the same reason to avoid duplicates
        conn = db.get_db()
        conn.execute(
            "DELETE FROM pto_manual_adjustments WHERE team_member_id=? AND reason=?",
            (tm_id, "Starting balance from V4 spreadsheet (pre-2026 carryover)"),
        )
        conn.commit()
        conn.close()
        db.add_pto_adjustment(
            team_member_id=tm_id,
            adjustment_days=round(start_days, 4),
            reason="Starting balance from V4 spreadsheet (pre-2026 carryover)",
            effective_date="2026-01-01",
        )
        count += 1
    return count


def import_weekly_accruals(data):
    """Import each week's accrual as a pto_accruals record.

    Uses the 'days_accrued_this_week' delta from the spreadsheet, which captures
    regular accrual + bank holiday accrual + any other adjustments the V4 tracker
    calculated. running_balance is the cumulative days directly from the sheet.
    """
    count = 0
    for tm_id, emp in data["employees"].items():
        accrual_type = "salaried" if emp["salaried"] else "hourly"

        for wk in emp["weeks"]:
            # Skip weeks with no change (no accrual, no hours)
            if wk.get("days_accrued_this_week", 0) == 0 and wk.get("hours_worked", 0) == 0:
                continue

            end_dt = datetime.strptime(wk["week_ending"], "%Y-%m-%d").date()
            start_dt = end_dt - timedelta(days=6)

            db.add_pto_accrual(
                team_member_id=tm_id,
                period_start=start_dt.strftime("%Y-%m-%d"),
                period_end=end_dt.strftime("%Y-%m-%d"),
                hours_worked=wk["hours_worked"],
                accrual_type=accrual_type,
                days_accrued=round(wk["days_accrued_this_week"], 4),
                running_balance=round(wk["running_days"], 4),
                source="v4_import",
            )
            count += 1
    return count


def import_days_taken(data):
    """Import the Days Taken log."""
    count = 0
    for dt in data["days_taken"]:
        db.add_pto_taken(
            team_member_id=dt["team_member_id"],
            date=dt["date"],
            days_taken=dt["days_taken"],
            hours_equivalent=dt["hours_equivalent"],
            reason=dt["reason"],
        )
        count += 1
    return count


def run_import():
    """Execute full historical import. Safe to run multiple times (uses UPSERT)."""
    data = load_historical_data()

    ensure_departed_employees_exist()
    adjustments = import_starting_balances(data)
    accruals = import_weekly_accruals(data)
    taken = import_days_taken(data)

    return {
        "employees": len(data["employees"]),
        "starting_balance_adjustments": adjustments,
        "weekly_accruals": accruals,
        "days_taken": taken,
    }
