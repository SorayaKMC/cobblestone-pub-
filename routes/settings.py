from flask import Blueprint, render_template, request, redirect, url_for, flash
import db
import square_client

bp = Blueprint("settings", __name__)


@bp.route("/settings")
def settings_page():
    categories = db.get_employee_categories()
    return render_template("settings.html", employees=categories)


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
            updates.append({
                "team_member_id": tm_id,
                "given_name": first,
                "family_name": last,
                "category": category,
                "cleaning_amount": cleaning,
                "pay_type": pay_type,
                "weekly_salary": weekly_salary,
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

        count = 0
        for m in members:
            if m["id"] not in existing:
                db.update_employee_category(
                    m["id"], m["given_name"], m["family_name"], "Staff", 0
                )
                count += 1
            else:
                # Update names from Square but keep local category
                row = existing[m["id"]]
                db.update_employee_category(
                    m["id"], m["given_name"], m["family_name"],
                    row["category"], row["cleaning_amount"]
                )

        if count > 0:
            flash(f"Synced from Square. {count} new employee(s) added as Staff.", "success")
        else:
            flash("All employees up to date.", "info")
    except Exception as e:
        flash(f"Sync failed: {str(e)}", "danger")

    return redirect(url_for("settings.settings_page"))
