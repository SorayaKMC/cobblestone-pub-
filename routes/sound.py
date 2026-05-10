"""Sound engineer (Shane) view — scoped, read-mostly access at /sound.

Auth is handled in the global before_request (see app.py). This blueprint
only renders the engineer-facing pages and exposes one write action
(mark venue fee paid). Everything else is read-only.

The engineer auth credentials are separate from manager creds:
ENGINEER_AUTH_USERNAME / ENGINEER_AUTH_PASSWORD env vars.
"""

import os
import json
from datetime import date, datetime, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)

import db


bp = Blueprint("sound", __name__)


def _today_iso():
    return date.today().isoformat()


def _load_email_snippets_for(contact_email):
    """Mirror of routes/bookings._load_email_snippets_for so the engineer
    detail page can show the same recent-emails panel."""
    if not contact_email:
        return []
    try:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "email_snippets.json")
        with open(cache_path) as f:
            data = json.load(f)
        return data.get(contact_email.strip().lower(), [])
    except Exception:
        return []


@bp.route("/sound")
def sound_list():
    """List of confirmed upcoming gigs for Shane."""
    today = _today_iso()
    cutoff = (date.today() + timedelta(days=120)).isoformat()  # next ~4 months

    bookings = db.list_bookings(
        status="confirmed",
        start_date=today,
        end_date=cutoff,
        limit=500,
    )

    # Strip past gigs that snuck through (shouldn't happen but just in case)
    bookings = [b for b in bookings if b["event_date"] >= today]

    # IDs of gigs within 7 days that need a door person — surface as a soft warning
    door_warning_ids = {
        b["id"] for b in db.get_bookings_needing_door_confirmation(days_ahead=7)
    }

    return render_template(
        "sound_list.html",
        bookings=bookings,
        today=today,
        door_warning_ids=door_warning_ids,
    )


@bp.route("/sound/<int:booking_id>")
def sound_detail(booking_id):
    """Read-only detail page for a single gig from Shane's POV."""
    booking = db.get_booking(booking_id)
    if not booking:
        flash("Booking not found.", "danger")
        return redirect(url_for("sound.sound_list"))

    # Only show confirmed gigs to Shane (no inquiries / cancelled / etc.)
    if booking["status"] != "confirmed":
        flash("That booking isn't a confirmed gig.", "warning")
        return redirect(url_for("sound.sound_list"))

    return render_template(
        "sound_detail.html",
        booking=booking,
        attachments=db.get_booking_attachments(booking_id),
        email_snippets=_load_email_snippets_for(booking["contact_email"]),
    )


@bp.route("/sound/<int:booking_id>/mark-fee-paid", methods=["POST"])
def sound_mark_fee_paid(booking_id):
    """Shane marks the venue fee as paid (his fee, paid by act on the night)."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    if booking["status"] != "confirmed":
        flash("Can only mark fees paid on confirmed gigs.", "warning")
        return redirect(url_for("sound.sound_detail", booking_id=booking_id))

    db.update_booking_field(
        booking_id, "venue_fee_paid_at",
        datetime.now().isoformat(),
        actor="engineer",
    )
    db.add_booking_audit(
        booking_id, "engineer", "venue_fee_paid",
        "Marked venue fee paid (Shane via /sound)",
    )
    flash(f"Venue fee marked paid for {booking['act_name']}. ✓", "success")
    return redirect(url_for("sound.sound_detail", booking_id=booking_id))
