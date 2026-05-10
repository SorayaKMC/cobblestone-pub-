"""Seed the recurring 'The Night Larry Got Stretched' series.

Pattern: first Sunday of each month.

Run once:
    python3 seed_larry_series.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--dry-run]

Defaults: start = next first-Sunday on or after today, end = 2026-12-31.
Idempotent: skips if a series with the same act_name overlapping the
range already exists.
"""

import argparse
from datetime import date, timedelta

import db


def _next_first_sunday(d):
    """Return the first Sunday of d's month; if it's already past, the
    first Sunday of the following month."""
    year, month = d.year, d.month
    while True:
        first = date(year, month, 1)
        offset = (6 - first.weekday()) % 7  # Sunday = 6
        candidate = first + timedelta(days=offset)
        if candidate >= d:
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default=None)
    p.add_argument("--end",   default="2026-12-31")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    start = date.fromisoformat(args.start) if args.start else _next_first_sunday(date.today())
    end   = date.fromisoformat(args.end)

    db.init_db()

    series_data = {
        "venue":         "Backroom",
        "event_type":    "Gig",
        "act_name":      "The Night Larry Got Stretched",
        "contact_name":  None,
        "contact_email": None,
        "contact_phone": None,
        "recurrence":    "monthly_first_weekday",
        "start_date":    start.isoformat(),
        "end_date":      end.isoformat(),
        "door_time":     None,
        "start_time":    None,
        "end_time":      None,
        "description":   "Recurring monthly storytelling/music night.",
        "notes":         "First Sunday of each month. To skip a month, cancel that individual booking.",
    }

    dates = db._generate_series_dates(
        series_data["start_date"], series_data["end_date"], series_data["recurrence"],
    )

    print(f"The Night Larry Got Stretched — {start} to {end}")
    print(f"  Pattern: monthly_first_weekday ({len(dates)} occurrences)")
    print()
    for d in dates:
        print(f"  {d}  ({date.fromisoformat(d).strftime('%A')})")

    if args.dry_run:
        print(f"\nDRY RUN — no rows written. Re-run without --dry-run to seed.")
        return

    # Idempotency check
    conn = db.get_db()
    existing = conn.execute(
        """SELECT id, start_date, end_date FROM booking_series
           WHERE act_name = ? AND end_date >= ? AND start_date <= ?""",
        (series_data["act_name"], series_data["start_date"], series_data["end_date"]),
    ).fetchone()
    if existing:
        print(f"\nSeries already exists (id={existing['id']}, "
              f"{existing['start_date']} → {existing['end_date']}). Skipping.")
        return

    print(f"\nCreating series + {len(dates)} bookings...")
    series_id, booking_ids = db.create_booking_series(series_data)
    print(f"Done. series_id={series_id}, {len(booking_ids)} booking rows created.")


if __name__ == "__main__":
    main()
