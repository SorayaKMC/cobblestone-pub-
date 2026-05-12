"""Compare OLD vs NEW 13-week-avg-shift calc for Oonagh Flynn.

Helps verify the vacation-resistant fix actually fixes her dropping avg.
Run on Render Shell — pulls live Square data.

Usage:
    python3 compare_oonagh_avg.py
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import square_client
import pto_engine


def _old_calc(tm_id, end_str):
    """The OLD 13-calendar-week logic, replicated for comparison."""
    start_dt = datetime.strptime(end_str, "%Y-%m-%d") - timedelta(weeks=13)
    start_str = start_dt.strftime("%Y-%m-%d")
    try:
        tcs = square_client.get_timecards(start_str, end_str)
    except Exception:
        return pto_engine.DEFAULT_SHIFT_HOURS, 0
    by_date = pto_engine._shifts_grouped_by_date(tcs, tm_id)
    shifts = list(by_date.values())
    if len(shifts) < 5:
        return pto_engine.DEFAULT_SHIFT_HOURS, len(shifts)
    avg = sum(shifts) / Decimal(str(len(shifts)))
    return avg.quantize(Decimal("0.01")), len(shifts)


def _new_calc_with_count(tm_id, end_str):
    """NEW logic, but also return shift count for transparency."""
    start_dt = datetime.strptime(end_str, "%Y-%m-%d") - timedelta(weeks=26)
    start_str = start_dt.strftime("%Y-%m-%d")
    try:
        tcs = square_client.get_timecards(start_str, end_str)
    except Exception:
        return pto_engine.DEFAULT_SHIFT_HOURS, 0
    by_date = pto_engine._shifts_grouped_by_date(tcs, tm_id)
    shifts = pto_engine._last_n_active_weeks_shifts(by_date, n=13)
    if len(shifts) < 5:
        return pto_engine.DEFAULT_SHIFT_HOURS, len(shifts)
    avg = sum(shifts) / Decimal(str(len(shifts)))
    return avg.quantize(Decimal("0.01")), len(shifts)


def main():
    # Find Oonagh
    team = square_client.get_team_members()
    oonagh = None
    for m in team:
        full = f"{m.get('given_name','')} {m.get('family_name','')}".lower()
        if "oonagh" in full or "flynn" in full:
            oonagh = m
            break
    if not oonagh:
        print("Couldn't find Oonagh in Square team members.")
        return

    tm_id = oonagh["id"]
    name = f"{oonagh.get('given_name','')} {oonagh.get('family_name','')}"
    print(f"\nComparing 13-week avg shift for {name} ({tm_id})\n")
    print(f"  {'Week ending':<14} | {'OLD calc':<22} | {'NEW calc':<22} | Delta")
    print(f"  {'-' * 14} | {'-' * 22} | {'-' * 22} | {'-' * 6}")

    # Last 3 Sundays (week-ending dates)
    today = date.today()
    days_since_sun = (today.weekday() + 1) % 7
    last_sunday = today - timedelta(days=days_since_sun)
    if days_since_sun == 0:
        last_sunday = today  # if today IS Sunday, use today

    for i in range(3):
        end_date = last_sunday - timedelta(weeks=i)
        end_str = end_date.isoformat()
        old_avg, old_n = _old_calc(tm_id, end_str)
        new_avg, new_n = _new_calc_with_count(tm_id, end_str)
        delta = float(new_avg) - float(old_avg)
        print(f"  {end_str:<14} | {float(old_avg):>5.2f} hrs over {old_n:>2} shifts | "
              f"{float(new_avg):>5.2f} hrs over {new_n:>2} shifts | {delta:+.2f}")

    print()
    print("If Delta is + (positive), the new calc gives Oonagh credit for her")
    print("vacation weeks not pulling the avg down — i.e., the fix is doing its job.")


if __name__ == "__main__":
    main()
