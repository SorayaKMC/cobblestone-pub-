"""Re-sync Google Calendar from the bookings DB.

Walks every confirmed, non-archived, future booking and ensures the
Google Calendar event matches what's in the DB. Useful as a one-shot
recovery after a bug that may have silently failed to update Calendar
events (e.g. the sqlite3.Row.get() bug, now fixed).

What it does:

  Confirmed booking WITH google_calendar_event_id set:
    → calls update_calendar_event() to refresh the event description
      (act name, times, contact info, support act, notes, etc.)

  Confirmed booking WITHOUT google_calendar_event_id (unlinked):
    → reports it. By default, does NOT auto-create — to avoid
      duplicating events that already exist on the calendar from a
      bulk import. Pass --create-missing to actually create them.

  Non-confirmed booking WITH google_calendar_event_id (stale):
    → reports it. Pass --delete-stale to delete the calendar event
      (e.g. for bookings that were demoted from confirmed to
      tentative/hold/cancelled while the bug was active).

Usage:
    python3 sync_calendar.py                     # dry-run report
    python3 sync_calendar.py --confirm           # refresh linked events
    python3 sync_calendar.py --confirm --create-missing  # also create unlinked
    python3 sync_calendar.py --confirm --delete-stale    # also clean stale
    python3 sync_calendar.py --confirm --create-missing --delete-stale  # full
"""

import argparse
import time
from datetime import date

import db
import calendar_client


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually apply changes (default: dry-run report).")
    p.add_argument("--create-missing", action="store_true",
                   help="Also create Calendar events for confirmed bookings "
                        "that don't have one. WARNING: may duplicate if an "
                        "event already exists on the calendar.")
    p.add_argument("--delete-stale", action="store_true",
                   help="Also delete Calendar events linked to bookings that "
                        "are no longer confirmed (tentative/hold/cancelled).")
    p.add_argument("--delay", type=float, default=0.5,
                   help="Seconds to pause between API calls (default: 0.5).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()
    today = date.today().isoformat()

    # Pull all upcoming bookings (any status) — we'll partition by what to do
    rows = conn.execute(
        """SELECT * FROM bookings
           WHERE event_date >= ?
             AND archived_at IS NULL
           ORDER BY event_date""",
        (today,),
    ).fetchall()
    conn.close()

    refresh = []       # confirmed + has event_id → update
    create  = []       # confirmed + no event_id → create (only if flag)
    stale   = []       # not-confirmed + has event_id → delete (only if flag)

    for r in rows:
        has_event = bool(r["google_calendar_event_id"])
        is_confirmed = r["status"] == "confirmed"
        if is_confirmed and has_event:
            refresh.append(r)
        elif is_confirmed and not has_event:
            create.append(r)
        elif not is_confirmed and has_event:
            stale.append(r)

    print(f"\n{'DRY RUN — ' if not args.confirm else ''}"
          f"Calendar sync — {today} onwards\n")
    print(f"  Confirmed bookings with calendar event   : {len(refresh):>4}  (will refresh)")
    print(f"  Confirmed bookings WITHOUT calendar event: {len(create):>4}  "
          f"(will create)" if args.create_missing else
          f"  Confirmed bookings WITHOUT calendar event: {len(create):>4}  "
          f"(reporting only — pass --create-missing to create)")
    print(f"  Non-confirmed bookings WITH stale event  : {len(stale):>4}  "
          f"(will delete)" if args.delete_stale else
          f"  Non-confirmed bookings WITH stale event  : {len(stale):>4}  "
          f"(reporting only — pass --delete-stale to clean up)")
    print()

    # Show details
    if refresh:
        print(f"--- Refresh ({len(refresh)} events) ---")
        for r in refresh[:50]:
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']}")
        if len(refresh) > 50:
            print(f"  ... and {len(refresh) - 50} more")

    if create:
        print(f"\n--- Confirmed but unlinked ({len(create)} bookings) ---")
        for r in create:
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']}  "
                  f"({r['event_type'] or '?'})")

    if stale:
        print(f"\n--- Stale calendar events ({len(stale)} events) ---")
        for r in stale:
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']}  "
                  f"(status={r['status']})")

    if not args.confirm:
        print("\nDRY RUN — re-run with --confirm to apply changes.")
        return

    # Apply changes
    ok = fail = 0

    # 1. Refresh existing events
    if refresh:
        print(f"\nRefreshing {len(refresh)} Calendar event(s)...")
        for r in refresh:
            try:
                if calendar_client.update_calendar_event(r, r["google_calendar_event_id"]):
                    ok += 1
                else:
                    fail += 1
                    print(f"  FAILED to refresh #{r['id']} {r['act_name']}")
            except Exception as e:
                fail += 1
                print(f"  ERROR on #{r['id']} {r['act_name']}: {e}")
            time.sleep(args.delay)

    # 2. Create missing events
    if args.create_missing and create:
        print(f"\nCreating {len(create)} new Calendar event(s)...")
        for r in create:
            try:
                event_id = calendar_client.create_calendar_event(r)
                if event_id:
                    db.update_booking_field(
                        r["id"], "google_calendar_event_id", event_id, actor="system",
                    )
                    db.add_booking_audit(
                        r["id"], "system", "calendar_event_created",
                        f"Created via sync_calendar.py: event_id={event_id}",
                    )
                    ok += 1
                    print(f"  Created #{r['id']} → event {event_id[:12]}…")
                else:
                    fail += 1
                    print(f"  FAILED to create #{r['id']} {r['act_name']}")
            except Exception as e:
                fail += 1
                print(f"  ERROR on #{r['id']} {r['act_name']}: {e}")
            time.sleep(args.delay)

    # 3. Delete stale events
    if args.delete_stale and stale:
        print(f"\nDeleting {len(stale)} stale Calendar event(s)...")
        for r in stale:
            try:
                if calendar_client.delete_calendar_event(r, r["google_calendar_event_id"]):
                    db.update_booking_field(
                        r["id"], "google_calendar_event_id", None, actor="system",
                    )
                    db.add_booking_audit(
                        r["id"], "system", "calendar_event_deleted",
                        f"Stale event cleaned up via sync_calendar.py "
                        f"(booking status was {r['status']})",
                    )
                    ok += 1
                else:
                    fail += 1
                    print(f"  FAILED to delete #{r['id']} {r['act_name']}")
            except Exception as e:
                fail += 1
                print(f"  ERROR on #{r['id']} {r['act_name']}: {e}")
            time.sleep(args.delay)

    print(f"\nDone. Operations succeeded: {ok}  Failed: {fail}")


if __name__ == "__main__":
    main()
