"""Google Calendar integration for Cobblestone Pub booking confirmations.

Creates / updates / deletes events in the Cobblestone Google Calendar whenever
a booking is confirmed, rescheduled, or cancelled.

Required environment variables:
    GOOGLE_SERVICE_ACCOUNT_JSON   — full JSON key file contents (one-line string)
    GOOGLE_CALENDAR_ID            — Backroom calendar ID
    GOOGLE_CALENDAR_ID_UPSTAIRS   — Upstairs calendar ID (optional; falls back
                                    to GOOGLE_CALENDAR_ID if not set)

All vars are optional.  If credentials or a calendar ID are missing the
functions log a message and return None so the booking flow continues
uninterrupted.
"""

import json
import os

# Eagerly import the Google client libs at module load (single-threaded
# context) to avoid the well-known import race in googleapiclient when
# multiple threads first-import .discovery concurrently:
#   https://github.com/googleapis/google-api-python-client/issues/1502
from google.oauth2 import service_account
from googleapiclient.discovery import build

import config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calendar_id(venue="Backroom"):
    """Return the Google Calendar ID for the given venue."""
    if venue == "Upstairs":
        return (
            os.getenv("GOOGLE_CALENDAR_ID_UPSTAIRS", "")
            or os.getenv("GOOGLE_CALENDAR_ID", "")
        )
    return os.getenv("GOOGLE_CALENDAR_ID", "")


def _calendar_service(venue="Backroom"):
    """Build and return an authenticated Google Calendar service, or None."""
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        print("[calendar] GOOGLE_SERVICE_ACCOUNT_JSON not set — Calendar disabled")
        return None
    if not _calendar_id(venue):
        print(f"[calendar] No calendar ID configured for venue '{venue}' — Calendar disabled")
        return None

    try:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[calendar] Failed to build service: {e}")
        return None


def _booking_to_event(booking):
    """Convert a booking row to a Google Calendar event dict.

    If the booking has no times set (door_time, start_time, end_time all
    null/empty), the event is created as an ALL-DAY event. This is what
    we want for holds, tbc placeholders, and any booking where times
    haven't been agreed yet. Once any time is set, it becomes a timed
    event with sensible defaults filling the other fields.
    """
    from datetime import datetime as _dt, timedelta

    event_date  = booking["event_date"]          # YYYY-MM-DD
    start_time  = booking["start_time"]
    door_time   = booking["door_time"]
    end_time    = booking["end_time"]
    has_any_time = bool(start_time) or bool(door_time) or bool(end_time)

    tz = "Europe/Dublin"

    if has_any_time:
        # Timed event — fill in missing pieces with sensible defaults
        eff_start = start_time or "20:00"
        start_dt = _dt.strptime(f"{event_date} {eff_start}", "%Y-%m-%d %H:%M")
        if end_time:
            end_dt = _dt.strptime(f"{event_date} {end_time}", "%Y-%m-%d %H:%M")
        else:
            end_dt = start_dt + timedelta(hours=3)

        def _fmt(dt):
            return dt.strftime("%Y-%m-%dT%H:%M:%S")

        event_time_block = {
            "start": {"dateTime": _fmt(start_dt), "timeZone": tz},
            "end":   {"dateTime": _fmt(end_dt),   "timeZone": tz},
        }
    else:
        # All-day event — Google's spec needs end.date = start.date + 1 day
        end_date_obj = _dt.strptime(event_date, "%Y-%m-%d") + timedelta(days=1)
        end_date_str = end_date_obj.strftime("%Y-%m-%d")
        event_time_block = {
            "start": {"date": event_date},
            "end":   {"date": end_date_str},
        }

    act   = booking["act_name"]
    venue = booking["venue"]

    # Legacy detector — confirmed bookings that predate the €50 door-fee policy:
    # either migrated from the original form (source='form-import') OR more than
    # 6 weeks old (rolling cutoff). These don't pay a door person fee.
    is_legacy_no_door_fee = False
    try:
        if (booking["status"] or "") == "confirmed":
            if (booking["source"] or "") == "form-import":
                is_legacy_no_door_fee = True
            elif booking["created_at"]:
                cutoff = (_dt.now().date() - timedelta(weeks=6)).isoformat()
                if booking["created_at"][:10] < cutoff:
                    is_legacy_no_door_fee = True
    except Exception:
        pass

    # Build a rich structured description
    parts = [
        f"📍 {venue} — Cobblestone Pub, 77 King St N, Smithfield, Dublin 7",
        f"🎭 {booking['event_type'] or 'Gig'}",
    ]
    if is_legacy_no_door_fee:
        parts.append("🚫 NO DOORPERSON FEE — legacy booking (predates €50 door-fee policy)")
    parts += [
        "",
        "── TIMES ──────────────────────────────────────",
        f"Doors:  {booking['door_time'] or 'TBC'}",
        f"Show:   {booking['start_time'] or 'TBC'}",
        f"End:    {booking['end_time'] or 'TBC'}",
        "",
        "── CONTACTS ────────────────────────────────────",
    ]
    if booking["contact_name"]:
        parts.append(f"Act contact: {booking['contact_name']}")
    if booking["contact_email"]:
        parts.append(f"Email:       {booking['contact_email']}")
    if booking["contact_phone"]:
        parts.append(f"Phone:       {booking['contact_phone']}")

    parts += [
        "",
        "── LOGISTICS ───────────────────────────────────",
    ]

    # Door person
    dp = booking["door_person"]
    dp_fee = booking["door_fee_required"]
    if is_legacy_no_door_fee:
        parts.append("Door person: NO FEE — legacy booking (no €50 charge on the night)")
    elif dp == "pub":
        parts.append("Door person: Pub provided (€50 — band to pay on night)")
    elif dp == "own":
        parts.append("Door person: Band providing their own")
    elif dp == "none":
        parts.append("Door person: Not required")
    elif dp_fee:
        parts.append("Door person: Required (€50)")
    else:
        parts.append("Door person: TBC")

    # Ticketing
    if booking["ticketing"]:
        ticket_line = f"Ticketing:   {booking['ticketing']}"
        if booking["ticket_price"]:
            ticket_line += f" — {booking['ticket_price']}"
        parts.append(ticket_line)
    if booking["ticket_link"]:
        parts.append(f"Ticket link: {booking['ticket_link']}")

    # Sound engineer
    parts += [
        "Sound eng:   Shane Hannigan — +353 (85) 175 8254 / onsoundie@gmail.com",
    ]

    if booking["support_act"]:
        parts.append(f"Support:     {booking['support_act']}")

    if booking["description"]:
        parts += ["", "── DESCRIPTION ─────────────────────────────────", booking["description"].strip()]

    if booking["notes"]:
        parts += ["", "── INTERNAL NOTES ──────────────────────────────", booking["notes"].strip()]

    parts += [
        "",
        "─" * 50,
        "⚠️  This event is managed by the Cobblestone booking system.",
        "To edit or cancel, use: cobblestone-pub.onrender.com/bookings",
        "Do NOT add bookings directly in Google Calendar — they won't appear in the system.",
    ]

    return {
        "summary": f"{act} | {venue} — Cobblestone Pub",
        "location": f"Cobblestone Pub — {venue}, 77 King St N, Smithfield, Dublin 7",
        "description": "\n".join(parts),
        **event_time_block,   # start + end (timed or all-day)
        "colorId": "2",   # Sage green — easy to spot in the calendar
        "extendedProperties": {
            "private": {
                "cobblestone_booking_id": str(booking["id"]),
            }
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_calendar_event(booking):
    """Create a Google Calendar event for a confirmed booking.

    Routes to the correct calendar based on booking['venue'].
    Returns the created event ID string, or None on failure / misconfiguration.
    """
    venue = booking["venue"] or "Backroom"
    service = _calendar_service(venue)
    if not service:
        return None

    try:
        event_body = _booking_to_event(booking)
        result = service.events().insert(
            calendarId=_calendar_id(venue),
            body=event_body,
        ).execute()
        event_id = result.get("id")
        print(f"[calendar] Created event {event_id!r} on {venue} calendar for booking #{booking['id']}")
        return event_id
    except Exception as e:
        print(f"[calendar] Failed to create event for booking #{booking['id']}: {e}")
        return None


def update_calendar_event(booking, event_id):
    """Update an existing Calendar event after booking details change.

    Routes to the correct calendar based on booking['venue'].
    Returns True on success, False on failure.
    """
    if not event_id:
        return False
    venue = booking["venue"] or "Backroom"
    service = _calendar_service(venue)
    if not service:
        return False

    try:
        event_body = _booking_to_event(booking)
        service.events().update(
            calendarId=_calendar_id(venue),
            eventId=event_id,
            body=event_body,
        ).execute()
        print(f"[calendar] Updated event {event_id!r} on {venue} calendar for booking #{booking['id']}")
        return True
    except Exception as e:
        print(f"[calendar] Failed to update event {event_id!r}: {e}")
        return False


def delete_calendar_event(booking, event_id):
    """Delete a Calendar event when a booking is cancelled.

    Routes to the correct calendar based on booking['venue'].
    Returns True on success, False on failure.
    """
    if not event_id:
        return False
    venue = booking["venue"] or "Backroom"
    service = _calendar_service(venue)
    if not service:
        return False

    try:
        service.events().delete(
            calendarId=_calendar_id(venue),
            eventId=event_id,
        ).execute()
        print(f"[calendar] Deleted event {event_id!r} from {venue} calendar for booking #{booking['id']}")
        return True
    except Exception as e:
        print(f"[calendar] Failed to delete event {event_id!r}: {e}")
        return False
