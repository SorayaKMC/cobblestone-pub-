"""Extract structured invoice data from PDFs using Claude API.

Workflow:
  1. Extract text from PDF with pdfplumber (fast, free).
  2. If text is short/empty (scanned PDF), fall back to Claude vision.
  3. Send text to Claude with structured JSON output schema.
  4. Parse response, match supplier to directory, fill defaults.
"""

import base64
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import config
import db


SYSTEM_PROMPT = """You extract invoice data from Irish supplier invoices for a Dublin pub.
Return ONLY a compact JSON object with these fields (no markdown, no prose):

{
  "supplier_name": "...",
  "invoice_date": "YYYY-MM-DD",
  "invoice_number": "...",
  "net_amount": 0.00,
  "vat_amount": 0.00,
  "total_amount": 0.00,
  "vat_rate": 23,
  "confidence": "high|medium|low"
}

Rules:
- All amounts in EUR as numbers (not strings).
- Irish VAT rates: 23% (standard), 13.5% (hospitality), 9% (reduced), 0% (exempt).
- If you see multiple VAT rates in one invoice, report the dominant one and sum the net/VAT.
- invoice_date must be ISO format. If unclear, use the issue date.
- Prefer cleaner totals (e.g., "Total EUR" or "Amount due") over subtotals.
- If any field can't be read reliably, use null and mark confidence "low".
- Supplier name should be the trading name, not legal entity (e.g., "BWG" not "BWG Foods Ireland Ltd").
"""


def _anthropic_client():
    """Lazy-import the Anthropic client so missing key doesn't break startup."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set - cannot extract invoices")
    from anthropic import Anthropic
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


def file_hash(filepath):
    """SHA256 hash of a file - used to dedupe uploads."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_whitespace(text):
    """Collapse layout padding so length checks and token budget reflect real content."""
    # Runs of spaces/tabs -> single space
    text = re.sub(r"[ \t]+", " ", text)
    # Spaces around newlines -> just the newline
    text = re.sub(r" *\n *", "\n", text)
    # 3+ blank lines -> 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(pdf_path):
    """Extract text from a PDF. Returns (text, used_vision_fallback)."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:5]:  # cap at first 5 pages to save tokens
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        text = _normalize_whitespace("\n\n".join(text_parts))
        # Measure by non-whitespace content so an invoice with heavy padding
        # still qualifies for text extraction instead of falling back to vision.
        meaningful = re.sub(r"\s+", "", text)
        if len(meaningful) > 50:
            return text, False
    except Exception as e:
        print(f"[extract] pdfplumber failed: {e}")
    return "", True


# Model names for this account's access tier
MODEL_TEXT = "claude-haiku-4-5-20251001"      # fast + cheap for text extraction
MODEL_VISION = "claude-sonnet-4-5-20250929"   # better for scanned/image PDFs


def extract_with_text(text):
    """Send extracted text to Claude for structured extraction."""
    client = _anthropic_client()
    resp = client.messages.create(
        model=MODEL_TEXT,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Extract from this invoice text:\n\n{text[:8000]}"}],
    )
    content = resp.content[0].text
    return _parse_json_response(content)


def extract_with_vision(pdf_path):
    """Fallback: send PDF directly to Claude vision model."""
    client = _anthropic_client()
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    b64 = base64.b64encode(pdf_bytes).decode()

    resp = client.messages.create(
        model=MODEL_VISION,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": "Extract invoice fields per the schema."},
            ],
        }],
    )
    content = resp.content[0].text
    return _parse_json_response(content)


def _parse_json_response(text):
    """Extract a JSON object from Claude's response text."""
    # Sometimes Claude wraps JSON in code fences - strip them
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"No JSON found in response: {text[:200]}")
    return json.loads(match.group())


def enrich_with_supplier(extracted):
    """Match extracted supplier name to directory + fill defaults."""
    name = (extracted.get("supplier_name") or "").strip()
    if not name:
        return extracted

    supplier = db.find_supplier_by_name(name)
    if supplier:
        extracted["supplier_id"] = supplier["id"]
        extracted["supplier_name_canonical"] = supplier["name"]
        if not extracted.get("category"):
            extracted["category"] = supplier["default_category"]
        if not extracted.get("vat_rate") and supplier["default_vat_rate"]:
            extracted["vat_rate"] = supplier["default_vat_rate"]
    return extracted


def extract_invoice(pdf_path):
    """Full pipeline: PDF -> text -> Claude -> enriched dict.

    Returns dict with keys expected by db.save_invoice(), plus metadata.
    """
    text, needs_vision = extract_pdf_text(pdf_path)
    meaningful_len = len(re.sub(r"\s+", "", text))
    if needs_vision or meaningful_len < 100:
        data = extract_with_vision(pdf_path)
    else:
        data = extract_with_text(text)

    data = enrich_with_supplier(data)
    data["source"] = "pdf_upload"
    data["file_hash"] = file_hash(pdf_path)
    data["pdf_path"] = str(pdf_path)
    data["status"] = "pending"  # always review before approving
    return data


def ensure_invoices_dir():
    """Make sure the upload folder exists."""
    Path(config.INVOICES_DIR).mkdir(parents=True, exist_ok=True)
    return config.INVOICES_DIR


def save_uploaded_pdf(upload_file):
    """Save a Flask FileStorage to disk with a sortable filename. Returns path."""
    ensure_invoices_dir()
    orig = upload_file.filename or "invoice.pdf"
    # Prefix with timestamp so files sort by upload order
    safe = re.sub(r"[^\w.-]", "_", orig)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(config.INVOICES_DIR, f"{stamp}_{safe}")
    upload_file.save(path)
    return path
