"""Dedupe bookings table — keeps the most recently updated row per (act_name, event_date).

Safe to run repeatedly. Always shows what would be deleted first;
use --confirm to actually delete.

Usage:
    python3 dedupe_bookings.py            # dry run, lists duplicates
    python3 dedupe_bookings.py --confirm  # actually deletes
"""

import argparse
import sys
from collections import defaultdict

import db


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually delete duplicates (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()

    rows = conn.execute(
        """SELECT id, act_name, event_date, status, source, updated_at
           FROM bookings
           ORDER BY act_name, event_date, updated_at DESC, id DESC"""
    ).fetchall()

    # Group by (act_name lowercased + event_date)
    groups = defaultdict(list)
    for r in rows:
        key = ((r["act_name"] or "").strip().lower(), r["event_date"])
        groups[key].append(r)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}

    if not duplicates:
        print(f"No duplicates found across {len(rows)} bookings. ✓")
        return

    print(f"Found {len(duplicates)} (act_name, event_date) pairs with duplicates")
    print(f"Total bookings: {len(rows)}; will keep one per group, delete the rest")
    print()

    to_delete = []
    for key, group in sorted(duplicates.items(), key=lambda x: x[0][1] or ""):
        # Keep the first (most recently updated, highest id by ORDER BY)
        keeper = group[0]
        deletes = group[1:]
        to_delete.extend(d["id"] for d in deletes)

        print(f"  {key[1]}  {key[0][:50]}")
        print(f"    KEEP:    id={keeper['id']:<5} status={keeper['status']:<10} source={keeper['source']}")
        for d in deletes:
            print(f"    DELETE:  id={d['id']:<5} status={d['status']:<10} source={d['source']}")
        print()

    print(f"Total to delete: {len(to_delete)}")

    if not args.confirm:
        print("\nDRY RUN — nothing deleted. Re-run with --confirm to delete.")
        return

    print("\nDeleting...")
    for bid in to_delete:
        # Delete dependent rows first
        conn.execute("DELETE FROM booking_audit WHERE booking_id = ?", (bid,))
        conn.execute("DELETE FROM booking_attachments WHERE booking_id = ?", (bid,))
        conn.execute("DELETE FROM bookings WHERE id = ?", (bid,))
    conn.commit()
    print(f"Deleted {len(to_delete)} duplicate booking rows.")


if __name__ == "__main__":
    main()
