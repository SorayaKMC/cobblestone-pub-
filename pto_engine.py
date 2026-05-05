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


def _shifts_grouped_by_date(timecards, team_member_id=None):
    """Group raw timecards into per-date totals so a 'shift' = one workday,
    even if the employee clocked in/out twice (split shift across a break).

    Returns {iso_date: total_paid_hours} (only dates with > 0 hours).
    """
    from datetime import datetime as _dt
    by_date = {}
    for tc in timecards:
        if team_member_id is not None and tc["team_member_id"] != team_member_id:
            continue
        if tc["paid_minutes"] <= 0:
            continue
        start_str = tc.get("start_at")
        if not start_str:
            continue
        try:
            day = _dt.fromisoformat(start_str.replace("Z", "+00:00")).date().isoformat()
        except Exception:
            continue
        by_date[day] = by_date.get(day, Decimal("0")) + (tc["paid_minutes"] / Decimal("60"))
    # Strip days with zero hours just in case
    return {d: h for d, h in by_date.items() if h > 0}


def calculate_13_week_avg_shift(team_member_id, end_date):
    """Calculate the 13-week rolling average shift length for an employee.

    A 'shift' is one workday — split shifts (e.g. lunch service + dinner
    service with a break in between) are summed into a single shift.

    Args:
        team_member_id: Square team member ID
        end_date: 'YYYY-MM-DD' - the end of the period to look back from

    Returns Decimal average hours per shift, or DEFAULT_SHIFT_HOURS if
    insufficient data (fewer than 5 shifts in the lookback window).
    """
    from datetime import datetime, timedelta
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(weeks=13)
    start_str = start_dt.strftime("%Y-%m-%d")

    try:
        timecards = square_client.get_timecards(start_str, end_date)
    except Exception:
        return DEFAULT_SHIFT_HOURS

    by_date = _shifts_grouped_by_date(timecards, team_member_id)
    shift_hours = list(by_date.values())

    if len(shift_hours) < 5:
        return DEFAULT_SHIFT_HOURS

    avg = sum(shift_hours) / Decimal(str(len(shift_hours)))
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

    # Group timecards per-employee, per-date so split shifts in one
    # workday count as a single shift.
    from datetime import datetime as _dt
    by_emp_date = {tm_id: {} for tm_id in employee_ids}
    for tc in timecards:
        tm_id = tc.get("team_member_id")
        if tm_id not in by_emp_date or tc["paid_minutes"] <= 0:
            continue
        start_str_tc = tc.get("start_at")
        if not start_str_tc:
            continue
        try:
            day = _dt.fromisoformat(start_str_tc.replace("Z", "+00:00")).date().isoformat()
        except Exception:
            continue
        by_emp_date[tm_id][day] = (
            by_emp_date[tm_id].get(day, Decimal("0"))
            + (tc["paid_minutes"] / Decimal("60"))
        )

    result = {}
    for tm_id in employee_ids:
        shift_hours = [h for h in by_emp_date.get(tm_id, {}).values() if h > 0]
        if len(shift_hours) < 5:
            result[tm_id] = DEFAULT_SHIFT_HOURS
        else:
            avg = sum(shift_hours) / Decimal(str(len(shift_hours)))
            result[tm_id] = avg.quantize(Decimal("0.01"))

    return result


def get_employee_accrual_type(team_member_id, team_members=None):
    """Determine if employee is hourly or salaried for PTO accrual purposes.

    Local Settings is the source of truth — at Cobblestone, Management
    staff are salaried but clock in via Square so we can track how much
    of their time is spent bartending. Square has them as HOURLY but
    their PTO accrual must follow their salaried status (0.4 days/week
    flat, not 8.08% of hours).

    Returns 'hourly' or 'salaried'.
    """
    cat = db.get_employee_category(team_member_id)
    if cat:
        pt = (cat["pay_type"] or "").lower()
        if pt == "salaried":
            return "salaried"
        if pt == "hourly":
            return "hourly"

    # Fall back to Square's pay_type if no local record found
    if team_members is None:
        team_members = square_client.get_team_members()
    for m in team_members:
        if m["id"] == team_member_id:
            if m["pay_type"] == "SALARY":
                return "salaried"
            return "hourly"

    return "hourly"


def calculate_weekly_accrual(team_member_id, start_date, end_date, team_members=None,
                              manual_hours_override=None):
    """Calculate PTO accrual for one week.

    Hours are sourced from Square timecards (grouped by date so split shifts
    in one workday count as one shift). If `manual_hours_override` is given,
    those hours are used instead — for cases where the employee doesn't
    clock into Square but worked hours we know from elsewhere (Peter's
    payslip, manager-recorded hours, etc.).

    Args:
        team_member_id: Square team member ID
        start_date: 'YYYY-MM-DD' Monday
        end_date: 'YYYY-MM-DD' Sunday
        manual_hours_override: Decimal | float | None

    Returns dict: hours_worked, accrued_hours, days_accrued, accrual_type,
                  avg_shift, shifts_count, source ('square' | 'manual').
    """
    accrual_type = get_employee_accrual_type(team_member_id, team_members)

    if manual_hours_override is not None and Decimal(str(manual_hours_override)) > 0:
        hours_worked = Decimal(str(manual_hours_override))
        shifts_count = 1  # treat manual entry as one workday
        source = "manual"
    else:
        try:
            timecards = square_client.get_timecards(start_date, end_date)
        except Exception:
            timecards = []
        # Group by date so split shifts (lunch + dinner with a break) count
        # as a single shift, matching how Cobblestone treats a workday.
        by_date = _shifts_grouped_by_date(timecards, team_member_id)
        hours_worked = sum(by_date.values(), Decimal("0"))
        shifts_count = len(by_date)
        source = "square"

    if accrual_type == "salaried":
        # Salaried staff accrue a flat 0.4 days every week regardless of
        # whether they clocked in (they don't, by definition — Square
        # timecards are for hourly staff). The previous gate on
        # shifts_count > 0 silently zeroed every salaried week.
        days_accrued = SALARIED_WEEKLY
        avg_shift = DEFAULT_SHIFT_HOURS
        accrued_hours = days_accrued * avg_shift
    else:
        # 8.08% of hours; days = accrued hours / avg shift hours
        accrued_hours = hours_worked * ACCRUAL_RATE
        avg_shift = calculate_13_week_avg_shift(team_member_id, end_date)
        if avg_shift > 0:
            days_accrued = accrued_hours / avg_shift
        else:
            days_accrued = Decimal("0")

    return {
        "hours_worked": hours_worked.quantize(Decimal("0.01")),
        "accrued_hours": accrued_hours.quantize(Decimal("0.0001")),
        "accrual_type": accrual_type,
        "days_accrued": days_accrued.quantize(Decimal("0.0001")),
        "avg_shift": avg_shift,
        "shifts_count": shifts_count,
        "source": source,
    }


def recalculate_pto(team_member_id, from_date, to_date, team_members=None):
    """Recalculate PTO accruals for an employee over a date range.

    Upper Management employees are skipped entirely — per Cobblestone
    policy they don't accrue annual leave through this system.

    Iterates week by week, calculating accruals and updating the database.
    Returns the final running balance.
    """
    from datetime import datetime, timedelta

    cat = db.get_employee_category(team_member_id)
    if cat and cat["category"] == "Upper Management":
        return {"final_balance": 0.0, "skipped_protected": 0,
                "skipped_reason": "upper_management"}

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

        # Skip protected weeks (e.g. imported from V4 spreadsheet) — but
        # NOT manual-hours rows, since those are still accrual-driven and
        # should be re-summed alongside Square data.
        if db.is_pto_accrual_protected(team_member_id, week_start):
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

        # Pick up any manual hours override stored against this employee + week
        manual_override = db.get_manual_hours(team_member_id, week_start)
        accrual = calculate_weekly_accrual(
            team_member_id, week_start, week_end, team_members,
            manual_hours_override=manual_override,
        )

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
            source=accrual.get("source", "square"),
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
