"""One-off cleanup of bookings flagged by reconcile_calendar.py.

After retag_residencies + reconcile_calendar leave a small set of
bookings without a Calendar match, this script handles them per
Soraya's adjudication:

  1. RENAME  #385 'People Before Profit' → 'People Before Profit (PBP)'
              so reconcile can match it to 'Pbp Night' on the calendar.

  2. ARCHIVE #198 'Balaclavas BackBar' 2026-06-10 — first Wednesday of
              June, anomalous (series rule skips first Wed).

  3. CREATE  Calendar event for #297 'Mr. Irish Bastard's' 2026-07-25 —
              night 2 of the two-night stand; calendar only has night 1.

  4. ARCHIVE 8 stale 'tbc' Sunday-evening placeholder bookings on dates
              where Dublin Jazz Coop already covers the calendar:
              #247, #255, #262, #263, #272, #278, #282, #284

NOT touched: #291 Knockshebane (left for manual review tomorrow).

Usage:
    python3 cleanup_unlinked_bookings.py            # dry-run
    python3 cleanup_unlinked_bookings.py --confirm  # apply
"""

import argparse
from datetime import datetime

import db


RENAME_OPS = [
    (385, "People Before Profit", "People Before Profit (PBP)"),
]
ARCHIVE_IDS_BALACLAVAS = [198]
ARCHIVE_IDS_TBC        = [247, 255, 262, 263, 272, 278, 282, 284]
CREATE_CAL_EVENT_IDS   = [297]   # Mr. Irish Bastard 2026-07-25


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually apply changes (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()
    now = datetime.now().isoformat()

    # ── 1. RENAMES ────────────────────────────────────────────────────────
    rename_pending = []
    for bid, expected_from, target in RENAME_OPS:
        row = conn.execute(
            "SELECT id, act_name FROM bookings WHERE id = ?", (bid,)
        ).fetchone()
        if not row:
            print(f"  ⚠ Booking #{bid} not found — skipping rename")
            continue
        if row["act_name"] == target:
            print(f"  ✓ Booking #{bid} already named {target!r} — no-op")
            continue
        print(f"  ✱ Booking #{bid} {row['act_name']!r} → {target!r}")
        rename_pending.append((bid, row["act_name"], target))

    # ── 2. ARCHIVE BALACLAVAS ANOMALY ─────────────────────────────────────
    archive_balaclavas = []
    for bid in ARCHIVE_IDS_BALACLAVAS:
        row = conn.execute(
            "SELECT id, act_name, event_date, archived_at FROM bookings WHERE id = ?",
            (bid,),
        ).fetchone()
        if not row:
            print(f"  ⚠ Booking #{bid} not found — skipping archive")
            continue
        if row["archived_at"]:
            print(f"  ✓ Booking #{bid} already archived — no-op")
            continue
        print(f"  ✱ Archive Balaclavas anomaly: #{bid} {row['event_date']}  {row['act_name']}")
        archive_balaclavas.append(row)

    # ── 3. CREATE CALENDAR EVENT (Mr Irish Bastard night 2) ───────────────
    cal_create_pending = []
    for bid in CREATE_CAL_EVENT_IDS:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
        if not row:
            print(f"  ⚠ Booking #{bid} not found — skipping calendar create")
            continue
        if row["google_calendar_event_id"]:
            print(f"  ✓ Booking #{bid} already has calendar event — no-op")
            continue
        print(f"  ✱ Create Calendar event for #{bid} {row['event_date']}  {row['act_name']}")
        cal_create_pending.append(row)

    # ── 4. ARCHIVE TBC PLACEHOLDERS ───────────────────────────────────────
    archive_tbc = []
    for bid in ARCHIVE_IDS_TBC:
        row = conn.execute(
            "SELECT id, act_name, event_date, archived_at FROM bookings WHERE id = ?",
            (bid,),
        ).fetchone()
        if not row:
            print(f"  ⚠ Booking #{bid} not found — skipping archive")
            continue
        if row["archived_at"]:
            print(f"  ✓ Booking #{bid} already archived — no-op")
            continue
        print(f"  ✱ Archive tbc placeholder: #{bid} {row['event_date']}  {row['act_name']}")
        archive_tbc.append(row)

    total_actions = (len(rename_pending) + len(archive_balaclavas)
                     + len(cal_create_pending) + len(archive_tbc))
    print(f"\nTotal actions pending: {total_actions}")

    if not args.confirm:
        print("\nDRY RUN — re-run with --confirm to apply.")
        return

    if total_actions == 0:
        print("\nNothing to do. ✓")
        return

    # ── APPLY ─────────────────────────────────────────────────────────────
    print(f"\nApplying {total_actions} action(s)...")

    # Renames
    for bid, old, new in rename_pending:
        conn.execute(
            "UPDATE bookings SET act_name = ?, updated_at = ? WHERE id = ?",
            (new, now, bid),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (bid, "internal", "renamed",
             f"act_name {old!r} → {new!r} via cleanup_unlinked_bookings.py"),
        )

    # Archive Balaclavas anomaly
    for row in archive_balaclavas:
        conn.execute(
            "UPDATE bookings SET archived_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (row["id"], "internal", "archived",
             "Archived: Balaclavas BackBar 2026-06-10 — first Wednesday "
             "of month, anomalous per series rule. Via cleanup_unlinked_bookings.py."),
        )

    # Archive tbc placeholders
    for row in archive_tbc:
        conn.execute(
            "UPDATE bookings SET archived_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (row["id"], "internal", "archived",
             "Archived: stale 'tbc' Sunday-evening placeholder — Dublin Jazz Coop "
             "covers these dates on the calendar already. Via cleanup_unlinked_bookings.py."),
        )

    conn.commit()

    # Create calendar events (do these last since they hit external API)
    if cal_create_pending:
        try:
            import calendar_client
        except Exception as e:
            print(f"  ⚠ Could not import calendar_client: {e}")
            calendar_client = None
        if calendar_client:
            for row in cal_create_pending:
                # Re-fetch to get the latest row state
                booking = db.get_booking(row["id"])
                try:
                    event_id = calendar_client.create_calendar_event(booking)
                    if event_id:
                        db.update_booking_field(
                            booking["id"], "google_calendar_event_id",
                            event_id, actor="system",
                        )
                        db.add_booking_audit(
                            booking["id"], "system", "calendar_event_created",
                            f"Created via cleanup_unlinked_bookings.py: event_id={event_id}",
                        )
                        print(f"  ✓ Created event for #{booking['id']} → {event_id[:12]}…")
                    else:
                        print(f"  ✗ Failed to create event for #{booking['id']}")
                except Exception as e:
                    print(f"  ✗ Error creating event for #{booking['id']}: {e}")

    conn.close()
    print(f"\nDone.")
    print(f"  Renamed         : {len(rename_pending)}")
    print(f"  Archived (Balac): {len(archive_balaclavas)}")
    print(f"  Archived (tbc)  : {len(archive_tbc)}")
    print(f"  Calendar events : {len(cal_create_pending)}")


if __name__ == "__main__":
    main()
