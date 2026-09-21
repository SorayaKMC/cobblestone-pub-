"""drive_archive.py — archive processed invoice PDFs to Google Drive.

Uploads local PDF files to a dedicated 'Invoice Archive' subfolder in the
existing Google Drive invoices folder, then deletes the local copy to free
disk space on Render.

The invoice's pdf_path in the database is updated to the Drive web-view URL
so the PDF link in the UI still works (opens in Drive instead of serving
the local file).
"""

import json
import logging
import os

log = logging.getLogger(__name__)

ARCHIVE_FOLDER_NAME = "Invoice Archive"

# Reuse the same scopes as drive_watcher
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://mail.google.com/",
]


def _drive_service():
    import config
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_json = config.GOOGLE_SERVICE_ACCOUNT_JSON
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set — cannot archive to Drive.")
    sa_info = json.loads(sa_json)

    # Try with impersonation first (same as drive_watcher); fall back without it.
    try:
        import drive_watcher
        gmail_user = getattr(drive_watcher, "GMAIL_USER", None)
    except Exception:
        gmail_user = None

    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=DRIVE_SCOPES
    )
    if gmail_user:
        creds = creds.with_subject(gmail_user)

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_archive_folder(service, parent_folder_id):
    """Return the Drive folder ID for the archive folder, creating it if needed."""
    # Search for existing folder
    q = (
        f"name='{ARCHIVE_FOLDER_NAME}' "
        f"and '{parent_folder_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    res = service.files().list(q=q, fields="files(id,name)", spaces="drive").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    # Create it
    meta = {
        "name": ARCHIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    log.info("[archive] Created Drive folder '%s' (%s)", ARCHIVE_FOLDER_NAME, folder["id"])
    return folder["id"]


def upload_pdf_to_drive(local_path, filename, folder_id):
    """Upload a single PDF to Drive. Returns the web-view URL string, or None on failure."""
    from googleapiclient.http import MediaFileUpload

    service = _drive_service()
    archive_folder_id = _get_or_create_archive_folder(service, folder_id)

    file_meta = {"name": filename, "parents": [archive_folder_id]}
    media = MediaFileUpload(local_path, mimetype="application/pdf", resumable=False)
    uploaded = service.files().create(
        body=file_meta, media_body=media, fields="id,webViewLink"
    ).execute()

    # Make the file readable by anyone with the link
    service.permissions().create(
        fileId=uploaded["id"],
        body={"role": "reader", "type": "anyone"},
    ).execute()

    return uploaded.get("webViewLink")


def archive_all_pdfs(db_conn=None):
    """Archive every approved invoice that still has a local PDF on disk.

    Returns a dict:
      {
        "archived": int,   # successfully uploaded + local file deleted
        "skipped": int,    # already a Drive URL or no file on disk
        "failed":  int,    # upload error
        "errors":  list[str],
      }
    """
    import config
    import db as _db

    parent_folder_id = config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
    if not parent_folder_id:
        return {
            "archived": 0, "skipped": 0, "failed": 1,
            "errors": ["GOOGLE_DRIVE_INVOICES_FOLDER_ID is not set in Render environment."],
        }

    invoices = _db.list_invoices(status="approved", limit=10000)
    # Also grab pending — they have PDFs too
    invoices += _db.list_invoices(status="pending", limit=10000)

    archived = skipped = failed = 0
    errors = []

    for inv in invoices:
        pdf_path = inv.get("pdf_path") or ""

        # Already a URL (previously archived) or no path recorded — skip
        if not pdf_path or pdf_path.startswith("http"):
            skipped += 1
            continue

        # Local file doesn't exist — clean up the stale reference
        if not os.path.exists(pdf_path):
            skipped += 1
            continue

        filename = os.path.basename(pdf_path)
        try:
            drive_url = upload_pdf_to_drive(pdf_path, filename, parent_folder_id)
            if drive_url:
                # Update DB record to Drive URL
                _db.update_invoice_pdf_path(inv["id"], drive_url)
                # Delete local copy
                try:
                    os.remove(pdf_path)
                except OSError as e:
                    log.warning("[archive] Could not delete local file %s: %s", pdf_path, e)
                archived += 1
                log.info("[archive] Archived %s → %s", filename, drive_url)
            else:
                failed += 1
                errors.append(f"No URL returned for {filename}")
        except Exception as e:
            failed += 1
            errors.append(f"{filename}: {e}")
            log.error("[archive] Failed to archive %s: %s", filename, e)

    return {"archived": archived, "skipped": skipped, "failed": failed, "errors": errors}
