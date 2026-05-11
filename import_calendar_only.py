"""Bulk-import selected calendar-only entries into the bookings DB.

Each row is (date, act_name, status, email, notes). Skipped if a booking
already exists for that date+act_name (dedupe). Idempotent — safe to re-run.

Usage:
    python3 import_calendar_only.py            # dry-run
    python3 import_calendar_only.py --confirm  # do it
"""

import argparse
from datetime import datetime

import db


# --- Decision list (per Soraya's adjudication) -----------------------------
# (date, act_name, status, email, notes)

ONE_OFF_GIGS = [
    ("2026-06-09", "Frank Owens book launch",          "confirmed", None,                       "Calendar import"),
    ("2026-06-11", "MTL/KOR (MCD)",                    "tentative", "luke.kavanagh@mcd.ie",    "Calendar import — MCD pencil, not yet confirmed"),
    ("2026-06-21", "Reverend Hutch",                   "confirmed", "reverendhutch@utcic.org", "Calendar import"),
    ("2026-07-04", "Meet the Faukers",                 "tentative", None,                       "Calendar import — pending"),
    ("2026-07-09", "Inni-K",                           "tentative", None,                       "Calendar import — pending"),
    ("2026-07-12", "I am Here",                        "confirmed", "jenimcmahon@gmail.com",    "Calendar import"),
    ("2026-07-17", "Seasons s2, e4",                   "tentative", None,                       "Calendar import — pending, awaiting clarification"),
    ("2026-07-18", "Eoin O Faoláin gig",               "confirmed", None,                       "Calendar import"),
    ("2026-08-09", "Mark Flynn Gig",                   "confirmed", None,                       "Calendar import"),
    ("2026-08-20", "Inni-K",                           "confirmed", None,                       "Calendar import"),
    ("2026-09-04", "Collaboration Concert",            "confirmed", None,                       "Calendar import"),
    ("2026-10-16", "BAC 7 Festival — Féile Splanc",    "confirmed", "bac7@cnag.ie",            "Calendar import"),
    ("2026-12-19", "Joe Higgins night",                "confirmed", None,                       "Calendar import"),
]

HOLDS = [
    ("2026-05-24", "Roisin Gaffney hold",   "hold", "gaffneyrp18@gmail.com",  "Calendar import — hold"),
    ("2026-06-25", "Pride hold",            "hold", None,                      "Calendar import — hold (day 1 of 2)"),
    ("2026-06-26", "Pride hold",            "hold", None,                      "Calendar import — hold (day 2 of 2)"),
    ("2026-09-17", "Sally Hold",            "hold", None,                      "Calendar import — hold"),
    ("2026-09-18", "Hold date Kelda",       "hold", None,                      "Calendar import — hold"),
    ("2026-09-19", "Sally Hold",            "hold", None,                      "Calendar import — hold"),
    ("2026-11-06", "Luke MCD hold",         "hold", "luke.kavanagh@mcd.ie",    "Calendar import — hold"),
    ("2026-11-13", "Luke MCD hold",         "hold", "luke.kavanagh@mcd.ie",    "Calendar import — hold"),
    ("2026-11-20", "Luke MCD hold",         "hold", "luke.kavanagh@mcd.ie",    "Calendar import — hold"),
]

ENTRIES = ONE_OFF_GIGS + HOLDS


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually insert (default: dry-run).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()

    print(f"Calendar-only bulk import — {len(ENTRIES)} entries to consider\n")

    to_insert = []
    skipped = []
    for event_date, act_name, status, email, notes in ENTRIES:
        # Dedupe: skip if a booking already exists on this date with same act_name
        # OR (if email given) same email
        params = [event_date]
        sql = ("SELECT id, act_name, status FROM bookings "
               "WHERE event_date = ? AND archived_at IS NULL AND (")
        clauses = ["LOWER(TRIM(act_name)) = LOWER(TRIM(?))"]
        params.append(act_name)
        if email:
            clauses.append("LOWER(contact_email) = ?")
            params.append(email.lower())
        sql += " OR ".join(clauses) + ")"
        existing = conn.execute(sql, params).fetchone()
        if existing:
            skipped.append((event_date, act_name, status,
                            f"already exists (#{existing['id']} '{existing['act_name']}' status={existing['status']})"))
            continue
        to_insert.append((event_date, act_name, status, email, notes))

    print(f"To insert: {len(to_insert)}")
    print(f"Skipping (already exist): {len(skipped)}\n")

    if to_insert:
        print("--- Will insert ---")
        for d, name, s, email, _ in to_insert:
            email_str = f" ({email})" if email else ""
            print(f"  {d}  [{s}]  {name}{email_str}")

    if skipped:
        print("\n--- Skipped (already in DB) ---")
        for d, name, s, reason in skipped:
            print(f"  {d}  {name}  →  {reason}")

    if not args.confirm:
        print(f"\nDRY RUN — re-run with --confirm to insert {len(to_insert)} bookings.")
        return

    if not to_insert:
        print("\nNothing to insert. ✓")
        return

    print(f"\nInserting {len(to_insert)} bookings...")
    for event_date, act_name, status, email, notes in to_insert:
        try:
            dow = datetime.strptime(event_date, "%Y-%m-%d").strftime("%A")
        except Exception:
            dow = None
        data = {
            "venue":               "Backroom",
            "event_date":          event_date,
            "day_of_week":         dow,
            "door_time":           None,
            "start_time":          None,
            "end_time":            None,
            "status":              status,
            "event_type":          "Gig",
            "act_name":            act_name,
            "contact_name":        None,
            "contact_email":       email,
            "contact_phone":       None,
            "expected_attendance": None,
            "description":         None,
            "media_links":         None,
            "ticketing":           None,
            "ticket_price":        None,
            "ticket_link":         None,
            "door_person":         None,
            "door_fee_required":   0,
            "venue_fee_required":  1,
            "blocks_public_calendar": 1,
            "announcement_date":   None,
            "support_act":         None,
            "promo_ok":            None,
            "notes":               notes,
            "source":              "calendar-import",
        }
        bid = db.save_booking(data)
        db.add_booking_audit(bid, "internal", "imported_from_calendar",
                             f"Bulk-imported from Google Calendar: {notes}")
    print(f"Done. {len(to_insert)} bookings inserted.")


if __name__ == "__main__":
    main()
