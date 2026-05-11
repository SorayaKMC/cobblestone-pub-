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


# Match patterns for the residencies (case-insensitive substring on act_name).
# Optional rename_to renames matched bookings to a canonical act_name.
RESIDENCY_PATTERNS = [
    {"label": "Balaclavas",    "pattern": "%balaclavas%"},
    {"label": "Dance Classes", "pattern": "%dance class%",
     "rename_to": "Dance Classes: Caoimhe ní Maolagáin and Louise Barker"},
    {"label": "Caoimhe (legacy)", "pattern": "%caoimhe%"},
    {"label": "Larry's Night", "pattern": "%larry%night%"},
    {"label": "Piper's Club",  "pattern": "%piper%"},
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
    # Each pending item: (row, rename_to-or-None)
    pending = []

    print("Scanning for in-house residency series:\n")
    seen_ids = set()
    for spec in RESIDENCY_PATTERNS:
        label     = spec["label"]
        pattern   = spec["pattern"]
        rename_to = spec.get("rename_to")
        rows = conn.execute(
            """SELECT id, act_name, event_date, event_type FROM bookings
               WHERE LOWER(act_name) LIKE ?
                 AND archived_at IS NULL
               ORDER BY event_date""",
            (pattern.lower(),),
        ).fetchall()
        # Dedupe across patterns — if a row matched an earlier pattern, skip
        rows = [r for r in rows if r["id"] not in seen_ids]
        for r in rows:
            seen_ids.add(r["id"])
        # An item needs an update if event_type is wrong OR a rename is requested
        # and the current name doesn't match the target.
        def _needs_action(row):
            if row["event_type"] != TARGET_EVENT_TYPE:
                return True
            if rename_to and row["act_name"] != rename_to:
                return True
            return False
        needs_update = [r for r in rows if _needs_action(r)]
        already_ok   = [r for r in rows if not _needs_action(r)]
        rename_note  = f" (rename → {rename_to[:30]}…)" if rename_to else ""
        print(f"  {label:<18}: {len(rows):>3} matched  "
              f"({len(needs_update)} need update, {len(already_ok)} already tagged){rename_note}")
        for r in needs_update:
            pending.append((r, rename_to))
        total_matched += len(rows)
        total_already += len(already_ok)

    print(f"\nTotal matched      : {total_matched}")
    print(f"Already tagged ✓   : {total_already}")
    print(f"Need update        : {len(pending)}")

    if not pending:
        print("\nNothing to update. ✓")
        return

    if not args.confirm:
        print(f"\n--- Would update these {len(pending)} rows ---")
        for r, rename_to in pending[:30]:
            change = f"event_type {r['event_type']!r} → '{TARGET_EVENT_TYPE}'"
            if rename_to and r["act_name"] != rename_to:
                change += f" + act_name {r['act_name']!r} → {rename_to!r}"
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name'][:35]:<35}  | {change}")
        if len(pending) > 30:
            print(f"  ... and {len(pending) - 30} more")
        print(f"\nDRY RUN — re-run with --confirm to update.")
        return

    print(f"\nUpdating {len(pending)} bookings...")
    now = datetime.now().isoformat()
    for r, rename_to in pending:
        if rename_to and r["act_name"] != rename_to:
            conn.execute(
                "UPDATE bookings SET event_type = ?, act_name = ?, updated_at = ? WHERE id = ?",
                (TARGET_EVENT_TYPE, rename_to, now, r["id"]),
            )
            detail = (f"Retagged event_type {r['event_type']!r} → '{TARGET_EVENT_TYPE}' "
                      f"+ renamed act_name {r['act_name']!r} → {rename_to!r} "
                      f"via retag_residencies.py")
        else:
            conn.execute(
                "UPDATE bookings SET event_type = ?, updated_at = ? WHERE id = ?",
                (TARGET_EVENT_TYPE, now, r["id"]),
            )
            detail = (f"Retagged event_type {r['event_type']!r} → '{TARGET_EVENT_TYPE}' "
                      f"via retag_residencies.py")
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (r["id"], "internal", "retagged", detail),
        )
    conn.commit()
    conn.close()
    print(f"Done. {len(pending)} bookings updated.")


if __name__ == "__main__":
    main()
