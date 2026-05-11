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
# Optional 'rename_to' renames matched bookings to a canonical act_name.
# Optional 'field_updates' = dict of column → value to set on each match.
# Optional 'notes_to_set' = canonical note text; appended if not already present.
RESIDENCY_PATTERNS = [
    {"label": "Balaclavas",    "pattern": "%balaclavas%"},
    {"label": "Dance Classes", "pattern": "%dance class%",
     "rename_to": "Dance Classes: Caoimhe ní Maolagáin and Louise Barker"},
    {"label": "Caoimhe (legacy)", "pattern": "%caoimhe%"},
    {"label": "Larry's Night", "pattern": "%larry%"},  # catches 'Larry Night' + 'The Night Larry Got Stretched'
    {"label": "Piper's Club",  "pattern": "%piper%"},
    {"label": "Dublin Jazz Coop", "pattern": "%jazz coop%",
     "field_updates": {
         "blocks_public_calendar": 0,   # afternoon-only — evening gigs can still book
         "door_person": "none",         # Jazz Coop handle their own door
         # venue_fee_required stays at whatever it is — Shane is still needed
     },
     "notes_to_set": ("Sunday afternoon residency — room is occupied until 6pm. "
                      "Any evening soundcheck/load-in on the same date must be after 6pm. "
                      "Shane handles sound. Jazz Coop manage their own door (no door person needed).")
    },
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
    # Each pending item: (row, spec) — spec carries rename_to / field_updates / notes_to_set
    pending = []

    print("Scanning for in-house residency series:\n")
    seen_ids = set()
    for spec in RESIDENCY_PATTERNS:
        label         = spec["label"]
        pattern       = spec["pattern"]
        rename_to     = spec.get("rename_to")
        field_updates = spec.get("field_updates") or {}
        notes_to_set  = spec.get("notes_to_set")

        # Select all columns we may need to inspect
        rows = conn.execute(
            f"""SELECT * FROM bookings
                WHERE LOWER(act_name) LIKE ?
                  AND archived_at IS NULL
                ORDER BY event_date""",
            (pattern.lower(),),
        ).fetchall()
        # Dedupe across patterns — if a row matched an earlier pattern, skip
        rows = [r for r in rows if r["id"] not in seen_ids]
        for r in rows:
            seen_ids.add(r["id"])

        def _needs_action(row):
            if row["event_type"] != TARGET_EVENT_TYPE:
                return True
            if rename_to and row["act_name"] != rename_to:
                return True
            for col, target in field_updates.items():
                if row[col] != target:
                    return True
            if notes_to_set:
                cur_notes = row["notes"] or ""
                if notes_to_set not in cur_notes:
                    return True
            return False

        needs_update = [r for r in rows if _needs_action(r)]
        already_ok   = [r for r in rows if not _needs_action(r)]
        extras = []
        if rename_to:     extras.append(f"rename")
        if field_updates: extras.append(f"+fields:{','.join(field_updates.keys())}")
        if notes_to_set:  extras.append(f"+notes")
        extras_str = f" ({' '.join(extras)})" if extras else ""
        print(f"  {label:<20}: {len(rows):>3} matched  "
              f"({len(needs_update)} need update, {len(already_ok)} already tagged){extras_str}")
        for r in needs_update:
            pending.append((r, spec))
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
        for r, spec in pending[:30]:
            rename_to     = spec.get("rename_to")
            field_updates = spec.get("field_updates") or {}
            notes_to_set  = spec.get("notes_to_set")
            changes = [f"event_type→'{TARGET_EVENT_TYPE}'"]
            if rename_to and r["act_name"] != rename_to:
                changes.append(f"act_name→{rename_to[:25]!r}…")
            for col, val in field_updates.items():
                if r[col] != val:
                    changes.append(f"{col}={val}")
            if notes_to_set and notes_to_set not in (r["notes"] or ""):
                changes.append("notes+=…")
            print(f"  #{r['id']:>4}  {r['event_date']}  {(r['act_name'] or '')[:30]:<30}  | "
                  + ", ".join(changes))
        if len(pending) > 30:
            print(f"  ... and {len(pending) - 30} more")
        print(f"\nDRY RUN — re-run with --confirm to update.")
        return

    print(f"\nUpdating {len(pending)} bookings...")
    now = datetime.now().isoformat()
    for r, spec in pending:
        rename_to     = spec.get("rename_to")
        field_updates = spec.get("field_updates") or {}
        notes_to_set  = spec.get("notes_to_set")

        # Assemble UPDATE columns + values
        sets = ["event_type = ?", "updated_at = ?"]
        vals = [TARGET_EVENT_TYPE, now]
        detail_parts = [f"event_type {r['event_type']!r} → '{TARGET_EVENT_TYPE}'"]

        if rename_to and r["act_name"] != rename_to:
            sets.append("act_name = ?")
            vals.append(rename_to)
            detail_parts.append(f"act_name {r['act_name']!r} → {rename_to!r}")

        for col, target in field_updates.items():
            if r[col] != target:
                sets.append(f"{col} = ?")
                vals.append(target)
                detail_parts.append(f"{col}={target}")

        if notes_to_set and notes_to_set not in (r["notes"] or ""):
            new_notes = notes_to_set if not r["notes"] else f"{r['notes']}\n\n{notes_to_set}"
            sets.append("notes = ?")
            vals.append(new_notes)
            detail_parts.append("appended residency note")

        vals.append(r["id"])
        conn.execute(f"UPDATE bookings SET {', '.join(sets)} WHERE id = ?", vals)
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (r["id"], "internal", "retagged",
             "; ".join(detail_parts) + " via retag_residencies.py"),
        )
    conn.commit()
    conn.close()
    print(f"Done. {len(pending)} bookings updated.")


if __name__ == "__main__":
    main()
