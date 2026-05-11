"""Reconcile existing Google Calendar events with DB bookings.

Background: the sqlite3.Row.get() bug silently failed every app-driven
calendar-event-creation call, so confirmed bookings never had their
google_calendar_event_id populated. Meanwhile the calendar has events
from an earlier bulk import. This script links them back together by
matching on event_date + act_name.

What it does (dry-run by default):

  For each confirmed booking WITHOUT google_calendar_event_id:
    - Fetch all calendar events on that booking's event_date
    - Find an event whose title contains the booking's act_name
      (case-insensitive substring match, both directions)
    - If single match → propose linking (sets google_calendar_event_id)
    - If multiple matches → report ambiguous (manual fix needed)
    - If no match     → report missing (could create via sync_calendar.py
                        --create-missing once reconciled)

Usage:
    python3 reconcile_calendar.py              # dry-run report
    python3 reconcile_calendar.py --confirm    # apply the proposed links
"""

import argparse
import re
import unicodedata
from datetime import date

import db
import calendar_client


# Words to ignore when computing similarity — too common to be signal
STOPWORDS = {
    "the", "and", "with", "presents", "presented", "live", "at", "in", "on",
    "of", "by", "for", "from", "to", "a", "an", "is", "no", "have", "their",
    "own", "door", "person", "needed", "tbc", "back", "bar", "backbar",
    "cobblestone", "backroom", "upstairs", "night", "nights",
}


def _strip_accents(s):
    """Caoimhe → caoimhe, ní → ni, etc."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _tokens(s):
    """Return a set of meaningful tokens from a string."""
    if not s:
        return set()
    s = _strip_accents(s).lower()
    # Strip apostrophes BEFORE punctuation→space, so "Piper's" → "pipers"
    # rather than "piper" + "s". Same for curly quotes.
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    out = set()
    for t in s.split():
        if not t:
            continue
        if t in STOPWORDS:
            continue
        if t.isdigit():
            continue
        out.add(t)
    return out


def _similarity(a, b):
    """Symmetric Jaccard-ish: |common| / min(|a|, |b|).

    Returns 0.0 if either side has no meaningful tokens.
    """
    at, bt = _tokens(a), _tokens(b)
    if not at or not bt:
        return 0.0
    common = at & bt
    return len(common) / min(len(at), len(bt))


# (Legacy helper kept for backwards-compat in any external callers)
def _normalise(s):
    if not s:
        return ""
    s = _strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true",
                   help="Actually link the events (default: dry-run report).")
    return p.parse_args()


def main():
    args = parse_args()
    db.init_db()
    conn = db.get_db()
    today = date.today().isoformat()

    # Get confirmed bookings missing a calendar event id
    bookings = conn.execute(
        """SELECT * FROM bookings
           WHERE status = 'confirmed'
             AND event_date >= ?
             AND archived_at IS NULL
             AND (google_calendar_event_id IS NULL OR google_calendar_event_id = '')
           ORDER BY event_date""",
        (today,),
    ).fetchall()
    conn.close()

    if not bookings:
        print("No confirmed bookings missing a calendar event id. Nothing to do.")
        return

    print(f"\n{'DRY RUN — ' if not args.confirm else ''}"
          f"Reconciling {len(bookings)} confirmed bookings missing calendar event id.\n")

    # Build the calendar service (Backroom only for now — Upstairs is V0-disabled)
    service = calendar_client._calendar_service("Backroom")
    if not service:
        print("[ERR] Could not build calendar service. Check GOOGLE_SERVICE_ACCOUNT_JSON env var.")
        return
    cal_id = calendar_client._calendar_id("Backroom")

    # Fetch all upcoming events once (cap at ~2 years out)
    end_iso = (date.fromisoformat(today).replace(year=date.fromisoformat(today).year + 2)).isoformat()
    print(f"Fetching Calendar events from {today} onward...")
    all_events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=cal_id,
            timeMin=f"{today}T00:00:00Z",
            timeMax=f"{end_iso}T23:59:59Z",
            singleEvents=True,
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        all_events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    print(f"Fetched {len(all_events)} calendar events.\n")

    # Index by date
    events_by_date = {}
    for e in all_events:
        start = e.get("start", {})
        d = start.get("date") or (start.get("dateTime") or "")[:10]
        if d:
            events_by_date.setdefault(d, []).append(e)

    linked = []     # (booking, event) — 1:1 match
    ambiguous = []  # (booking, [event, …]) — multi-match
    missing = []    # (booking,) — no match

    # Similarity threshold for token-based fuzzy match. 0.5 = at least half
    # of the smaller token set must overlap. Tuned to catch
    # 'Caoimhe ní Maolagáin and Louise Barker' ↔ 'Caoimhe ní Maolagáin and Louise Dancing 5.45-6.30'
    # 'Mr Irish Bastard' ↔ 'Mr Bastard Two Night Stand'
    # without false positives like 'People Before Profit' ↔ 'Pbp Night'.
    SIM_THRESHOLD = 0.5

    for b in bookings:
        ev_date = b["event_date"]
        candidates = events_by_date.get(ev_date, [])
        if not candidates:
            missing.append(b)
            continue

        # Score every candidate on the same date by token similarity, pick best
        scored = []
        for e in candidates:
            score = _similarity(b["act_name"], e.get("summary", ""))
            if score >= SIM_THRESHOLD:
                scored.append((score, e))

        if not scored:
            missing.append(b)
            continue

        # Sort by score descending; if there's a clear winner (top score > 2nd-best
        # by 0.15+), pick it. Otherwise flag ambiguous.
        scored.sort(key=lambda x: x[0], reverse=True)
        if len(scored) == 1 or (scored[0][0] - scored[1][0] >= 0.15):
            linked.append((b, scored[0][1]))
        else:
            ambiguous.append((b, [e for _, e in scored]))

    # Report
    print(f"  Single-match (link)  : {len(linked):>4}")
    print(f"  Ambiguous (>1 match) : {len(ambiguous):>4}")
    print(f"  No match (missing)   : {len(missing):>4}")
    print()

    if linked:
        print(f"--- Proposed links ({len(linked)}) ---")
        for b, e in linked[:50]:
            ev_id = e.get("id", "")[:12]
            print(f"  #{b['id']:>4}  {b['event_date']}  {b['act_name'][:35]:<35}  → {ev_id}…")
        if len(linked) > 50:
            print(f"  ... and {len(linked) - 50} more")

    if ambiguous:
        print(f"\n--- Ambiguous (multiple matches on same date) ---")
        for b, evs in ambiguous:
            print(f"  #{b['id']:>4}  {b['event_date']}  {b['act_name']}")
            for e in evs:
                print(f"        candidate: {e.get('summary', '')[:60]}  ({e.get('id', '')[:12]}…)")

    if missing:
        print(f"\n--- No calendar match found ({len(missing)}) ---")
        for b in missing[:50]:
            print(f"  #{b['id']:>4}  {b['event_date']}  {b['act_name']}")
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more")
        print(f"\n  These can be created with: python3 sync_calendar.py --confirm --create-missing")

    if not args.confirm:
        print(f"\nDRY RUN — re-run with --confirm to link {len(linked)} bookings.")
        return

    if not linked:
        print("\nNothing to link.")
        return

    print(f"\nLinking {len(linked)} bookings...")
    for b, e in linked:
        ev_id = e.get("id")
        db.update_booking_field(
            b["id"], "google_calendar_event_id", ev_id, actor="system",
        )
        db.add_booking_audit(
            b["id"], "system", "calendar_event_linked",
            f"Reconciled to existing calendar event {ev_id} "
            f"(summary: {e.get('summary', '')[:60]}) via reconcile_calendar.py",
        )
    print(f"Done. {len(linked)} bookings linked.")


if __name__ == "__main__":
    main()
