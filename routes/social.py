"""Social media (Méabh) view — read-only access at /social.

Auth handled in app.py before_request. Credentials:
SOCIAL_AUTH_USERNAME / SOCIAL_AUTH_PASSWORD env vars.

Gives access to:
  /social                 — upcoming confirmed gigs list
  /social/<id>            — act detail: bio, social links, attachments
  /social/weekly-poster   — download this week's social card (post + story)
"""

from datetime import date, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort)
import db

bp = Blueprint("social", __name__)


def _today_iso():
    return date.today().isoformat()


@bp.route("/social")
def social_list():
    today = _today_iso()
    cutoff = (date.today() + timedelta(days=60)).isoformat()

    bookings = db.list_bookings(
        status="confirmed",
        start_date=today,
        end_date=cutoff,
        limit=500,
    )
    bookings = [b for b in bookings if b["event_date"] >= today]

    return render_template("social_list.html", bookings=bookings, today=today)


@bp.route("/social/<int:booking_id>")
def social_detail(booking_id):
    booking = db.get_booking(booking_id)
    if not booking:
        flash("Booking not found.", "danger")
        return redirect(url_for("social.social_list"))
    if booking["status"] != "confirmed":
        flash("That booking isn't confirmed.", "warning")
        return redirect(url_for("social.social_list"))

    return render_template(
        "social_detail.html",
        booking=booking,
        attachments=db.get_booking_attachments(booking_id),
    )


@bp.route("/social/weekly-poster")
def weekly_poster():
    """Social card download page — post (1080×1350) and story (1080×1920)."""
    from datetime import date, timedelta
    today = date.today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    monday = today + timedelta(days=days_to_monday)

    week_param = request.args.get("week")
    if week_param:
        try:
            monday = date.fromisoformat(week_param)
            monday -= timedelta(days=monday.weekday())
        except ValueError:
            pass

    sunday = monday + timedelta(days=6)
    from routes.bookings import _week_bookings
    days = _week_bookings(monday.isoformat())
    prev_monday = (monday - timedelta(days=7)).isoformat()
    next_monday = (monday + timedelta(days=7)).isoformat()

    return render_template(
        "social_weekly_poster.html",
        days=days,
        monday=monday,
        sunday=sunday,
        prev_monday=prev_monday,
        next_monday=next_monday,
    )
