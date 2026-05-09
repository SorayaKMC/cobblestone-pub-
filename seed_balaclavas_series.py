"""Seed the recurring Balaclavas BackBar series.

Pattern: every Wednesday EXCEPT the first Wednesday of each month.
First Wednesdays remain bookable for gigs; manager can manually add a
Balaclavas booking on a first Wed if needed (override).

Run once:
    python3 seed_balaclavas_series.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--dry-run]

Defaults: start = next Wednesday from today, end = 2026-12-31.
"""

import sys
import argparse
from datetime import date, timedelta

import db


def _next_wednesday(d):
    """Return the date of the next Wednesday on or after d."""
    days_ahead = (2 - d.weekday()) % 7  # Wednesday == 2
    return d + timedelta(days=days_ahead)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default=None,
                   help="Start date YYYY-MM-DD (default: next Wednesday).")
    p.add_argument("--end", default="2026-12-31",
                   help="End date YYYY-MM-DD (default: 2026-12-31).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the dates that would be created — don't write.")
    return p.parse_args()


def main():
    args = parse_args()

    start = date.fromisoformat(args.start) if args.start else _next_wednesday(date.today())
    end   = date.fromisoformat(args.end)

    db.init_db()

    series_data = {
        "venue":         "Backroom",
        "event_type":    "Other",
        "act_name":      "Balaclavas BackBar",
        "contact_name":  None,
        "contact_email": None,
        "contact_phone": None,
        "recurrence":    "weekly_skip_first",
        "start_date":    start.isoformat(),
        "end_date":      end.isoformat(),
        "door_time":     None,
        "start_time":    None,
        "end_time":      None,
        "description":   "Recurring Wednesday night session in the back bar.",
        "notes":         "Auto-skips first Wednesday of each month. To override (run a Balaclavas night on a first Wed), add as a standalone booking.",
    }

    # Preview the dates
    dates = db._generate_series_dates(
        series_data["start_date"],
        series_data["end_date"],
        series_data["recurrence"],
    )

    print(f"Balaclavas BackBar series — {start} to {end}")
    print(f"  Pattern: weekly_skip_first ({len(dates)} occurrences)")
    print()
    for d in dates:
        print(f"  {d}  ({date.fromisoformat(d).strftime('%A')})")

    if args.dry_run:
        print(f"\nDRY RUN — no rows written. Re-run without --dry-run to seed.")
        return

    print(f"\nCreating series + {len(dates)} bookings...")
    series_id, booking_ids = db.create_booking_series(series_data)
    print(f"Done. series_id={series_id}, {len(booking_ids)} booking rows created.")


if __name__ == "__main__":
    main()
