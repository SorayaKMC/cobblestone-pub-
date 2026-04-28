"""PTO accrual engine for Cobblestone Pub.

Rules (matching PTO Annual Leave Tracker V4):
- Hourly staff: 8.08% of hours worked, converted to days using 13-week avg shift
- Salaried staff: 0.4 days per week worked
- Maximum cap: 21 days
"""

from decimal import Decimal
import square_client
import db

ACCRUAL_RATE = Decimal("0.0808")
SALARIED_WEEKLY = Decimal("0.4")
MAX_DAYS = Decimal("21")
DEFAULT_SHIFT_HOURS = Decimal("8.0")


def calculate_13_week_avg_shift(team_member_id, end_date):
    """Calculate the 13-week rolling average shift length for an employee.

    Args:
        team_member_id: Square team member ID
        end_date: 'YYYY-MM-DD' - the end of the period to look back from

    Returns Decimal average hours per shift, or DEFAULT_SHIFT_HOURS if insufficient data.
    """
    from datetime import datetime, timedelta
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(weeks=13)
    start_str = start_dt.strftime("%Y-%m-%d")

    try:
        timecards = square_client.get_timecards(start_str, end_date)
    except Exception:
        return DEFAULT_SHIFT_HOURS

    # Filter to this employee's closed timecards
    shifts = []
    for tc in timecards:
        if tc["team_member_id"] == team_member_id and tc["paid_minutes"] > 0:
            shift_hours = tc["paid_minutes"] / Decimal("60")
            shifts.append(shift_hours)

    if len(shifts) < 5:
        return DEFAULT_SHIFT_HOURS

    avg = sum(shifts) / Decimal(str(len(shifts)))
    return avg.quantize(Decimal("0.01"))


def calculate_13_week_avg_shift_batch(employee_ids, end_date):
    """Batch version: compute 13-week rolling avg shift for all given employee IDs.

    Makes a SINGLE Square API call covering the full 13-week window, then groups
    results by team member — much faster than calling calculate_13_week_avg_shift
    once per employee.

    Args:
        employee_ids: list of Square team member IDs to compute for
        end_date: 'YYYY-MM-DD' end of lookback window

    Returns dict: {team_member_id: Decimal avg_shift}
    Missing / insufficient employees fall back to DEFAULT_SHIFT_HOURS.
    """
    from datetime import datetime, timedelta

    if not employee_ids:
        return {}

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(weeks=13)
    start_str = start_dt.strftime("%Y-%m-%d")

    try:
        timecards = square_client.get_timecards(start_str, end_date)
    except Exception:
        return {tm_id: DEFAULT_SHIFT_HOURS for tm_id in employee_ids}

    shifts_by_emp = {tm_id: [] for tm_id in employee_ids}
    for tc in timecards:
        tm_id = tc["team_member_id"]
        if tm_id in shifts_by_emp and tc["paid_minutes"] > 0:
            shift_hours = tc["paid_minutes"] / Decimal("60")
            shifts_by_emp[tm_id].append(shift_hours)

    result = {}
    for tm_id in employee_ids:
        shifts = shifts_by_emp.get(tm_id, [])
        if len(shifts) < 5:
            result[tm_id] = DEFAULT_SHIFT_HOURS
        else:
            avg = sum(shifts) / Decimal(str(len(shifts)))
            result[tm_id] = avg.quantize(Decimal("0.01"))

    return result


def get_employee_accrual_type(team_member_id, team_members=None):
    """Determine if employee is hourly or salaried.

    Returns 'hourly' or 'salaried'.
    """
    if team_members is None:
        team_members = square_client.get_team_members()

    for m in team_members:
        if m["id"] == team_member_id:
            if m["pay_type"] == "SALARY":
                return "salaried"
            return "hourly"

    return "hourly"


def calculate_weekly_accrual(team_member_id, start_date, end_date, team_members=None):
    """Calculate PTO accrual for one week.

    Args:
        team_member_id: Square team member ID
        start_date: 'YYYY-MM-DD' Monday
        end_date: 'YYYY-MM-DD' Sunday

    Returns dict: hours_worked, accrual_type, days_accrued, avg_shift
    """
    accrual_type = get_employee_accrual_type(team_member_id, team_members)

    # Get hours worked this week
    try:
        timecards = square_client.get_timecards(start_date, end_date)
    except Exception:
        timecards = []

    hours_worked = Decimal("0")
    shifts_count = 0
    for tc in timecards:
        if tc["team_member_id"] == team_member_id and tc["paid_minutes"] > 0:
            hours_worked += tc["paid_minutes"] / Decimal("60")
            shifts_count += 1

    if accrual_type == "salaried":
        # 0.4 days per week, pro-rated if partial
        days_accrued = SALARIED_WEEKLY if shifts_count > 0 else Decimal("0")
        avg_shift = DEFAULT_SHIFT_HOURS
    else:
        # 8.08% of hours, converted to days
        accrual_hours = hours_worked * ACCRUAL_RATE
        avg_shift = calculate_13_week_avg_shift(team_member_id, end_date)
        if avg_shift > 0:
            days_accrued = accrual_hours / avg_shift
        else:
            days_accrued = Decimal("0")

    return {
        "hours_worked": hours_worked.quantize(Decimal("0.01")),
        "accrual_type": accrual_type,
        "days_accrued": days_accrued.quantize(Decimal("0.0001")),
        "avg_shift": avg_shift,
        "shifts_count": shifts_count,
    }


def recalculate_pto(team_member_id, from_date, to_date, team_members=None):
    """Recalculate PTO accruals for an employee over a date range.

    Iterates week by week, calculating accruals and updating the database.
    Returns the final running balance.
    """
    from datetime import datetime, timedelta

    start_dt = datetime.strptime(from_date, "%Y-%m-%d")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d")

    # Align to Monday
    while start_dt.weekday() != 0:
        start_dt -= timedelta(days=1)

    # Get existing balance before from_date
    conn = db.get_db()
    row = conn.execute(
        """SELECT running_balance FROM pto_accruals
           WHERE team_member_id = ? AND period_start < ?
           ORDER BY period_start DESC LIMIT 1""",
        (team_member_id, from_date),
    ).fetchone()
    conn.close()

    running_balance = Decimal(str(row["running_balance"])) if row else Decimal("0")

    # Also account for any manual adjustments
    conn = db.get_db()
    adj_row = conn.execute(
        """SELECT COALESCE(SUM(adjustment_days), 0) as total
           FROM pto_manual_adjustments
           WHERE team_member_id = ? AND effective_date < ?""",
        (team_member_id, from_date),
    ).fetchone()
    conn.close()

    current_dt = start_dt
    skipped = 0
    while current_dt <= end_dt:
        week_start = current_dt.strftime("%Y-%m-%d")
        week_end = (current_dt + timedelta(days=6)).strftime("%Y-%m-%d")

        # Skip protected weeks (e.g. imported from V4 spreadsheet)
        if db.is_pto_accrual_protected(team_member_id, week_start):
            # Still advance the running balance using the existing value
            conn = db.get_db()
            existing = conn.execute(
                "SELECT running_balance FROM pto_accruals WHERE team_member_id=? AND period_start=?",
                (team_member_id, week_start),
            ).fetchone()
            conn.close()
            if existing:
                running_balance = Decimal(str(existing["running_balance"]))
            skipped += 1
            current_dt += timedelta(weeks=1)
            continue

        accrual = calculate_weekly_accrual(team_member_id, week_start, week_end, team_members)

        # Get days taken this week
        conn = db.get_db()
        taken_row = conn.execute(
            """SELECT COALESCE(SUM(days_taken), 0) as total
               FROM pto_taken
               WHERE team_member_id = ? AND date BETWEEN ? AND ?""",
            (team_member_id, week_start, week_end),
        ).fetchone()
        conn.close()
        days_taken = Decimal(str(taken_row["total"]))

        # Get adjustments this week
        conn = db.get_db()
        adj_row = conn.execute(
            """SELECT COALESCE(SUM(adjustment_days), 0) as total
               FROM pto_manual_adjustments
               WHERE team_member_id = ? AND effective_date BETWEEN ? AND ?""",
            (team_member_id, week_start, week_end),
        ).fetchone()
        conn.close()
        week_adj = Decimal(str(adj_row["total"]))

        running_balance = running_balance + accrual["days_accrued"] - days_taken + week_adj
        running_balance = min(running_balance, MAX_DAYS)
        running_balance = max(running_balance, Decimal("0"))

        db.add_pto_accrual(
            team_member_id=team_member_id,
            period_start=week_start,
            period_end=week_end,
            hours_worked=float(accrual["hours_worked"]),
            accrual_type=accrual["accrual_type"],
            days_accrued=float(accrual["days_accrued"]),
            running_balance=float(running_balance),
            source="square",
            respect_protected=True,
        )

        current_dt += timedelta(weeks=1)

    return {"final_balance": float(running_balance), "skipped_protected": skipped}


def get_pto_status(balance):
    """Return status label and CSS class based on balance."""
    if balance >= 21:
        return "At Cap", "status-at-cap"
    elif balance >= 18:
        return "Near Limit", "status-near-limit"
    elif balance < 3:
        return "Low", "status-low"
    return "OK", "status-ok"
