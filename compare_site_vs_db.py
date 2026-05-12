"""Compare the Squarespace events listing vs DB confirmed bookings.

Fetched the site list manually on 12-May-2026 from
https://www.cobblestonepub.ie/cobblestone-backroom

Outputs three lists:
  ⚠  In DB CONFIRMED but NOT on site  →  needs to be added to Squarespace
  ⚠  On site but NOT in DB confirmed  →  missing from booking system, OR
                                          DB act name doesn't match
  ✓  Both                              →  good

Run on Render Shell:
    python3 compare_site_vs_db.py
"""

import re
import unicodedata
from datetime import datetime
import db


# Manually-scraped from cobblestonepub.ie/cobblestone-backroom on 12-May-2026.
# (date_iso, site_act_name)
SITE_EVENTS = [
    ("2026-04-26", "The Dublin Jazz Co-op Presents Paul Dunlea Trio"),
    ("2026-04-28", "Rusalka, Broadford, David Virgin"),
    ("2026-04-30", "The Dublin Jazz Co-op: International Jazz Day Celebration"),
    ("2026-05-01", "Ciaran Moran: Back where I Began"),
    ("2026-05-02", "Gráinne Brady & Michael Biggins"),
    ("2026-05-07", "Alice Jago: Look to the Sky Album Preview"),
    ("2026-05-09", "Ben Turner: Songs and Stories"),
    ("2026-05-10", "İkiye On Kala live in Dublin"),
    ("2026-05-12", "The Onlies"),
    ("2026-05-17", "Eugene Chadbourne"),
    ("2026-05-22", "Alaskan Songwriters: Fortenbery, Vidic, Heist and Heist"),
    ("2026-05-24", "Balfolk Dublin presents Silk Pill"),
    ("2026-05-24", "Knockshebane and Special Guests"),
    ("2026-05-28", "Dubh Lee - FUFO EP Launch"),
    ("2026-05-31", "The Dublin Jazz Co-op: Laoise Leahy & Johnny Taylor"),
    ("2026-06-03", "Fergal Scahill & Ryan Molloy"),
    ("2026-06-05", "Was Man & Band"),
    ("2026-06-06", "Electric Blue - The Cranberries Tribute Band"),
    ("2026-06-14", "Train Room Album Launch"),
    ("2026-06-16", "Sister Brigid"),
    ("2026-06-18", "Hánt - Live At The Cobblestone"),
    ("2026-06-20", "Launch of Song Of The Fallen by Karl Parkinson"),
    ("2026-06-28", "The Dublin Jazz Co-op (TBC)"),
    ("2026-07-02", "Tulua - Album launch"),
    ("2026-07-23", "Sweet Jayne single launch"),
    ("2026-07-24", "Mr. Irish Bastard's Two Night Stand"),
    ("2026-07-25", "Mr. Irish Bastard's Two Night Stand"),
    ("2026-07-26", "The Dublin Jazz Co-op (TBC)"),
    ("2026-08-28", "Kirsteen Harvey"),
    ("2026-09-04", "The Collaboration Showcase 2026"),
    ("2026-09-12", "Marissa Anderson"),
]


STOPWORDS = {
    "the", "and", "with", "presents", "presented", "live", "at", "in", "on",
    "of", "by", "for", "from", "to", "a", "an", "is", "no",
    "cobblestone", "backroom", "dublin",
}


def _tokens(s):
    if not s:
        return set()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return {t for t in s.split() if t and t not in STOPWORDS and not t.isdigit() and len(t) > 1}


def _similarity(a, b):
    at, bt = _tokens(a), _tokens(b)
    if not at or not bt:
        return 0.0
    return len(at & bt) / min(len(at), len(bt))


def main():
    db.init_db()
    conn = db.get_db()

    # Pull all confirmed bookings whose event_date falls in the site's covered range
    site_dates = sorted({d for d, _ in SITE_EVENTS})
    start, end = site_dates[0], site_dates[-1]
    rows = conn.execute(
        """SELECT id, event_date, act_name, event_type, squarespace_listing_status, contact_email
           FROM bookings
           WHERE status='confirmed'
             AND archived_at IS NULL
             AND event_date >= ?
             AND event_date <= ?
           ORDER BY event_date""",
        (start, end),
    ).fetchall()
    conn.close()

    # Match each site event to a DB booking
    db_by_date = {}
    for r in rows:
        db_by_date.setdefault(r["event_date"], []).append(r)

    matched_db_ids = set()
    in_both = []
    site_only = []
    for site_date, site_act in SITE_EVENTS:
        candidates = db_by_date.get(site_date, [])
        if not candidates:
            site_only.append((site_date, site_act))
            continue
        # Score each — pick highest if >= 0.4
        scored = [(c, _similarity(site_act, c["act_name"])) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored and scored[0][1] >= 0.4:
            best = scored[0][0]
            matched_db_ids.add(best["id"])
            in_both.append((site_date, site_act, best))
        else:
            site_only.append((site_date, site_act))

    db_only = [r for r in rows if r["id"] not in matched_db_ids
               and (r["event_type"] or "") != "Residency Gigs"]

    # ── Report ───────────────────────────────────────────────────────────
    print(f"\nDate range checked: {start} → {end}")
    print(f"  Site listings:        {len(SITE_EVENTS)}")
    print(f"  DB confirmed:         {len(rows)} (non-residency: "
          f"{sum(1 for r in rows if (r['event_type'] or '') != 'Residency Gigs')})")
    print()

    print(f"⚠️  In DB but NOT on site ({len(db_only)}):  →  needs to be added to Squarespace")
    if db_only:
        for r in db_only:
            print(f"  #{r['id']:>4}  {r['event_date']}  {r['act_name']:<50}  "
                  f"(listing status: {r['squarespace_listing_status']})")
    else:
        print("  (nothing — every DB confirmed gig is on the site ✓)")
    print()

    print(f"⚠️  On site but NOT in DB confirmed ({len(site_only)}):  →  check booking exists in system")
    if site_only:
        for site_date, site_act in site_only:
            # Check if there's ANY booking (any status) on this date for context
            extra = ""
            same_date_any = db_by_date.get(site_date, [])
            if same_date_any:
                extra = f"  (DB has on this date: " + \
                        ", ".join(f"{r['act_name']} [{r['event_type'] or 'Gig'}]" for r in same_date_any) + ")"
            print(f"  {site_date}  {site_act}{extra}")
    else:
        print("  (nothing — every site listing matches a DB confirmed gig ✓)")
    print()

    print(f"✓  Matched on both ({len(in_both)})")
    for site_date, site_act, db_row in in_both:
        ls = db_row["squarespace_listing_status"]
        mark = "✓" if ls == "live" else ("△" if ls == "partial" else "○")
        print(f"  {mark} #{db_row['id']:>4}  {site_date}  {site_act[:35]:<35}  "
              f"→ DB: {db_row['act_name'][:35]:<35}  ({ls})")


if __name__ == "__main__":
    main()
