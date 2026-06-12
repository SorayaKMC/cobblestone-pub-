from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from io import BytesIO
import re
import zipfile
import db
import square_client

bp = Blueprint("settings", __name__)


@bp.route("/settings")
def settings_page():
    categories = db.get_employee_categories()
    # Per-employee payslip counts so each row can show a badge.
    payslip_counts = {
        c["team_member_id"]: db.count_payslips_for_employee(c["team_member_id"])
        for c in categories
    }
    return render_template(
        "settings.html",
        employees=categories,
        payslip_counts=payslip_counts,
    )


def _safe_filename_component(s):
    """Strip characters that confuse filesystems / Content-Disposition."""
    if not s:
        return ""
    s = re.sub(r"[^A-Za-z0-9._\- ]+", "_", s).strip()
    return s.replace(" ", "_")


@bp.route("/settings/employees/<team_member_id>/payslips.zip")
def download_employee_payslips(team_member_id):
    """Bundle payslip PDFs for one employee into a single .zip download.
    Optional query params ?from=YYYY-MM-DD & ?to=YYYY-MM-DD filter by
    pay_date inclusive. Files inside the zip are named with the pay
    week so they sort chronologically when extracted."""
    cat = db.get_employee_category(team_member_id)
    if not cat:
        abort(404)

    start_date = (request.args.get("from") or "").strip() or None
    end_date = (request.args.get("to") or "").strip() or None
    start_iso_week = (request.args.get("from_week") or "").strip() or None
    end_iso_week = (request.args.get("to_week") or "").strip() or None

    payslips = db.get_payslips_for_employee(
        team_member_id,
        start_date=start_date, end_date=end_date,
        start_iso_week=start_iso_week, end_iso_week=end_iso_week,
    )
    if not payslips:
        if start_date or end_date or start_iso_week or end_iso_week:
            flash(
                f"No payslips for {cat['given_name']} {cat['family_name']} "
                f"in that range.", "warning",
            )
        else:
            flash(
                f"No payslips on file for {cat['given_name']} {cat['family_name']}.",
                "warning",
            )
        return redirect(url_for("settings.settings_page"))

    employee_label = _safe_filename_component(
        f"{cat['given_name']}_{cat['family_name']}"
    ) or "employee"

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for slip in payslips:
            week_label = slip["iso_week"] or ""  # e.g. 2026-W22
            pdf_filename = f"Payslip_{employee_label}_{week_label}.pdf"
            zf.writestr(pdf_filename, bytes(slip["pdf_blob"]))

    # Include range in the download filename if filtered, so multiple
    # downloads for the same person don't overwrite each other.
    range_suffix = ""
    if start_iso_week and end_iso_week:
        range_suffix = f"_{start_iso_week}_to_{end_iso_week}"
    elif start_iso_week:
        range_suffix = f"_from_{start_iso_week}"
    elif end_iso_week:
        range_suffix = f"_to_{end_iso_week}"
    elif start_date and end_date:
        range_suffix = f"_{start_date}_to_{end_date}"
    elif start_date:
        range_suffix = f"_from_{start_date}"
    elif end_date:
        range_suffix = f"_to_{end_date}"

    buf.seek(0)
    return send_file(
        buf,
        download_name=f"{employee_label}_payslips{range_suffix}.zip",
        as_attachment=True,
        mimetype="application/zip",
    )


@bp.route("/settings/categories", methods=["POST"])
def save_categories():
    updates = []
    for key in request.form:
        if key.startswith("category_"):
            tm_id = key.replace("category_", "")
            first = request.form.get(f"first_{tm_id}", "")
            last = request.form.get(f"last_{tm_id}", "")
            category = request.form[key]
            cleaning = float(request.form.get(f"cleaning_{tm_id}", 0) or 0)
            pay_type = request.form.get(f"paytype_{tm_id}", "hourly")
            weekly_salary = float(request.form.get(f"salary_{tm_id}", 0) or 0)
            is_active = 0 if request.form.get(f"former_{tm_id}") else 1
            email = (request.form.get(f"email_{tm_id}", "") or "").strip() or None
            updates.append({
                "team_member_id": tm_id,
                "given_name": first,
                "family_name": last,
                "category": category,
                "cleaning_amount": cleaning,
                "pay_type": pay_type,
                "weekly_salary": weekly_salary,
                "email": email,
                "is_active": is_active,
            })
    if updates:
        db.bulk_update_categories(updates)
        flash("Categories saved.", "success")
    return redirect(url_for("settings.settings_page"))


@bp.route("/settings/sync", methods=["POST"])
def sync_team():
    try:
        members = square_client.get_team_members()
        existing = {r["team_member_id"]: r for r in db.get_employee_categories()}

        added = 0
        emails_pulled = 0
        for m in members:
            email = m.get("email_address") or None
            if email:
                emails_pulled += 1
            if m["id"] not in existing:
                db.update_employee_category(
                    m["id"], m["given_name"], m["family_name"], "Staff",
                    cleaning_amount=0, email=email,
                )
                added += 1
            else:
                row = existing[m["id"]]
                # Square is source of truth for names + email; preserve local
                # category, cleaning, salary, pay type so manual edits aren't lost.
                db.update_employee_category(
                    m["id"], m["given_name"], m["family_name"],
                    row["category"],
                    cleaning_amount=row["cleaning_amount"],
                    weekly_salary=row["weekly_salary"] if "weekly_salary" in row.keys() else 0,
                    pay_type=row["pay_type"] if "pay_type" in row.keys() else "hourly",
                    email=email,
                )

        msg_bits = []
        if added:
            msg_bits.append(f"{added} new employee(s) added as Staff")
        msg_bits.append(f"{emails_pulled} email(s) synced from Square")
        if not added:
            msg_bits.insert(0, "All employees up to date")
        flash("Synced from Square. " + ". ".join(msg_bits) + ".", "success")
    except Exception as e:
        flash(f"Sync failed: {str(e)}", "danger")

    return redirect(url_for("settings.settings_page"))
