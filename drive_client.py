"""Google Drive client for auto-mirroring band promo uploads.

Uses the existing GOOGLE_SERVICE_ACCOUNT_JSON service account credentials
(same one used by calendar_client.py). The service account must be granted
'Editor' on GOOGLE_DRIVE_PROMOS_PARENT_ID via Drive's Share UI.

NO domain-wide delegation — straight service-account access to folders
that have been explicitly shared with its email.

All functions return None on failure and log to stdout, so a band upload
that succeeds locally won't be derailed by a Drive hiccup.
"""

import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config


SCOPES = ["https://www.googleapis.com/auth/drive"]


def _service():
    """Build an authenticated Drive v3 service or return None."""
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        print("[drive] GOOGLE_SERVICE_ACCOUNT_JSON not set — Drive disabled")
        return None
    try:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES,
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[drive] Failed to build service: {e}")
        return None


def _escape(name):
    """Escape a name for use in a Drive 'q' query."""
    return name.replace("\\", "\\\\").replace("'", "\\'")


def get_or_create_folder(service, parent_id, name):
    """Find or create a subfolder by name under parent_id. Returns id."""
    try:
        q = (
            f"name = '{_escape(name)}' and "
            f"'{parent_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        resp = service.files().list(q=q, fields="files(id, name)", pageSize=10).execute()
        items = resp.get("files", [])
        if items:
            return items[0]["id"]
        # Create new folder
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        f = service.files().create(body=meta, fields="id").execute()
        return f.get("id")
    except Exception as e:
        print(f"[drive] get_or_create_folder({name!r}) failed: {e}")
        return None


def upload_file(service, parent_id, local_path, filename, mime_type=None):
    """Upload a local file to a Drive folder. Returns the file dict or None."""
    try:
        media = MediaFileUpload(local_path, mimetype=mime_type or "application/octet-stream",
                                resumable=False)
        meta = {"name": filename, "parents": [parent_id]}
        f = service.files().create(
            body=meta,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
        return f
    except Exception as e:
        print(f"[drive] upload_file({filename!r}) failed: {e}")
        return None


def mirror_promo_upload(booking, local_path, filename, mime_type=None):
    """Mirror a band's poster upload to Google Drive.

    Builds the folder structure:
        Cobblestone Promos / <YYYY-MM> / <event_date> — <act_name> / <filename>

    Only mirrors bookings with a future event_date (no point mirroring posters
    for gigs that already happened — see Soraya's note 12 May 2026).

    Returns the act folder's URL (https://drive.google.com/drive/folders/<id>)
    on success, or None if mirroring was skipped/failed.

    Safe to call from inside the upload handler — never raises, only logs.
    """
    parent_id = config.GOOGLE_DRIVE_PROMOS_PARENT_ID
    if not parent_id:
        return None  # Not configured — skip silently

    # Skip past gigs — we only mirror upcoming ones
    try:
        from datetime import date
        ev_date = booking["event_date"]
        if ev_date < date.today().isoformat():
            return None
    except Exception:
        pass

    service = _service()
    if not service:
        return None

    try:
        month_str = booking["event_date"][:7]  # YYYY-MM
        month_folder_id = get_or_create_folder(service, parent_id, month_str)
        if not month_folder_id:
            return None

        # Folder name: "YYYY-MM-DD — Act Name" (cap length to avoid Drive limits)
        act_name = (booking["act_name"] or "Untitled").strip()
        act_folder_name = f"{booking['event_date']} — {act_name}"[:120]
        act_folder_id = get_or_create_folder(service, month_folder_id, act_folder_name)
        if not act_folder_id:
            return None

        # Upload the file itself
        uploaded = upload_file(service, act_folder_id, local_path, filename, mime_type)
        if not uploaded:
            return None

        url = f"https://drive.google.com/drive/folders/{act_folder_id}"
        print(f"[drive] Mirrored {filename!r} → booking #{booking['id']} folder")
        return url
    except Exception as e:
        print(f"[drive] mirror_promo_upload failed for booking #{booking['id']}: {e}")
        return None
