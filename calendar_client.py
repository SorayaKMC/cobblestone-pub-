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
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

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
    """Convert a booking row to a Google Calendar event dict."""
    from datetime import datetime as _dt, timedelta

    event_date  = booking["event_date"]          # YYYY-MM-DD
    start_time  = booking["start_time"] or "20:00"
    door_time   = booking["door_time"]  or "19:00"
    end_time    = booking["end_time"]

    # Build RFC3339 datetimes — assume Europe/Dublin local time
    tz = "Europe/Dublin"
    start_dt = _dt.strptime(f"{event_date} {start_time}", "%Y-%m-%d %H:%M")
    if end_time:
        end_dt = _dt.strptime(f"{event_date} {end_time}", "%Y-%m-%d %H:%M")
    else:
        end_dt = start_dt + timedelta(hours=3)

    def _fmt(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    act   = booking["act_name"]
    venue = booking["venue"]

    # Build a useful description
    parts = [f"Venue: {venue} — Cobblestone Pub, 77 King St N, Smithfield, Dublin 7"]
    if door_time:
        parts.append(f"Doors: {door_time}")
    if booking["contact_name"]:
        parts.append(f"Contact: {booking['contact_name']}")
    if booking["contact_email"]:
        parts.append(f"Email: {booking['contact_email']}")
    if booking["contact_phone"]:
        parts.append(f"Phone: {booking['contact_phone']}")
    if booking["description"]:
        parts.append(f"\n{booking['description']}")

    return {
        "summary": f"{act} | {venue} — Cobblestone Pub",
        "location": f"Cobblestone Pub — {venue}, 77 King St N, Smithfield, Dublin 7",
        "description": "\n".join(parts),
        "start": {"dateTime": _fmt(start_dt), "timeZone": tz},
        "end":   {"dateTime": _fmt(end_dt),   "timeZone": tz},
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
    venue = booking.get("venue", "Backroom")
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
    venue = booking.get("venue", "Backroom")
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
    venue = booking.get("venue", "Backroom")
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
