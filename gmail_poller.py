"""Gmail inbox poller for invoice@cobblestonepub.ie.

Workflow:
  1. Connect to Gmail via service account with domain-wide delegation.
  2. Find unread emails with PDF attachments.
  3. Save each PDF to Google Drive (GOOGLE_DRIVE_INVOICES_FOLDER_ID).
  4. Run the existing invoice extraction pipeline (Claude AI).
  5. Save as pending invoice in the database.
  6. Move the email to a 'Processed' label and mark as read.

Required environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON   — full JSON key for the service account (single line)
  GOOGLE_DRIVE_INVOICES_FOLDER_ID — Drive folder ID to save PDFs into
"""

import base64
import io
import json
import os
import re
from datetime import date, datetime

import config


GMAIL_USER = "invoice@cobblestonepub.ie"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _credentials(scopes):
    """Build delegated service account credentials."""
    from google.oauth2 import service_account

    sa_json = config.GOOGLE_SERVICE_ACCOUNT_JSON
    if not sa_json:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set. "
            "Add it in your Render environment variables."
        )
    sa_info = json.loads(sa_json)
    return (
        service_account.Credentials
        .from_service_account_info(sa_info, scopes=scopes)
        .with_subject(GMAIL_USER)
    )


def _gmail():
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=_credentials(GMAIL_SCOPES))


def _drive():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_credentials(DRIVE_SCOPES))


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def _ensure_processed_label(service):
    """Return the id of the 'Processed' Gmail label, creating it if needed."""
    response = service.users().labels().list(userId="me").execute()
    for label in response.get("labels", []):
        if label["name"].lower() == "processed":
            return label["id"]
    created = service.users().labels().create(
        userId="me",
        body={
            "name": "Processed",
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


def _all_parts(payload):
    """Recursively yield all leaf parts of a Gmail message payload."""
    if "parts" in payload:
        for part in payload["parts"]:
            yield from _all_parts(part)
    else:
        yield payload


def _pdf_parts(payload):
    """Return parts that look like PDF attachments."""
    results = []
    for part in _all_parts(payload):
        mime = part.get("mimeType", "")
        filename = part.get("filename", "")
        is_pdf = (
            mime == "application/pdf"
            or mime == "application/octet-stream"
            or filename.lower().endswith(".pdf")
        )
        has_content = part.get("body", {}).get("attachmentId") or part.get("body", {}).get("data")
        if is_pdf and has_content:
            results.append(part)
    return results


def _download_part(service, msg_id, part):
    """Download a message part and return raw bytes."""
    body = part.get("body", {})
    attachment_id = body.get("attachmentId")
    if attachment_id:
        att = service.users().messages().attachments().get(
            userId="me", messageId=msg_id, id=attachment_id
        ).execute()
        data = att["data"]
    else:
        data = body.get("data", "")
    # Gmail uses URL-safe base64; pad to a multiple of 4
    return base64.urlsafe_b64decode(data + "==")


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def save_to_drive(filename, pdf_bytes, folder_id=None):
    """Upload a PDF to the given Drive folder (default: invoices folder).

    Returns the webViewLink URL.
    """
    from googleapiclient.http import MediaIoBaseUpload

    if folder_id is None:
        folder_id = config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
    file_metadata = {"name": filename}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    service = _drive()
    result = service.files().create(
        body=file_metadata,
        media_body=MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf"),
        fields="id,webViewLink",
    ).execute()
    return result.get("webViewLink", "")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _email_subject(msg):
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == "subject":
            return h.get("value", "")
    return ""


def check_inbox():
    """Scan the inbox for unread emails with PDF attachments and process them.

    Each PDF is first classified as invoice or statement (statement_detector).
    Invoices flow through the existing Claude extractor → bookkeeping DB.
    Statements are filed in the statements Drive folder + statements DB,
    skipping the invoice extractor entirely.

    Returns a list of result dicts — one per PDF attachment found:
      {
        filename:      str,
        kind:          'invoice' | 'statement',
        drive_url:     str | None,
        invoice_id:    int | None,
        statement_id:  int | None,
        skipped:       bool,
        drive_error:   str | None,
        extract_error: str | None,
        signals:       list[str],     # detection signals
      }
    """
    import db
    import invoice_extractor
    import statement_detector

    service = _gmail()
    processed_label_id = _ensure_processed_label(service)

    msgs = service.users().messages().list(
        userId="me", q="is:unread has:attachment", maxResults=50
    ).execute()

    all_results = []

    for meta in msgs.get("messages", []):
        msg_id = meta["id"]
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
        except Exception as e:
            all_results.append({"filename": "?", "extract_error": str(e)})
            continue

        subject = _email_subject(msg)

        pdf_parts = _pdf_parts(msg.get("payload", {}))
        if not pdf_parts:
            # No PDFs — mark read and move so we don't re-check it
            _archive(service, msg_id, processed_label_id)
            continue

        for part in pdf_parts:
            filename = part.get("filename") or f"file_{msg_id[:8]}.pdf"
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"

            result = {"filename": filename, "kind": "invoice", "drive_url": None,
                      "invoice_id": None, "statement_id": None,
                      "skipped": False, "drive_error": None, "extract_error": None,
                      "signals": []}

            try:
                pdf_bytes = _download_part(service, msg_id, part)
            except Exception as e:
                result["extract_error"] = f"Download failed: {e}"
                all_results.append(result)
                continue

            # --- Save locally so we can hash + classify ---
            try:
                invoice_extractor.ensure_invoices_dir()
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe = re.sub(r"[^\w.-]", "_", filename)
                local_path = os.path.join(config.INVOICES_DIR, f"{stamp}_{safe}")
                with open(local_path, "wb") as f:
                    f.write(pdf_bytes)
                fhash = invoice_extractor.file_hash(local_path)
            except Exception as e:
                result["extract_error"] = f"Local save failed: {e}"
                all_results.append(result)
                continue

            # --- Classify: invoice or statement? ---
            try:
                classification = statement_detector.classify(
                    local_path, filename=filename, email_subject=subject
                )
            except Exception:
                classification = {"kind": "invoice", "confidence": "low",
                                  "signals": [], "extracted": {}}
            result["kind"] = classification["kind"]
            result["signals"] = classification["signals"]

            if classification["kind"] == "statement":
                _process_as_statement(local_path, fhash, filename, pdf_bytes,
                                      classification, result, source="email")
            else:
                _process_as_invoice(local_path, fhash, filename, pdf_bytes,
                                    result, source="email")

            all_results.append(result)

        # Move email to Processed + mark as read regardless of outcome
        _archive(service, msg_id, processed_label_id)

    return all_results


def _process_as_invoice(local_path, fhash, filename, pdf_bytes, result, source):
    """Save invoice to bookkeeping DB + upload PDF to invoices Drive folder."""
    import db
    import invoice_extractor

    # Drive upload (best-effort; failure doesn't block local save)
    try:
        result["drive_url"] = save_to_drive(
            filename, pdf_bytes, folder_id=config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
        )
    except Exception as e:
        result["drive_error"] = str(e)

    try:
        if any(inv["file_hash"] == fhash for inv in db.list_invoices() if inv["file_hash"]):
            os.remove(local_path)
            result["skipped"] = True
            return

        data = invoice_extractor.extract_invoice(local_path)
        notes = f"From {source}. AI confidence: {data.get('confidence', 'unknown')}"
        if result.get("drive_url"):
            notes += f". Drive: {result['drive_url']}"
        result["invoice_id"] = db.save_invoice({
            "supplier_id":   data.get("supplier_id"),
            "supplier_name": (data.get("supplier_name_canonical")
                              or data.get("supplier_name") or "Unknown"),
            "invoice_date":  data.get("invoice_date") or date.today().isoformat(),
            "invoice_number": data.get("invoice_number"),
            "net_amount":    float(data.get("net_amount") or 0),
            "vat_amount":    float(data.get("vat_amount") or 0),
            "total_amount":  float(data.get("total_amount") or 0),
            "vat_rate":      float(data.get("vat_rate") or 23),
            "category":      data.get("category"),
            "source":        source,
            "pdf_path":      local_path,
            "file_hash":     fhash,
            "status":        "pending",
            "notes":         notes,
        })
    except Exception as e:
        result["extract_error"] = str(e)


def _process_as_statement(local_path, fhash, filename, pdf_bytes,
                           classification, result, source):
    """Save statement to statements DB + upload PDF to statements Drive folder."""
    import db

    # Dedupe — if we already saved this statement, skip
    if db.get_statement_by_hash(fhash):
        try:
            os.remove(local_path)
        except OSError:
            pass
        result["skipped"] = True
        return

    # Drive upload to statements folder (falls back to invoices folder if
    # the statements folder env var isn't configured)
    target_folder = (config.GOOGLE_DRIVE_STATEMENTS_FOLDER_ID
                     or config.GOOGLE_DRIVE_INVOICES_FOLDER_ID)
    try:
        result["drive_url"] = save_to_drive(filename, pdf_bytes, folder_id=target_folder)
    except Exception as e:
        result["drive_error"] = str(e)

    extracted = classification.get("extracted") or {}
    signals_text = "; ".join(classification.get("signals", []))

    try:
        result["statement_id"] = db.save_statement({
            "supplier_id": None,
            "supplier_name": extracted.get("supplier_name") or "Unknown",
            "statement_date": extracted.get("statement_date"),
            "total_balance": extracted.get("total_balance"),
            "pdf_path": local_path,
            "file_hash": fhash,
            "drive_url": result.get("drive_url"),
            "source": source,
            "status": "pending",
            "detection_signals": signals_text,
            "notes": f"Auto-classified as statement ({classification.get('confidence', '?')} confidence) from {source}.",
        })
    except Exception as e:
        result["extract_error"] = f"Save statement failed: {e}"


def sweep_inbox_for_year(impersonate_user, year):
    """Historical sweep: find every email in `impersonate_user`'s inbox
    that has a PDF attachment within the given year, and import any PDFs
    we don't already have (by hash dedupe).

    Designed for one-time recovery — used to find 2025 invoices that
    were sent to info@ instead of invoice@. Does NOT mutate the source
    inbox (no archiving, no labelling) since the user reads their own
    info@ for non-invoice mail too.

    Sets cache key 'inbox_sweep_progress' so the audit page can show
    progress + final summary.
    """
    from datetime import datetime as _dt
    import db
    import invoice_extractor
    import statement_detector

    db.set_cache("inbox_sweep_progress", {
        "started_at": _dt.now().isoformat(),
        "user": impersonate_user,
        "year": year,
        "status": "scanning",
        "scanned": 0,
        "imported_invoices": 0,
        "imported_statements": 0,
        "skipped_dupes": 0,
        "errors": 0,
    })

    # Build a service impersonating the requested user (info@ is different
    # from the gmail_poller's default invoice@)
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = (
        service_account.Credentials
        .from_service_account_info(sa_info, scopes=GMAIL_SCOPES)
        .with_subject(impersonate_user)
    )
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    query = f"after:{year}/1/1 before:{year+1}/1/1 has:attachment filename:pdf"

    counts = {"scanned": 0, "imported_invoices": 0, "imported_statements": 0,
              "skipped_dupes": 0, "errors": 0}
    page_token = None
    total_msgs = 0

    while True:
        try:
            resp = service.users().messages().list(
                userId="me", q=query, pageToken=page_token, maxResults=100,
            ).execute()
        except Exception as e:
            print(f"[inbox-sweep] list failed: {e}")
            break

        msgs = resp.get("messages", [])
        total_msgs += len(msgs)

        for meta in msgs:
            counts["scanned"] += 1
            if counts["scanned"] % 10 == 0:
                _update_sweep_progress(counts, "processing", impersonate_user, year, total_msgs)

            msg_id = meta["id"]
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_id, format="full",
                ).execute()
            except Exception as e:
                counts["errors"] += 1
                continue

            subject = _email_subject(msg)
            pdf_parts = _pdf_parts(msg.get("payload", {}))
            if not pdf_parts:
                continue

            for part in pdf_parts:
                filename = part.get("filename") or f"info_{msg_id[:8]}.pdf"
                if not filename.lower().endswith(".pdf"):
                    filename += ".pdf"
                try:
                    pdf_bytes = _download_part(service, msg_id, part)
                    invoice_extractor.ensure_invoices_dir()
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe = re.sub(r"[^\w.-]", "_", filename)
                    local_path = os.path.join(config.INVOICES_DIR, f"sweep_{stamp}_{safe}")
                    with open(local_path, "wb") as fh:
                        fh.write(pdf_bytes)
                    fhash = invoice_extractor.file_hash(local_path)
                except Exception as e:
                    counts["errors"] += 1
                    continue

                # Hash dedupe
                if any(inv["file_hash"] == fhash for inv in db.list_invoices() if inv["file_hash"]):
                    try: os.remove(local_path)
                    except OSError: pass
                    counts["skipped_dupes"] += 1
                    continue
                if db.get_statement_by_hash(fhash):
                    try: os.remove(local_path)
                    except OSError: pass
                    counts["skipped_dupes"] += 1
                    continue

                try:
                    classification = statement_detector.classify(
                        local_path, filename=filename, email_subject=subject,
                    )
                except Exception:
                    classification = {"kind": "invoice", "confidence": "low",
                                      "signals": [], "extracted": {}}

                try:
                    if classification["kind"] == "statement":
                        extracted = classification.get("extracted") or {}
                        db.save_statement({
                            "supplier_id": None,
                            "supplier_name": extracted.get("supplier_name") or "Unknown",
                            "statement_date": extracted.get("statement_date"),
                            "total_balance": extracted.get("total_balance"),
                            "pdf_path": local_path,
                            "file_hash": fhash,
                            "drive_url": None,
                            "source": f"sweep:{impersonate_user}",
                            "status": "pending",
                            "detection_signals": "; ".join(classification.get("signals", [])),
                            "notes": f"Imported via {year} sweep of {impersonate_user}.",
                        })
                        counts["imported_statements"] += 1
                    else:
                        data = invoice_extractor.extract_invoice(local_path)
                        db.save_invoice({
                            "supplier_id":   data.get("supplier_id"),
                            "supplier_name": (data.get("supplier_name_canonical")
                                              or data.get("supplier_name") or "Unknown"),
                            "invoice_date":  data.get("invoice_date") or "",
                            "invoice_number": data.get("invoice_number"),
                            "net_amount":    float(data.get("net_amount") or 0),
                            "vat_amount":    float(data.get("vat_amount") or 0),
                            "total_amount":  float(data.get("total_amount") or 0),
                            "vat_rate":      float(data.get("vat_rate") or 23),
                            "category":      data.get("category"),
                            "source":        f"sweep:{impersonate_user}",
                            "pdf_path":      local_path,
                            "file_hash":     fhash,
                            "status":        "pending",
                            "notes":         (f"Imported via {year} sweep of "
                                              f"{impersonate_user}. AI confidence: "
                                              f"{data.get('confidence','unknown')}."),
                        })
                        counts["imported_invoices"] += 1
                except Exception as e:
                    counts["errors"] += 1
                    print(f"[inbox-sweep] save failed {filename}: {e}")

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    _update_sweep_progress(counts, "completed", impersonate_user, year, total_msgs)
    return counts


def _update_sweep_progress(counts, status, user, year, total):
    from datetime import datetime as _dt
    import db
    payload = dict(counts)
    payload.update({
        "status": status,
        "user": user,
        "year": year,
        "total_messages": total,
        "ts": _dt.now().isoformat(),
    })
    db.set_cache("inbox_sweep_progress", payload)


def _archive(service, msg_id, processed_label_id):
    """Move a message to Processed and mark as read."""
    try:
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={
                "addLabelIds":    [processed_label_id],
                "removeLabelIds": ["UNREAD", "INBOX"],
            },
        ).execute()
    except Exception as e:
        print(f"[gmail] Could not archive message {msg_id}: {e}")
