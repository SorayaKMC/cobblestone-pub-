"""Watch a Google Drive folder for human-uploaded invoice PDFs.

For each new PDF found at the root of `GOOGLE_DRIVE_INVOICES_FOLDER_ID`:
  1. Download bytes
  2. SHA-256 hash dedupe against the bookkeeping DB
  3. If new, run the existing Claude-based invoice extractor, save record
  4. Rename to '[imported-YYYY-MM-DD] <original>.pdf'
  5. Move into the auto-created 'Processed' subfolder

Already-processed files (those in the 'Processed' subfolder, or those
already prefixed with '[imported-...]') are ignored. Existing month-organised
subfolders (Jan 2026, Feb 2026, etc.) are not touched — the watcher only
scans files directly in the root folder.

Auth: same service-account + domain-wide-delegation pattern as gmail_poller.
Requires the `drive` scope so we can read files we didn't create and move
them. Impersonates info@cobblestonepub.ie.
"""

import io
import json
import os
import re
from datetime import date, datetime

import config
import db


GMAIL_USER = "info@cobblestonepub.ie"
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]
PROCESSED_FOLDER_NAME = "Processed"
IMPORTED_PREFIX_RE = re.compile(r"^\[imported-\d{4}-\d{2}-\d{2}\]\s")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _credentials():
    from google.oauth2 import service_account

    sa_json = config.GOOGLE_SERVICE_ACCOUNT_JSON
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set.")
    sa_info = json.loads(sa_json)
    return (
        service_account.Credentials
        .from_service_account_info(sa_info, scopes=DRIVE_SCOPES)
        .with_subject(GMAIL_USER)
    )


def _drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def _ensure_processed_folder(service, root_id):
    """Find or create the 'Processed' subfolder inside root. Returns its id."""
    q = (
        f"'{root_id}' in parents and "
        f"name = '{PROCESSED_FOLDER_NAME}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    resp = service.files().list(
        q=q, fields="files(id,name)", pageSize=1
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    created = service.files().create(
        body={
            "name": PROCESSED_FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_id],
        },
        fields="id",
    ).execute()
    return created["id"]


def list_pending_pdfs(service, root_id):
    """Return PDFs directly in the root folder, ignoring already-imported ones."""
    q = (
        f"'{root_id}' in parents and "
        "mimeType = 'application/pdf' and "
        "trashed = false"
    )
    fields = "nextPageToken, files(id,name,createdTime,size,webViewLink)"
    pending = []
    page_token = None
    while True:
        resp = service.files().list(
            q=q, fields=fields, pageSize=100, pageToken=page_token
        ).execute()
        for f in resp.get("files", []):
            if IMPORTED_PREFIX_RE.match(f.get("name", "")):
                continue
            pending.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return pending


def _download_bytes(service, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _rename_and_move(service, file_id, new_name, processed_folder_id):
    """Rename the file and move it from current parents to the Processed folder."""
    current = service.files().get(fileId=file_id, fields="parents").execute()
    old_parents = ",".join(current.get("parents", []))
    service.files().update(
        fileId=file_id,
        body={"name": new_name},
        addParents=processed_folder_id,
        removeParents=old_parents,
        fields="id,name,parents",
    ).execute()


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def import_pending():
    """Scan the configured Drive folder, import any new PDFs, return results.

    Each result dict:
      {
        "file_id": str,
        "filename": str,        # original name in Drive
        "new_name": str | None, # name after rename (None if not renamed)
        "invoice_id": int | None,
        "skipped": bool,        # already imported (hash hit), still renamed+moved
        "error": str | None,
      }
    """
    import invoice_extractor  # lazy: avoids loading anthropic on local dev

    root_id = config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
    if not root_id:
        raise RuntimeError(
            "GOOGLE_DRIVE_INVOICES_FOLDER_ID is not set — "
            "watcher has nowhere to look."
        )

    service = _drive_service()
    processed_id = _ensure_processed_folder(service, root_id)
    pending = list_pending_pdfs(service, root_id)

    results = []
    today_str = date.today().isoformat()

    invoice_extractor.ensure_invoices_dir()
    existing_hashes = {inv["file_hash"] for inv in db.list_invoices() if inv.get("file_hash")}

    for f in pending:
        file_id = f["id"]
        original_name = f.get("name", f"drive_{file_id[:8]}.pdf")
        result = {
            "file_id": file_id,
            "filename": original_name,
            "new_name": None,
            "invoice_id": None,
            "skipped": False,
            "error": None,
        }

        try:
            pdf_bytes = _download_bytes(service, file_id)
        except Exception as e:
            result["error"] = f"Download failed: {e}"
            results.append(result)
            continue

        # Save locally so we can hash + extract using existing pipeline
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r"[^\w.-]", "_", original_name)
            local_path = os.path.join(config.INVOICES_DIR, f"{stamp}_{safe}")
            with open(local_path, "wb") as out:
                out.write(pdf_bytes)
            fhash = invoice_extractor.file_hash(local_path)

            if fhash in existing_hashes:
                # Already imported via another path; just clean up Drive.
                os.remove(local_path)
                result["skipped"] = True
            else:
                data = invoice_extractor.extract_invoice(local_path)
                notes_parts = [
                    f"From Drive folder. AI confidence: {data.get('confidence', 'unknown')}.",
                    f"Drive link: {f.get('webViewLink', '')}".strip(),
                ]
                result["invoice_id"] = db.save_invoice({
                    "supplier_id":   data.get("supplier_id"),
                    "supplier_name": (data.get("supplier_name_canonical")
                                      or data.get("supplier_name") or "Unknown"),
                    "invoice_date":  data.get("invoice_date") or today_str,
                    "invoice_number": data.get("invoice_number"),
                    "net_amount":    float(data.get("net_amount") or 0),
                    "vat_amount":    float(data.get("vat_amount") or 0),
                    "total_amount":  float(data.get("total_amount") or 0),
                    "vat_rate":      float(data.get("vat_rate") or 23),
                    "category":      data.get("category"),
                    "source":        "drive",
                    "pdf_path":      local_path,
                    "file_hash":     fhash,
                    "status":        "pending",
                    "notes":         " ".join(p for p in notes_parts if p),
                })
                existing_hashes.add(fhash)
        except Exception as e:
            result["error"] = f"Extract/save failed: {e}"
            results.append(result)
            continue

        # Rename + move regardless (so root stays empty / tidy)
        try:
            new_name = f"[imported-{today_str}] {original_name}"
            if not new_name.lower().endswith(".pdf"):
                new_name += ".pdf"
            _rename_and_move(service, file_id, new_name, processed_id)
            result["new_name"] = new_name
        except Exception as e:
            # Rename/move failure shouldn't lose the import — just note it.
            result["error"] = (result["error"] or "") + f" Move failed: {e}"

        results.append(result)

    return results


def status_snapshot():
    """Quick read for the bookkeeping page status panel.

    Returns dict: {pending_count, root_url, processed_url, configured, error}.
    Doesn't import or move anything — safe to call on every page load.
    """
    snap = {
        "pending_count": None,
        "root_url": None,
        "processed_url": None,
        "configured": False,
        "error": None,
    }
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        snap["error"] = "GOOGLE_SERVICE_ACCOUNT_JSON not set"
        return snap

    root_id = config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
    if not root_id:
        snap["error"] = "GOOGLE_DRIVE_INVOICES_FOLDER_ID not set"
        return snap

    snap["configured"] = True
    snap["root_url"] = f"https://drive.google.com/drive/folders/{root_id}"

    try:
        service = _drive_service()
        pending = list_pending_pdfs(service, root_id)
        snap["pending_count"] = len(pending)

        q = (
            f"'{root_id}' in parents and "
            f"name = '{PROCESSED_FOLDER_NAME}' and "
            "mimeType = 'application/vnd.google-apps.folder' and "
            "trashed = false"
        )
        resp = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
        files = resp.get("files", [])
        if files:
            snap["processed_url"] = (
                f"https://drive.google.com/drive/folders/{files[0]['id']}"
            )
    except Exception as e:
        snap["error"] = str(e)

    return snap
