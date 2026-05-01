# Dashboard

**URL:** `/dashboard`

## What it does

The Dashboard is the weekly performance view: net sales, payroll spend, labour
percentage, daily breakdown, t-shirt merch, and Irish VAT period totals — all
pulled live from Square.

Data is cached in SQLite so the page loads in under a second after the first
hit each morning. Cache is auto-refreshed in the background; you don't need to
do anything to keep it current.

## Key sections

1. **KPI strip** — net sales for the most recent completed week, year-on-year
   uplift vs 2025, payroll % of net sales, t-shirt unit/revenue totals.
2. **Daily sales vs 2025 same week** — per-day bars comparing the selected week
   to the same week last year. % delta is shown above each bar (green if up,
   red if down). Click any week button (W02, W03, ...) to switch.
3. **Net sales by week** — full-year overview with 2025 vs 2026 stacked.
4. **Year-on-year % change** — line chart of week-over-week YoY change.
5. **Payroll by week** — total payroll plus the Upper Management vs
   Management+Staff split per week.
6. **Hours by day (current week)** — staff hours mapped against daily sales.
7. **VAT periods** — the two upcoming Irish VAT bi-monthly periods with
   output VAT computed from sales and input VAT pulled from the bookkeeping
   module (or fallback hard-coded values for months without invoices yet).

## How to use it

- **Daily check:** open the page each morning. The most recent completed week
  is what to focus on. The current (in-progress) week is shown but is
  partial — don't compare it directly to a full week.
- **Compare a specific week:** click the week button (W02, W03, ...) under the
  Daily sales chart to switch focus.
- **Force a refresh:** if numbers look stale, click the refresh icon in the
  top right. This clears the current week's cache and re-pulls from Square.
  Completed weeks are cached forever (they don't change), so the refresh
  only re-fetches the current and last few weeks.

## Common questions

- **Why is this week's number lower than last week's?** The current week is
  partial — it includes whatever days have happened so far. Don't compare
  partial-to-full.
- **Why doesn't the YoY KPI include this week?** It excludes the current
  partial week so you're always comparing completed weeks to completed weeks.
- **The dashboard says "Loading..." for ages.** First-time data load from
  Square takes 2-3 minutes. The page auto-refreshes every 15 seconds. You
  only see this on a fresh deploy.

## When something looks wrong

- **A week shows €0 sales:** Square API didn't return data for that week.
  Click refresh, or check Square is reachable. If it persists, look at
  Render's logs for `[gmail]` or Square errors.
- **VAT period shows "pending":** the input VAT for one of the months in the
  period hasn't been confirmed yet. Either wait for invoices to flow in (and
  be approved on the bookkeeping page) or hard-code the value if you have
  the accountant's number from elsewhere.
- **YoY uplift looks wrong:** the comparison is by ISO week number, so
  weeks shift by a day across years. This is the correct comparison for
  weekly hospitality businesses.
