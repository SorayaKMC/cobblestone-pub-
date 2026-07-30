"""Bank reconciliation — upload AIB CSV, match against invoices and payroll."""

import re
import csv
import io
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
import db

bp = Blueprint("reconcile", __name__)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _parse_amount(s):
    if not s or not s.strip():
        return None
    try:
        return float(s.strip())
    except ValueError:
        return None


def _parse_aib_csv(file_bytes):
    """Parse AIB BalanceAndTransactionReport.csv.

    Columns (no header row):
      0: sort_code  1: account_no  2: account_type  3: currency
      4: date(DD/MM/YYYY)  5: empty  6: description
      7: debit(negative)   8: credit(positive)   9: balance(optional)
    """
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))

    transactions = []
    opening_balance = None
    closing_balance = None

    for row in reader:
        if len(row) < 9:
            continue

        raw_date = row[4].strip()
        description = row[6].strip()
        debit_str = row[7].strip()
        credit_str = row[8].strip()
        balance_str = row[9].strip() if len(row) > 9 else ""

        if not raw_date or not description:
            continue

        # Skip the opening balance row
        if description == "OPENING BALANCE":
            if balance_str:
                try:
                    opening_balance = float(balance_str)
                except ValueError:
                    pass
            continue

        try:
            txn_date = datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
        except ValueError:
            continue

        debit = _parse_amount(debit_str)    # negative value like -529.88
        credit = _parse_amount(credit_str)  # positive value
        balance = _parse_amount(balance_str)

        if balance is not None:
            closing_balance = balance

        txn_type, extracted_name = _classify_transaction(description)

        transactions.append({
            "txn_date": txn_date,
            "description": description,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "txn_type": txn_type,
            "extracted_name": extracted_name,
        })

    return transactions, opening_balance, closing_balance


def _classify_transaction(description):
    """Return (txn_type, extracted_name) for a transaction description."""
    desc = description.strip()

    # Income / credits — Square payouts
    if re.match(r"T3[A-Z0-9]{8,}", desc):
        return "income", None

    # Cash lodgments
    if desc.startswith("LATM CR") or desc.startswith("LODGMENT"):
        return "income", None

    # Bank charges
    if any(k in desc for k in ("BOI BOL CHARGE", "NOTIFIED FEES", "AMEND S/O CHARGE")):
        return "bank_charge", None

    # Payroll — B365 transfers
    m = re.match(r"B365\s+(.+?)\s+IP$", desc)
    if m:
        return "payroll", m.group(1).strip()

    # Payroll — 365 Online transfers (some use this for payroll too)
    m = re.match(r"365 Online\s+(.+)", desc)
    if m:
        name = m.group(1).strip()
        # Account references like 96216286, 92952008 are supplier payments, not payroll
        if re.match(r"\d{6,}", name):
            return "supplier_transfer", None
        return "payroll_online", name

    # SEPA direct debits
    if "SEPA DD" in desc:
        vendor = desc.replace("SEPA DD", "").strip()
        return "direct_debit", vendor

    # Standing orders
    if desc.endswith(" SO"):
        name = desc[:-3].strip()
        return "standing_order", name

    # Card payments (POS / POSC)
    m = re.match(r"POSC?\d{4,6}\w*\s+(.+)", desc)
    if m:
        return "card_payment", m.group(1).strip()

    return "other", None


# ---------------------------------------------------------------------------
# Auto-matcher
# ---------------------------------------------------------------------------

_DATE_TOLERANCE_INVOICE = 14   # days either side for invoice matching
_DATE_TOLERANCE_PAYROLL = 7    # days either side for payroll matching


def _date_diff(d1_iso, d2_iso):
    try:
        return abs((date.fromisoformat(d1_iso) - date.fromisoformat(d2_iso)).days)
    except Exception:
        return 9999


def _name_score(bank_name, given_name, family_name):
    """Score how well a bank extracted name matches an employee. Returns 0–3."""
    if not bank_name:
        return 0
    bank_tokens = bank_name.upper().split()
    full = (given_name + " " + family_name).upper()
    # Strip titles
    clean_given = re.sub(r"^(MR|MRS|MS|DR)\.?\s+", "", given_name.upper())
    clean_family = family_name.upper().replace("'", "").replace("-", " ")

    score = 0
    for tok in bank_tokens:
        if len(tok) < 2:
            continue
        if clean_given.startswith(tok) or tok.startswith(clean_given[:min(len(tok), len(clean_given))]):
            score += 2
        elif any(part.startswith(tok) or tok.startswith(part[:min(len(tok), len(part))])
                 for part in clean_family.split()):
            score += 1
    return score


def _auto_match(statement_id):
    transactions = db.get_bank_transactions(statement_id)
    invoices = db.list_invoices(limit=5000)
    pay_nets = db.get_all_pay_period_nets_with_dates()
    employees = db.get_employee_categories()

    # Index invoices by rounded total_amount
    inv_by_amount = {}
    for inv in invoices:
        key = round(float(inv["total_amount"] or 0), 2)
        inv_by_amount.setdefault(key, []).append(inv)

    # Index payroll nets by rounded net_pay
    pay_by_amount = {}
    for pn in pay_nets:
        key = round(float(pn["net_pay"] or 0), 2)
        pay_by_amount.setdefault(key, []).append(pn)

    for txn in transactions:
        if txn["match_status"] == "matched":
            continue

        # Auto-label income credits
        if txn["credit"] and not txn["debit"]:
            desc = txn["description"]
            if re.match(r"T3[A-Z0-9]{8,}", desc):
                db.update_bank_transaction_match(txn["id"], "matched", "income", None, "Square payout – bar & online sales")
            elif desc.startswith("LATM CR"):
                db.update_bank_transaction_match(txn["id"], "matched", "income", None, "Square cash lodgment")
            elif desc.startswith("LODGMENT"):
                db.update_bank_transaction_match(txn["id"], "matched", "income", None, "Cash lodgment")
            else:
                db.update_bank_transaction_match(txn["id"], "review", "income", None, f"Income – {desc}")
            continue

        if not txn["debit"]:
            continue

        # Auto-ignore bank charges
        if txn["txn_type"] == "bank_charge":
            db.update_bank_transaction_match(txn["id"], "ignored", "bank_charge", None, "Bank charge")
            continue

        debit_abs = round(abs(float(txn["debit"])), 2)
        txn_date = txn["txn_date"]
        is_payroll = txn["txn_type"] in ("payroll", "payroll_online")

        # --- Payroll: try exact amount + date match against payslip data ---
        if is_payroll:
            candidates = pay_by_amount.get(debit_abs, [])
            best = None
            best_score = (-1, 9999)
            for pn in candidates:
                diff = _date_diff(txn_date, pn["pay_date"])
                if diff > _DATE_TOLERANCE_PAYROLL:
                    continue
                ns = _name_score(txn["extracted_name"], pn["raw_name"], "")
                if best is None or (ns > best_score[0]) or (ns == best_score[0] and diff < best_score[1]):
                    best = pn
                    best_score = (ns, diff)
            if best:
                label = f"Payroll – {best['raw_name']} ({best['period_label'] or best['iso_week']})"
                db.update_bank_transaction_match(txn["id"], "matched", "payroll", best["id"], label)
                continue

            # --- Payroll: try employee name match (no payslip needed) ---
            bank_name = txn["extracted_name"] or ""
            best_emp = None
            best_emp_score = 0
            for emp in employees:
                ns = _name_score(bank_name, emp["given_name"], emp["family_name"])
                if ns > best_emp_score:
                    best_emp = emp
                    best_emp_score = ns
            if best_emp and best_emp_score >= 2:
                full_name = f"{best_emp['given_name']} {best_emp['family_name']}"
                label = f"Payroll – {full_name} (no payslip on file for this period)"
                db.update_bank_transaction_match(txn["id"], "matched", "payroll_name", None, label)
                continue

        # --- Invoice match for all debit types (including B365 supplier payments) ---
        candidates = inv_by_amount.get(debit_abs, [])
        best_inv = None
        best_diff = _DATE_TOLERANCE_INVOICE + 1
        for inv in candidates:
            diff = _date_diff(txn_date, inv["invoice_date"])
            if diff <= _DATE_TOLERANCE_INVOICE and diff < best_diff:
                best_inv = inv
                best_diff = diff
        if best_inv:
            label = f"{best_inv['supplier_name']} – inv #{best_inv['invoice_number'] or best_inv['id']} (€{best_inv['total_amount']:.2f})"
            db.update_bank_transaction_match(txn["id"], "matched", "invoice", best_inv["id"], label)
            continue

        # --- Final fallback: acknowledge payroll transactions with extracted name ---
        # Covers casual staff, contractors, and one-off payments that have no payslip
        # record and no invoice — at least record who was paid so it's not a mystery.
        if is_payroll and txn["extracted_name"]:
            label = f"Payroll/payment – {txn['extracted_name']} (no record on file)"
            db.update_bank_transaction_match(txn["id"], "review", "payroll_unknown", None, label)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/reconcile")
def reconcile_index():
    statements = db.list_bank_statements()
    return render_template("reconcile.html", statements=statements, view=None)


@bp.route("/reconcile/upload", methods=["POST"])
def reconcile_upload():
    f = request.files.get("csv_file")
    if not f or not f.filename:
        flash("Please choose a CSV file.", "danger")
        return redirect(url_for("reconcile.reconcile_index"))

    raw = f.read()
    transactions, opening_balance, closing_balance = _parse_aib_csv(raw)

    if not transactions:
        flash("No transactions found in that file. Make sure it's the AIB BalanceAndTransactionReport.csv.", "danger")
        return redirect(url_for("reconcile.reconcile_index"))

    dates = [t["txn_date"] for t in transactions]
    debits = [abs(float(t["debit"])) for t in transactions if t["debit"]]
    credits = [float(t["credit"]) for t in transactions if t["credit"]]

    stmt_id = db.save_bank_statement(
        filename=f.filename,
        date_from=min(dates),
        date_to=max(dates),
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        transaction_count=len(transactions),
        debit_total=round(sum(debits), 2),
        credit_total=round(sum(credits), 2),
    )
    db.save_bank_transactions(stmt_id, transactions)
    _auto_match(stmt_id)

    flash(f"Uploaded {len(transactions)} transactions. Auto-matching complete.", "success")
    return redirect(url_for("reconcile.reconcile_view", statement_id=stmt_id))


@bp.route("/reconcile/<int:statement_id>")
def reconcile_view(statement_id):
    statement = db.get_bank_statement(statement_id)
    if not statement:
        flash("Statement not found.", "danger")
        return redirect(url_for("reconcile.reconcile_index"))

    transactions = db.get_bank_transactions(statement_id)
    status_filter = request.args.get("status", "all")

    if status_filter != "all":
        transactions = [t for t in transactions if t["match_status"] == status_filter]

    all_txns = db.get_bank_transactions(statement_id)
    matched = sum(1 for t in all_txns if t["match_status"] == "matched")
    unmatched = sum(1 for t in all_txns if t["match_status"] == "unmatched")
    ignored = sum(1 for t in all_txns if t["match_status"] == "ignored")
    review = sum(1 for t in all_txns if t["match_status"] == "review")

    all_statements = db.list_bank_statements()
    invoices = db.list_invoices(limit=5000)

    return render_template(
        "reconcile.html",
        statements=all_statements,
        view=statement,
        transactions=transactions,
        status_filter=status_filter,
        matched=matched,
        unmatched=unmatched,
        ignored=ignored,
        review=review,
        invoices=invoices,
    )


@bp.route("/reconcile/txn/<int:txn_id>/match", methods=["POST"])
def txn_match(txn_id):
    match_type = request.form.get("match_type")
    match_id = request.form.get("match_id")
    match_label = request.form.get("match_label", "")
    statement_id = request.form.get("statement_id")

    if match_type and match_id:
        db.update_bank_transaction_match(
            txn_id, "matched", match_type, int(match_id), match_label
        )
    else:
        flash("Please select a match.", "warning")

    return redirect(url_for("reconcile.reconcile_view", statement_id=statement_id,
                            status=request.args.get("status", "all")))


@bp.route("/reconcile/txn/<int:txn_id>/ignore", methods=["POST"])
def txn_ignore(txn_id):
    statement_id = request.form.get("statement_id")
    db.update_bank_transaction_match(txn_id, "ignored", None, None, "Manually ignored")
    return redirect(url_for("reconcile.reconcile_view", statement_id=statement_id,
                            status=request.args.get("status", "all")))


@bp.route("/reconcile/txn/<int:txn_id>/unmatch", methods=["POST"])
def txn_unmatch(txn_id):
    statement_id = request.form.get("statement_id")
    db.update_bank_transaction_match(txn_id, "unmatched", None, None, None)
    return redirect(url_for("reconcile.reconcile_view", statement_id=statement_id,
                            status=request.args.get("status", "all")))


@bp.route("/reconcile/<int:statement_id>/rematch", methods=["POST"])
def reconcile_rematch(statement_id):
    """Re-run auto-matching on all unmatched transactions in a statement."""
    _auto_match(statement_id)
    flash("Auto-matching re-run complete.", "success")
    return redirect(url_for("reconcile.reconcile_view", statement_id=statement_id))


@bp.route("/reconcile/<int:statement_id>/delete", methods=["POST"])
def reconcile_delete(statement_id):
    db.delete_bank_statement(statement_id)
    flash("Statement deleted.", "success")
    return redirect(url_for("reconcile.reconcile_index"))


@bp.route("/reconcile/txn/<int:txn_id>/match-options")
def txn_match_options(txn_id):
    """Return JSON list of invoices for the manual match modal."""
    q = request.args.get("q", "").lower()
    invoices = db.list_invoices(keyword=q or None, limit=50)
    return jsonify([
        {
            "id": inv["id"],
            "label": f"{inv['supplier_name']} – #{inv['invoice_number'] or inv['id']} – €{inv['total_amount']:.2f} – {inv['invoice_date']}",
        }
        for inv in invoices
    ])
