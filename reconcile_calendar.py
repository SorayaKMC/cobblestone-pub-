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
from datetime import date

import db
import calendar_client


def _normalise(s):
    """Lowercase + strip punctuation + collapse whitespace for fuzzy matching."""
    if not s:
        return ""
    s = s.lower()
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

    for b in bookings:
        ev_date = b["event_date"]
        candidates = events_by_date.get(ev_date, [])
        if not candidates:
            missing.append(b)
            continue

        # Match by normalised act_name substring (either direction)
        act_norm = _normalise(b["act_name"])
        matches = []
        for e in candidates:
            sum_norm = _normalise(e.get("summary", ""))
            if not sum_norm:
                continue
            # Match: act name substring of summary OR summary substring of act name
            # (handles "Caoimhe ní Maolagáin and Louise" vs "Caoimhe ní Maolagáin and Louise Dancing 5.45-6.30, 6.30-7.15")
            if act_norm in sum_norm or sum_norm in act_norm:
                matches.append(e)

        if len(matches) == 1:
            linked.append((b, matches[0]))
        elif len(matches) > 1:
            ambiguous.append((b, matches))
        else:
            missing.append(b)

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
