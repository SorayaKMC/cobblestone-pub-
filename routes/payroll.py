from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from decimal import Decimal
from datetime import date
import io
import os
import re
import secrets
import tempfile
import square_client
import db
import excel_export
import config
import tips_historical_import
import payslip_extractor

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

        # Holiday pay: pull from PTO tracker (auto-sync — no double-entry)
        pto_taken = db.get_pto_taken_for_week(start_date, end_date)

        # Include employees who took PTO but didn't work this week — they still
        # need to appear on payroll so they get paid for the holiday hours.
        existing_ids = {p["team_member_id"] for p in payroll}
        members_by_id = {m["id"]: m for m in team_members}
        cats_by_id = {c["team_member_id"]: c for c in categories}
        for tm_id, pto_d in pto_taken.items():
            if tm_id in existing_ids:
                continue
            if not pto_d.get("hours", 0):
                continue
            cat = cats_by_id.get(tm_id)
            if not cat:
                continue
            member = members_by_id.get(tm_id, {})
            wage_rate = member.get("hourly_rate", Decimal("0"))
            payroll.append({
                "team_member_id": tm_id,
                "given_name": cat["given_name"],
                "family_name": cat["family_name"],
                "wage_rate": wage_rate.quantize(Decimal("0.01")) if hasattr(wage_rate, "quantize") else Decimal(str(wage_rate)),
                "gross": Decimal("0.00"),
                "hours": Decimal("0.00"),
                "tips": Decimal("0.00"),
                "cleaning": Decimal("0.00"),
                "bonus": Decimal("0.00"),
                "total": Decimal("0.00"),
                "category": cat["category"],
                "total_for_labor": Decimal("0.00"),
                "regular_hours": Decimal("0.00"),
                "overtime_hours": Decimal("0.00"),
                "doubletime_hours": Decimal("0.00"),
                "regular_cost": Decimal("0.00"),
                "overtime_cost": Decimal("0.00"),
                "doubletime_cost": Decimal("0.00"),
                "total_cost": Decimal("0.00"),
                "transaction_tips": Decimal("0.00"),
                "declared_cash_tips": Decimal("0.00"),
                "pto_only": True,  # template hint: row is PTO-only
            })
        # Re-sort with the added PTO-only rows
        order = {"Upper Management": 0, "Management": 1, "Staff": 2}
        payroll.sort(key=lambda x: (order.get(x["category"], 9), x["family_name"]))

        for p in payroll:
            pto = pto_taken.get(p["team_member_id"], {})
            p["holiday_hours"] = pto.get("hours", 0.0)
            p["holiday_days"] = pto.get("days", 0.0)

        # Net pay (from accountant's gross-to-net upload, if any)
        net_pays = db.get_net_pays_by_employee(iso_week)
        net_total_accountant = 0.0
        for p in payroll:
            v = net_pays.get(p["team_member_id"])
            p["net_pay_accountant"] = v
            if v is not None:
                net_total_accountant += float(v)

        # Totals
        total_hours = sum(p["hours"] for p in payroll)
        total_gross = sum(p["gross"] for p in payroll)
        total_tips = sum(p["tips"] for p in payroll)
        total_cleaning = sum(p["cleaning"] for p in payroll)
        total_bonus = sum(p["bonus"] for p in payroll)
        grand_total = sum(p["total"] for p in payroll)
        total_labor = sum(p["total_for_labor"] for p in payroll)
        total_holiday_hours = sum(p["holiday_hours"] for p in payroll)

        # Category subtotals
        um_total = sum(p["total_for_labor"] for p in payroll if p["category"] == "Upper Management")
        mgmt_total = sum(p["total_for_labor"] for p in payroll if p["category"] == "Management")
        staff_total = sum(p["total_for_labor"] for p in payroll if p["category"] == "Staff")

        prev_week = f"{year}-W{week-1:02d}" if week > 1 else f"{year-1}-W52"
        next_week = f"{year}-W{week+1:02d}" if week < 52 else f"{year+1}-W01"

        is_finalized = db.is_week_finalized(iso_week)
        has_accountant_data = db.get_pay_period(iso_week) is not None
        error = None
    except Exception as e:
        payroll = []
        total_hours = total_gross = total_tips = total_cleaning = total_bonus = grand_total = total_labor = Decimal("0")
        total_holiday_hours = 0.0
        um_total = mgmt_total = staff_total = Decimal("0")
        prev_week = next_week = iso_week
        is_finalized = False
        has_accountant_data = False
        net_total_accountant = 0.0
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
        total_holiday_hours=total_holiday_hours,
        um_total=um_total,
        mgmt_total=mgmt_total,
        staff_total=staff_total,
        prev_week=prev_week,
        next_week=next_week,
        is_finalized=is_finalized,
        has_accountant_data=has_accountant_data,
        net_total_accountant=net_total_accountant,
        error=error,
    )


@bp.route("/payroll/check-tips", methods=["POST"])
def check_tips():
    """Pull this week's tips from the shared Google Sheet → save into the
    weekly_tips table → flash result. Skipped if week is finalized."""
    import tips_sheet_importer
    iso_week = request.form.get("iso_week", "").strip()
    if not iso_week:
        flash("Missing week.", "danger")
        return redirect(url_for("payroll.payroll_page"))
    if db.is_week_finalized(iso_week):
        flash(f"{iso_week} is finalized — unlock it first to refresh tips.", "warning")
        return redirect(url_for("payroll.payroll_page", week=iso_week))

    result = tips_sheet_importer.import_tips_for_week(iso_week)
    if not result.get("ok"):
        flash(f"Tip import failed: {result.get('error', '?')}", "danger")
        return redirect(url_for("payroll.payroll_page", week=iso_week))

    bits = [
        f"Matched {result['matched_count']} employee(s) totalling "
        f"€{result['matched_total']:.2f} from tab '{result['tab']}'. "
        f"Total column: {result['total_col']}.",
    ]
    if result.get("unmatched"):
        rows = ", ".join(f"{n} (€{v:.2f})" for n, v in result["unmatched"][:8])
        more = "" if len(result["unmatched"]) <= 8 else f" + {len(result['unmatched'])-8} more"
        bits.append(
            f"{len(result['unmatched'])} row(s) didn't match: "
            f"{rows}{more}. Edit the sheet name or add to Settings, then re-run."
        )
    category = "warning" if result.get("unmatched") else "success"
    flash(" ".join(bits), category)
    return redirect(url_for("payroll.payroll_page", week=iso_week))


@bp.route("/payroll/refresh", methods=["POST"])
def refresh_week():
    """Re-pull from Square + recalculate PTO accruals for the selected week.

    The payroll page already pulls fresh timecards on each load, but PTO
    accruals are stored — they only update when a recalculation runs. This
    button re-runs the recalc for ONE week so any backdated Square edits
    flow into the holiday-hours column for that week.
    """
    import pto_engine
    iso_week = request.form.get("iso_week", "").strip()
    if not iso_week or "-W" not in iso_week:
        flash("Missing or invalid week.", "danger")
        return redirect(url_for("payroll.payroll_page"))

    try:
        year_str, week_str = iso_week.split("-W")
        year = int(year_str)
        week_num = int(week_str)
        start_date, end_date = square_client.week_dates(year, week_num)
    except (ValueError, IndexError):
        flash("Invalid week format.", "danger")
        return redirect(url_for("payroll.payroll_page"))

    try:
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()
        recalc_count = 0
        for cat in categories:
            try:
                pto_engine.recalculate_pto(
                    cat["team_member_id"], start_date, end_date, team_members
                )
                recalc_count += 1
            except Exception as e:
                print(f"[payroll-refresh] {cat['family_name']}: {e}")
        flash(
            f"Refreshed {iso_week} from Square. Recalculated PTO for "
            f"{recalc_count} employees.",
            "success",
        )
    except Exception as e:
        flash(f"Refresh failed: {e}", "danger")

    return redirect(url_for("payroll.payroll_page", week=iso_week))


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


# ---------------------------------------------------------------------------
# Accountant uploads (Peter's gross-to-net + payslips PDFs)
# ---------------------------------------------------------------------------

_TITLES = {"mr", "ms", "mrs", "dr", "miss"}


def _strip_titles(parts):
    return [p for p in parts if p.lower().strip(".") not in _TITLES]


def _fuzzy_name_match(raw_name, active_employees):
    """Best-effort match of a payslip name to an employee. Returns tm_id or None.

    The accountant's PDFs format names inconsistently: 'Mr Thomas Mulligan',
    'Mc Mahon Soraya' (surname-first), 'Carlos Manuel Dia Soto' (multi-token).
    """
    if not raw_name:
        return None
    raw_parts = _strip_titles(raw_name.replace("-", " ").split())
    raw_tokens = set(p.lower() for p in raw_parts)
    norm_raw = " ".join(p.lower() for p in raw_parts)

    for emp in active_employees:
        first_last = f"{emp['given_name']} {emp['family_name']}".lower()
        last_first = f"{emp['family_name']} {emp['given_name']}".lower()
        if norm_raw == first_last or norm_raw == last_first:
            return emp["team_member_id"]

    for emp in active_employees:
        emp_tokens = set()
        for field in (emp["given_name"], emp["family_name"]):
            for tok in field.replace("-", " ").split():
                emp_tokens.add(tok.lower())
        if raw_tokens and (raw_tokens == emp_tokens or
                           raw_tokens.issubset(emp_tokens) or
                           emp_tokens.issubset(raw_tokens)):
            return emp["team_member_id"]
    return None


def _build_accountant_view_model(period):
    """Assemble the data needed to render payroll_accountant.html."""
    if not period:
        return {"period": None, "rows": [], "all_resolved": False}

    nets = db.get_pay_period_nets(period["id"])
    payslips = db.get_pay_period_payslips(period["id"])
    payslip_refs = {p["ref_no"] for p in payslips}

    active_employees = [r for r in db.get_employee_categories() if r["is_active"]]
    employees_options = sorted(
        [{"id": e["team_member_id"], "name": f"{e['given_name']} {e['family_name']}", "category": e["category"]}
         for e in active_employees],
        key=lambda x: x["name"],
    )

    rows = []
    for n in nets:
        rows.append({
            "ref": n["ref_no"],
            "raw_name": n["raw_name"],
            "team_member_id": n["team_member_id"],
            "gross_pay": n["gross_pay"],
            "net_pay": n["net_pay"],
            "has_payslip": n["ref_no"] in payslip_refs,
        })

    all_resolved = all(r["team_member_id"] for r in rows) and bool(rows)
    return {
        "period": period,
        "rows": rows,
        "employees": employees_options,
        "all_resolved": all_resolved,
    }


@bp.route("/payroll/accountant", methods=["GET"])
def accountant_page():
    year, week, start_date, end_date, label, iso_week = _get_week_params()
    period = db.get_pay_period(iso_week)
    vm = _build_accountant_view_model(period)

    drafts = db.get_email_drafts(period["id"]) if period else []
    drafts_by_tm = {d["team_member_id"]: d for d in drafts}
    for r in vm["rows"]:
        d = drafts_by_tm.get(r["team_member_id"])
        r["draft_status"] = d["status"] if d else None
        r["draft_id"] = d["gmail_draft_id"] if d else None
        r["draft_email"] = d["email"] if d else None
        r["draft_error"] = d["error"] if d else None

    return render_template("payroll_accountant.html",
        iso_week=iso_week,
        week_label=label,
        **vm,
    )


@bp.route("/payroll/accountant/upload", methods=["POST"])
def accountant_upload():
    gtn_file = request.files.get("gross_to_net")
    payslips_file = request.files.get("payslips")

    fallback_iso = request.form.get("iso_week") or _get_week_params()[5]

    if not gtn_file or not gtn_file.filename:
        flash("Please upload the Gross-to-Net PDF.", "danger")
        return redirect(url_for("payroll.accountant_page", week=fallback_iso))
    if not payslips_file or not payslips_file.filename:
        flash("Please upload the combined payslips PDF.", "danger")
        return redirect(url_for("payroll.accountant_page", week=fallback_iso))

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as gf:
        gtn_file.save(gf.name)
        gtn_path = gf.name
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pf:
        payslips_file.save(pf.name)
        slips_path = pf.name

    try:
        gtn = payslip_extractor.parse_gross_to_net(gtn_path)
        slips = payslip_extractor.split_payslips(slips_path)
    except Exception as e:
        flash(f"Could not parse PDFs: {e}", "danger")
        return redirect(url_for("payroll.accountant_page", week=fallback_iso))
    finally:
        try: os.unlink(gtn_path)
        except OSError: pass
        try: os.unlink(slips_path)
        except OSError: pass

    if not gtn["rows"]:
        flash("No employee rows found in the gross-to-net PDF.", "danger")
        return redirect(url_for("payroll.accountant_page", week=fallback_iso))

    week_num, pay_date, year_parsed = payslip_extractor.parse_period_label(gtn["period_label"])
    if not pay_date:
        flash("Could not read the pay period from the gross-to-net PDF.", "danger")
        return redirect(url_for("payroll.accountant_page", week=fallback_iso))

    iso_week_actual = f"{year_parsed}-W{week_num:02d}"
    try:
        _, period_end = square_client.week_dates(year_parsed, week_num)
    except Exception:
        period_end = payslip_extractor.period_end_from_pay_date(pay_date)

    saved_map = db.get_ref_mappings()
    active_employees = [r for r in db.get_employee_categories() if r["is_active"]]

    auto_count = 0
    for row in gtn["rows"]:
        ref = row["ref"]
        tm_id = saved_map.get(ref)
        if not tm_id:
            tm_id = _fuzzy_name_match(row["raw_name"], active_employees)
        row["team_member_id"] = tm_id
        if tm_id:
            auto_count += 1

    slip_by_ref = {s["ref"]: s for s in slips}
    for ref, tm_id in [(r["ref"], r["team_member_id"]) for r in gtn["rows"]]:
        if ref in slip_by_ref:
            slip_by_ref[ref]["team_member_id"] = tm_id

    period_id = db.upsert_pay_period(
        iso_week_actual, week_num, year_parsed, pay_date, period_end, gtn["period_label"]
    )
    db.replace_pay_period_nets(period_id, gtn["rows"])
    db.replace_pay_period_payslips(period_id, list(slip_by_ref.values()))

    total = len(gtn["rows"])
    if auto_count == total:
        flash(f"Uploaded {total} employees for {iso_week_actual} — all auto-mapped.", "success")
    else:
        flash(
            f"Uploaded {total} employees for {iso_week_actual}. "
            f"{auto_count} auto-mapped, {total - auto_count} need review below.",
            "warning",
        )
    return redirect(url_for("payroll.accountant_page", week=iso_week_actual))


@bp.route("/payroll/accountant/save", methods=["POST"])
def accountant_save():
    period_id = int(request.form.get("pay_period_id", 0) or 0)
    if not period_id:
        flash("Missing pay period.", "danger")
        return redirect(url_for("payroll.accountant_page"))

    period = db.get_pay_period_by_id(period_id)
    if not period:
        flash("Pay period not found.", "danger")
        return redirect(url_for("payroll.accountant_page"))

    mappings = {}
    nets_existing = db.get_pay_period_nets(period_id)
    raw_by_ref = {n["ref_no"]: n["raw_name"] for n in nets_existing}

    for key, value in request.form.items():
        if key.startswith("map_"):
            ref = key.replace("map_", "")
            tm_id = (value or "").strip() or None
            mappings[ref] = (tm_id, raw_by_ref.get(ref))

    persistent = {ref: pair for ref, pair in mappings.items() if pair[0]}
    if persistent:
        db.save_ref_mappings(persistent)

    conn = db.get_db()
    for ref, (tm_id, _) in mappings.items():
        conn.execute(
            "UPDATE pay_period_nets SET team_member_id=? WHERE pay_period_id=? AND ref_no=?",
            (tm_id, period_id, ref),
        )
        conn.execute(
            "UPDATE pay_period_payslips SET team_member_id=? WHERE pay_period_id=? AND ref_no=?",
            (tm_id, period_id, ref),
        )
    conn.commit()
    conn.close()

    flash("Mappings saved.", "success")
    return redirect(url_for("payroll.accountant_page", week=period["iso_week"]))


@bp.route("/payroll/accountant/test-gmail", methods=["POST"])
def accountant_test_gmail():
    """Create a self-addressed test draft to verify the Gmail integration."""
    fallback_iso = request.form.get("iso_week") or _get_week_params()[5]
    try:
        import payroll_drafts
        draft_id, err = payroll_drafts.create_test_draft()
    except Exception as e:
        flash(f"Gmail test failed: {e}", "danger")
        return redirect(url_for("payroll.accountant_page", week=fallback_iso))

    if err:
        flash(f"Gmail test failed: {err}", "danger")
    else:
        flash(
            "Gmail test draft created in info@cobblestonepub.ie. "
            "Open Gmail Drafts to confirm — safe to delete.",
            "success",
        )
    return redirect(url_for("payroll.accountant_page", week=fallback_iso))


@bp.route("/payroll/accountant/generate-drafts", methods=["POST"])
def accountant_generate_drafts():
    period_id = int(request.form.get("pay_period_id", 0) or 0)
    if not period_id:
        flash("Missing pay period.", "danger")
        return redirect(url_for("payroll.accountant_page"))
    period = db.get_pay_period_by_id(period_id)
    if not period:
        flash("Pay period not found.", "danger")
        return redirect(url_for("payroll.accountant_page"))

    try:
        import payroll_drafts
        result = payroll_drafts.generate_drafts_for_period(period_id)
    except Exception as e:
        flash(f"Could not create drafts: {e}", "danger")
        return redirect(url_for("payroll.accountant_page", week=period["iso_week"]))

    summary_bits = []
    if result["created"]:
        summary_bits.append(f"{result['created']} draft(s) created")
    if result["skipped"]:
        summary_bits.append(f"{result['skipped']} skipped")
    if result["failed"]:
        summary_bits.append(f"{result['failed']} failed")
    flash(
        ("Drafts generated for " + period["iso_week"] + ": "
         + ", ".join(summary_bits)
         + ". Open Gmail Drafts to review."),
        "success" if not result["failed"] else "warning",
    )
    return redirect(url_for("payroll.accountant_page", week=period["iso_week"]))


@bp.route("/payroll/accountant/payslip/<int:period_id>/<ref>")
def accountant_payslip(period_id, ref):
    row = db.get_payslip_blob_by_ref(period_id, ref)
    if not row:
        flash("Payslip not found.", "danger")
        return redirect(url_for("payroll.accountant_page"))
    period = db.get_pay_period_by_id(period_id)
    safe_name = re.sub(r"[^\w-]", "_", row["raw_name"])
    filename = f"Payslip_{safe_name}_W{period['week_num']:02d}_{period['year']}.pdf"
    return send_file(
        io.BytesIO(row["pdf_blob"]),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
    )


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
