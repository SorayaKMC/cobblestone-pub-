"""Link mirrored Drive folders to DB bookings.

After running the legacy Drive mirror (created folders in bookings@'s
Drive at Cobblestone Promos/<month>/<date — act>/), this script
matches each Drive folder to its DB booking and sets
booking.promo_folder_url so the booking detail page can surface a
'View promo folder' link.

Matching is fuzzy: same event_date, similar act_name (token overlap).
If a folder can't be matched to a booking, it's reported and skipped.

Usage:
    python3 mirror_legacy_drive_folders.py            # dry-run
    python3 mirror_legacy_drive_folders.py --confirm  # apply
"""

import argparse
import re
import unicodedata
from datetime import datetime

import db


# (event_date, original_act_name, drive_folder_id) — from the May 2026 mirror
# These are the 29 folders we created in bookings@'s Cobblestone Promos.
LEGACY_FOLDERS = [
    ("2025-03-12", "ÁINE TYRRELL - BITSEACH",                 "1vbiyZuNlzc41owZZ96MhV7js2tmIdt4Z"),
    ("2025-09-20", "The Hendrix Cream Experience",            "1OzoKl_U5h2NFGE8yqPz3e0sBNv2e-NDZ"),
    ("2025-09-23", "Grosse Isle - Music & Song from Québec & Ireland", "1vDT0p9P15MMErwsq_fdk-1NFlwnDm1qr"),
    ("2025-09-25", "Fortune Igiebor",                          "1hM5saAeYt_axAlbk7fdtjllOqYtoB71y"),
    ("2025-09-27", "Kevin Hill live at The Cobblestone",       "1arD9TF9aYX-SsnZvJuUpG0uiA9fzuP8G"),
    ("2025-10-01", "Fiona Bevan + Adam Beattie",               "1ZVrjMOTwxTWkj-F3VTtjb0AP4rTRNqAh"),
    ("2025-10-04", "The Under Cover Police",                   "1sZ_RZ_OqjNa_1endTPTo9nJSYGuzfxQ_"),
    ("2025-10-18", "Without Willow Live at The Cobblestone",   "1E8cu3xwuJCCnY06TAkGJVbYRff_yOkdX"),
    ("2025-10-19", "EMER DUNNE TRIO",                          "1gBcVLxo6GrYSNFaHjY0yKfTsFHwGfaQt"),
    ("2025-10-21", "The Empty Pockets",                        "1Ercr_n8HisUkn5GyVoafm0zpmLCmG5Mu"),
    ("2025-10-23", "Bug Hunter & The Narcissist Cookbook",     "1Ba_eDTv-5VcS_Dh7E1eKTkl04i9lVTcY"),
    ("2025-10-25", "Shane Hennessy",                           "1nvl3sOYPOmdvU3J95ufrEcDAhbPNcW3Y"),
    ("2025-10-28", "The Irish from Brittany",                  "1aqtf5H_8gwguF4ci4T7GFdLQrIZrpQ6o"),
    ("2025-11-08", "The Arbour Hillbillies",                   "1oIFT6T_66Aus_tkwbXQrNqJ5YJOj9fC3"),
    ("2025-11-15", "Andrea Palandri",                          "1oI6o3PHtFV-5Tseb6H5upH4YNQfVBW5X"),
    ("2025-11-16", "Antoni O'Breskey",                         "1sRw3AyxpvXXutClQc6VsmiDFE2xMfrXZ"),
    ("2025-11-23", "Dublin Across the Atlantic Launch",        "158-1mcOsfNihKSQFEUSRQz8IffOKZIoF"),
    ("2025-12-11", "Ceoil for Deema",                          "1nlMcB897li-GGzooyurwOo5SiVk7UsPr"),
    ("2025-12-13", "Eoin Ryan Anthony",                        "1FTuszxehhyRhwvOEwHyshhuJERGqSwk2"),
    ("2026-01-10", "SELK with support from Bradley Lauretti",  "1Q9TFNqLUZzyLyAyVfCb7SiBewOhRejeo"),
    ("2026-01-31", "Taibhsí Oriel",                            "16YS57i7vwVYDWbUm7D4xxFiFrbLKMqjd"),
    ("2026-02-05", "Fiárock",                                  "1Z9aogrrdOfVR2WkpvDrdkEkU_6HTi6Ac"),
    ("2026-02-21", "Logan McKillop & Caleb Tomlinson",         "1FfaxD7ZUEwMQ2xuQcczcImXXIajcL1b7"),
    ("2026-02-24", "indie nights",                             "1u4aut9nt6b5f19Az4RLGZA7bS-FTgGUT"),
    ("2026-03-08", "the headshrinkers",                        "1iILO155vOnG6q8STlZNqkq5ESzZ4aMZ-"),
    ("2026-04-03", "Barnburner's 'Nothing to Hold'",           "1KXJOJGTulyLxqA4YMqa-31U1umot53J0"),
    ("2026-04-04", "Foggy Notions Presents Ben de la Cour",    "1djbegj3m6b2OW5UbZUFSr5C8SbU29rv9"),
    ("2026-04-09", "CAS Album Launch",                         "1CxXJMNlce_f7_YpERO6Ar61RTh2LKam-"),
    ("2026-04-14", "BRIDEEN",                                  "1FIQiFam5Wws-CYwfR9zSkaGp0gk8Lare"),
]


STOPWORDS = {
    "the", "and", "with", "presents", "presented", "live", "at", "in", "on",
    "of", "by", "for", "from", "to", "a", "an", "is", "no", "have", "their",
    "own", "door", "person", "needed", "tbc", "back", "bar", "backbar",
    "cobblestone", "backroom", "upstairs", "night", "nights",
}


def _strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _tokens(s):
    if not s:
        return set()
    s = _strip_accents(s).lower()
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return {t for t in s.split() if t and t not in STOPWORDS and not t.isdigit()}


def _similarity(a, b):
    at, bt = _tokens(a), _tokens(b)
    if not at or not bt:
        return 0.0
    return len(at & bt) / min(len(at), len(bt))


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

    SIM_THRESHOLD = 0.5
    BASE = "https://drive.google.com/drive/folders/"

    linked = []
    ambiguous = []
    missing = []

    print(f"\n{'DRY RUN — ' if not args.confirm else ''}"
          f"Linking {len(LEGACY_FOLDERS)} Drive folders to bookings...\n")

    for ev_date, form_act, folder_id in LEGACY_FOLDERS:
        url = BASE + folder_id
        # Find bookings on the same date
        rows = conn.execute(
            "SELECT * FROM bookings WHERE event_date = ? AND archived_at IS NULL",
            (ev_date,),
        ).fetchall()

        if not rows:
            missing.append((ev_date, form_act, "no booking on that date"))
            continue

        # Score each candidate
        scored = [(r, _similarity(form_act, r["act_name"])) for r in rows]
        scored = [(r, s) for r, s in scored if s >= SIM_THRESHOLD]
        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            missing.append((ev_date, form_act, f"{len(rows)} booking(s) on date but none with name match"))
            continue

        # Clear winner if >= 1 match AND (only one OR top score > 2nd by 0.2)
        if len(scored) == 1 or (scored[0][1] - scored[1][1] >= 0.2):
            booking = scored[0][0]
            current = booking["promo_folder_url"]
            if current == url:
                print(f"  ✓ #{booking['id']:>4}  {ev_date}  {booking['act_name'][:40]:<40}  already linked")
            else:
                linked.append((booking, url))
                arrow = "→" if not current else "↺"
                print(f"  ✱ #{booking['id']:>4}  {ev_date}  {booking['act_name'][:40]:<40}  {arrow} {folder_id[:12]}…")
        else:
            ambiguous.append((ev_date, form_act, scored))

    if ambiguous:
        print(f"\n⚠ Ambiguous matches ({len(ambiguous)}) — manual review:")
        for ev_date, form_act, scored in ambiguous:
            print(f"  {ev_date}  form: {form_act!r}")
            for r, s in scored[:3]:
                print(f"    candidate #{r['id']}  (sim {s:.2f})  {r['act_name']}")

    if missing:
        print(f"\n⚠ No DB match ({len(missing)}):")
        for ev_date, form_act, reason in missing:
            print(f"  {ev_date}  {form_act!r}  — {reason}")

    print(f"\nSummary: {len(linked)} to link, "
          f"{len(ambiguous)} ambiguous, {len(missing)} missing")

    if not args.confirm:
        print(f"\nDRY RUN — re-run with --confirm to apply.")
        return

    if not linked:
        print("\nNothing to update. ✓")
        return

    now = datetime.now().isoformat()
    for booking, url in linked:
        conn.execute(
            "UPDATE bookings SET promo_folder_url = ?, updated_at = ? WHERE id = ?",
            (url, now, booking["id"]),
        )
        conn.execute(
            "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
            (booking["id"], "internal", "promo_folder_linked",
             f"Linked to Drive folder {url} via mirror_legacy_drive_folders.py"),
        )
    conn.commit()
    conn.close()
    print(f"\nDone. {len(linked)} bookings now have a promo_folder_url. ✓")


if __name__ == "__main__":
    main()
