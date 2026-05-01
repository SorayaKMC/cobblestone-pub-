"""Convert each docs/*.md to a PDF for training/distribution.

Strategy:
  1. Render each markdown file to HTML with print-friendly styling.
  2. Use Chrome (headless) to convert each HTML to PDF.

Outputs:
  docs/pdfs/01-dashboard.pdf
  docs/pdfs/02-payroll-weekly.pdf
  ...
  docs/pdfs/Cobblestone-Training-Manual.pdf  (combined; all sections)

Usage (from repo root):
    python3 docs/build_pdfs.py

Requires:
  - markdown:    python3 -m pip install --user markdown
  - Google Chrome installed at the standard macOS location
    (for non-Mac, edit CHROME_PATH below)
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown


DOCS_DIR = Path(__file__).resolve().parent
PDF_DIR = DOCS_DIR / "pdfs"
PDF_DIR.mkdir(exist_ok=True)

# Where Chrome lives on macOS (default install). On Linux it might be
# /usr/bin/google-chrome; on Windows, the .exe path.
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

FILE_ORDER = [
    "SOP.md",
    "01-dashboard.md",
    "02-payroll-weekly.md",
    "03-payroll-accountant.md",
    "04-pto-tracker.md",
    "05-bookkeeping.md",
    "06-bookings.md",
    "07-settings.md",
    "08-new-manager-guide.md",
    "09-year-end-checklist.md",
]

TITLE_BY_FILE = {
    "SOP.md": "Standard Operating Procedure",
    "01-dashboard.md": "Dashboard",
    "02-payroll-weekly.md": "Payroll - Weekly Process",
    "03-payroll-accountant.md": "Payroll - Accountant Files",
    "04-pto-tracker.md": "PTO Tracker",
    "05-bookkeeping.md": "Bookkeeping & Invoices",
    "06-bookings.md": "Backroom Bookings",
    "07-settings.md": "Settings",
    "08-new-manager-guide.md": "New Manager Onboarding",
    "09-year-end-checklist.md": "Year-End Checklist",
    "README.md": "Cobblestone Pub Docs - Index",
}

CSS_STYLES = """
@page {
    size: A4;
    margin: 2cm;
}

@media print {
    @page :first {
        margin-top: 2cm;
    }
}

body {
    font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #222;
    max-width: 760px;
    margin: 0 auto;
    padding: 30px;
}

h1 {
    font-family: Georgia, serif;
    font-size: 22pt;
    color: #0f2318;
    border-bottom: 2px solid #0f2318;
    padding-bottom: 0.3em;
    margin-top: 0;
}

h2 {
    font-family: Georgia, serif;
    font-size: 15pt;
    color: #0f2318;
    margin-top: 1.5em;
    border-bottom: 1px solid #ccc;
    padding-bottom: 0.2em;
    page-break-after: avoid;
}

h3 {
    font-family: Georgia, serif;
    font-size: 12.5pt;
    color: #2c5b3f;
    margin-top: 1.2em;
    page-break-after: avoid;
}

p, li { font-size: 10.5pt; }

code {
    font-family: Menlo, "Courier New", monospace;
    background: #f4f4f4;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9.5pt;
}

pre {
    background: #f4f4f4;
    border-left: 3px solid #2c5b3f;
    padding: 8px 12px;
    overflow-x: auto;
    page-break-inside: avoid;
    white-space: pre-wrap;
    word-wrap: break-word;
}

pre code { background: none; padding: 0; font-size: 9pt; }

table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #ccc;
    padding: 6px 10px;
    text-align: left;
    font-size: 9.5pt;
    vertical-align: top;
}

th { background: #0f2318; color: #fff; }
tr:nth-child(even) td { background: #f9f9f9; }

a { color: #2c5b3f; text-decoration: none; }
blockquote {
    border-left: 3px solid #ccc;
    padding-left: 12px;
    color: #555;
    margin: 1em 0;
}
ul, ol { margin: 0.5em 0 0.5em 1.5em; }

.section-page-break { page-break-before: always; }

.cover {
    text-align: center;
    padding-top: 30%;
    page-break-after: always;
}
.cover h1 { font-size: 32pt; border: none; margin-bottom: 0.2em; }
.cover .subtitle { font-size: 14pt; color: #666; margin-bottom: 2em; }
.cover .meta { margin-top: 4em; color: #888; font-size: 10pt; }
"""


def md_to_html(md_text):
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
    )


def wrap_html(body_html, title):
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{title}</title>
<style>{CSS_STYLES}</style>
</head>
<body>{body_html}</body></html>"""


def html_to_pdf_with_chrome(html_path: Path, pdf_path: Path) -> bool:
    """Run Chrome headless to convert HTML to PDF. Returns True on success."""
    if not Path(CHROME_PATH).exists():
        return False
    cmd = [
        CHROME_PATH,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={pdf_path}",
        f"file://{html_path}",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        print(f"  Chrome failed: {result.stderr.strip()[:300]}")
        return False
    return pdf_path.exists() and pdf_path.stat().st_size > 0


def render_single(md_path: Path, out_path: Path, title: str, work_dir: Path):
    md_text = md_path.read_text(encoding="utf-8")
    body_html = md_to_html(md_text)
    html = wrap_html(body_html, title)
    html_path = work_dir / (md_path.stem + ".html")
    html_path.write_text(html, encoding="utf-8")
    if html_to_pdf_with_chrome(html_path, out_path):
        print(f"  wrote {out_path.relative_to(DOCS_DIR.parent)}")
    else:
        print(f"  Chrome conversion failed for {md_path.name}; HTML left at {html_path}")


def render_combined(out_path: Path, work_dir: Path):
    sections_html = [
        """<div class="cover">
            <h1>Cobblestone Pub<br>Management Portal</h1>
            <div class="subtitle">Operations Training Manual</div>
            <div class="meta">All sections in one document.<br>For the latest version, see the docs/ folder of the repo.</div>
        </div>"""
    ]
    for fname in FILE_ORDER:
        md_path = DOCS_DIR / fname
        if not md_path.exists():
            print(f"  skip (missing): {fname}")
            continue
        body = md_to_html(md_path.read_text(encoding="utf-8"))
        sections_html.append(f'<div class="section-page-break">{body}</div>')

    html = wrap_html("".join(sections_html), "Cobblestone Pub Training Manual")
    html_path = work_dir / "_combined.html"
    html_path.write_text(html, encoding="utf-8")
    if html_to_pdf_with_chrome(html_path, out_path):
        print(f"  wrote {out_path.relative_to(DOCS_DIR.parent)}")
    else:
        print(f"  Combined conversion failed; HTML left at {html_path}")


def main():
    if not Path(CHROME_PATH).exists():
        print(f"Chrome not found at {CHROME_PATH}.")
        print("Edit CHROME_PATH in this script to point at your Chrome binary,")
        print("or open each docs/*.md in a Markdown viewer and print to PDF.")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        print("Building per-section PDFs:")
        for fname in FILE_ORDER + ["README.md"]:
            md_path = DOCS_DIR / fname
            if not md_path.exists():
                continue
            out_path = PDF_DIR / fname.replace(".md", ".pdf")
            title = TITLE_BY_FILE.get(fname, fname)
            render_single(md_path, out_path, title, work_dir)

        print("\nBuilding combined training manual:")
        render_combined(PDF_DIR / "Cobblestone-Training-Manual.pdf", work_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
