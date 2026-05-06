"""Generate Gmail drafts for each employee with their payslip + PTO summary.

Drafts are created in info@cobblestonepub.ie via the existing Google service
account with domain-wide delegation (same pattern as gmail_poller.py).
"""

import base64
import json
from datetime import datetime
from decimal import Decimal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Eagerly import the Google client libs at module load (single-threaded
# context) to avoid the well-known import race in googleapiclient when
# multiple threads first-import .discovery concurrently:
#   https://github.com/googleapis/google-api-python-client/issues/1502
from google.oauth2 import service_account
from googleapiclient.discovery import build

import config
import db
import payslip_extractor
import pto_engine
import square_client


GMAIL_USER = "info@cobblestonepub.ie"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


def _credentials():
    sa_json = config.GOOGLE_SERVICE_ACCOUNT_JSON
    if not sa_json:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set. "
            "Add it in your environment variables."
        )
    try:
        sa_info = json.loads(sa_json)
    except json.JSONDecodeError as e:
        # Surface enough context to diagnose without leaking the secret.
        head = sa_json.lstrip()[:20].replace("\n", "\\n")
        length = len(sa_json)
        raise RuntimeError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON ({e.msg} at char {e.pos}). "
            f"Length={length}, starts with: {head!r}. "
            "Expected the value to start with '{' and be the entire service-account "
            "JSON file content (no wrapping quotes, no prefix)."
        ) from e
    if not isinstance(sa_info, dict) or sa_info.get("type") != "service_account":
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON parsed but does not look like a service "
            "account key (expected an object with \"type\":\"service_account\")."
        )
    return (
        service_account.Credentials
        .from_service_account_info(sa_info, scopes=GMAIL_SCOPES)
        .with_subject(GMAIL_USER)
    )


def _gmail_service():
    return build("gmail", "v1", credentials=_credentials())


def _format_date_dmy(iso_date):
    """'2026-04-26' -> '26/04/2026'."""
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return d.strftime("%d/%m/%Y")


def build_subject(week_num, period_end_iso):
    return f"Cobblestone Pub - Payslip Week {week_num}, period ending {_format_date_dmy(period_end_iso)}"


def build_body(period_end_iso, first_name=None, accrued_hrs=None, avg_shift=None, balance_days=None):
    """Build the email body. Pass None for the PTO fields to omit the leave summary
    (used for upper management, who don't accrue PTO).

    first_name: optional employee first name for the greeting line.
    """
    period = _format_date_dmy(period_end_iso)
    greeting = f"Hi {first_name}," if first_name else "Hi,"

    parts = [
        greeting,
        "",
        f"Please find your payslip for the period ending {period}.",
        "",
        "Please review the details carefully, including hours worked, rate of pay, and tips, and any deductions. "
        "If you believe there are any discrepancies, please notify management in writing within 48 hours so we can review and resolve promptly.",
        "",
        "If you have any questions regarding your pay, tax, PRSI, or statutory deductions, please let us know.",
        "",
    ]

    if accrued_hrs is not None and avg_shift is not None and balance_days is not None:
        parts.extend([
            "Annual Leave Summary:",
            "",
            f"You accrued {accrued_hrs:.1f} hrs this week. Your 13-week average shift is {avg_shift:.2f} hrs.",
            "",
            f"Your current annual leave accrual total is: {balance_days:.2f} days.",
            "",
        ])

    parts.extend([
        "Thank you for your continued work and professionalism.",
        "",
        "Kind regards,",
        "Soraya",
        "The Cobblestone Pub",
    ])

    return "\n".join(parts)


def _build_mime(to_email, subject, body, attachment_bytes, attachment_filename):
    """Build a multipart/mixed MIME message with a PDF attachment.

    Uses MIMEBase + explicit base64 encoding (rather than MIMEApplication's
    auto-encoding) because Gmail is strict about Content-Transfer-Encoding
    headers being present on attachment parts. The previous MIMEApplication
    pattern produced drafts where attachments silently failed to render.
    """
    msg = MIMEMultipart("mixed")
    msg["To"] = to_email
    msg["From"] = GMAIL_USER
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Force bytes — sqlite3 sometimes returns memoryview for BLOB columns
    # and the MIME encoders only accept bytes-like proper.
    pdf_bytes = bytes(attachment_bytes)

    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{attachment_filename}"',
    )
    part.add_header("Content-Type", f'application/pdf; name="{attachment_filename}"')
    msg.attach(part)
    return msg


def _create_draft(service, mime_msg):
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
    body = {"message": {"raw": raw}}
    result = service.users().drafts().create(userId="me", body=body).execute()
    return result.get("id")


def create_test_draft():
    """Create a self-addressed test draft to verify Gmail auth.

    Returns (draft_id, None) on success, (None, error_message) on failure.
    The draft is addressed to info@ itself so it cannot accidentally email an
    employee, and is clearly marked as a test in the subject and body.
    """
    try:
        service = _gmail_service()
    except Exception as e:
        return None, f"Auth setup failed: {e}"

    msg = MIMEMultipart()
    msg["To"] = GMAIL_USER
    msg["From"] = GMAIL_USER
    msg["Subject"] = "Cobblestone payroll - Gmail draft test"
    msg.attach(MIMEText(
        "This is a test draft created by the Cobblestone payroll app to verify "
        f"that drafts can be created in {GMAIL_USER}.\n\n"
        "Safe to delete.",
        "plain",
    ))

    try:
        draft_id = _create_draft(service, msg)
        return draft_id, None
    except Exception as e:
        return None, str(e)


def _pto_data_for_employee(tm_id, period_end_iso, summary_balances):
    """Returns (accrued_hrs, avg_shift, balance_days) or (None, None, None) on failure.

    Computes accrual TWO ways, picks the higher value:
      1. Read from pto_accruals table (fast path, populated by recalc)
      2. Compute live by calling pto_engine.calculate_weekly_accrual

    The live path is bulletproof against stale or missing DB rows. Even if
    the recalc job didn't fire for this week, the email body will still
    show the correct number directly from Square + the accrual rules.
    """
    try:
        from datetime import timedelta
        period_end = datetime.strptime(period_end_iso, "%Y-%m-%d").date()
        period_start = period_end - timedelta(days=6)

        # Fast path: read from DB
        accrual = db.get_pto_accrual_for_week(tm_id, period_start.isoformat())
        days_accrued = float(accrual["days_accrued"]) if accrual else 0.0

        # Live path: compute from Square right now. Always trust the live
        # computation if it's higher than the DB value (indicates the DB
        # is stale). Hours sources, in priority order:
        #   1. Manual-hours entry (rare)
        #   2. Hours extracted from Peter's uploaded payslip (most authoritative)
        #   3. Square timecards (the normal path)
        try:
            manual_override = db.get_manual_hours(tm_id, period_start.isoformat())
            # If Peter's payslip is uploaded for the work week the user is
            # processing, those hours override Square — payslip is ground
            # truth post-upload.
            iso_week_str = f"{period_end.year}-W{period_end.isocalendar()[1]:02d}"
            payslip_hours = db.get_payslip_hours_for_employee(tm_id, iso_week_str)
            if payslip_hours and (manual_override is None or payslip_hours > manual_override):
                effective_override = payslip_hours
            else:
                effective_override = manual_override

            live = pto_engine.calculate_weekly_accrual(
                tm_id, period_start.isoformat(), period_end.isoformat(),
                manual_hours_override=effective_override,
            )
            live_days = float(live["days_accrued"]) if live else 0.0
            if live_days > days_accrued:
                days_accrued = live_days
        except Exception as e:
            print(f"[drafts] Live accrual calc failed for {tm_id}: {e}")

        avg_shift_dec = pto_engine.calculate_13_week_avg_shift(tm_id, period_end_iso)
        avg_shift = float(avg_shift_dec) if avg_shift_dec else 8.0

        accrued_hrs = days_accrued * avg_shift
        balance_days = float(summary_balances.get(tm_id, 0.0))
        return accrued_hrs, avg_shift, balance_days
    except Exception as e:
        print(f"[drafts] _pto_data_for_employee failed for {tm_id}: {e}")
        return None, None, None


def generate_drafts_for_period(pay_period_id):
    """Create one Gmail draft per employee with a mapped row + email + payslip.

    Returns a dict with counts and per-employee outcomes.

    PTO accrual data is pulled live from Square via _pto_data_for_employee
    at email-composition time — no need for a separate pre-recalc here.
    """
    period = db.get_pay_period_by_id(pay_period_id)
    if not period:
        raise ValueError("Pay period not found")

    nets = db.get_pay_period_nets(pay_period_id)
    payslips_meta = db.get_pay_period_payslips(pay_period_id)
    payslip_refs = {p["ref_no"] for p in payslips_meta}

    employees = {r["team_member_id"]: r for r in db.get_employee_categories()}

    # Cumulative balance from the PTO summary (capped at 21).
    summary = db.get_pto_summary()
    summary_balances = {s["team_member_id"]: s["balance"] for s in summary}

    subject = build_subject(period["week_num"], period["period_end"])

    service = _gmail_service()

    # Re-running Generate Drafts: delete any existing Gmail drafts for this
    # pay period first so we don't end up with duplicates (one with an
    # attachment, one without — common when an earlier run had a bug).
    existing_drafts = db.get_email_drafts(pay_period_id)
    deleted_count = 0
    for d in existing_drafts:
        old_id = d["gmail_draft_id"]
        if not old_id:
            continue
        try:
            service.users().drafts().delete(userId="me", id=old_id).execute()
            deleted_count += 1
        except Exception:
            # If the user already deleted the draft from Gmail, no problem.
            pass
    if deleted_count:
        print(f"[payroll-drafts] Cleaned up {deleted_count} existing draft(s) before regenerating")

    created = skipped = failed = 0
    zero_accrual_warnings = 0  # hourly+mgmt drafts where accrued hrs came out 0
    results = []

    for n in nets:
        tm_id = n["team_member_id"]
        ref = n["ref_no"]
        raw_name = n["raw_name"]

        if not tm_id:
            db.record_email_draft(pay_period_id, f"unmapped_{ref}", "",
                                  None, "skipped", "Unmapped row")
            results.append({"ref": ref, "raw_name": raw_name, "status": "skipped",
                            "reason": "Unmapped row"})
            skipped += 1
            continue

        emp = employees.get(tm_id)
        if not emp:
            db.record_email_draft(pay_period_id, tm_id, "",
                                  None, "skipped", "Employee record missing")
            results.append({"ref": ref, "raw_name": raw_name, "status": "skipped",
                            "reason": "Employee record missing"})
            skipped += 1
            continue

        email = (emp["email"] or "").strip() if "email" in emp.keys() else ""
        if not email:
            db.record_email_draft(pay_period_id, tm_id, "",
                                  None, "skipped", "No email on file")
            results.append({"ref": ref, "raw_name": raw_name, "status": "skipped",
                            "reason": "No email on file"})
            skipped += 1
            continue

        if ref not in payslip_refs:
            db.record_email_draft(pay_period_id, tm_id, email,
                                  None, "failed", "No payslip PDF for this ref")
            results.append({"ref": ref, "raw_name": raw_name, "status": "failed",
                            "reason": "No payslip PDF for this ref"})
            failed += 1
            continue

        slip_row = db.get_payslip_blob_by_ref(pay_period_id, ref)
        pdf_bytes = slip_row["pdf_blob"]
        first_name = (emp["given_name"] or "").strip() or None

        if emp["category"] == "Upper Management":
            body = build_body(period["period_end"], first_name=first_name)
        else:
            accrued_hrs, avg_shift, balance_days = _pto_data_for_employee(
                tm_id, period["period_end"], summary_balances
            )
            if accrued_hrs is None:
                # Fall back to a no-PTO email rather than failing the whole draft.
                body = build_body(period["period_end"], first_name=first_name)
            else:
                if accrued_hrs == 0:
                    zero_accrual_warnings += 1
                body = build_body(period["period_end"], first_name=first_name,
                                  accrued_hrs=accrued_hrs, avg_shift=avg_shift,
                                  balance_days=balance_days)

        full_name = f"{emp['given_name']} {emp['family_name']}".replace("/", "_")
        attachment_filename = f"Payslip_{full_name}_W{period['week_num']:02d}_{period['year']}.pdf"

        try:
            mime = _build_mime(email, subject, body, pdf_bytes, attachment_filename)
            draft_id = _create_draft(service, mime)
            db.record_email_draft(pay_period_id, tm_id, email, draft_id, "created", None)
            results.append({"ref": ref, "raw_name": raw_name, "status": "created",
                            "email": email})
            created += 1
        except Exception as e:
            db.record_email_draft(pay_period_id, tm_id, email, None, "failed", str(e))
            results.append({"ref": ref, "raw_name": raw_name, "status": "failed",
                            "reason": str(e)})
            failed += 1

    return {
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "total": len(nets),
        "zero_accrual_warnings": zero_accrual_warnings,
        "results": results,
    }
