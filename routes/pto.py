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
    # Also flag salaried staff (excl. UM) with zero accrual — likely a
    # data issue (Square pay_type wrong, or Settings pay_type wrong).
    config_warnings = []
    for emp in summary:
        avg = emp.get("avg_shift") or 8.0
        emp["balance_hours"] = round(emp["balance"] * avg, 1)
        emp["accrued_hours_total"] = round(emp["total_accrued"] * avg, 1)
        emp["taken_hours_total"] = round(emp["total_taken"] * avg, 1)

        cat = next((c for c in categories if c["team_member_id"] == emp["team_member_id"]), None)
        if cat and emp["is_active"] and cat["category"] != "Upper Management":
            local_pt = (cat["pay_type"] or "").lower()
            if local_pt == "salaried" and emp["total_accrued"] == 0:
                config_warnings.append({
                    "name": f"{emp['given_name']} {emp['family_name']}",
                    "issue": "Salaried with zero accrual — recalculate or check pay_type in Settings.",
                })
            elif local_pt == "hourly" and emp["accrual_type"] == "Salaried":
                config_warnings.append({
                    "name": f"{emp['given_name']} {emp['family_name']}",
                    "issue": "Settings says hourly but Square says salaried — pick one.",
                })

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
        config_warnings=config_warnings,
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


@bp.route("/pto/diagnose/<tm_id>")
def diagnose(tm_id):
    """Show raw Square + DB data for one employee, to figure out why
    accruals aren't computing. Surfaces the most common causes:
      - team_member_id mismatch between our DB and Square
      - duplicate Square team members with same name
      - Square member is Inactive (excluded from default sync)
      - genuinely zero timecards (employee isn't clocking in)
    """
    from datetime import datetime as _dt
    try:
        year = int(request.args.get("year", str(date.today().year)))
    except ValueError:
        year = date.today().year

    cat = db.get_employee_category(tm_id)
    given = cat["given_name"] if cat else ""
    family = cat["family_name"] if cat else ""
    full_name = f"{given} {family}".strip().lower()

    # Square: pull ALL team members (any status) to spot duplicates / inactives
    square_members = []
    square_match_by_id = None
    square_name_matches = []
    square_err = None
    try:
        square_members = square_client.get_all_team_members()
        for m in square_members:
            if m["id"] == tm_id:
                square_match_by_id = m
            mname = f"{m['given_name']} {m['family_name']}".strip().lower()
            # Match on first or last name token presence (loose)
            if full_name and mname and (
                given.lower() and given.lower() in mname
                or family.lower() and family.lower() in mname
            ):
                square_name_matches.append(m)
    except Exception as e:
        square_err = str(e)

    # Square timecards for this tm_id in the year
    timecards_year = []
    timecard_err = None
    try:
        timecards_year = [
            tc for tc in square_client.get_timecards(f"{year}-01-01", f"{year}-12-31")
            if tc["team_member_id"] == tm_id
        ]
    except Exception as e:
        timecard_err = str(e)

    # Group timecards by date
    by_date = {}
    for tc in timecards_year:
        try:
            day = _dt.fromisoformat(tc["start_at"].replace("Z", "+00:00")).date().isoformat()
        except Exception:
            continue
        if tc["paid_minutes"] > 0:
            by_date[day] = by_date.get(day, 0) + float(tc["paid_minutes"]) / 60.0

    # PTO accruals saved for this employee
    conn = db.get_db()
    accrual_rows = conn.execute(
        """SELECT period_start, period_end, hours_worked, days_accrued, source
           FROM pto_accruals
           WHERE team_member_id = ? AND strftime('%Y', period_start) = ?
           ORDER BY period_start""",
        (tm_id, str(year)),
    ).fetchall()

    # PTO TAKEN rows for this employee — shows the raw dates and amounts
    # logged. Use this to diagnose 'Holiday Pay column on W18 looks wrong'.
    taken_rows = conn.execute(
        """SELECT date, days_taken, hours_equivalent, reason
           FROM pto_taken
           WHERE team_member_id = ? AND strftime('%Y', date) = ?
           ORDER BY date""",
        (tm_id, str(year)),
    ).fetchall()
    conn.close()

    manual_rows = db.list_manual_hours(tm_id)

    return render_template("pto_diagnose.html",
        tm_id=tm_id,
        year=year,
        cat=cat,
        square_match_by_id=square_match_by_id,
        square_name_matches=[m for m in square_name_matches if m["id"] != tm_id],
        square_err=square_err,
        timecards_year=timecards_year,
        by_date=by_date,
        timecard_err=timecard_err,
        accrual_rows=accrual_rows,
        taken_rows=taken_rows,
        manual_rows=manual_rows,
    )


@bp.route("/pto/relink", methods=["POST"])
def relink_to_square():
    """Move all PTO history from one team_member_id to another. Used when
    the diagnostic shows an employee has been recreated in Square under
    a new ID — we want to pull the PTO history forward."""
    old_id = request.form.get("old_id", "").strip()
    new_id = request.form.get("new_id", "").strip()
    if not old_id or not new_id or old_id == new_id:
        flash("Pick a different new ID to relink to.", "warning")
        return redirect(url_for("pto.pto_page"))

    conn = db.get_db()
    # Move all PTO-related rows
    conn.execute("UPDATE pto_accruals SET team_member_id=? WHERE team_member_id=?", (new_id, old_id))
    conn.execute("UPDATE pto_taken SET team_member_id=? WHERE team_member_id=?", (new_id, old_id))
    conn.execute("UPDATE pto_manual_adjustments SET team_member_id=? WHERE team_member_id=?", (new_id, old_id))
    conn.execute("UPDATE pto_manual_hours SET team_member_id=? WHERE team_member_id=?", (new_id, old_id))
    # Move the employee_categories row too
    cat = conn.execute("SELECT * FROM employee_categories WHERE team_member_id=?", (old_id,)).fetchone()
    if cat:
        conn.execute("DELETE FROM employee_categories WHERE team_member_id=?", (old_id,))
        # Update names from Square if it has them
        member = next((m for m in square_client.get_all_team_members() if m["id"] == new_id), None)
        gn = member["given_name"] if member else cat["given_name"]
        fn = member["family_name"] if member else cat["family_name"]
        conn.execute(
            """INSERT INTO employee_categories
               (team_member_id, given_name, family_name, category, cleaning_amount,
                weekly_salary, pay_type, email, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(team_member_id) DO UPDATE SET
                 given_name=excluded.given_name,
                 family_name=excluded.family_name,
                 category=excluded.category,
                 cleaning_amount=excluded.cleaning_amount,
                 weekly_salary=excluded.weekly_salary,
                 pay_type=excluded.pay_type,
                 is_active=excluded.is_active""",
            (new_id, gn, fn, cat["category"], cat["cleaning_amount"],
             cat["weekly_salary"], cat["pay_type"], cat["email"] if "email" in cat.keys() else None,
             cat["is_active"]),
        )
    conn.commit()
    conn.close()
    flash(f"Relinked from {old_id} to {new_id}. Click Recalculate PTO to refresh.",
          "success")
    return redirect(url_for("pto.diagnose", tm_id=new_id))


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
