"""Backroom & Upstairs booking management routes.

Phase 1 of the booking-system rebuild: internal-only tracker that replaces
Backroom_Booking_Tracker.xlsx. Public band-facing routes (Phase 2),
Squarespace block + auto-confirm emails (Phase 3), and Square payment
links (Phase 4) land in subsequent commits.
"""

from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
import db


bp = Blueprint("bookings", __name__)


# ─── Constants exposed to templates ─────────────────────────────────────────
EVENT_TYPES = ["Gig", "Class", "Private Hire", "Rehearsal", "Filming", "Other"]
STATUSES = ["inquiry", "tentative", "confirmed", "completed", "cancelled"]
VENUES = ["Backroom", "Upstairs"]

STATUS_LABELS = {
    "inquiry":   "Inquiry",
    "tentative": "Tentative",
    "confirmed": "Confirmed",
    "completed": "Completed",
    "cancelled": "Cancelled",
}

# Bootstrap badge classes per status, used by the templates
STATUS_BADGES = {
    "inquiry":   "warning",
    "tentative": "info",
    "confirmed": "success",
    "completed": "secondary",
    "cancelled": "dark",
}


# ─── Helpers ────────────────────────────────────────────────────────────────
def _parse_form(form):
    """Pull a clean booking dict from request.form. Light validation only."""
    def _opt(key, default=None):
        v = (form.get(key) or "").strip()
        return v if v else default

    def _opt_int(key):
        v = _opt(key)
        try:
            return int(v) if v else None
        except ValueError:
            return None

    event_date = _opt("event_date")
    if not event_date:
        raise ValueError("Event date is required")
    if not _opt("act_name"):
        raise ValueError("Act / event name is required")

    # Compute day-of-week label for convenience
    try:
        dow = datetime.strptime(event_date, "%Y-%m-%d").strftime("%A")
    except Exception:
        dow = None

    return {
        "venue":               _opt("venue", "Backroom"),
        "event_date":          event_date,
        "day_of_week":         dow,
        "door_time":           _opt("door_time"),
        "start_time":          _opt("start_time"),
        "end_time":            _opt("end_time"),
        "status":              _opt("status", "inquiry"),
        "event_type":          _opt("event_type", "Gig"),
        "act_name":            _opt("act_name"),
        "contact_name":        _opt("contact_name"),
        "contact_email":       _opt("contact_email"),
        "contact_phone":       _opt("contact_phone"),
        "expected_attendance": _opt_int("expected_attendance"),
        "description":         _opt("description"),
        "media_links":         _opt("media_links"),
        "ticketing":           _opt("ticketing"),
        "ticket_price":        _opt("ticket_price"),
        "ticket_link":         _opt("ticket_link"),
        "door_person":         _opt("door_person"),
        "door_fee_required":   1 if form.get("door_fee_required") else 0,
        "venue_fee_required":  1 if form.get("venue_fee_required") else 0,
        "announcement_date":   _opt("announcement_date"),
        "support_act":         _opt("support_act"),
        "promo_ok":            _opt("promo_ok"),
        "notes":               _opt("notes"),
        "source":              _opt("source", "manual"),
    }


def _today_iso():
    return date.today().isoformat()


# ─── Routes ─────────────────────────────────────────────────────────────────
@bp.route("/bookings")
def bookings_list():
    """Master tracker view - filterable list of all bookings."""
    status   = request.args.get("status", "")
    venue    = request.args.get("venue", "")
    evtype   = request.args.get("event_type", "")
    start    = request.args.get("start_date", "")
    end      = request.args.get("end_date", "")
    view     = request.args.get("view", "upcoming")  # upcoming | past | all

    today = _today_iso()
    effective_start = start or None
    effective_end = end or None

    if not start and not end:
        if view == "upcoming":
            effective_start = today
        elif view == "past":
            effective_end = today

    bookings = db.list_bookings(
        status=status or None,
        venue=venue or None,
        event_type=evtype or None,
        start_date=effective_start,
        end_date=effective_end,
    )

    counts = db.booking_counts()

    return render_template(
        "bookings_list.html",
        bookings=bookings,
        counts=counts,
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
        event_types=EVENT_TYPES,
        venues=VENUES,
        filter_status=status,
        filter_venue=venue,
        filter_event_type=evtype,
        filter_start=start,
        filter_end=end,
        view=view,
        today=today,
    )


@bp.route("/bookings/new", methods=["GET", "POST"])
def new_booking():
    """Manually add a booking (e.g. from a phone call)."""
    if request.method == "GET":
        return render_template(
            "booking_detail.html",
            booking=None,
            audit=[],
            attachments=[],
            statuses=STATUSES,
            status_labels=STATUS_LABELS,
            status_badges=STATUS_BADGES,
            event_types=EVENT_TYPES,
            venues=VENUES,
            today=_today_iso(),
        )

    try:
        data = _parse_form(request.form)
        bid = db.save_booking(data)
        db.add_booking_audit(bid, "manual", "created", "Manually entered via webapp")
        flash(f"Booking #{bid} created.", "success")
        return redirect(url_for("bookings.booking_detail", booking_id=bid))
    except Exception as e:
        flash(f"Could not save booking: {e}", "danger")
        return redirect(url_for("bookings.new_booking"))


@bp.route("/bookings/<int:booking_id>")
def booking_detail(booking_id):
    """Detail view for a single booking - shows everything + actions sidebar."""
    booking = db.get_booking(booking_id)
    if not booking:
        flash("Booking not found.", "danger")
        return redirect(url_for("bookings.bookings_list"))

    return render_template(
        "booking_detail.html",
        booking=booking,
        audit=db.get_booking_audit(booking_id),
        attachments=db.get_booking_attachments(booking_id),
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
        event_types=EVENT_TYPES,
        venues=VENUES,
        today=_today_iso(),
    )


@bp.route("/bookings/<int:booking_id>/edit", methods=["POST"])
def edit_booking(booking_id):
    """Save edits to an existing booking."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    try:
        data = _parse_form(request.form)
        db.save_booking(data, booking_id=booking_id)
        db.add_booking_audit(booking_id, "internal", "edited",
                             f"Updated via detail page")
        flash("Booking updated.", "success")
    except Exception as e:
        flash(f"Could not update booking: {e}", "danger")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


@bp.route("/bookings/<int:booking_id>/status", methods=["POST"])
def change_status(booking_id):
    """Move a booking through the status pipeline."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    new_status = request.form.get("status", "").strip()
    if new_status not in STATUSES:
        flash(f"Invalid status: {new_status}", "danger")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    note = request.form.get("note", "").strip() or None
    actor = request.form.get("actor", "internal")
    db.update_booking_status(booking_id, new_status, actor=actor, detail=note)
    flash(f"Status set to {STATUS_LABELS.get(new_status, new_status)}.", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


@bp.route("/bookings/<int:booking_id>/fee/<which>", methods=["POST"])
def mark_fee_paid(booking_id, which):
    """Mark venue or door fee as paid (manual flag, pre-Square-payment-links)."""
    if which not in ("venue", "door"):
        abort(404)
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    field = "venue_fee_paid_at" if which == "venue" else "door_fee_paid_at"
    is_paid = booking[field] is not None
    new_value = None if is_paid else datetime.now().isoformat()
    db.update_booking_field(booking_id, field, new_value, actor="internal")
    flash(f"{which.capitalize()} fee marked as {'unpaid' if is_paid else 'paid'}.", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


@bp.route("/bookings/<int:booking_id>/squarespace", methods=["POST"])
def toggle_squarespace_published(booking_id):
    """Tick / untick the 'Squarespace published' checkbox."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    is_published = booking["squarespace_published_at"] is not None
    new_value = None if is_published else datetime.now().isoformat()
    db.update_booking_field(booking_id, "squarespace_published_at", new_value, actor="internal")
    flash(f"Squarespace status: {'unpublished' if is_published else 'published'}.", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


@bp.route("/bookings/<int:booking_id>/note", methods=["POST"])
def add_note(booking_id):
    """Append a free-text note to the booking + audit log."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    note = request.form.get("note", "").strip()
    if not note:
        flash("Note can't be empty.", "warning")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    db.add_booking_audit(booking_id, "internal", "note", note)
    flash("Note added.", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
