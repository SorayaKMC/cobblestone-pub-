# Bookkeeping & Invoices

**URL:** `/bookkeeping`

## What it does

Captures every supplier invoice and turns it into a structured record
(supplier, date, net, VAT, total, category) that feeds VAT period totals
on the Dashboard.

There are **three intake paths** that all converge on the same place:

1. **Email at `invoice@cobblestonepub.ie`** — a background poller checks
   the inbox every 30 minutes, pulls PDF attachments out, runs them
   through Claude AI to extract structured fields, and saves them.
2. **Drive folder uploads** — drop any PDF directly into the configured
   Google Drive invoices folder. A background watcher imports it within
   30 minutes.
3. **Manual upload via the page** — the **Upload PDFs (AI)** button on
   the Bookkeeping page accepts up to 20 PDFs at a time.

### Invoices vs statements

Each PDF coming in is **classified** before processing:

- **Invoice** — a bill for a single transaction, with line items, VAT,
  invoice number, and total. Goes through the AI extractor and into the
  bookkeeping invoice list. Contributes to VAT period totals.
- **Statement** — a roll-up of multiple invoices ("here's everything we
  billed you this month + your outstanding balance"). Goes into the
  separate Statements module, accessible via the **Statements** button
  at the top of the Bookkeeping page. Statements do **not** feed VAT
  period totals — they're a record-keeping and reconciliation tool.

The classifier uses filename, email subject, and PDF text content. It's
**conservative** — when in doubt, treats the PDF as an invoice. If
something gets misclassified either way, you can fix it with one click:

- On an invoice: open it → **Actually a Statement** button
- On a statement: open it → **Actually an Invoice** button

Statements arrive at `invoice@` get filed in the **statements Drive
folder** (set via `GOOGLE_DRIVE_STATEMENTS_FOLDER_ID`). Invoices go to
the **invoices Drive folder**. Both have their own `Processed/`
subfolder where files end up after import.

Whichever path an invoice takes, it ends up:
- As a record in the bookkeeping list (status: Pending Review)
- As a stored PDF on disk + in the Drive invoices folder
- Renamed to `[imported-YYYY-MM-DD] {original}.pdf` and moved to the
  `Processed/` subfolder in Drive (Drive watcher path; the email poller
  uploads with the original name and the watcher tidies it up next pass)

## How to use it (daily / weekly)

### When invoices arrive

You don't need to do anything proactive. Suppliers email
`invoice@cobblestonepub.ie` (or you forward from `info@`); the system
pulls them in. You'll see them appear on the Bookkeeping page.

### Reviewing pending invoices

1. Open **`/bookkeeping`**.
2. Filter by **Status = Pending** if the list is large.
3. For each row:
   - Click the supplier name → opens the invoice form with extracted
     fields pre-filled.
   - Verify supplier, date, net/VAT/total amounts, and category.
   - Adjust anything wrong (Claude is good but not infallible).
   - Change status to **Approved**. Save.

### When suppliers email the wrong address

If a supplier emails `info@cobblestonepub.ie` instead of `invoice@`, set
up a one-time **Gmail filter** on `info@`:

1. Gmail → Settings → Filters and Blocked Addresses → Create new filter.
2. From: `accounts@thatsupplier.com` (or whatever).
3. Has attachment, filename contains `pdf` (optional, narrows further).
4. Forward to: `invoice@cobblestonepub.ie`.

Now their invoices auto-route to the right inbox.

### When someone hands you a paper invoice

1. Scan to PDF.
2. Either:
   - Drop the PDF directly into the Drive invoices folder, or
   - Click **Upload PDFs (AI)** on the Bookkeeping page and select it.

Either way, it's imported automatically.

## Page sections

1. **Drive watcher status panel** — at the top, shows the count of PDFs
   pending in the root of the invoices folder, links to the folder and
   the Processed subfolder, and the last scan time + result. **Scan
   Drive Now** triggers an immediate scan.
2. **Monthly Input VAT** — current-year monthly totals, used by the
   Dashboard's VAT period KPI.
3. **Filters** — date range, supplier, category, status.
4. **Invoices table** — all matching invoices, totals at the bottom.

## Status values

- **Pending Review** — newly imported, hasn't been verified by a human
- **Approved** — confirmed correct, counts toward VAT period totals
- **Rejected** — duplicates, errors, junk PDFs

## Common questions

- **An invoice shows "Unknown" supplier:** Claude couldn't identify the
  supplier from the PDF. Open the invoice, type the right name, save.
- **AI confidence is "low":** the extraction wasn't certain. Always
  human-review low-confidence invoices before approving.
- **Why are some PDFs in the folder still in root?** The watcher only
  runs every 30 minutes. Click **Scan Drive Now** to trigger immediately.
- **A duplicate appeared:** dedup is by file hash. If a supplier sent
  the same PDF twice (e.g. once to `info@`, once forwarded to
  `invoice@`), it's deduped automatically. If two slightly different
  PDFs of the same invoice both got imported, mark one as Rejected.

## When something looks wrong

- **Drive watcher panel shows red error:**
  - "GOOGLE_DRIVE_INVOICES_FOLDER_ID not set" → set the env var on
    Render.
  - "Drive API has not been used in project ..." → enable the Drive
    API in Google Cloud Console for that project.
  - "insufficient authentication scopes" → add `drive` scope to the
    domain-wide delegation in Workspace Admin.
- **Email poller not picking up new invoices:**
  - Check Render's cobblestone-pub logs for `[gmail]` lines.
  - Verify `GOOGLE_SERVICE_ACCOUNT_JSON` is set and valid.
  - Verify the service account is authorised for `gmail.modify` scope
    in Workspace Admin.
- **Drive uploads failing with 403:** verify `info@cobblestonepub.ie`
  has Editor access on the invoices folder. Right-click the folder in
  Drive → Share → confirm.
