"""Backfill: clear door_fee_required on confirmed bookings older than 6 weeks.

These bookings were made before the new €50 door-person-fee policy, so
the fee shouldn't apply. This script flips door_fee_required from 1→0
on every confirmed booking whose created_at is more than 6 weeks ago.

Idempotent — safe to re-run. The /admin/run-reminders cron also calls
db.auto_clear_legacy_door_fees() nightly, so going forward this happens
automatically as bookings cross the 6-week line.

Usage:
    python3 backfill_legacy_door_fees.py            # dry-run preview
    python3 backfill_legacy_door_fees.py --confirm  # apply
"""

import argparse
from datetime import date, datetime, timedelta

import db


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually apply changes (default: dry-run report).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()

    cutoff = (date.today() - timedelta(weeks=6)).isoformat()
    rows = conn.execute(
        """SELECT id, event_date, act_name, contact_email, created_at, source,
                  door_fee_required, door_fee_paid_at
           FROM bookings
           WHERE status='confirmed'
             AND door_fee_required=1
             AND archived_at IS NULL
             AND (
                 source = 'form-import'
                 OR substr(created_at, 1, 10) < ?
             )
           ORDER BY event_date""",
        (cutoff,),
    ).fetchall()

    print(f"\nBackfill — clear door_fee_required on legacy confirmed bookings")
    print(f"Rule: source='form-import' OR created before {cutoff} (6 weeks ago)\n")
    print(f"Found {len(rows)} booking(s) that need door_fee_required cleared:")
    print()
    for r in rows:
        why = "form-import" if r["source"] == "form-import" else f"created {r['created_at'][:10]}"
        paid_note = " ⚠ already-paid door fee on file" if r["door_fee_paid_at"] else ""
        print(f"  #{r['id']:>4}  [{why:<18}]  event {r['event_date']}  "
              f"{(r['act_name'] or '')[:40]}{paid_note}")

    if not rows:
        print("Nothing to backfill. ✓")
        conn.close()
        return

    if not args.confirm:
        print(f"\nDRY RUN — re-run with --confirm to clear door_fee_required on {len(rows)} bookings.")
        conn.close()
        return

    now = datetime.now().isoformat()
    for r in rows:
        conn.execute(
            "UPDATE bookings SET door_fee_required=0, updated_at=? WHERE id=?",
            (now, r["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (r["id"], "internal", "door_fee_cleared",
             f"Backfill: cleared door_fee_required (legacy booking, "
             f"created {r['created_at'][:10]}, before cutoff {cutoff}). "
             f"Via backfill_legacy_door_fees.py."),
        )
    conn.commit()
    conn.close()
    print(f"\nDone. {len(rows)} bookings updated.")


if __name__ == "__main__":
    main()
