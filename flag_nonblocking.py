"""Flag bookings as non-blocking on the public calendar (for partial-day events).

When set, the booking still appears on internal views but the public booking
form's calendar shows the date as available. Use for daytime/afternoon-only
events that don't conflict with an evening gig (e.g. Dublin Jazz Coop's
Sunday 3pm slots).

Match by contact email, by act name (case-insensitive substring), or both.
Idempotent — re-running has no effect.

Usage:
    python3 flag_nonblocking.py --email dublinjazzcoop@gmail.com
    python3 flag_nonblocking.py --act-contains "jazz coop"
    python3 flag_nonblocking.py --email someone@x.ie --confirm
    python3 flag_nonblocking.py --unblock --email someone@x.ie  # reverse it
"""

import argparse
from datetime import datetime

import db


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", default=None,
                   help="Match bookings whose contact_email equals this (case-insensitive).")
    p.add_argument("--act-contains", default=None,
                   help="Match bookings whose act_name contains this (case-insensitive).")
    p.add_argument("--unblock", action="store_true",
                   help="Reverse: set blocks_public_calendar back to 1 (blocking).")
    p.add_argument("--confirm", action="store_true",
                   help="Actually update (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.email and not args.act_contains:
        print("ERROR: pass at least one of --email or --act-contains")
        return

    target = 1 if args.unblock else 0  # 0 = non-blocking, 1 = blocks
    target_label = "BLOCKING" if args.unblock else "non-blocking"

    db.init_db()
    conn = db.get_db()

    where = []
    params = []
    if args.email:
        where.append("LOWER(contact_email) = ?")
        params.append(args.email.strip().lower())
    if args.act_contains:
        where.append("LOWER(act_name) LIKE ?")
        params.append(f"%{args.act_contains.strip().lower()}%")
    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"""SELECT id, act_name, event_date, contact_email, blocks_public_calendar
            FROM bookings
            WHERE {where_sql} AND archived_at IS NULL
            ORDER BY event_date""",
        params,
    ).fetchall()

    if not rows:
        print("No matching bookings found.")
        return

    needs_change = [r for r in rows if r["blocks_public_calendar"] != target]
    already_set  = [r for r in rows if r["blocks_public_calendar"] == target]

    print(f"Matched {len(rows)} booking(s). {len(needs_change)} need update; {len(already_set)} already {target_label}.\n")

    if needs_change:
        print(f"Will set the following to {target_label}:")
        for r in needs_change:
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']}  ({r['contact_email']})")

    if not args.confirm:
        print(f"\nDRY RUN — re-run with --confirm to update {len(needs_change)} booking(s).")
        return

    if not needs_change:
        print("Nothing to update. ✓")
        return

    print(f"\nUpdating {len(needs_change)} bookings...")
    now = datetime.now().isoformat()
    detail = (f"Set blocks_public_calendar={target} via flag_nonblocking.py "
              f"({'restored to blocking' if args.unblock else 'partial-day event'})")
    for r in needs_change:
        conn.execute(
            "UPDATE bookings SET blocks_public_calendar = ?, updated_at = ? WHERE id = ?",
            (target, now, r["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (r["id"], "internal",
             "set_non_blocking" if not args.unblock else "set_blocking",
             detail),
        )
    conn.commit()
    conn.close()
    print(f"Done. {len(needs_change)} bookings updated.")


if __name__ == "__main__":
    main()
