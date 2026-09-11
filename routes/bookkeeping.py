"""Bookkeeping routes - invoice tracking + supplier management."""

import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort, jsonify
from datetime import date, datetime
import os
import db
import config
import invoice_extractor


def _drive_url_from_notes(notes):
    """Extract a Drive URL from a free-text notes field, if present."""
    if not notes:
        return None
    m = re.search(r"https?://drive\.google\.com/\S+", notes)
    return m.group(0) if m else None

bp = Blueprint("bookkeeping", __name__)


@bp.route("/bookkeeping")
def bookkeeping_page():
    # Filters
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    supplier_id = request.args.get("supplier_id", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "")
    keyword = request.args.get("keyword", "")

    supplier_id_int = int(supplier_id) if supplier_id.isdigit() else None
    status_filter = status if status else None

    invoices = db.list_invoices(
        start_date=start_date or None,
        end_date=end_date or None,
        supplier_id=supplier_id_int,
        category=category or None,
        status=status_filter,
        keyword=keyword or None,
    )
    suppliers = db.list_suppliers()

    # Aggregates
    total_net = sum((inv["net_amount"] or 0) for inv in invoices)
    total_vat = sum((inv["vat_amount"] or 0) for inv in invoices)
    total_gross = sum((inv["total_amount"] or 0) for inv in invoices)

    # Current year monthly VAT totals
    today = date.today()
    monthly = db.monthly_vat_totals(today.year)

    # Drive watcher status panel
    try:
        import drive_watcher
        drive_status = drive_watcher.status_snapshot()
    except Exception as e:
        drive_status = {"configured": False, "error": str(e),
                        "pending_count": None, "root_url": None,
                        "processed_url": None}
    drive_last_run, _ = db.get_cache("drive_watcher_last_run")

    late_vat = db.get_late_vat_invoices()
    late_vat_pending = [i for i in late_vat if i["reclaim_status"] == "pending"]
    late_vat_vat_total = sum(float(i["vat_amount"] or 0) for i in late_vat_pending)
    late_vat_net_total = sum(float(i["net_amount"] or 0) for i in late_vat_pending)

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
        filter_keyword=keyword,
        today=today.isoformat(),
        drive_status=drive_status,
        drive_last_run=drive_last_run,
        late_vat=late_vat_pending,
        late_vat_vat_total=late_vat_vat_total,
        late_vat_net_total=late_vat_net_total,
    )


@bp.route("/bookkeeping/late-vat/<int:invoice_id>/action", methods=["POST"])
def late_vat_action(invoice_id):
    action = request.form.get("action")  # 'reclaimed' or 'written_off'
    note = request.form.get("note", "").strip() or None
    if action in ("reclaimed", "written_off"):
        db.set_vat_reclaim_status(invoice_id, action, note)
    return redirect(url_for("bookkeeping.bookkeeping_page") + "#late-vat")


@bp.route("/bookkeeping/missing")
def missing_invoices():
    report = db.get_missing_invoice_report()
    total_outstanding = sum(r["total_paid"] for r in report)
    return render_template(
        "missing_invoices.html",
        report=report,
        total_outstanding=total_outstanding,
    )


@bp.route("/bookkeeping/statements")
def statements_list():
    start = request.args.get("start_date", "")
    end = request.args.get("end_date", "")
    supplier_id = request.args.get("supplier_id", "")
    status = request.args.get("status", "")

    rows = db.list_statements(
        start_date=start or None,
        end_date=end or None,
        supplier_id=int(supplier_id) if supplier_id.isdigit() else None,
        status=status or None,
    )
    suppliers = db.list_suppliers()
    counts = db.statement_counts()

    return render_template(
        "statements_list.html",
        statements=rows,
        suppliers=suppliers,
        counts=counts,
        filter_start=start,
        filter_end=end,
        filter_supplier=supplier_id,
        filter_status=status,
    )


@bp.route("/bookkeeping/statements/<int:statement_id>", methods=["GET", "POST"])
def statement_detail(statement_id):
    stmt = db.get_statement(statement_id)
    if not stmt:
        flash("Statement not found.", "danger")
        return redirect(url_for("bookkeeping.statements_list"))

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "save":
            db.save_statement({
                "supplier_id": int(request.form["supplier_id"]) if request.form.get("supplier_id", "").isdigit() else None,
                "supplier_name": request.form.get("supplier_name", "").strip() or "Unknown",
                "statement_date": request.form.get("statement_date") or None,
                "total_balance": float(request.form["total_balance"]) if request.form.get("total_balance") else None,
                "pdf_path": stmt["pdf_path"],
                "drive_url": stmt["drive_url"],
                "status": request.form.get("status", "pending"),
                "notes": request.form.get("notes", "").strip() or None,
            }, statement_id=statement_id)
            flash("Statement updated.", "success")
        elif action == "delete":
            db.delete_statement(statement_id)
            flash("Statement deleted.", "info")
            return redirect(url_for("bookkeeping.statements_list"))
        elif action == "reclassify_as_invoice":
            return _reclassify_statement_as_invoice(statement_id)
        return redirect(url_for("bookkeeping.statement_detail", statement_id=statement_id))

    suppliers = db.list_suppliers()
    return render_template(
        "statement_detail.html",
        statement=stmt,
        suppliers=suppliers,
    )


def _reclassify_statement_as_invoice(statement_id):
    """Move a misclassified statement into the invoices DB. Best-effort —
    we run the AI extractor on the PDF and create an invoice record, then
    delete the statement record. PDF stays where it is on Drive (statements
    Processed); manual move if desired."""
    stmt = db.get_statement(statement_id)
    if not stmt:
        flash("Statement not found.", "danger")
        return redirect(url_for("bookkeeping.statements_list"))

    pdf_path = stmt["pdf_path"]
    if not pdf_path or not os.path.exists(pdf_path):
        flash("Statement PDF is no longer on local disk; cannot reclassify automatically.", "warning")
        return redirect(url_for("bookkeeping.statement_detail", statement_id=statement_id))

    try:
        data = invoice_extractor.extract_invoice(pdf_path)
        invoice_id = db.save_invoice({
            "supplier_id":   data.get("supplier_id"),
            "supplier_name": (data.get("supplier_name_canonical")
                              or data.get("supplier_name") or stmt["supplier_name"]),
            "invoice_date":  data.get("invoice_date") or date.today().isoformat(),
            "invoice_number": data.get("invoice_number"),
            "net_amount":    float(data.get("net_amount") or 0),
            "vat_amount":    float(data.get("vat_amount") or 0),
            "total_amount":  float(data.get("total_amount") or 0),
            "vat_rate":      float(data.get("vat_rate") or 23),
            "category":      data.get("category"),
            "source":        "reclassified",
            "pdf_path":      pdf_path,
            "file_hash":     stmt["file_hash"],
            "status":        "pending",
            "notes":         f"Reclassified from statement #{statement_id}. AI confidence: {data.get('confidence', 'unknown')}.",
        })
        db.delete_statement(statement_id)
        flash(f"Reclassified as invoice #{invoice_id}. Review on the bookkeeping page.", "success")
        return redirect(url_for("bookkeeping.edit_invoice", invoice_id=invoice_id))
    except Exception as e:
        flash(f"Reclassify failed: {e}", "danger")
        return redirect(url_for("bookkeeping.statement_detail", statement_id=statement_id))


@bp.route("/bookkeeping/bulk-approve", methods=["POST"])
def bulk_approve_invoices():
    """Approve every invoice id submitted via invoice_ids[] checkboxes.

    Skips ids that don't exist or are already approved (idempotent).
    Filter context is preserved on the redirect so the user lands back
    where they were.
    """
    raw_ids = request.form.getlist("invoice_ids")
    ids = []
    for r in raw_ids:
        try:
            ids.append(int(r))
        except (TypeError, ValueError):
            continue

    approved = 0
    skipped = 0
    for inv_id in ids:
        inv = db.get_invoice(inv_id)
        if not inv:
            skipped += 1
            continue
        if inv["status"] == "approved":
            skipped += 1
            continue
        # Re-save with status flipped — keep all other fields untouched.
        data = {
            "supplier_id": inv["supplier_id"],
            "supplier_name": inv["supplier_name"],
            "invoice_date": inv["invoice_date"],
            "invoice_number": inv["invoice_number"],
            "net_amount": inv["net_amount"],
            "vat_amount": inv["vat_amount"],
            "total_amount": inv["total_amount"],
            "vat_rate": inv["vat_rate"],
            "category": inv["category"],
            "status": "approved",
            "notes": inv["notes"],
        }
        db.save_invoice(data, invoice_id=inv_id)
        approved += 1

    if approved == 0 and skipped == 0:
        flash("No invoices selected.", "warning")
    elif skipped:
        flash(f"Approved {approved} invoice(s). Skipped {skipped} (already approved or missing).", "success")
    else:
        flash(f"Approved {approved} invoice(s).", "success")

    # Preserve the filter context the user was browsing
    filter_qs = _filter_query_string(_filter_args_from_request())
    return redirect("/bookkeeping" + filter_qs)


@bp.route("/bookkeeping/<int:invoice_id>/reclassify-as-statement", methods=["POST"])
def reclassify_invoice_as_statement(invoice_id):
    """Move a misclassified invoice into the statements DB."""
    inv = db.get_invoice(invoice_id) if hasattr(db, "get_invoice") else None
    if not inv:
        # Fall back to a list lookup
        for r in db.list_invoices():
            if r["id"] == invoice_id:
                inv = r
                break
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    try:
        # If a statement with this file_hash already exists, the user is
        # effectively saying "I already have this as a statement, just
        # drop the bad invoice copy". Skip the insert and link to the
        # existing one — otherwise we'd hit the UNIQUE constraint.
        existing = None
        if inv["file_hash"]:
            existing = db.get_statement_by_hash(inv["file_hash"])
        if existing:
            db.delete_invoice(invoice_id)
            flash(
                f"Invoice removed — a statement for this PDF already exists "
                f"(#{existing['id']}). Opened the existing statement.",
                "info",
            )
            return redirect(url_for("bookkeeping.statement_detail", statement_id=existing["id"]))

        statement_id = db.save_statement({
            "supplier_id": inv["supplier_id"],
            "supplier_name": inv["supplier_name"],
            "statement_date": inv["invoice_date"],
            "total_balance": inv["total_amount"],
            "pdf_path": inv["pdf_path"],
            "file_hash": inv["file_hash"],
            "drive_url": None,
            "source": "reclassified",
            "status": "pending",
            "detection_signals": "manually reclassified by user",
            "notes": f"Reclassified from invoice #{invoice_id}.",
        })
        db.delete_invoice(invoice_id)
        flash(f"Reclassified as statement. Moved on to next pending invoice.", "success")
        filters = _filter_args_from_request()
        next_id = _next_pending_in_filter(invoice_id, filters)
        if next_id:
            return redirect(url_for("bookkeeping.edit_invoice", invoice_id=next_id, **{
                f"filter_{k}": v for k, v in filters.items() if v
            }))
        return redirect("/bookkeeping" + _filter_query_string(filters))
    except Exception as e:
        flash(f"Reclassify failed: {e}", "danger")
        return redirect(url_for("bookkeeping.bookkeeping_page"))


@bp.route("/bookkeeping/drive-scan", methods=["POST"])
def drive_scan_now():
    """Trigger an immediate Drive folder scan."""
    try:
        import drive_watcher
        results = drive_watcher.import_pending()
    except Exception as e:
        flash(f"Drive scan failed: {e}", "danger")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    imported = sum(1 for r in results if r.get("invoice_id"))
    skipped = sum(1 for r in results if r.get("skipped"))
    errored = sum(1 for r in results if r.get("error"))

    db.set_cache("drive_watcher_last_run", {
        "ts": datetime.now().isoformat(),
        "imported": imported,
        "errored": errored,
        "skipped": skipped,
        "total": len(results),
        "results": results[-10:],
    })

    bits = []
    if imported:
        bits.append(f"{imported} imported")
    if skipped:
        bits.append(f"{skipped} already-imported tidied up")
    if errored:
        bits.append(f"{errored} errored")
    if not bits:
        bits.append("nothing pending")
    flash("Drive scan: " + ", ".join(bits) + ".",
          "warning" if errored else "success")
    return redirect(url_for("bookkeeping.bookkeeping_page"))


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


def _filter_args_from_request():
    """Pull bookkeeping filter args from the request.

    GET: accepts either filter_* prefixed names OR plain names
    (start_date etc.) — the bookkeeping list page links with plain
    names, the edit page passes them through with filter_* prefix.

    POST: ONLY accepts filter_* prefixed names. The invoice form has
    its own non-prefixed fields named supplier_id / category / status
    that belong to the invoice being edited, NOT to the filter — never
    treat those as filter context.
    """
    if request.method == "POST":
        src = request.form
        return {
            "start_date":  src.get("filter_start_date", ""),
            "end_date":    src.get("filter_end_date", ""),
            "supplier_id": src.get("filter_supplier_id", ""),
            "category":    src.get("filter_category", ""),
            "status":      src.get("filter_status", ""),
            "keyword":     src.get("filter_keyword", ""),
        }
    src = request.args
    return {
        "start_date":  src.get("filter_start_date") or src.get("start_date") or "",
        "end_date":    src.get("filter_end_date") or src.get("end_date") or "",
        "supplier_id": src.get("filter_supplier_id") or src.get("supplier_id") or "",
        "category":    src.get("filter_category") or src.get("category") or "",
        "status":      src.get("filter_status") or src.get("status") or "",
        "keyword":     src.get("filter_keyword") or src.get("keyword") or "",
    }


def _filter_query_string(filters):
    """Build a query string from filter dict, omitting empty fields."""
    parts = [f"{k}={v}" for k, v in filters.items() if v]
    return ("?" + "&".join(parts)) if parts else ""


def _next_pending_in_filter(current_invoice_id, filters):
    """Find the next pending invoice to review — the one with the date
    closest to today (most recent first), skipping the current invoice.

    Sorted DESC so the user always lands on the most recent unreviewed
    invoice rather than wrapping around to the oldest.
    """
    rows = db.list_invoices(
        start_date=filters.get("start_date") or None,
        end_date=filters.get("end_date") or None,
        supplier_id=int(filters["supplier_id"]) if (filters.get("supplier_id") or "").isdigit() else None,
        category=filters.get("category") or None,
        status="pending",
        keyword=filters.get("keyword") or None,
        limit=500,
    )
    # Most recent first (closest to today)
    rows = sorted(rows, key=lambda r: ((r["invoice_date"] or ""), r["id"]), reverse=True)

    for r in rows:
        if r["id"] != current_invoice_id:
            return r["id"]
    return None


def _neighbors_in_filter(current_invoice_id, filters):
    """Return (prev_id, next_id) for plain prev/next browsing in the same
    filter. Unlike _next_pending_in_filter, this ignores status — so you
    can step back to an already-approved invoice to fix it.
    """
    rows = db.list_invoices(
        start_date=filters.get("start_date") or None,
        end_date=filters.get("end_date") or None,
        supplier_id=int(filters["supplier_id"]) if (filters.get("supplier_id") or "").isdigit() else None,
        category=filters.get("category") or None,
        status=filters.get("status") or None,
        keyword=filters.get("keyword") or None,
        limit=1000,
    )
    rows = sorted(rows, key=lambda r: ((r["invoice_date"] or ""), r["id"]))
    prev_id = None
    next_id = None
    for i, r in enumerate(rows):
        if r["id"] == current_invoice_id:
            if i > 0:
                prev_id = rows[i - 1]["id"]
            if i < len(rows) - 1:
                next_id = rows[i + 1]["id"]
            break
    return prev_id, next_id


@bp.route("/bookkeeping/<int:invoice_id>/edit", methods=["GET", "POST"])
def edit_invoice(invoice_id):
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        flash("Invoice not found.", "danger")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    filters = _filter_args_from_request()

    if request.method == "GET":
        suppliers = db.list_suppliers()
        drive_url = _drive_url_from_notes(invoice["notes"])
        local_pdf_available = bool(invoice["pdf_path"]) and os.path.exists(invoice["pdf_path"])

        # Count remaining pending in this filter (informational header)
        pending_in_filter = db.list_invoices(
            start_date=filters.get("start_date") or None,
            end_date=filters.get("end_date") or None,
            supplier_id=int(filters["supplier_id"]) if (filters.get("supplier_id") or "").isdigit() else None,
            category=filters.get("category") or None,
            status="pending",
            limit=500,
        )

        # Plain prev/next neighbours in the same filter (any status) so
        # you can step back to fix an already-approved invoice.
        prev_id, next_id = _neighbors_in_filter(invoice_id, filters)

        return render_template(
            "invoice_form.html",
            invoice=invoice,
            suppliers=suppliers,
            categories=config.INVOICE_CATEGORIES,
            today=date.today().isoformat(),
            drive_url=drive_url,
            local_pdf_available=local_pdf_available,
            filters=filters,
            filter_query_string=_filter_query_string(filters),
            pending_in_filter_count=len(pending_in_filter),
            prev_invoice_id=prev_id,
            next_invoice_id=next_id,
        )

    # POST — save
    save_action = request.form.get("save_action", "back")  # 'back' | 'next'
    try:
        data = _parse_invoice_form(request.form)
        db.save_invoice(data, invoice_id=invoice_id)
        if data.get("supplier_id") and data.get("category"):
            db.update_supplier_category(data["supplier_id"], data["category"])
        flash("Invoice updated.", "success")
    except Exception as e:
        flash(f"Could not update invoice: {e}", "danger")
        # Stay on this invoice if save failed
        return redirect(url_for("bookkeeping.edit_invoice", invoice_id=invoice_id, **{
            f"filter_{k}": v for k, v in filters.items() if v
        }))

    if save_action == "next":
        next_id = _next_pending_in_filter(invoice_id, filters)
        if next_id:
            return redirect(url_for("bookkeeping.edit_invoice", invoice_id=next_id, **{
                f"filter_{k}": v for k, v in filters.items() if v
            }))
        # No more pending in filter — fall through to list
        flash("No more pending invoices in this filter — back to list.", "info")

    # 'back' or no-more-next — return to the filtered list
    return redirect("/bookkeeping" + _filter_query_string(filters))


@bp.route("/bookkeeping/audit")
def audit_year():
    """Per-supplier coverage audit for a given year — surfaces missing
    invoices by showing which months we have for each supplier."""
    try:
        year = int(request.args.get("year", str(date.today().year - 1)))
    except ValueError:
        year = date.today().year - 1

    suppliers_data = db.audit_supplier_year(year)

    # Sort: most-spent suppliers first, then suppliers with the most gaps
    suppliers_data.sort(key=lambda s: (-s["total"], -(12 - len(s["months"]))))

    grand_count = sum(s["count"] for s in suppliers_data)
    grand_net = sum(s["net"] for s in suppliers_data)
    grand_vat = sum(s["vat"] for s in suppliers_data)
    grand_total = sum(s["total"] for s in suppliers_data)

    sweep_progress, _ = db.get_cache("inbox_sweep_progress")
    deep_scan_progress, _ = db.get_cache("drive_deep_scan_progress")

    return render_template(
        "audit_year.html",
        year=year,
        suppliers_data=suppliers_data,
        grand_count=grand_count,
        grand_net=grand_net,
        grand_vat=grand_vat,
        grand_total=grand_total,
        sweep_progress=sweep_progress,
        deep_scan_progress=deep_scan_progress,
    )


@bp.route("/bookkeeping/audit/sweep-info", methods=["POST"])
def audit_sweep_info():
    """Trigger a background sweep of info@cobblestonepub.ie for a given year.
    Background thread updates cache_metadata['inbox_sweep_progress']."""
    import threading
    import gmail_poller

    try:
        year = int(request.form.get("year", str(date.today().year - 1)))
    except ValueError:
        year = date.today().year - 1
    user = request.form.get("user", "info@cobblestonepub.ie").strip()

    def _run():
        try:
            gmail_poller.sweep_inbox_for_year(user, year)
        except Exception as e:
            db.set_cache("inbox_sweep_progress", {
                "status": "failed",
                "year": year,
                "user": user,
                "error": str(e),
            })

    threading.Thread(target=_run, daemon=True).start()
    flash(f"Sweep of {user} for {year} started in the background. "
          "Refresh this page to watch progress.", "info")
    return redirect(url_for("bookkeeping.audit_year", year=year))


def _extract_drive_folder_id(url_or_id):
    """Accept either a bare folder ID (28+ chars) or any Drive URL form
    and return the folder ID. Returns None if no ID detected."""
    if not url_or_id:
        return None
    s = url_or_id.strip()
    # URLs look like
    #   https://drive.google.com/drive/folders/<ID>?...
    #   https://drive.google.com/drive/u/0/folders/<ID>
    m = re.search(r"/folders/([A-Za-z0-9_-]{20,})", s)
    if m:
        return m.group(1)
    # Bare ID (no URL)
    if re.match(r"^[A-Za-z0-9_-]{20,}$", s):
        return s
    return None


@bp.route("/bookkeeping/audit/deep-scan-drive", methods=["POST"])
def audit_deep_scan_drive():
    """Trigger a background recursive scan of a Drive folder tree.

    Accepts an optional ?folder= URL/ID — defaults to the configured
    invoices folder. Lets the user point the scan at archive folders
    held elsewhere in Drive without changing the env var."""
    import threading
    import drive_watcher

    try:
        year = int(request.form.get("year", str(date.today().year - 1)))
    except ValueError:
        year = date.today().year - 1

    raw_folder = request.form.get("folder", "").strip()
    folder_id = _extract_drive_folder_id(raw_folder) if raw_folder else None

    if raw_folder and not folder_id:
        flash("Could not parse a Drive folder ID from that input. Paste a "
              "folder URL or the bare ID.", "danger")
        return redirect(url_for("bookkeeping.audit_year", year=year))

    def _run():
        try:
            drive_watcher.deep_scan_year(year, folder_id=folder_id)
        except Exception as e:
            db.set_cache("drive_deep_scan_progress", {
                "status": "failed",
                "year": year,
                "folder_id": folder_id,
                "error": str(e),
            })

    threading.Thread(target=_run, daemon=True).start()
    target_label = (folder_id or "configured invoices folder")
    flash(f"Deep scan of {target_label} started for {year}. "
          "Refresh this page to watch progress.", "info")
    return redirect(url_for("bookkeeping.audit_year", year=year))


@bp.route("/bookkeeping/monthly-summary")
def download_monthly_summary():
    """Download an Excel summary of approved invoices for a given month or
    custom date range. Used for VAT prep and accountant submissions.

    Query params:
      ?month=YYYY-MM  (single month — preferred)
      OR
      ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD (custom range)
    """
    from calendar import monthrange
    import excel_export

    month_str = request.args.get("month", "").strip()
    start = request.args.get("start_date", "").strip()
    end = request.args.get("end_date", "").strip()

    if month_str:
        try:
            year, mon = map(int, month_str.split("-"))
            start = f"{year:04d}-{mon:02d}-01"
            last_day = monthrange(year, mon)[1]
            end = f"{year:04d}-{mon:02d}-{last_day:02d}"
            period_label = datetime(year, mon, 1).strftime("%B %Y")
        except (ValueError, IndexError):
            flash("Invalid month format. Use YYYY-MM (e.g. 2026-04).", "danger")
            return redirect(url_for("bookkeeping.bookkeeping_page"))
    elif start and end:
        try:
            ds = datetime.strptime(start, "%Y-%m-%d")
            de = datetime.strptime(end, "%Y-%m-%d")
            if ds.strftime("%Y-%m") == de.strftime("%Y-%m"):
                period_label = ds.strftime("%B %Y")
            else:
                period_label = f"{ds.strftime('%b %Y')} - {de.strftime('%b %Y')}"
        except ValueError:
            flash("Invalid date format.", "danger")
            return redirect(url_for("bookkeeping.bookkeeping_page"))
    else:
        flash("Pick a month or date range to download a summary.", "warning")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    invoices = db.list_invoices(
        start_date=start, end_date=end, status="approved", limit=5000,
    )

    buf = excel_export.generate_invoice_monthly_excel(period_label, invoices)
    safe_label = period_label.replace(" ", "_").replace("-", "")
    filename = f"Cobblestone_Invoice_Summary_{safe_label}.xlsx"
    return send_file(
        buf, download_name=filename, as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/bookkeeping/<int:invoice_id>/pdf")
def view_invoice_pdf(invoice_id):
    """Serve the local PDF for an invoice. Inline-displays so the browser
    opens it in a tab rather than forcing download."""
    invoice = db.get_invoice(invoice_id)
    if not invoice or not invoice["pdf_path"]:
        abort(404)
    pdf_path = invoice["pdf_path"]
    if not os.path.exists(pdf_path):
        abort(404)
    safe_name = re.sub(r"[^\w.-]", "_", invoice["supplier_name"] or "invoice")
    download_name = f"Invoice_{invoice['id']}_{safe_name}.pdf"
    return send_file(pdf_path, mimetype="application/pdf",
                     as_attachment=False, download_name=download_name)


@bp.route("/bookkeeping/statements/<int:statement_id>/pdf")
def view_statement_pdf(statement_id):
    stmt = db.get_statement(statement_id)
    if not stmt or not stmt["pdf_path"]:
        abort(404)
    pdf_path = stmt["pdf_path"]
    if not os.path.exists(pdf_path):
        abort(404)
    safe_name = re.sub(r"[^\w.-]", "_", stmt["supplier_name"] or "statement")
    download_name = f"Statement_{stmt['id']}_{safe_name}.pdf"
    return send_file(pdf_path, mimetype="application/pdf",
                     as_attachment=False, download_name=download_name)


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

@bp.route("/bookkeeping/suppliers/quick-add", methods=["POST"])
def suppliers_quick_add():
    """JSON endpoint for the 'add supplier' modal on the invoice form.

    Returns the supplier dict on success so the caller can append a new
    <option> to the dropdown without a page reload. If a supplier with
    the same name already exists (case-insensitive), returns that one
    instead of erroring — DB has INSERT OR IGNORE so this is the
    sensible behaviour.
    """
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400

    try:
        rate = float(request.form.get("default_vat_rate", 23) or 23)
    except (TypeError, ValueError):
        rate = 23.0
    category = (request.form.get("default_category") or "").strip() or None
    vat_num = (request.form.get("vat_number") or "").strip() or None

    db.add_supplier(name, rate, category, vat_num)
    # add_supplier uses INSERT OR IGNORE so on duplicate we still need
    # to look up the existing row. find_supplier_by_name handles both
    # exact and fuzzy match — for the freshly-inserted row this is exact.
    row = db.find_supplier_by_name(name)
    if not row:
        return jsonify({"error": "Could not save supplier."}), 500

    return jsonify({
        "id": row["id"],
        "name": row["name"],
        "default_vat_rate": row["default_vat_rate"],
        "default_category": row["default_category"] or "",
        "vat_number": row["vat_number"] or "",
    })


@bp.route("/bookkeeping/suppliers/quick-edit", methods=["POST"])
def suppliers_quick_edit():
    """JSON endpoint for the 'edit supplier' modal on the invoice form.

    Updates an existing supplier and returns the fresh row so the caller
    can update its dropdown <option> without a page reload.
    """
    sid_raw = (request.form.get("supplier_id") or "").strip()
    if not sid_raw.isdigit():
        return jsonify({"error": "Missing or invalid supplier id."}), 400
    supplier_id = int(sid_raw)

    existing = db.get_supplier(supplier_id)
    if not existing:
        return jsonify({"error": "Supplier not found."}), 404

    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400

    try:
        rate = float(request.form.get("default_vat_rate", 23) or 23)
    except (TypeError, ValueError):
        rate = 23.0
    category = (request.form.get("default_category") or "").strip() or None
    vat_num = (request.form.get("vat_number") or "").strip() or None

    db.update_supplier(supplier_id, name, rate, category, vat_num)
    row = db.get_supplier(supplier_id)
    if not row:
        return jsonify({"error": "Could not load updated supplier."}), 500

    return jsonify({
        "id": row["id"],
        "name": row["name"],
        "default_vat_rate": row["default_vat_rate"],
        "default_category": row["default_category"] or "",
        "vat_number": row["vat_number"] or "",
    })


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


def _parse_square_tax_csv(file_storage) -> dict | None:
    """Parse a tax summary file (Square CSV export or corrected .xlsx) into the sales-by-rate dict.

    Columns expected:
      Tax Name | Taxable Amount | Taxable Item Sales | Taxable Service Charges | Tax Collected

    We use:
      - Taxable Item Sales (col C / index 2) as the net sales figure for each rate
      - Tax Collected (col E / index 4) as the VAT collected

    Summary rows: 'Non Taxable Sales', 'Total Net Sales' (used for 0% bucket / totals).

    Accepts:
      - .xlsx  — parsed with openpyxl (user-compiled corrected format)
      - .csv   — Square UTF-16 tab-separated export

    Returns:
        {
          "by_rate": {23.0: {"sales": Decimal, "tax": Decimal}, ...},
          "total_sales": Decimal,
          "total_tax": Decimal,
        }
    or None if parsing fails.
    """
    from decimal import Decimal
    import csv, io

    TAX_NAME_MAP = {
        "reg vat":      23.0,
        "special vat":   9.0,   # Irish reduced rate changed from 13.5% to 9%
        "reduced vat":   9.0,
        "9% vat":        9.0,
        "vat 9%":        9.0,
        "food vat":      9.0,
    }

    def _to_decimal(val):
        """Convert a cell value (number or string with currency symbols) to Decimal."""
        if val is None:
            return Decimal("0")
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        s = str(val).strip().lstrip("€$£").replace(",", "").strip()
        try:
            return Decimal(s)
        except Exception:
            return Decimal("0")

    def _process_rows(rows):
        """rows: iterable of lists/tuples. Returns the by_rate dict."""
        by_rate = {}
        non_taxable = Decimal("0")
        total_tax = Decimal("0")

        for row in rows:
            if not row or row[0] is None:
                continue
            name = str(row[0]).strip().lower()

            # Tax rate rows: must have at least 5 columns
            if name in TAX_NAME_MAP and len(row) >= 5:
                pct = TAX_NAME_MAP[name]
                sales = _to_decimal(row[2])   # Taxable Item Sales (col C)
                tax   = _to_decimal(row[4])   # Tax Collected (col E)
                by_rate[pct] = {"sales": sales, "tax": tax}
                total_tax += tax

            elif "non taxable" in name and len(row) >= 2:
                non_taxable = _to_decimal(row[1])

        if non_taxable:
            by_rate[0.0] = {"sales": non_taxable, "tax": Decimal("0")}

        total_sales = sum(v["sales"] for v in by_rate.values())
        return {"by_rate": by_rate, "total_sales": total_sales, "total_tax": total_tax}

    try:
        filename = (file_storage.filename or "").lower()

        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            # Excel format (user-compiled corrected report)
            import openpyxl, io as _io
            raw = file_storage.read()
            wb = openpyxl.load_workbook(_io.BytesIO(raw), data_only=True)
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                if any(c is not None for c in row):
                    rows.append(list(row))
            # Skip header row if it contains "Tax Name"
            if rows and str(rows[0][0] or "").strip().lower() == "tax name":
                rows = rows[1:]
            return _process_rows(rows)

        else:
            # CSV format (Square export — UTF-16 tab-separated)
            raw = file_storage.read()
            try:
                text = raw.decode("utf-16")
            except Exception:
                text = raw.decode("utf-8", errors="replace")

            reader = csv.reader(io.StringIO(text), delimiter="\t")
            rows = []
            first = True
            for row in reader:
                row = [c.strip() for c in row]
                if first and row and row[0].lower() == "tax name":
                    first = False
                    continue
                first = False
                rows.append(row)
            return _process_rows(rows)

    except Exception as e:
        print(f"[vat-period] tax report parse error: {e}")
        return None


@bp.route("/bookkeeping/vat-period", methods=["GET", "POST"])
def download_vat_period():
    """Download a VAT summary for one or two months in the accountant (Peter) format.

    POST form fields:
      m1        YYYY-MM  (required)
      m2        YYYY-MM  (optional — second month)
      csv_m1    Square tax summary CSV for month 1 (optional)
      csv_m2    Square tax summary CSV for month 2 (optional)

    One month  → SUMMARY | {M1} VAT Collected | {M1} VAT Paid
    Two months → SUMMARY | {M1} VAT Collected | {M1} VAT Paid | {M2} VAT Collected | {M2} VAT Paid
    """
    from calendar import monthrange
    import excel_export

    if request.method == "GET":
        # Support legacy GET links (redirect to bookkeeping page)
        flash("Use the Download form to generate a VAT period report.", "info")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    m1_str = request.form.get("m1", "").strip()
    m2_str = request.form.get("m2", "").strip()

    if not m1_str:
        flash("Please select at least one month.", "warning")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    try:
        y1, mo1 = map(int, m1_str.split("-"))
    except (ValueError, AttributeError):
        flash("Invalid month format.", "danger")
        return redirect(url_for("bookkeeping.bookkeeping_page"))

    two_months = bool(m2_str)
    if two_months:
        try:
            y2, mo2 = map(int, m2_str.split("-"))
        except (ValueError, AttributeError):
            flash("Invalid second month format.", "danger")
            return redirect(url_for("bookkeeping.bookkeeping_page"))

    def _month_range(year, mon):
        last = monthrange(year, mon)[1]
        return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}"

    # Parse uploaded Square tax CSVs (optional)
    csv_m1 = request.files.get("csv_m1")
    csv_m2 = request.files.get("csv_m2")
    m1_sales = _parse_square_tax_csv(csv_m1) if csv_m1 and csv_m1.filename else None
    m2_sales = _parse_square_tax_csv(csv_m2) if csv_m2 and csv_m2.filename else None

    m1_start, m1_end = _month_range(y1, mo1)
    m1_short = datetime(y1, mo1, 1).strftime("%B")
    m1_invoices = db.list_invoices(start_date=m1_start, end_date=m1_end,
                                    status="approved", limit=5000)

    if two_months:
        m2_start, m2_end = _month_range(y2, mo2)
        m2_short = datetime(y2, mo2, 1).strftime("%B")
        m2_invoices = db.list_invoices(start_date=m2_start, end_date=m2_end,
                                        status="approved", limit=5000)
        buf = excel_export.generate_vat_period_excel(
            m1_short, m2_short,
            m1_invoices, m2_invoices,
            m1_sales, m2_sales,
        )
        period_slug = f"{m1_str}_{m2_str}".replace("-", "")
    else:
        buf = excel_export.generate_vat_period_excel(
            m1_short, m1_short,
            m1_invoices, [],
            m1_sales, None,
        )
        period_slug = m1_str.replace("-", "")

    filename = f"Cobblestone_VAT_{period_slug}.xlsx"
    return send_file(
        buf, download_name=filename, as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
