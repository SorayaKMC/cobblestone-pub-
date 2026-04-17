from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from decimal import Decimal
from datetime import date
import secrets
import square_client
import db
import excel_export
import config
import tips_historical_import

bp = Blueprint("payroll", __name__)


def _get_week_params():
    """Parse week from query params. Returns (year, week_num, start_date, end_date, label)."""
    year, week = square_client.current_week()
    week_param = request.args.get("week")
    if week_param:
        try:
            parts = week_param.split("-W")
            year = int(parts[0])
            week = int(parts[1])
        except (ValueError, IndexError):
            pass

    start_date, end_date = square_client.week_dates(year, week)
    label = f"Week {week}"
    iso_week = f"{year}-W{week:02d}"
    return year, week, start_date, end_date, label, iso_week


def _build_payroll_data(timecards, team_members, categories, manual_tips=None, weekly_cleaning=None, weekly_bonus=None):
    """Assemble payroll data from timecards + manual tips/cleaning/bonus.

    Tips, cleaning, and bonus are all entered manually (not from Square).
    All three flow into the Total column and total_for_labor.

    Returns list of employee payroll dicts sorted by category then name.
    """
    if manual_tips is None:
        manual_tips = {}
    if weekly_cleaning is None:
        weekly_cleaning = {}
    if weekly_bonus is None:
        weekly_bonus = {}

    # Index team members and categories
    members_by_id = {m["id"]: m for m in team_members}
    cats_by_id = {r["team_member_id"]: r for r in categories}

    # Aggregate timecards per employee (hours only - tips are manual)
    employee_hours = {}
    for tc in timecards:
        tm_id = tc["team_member_id"]
        if tm_id not in employee_hours:
            employee_hours[tm_id] = {
                "regular": Decimal("0"),
                "overtime": Decimal("0"),
                "doubletime": Decimal("0"),
                "total": Decimal("0"),
            }

        employee_hours[tm_id]["regular"] += tc["regular_hours"]
        employee_hours[tm_id]["overtime"] += tc["overtime_hours"]
        employee_hours[tm_id]["doubletime"] += tc["doubletime_hours"]
        employee_hours[tm_id]["total"] += tc["regular_hours"] + tc["overtime_hours"] + tc["doubletime_hours"]

    # Include salaried employees who may not have timecards (e.g. Upper Management)
    for cat_row in categories:
        tm_id = cat_row["team_member_id"]
        if tm_id not in employee_hours and cat_row["pay_type"] == "salaried" and cat_row["weekly_salary"] > 0:
            employee_hours[tm_id] = {
                "regular": Decimal("0"),
                "overtime": Decimal("0"),
                "doubletime": Decimal("0"),
                "total": Decimal("0"),
            }

    # Include anyone who has manual tips/bonus entered (even if no timecards/salary)
    for tm_id in list(manual_tips.keys()) + list(weekly_bonus.keys()):
        if tm_id not in employee_hours:
            employee_hours[tm_id] = {
                "regular": Decimal("0"),
                "overtime": Decimal("0"),
                "doubletime": Decimal("0"),
                "total": Decimal("0"),
            }

    # Build payroll rows
    payroll = []
    for tm_id, hours in employee_hours.items():
        member = members_by_id.get(tm_id, {})
        cat_row = cats_by_id.get(tm_id)

        given_name = member.get("given_name", cat_row["given_name"] if cat_row else "Unknown")
        family_name = member.get("family_name", cat_row["family_name"] if cat_row else "")
        category = cat_row["category"] if cat_row else "Staff"

        # Cleaning: weekly override > employee default > 0
        default_cleaning = Decimal(str(cat_row["cleaning_amount"])) if cat_row else Decimal("0")
        if tm_id in weekly_cleaning:
            cleaning = Decimal(str(weekly_cleaning[tm_id]))
        else:
            cleaning = default_cleaning

        pay_type = cat_row["pay_type"] if cat_row else "hourly"
        weekly_salary = Decimal(str(cat_row["weekly_salary"])) if cat_row else Decimal("0")

        wage_rate = member.get("hourly_rate", Decimal("0"))

        # Salaried staff: use fixed weekly salary for gross, not hours x rate
        if pay_type == "salaried" and weekly_salary > 0:
            gross = weekly_salary
        else:
            gross = hours["total"] * wage_rate

        # Tips and bonus are manually entered (never from Square)
        tips = Decimal(str(manual_tips.get(tm_id, 0) or 0))
        bonus = Decimal(str(weekly_bonus.get(tm_id, 0) or 0))
        total = gross + tips + cleaning + bonus
        total_for_labor = gross + cleaning + bonus

        payroll.append({
            "team_member_id": tm_id,
            "given_name": given_name,
            "family_name": family_name,
            "wage_rate": wage_rate.quantize(Decimal("0.01")),
            "gross": gross.quantize(Decimal("0.01")),
            "hours": hours["total"].quantize(Decimal("0.01")),
            "tips": tips.quantize(Decimal("0.01")),
            "cleaning": cleaning.quantize(Decimal("0.01")),
            "bonus": bonus.quantize(Decimal("0.01")),
            "total": total.quantize(Decimal("0.01")),
            "category": category,
            "total_for_labor": total_for_labor.quantize(Decimal("0.01")),
            "regular_hours": hours["regular"].quantize(Decimal("0.01")),
            "overtime_hours": hours["overtime"].quantize(Decimal("0.01")),
            "doubletime_hours": hours["doubletime"].quantize(Decimal("0.01")),
            "regular_cost": (hours["regular"] * wage_rate).quantize(Decimal("0.01")),
            "overtime_cost": (hours["overtime"] * wage_rate * Decimal("1.5")).quantize(Decimal("0.01")),
            "doubletime_cost": (hours["doubletime"] * wage_rate * Decimal("2")).quantize(Decimal("0.01")),
            "total_cost": gross.quantize(Decimal("0.01")),
            "transaction_tips": Decimal("0"),
            "declared_cash_tips": tips.quantize(Decimal("0.01")),
        })

    # Sort: Upper Management first, then Management, then Staff
    order = {"Upper Management": 0, "Management": 1, "Staff": 2}
    payroll.sort(key=lambda x: (order.get(x["category"], 9), x["family_name"]))

    return payroll


@bp.route("/payroll")
def payroll_page():
    year, week, start_date, end_date, label, iso_week = _get_week_params()

    try:
        timecards = square_client.get_timecards(start_date, end_date)
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()
        manual_tips = db.get_weekly_tips(iso_week)
        weekly_cleaning = db.get_weekly_cleaning(iso_week)
        weekly_bonus = db.get_weekly_bonus(iso_week)

        payroll = _build_payroll_data(timecards, team_members, categories, manual_tips, weekly_cleaning, weekly_bonus)

        # Totals
        total_hours = sum(p["hours"] for p in payroll)
        total_gross = sum(p["gross"] for p in payroll)
        total_tips = sum(p["tips"] for p in payroll)
        total_cleaning = sum(p["cleaning"] for p in payroll)
        total_bonus = sum(p["bonus"] for p in payroll)
        grand_total = sum(p["total"] for p in payroll)
        total_labor = sum(p["total_for_labor"] for p in payroll)

        # Category subtotals
        um_total = sum(p["total_for_labor"] for p in payroll if p["category"] == "Upper Management")
        mgmt_total = sum(p["total_for_labor"] for p in payroll if p["category"] == "Management")
        staff_total = sum(p["total_for_labor"] for p in payroll if p["category"] == "Staff")

        prev_week = f"{year}-W{week-1:02d}" if week > 1 else f"{year-1}-W52"
        next_week = f"{year}-W{week+1:02d}" if week < 52 else f"{year+1}-W01"

        is_finalized = db.is_week_finalized(iso_week)
        error = None
    except Exception as e:
        payroll = []
        total_hours = total_gross = total_tips = total_cleaning = total_bonus = grand_total = total_labor = Decimal("0")
        um_total = mgmt_total = staff_total = Decimal("0")
        prev_week = next_week = iso_week
        is_finalized = False
        error = str(e)

    return render_template("payroll.html",
        payroll=payroll,
        week_label=label,
        iso_week=iso_week,
        start_date=start_date if not error else "",
        end_date=end_date if not error else "",
        total_hours=total_hours,
        total_gross=total_gross,
        total_tips=total_tips,
        total_cleaning=total_cleaning,
        total_bonus=total_bonus,
        grand_total=grand_total,
        total_labor=total_labor,
        um_total=um_total,
        mgmt_total=mgmt_total,
        staff_total=staff_total,
        prev_week=prev_week,
        next_week=next_week,
        is_finalized=is_finalized,
        error=error,
    )


@bp.route("/payroll/tips", methods=["POST"])
def save_tips():
    """Save manually-entered tips + cleaning for a week. Blocked if week finalized."""
    iso_week = request.form.get("iso_week")
    if not iso_week:
        flash("Missing week.", "danger")
        return redirect(url_for("payroll.payroll_page"))

    if db.is_week_finalized(iso_week):
        flash(f"{iso_week} is finalized. Unlock it first to make changes.", "warning")
        return redirect(url_for("payroll.payroll_page", week=iso_week))

    tips_by_employee = {}
    cleaning_by_employee = {}
    bonus_by_employee = {}
    for key in request.form:
        if key.startswith("tip_"):
            tm_id = key.replace("tip_", "")
            try:
                tips_by_employee[tm_id] = float(request.form[key] or 0)
            except (ValueError, TypeError):
                tips_by_employee[tm_id] = 0
        elif key.startswith("clean_"):
            tm_id = key.replace("clean_", "")
            try:
                cleaning_by_employee[tm_id] = float(request.form[key] or 0)
            except (ValueError, TypeError):
                cleaning_by_employee[tm_id] = 0
        elif key.startswith("bonus_"):
            tm_id = key.replace("bonus_", "")
            try:
                bonus_by_employee[tm_id] = float(request.form[key] or 0)
            except (ValueError, TypeError):
                bonus_by_employee[tm_id] = 0

    if tips_by_employee:
        db.bulk_set_weekly_tips(iso_week, tips_by_employee)
    if cleaning_by_employee:
        db.bulk_set_weekly_cleaning(iso_week, cleaning_by_employee)
    if bonus_by_employee:
        db.bulk_set_weekly_bonus(iso_week, bonus_by_employee)

    flash(f"Tips, cleaning & bonus saved for {iso_week}.", "success")
    return redirect(url_for("payroll.payroll_page", week=iso_week))


@bp.route("/payroll/import-tips", methods=["POST"])
def import_tips():
    """One-time import of historical tips from the V1 tips spreadsheet."""
    try:
        result = tips_historical_import.run_import()
        flash(
            f"Imported tips for {result['weeks']} weeks ({result['records']} records).",
            "success",
        )
    except Exception as e:
        flash(f"Tips import failed: {str(e)}", "danger")
    return redirect(url_for("payroll.payroll_page"))


@bp.route("/payroll/finalize", methods=["POST"])
def finalize():
    iso_week = request.form.get("iso_week")
    if not iso_week:
        flash("Missing week.", "danger")
        return redirect(url_for("payroll.payroll_page"))
    db.finalize_week(iso_week, finalized_by=config.AUTH_USERNAME or "local")
    flash(f"{iso_week} finalized. Tips and cleaning are now locked.", "success")
    return redirect(url_for("payroll.payroll_page", week=iso_week))


@bp.route("/payroll/unlock", methods=["POST"])
def unlock():
    iso_week = request.form.get("iso_week")
    admin_pw = request.form.get("admin_password", "")
    if not iso_week:
        flash("Missing week.", "danger")
        return redirect(url_for("payroll.payroll_page"))
    if not secrets.compare_digest(admin_pw, config.ADMIN_PASSWORD):
        flash("Incorrect admin password. Week remains locked.", "danger")
        return redirect(url_for("payroll.payroll_page", week=iso_week))
    db.unfinalize_week(iso_week)
    flash(f"{iso_week} unlocked. You can edit it now.", "success")
    return redirect(url_for("payroll.payroll_page", week=iso_week))


@bp.route("/payroll/download/peter")
def download_peter():
    year, week, start_date, end_date, label, iso_week = _get_week_params()

    try:
        timecards = square_client.get_timecards(start_date, end_date)
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()
        manual_tips = db.get_weekly_tips(iso_week)
        weekly_cleaning = db.get_weekly_cleaning(iso_week)
        weekly_bonus = db.get_weekly_bonus(iso_week)
        payroll = _build_payroll_data(timecards, team_members, categories, manual_tips, weekly_cleaning, weekly_bonus)

        # Get sales for the summary
        try:
            sales = square_client.get_weekly_sales(start_date, end_date)
            net_sales = sales["total_sales"]
        except Exception:
            net_sales = None

        buf = excel_export.generate_peter_excel(label, payroll, net_sales)
        filename = f"Cobblestone_{label.replace(' ', '_')}_for_Peter.xlsx"
        return send_file(buf, download_name=filename, as_attachment=True,
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        flash(f"Export failed: {str(e)}", "danger")
        return payroll_page()


@bp.route("/payroll/download/raw")
def download_raw():
    year, week, start_date, end_date, label, iso_week = _get_week_params()

    try:
        timecards = square_client.get_timecards(start_date, end_date)
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()
        manual_tips = db.get_weekly_tips(iso_week)
        weekly_cleaning = db.get_weekly_cleaning(iso_week)
        weekly_bonus = db.get_weekly_bonus(iso_week)
        payroll = _build_payroll_data(timecards, team_members, categories, manual_tips, weekly_cleaning, weekly_bonus)

        raw_data = [{
            "employee_id": p["given_name"] + " " + p["family_name"],
            "given_name": p["given_name"],
            "family_name": p["family_name"],
            "regular_hours": p["regular_hours"],
            "overtime_hours": p["overtime_hours"],
            "doubletime_hours": p["doubletime_hours"],
            "total_hours": p["hours"],
            "regular_cost": p["regular_cost"],
            "overtime_cost": p["overtime_cost"],
            "doubletime_cost": p["doubletime_cost"],
            "total_cost": p["total_cost"],
            "transaction_tips": p["transaction_tips"],
            "declared_cash_tips": p["declared_cash_tips"],
        } for p in payroll]

        buf = excel_export.generate_raw_timecard_excel(label, raw_data)
        filename = f"Cobblestone_{label.replace(' ', '_')}_Timecards.xlsx"
        return send_file(buf, download_name=filename, as_attachment=True,
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        flash(f"Export failed: {str(e)}", "danger")
        return payroll_page()
