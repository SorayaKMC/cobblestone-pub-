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
    """Scan both the invoices and statements Drive folders for new PDFs.

    Behaviour by folder:
      - INVOICES folder: classify each PDF. If it's actually a statement,
        save the statement record + move the PDF straight to the statements
        folder's Processed subfolder. If it's an invoice, run the existing
        Claude extractor + save invoice record.
      - STATEMENTS folder: skip classification (whatever's here is presumed
        to be a statement). Save statement record. Move to Processed.

    Existing month-organised subfolders in either root are left untouched.

    Each result dict:
      {
        "file_id": str,
        "filename": str,
        "new_name": str | None,
        "kind": "invoice" | "statement",
        "invoice_id": int | None,
        "statement_id": int | None,
        "skipped": bool,
        "error": str | None,
      }
    """
    invoices_root = config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
    if not invoices_root:
        raise RuntimeError(
            "GOOGLE_DRIVE_INVOICES_FOLDER_ID is not set — "
            "watcher has nowhere to look."
        )

    service = _drive_service()
    results = []

    # --- Process invoices folder (with classification) ---
    invoices_processed = _ensure_processed_folder(service, invoices_root)
    statements_root = config.GOOGLE_DRIVE_STATEMENTS_FOLDER_ID
    statements_processed = (_ensure_processed_folder(service, statements_root)
                            if statements_root else None)

    for f in list_pending_pdfs(service, invoices_root):
        results.append(_process_drive_pdf(
            service, f, source_kind="invoices",
            invoices_processed=invoices_processed,
            statements_processed=statements_processed,
        ))

    # --- Process statements folder (no classification) ---
    if statements_root:
        for f in list_pending_pdfs(service, statements_root):
            results.append(_process_drive_pdf(
                service, f, source_kind="statements",
                invoices_processed=invoices_processed,
                statements_processed=statements_processed,
            ))

    return results


def _process_drive_pdf(service, f, source_kind, invoices_processed, statements_processed):
    """Process a single PDF from Drive. source_kind is 'invoices' or 'statements'."""
    import invoice_extractor
    import statement_detector

    file_id = f["id"]
    original_name = f.get("name", f"drive_{file_id[:8]}.pdf")
    today_str = date.today().isoformat()
    result = {
        "file_id": file_id,
        "filename": original_name,
        "new_name": None,
        "kind": "invoice" if source_kind == "invoices" else "statement",
        "invoice_id": None,
        "statement_id": None,
        "skipped": False,
        "error": None,
    }

    try:
        pdf_bytes = _download_bytes(service, file_id)
    except Exception as e:
        result["error"] = f"Download failed: {e}"
        return result

    try:
        invoice_extractor.ensure_invoices_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^\w.-]", "_", original_name)
        local_path = os.path.join(config.INVOICES_DIR, f"{stamp}_{safe}")
        with open(local_path, "wb") as out:
            out.write(pdf_bytes)
        fhash = invoice_extractor.file_hash(local_path)
    except Exception as e:
        result["error"] = f"Local save failed: {e}"
        return result

    # Classify (only if from the invoices folder; statements folder is trusted)
    if source_kind == "invoices":
        try:
            classification = statement_detector.classify(local_path, filename=original_name)
        except Exception:
            classification = {"kind": "invoice", "confidence": "low",
                              "signals": [], "extracted": {}}
        result["kind"] = classification["kind"]
    else:
        classification = {"kind": "statement", "confidence": "high",
                          "signals": ["located in statements folder"], "extracted": {}}

    # --- Statement path ---
    if classification["kind"] == "statement":
        if db.get_statement_by_hash(fhash):
            try: os.remove(local_path)
            except OSError: pass
            result["skipped"] = True
        else:
            extracted = classification.get("extracted") or {}
            try:
                result["statement_id"] = db.save_statement({
                    "supplier_id": None,
                    "supplier_name": extracted.get("supplier_name") or "Unknown",
                    "statement_date": extracted.get("statement_date"),
                    "total_balance": extracted.get("total_balance"),
                    "pdf_path": local_path,
                    "file_hash": fhash,
                    "drive_url": f.get("webViewLink"),
                    "source": "drive",
                    "status": "pending",
                    "detection_signals": "; ".join(classification.get("signals", [])),
                    "notes": (f"From Drive ({source_kind} folder). "
                              f"Confidence: {classification.get('confidence')}."),
                })
            except Exception as e:
                result["error"] = f"Save statement failed: {e}"

        # Move to statements Processed folder if available, else
        # leave a note. Falls back to invoices Processed if statements
        # folder isn't configured.
        target_processed = statements_processed or invoices_processed
        try:
            new_name = f"[imported-{today_str}] {original_name}"
            if not new_name.lower().endswith(".pdf"):
                new_name += ".pdf"
            _rename_and_move(service, file_id, new_name, target_processed)
            result["new_name"] = new_name
        except Exception as e:
            result["error"] = (result["error"] or "") + f" Move failed: {e}"
        return result

    # --- Invoice path ---
    existing_hashes = {inv["file_hash"] for inv in db.list_invoices() if inv["file_hash"]}
    try:
        if fhash in existing_hashes:
            try: os.remove(local_path)
            except OSError: pass
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
    except Exception as e:
        result["error"] = f"Extract/save failed: {e}"

    try:
        new_name = f"[imported-{today_str}] {original_name}"
        if not new_name.lower().endswith(".pdf"):
            new_name += ".pdf"
        _rename_and_move(service, file_id, new_name, invoices_processed)
        result["new_name"] = new_name
    except Exception as e:
        result["error"] = (result["error"] or "") + f" Move failed: {e}"
    return result


def deep_scan_year(year):
    """Recursively walk the entire invoices Drive folder tree (including
    every subfolder, e.g. month-organised archives) and import any PDFs
    we don't already have in the bookkeeping DB by hash.

    Designed for one-time historical recovery — the regular Drive watcher
    only scans the root of the invoices folder. This sweeps everything.

    Files are NOT moved or renamed (these are historical archives; we
    leave the user's organisation alone). Only new ones get imported.

    Sets cache key 'drive_deep_scan_progress' so the audit page can show
    progress + final summary.
    """
    import invoice_extractor
    import statement_detector
    from datetime import datetime as _dt

    root_id = config.GOOGLE_DRIVE_INVOICES_FOLDER_ID
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_INVOICES_FOLDER_ID is not set.")

    db.set_cache("drive_deep_scan_progress", {
        "started_at": _dt.now().isoformat(),
        "status": "scanning",
        "year": year,
        "scanned": 0,
        "imported_invoices": 0,
        "imported_statements": 0,
        "skipped_dupes": 0,
        "errors": 0,
    })

    service = _drive_service()

    # Walk the tree to enumerate all PDFs
    pdfs = []
    folders_to_visit = [root_id]
    visited = set()
    while folders_to_visit:
        current = folders_to_visit.pop()
        if current in visited:
            continue
        visited.add(current)
        page_token = None
        while True:
            try:
                resp = service.files().list(
                    q=f"'{current}' in parents and trashed = false",
                    fields="nextPageToken, files(id,name,mimeType,parents,createdTime,webViewLink)",
                    pageSize=100,
                    pageToken=page_token,
                ).execute()
            except Exception as e:
                print(f"[deep-scan] folder {current} listing failed: {e}")
                break
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    folders_to_visit.append(f["id"])
                elif f["mimeType"] == "application/pdf":
                    pdfs.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    db.set_cache("drive_deep_scan_progress", {
        "started_at": _dt.now().isoformat(),
        "status": "processing",
        "year": year,
        "found_pdfs": len(pdfs),
        "scanned": 0,
        "imported_invoices": 0,
        "imported_statements": 0,
        "skipped_dupes": 0,
        "errors": 0,
    })

    invoice_extractor.ensure_invoices_dir()
    existing_invoice_hashes = {inv["file_hash"] for inv in db.list_invoices() if inv["file_hash"]}

    counts = {"scanned": 0, "imported_invoices": 0, "imported_statements": 0,
              "skipped_dupes": 0, "errors": 0}

    for f in pdfs:
        counts["scanned"] += 1
        # Update progress every 10 files so the user can see movement
        if counts["scanned"] % 10 == 0:
            _update_deep_scan_progress(counts, "processing", year, len(pdfs))

        file_id = f["id"]
        original_name = f.get("name", f"drive_{file_id[:8]}.pdf")

        # Skip files in our own Processed subfolder — those have already been
        # processed by the regular watcher.
        if "[imported-" in original_name:
            counts["skipped_dupes"] += 1
            continue

        try:
            pdf_bytes = _download_bytes(service, file_id)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r"[^\w.-]", "_", original_name)
            local_path = os.path.join(config.INVOICES_DIR, f"deep_{stamp}_{safe}")
            with open(local_path, "wb") as out:
                out.write(pdf_bytes)
            fhash = invoice_extractor.file_hash(local_path)
        except Exception as e:
            counts["errors"] += 1
            print(f"[deep-scan] download failed {original_name}: {e}")
            continue

        # Already imported? (hash match in invoices or statements)
        if fhash in existing_invoice_hashes or db.get_statement_by_hash(fhash):
            try: os.remove(local_path)
            except OSError: pass
            counts["skipped_dupes"] += 1
            continue

        # Classify and import
        try:
            classification = statement_detector.classify(local_path, filename=original_name)
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
                    "drive_url": f.get("webViewLink"),
                    "source": "drive-deep-scan",
                    "status": "pending",
                    "detection_signals": "; ".join(classification.get("signals", [])),
                    "notes": f"Imported via deep-scan from {original_name}",
                })
                counts["imported_statements"] += 1
            else:
                data = invoice_extractor.extract_invoice(local_path)
                inv_id = db.save_invoice({
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
                    "source":        "drive-deep-scan",
                    "pdf_path":      local_path,
                    "file_hash":     fhash,
                    "status":        "pending",
                    "notes":         f"Imported via deep-scan from {original_name}. "
                                     f"AI confidence: {data.get('confidence','unknown')}.",
                })
                counts["imported_invoices"] += 1
                existing_invoice_hashes.add(fhash)
        except Exception as e:
            counts["errors"] += 1
            print(f"[deep-scan] extract/save failed {original_name}: {e}")

    _update_deep_scan_progress(counts, "completed", year, len(pdfs))
    return counts


def _update_deep_scan_progress(counts, status, year, total):
    from datetime import datetime as _dt
    payload = dict(counts)
    payload.update({
        "status": status,
        "year": year,
        "found_pdfs": total,
        "ts": _dt.now().isoformat(),
    })
    db.set_cache("drive_deep_scan_progress", payload)


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
