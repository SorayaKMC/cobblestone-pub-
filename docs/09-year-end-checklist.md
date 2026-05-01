# Year-End Checklist

Run through this list in the **last two weeks of December** so the year
closes cleanly and the new year starts with everything in place.

Most of these are quick (5-10 min each). The whole list shouldn't take
more than half a day.

## December — final-fortnight tasks

### Bookkeeping wrap-up

- [ ] **Open `/bookkeeping`**. Filter Status = Pending. Drive the count
      to zero. Anything left at year-end should be Approved or Rejected.
- [ ] Cross-check the **Annual Input VAT total** with the accountant's
      year-end summary. Drill into months that don't match.
- [ ] Verify **VAT Period 6** (Nov + Dec) is on track. Output VAT comes
      from Dashboard sales; input VAT must be Approved invoices for
      Nov + Dec.
- [ ] In Drive, confirm every December PDF is in the `Processed/`
      subfolder, not lingering at the root.

### Payroll wrap-up

- [ ] Run the final weekly payroll cycle for the year (typically the
      week ending the last Sunday of December).
- [ ] Verify every employee's **Net Pay (accountant)** column is
      populated for the final week.
- [ ] Generate and send payslip drafts as usual. Make sure the email
      bodies show period ending in December.

### PTO wrap-up

- [ ] **Click Recalculate PTO** on the PTO page with `From` set to
      `2026-01-05` (or wherever the year started) and `To` set to
      `2026-12-31`. This makes sure the year's accruals are fully up
      to date before any year-end snapshots.
- [ ] Take a snapshot: download or screenshot the PTO summary table.
      Save in Drive somewhere obvious (e.g.
      `Cobblestone Work/PTO Snapshots/2026-12-31.pdf`). This is the
      record of every employee's year-end balance.
- [ ] **Decide carryover policy** with management. The system caps at
      21 days, so any surplus over 21 is preserved as `over cap` and
      replenishes the visible balance as leave is taken next year.
      Decide if you want to:
      - Leave it as-is (surplus auto-carries over)
      - Manually adjust everyone down to a cap (e.g. enforce statutory
        4 weeks = 20 days). Use the **Manual Adjustment** form on the
        PTO page with negative numbers and "Year-end carryover cap"
        as the reason.

### Bookings wrap-up

- [ ] Verify all December bookings are marked **Completed** (auto-done
      by the daily cron, but worth confirming).
- [ ] Archive any cancelled-but-not-deleted bookings.
- [ ] Set up the new year's **blackout dates** on
      `/bookings/blackouts` (private events, holidays, maintenance).
- [ ] Create or roll over any **recurring series** for the new year on
      `/bookings/series`.

### Supplier directory

- [ ] Review `/bookkeeping/suppliers`. Any suppliers you're no longer
      using? Mark them inactive (so they don't appear in dropdowns
      next year).
- [ ] Any new suppliers from the year-end period whose default category
      / VAT rate isn't set right? Edit them now.

### Settings — annual review

- [ ] **Sync from Square** (Settings → top right) to pull any
      end-of-year staff changes.
- [ ] Walk through the employee list. Anyone marked Active who
      shouldn't be? Tick **Former?** for them.
- [ ] Anyone whose **Cleaning (€/wk)** changed during the year and
      hasn't been updated? Adjust now so January starts clean.
- [ ] Anyone whose **Category** should change next year (e.g. promoted
      from Staff to Management)? Update now.

## January — opening tasks

### First week of January

- [ ] **Dashboard sanity check.** The dashboard shows current-year vs
      previous-year. Verify that 2027 (or whatever next year is) is
      showing zero net sales for the in-progress week and that
      previous-year (2026) data is correctly archived.
- [ ] **Hard-coded VAT fallback values** in `routes/dashboard.py` may
      need updating for the new year. The code has a
      `FALLBACK_INPUT_VAT_2026` dict with hard-coded numbers for
      months without invoices yet. If you want this for 2027 too,
      update the dict before invoices start flowing in. (Or skip —
      live invoices will fill the gap once approved.)
- [ ] **Historical payroll dictionary** (also in
      `routes/dashboard.py`, `HISTORICAL_PAYROLL_2026`) is for legacy
      weeks before Square timecards were rolled out. New years
      shouldn't need entries unless there's a similar gap.

### First-week PTO

- [ ] If you adjusted balances for year-end carryover, double-check
      every employee's Total Adjustments column on the PTO page
      reflects what you intended.
- [ ] If you didn't adjust, surplus carries over automatically — the
      `over cap` line on each employee's row will gradually decrease
      as they take leave through the year.

## Quarterly reminders (any time of year)

- [ ] **Verify background jobs** are running. Render logs should show
      regular `[gmail]`, `[drive]`, and weekly `[pto-weekly]` lines.
      If any are silent for >24h, investigate.
- [ ] **Rotate the service account key** annually. From the GCP
      project: Service Accounts → cobblestone-pub-app → Keys → Add new
      JSON key. Replace `GOOGLE_SERVICE_ACCOUNT_JSON` on Render. After
      verifying everything still works, delete the old key from GCP.
- [ ] **Review who has access** to Render, GCP, Workspace Admin, and
      Square Dashboard. Revoke access for anyone who's left.

## Useful queries for year-end

If you need to dig into specific data, these can be run with the
SQLite CLI on Render's persistent disk:

```bash
# Total invoices by month for the year
sqlite3 cobblestone.db "SELECT strftime('%Y-%m', invoice_date) as m, COUNT(*), ROUND(SUM(net_amount), 2), ROUND(SUM(vat_amount), 2) FROM invoices WHERE strftime('%Y', invoice_date) = '2026' AND status = 'approved' GROUP BY m ORDER BY m;"

# Total payroll per month (rough — uses the accountant's net pay)
sqlite3 cobblestone.db "SELECT strftime('%Y-%m', p.pay_date) as m, COUNT(*), ROUND(SUM(n.net_pay), 2) FROM pay_period_nets n JOIN pay_periods p ON p.id = n.pay_period_id WHERE strftime('%Y', p.pay_date) = '2026' GROUP BY m ORDER BY m;"

# PTO accrued and taken by employee for the year
sqlite3 cobblestone.db "SELECT ec.given_name || ' ' || ec.family_name, ROUND(SUM(a.days_accrued), 2) as accrued, COALESCE((SELECT ROUND(SUM(t.days_taken), 2) FROM pto_taken t WHERE t.team_member_id = ec.team_member_id AND strftime('%Y', t.date) = '2026'), 0) as taken FROM pto_accruals a JOIN employee_categories ec ON ec.team_member_id = a.team_member_id WHERE strftime('%Y', a.period_start) = '2026' GROUP BY ec.team_member_id ORDER BY ec.family_name;"
```

These are read-only — safe to run any time.

## Don't forget

- The accountant (Peter) likely needs an **end-of-year payroll summary**
  separate from anything in this app. Coordinate with him on what he
  needs.
- The **Revenue (Irish tax authority)** annual filings are also
  external to this app — payroll YTD totals from your accountant.
- **Insurance, lease, software subscriptions** — annual renewals
  outside this system.
- **Stocktake** — usually done end-of-month or end-of-quarter, not
  tracked in this app today.
