"""Retag existing in-house residency series as event_type='Residency Gigs'.

Updates Balaclavas, Caoimhe, Larry's Night and Piper's Club bookings
(NOT Flying Monkeys — they need a sound engineer so they're treated
as regular gigs). Idempotent — safe to re-run.

Usage:
    python3 retag_residencies.py            # dry-run
    python3 retag_residencies.py --confirm  # actually update
"""

import argparse
from datetime import datetime

import db


# Match patterns for the residencies (case-insensitive substring on act_name)
RESIDENCY_PATTERNS = [
    ("Balaclavas",   "%balaclavas%"),
    ("Caoimhe dance", "%caoimhe%"),
    ("Larry's Night", "%larry%night%"),
    ("Piper's Club",  "%piper%"),
]

TARGET_EVENT_TYPE = "Residency Gigs"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually update (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()

    total_matched = 0
    total_already = 0
    rows_to_update = []

    print("Scanning for in-house residency series:\n")
    for label, pattern in RESIDENCY_PATTERNS:
        rows = conn.execute(
            """SELECT id, act_name, event_date, event_type FROM bookings
               WHERE LOWER(act_name) LIKE ?
                 AND archived_at IS NULL
               ORDER BY event_date""",
            (pattern.lower(),),
        ).fetchall()
        needs_update = [r for r in rows if r["event_type"] != TARGET_EVENT_TYPE]
        already_ok   = [r for r in rows if r["event_type"] == TARGET_EVENT_TYPE]
        print(f"  {label:<18}: {len(rows):>3} matched  "
              f"({len(needs_update)} need update, {len(already_ok)} already tagged)")
        rows_to_update.extend(needs_update)
        total_matched += len(rows)
        total_already += len(already_ok)

    print(f"\nTotal matched      : {total_matched}")
    print(f"Already tagged ✓   : {total_already}")
    print(f"Need event_type fix: {len(rows_to_update)}")

    if not rows_to_update:
        print("\nNothing to update. ✓")
        return

    if not args.confirm:
        print(f"\n--- Would update these {len(rows_to_update)} rows ---")
        for r in rows_to_update[:30]:
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']:<40}  "
                  f"({r['event_type']!r} → '{TARGET_EVENT_TYPE}')")
        if len(rows_to_update) > 30:
            print(f"  ... and {len(rows_to_update) - 30} more")
        print(f"\nDRY RUN — re-run with --confirm to update.")
        return

    print(f"\nUpdating {len(rows_to_update)} bookings...")
    now = datetime.now().isoformat()
    for r in rows_to_update:
        conn.execute(
            "UPDATE bookings SET event_type = ?, updated_at = ? WHERE id = ?",
            (TARGET_EVENT_TYPE, now, r["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (r["id"], "internal", "retagged",
             f"Retagged event_type {r['event_type']!r} → '{TARGET_EVENT_TYPE}' "
             f"via retag_residencies.py"),
        )
    conn.commit()
    conn.close()
    print(f"Done. {len(rows_to_update)} bookings retagged as '{TARGET_EVENT_TYPE}'.")


if __name__ == "__main__":
    main()
