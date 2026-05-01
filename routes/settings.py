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
