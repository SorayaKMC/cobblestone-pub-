"""Set squarespace_listing_status on bookings that are already on the site.

Based on the 12-May-2026 site scrape of cobblestonepub.ie/cobblestone-backroom.
Bookings get classified by whether the site listing has a ticket link:

  Has ticket link on site  →  'live'   (fully published)
  No ticket link on site   →  'partial' (listed but info pending)

You can manually flip donation-only / free gigs from 'partial' → 'live'
on their booking detail page if the partial flag is wrong for them.

Usage:
    python3 update_listing_status_from_site.py            # dry-run
    python3 update_listing_status_from_site.py --confirm  # apply
"""

import argparse
from datetime import datetime

import db


# Each entry: (db_booking_id, target_status, note_about_site)
# Compiled from the 12-May-2026 fetch of /cobblestone-backroom.
TARGETS = [
    (224, "live",    "The Onlies — Eventbrite link present"),
    (227, "live",    "Eugene Chadbourne — Billetto link present"),
    (229, "partial", "Alaskan Songwriters — no ticket link"),
    (291, "live",    "Knockshebane — Eventbrite link present"),
    (232, "partial", "Dubh Lee FUFO EP — no ticket link"),
    (234, "live",    "Jazz Co-op: Laoise Leahy — Eventbrite link present"),
    (235, "partial", "Fergal Scahill & Ryan Molloy — no ticket link"),
    (237, "live",    "Was Man & Band — Eventbrite link present"),
    (238, "live",    "Electric Blue — Eventbrite link present"),
    (241, "partial", "Train Room — no ticket link"),
    (243, "live",    "Hánt — Eventbrite link present"),
    (245, "partial", "Karl Parkinson Song Of The Fallen — no ticket link"),
    (248, "live",    "Tulua — Eventbrite link present"),
    (253, "partial", "Sweet Jayne — Instagram link only, no ticket link"),
    (254, "live",    "Mr Irish Bastard Night 1 — SeeTickets link present"),
    (297, "live",    "Mr Irish Bastard Night 2 — SeeTickets link present"),
    (261, "partial", "Kirsteen Harvey — no ticket link"),
    (267, "live",    "Marisa Anderson — Billetto link present"),
]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually apply (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()

    pending = []
    for bid, target, note in TARGETS:
        row = conn.execute(
            "SELECT id, act_name, squarespace_listing_status FROM bookings WHERE id = ?",
            (bid,),
        ).fetchone()
        if not row:
            print(f"  ⚠ Booking #{bid} not found — skipping")
            continue
        current = row["squarespace_listing_status"]
        if current == target:
            print(f"  ✓ #{bid:>4}  {row['act_name'][:40]:<40}  already '{target}'")
            continue
        print(f"  ✱ #{bid:>4}  {row['act_name'][:40]:<40}  '{current}' → '{target}'  ({note})")
        pending.append((bid, target, note, current))

    print(f"\n{len(pending)} change(s) to apply.")

    if not args.confirm:
        print("\nDRY RUN — re-run with --confirm to apply.")
        return
    if not pending:
        print("Nothing to update. ✓")
        return

    now = datetime.now().isoformat()
    for bid, target, note, current in pending:
        # Update listing status
        sets = ["squarespace_listing_status = ?", "updated_at = ?"]
        vals = [target, now]
        # Also stamp squarespace_published_at if going live (keeps legacy
        # timestamp in sync — matches the route's behavior)
        if target == "live":
            sets.append("squarespace_published_at = ?")
            vals.append(now)
        elif target != "live":
            sets.append("squarespace_published_at = NULL")
        vals.append(bid)
        conn.execute(f"UPDATE bookings SET {', '.join(sets)} WHERE id = ?", vals)
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (bid, "internal", "squarespace_status_updated",
             f"Set squarespace_listing_status: {current} → {target} "
             f"(based on 12-May-2026 site scrape — {note})."),
        )
    conn.commit()
    conn.close()
    print(f"\nDone. {len(pending)} bookings updated.")


if __name__ == "__main__":
    main()
