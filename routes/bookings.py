"""Backroom & Upstairs booking management routes.

Internal tracker (Phase 1) + public band-facing routes (Phase 2).
Squarespace block + auto-confirm emails land in Phase 3.
Square payment links land in Phase 4.
"""

import os
import re
from datetime import date, datetime
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort, jsonify, send_file)
import config
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
        squarespace_block=_squarespace_block(booking),
    )


@bp.route("/bookings/<int:booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    """Confirm a booking: set status, stamp confirmation time, send email."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)

    db.update_booking_status(booking_id, "confirmed", actor="internal",
                             detail="Confirmed via Quick Actions")
    db.update_booking_field(booking_id, "confirmation_sent_at",
                            datetime.now().isoformat(), actor="internal")

    # Send confirmation email — non-blocking
    email_sent = False
    if booking["contact_email"]:
        try:
            import bookings_email
            email_sent = bookings_email.send_booking_confirmation(
                db.get_booking(booking_id),          # re-fetch with updated status
                request.host_url.rstrip("/"),
            )
        except Exception as e:
            print(f"[bookings] Confirmation email failed: {e}")

    if email_sent:
        flash("Booking confirmed and confirmation email sent to the band. ✓", "success")
    elif booking["contact_email"]:
        flash("Booking confirmed. Email could not be sent — check SMTP settings in Render.", "warning")
    else:
        flash("Booking confirmed. No email address on file.", "success")

    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


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


# ─── Squarespace block generator ────────────────────────────────────────────

def _squarespace_block(booking):
    """Return a copy-pasteable Squarespace event text block for a confirmed booking."""
    if not booking:
        return ""

    try:
        dt = datetime.strptime(booking["event_date"], "%Y-%m-%d")
        date_str = dt.strftime("%A, %-d %B %Y")
    except Exception:
        date_str = booking["event_date"] or ""

    door  = booking["door_time"]  or "TBC"
    start = booking["start_time"] or "TBC"
    end   = booking["end_time"]   or ""

    times = f"Doors {door}"
    if start != "TBC":
        times += f" · Music {start}"
    if end:
        times += f" · End {end}"

    venue_line = f"Cobblestone Pub — {booking['venue']}\n77 King St N, Smithfield, Dublin 7"

    parts = [
        "── SQUARESPACE EVENT ──────────────────────────────────────────",
        "",
        f"TITLE:     {booking['act_name']} | Live at the Cobblestone Pub",
        "",
        f"DATE:      {date_str}",
        f"TIMES:     {times}",
        "",
        "LOCATION:",
        venue_line,
        "",
    ]

    if booking["description"]:
        parts += [
            "DESCRIPTION:",
            "─" * 50,
            booking["description"].strip(),
            "─" * 50,
            "",
        ]

    if booking["support_act"]:
        parts += [f"SUPPORT:   {booking['support_act']}", ""]

    if booking["ticketing"]:
        ticket = booking["ticketing"]
        if booking["ticket_price"]:
            ticket += f" — {booking['ticket_price']}"
        parts += [f"TICKETS:   {ticket}", ""]
        if booking["ticket_link"]:
            parts += [f"TICKET LINK: {booking['ticket_link']}", ""]

    if booking["media_links"]:
        parts += ["LINKS:", booking["media_links"].strip(), ""]

    if booking["announcement_date"]:
        parts += [f"ANNOUNCE:  {booking['announcement_date']}", ""]

    parts += [
        f"TAGS:      Live Music · {booking['venue']} · {booking['act_name']}",
        "───────────────────────────────────────────────────────────────",
    ]

    return "\n".join(parts)


# ─── Internal: attachment download ──────────────────────────────────────────

@bp.route("/bookings/<int:booking_id>/attachment/<int:att_id>")
def booking_attachment(booking_id, att_id):
    """Serve an uploaded file for internal staff review."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)
    att = next((a for a in db.get_booking_attachments(booking_id) if a["id"] == att_id), None)
    if not att:
        abort(404)
    return send_file(att["file_path"], as_attachment=True, download_name=att["filename"])


# ─── Public: band-facing routes (/book/...) ─────────────────────────────────

def _parse_public_form(form):
    """Parse the public band-facing booking form with stricter validation."""
    def _opt(key, default=None):
        v = (form.get(key) or "").strip()
        return v if v else default

    act_name = _opt("act_name")
    if not act_name:
        raise ValueError("Act / event name is required.")

    contact_name = _opt("contact_name")
    if not contact_name:
        raise ValueError("Your name is required.")

    contact_email = _opt("contact_email")
    if not contact_email or "@" not in contact_email:
        raise ValueError("A valid email address is required.")

    event_date = _opt("event_date")
    if not event_date:
        raise ValueError("Please select a date on the calendar.")
    if event_date < _today_iso():
        raise ValueError("Please select a future date.")

    try:
        dow = datetime.strptime(event_date, "%Y-%m-%d").strftime("%A")
    except Exception:
        dow = None

    return {
        "venue":               _opt("venue", "Backroom"),
        "event_date":          event_date,
        "day_of_week":         dow,
        "door_time":           None,
        "start_time":          None,
        "end_time":            None,
        "status":              "inquiry",
        "event_type":          _opt("event_type", "Gig"),
        "act_name":            act_name,
        "contact_name":        contact_name,
        "contact_email":       contact_email,
        "contact_phone":       _opt("contact_phone"),
        "expected_attendance": None,
        "description":         _opt("description"),
        "media_links":         _opt("media_links"),
        "ticketing":           None,
        "ticket_price":        None,
        "ticket_link":         None,
        "door_person":         None,
        "door_fee_required":   0,
        "venue_fee_required":  1,
        "announcement_date":   None,
        "support_act":         None,
        "promo_ok":            None,
        "notes":               None,
        "source":              "web",
    }


@bp.route("/book", methods=["GET"])
def book_form():
    """Public booking inquiry form."""
    return render_template(
        "book_public.html",
        venues=VENUES,
        event_types=EVENT_TYPES,
        form_data={},
    )


@bp.route("/book", methods=["POST"])
def book_submit():
    """Handle public booking form submission."""
    try:
        data = _parse_public_form(request.form)
        bid = db.save_booking(data)
        booking = db.get_booking(bid)
        db.add_booking_audit(bid, "band", "created", "Submitted via public booking form")

        # Auto-ack email — non-blocking, failure does not break the flow
        try:
            import bookings_email
            base_url = request.host_url.rstrip("/")
            bookings_email.send_booking_ack(booking, base_url)
        except Exception as email_err:
            print(f"[bookings] Auto-ack email failed: {email_err}")

        flash("Your inquiry has been received! We'll be in touch within 2–3 working days.", "success")
        return redirect(url_for("bookings.book_portal", token=booking["public_token"]))

    except ValueError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Something went wrong — please try again. ({e})", "danger")

    return render_template(
        "book_public.html",
        venues=VENUES,
        event_types=EVENT_TYPES,
        form_data=request.form,
    )


@bp.route("/book/availability.json")
def availability_json():
    """Return date→status map for the availability calendar (no auth required)."""
    venue = request.args.get("venue", "Backroom")
    today = _today_iso()

    rows = db.list_bookings(
        status=["confirmed", "tentative"],
        venue=venue,
        start_date=today,
    )

    statuses = {}
    for b in rows:
        d = b["event_date"]
        s = b["status"]
        # confirmed wins over tentative — never downgrade
        if s == "confirmed":
            statuses[d] = "booked"
        elif s == "tentative" and statuses.get(d) != "booked":
            statuses[d] = "tentative"

    return jsonify({"statuses": statuses, "venue": venue})


@bp.route("/book/<token>")
def book_portal(token):
    """Band's booking portal — status, checklist, file uploads."""
    booking = db.get_booking(token)
    if not booking:
        return render_template(
            "book_portal.html",
            booking=None,
            attachments=[],
            status_labels=STATUS_LABELS,
            status_badges=STATUS_BADGES,
        ), 404

    return render_template(
        "book_portal.html",
        booking=booking,
        attachments=db.get_booking_attachments(booking["id"]),
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
    )


@bp.route("/book/<token>/upload", methods=["POST"])
def book_upload(token):
    """Accept a file upload from the band portal."""
    booking = db.get_booking(token)
    if not booking:
        abort(404)

    if booking["status"] in ("cancelled", "completed"):
        flash("This booking is no longer accepting uploads.", "warning")
        return redirect(url_for("bookings.book_portal", token=token))

    f = request.files.get("file")
    if not f or not f.filename:
        flash("No file selected.", "warning")
        return redirect(url_for("bookings.book_portal", token=token))

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}:
        flash("Only images (JPG, PNG, GIF, WebP) and PDFs are accepted.", "danger")
        return redirect(url_for("bookings.book_portal", token=token))

    kind = request.form.get("kind", "other")
    booking_id = booking["id"]
    upload_dir = os.path.join(config.BOOKING_UPLOADS_DIR, str(booking_id))
    os.makedirs(upload_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w.\-]", "_", f.filename)
    filepath = os.path.join(upload_dir, f"{stamp}_{safe_name}")
    f.save(filepath)

    db.add_booking_attachment(booking_id, kind, f.filename, filepath)
    db.add_booking_audit(booking_id, "band", "uploaded", f"{kind}: {f.filename}")

    flash(f"'{f.filename}' uploaded successfully.", "success")
    return redirect(url_for("bookings.book_portal", token=token))


@bp.route("/bookings/<int:booking_id>/message", methods=["POST"])
def send_message(booking_id):
    """Send a staff-composed email to the band from inside the booking detail page."""
    booking = db.get_booking(booking_id)
    if not booking:
        abort(404)

    subject = (request.form.get("subject") or "").strip()
    body    = (request.form.get("body") or "").strip()

    if not subject:
        flash("Subject is required.", "warning")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    if not body:
        flash("Message body is required.", "warning")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    if not booking["contact_email"]:
        flash("No email address on file for this booking.", "warning")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

    try:
        import bookings_email
        sent = bookings_email.send_staff_message(
            booking, subject, body, request.host_url.rstrip("/")
        )
        if sent:
            db.add_booking_audit(booking_id, "internal", "email_sent",
                                 f"Subject: {subject}")
            flash(f"Email sent to {booking['contact_email']}. ✓", "success")
        else:
            flash("Email could not be sent — check SMTP settings in Render.", "warning")
    except Exception as e:
        flash(f"Email failed: {e}", "danger")

    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


@bp.route("/book/<token>/cancel", methods=["POST"])
def band_cancel_booking(token):
    """Handle a band cancelling their own booking via the portal."""
    booking = db.get_booking(token)
    if not booking:
        abort(404)

    if booking["status"] in ("cancelled", "completed"):
        flash("This booking is already closed.", "info")
        return redirect(url_for("bookings.book_portal", token=token))

    reason = (request.form.get("reason") or "").strip() or "No reason given"

    db.cancel_booking(
        booking["id"],
        cancelled_by="band",
        actor="band",
        detail=f"Cancelled via portal. Reason: {reason}",
    )

    # Refresh booking row before sending emails
    updated = db.get_booking(booking["id"])

    # Confirmation to band
    try:
        import bookings_email
        bookings_email.send_band_cancellation_confirmation(
            updated, request.host_url.rstrip("/")
        )
    except Exception as e:
        print(f"[bookings] Band cancel confirmation email failed: {e}")

    # Alert to pub staff
    try:
        import bookings_email
        bookings_email.send_cancellation_alert_to_pub(
            updated,
            request.host_url.rstrip("/"),
            cancelled_by="band",
            reason=reason,
        )
    except Exception as e:
        print(f"[bookings] Pub cancellation alert failed: {e}")

    flash("Your booking has been cancelled. We've sent a confirmation to your email.", "info")
    return redirect(url_for("bookings.book_portal", token=token))


@bp.route("/book/<token>/attachment/<int:att_id>")
def book_attachment(token, att_id):
    """Serve an uploaded file to the band via their portal token."""
    booking = db.get_booking(token)
    if not booking:
        abort(404)
    att = next((a for a in db.get_booking_attachments(booking["id"]) if a["id"] == att_id), None)
    if not att:
        abort(404)
    return send_file(att["file_path"], as_attachment=True, download_name=att["filename"])
