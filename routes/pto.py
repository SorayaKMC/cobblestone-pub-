from flask import Blueprint, render_template, request, redirect, url_for, flash
from decimal import Decimal
from datetime import date, datetime
import db
import square_client
import pto_engine
import pto_historical_import

bp = Blueprint("pto", __name__)


@bp.route("/pto")
def pto_page():
    summary = db.get_pto_summary()
    team_members = None
    try:
        team_members = square_client.get_team_members()
    except Exception:
        pass

    members_by_id = {m["id"]: m for m in team_members} if team_members else {}

    # Enrich with status and accrual type
    for emp in summary:
        status_label, status_class = pto_engine.get_pto_status(emp["balance"])
        emp["status_label"] = status_label
        emp["status_class"] = status_class

        member = members_by_id.get(emp["team_member_id"], {})
        emp["accrual_type"] = "Salaried" if member.get("pay_type") == "SALARY" else "Hourly"

    # Batch-compute 13-week avg shift for all hourly employees (single Square API call)
    today_iso = date.today().isoformat()
    hourly_ids = [emp["team_member_id"] for emp in summary if emp["accrual_type"] == "Hourly"]
    try:
        avg_shifts = pto_engine.calculate_13_week_avg_shift_batch(hourly_ids, today_iso)
    except Exception:
        avg_shifts = {}
    for emp in summary:
        if emp["accrual_type"] == "Hourly":
            raw = avg_shifts.get(emp["team_member_id"])
            emp["avg_shift"] = float(raw) if raw is not None else 8.0
        else:
            emp["avg_shift"] = None  # salaried — not used for accrual

    # For each employee, hours-equivalent of their balance using their
    # 13-week avg shift. Makes "you have X hours of leave" easy to read.
    for emp in summary:
        avg = emp.get("avg_shift") or 8.0
        emp["balance_hours"] = round(emp["balance"] * avg, 1)
        emp["accrued_hours_total"] = round(emp["total_accrued"] * avg, 1)
        emp["taken_hours_total"] = round(emp["total_taken"] * avg, 1)

    categories = db.get_employee_categories()
    active_employees = [
        {"id": r["team_member_id"], "name": f"{r['given_name']} {r['family_name']}"}
        for r in categories if r["is_active"]
    ]
    names_by_id = {
        r["team_member_id"]: f"{r['given_name']} {r['family_name']}"
        for r in categories
    }

    taken_log = db.get_pto_taken_log()
    manual_hours_log = db.list_manual_hours()

    return render_template("pto.html",
        summary=summary,
        employees=active_employees,
        names_by_id=names_by_id,
        taken_log=taken_log,
        manual_hours_log=manual_hours_log,
        today=date.today().isoformat(),
    )


@bp.route("/pto/manual-hours", methods=["POST"])
def add_manual_hours():
    """Record hours an employee worked in a given ISO week when Square
    doesn't have their timecards. The next Recalculate run picks these up.
    """
    tm_id = request.form.get("team_member_id")
    week_start = request.form.get("week_start", "").strip()
    hours = float(request.form.get("hours", 0) or 0)
    note = (request.form.get("note", "") or "").strip() or None

    if not tm_id or not week_start or hours <= 0:
        flash("Pick an employee, a week-start (Monday) date, and hours > 0.", "warning")
        return redirect(url_for("pto.pto_page"))

    # Snap to Monday of the week if a non-Monday date was given
    try:
        d = datetime.strptime(week_start, "%Y-%m-%d").date()
        from datetime import timedelta as _td
        snap = d - _td(days=d.weekday())
        week_start = snap.isoformat()
    except ValueError:
        flash("Invalid date format.", "danger")
        return redirect(url_for("pto.pto_page"))

    db.set_manual_hours(tm_id, week_start, hours, note=note)
    cat = db.get_employee_category(tm_id)
    name = f"{cat['given_name']} {cat['family_name']}" if cat else tm_id
    flash(
        f"Saved {hours} manual hour(s) for {name}, week starting {week_start}. "
        "Click Recalculate PTO to apply.",
        "success",
    )
    return redirect(url_for("pto.pto_page"))


@bp.route("/pto/manual-hours/delete", methods=["POST"])
def delete_manual_hours():
    tm_id = request.form.get("team_member_id")
    week_start = request.form.get("week_start")
    if tm_id and week_start:
        db.delete_manual_hours(tm_id, week_start)
        flash(f"Manual-hours entry removed. Recalculate to apply.", "info")
    return redirect(url_for("pto.pto_page"))


@bp.route("/pto/log", methods=["POST"])
def log_pto_taken():
    tm_id = request.form.get("team_member_id")
    pto_date = request.form.get("date")
    days = float(request.form.get("days_taken", 1))
    reason = request.form.get("reason", "")

    if not tm_id or not pto_date:
        flash("Please select an employee and date.", "warning")
        return redirect(url_for("pto.pto_page"))

    # Calculate hours equivalent from 13-week avg
    avg_shift = float(pto_engine.calculate_13_week_avg_shift(tm_id, pto_date))
    hours_equiv = days * avg_shift

    db.add_pto_taken(tm_id, pto_date, days, hours_equiv, reason)

    cat = db.get_employee_category(tm_id)
    name = f"{cat['given_name']} {cat['family_name']}" if cat else tm_id
    flash(f"Logged {days} day(s) PTO for {name} on {pto_date}.", "success")
    return redirect(url_for("pto.pto_page"))


@bp.route("/pto/adjust", methods=["POST"])
def adjust_pto():
    tm_id = request.form.get("team_member_id")
    adj_days = float(request.form.get("adjustment_days", 0))
    reason = request.form.get("reason", "")
    eff_date = request.form.get("effective_date", date.today().isoformat())

    if not tm_id or adj_days == 0 or not reason:
        flash("Please fill in all fields for the adjustment.", "warning")
        return redirect(url_for("pto.pto_page"))

    db.add_pto_adjustment(tm_id, adj_days, reason, eff_date)

    cat = db.get_employee_category(tm_id)
    name = f"{cat['given_name']} {cat['family_name']}" if cat else tm_id
    sign = "+" if adj_days > 0 else ""
    flash(f"Adjusted PTO for {name}: {sign}{adj_days} days ({reason}).", "success")
    return redirect(url_for("pto.pto_page"))


@bp.route("/pto/import-historical", methods=["POST"])
def import_historical():
    """Import historical PTO data from the V4 spreadsheet (one-time setup)."""
    try:
        result = pto_historical_import.run_import()
        flash(
            f"Imported historical PTO: {result['employees']} employees, "
            f"{result['starting_balance_adjustments']} starting balances, "
            f"{result['weekly_accruals']} weekly accruals, "
            f"{result['days_taken']} days-taken records.",
            "success",
        )
    except Exception as e:
        flash(f"Import failed: {str(e)}", "danger")
    return redirect(url_for("pto.pto_page"))


@bp.route("/pto/recalculate", methods=["POST"])
def recalculate():
    from_date = request.form.get("from_date", "2026-01-05")
    to_date = request.form.get("to_date", date.today().isoformat())

    try:
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()
        count = 0
        total_skipped = 0

        for cat in categories:
            tm_id = cat["team_member_id"]
            result = pto_engine.recalculate_pto(tm_id, from_date, to_date, team_members)
            count += 1
            if isinstance(result, dict):
                total_skipped += result.get("skipped_protected", 0)

        msg = f"Recalculated PTO for {count} employees ({from_date} to {to_date})."
        if total_skipped > 0:
            msg += f" Protected {total_skipped} imported week(s) from V4 spreadsheet."
        flash(msg, "success")
    except Exception as e:
        flash(f"Recalculation failed: {str(e)}", "danger")

    return redirect(url_for("pto.pto_page"))
