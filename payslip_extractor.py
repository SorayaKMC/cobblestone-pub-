"""Parse the accountant's PDFs sent after weekly payroll.

Two inputs:
  1. Gross-to-Net summary — one row per employee with ref, name, and 10 numeric
     columns ending in Net Pay.
  2. Combined payslips — one page per employee, with a 'No./Ref : N / N' header
     and a 'Name : Full Name' header.

Both inputs share a ref number that is the reliable match key — names appear
in inconsistent orders across employees (e.g. 'Mr Thomas Mulligan' vs
'Mc Mahon Soraya').
"""

import io
import re
from datetime import datetime

import pdfplumber
from pypdf import PdfReader, PdfWriter


# --- Gross-to-Net summary ---

# A name line looks like: " 1 1 Mr Thomas Mulligan" — leading whitespace, the
# ref number twice, then the name (title optional). Some employees have no
# title; surnames may contain spaces (e.g. 'O Maolagain', 'Mc Mahon').
_NAME_RE = re.compile(r"^\s*(\d+)\s+\1\s+(.+?)\s*$")

# A numeric data line has 10 floats, possibly with leading whitespace.
_NUM_RE = re.compile(
    r"^\s*"
    + r"\s+".join([r"(-?\d+\.\d+)"] * 10)
    + r"\s*$"
)

_PERIOD_RE = re.compile(r"Pay Period\s*:\s*(.+)")


def parse_gross_to_net(pdf_path):
    """Extract per-employee rows + the period label from the gross-to-net PDF.

    Returns:
        {
          "period_label": "Week 18 01/05/2026",
          "rows": [
            {
              "ref": "1",
              "raw_name": "Mr Thomas Mulligan",
              "gross_pay": 989.21,
              "notional_pay": 0.00,
              "employee_pension": 0.00,
              "tax_due": 322.90,
              "employee_prsi": 0.00,
              "usc_due": 16.31,
              "lpt_due": 0.00,
              "net_adjustment": 0.00,
              "net_pay": 650.00,
              "employer_prsi": 0.00,
            },
            ...
          ]
        }
    """
    period_label = None
    rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                if period_label is None:
                    m = _PERIOD_RE.search(line)
                    if m:
                        period_label = m.group(1).strip()

                name_match = _NAME_RE.match(line)
                if name_match:
                    # Find the next numeric line (skip blanks)
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines):
                        num_match = _NUM_RE.match(lines[j])
                        if num_match:
                            nums = [float(x) for x in num_match.groups()]
                            rows.append({
                                "ref": name_match.group(1),
                                "raw_name": name_match.group(2),
                                "gross_pay": nums[0],
                                "notional_pay": nums[1],
                                "employee_pension": nums[2],
                                "tax_due": nums[3],
                                "employee_prsi": nums[4],
                                "usc_due": nums[5],
                                "lpt_due": nums[6],
                                "net_adjustment": nums[7],
                                "net_pay": nums[8],
                                "employer_prsi": nums[9],
                            })
                            i = j + 1
                            continue
                i += 1

    return {"period_label": period_label, "rows": rows}


# --- Combined payslips ---

_SLIP_REF_RE = re.compile(r"No\./Ref\s*:\s*(\d+)\s*/\s*\1")
_SLIP_NAME_RE = re.compile(r"Name\s*:\s*(.+?)\s*$", re.MULTILINE)
_SLIP_DATE_RE = re.compile(r"Date\s*:\s*(\d{1,2}\s+\w+\s+\d{4})")
_SLIP_PERIOD_RE = re.compile(r"Period\s*:\s*(.+?)\s*$", re.MULTILINE)

# Match the 'Basic Rate' line which carries hours worked.
# Format: "G Basic Rate 1 22.67 17.000 385.39 1613.98 T"
#         (G | Basic Rate | hours | rate | amount | YTD | flag)
_SLIP_HOURS_RE = re.compile(
    r"G\s+Basic\s+Rate\s+\d+\s+([\d.]+)\s+[\d.]+\s+[\d.,]+",
    re.IGNORECASE,
)


def _extract_hours_from_payslip_text(text):
    """Extract hours worked from a payslip page. Returns float or None.

    Sums all 'Basic Rate N' lines on the page (some employees have
    multiple rate tiers — e.g. one row at €17/hr plus another at €20/hr
    overtime).
    """
    if not text:
        return None
    total = 0.0
    found = False
    for m in _SLIP_HOURS_RE.finditer(text):
        try:
            total += float(m.group(1))
            found = True
        except ValueError:
            continue
    return total if found else None


def split_payslips(pdf_path):
    """Split the combined payslip PDF into one PDF per employee.

    Each output is a single-page PDF, keyed by ref. Returns:
        [
          {
            "ref": "1",
            "raw_name": "Thomas Mulligan",
            "period": "Week 18 26",
            "pay_date": "01 May 2026",
            "pdf_bytes": <bytes>,
          },
          ...
        ]
    """
    results = []
    reader = PdfReader(pdf_path)

    with pdfplumber.open(pdf_path) as plumber_pdf:
        for page_idx, page in enumerate(plumber_pdf.pages):
            text = page.extract_text() or ""
            ref_match = _SLIP_REF_RE.search(text)
            name_match = _SLIP_NAME_RE.search(text)
            date_match = _SLIP_DATE_RE.search(text)
            period_match = _SLIP_PERIOD_RE.search(text)

            if not ref_match or not name_match:
                continue

            writer = PdfWriter()
            writer.add_page(reader.pages[page_idx])
            buf = io.BytesIO()
            writer.write(buf)
            pdf_bytes = buf.getvalue()

            hours_worked = _extract_hours_from_payslip_text(text)

            results.append({
                "ref": ref_match.group(1),
                "raw_name": name_match.group(1).strip(),
                "period": period_match.group(1).strip() if period_match else None,
                "pay_date": date_match.group(1) if date_match else None,
                "hours_worked": hours_worked,
                "pdf_bytes": pdf_bytes,
            })

    return results


def parse_period_label(period_label):
    """Parse 'Week 18 01/05/2026' into (week_num, pay_date_iso, year)."""
    if not period_label:
        return None, None, None
    m = re.match(r"Week\s+(\d+)\s+(\d{2})/(\d{2})/(\d{4})", period_label.strip())
    if not m:
        return None, None, None
    week = int(m.group(1))
    pay_date = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
    return week, pay_date, int(m.group(4))


def period_end_from_pay_date(pay_date_iso):
    """Sunday on or before the pay date — 'period ending' as shown in emails."""
    d = datetime.strptime(pay_date_iso, "%Y-%m-%d").date()
    days_back = (d.weekday() - 6) % 7  # Mon=0 .. Sun=6
    from datetime import timedelta
    return (d - timedelta(days=days_back)).isoformat()
