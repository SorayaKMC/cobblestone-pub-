# Settings

**URL:** `/settings`

## What it does

The Settings page is the master employee directory. Every other module
(Payroll, PTO, Accountant Files, Email Drafts) reads from here.

For each employee it stores:

- **First / Last name** — synced from Square; read-only locally
- **Category** — `Upper Management`, `Management`, `Staff`. Drives:
  - Payroll grouping and labour-cost subtotals on the Dashboard
  - Whether they get a PTO leave summary in payslip emails (Upper
    Management is excluded; they don't accrue)
- **Pay Type** — Hourly or Salaried. Drives how Gross is computed on
  the Payroll page (hours × rate, or fixed weekly salary)
- **Weekly Salary** — only used for Salaried staff
- **Cleaning (€/wk)** — default cleaning allowance; can be overridden
  per-week on the Payroll page
- **Email** — used for payslip Gmail drafts. If empty, that employee
  is skipped during draft generation.
- **Former?** — checkbox; ticking it greys out the employee on the
  PTO summary and removes them from the Log Leave dropdown. Their
  history is preserved.

## How to use it

### When a new employee joins

1. Add them in **Square** first (Team → New Team Member). Set their
   pay type, hourly rate or salary, and **email address**.
2. Open `/settings` → click **Sync from Square** at the top right.
3. They'll appear at the bottom of the table as **Staff** by default.
4. Adjust their Category if they're Management or Upper Management.
5. Set Cleaning (€/wk) if applicable. Save Changes.

### When someone leaves

1. Tick the **Former?** checkbox for that employee.
2. Save Changes.
3. They're now greyed out, sorted to the bottom of the PTO list, and
   removed from the active payroll calculations going forward. History
   stays intact.

### When an employee's email changes

Update it on **Square** first, then click Sync from Square. Square is
treated as the source of truth for emails — manual local edits will
be overwritten on next sync.

If you must edit locally (e.g. employee doesn't have a Square email
field), edit the Email column on Settings and Save. Just remember to
also update Square so the next sync doesn't blow it away.

### When you change someone's category

Edit the Category dropdown, click Save Changes. Effects:

- Payroll page subtotals re-calculate
- Dashboard payroll split (UM vs M+S) updates next refresh
- Future payslip emails respect the new category (e.g. moving someone
  out of Upper Management means they'll start receiving the PTO
  summary block in payslip emails)

## Buttons explained

- **Sync from Square** — pulls fresh data for every employee. Adds new
  ones as Staff. For existing employees, updates names + emails but
  preserves your local Category, Pay Type, Salary, Cleaning, and
  Former? settings.
- **Save Changes** — saves whatever you've edited in the table. Always
  scroll down and click this after editing.

## Categories explained

| Category         | Examples           | Notes                                        |
|------------------|--------------------|----------------------------------------------|
| Upper Management | Thomas, Soraya     | Owners. No PTO accrual. Salaried.            |
| Management       | Tomas, Camille, Nheaca | Salaried managers. Get PTO + leave email. |
| Staff            | Bar staff (most)   | Hourly. Get PTO + leave email.              |

## Common questions

- **Why can't I edit names?** Names come from Square so they stay in
  sync with timecards. Edit in Square then sync.
- **An employee's email keeps disappearing:** they don't have an email
  on their Square profile, so each sync clears it. Either set the
  email in Square, or accept that you'll need to re-add it locally
  after each sync.
- **I synced and someone's category changed back to Staff:** that
  shouldn't happen — local Category is preserved. If it did, file it
  as a bug; the most likely cause would be a freshly-created employee
  matching an existing team_member_id.

## When something looks wrong

- **Sync fails:** check Square API credentials are set on Render
  (`SQUARE_ACCESS_TOKEN`). Look at the Render logs for the actual
  error.
- **An employee not in Settings but is in Square:** click Sync from
  Square — they should pull in. If still missing, their Square status
  may be Inactive.
- **An old employee shows as Active but they've left:** tick Former?,
  Save. If they keep coming back as Active after sync, their Square
  status is still Active — set them inactive in Square first.
