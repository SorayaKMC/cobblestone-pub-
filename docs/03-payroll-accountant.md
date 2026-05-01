# Payroll — Accountant Files

**URL:** `/payroll/accountant`

## What it does

After the weekly Peter Excel is sent and Peter returns the **gross-to-net
summary** plus the **combined payslips** (one PDF page per employee), this
page handles everything that follows:

- Parses the gross-to-net summary and saves each employee's net pay.
- Splits the combined payslips PDF into one PDF per employee.
- Creates a Gmail draft per employee in `info@cobblestonepub.ie` with their
  payslip attached and a personalised body that includes their PTO summary
  for the week (staff and management; upper management gets the same email
  minus the leave block).

You review the drafts in Gmail and click Send when happy.

## How to use it

### First time only — one-time setup

- Make sure each employee has an email on file. The fastest way is on
  Settings → click **Sync from Square** — pulls in any emails set on the
  Square team profile. Anyone missing an email will be skipped during
  draft generation.

### Every week, after Peter replies

1. **Open `/payroll/accountant`** for the current week (or click the
   **Accountant Files** button on the Payroll page).
2. **Section 1 — Upload Peter's PDFs**
   - Gross-to-Net (Short) PDF
   - Combined Payslips PDF (one page per employee)
   - Click **Upload & Parse**.
3. **Section 2 — Confirm Employee Mappings**
   - The system matches each row to a Cobblestone employee using the
     reference number Peter assigns (1, 12, 18, ...). After the first
     successful run, the mapping is remembered, so future weeks auto-match
     without you doing anything.
   - First-time runs will have ~5 unmapped rows because of name spelling
     differences (e.g. PDF says "Maclnnes" with lowercase L; database has
     "MacInnes" with capital I). Pick the right person from the dropdown
     for each yellow row, then click **Save Mappings**.
   - The "View" link on each row opens that person's split payslip PDF in
     a new tab — useful for double-checking before Generate Drafts.
4. **Section 3 — Generate Email Drafts**
   - Disabled until every row is mapped.
   - First click **Test Gmail Connection** (just creates a self-addressed
     test draft to verify auth — delete it from Gmail Drafts after).
   - Then click **Generate Drafts**. One Gmail draft is created per employee
     in `info@cobblestonepub.ie` with:
     - Subject: `Cobblestone Pub - Payslip Week N, period ending DD/MM/YYYY`
     - Body filled in with their PTO accrual + balance for staff/management
     - Their split payslip PDF attached
5. **Review and send in Gmail**
   - Open Gmail at `info@cobblestonepub.ie` → Drafts.
   - Walk through each draft, confirm the recipient and attachment look
     right, click Send.
   - If anything's wrong, edit in Gmail before sending.

## Columns on the Mappings table

| Column                   | What it shows                                         |
|--------------------------|-------------------------------------------------------|
| Ref                      | Peter's payroll reference number (the match key)      |
| Name on Payslip          | Exact text from Peter's PDF (Mr/Ms titles included)   |
| Cobblestone Employee     | Dropdown — pick the matching person from your DB      |
| Gross / Net              | Read from the gross-to-net PDF                        |
| Payslip                  | View link → opens that person's one-page PDF          |

## Behind the scenes

- Net Pay shows up as a read-only column on the regular Payroll page once
  you've uploaded for that week.
- Per-employee payslip PDFs are stored as BLOBs in SQLite, keyed by pay
  period and employee. They survive deploys.
- Drafts use the Gmail API via the same service account already authorised
  for the invoice tracker. Only `info@` is impersonated for drafts.

## Common questions

- **Why drafts and not direct send?** Deliberate. Lets you eyeball each
  email before it goes out. Once you trust the workflow, sending all 13
  drafts takes about 90 seconds.
- **Can I re-upload after generating drafts?** Yes — re-uploading replaces
  the parsed data for that week. You'll need to re-generate drafts if the
  net amounts changed. Existing drafts in Gmail are not auto-deleted; clean
  them up manually.
- **Upper management see the leave block?** No. Categorisation happens
  automatically based on the Settings page Category column.

## When something looks wrong

- **"Test Gmail Connection" fails with `unauthorized_client`:**
  domain-wide delegation hasn't propagated. Wait 2-5 min and retry. If
  persistent, check Workspace Admin → Domain Wide Delegation has the
  `gmail.modify` scope authorised.
- **Mappings show "unmapped" yellow even after saving:** the employee
  probably has a different `team_member_id` than the saved mapping
  (e.g. recreated in Square). Pick from the dropdown again and re-save.
- **A draft is missing:** the employee has no email on Settings (skipped),
  or there's no payslip PDF for that ref (the combined PDF was
  incomplete). Check the results panel for the specific reason.
