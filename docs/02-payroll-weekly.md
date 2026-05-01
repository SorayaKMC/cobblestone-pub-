# Payroll — Weekly Process

**URL:** `/payroll`

## What it does

The Payroll page assembles each employee's hours, gross pay, tips, cleaning
allowance, and total labour cost for one week. Hours come from Square
timecards; tips, cleaning, and bonuses are entered manually because they're
managed separately from Square. The page is the launchpad for sending
payroll to the accountant.

Once a week is "finalized," tips/cleaning/bonus values are locked. They can
be unlocked with the admin password if a correction is needed.

## How to use it (weekly cadence)

1. **Open `/payroll`** — defaults to the current week. Use the week selector
   at the top to navigate.
2. **Enter tips, cleaning, bonus** for each employee. Use the Tab key to move
   across. Click **Save Tips, Cleaning & Bonus** at the bottom.
3. Verify the **Holiday Pay (h)** column matches what you've already logged
   on the PTO page. If anyone is missing leave that should be there, log it
   on the PTO page first — it auto-syncs back here.
4. Click **Peter Excel** to download the formatted file the accountant
   expects. Email it to Peter.
5. Click **Finalize Week** when you're confident nothing else will change.
   Locks tips/cleaning/bonus until unlocked.
6. When Peter sends back the gross-to-net summary + payslips, see the
   **Accountant Files** brief.

## Columns explained

| Column            | Source / Notes                                         |
|-------------------|--------------------------------------------------------|
| First / Last      | From Square (synced via Settings)                       |
| Rate              | Hourly rate from Square                                 |
| Hours             | Sum of regular + overtime + double-time from timecards  |
| Gross             | Hours × rate, OR fixed weekly salary if salaried        |
| Tips              | Manually entered. NEVER pulled from Square's tip fields |
| Cleaning          | Manually entered. Default per-employee in Settings      |
| Bonus             | Manually entered (rare; for one-off bonuses)            |
| Holiday Pay (h)   | Auto-synced from `/pto` based on logged leave           |
| Total             | Gross + Tips + Cleaning + Bonus                         |
| Category          | UM / M / S badge — set in Settings                      |
| Labor Cost        | Gross + Cleaning + Bonus (excludes tips for labour %)   |
| Net (accountant)  | After Peter's PDF is uploaded — read-only               |

## Other actions on this page

- **Raw Timecards** download — exports a per-shift CSV-style breakdown for
  audit purposes.
- **Import Tips** — one-time historical import from the Tips Sheet 2026
  spreadsheet. Don't run this casually.
- **Accountant Files** — opens the upload + draft generation flow.

## Common questions

- **An employee worked but doesn't appear** — they may not be in
  `employee_categories`. Go to Settings → Sync from Square to pull them in.
- **Total looks wrong** — check Tips/Cleaning/Bonus aren't being
  double-counted (e.g. someone paid for cleaning but it's also in Bonus).
- **Holiday hours didn't sync** — log the leave on the PTO page (not here).
  The Payroll page is read-only for holiday hours.

## When something looks wrong

- **"Save Tips, Cleaning & Bonus" doesn't seem to save:** the week may be
  finalized. Look for the yellow "This week is finalized" banner. Click
  Unlock, enter admin password, then save.
- **Hours = 0 for someone who worked:** Square doesn't have their timecard.
  Either they didn't clock in, or there's a Square sync issue. Check Square
  Dashboard directly to confirm.
- **Wage rate = €0:** Square Team Member doesn't have a rate set. Update in
  Square; Settings → Sync from Square will pick it up.
