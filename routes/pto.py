from flask import Blueprint, render_template, request, redirect, url_for, flash
from decimal import Decimal
from datetime import date, datetime
import db
import square_client
import pto_engine

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

    categories = db.get_employee_categories()
    employees = [{"id": r["team_member_id"], "name": f"{r['given_name']} {r['family_name']}"} for r in categories]

    taken_log = db.get_pto_taken_log()

    return render_template("pto.html",
        summary=summary,
        employees=employees,
        taken_log=taken_log,
        today=date.today().isoformat(),
    )


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


@bp.route("/pto/recalculate", methods=["POST"])
def recalculate():
    from_date = request.form.get("from_date", "2026-01-05")
    to_date = request.form.get("to_date", date.today().isoformat())

    try:
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()
        count = 0

        for cat in categories:
            tm_id = cat["team_member_id"]
            pto_engine.recalculate_pto(tm_id, from_date, to_date, team_members)
            count += 1

        flash(f"Recalculated PTO for {count} employees ({from_date} to {to_date}).", "success")
    except Exception as e:
        flash(f"Recalculation failed: {str(e)}", "danger")

    return redirect(url_for("pto.pto_page"))
