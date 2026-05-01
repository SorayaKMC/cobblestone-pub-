# Cobblestone Pub App — Standard Operating Procedure

This document is the master operating procedure for the Cobblestone Pub
management app. It ties together the per-section briefs (in this same
folder) into daily / weekly / monthly checklists.

For the deeper "what does X do and how do I use it" detail on any
section, open its brief. They're numbered:

1. [Dashboard](01-dashboard.md)
2. [Payroll — Weekly](02-payroll-weekly.md)
3. [Payroll — Accountant Files](03-payroll-accountant.md)
4. [PTO Tracker](04-pto-tracker.md)
5. [Bookkeeping & Invoices](05-bookkeeping.md)
6. [Backroom Bookings](06-bookings.md)
7. [Settings](07-settings.md)

---

## Daily routine

### Morning (10 min)

1. **Open the Dashboard.** Scan yesterday's net sales vs the same day in
   2025. Anything off by more than 20% — investigate.
2. **Open Bookings.** Anything happening today? Door staff arrangements
   confirmed? Door fee paid?
3. **Open Bookkeeping.** Drive watcher panel — any pending invoices in
   the root folder? Any errors flagged on the most recent scan?
   Click Scan Drive Now if anything looks unprocessed.

### Throughout the day

- Suppliers email invoices to `invoice@cobblestonepub.ie` — the system
  imports them automatically. You don't need to do anything until the
  weekly review.
- Staff request leave → log it on `/pto` so the Payroll page picks it
  up automatically next week.
- New booking enquiries arrive → review on `/bookings` and either
  Confirm, set Tentative, or Reject.

---

## Weekly routine

### Sunday night / Monday morning (after the work week ends)

1. **PTO auto-recalc** runs at 23:00 Sunday (Dublin) automatically. Check
   `/pto` Monday morning — every active employee should have an accrual
   row for the week that just ended. If anyone shows 0 accrued for a
   week they worked, see the [PTO troubleshooting](04-pto-tracker.md)
   section.

### Monday — Tuesday: prepare payroll

1. **`/payroll`** for last week.
2. Enter tips, cleaning, bonus per employee. **Save**.
3. Verify Holiday Pay column matches what's logged on `/pto`.
4. Click **Peter Excel** → download → email to Peter (the accountant).
5. Click **Finalize Week**. This locks tips/cleaning/bonus.

### Wednesday — Thursday: process Peter's reply

When Peter sends back the gross-to-net summary + combined payslips:

1. **`/payroll/accountant`** for that week.
2. **Upload** both PDFs.
3. **Confirm Mappings** — first time: pick the right Cobblestone employee
   for any unmapped row, save. Subsequent weeks: auto-mapped.
4. **Test Gmail Connection** — quick check that drafts will work.
5. **Generate Drafts**.
6. **Open Gmail Drafts** in `info@cobblestonepub.ie` → review each →
   Send. Should take ~5 minutes for the whole team.

### Friday: bookkeeping review

1. **`/bookkeeping`** → filter Status = Pending.
2. For each: click in, verify supplier / amounts / VAT / category,
   approve. Reject duplicates and junk.
3. Clear the queue before close of business.

### Sunday: this week's bookings prep

1. **`/bookings`** → filter to this coming week.
2. For each show: door arrangements set? Door staff assigned?
3. Reach out manually if any band hasn't replied to the reminder
   emails.

---

## Monthly routine

### First few days of the new month

1. **Dashboard** — verify the previous month's totals look reasonable.
   Scroll to the VAT periods section.
2. **Bookkeeping** — confirm every invoice for the previous month is
   Approved, not Pending. The VAT period totals depend on it.
3. If a VAT period has just closed (15th of every other month):
   - Verify the period status moved from "Pending" to "Due" on the
     Dashboard.
   - Cross-check the net VAT due against your accountant's number.
   - If they differ by more than rounding, drill into the monthly
     breakdown on Bookkeeping to find the difference.

---

## Quarterly / occasional tasks

### When a new employee joins

1. Square first: add them as a Team Member with pay type, rate, email.
2. `/settings` → **Sync from Square** → they appear as Staff.
3. Set Category if they're Management or Upper Management.
4. Set Cleaning (€/wk) if applicable. Save.
5. (PTO will start accruing automatically from their first timecards.)

### When someone leaves

1. Square first: set their Team Member status to Inactive.
2. `/settings` → tick **Former?** for that employee → Save.
3. Their data stays in history; they're sorted to the bottom of PTO and
   excluded from active payroll calculations.

### When a supplier starts emailing the wrong address

If a new supplier emails `info@` instead of `invoice@`:

1. Gmail (`info@cobblestonepub.ie`) → Settings → Filters and Blocked
   Addresses → Create new filter.
2. From: `accounts@thatsupplier.com`.
3. Forward to: `invoice@cobblestonepub.ie`.
4. (Optional: also Skip the Inbox / Archive on `info@` to keep that
   inbox clean.)

---

## Troubleshooting cheat sheet

| Symptom                                                  | Where to look                                |
|----------------------------------------------------------|----------------------------------------------|
| Dashboard says "Loading..." for ages                     | First-load — wait 2-3 min                    |
| Numbers on Dashboard look stale                          | Click refresh button (top right of dashboard)|
| Employee not on Payroll page                             | `/settings` → Sync from Square               |
| Hours = 0 on Payroll for someone who worked              | Square doesn't have their timecards          |
| Holiday Pay missing on Payroll                           | Log it on `/pto` first; auto-syncs           |
| Payroll Test Gmail fails: `unauthorized_client`          | Workspace delegation propagation, wait 2 min |
| Drive watcher panel shows red "API not used"             | Enable Drive API in Google Cloud project     |
| Drive watcher shows 403                                  | Share folder with `info@` as Editor          |
| `GOOGLE_DRIVE_INVOICES_FOLDER_ID not set`                | Set env var on Render → cobblestone-pub      |
| Invoice arrived but shows "Unknown" supplier             | Open it, edit, save. Claude was unsure.      |
| PTO accrual = 0 for a week someone worked                | Check Payroll for that week; recalc PTO      |
| Booking confirmation email didn't arrive                 | Check Render logs for the booking            |

---

## What runs automatically (background jobs)

| Job                          | Cadence                          | What it does                                            |
|------------------------------|----------------------------------|---------------------------------------------------------|
| Dashboard cache warmup       | At app boot                      | Pre-fetches each week's Square data                     |
| Gmail invoice poller         | Every 30 min                     | Pulls PDFs from `invoice@`, extracts, saves             |
| Drive folder watcher         | Every 30 min                     | Imports human-uploaded PDFs from the invoices folder    |
| PTO weekly auto-recalc       | Sundays 23:00 Dublin             | Recalculates 4 weeks of accruals + 13-week avg shifts   |
| Booking reminders (cron)     | Daily                            | Sends pre-show reminders                                |
| Booking auto-complete        | Daily                            | Marks past bookings Completed                           |

All of these are **idempotent** — safe to run multiple times, won't
double-process anything.

To check any of these is running, look at the cobblestone-pub service
logs on Render and grep for the prefix:
- `[gmail]` — invoice email poller
- `[drive]` — Drive folder watcher
- `[pto-weekly]` — PTO auto-recalc
- `[warmup]` — Dashboard cache priming

---

## Credentials and where they live

The app needs three credential sets, all stored as env vars on the
**cobblestone-pub** Render service:

1. **`SQUARE_ACCESS_TOKEN`** — Square API access for sales, timecards,
   team members.
2. **`GOOGLE_SERVICE_ACCOUNT_JSON`** — Full JSON of the Google service
   account (from the GCP project `cobblestone-pub-app`). Used for:
   - Gmail invoice polling on `invoice@cobblestonepub.ie`
   - Gmail draft creation on `info@cobblestonepub.ie`
   - Drive folder access (read + write + move)
3. **`ANTHROPIC_API_KEY`** — Claude API for invoice extraction.

The service account in (2) needs **domain-wide delegation** authorised
in Google Workspace Admin for these scopes:
- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/drive`

Plus **Google Cloud APIs** enabled in the same project:
- Gmail API
- Google Drive API

Plus the **Drive invoices folder** must be shared with both:
- `info@cobblestonepub.ie` (for the Drive watcher)
- `invoice@cobblestonepub.ie` (for the email poller's uploads)

If you ever need to rotate the service account key, generate a new JSON
in GCP, paste it into Render's `GOOGLE_SERVICE_ACCOUNT_JSON`, save.
Render auto-redeploys; everything resumes.

---

## When in doubt

If something breaks and the troubleshooting table doesn't help:

1. **Check Render logs** for the cobblestone-pub service — most issues
   surface there with a clear error message.
2. **Check the relevant section's brief** in this folder.
3. **The flash messages on each page** usually say exactly what's wrong
   when they're red.
