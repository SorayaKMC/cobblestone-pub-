"""Archive any cancelled bookings that aren't already archived.

Backfill for cancellations that happened before auto-archive-on-cancel
was wired up. Idempotent — safe to re-run.

Usage:
    python3 archive_cancelled_bookings.py            # dry run
    python3 archive_cancelled_bookings.py --confirm  # do it
"""

import argparse
from datetime import datetime

import db


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually archive (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()

    rows = conn.execute(
        """SELECT id, act_name, event_date, cancelled_by
           FROM bookings
           WHERE status = 'cancelled' AND archived_at IS NULL
           ORDER BY event_date DESC"""
    ).fetchall()

    if not rows:
        print("No cancelled-but-unarchived bookings found. Nothing to do. ✓")
        return

    print(f"Found {len(rows)} cancelled booking(s) without archived_at:")
    for r in rows:
        cb = f" (cancelled by {r['cancelled_by']})" if r["cancelled_by"] else ""
        print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']}{cb}")

    if not args.confirm:
        print(f"\nDRY RUN — re-run with --confirm to archive these {len(rows)} bookings.")
        return

    print(f"\nArchiving {len(rows)} bookings...")
    now = datetime.now().isoformat()
    for r in rows:
        conn.execute(
            "UPDATE bookings SET archived_at = ?, updated_at = ? WHERE id = ?",
            (now, now, r["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (r["id"], "internal", "archived",
             "Backfill: auto-archived cancelled booking via archive_cancelled_bookings.py"),
        )
    conn.commit()
    conn.close()
    print(f"Done. {len(rows)} bookings archived.")


if __name__ == "__main__":
    main()
