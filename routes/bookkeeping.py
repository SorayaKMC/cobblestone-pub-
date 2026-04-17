"""Bookkeeping routes - invoice tracking + supplier management."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import date, datetime
import os
import db
import config
import invoice_extractor

bp = Blueprint("bookkeeping", __name__)


@bp.route("/bookkeeping")
def bookkeeping_page():
    # Filters
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    supplier_id = request.args.get("supplier_id", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "")

    supplier_id_int = int(supplier_id) if supplier_id.isdigit() else None
    status_filter = status if status else None

    invoices = db.list_invoices(
        start_date=start_date or None,
        end_date=end_date or None,
        supplier_id=supplier_id_int,
        category=category or None,
        status=status_filter,
    )
    suppliers = db.list_suppliers()

    # Aggregates
    total_net = sum((inv["net_amount"] or 0) for inv in invoices)
    total_vat = sum((inv["vat_amount"] or 0) for inv in invoices)
    total_gross = sum((inv["total_amount"] or 0) for inv in invoices)

    # Current year monthly VAT totals
    today = date.today()
    monthly = db.monthly_vat_totals(today.year)

    return render_template(
        "bookkeeping.html",
        invoices=invoices,
        suppliers=suppliers,
        categories=config.INVOICE_CATEGORIES,
        total_net=total_net,
        total_vat=total_vat,
        total_gross=total_gross,
        monthly=monthly,
        current_year=today.year,
        filter_start=start_date,
        filter_end=end_date,
        filter_supplier=supplier_id,
        filter_category=category,
        filter_status=status,
        today=today.isoformat(),
    )


@bp.route("/bookkeeping/new", methods=["GET", "POST"])
def new_invoice():
    if request.method == "GET":
        suppliers = db.list_suppliers()
        return render_template(
            "invoice_form.html",
            invoice=None,
            suppliers=suppliers,
            categories=config.INVOICE_CATEGORIES,
            today=date.today().isoformat(),
        )

    # POST - save
    try:
        data = _parse_invoice_form(request.form)
        invoice_id = db.save_invoice(data)
        if data.get("supplier_id") and data.get("category"):
            db.update_supplier_category(data["supplier_id"], data["category"])
        flash(f"Invoice saved (#{invoice_id}).", "success")
    except Exception as e:
        flash(f"Could not save invoice: {e}", "danger")
    return redirect(url_for("bookkeeping.bookkeeping_page"))


@bp.route("/bookkeeping/<int:invoice_id>/edit", methods=["GET", "POST"])
def edit_invoice(invoice_id):
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        flash("Invoice not found.", "danger")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    if request.method == "GET":
        suppliers = db.list_suppliers()
        return render_template(
            "invoice_form.html",
            invoice=invoice,
            suppliers=suppliers,
            categories=config.INVOICE_CATEGORIES,
            today=date.today().isoformat(),
        )

    try:
        data = _parse_invoice_form(request.form)
        db.save_invoice(data, invoice_id=invoice_id)
        if data.get("supplier_id") and data.get("category"):
            db.update_supplier_category(data["supplier_id"], data["category"])
        flash("Invoice updated.", "success")
    except Exception as e:
        flash(f"Could not update invoice: {e}", "danger")
    return redirect(url_for("bookkeeping.bookkeeping_page"))


@bp.route("/bookkeeping/<int:invoice_id>/delete", methods=["POST"])
def delete_invoice(invoice_id):
    db.delete_invoice(invoice_id)
    flash(f"Invoice #{invoice_id} deleted.", "info")
    return redirect(url_for("bookkeeping.bookkeeping_page"))


# --- PDF upload + AI extraction ---

@bp.route("/bookkeeping/upload", methods=["POST"])
def upload_invoices():
    """Upload one or more PDFs. Each gets extracted by Claude, saved as pending."""
    files = request.files.getlist("pdfs")
    if not files:
        flash("No files uploaded.", "warning")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    saved = 0
    skipped = 0
    errors = []
    for upload in files:
        if not upload.filename:
            continue
        if not upload.filename.lower().endswith(".pdf"):
            errors.append(f"{upload.filename}: not a PDF")
            continue
        try:
            path = invoice_extractor.save_uploaded_pdf(upload)

            # Dedupe by file hash before burning an API call
            file_hash_val = invoice_extractor.file_hash(path)
            existing = [i for i in db.list_invoices() if i["file_hash"] == file_hash_val]
            if existing:
                os.remove(path)
                skipped += 1
                continue

            data = invoice_extractor.extract_invoice(path)
            db.save_invoice({
                "supplier_id": data.get("supplier_id"),
                "supplier_name": data.get("supplier_name_canonical") or data.get("supplier_name") or "Unknown",
                "invoice_date": data.get("invoice_date") or date.today().isoformat(),
                "invoice_number": data.get("invoice_number"),
                "net_amount": float(data.get("net_amount") or 0),
                "vat_amount": float(data.get("vat_amount") or 0),
                "total_amount": float(data.get("total_amount") or 0),
                "vat_rate": float(data.get("vat_rate") or 23),
                "category": data.get("category"),
                "source": "pdf_upload",
                "pdf_path": data.get("pdf_path"),
                "file_hash": data.get("file_hash"),
                "status": "pending",
                "notes": f"AI confidence: {data.get('confidence', 'unknown')}",
            })
            saved += 1
        except Exception as e:
            errors.append(f"{upload.filename}: {e}")

    msg_parts = []
    if saved:
        msg_parts.append(f"{saved} invoice(s) extracted - review on the 'Pending' filter")
    if skipped:
        msg_parts.append(f"{skipped} skipped (already uploaded)")
    if errors:
        msg_parts.append(f"{len(errors)} failed")
    flash(" · ".join(msg_parts) if msg_parts else "No changes.", "success" if saved else "warning")
    if errors:
        flash("Errors: " + "; ".join(errors[:5]), "danger")

    return redirect(url_for("bookkeeping.bookkeeping_page", status="pending"))


def _parse_invoice_form(form):
    """Pull fields from the submitted invoice form into a clean dict."""
    supplier_id = form.get("supplier_id", "")
    supplier_id = int(supplier_id) if supplier_id.isdigit() else None

    supplier_name = form.get("supplier_name", "").strip()
    if supplier_id and not supplier_name:
        sup = [s for s in db.list_suppliers() if s["id"] == supplier_id]
        if sup:
            supplier_name = sup[0]["name"]

    def f(name, default=0.0):
        try:
            return float(form.get(name, default) or default)
        except (ValueError, TypeError):
            return default

    net = f("net_amount")
    vat = f("vat_amount")
    total = f("total_amount")
    vat_rate = f("vat_rate", 23)

    # Auto-fill totals if some fields are blank
    if total and not net and not vat and vat_rate > 0:
        # Split total into net + VAT using vat_rate
        net = round(total / (1 + vat_rate / 100), 2)
        vat = round(total - net, 2)
    elif net and not vat and vat_rate > 0:
        vat = round(net * vat_rate / 100, 2)
        if not total:
            total = round(net + vat, 2)
    elif not total and net and vat:
        total = round(net + vat, 2)

    return {
        "supplier_id": supplier_id,
        "supplier_name": supplier_name or "Unknown",
        "invoice_date": form.get("invoice_date", date.today().isoformat()),
        "invoice_number": form.get("invoice_number", "").strip() or None,
        "net_amount": net,
        "vat_amount": vat,
        "total_amount": total,
        "vat_rate": vat_rate,
        "category": form.get("category", "").strip() or None,
        "status": form.get("status", "approved"),
        "notes": form.get("notes", "").strip() or None,
        "source": form.get("source", "manual"),
    }


# --- Gmail inbox check ---

@bp.route("/bookkeeping/check-inbox", methods=["POST"])
def check_inbox():
    """Manually trigger a Gmail inbox scan for invoice PDFs."""
    try:
        from gmail_poller import check_inbox as _check
        results = _check()
        saved   = sum(1 for r in results if r.get("invoice_id"))
        skipped = sum(1 for r in results if r.get("skipped"))
        errors  = [r for r in results if r.get("extract_error") or r.get("drive_error")]

        parts = []
        if saved:
            parts.append(f"{saved} new invoice(s) pulled from inbox")
        if skipped:
            parts.append(f"{skipped} already imported")
        if not saved and not skipped and not errors:
            parts.append("No new invoices in inbox")
        flash(" · ".join(parts) if parts else "Inbox checked.", "success" if saved else "info")
        if errors:
            msgs = "; ".join(
                r.get("extract_error") or r.get("drive_error", "") for r in errors[:3]
            )
            flash(f"Some errors: {msgs}", "warning")
    except Exception as e:
        flash(f"Inbox check failed: {e}", "danger")

    return redirect(url_for("bookkeeping.bookkeeping_page", status="pending"))


# --- Suppliers management ---

@bp.route("/bookkeeping/suppliers", methods=["GET", "POST"])
def suppliers():
    if request.method == "POST":
        supplier_id = request.form.get("supplier_id", "")
        name = request.form.get("name", "").strip()
        rate = float(request.form.get("default_vat_rate", 23) or 23)
        category = request.form.get("default_category", "").strip() or None
        vat_num = request.form.get("vat_number", "").strip() or None
        if supplier_id.isdigit():
            db.update_supplier(int(supplier_id), name, rate, category, vat_num)
            flash(f"Supplier '{name}' updated.", "success")
        elif name:
            db.add_supplier(name, rate, category, vat_num)
            flash(f"Supplier '{name}' added.", "success")
        return redirect(url_for("bookkeeping.suppliers"))

    return render_template(
        "suppliers.html",
        suppliers=db.list_suppliers(),
        categories=config.INVOICE_CATEGORIES,
    )
