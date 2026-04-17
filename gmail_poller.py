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

def save_to_drive(filename, pdf_bytes):
    """Upload a PDF to the configured Drive folder. Returns the webViewLink URL."""
    from googleapiclient.http import MediaIoBaseUpload

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

def check_inbox():
    """Scan the inbox for unread emails with PDF attachments and process them.

    Returns a list of result dicts — one per PDF attachment found:
      {
        filename:      str,
        drive_url:     str | None,
        invoice_id:    int | None,   # set if successfully extracted + saved
        skipped:       bool,         # True if already imported (duplicate)
        drive_error:   str | None,
        extract_error: str | None,
      }
    """
    import db
    import invoice_extractor

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

        pdf_parts = _pdf_parts(msg.get("payload", {}))
        if not pdf_parts:
            # No PDFs — mark read and move so we don't re-check it
            _archive(service, msg_id, processed_label_id)
            continue

        for part in pdf_parts:
            filename = part.get("filename") or f"invoice_{msg_id[:8]}.pdf"
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"

            result = {"filename": filename, "drive_url": None, "invoice_id": None,
                      "skipped": False, "drive_error": None, "extract_error": None}

            try:
                pdf_bytes = _download_part(service, msg_id, part)
            except Exception as e:
                result["extract_error"] = f"Download failed: {e}"
                all_results.append(result)
                continue

            # --- Save to Google Drive ---
            try:
                result["drive_url"] = save_to_drive(filename, pdf_bytes)
            except Exception as e:
                result["drive_error"] = str(e)

            # --- Save locally + extract ---
            try:
                invoice_extractor.ensure_invoices_dir()
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe = re.sub(r"[^\w.-]", "_", filename)
                local_path = os.path.join(config.INVOICES_DIR, f"{stamp}_{safe}")
                with open(local_path, "wb") as f:
                    f.write(pdf_bytes)

                # Dedupe by file hash
                fhash = invoice_extractor.file_hash(local_path)
                if any(inv["file_hash"] == fhash for inv in db.list_invoices()):
                    os.remove(local_path)
                    result["skipped"] = True
                else:
                    data = invoice_extractor.extract_invoice(local_path)
                    notes = f"From email. AI confidence: {data.get('confidence', 'unknown')}"
                    if result["drive_url"]:
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
                        "source":        "email",
                        "pdf_path":      local_path,
                        "file_hash":     fhash,
                        "status":        "pending",
                        "notes":         notes,
                    })
            except Exception as e:
                result["extract_error"] = str(e)

            all_results.append(result)

        # Move email to Processed + mark as read regardless of extraction outcome
        _archive(service, msg_id, processed_label_id)

    return all_results


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
