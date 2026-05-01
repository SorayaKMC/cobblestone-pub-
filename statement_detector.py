"""Decide whether a PDF is an INVOICE or a STATEMENT.

A statement is a roll-up of multiple invoices ("here are all the bills we've
sent you this period and your outstanding balance"). It looks superficially
like an invoice but if processed as one it pollutes the bookkeeping VAT
totals.

Strategy: combine signals from filename, optional email subject, and PDF text.
Conservative threshold — default to "invoice" unless we see clear statement
indicators. Returns:

    {
        "kind": "invoice" | "statement",
        "confidence": "high" | "medium" | "low",
        "signals": [str, ...],     # human-readable reasons
        "extracted": {             # best-effort metadata if statement
            "supplier_name": str | None,
            "statement_date": str | None,    # ISO if found
            "total_balance":  float | None,
        }
    }
"""

import os
import re
from datetime import datetime

import pdfplumber


# --- Signal definitions -----------------------------------------------------

# Strong: any one of these is a high-confidence statement marker
_STRONG_FILENAME_KWS = ("statement", "stmt", "soa", "account_summary", "account-summary")
_STRONG_TEXT_KWS = (
    "statement of account",
    "account statement",
    "balance forward",
    "aged balance",
    "aged debtors",
    "outstanding balance",
)

# Medium: needs another signal alongside it to reach the threshold
_MEDIUM_SUBJECT_KWS = ("statement", "account summary", "monthly statement")
_INVOICE_REF_RE = re.compile(r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*\S+", re.IGNORECASE)
_AS_OF_RE = re.compile(r"as\s+of\s+\d{1,2}[/\-\.\s]\w+[/\-\.\s]\d{2,4}", re.IGNORECASE)

# Statement scoring: strong = 2 pts, medium = 1 pt. >= 2 pts = statement.
_THRESHOLD = 2

# --- Public API -------------------------------------------------------------

def classify(pdf_path, filename=None, email_subject=None):
    """Classify a PDF. See module docstring for return shape."""
    fname = filename or os.path.basename(pdf_path)
    fname_lower = fname.lower()
    signals = []
    score = 0

    # --- Filename signals (strong) ---
    for kw in _STRONG_FILENAME_KWS:
        if kw in fname_lower:
            signals.append(f"filename contains '{kw}' (+2)")
            score += 2
            break  # one filename hit is enough

    # --- Email subject signals (medium) ---
    if email_subject:
        subj_lower = email_subject.lower()
        for kw in _MEDIUM_SUBJECT_KWS:
            if kw in subj_lower:
                signals.append(f"subject contains '{kw}' (+1)")
                score += 1
                break

    # --- PDF text signals ---
    text = _extract_text(pdf_path, max_pages=3)
    text_lower = text.lower()

    # Strong text signals: each is +2
    for kw in _STRONG_TEXT_KWS:
        if kw in text_lower:
            signals.append(f"text contains '{kw}' (+2)")
            score += 2
            # Don't break — multiple strong signals should reinforce confidence

    # Multiple invoice references = likely a statement listing several invoices
    invoice_refs = _INVOICE_REF_RE.findall(text)
    if len(invoice_refs) >= 4:
        signals.append(f"text has {len(invoice_refs)} 'Invoice No' refs (+2)")
        score += 2
    elif len(invoice_refs) == 3:
        signals.append("text has 3 'Invoice No' refs (+1)")
        score += 1

    # "as of [date]" + balance language = statement-style summary
    if _AS_OF_RE.search(text) and "balance" in text_lower:
        signals.append("'as of [date]' near balance language (+1)")
        score += 1

    # --- Decide ---
    if score >= _THRESHOLD:
        confidence = "high" if score >= 4 else "medium"
        kind = "statement"
    else:
        confidence = "high" if score == 0 else "medium"
        kind = "invoice"

    extracted = _extract_statement_metadata(text) if kind == "statement" else {}

    return {
        "kind": kind,
        "confidence": confidence,
        "score": score,
        "signals": signals,
        "extracted": extracted,
    }


# --- Internals --------------------------------------------------------------

def _extract_text(pdf_path, max_pages=3):
    try:
        with pdfplumber.open(pdf_path) as pdf:
            chunks = []
            for page in pdf.pages[:max_pages]:
                t = page.extract_text() or ""
                chunks.append(t)
            return "\n".join(chunks)
    except Exception:
        return ""


_DATE_PATTERNS = [
    # 12/04/2026, 12-04-2026, 12 04 2026
    (re.compile(r"\b(\d{1,2})[/\-\s](\d{1,2})[/\-\s](\d{4})\b"),
     lambda m: f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"),
    # 2026-04-12 (already ISO-ish)
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
     lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
    # 12 April 2026
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"),
     lambda m: _try_named_month(m.group(1), m.group(2), m.group(3))),
]

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"]
)}


def _try_named_month(d, mon, y):
    mn = _MONTHS.get(mon.lower()[:3].rstrip(".") + mon.lower()[3:].rstrip("."))
    # Fall back to just first 3 chars
    if not mn:
        mn = _MONTHS.get(mon.lower()[:9])  # e.g. "September"
    if not mn:
        # Manual short-form lookup
        short = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                 "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
        mn = short.get(mon.lower()[:4].rstrip("."))
        if not mn:
            mn = short.get(mon.lower()[:3])
    if not mn:
        return None
    try:
        return f"{int(y):04d}-{int(mn):02d}-{int(d):02d}"
    except Exception:
        return None


def _extract_statement_metadata(text):
    """Best-effort: pull supplier, statement date, total balance from text."""
    extracted = {
        "supplier_name": None,
        "statement_date": None,
        "total_balance": None,
    }

    # Supplier — usually one of the first non-empty lines
    for line in text.splitlines()[:10]:
        s = line.strip()
        if not s or s.lower().startswith("statement"):
            continue
        if len(s) > 3 and len(s) < 60 and not any(c.isdigit() for c in s[:6]):
            extracted["supplier_name"] = s
            break

    # Statement date — look near "Statement Date" or "as of"
    date_context_re = re.compile(
        r"(?:statement\s+date|as\s+of|date)[:\s]+([\w\s\-/\.,]{6,30})",
        re.IGNORECASE,
    )
    m = date_context_re.search(text)
    if m:
        candidate = m.group(1)
        for pat, fmt in _DATE_PATTERNS:
            dm = pat.search(candidate)
            if dm:
                iso = fmt(dm)
                if iso:
                    extracted["statement_date"] = iso
                    break

    # Total balance — look for "Total Outstanding", "Balance Due", "Total"
    balance_re = re.compile(
        r"(?:total\s+outstanding|balance\s+due|outstanding\s+balance|total\s+owed|amount\s+due|total)\s*[:€£\$]*\s*([\d,]+\.\d{2})",
        re.IGNORECASE,
    )
    m = balance_re.search(text)
    if m:
        try:
            extracted["total_balance"] = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return extracted
