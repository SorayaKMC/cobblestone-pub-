# PTO Tracker

**URL:** `/pto`

## What it does

Tracks annual leave accrual and usage for every employee. Numbers come
from the Irish standard accrual rules baked into the engine:

- **Hourly staff:** 8.08% of hours worked, converted to days using the
  rolling 13-week average shift length.
- **Salaried staff:** 0.4 days per week worked.
- **Maximum balance:** 21 days. Anything earned beyond this is preserved
  as "over cap" — when leave is taken, the cap is replenished from the
  surplus before the visible balance drops.

Accruals automatically recalculate every Sunday 23:00 Dublin time
(background job on Render). You can also trigger a manual recalc any time.

## Page sections

1. **Summary table** — every employee with: total accrued, total taken,
   adjustments, current balance, accrual type (Hourly / Salaried), and
   13-week average shift length. Anyone over the 21-day cap shows
   `+N.NN over cap` under their balance.
2. **Log Leave Taken** — quick form to record a day of leave for any
   active employee.
3. **Manual Adjustment** — for one-off corrections (starting balance,
   admin grant, etc.). Requires a reason.
4. **Recent Leave Taken** — log of the last 20 leave records, with
   employee names (not codes) and reasons.
5. **Recalculate PTO** — admin tool to re-run accrual calculation for a
   date range. Used after backdated Square timecard edits or when fixing
   data issues.

## How to use it

### Recording leave when an employee takes a day off

1. Open **`/pto`**.
2. In **Log Leave Taken**, pick the employee, set the date, set days
   (1.0 for a full day, 0.5 for half).
3. Add a reason if useful (e.g. "Annual leave", "Sick").
4. Save. The leave shows up in the Recent Leave Taken table and feeds
   automatically into the Payroll page's Holiday Pay column.

### Granting a starting balance to a new hire

1. **Manual Adjustment** form.
2. Pick the employee, enter a positive number of days, set effective
   date, write the reason (e.g. "Starting balance per offer letter").
3. Save.

### Fixing an accrual that didn't compute

1. **Recalculate PTO** modal at the bottom of the page.
2. Set From and To dates covering the affected period (e.g. 4 weeks
   back to today).
3. Run. The engine re-runs accrual week-by-week for every employee. Any
   "Protected" weeks (imported from the V4 spreadsheet) are skipped and
   reported in the success message.

## Column glossary

| Column        | Meaning                                                 |
|---------------|---------------------------------------------------------|
| Type          | Hourly or Salaried (drives the accrual formula)         |
| Avg Shift     | 13-week rolling average shift hours (hourly only)       |
| Total Accrued | Lifetime accrual, uncapped                              |
| Adjustments   | Sum of manual adjustments (positive or negative)        |
| Total Taken   | Sum of logged leave days                                |
| Balance       | min(Accrued + Adjustments − Taken, 21)                  |

## Common questions

- **Why is my balance 21 even though Total Accrued is higher?** That's
  the cap. The surplus is preserved — when leave is taken, the visible
  balance stays at 21 until the buffer is gone.
- **Why didn't an employee accrue last week?** Square may not have their
  timecards. Check `/payroll` for that week — does it show their hours?
  If no, the timecards aren't there. If yes, click Recalculate PTO with
  the right date range.
- **What's "13-week avg shift"?** For hourly staff, leave is accrued in
  hours then converted to days. We need to know "what's a typical day
  for you" — that's the avg shift. Computed from the last 13 weeks of
  shifts; falls back to 8.0 if fewer than 5 shifts.
- **Why is my Type "Hourly" but I'm a salaried manager?** Type is read
  from Square's Team Member pay_type. If wrong, fix it in Square.

## When something looks wrong

- **An employee shows 0 accrued for a week they worked:** click
  Recalculate PTO with that date range. If still 0, the timecards aren't
  in Square — check the Payroll page for that week.
- **Balance dropped to 0:** likely an adjustment with a large negative
  number. Look in the Adjustments history (admin only).
- **Recalculate fails:** error message will name the problem. Often it's
  a Square API rate-limit; wait a minute and retry.

## Auto-recalc job

A background thread on Render fires every Sunday at 23:00 Dublin time
and recalculates the past 4 ISO weeks for every employee. This catches:

- Backdated Square timecard edits
- New employees added during the week
- The 13-week avg shift changes as old weeks roll off

Look for `[pto-weekly]` lines in Render's cobblestone-pub logs to confirm
it's running.
