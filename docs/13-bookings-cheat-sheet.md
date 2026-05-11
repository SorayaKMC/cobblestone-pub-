# Backroom Bookings — Cheat Sheet

Keep this open while you work — covers the 95% of tasks you'll do
day-to-day. For everything else, see the full Manager SOP (doc 11).

**Bookings tracker:** [bookings.cobblestonepub.ie/bookings](https://bookings.cobblestonepub.ie/bookings)

---

## The 5 things you'll do most

### 1. Triage a new inquiry

`/bookings` → click the row with the **orange "Inquiry" badge**.
Read the form, then pick one of:

| Action | What happens |
|---|---|
| **Confirm Booking** | Sends approval email (band + Shane CC'd), creates the Google Calendar event |
| **Confirm (silent)** | Same as above but skips the email + Square link — for re-confirms or things already coordinated by phone |
| **Tentative** | Soft-hold while you check something |
| **Cancel + Email Decline** | Sends the "date unavailable" email with a rebook link, then auto-archives |
| **Cancel** (silent) | Cancels without sending any email |

Always **check the "Recent emails" panel** on the detail page first
— you might already have context.

---

### 2. Quick Hold a date

Someone texts/WhatsApps "can I have May 23rd?" but hasn't filled the form?

`/bookings` → click **Quick Hold** (top right) → fill in name + date
+ notes → Submit.

- Date goes **purple** on your internal calendar
- **Blocks the public form** so no one else can book that Sunday
- **No email** sent to the band
- When they confirm → open the hold → change status to **Confirmed** →
  fill in missing details → Approve

---

### 3. Send a band their portal link

Band says "I didn't get the email"?

Booking detail page → **Send portal link** in the actions sidebar.
Tell them to check spam if it doesn't show within a minute.

---

### 4. Mark a fee as paid

Booking detail page →

- **Mark venue fee paid** when €150 lands
- **Mark door fee paid** when €50 lands or the door takings settle

Drops out of the "Outstanding fees" KPI tile.

---

### 5. Publish a gig to Squarespace

Booking detail page → scroll to the **"Squarespace block"** panel →
**Copy Squarespace block** → paste it into Squarespace → set the
**Squarespace listing** dropdown:

| State | When to pick it |
|---|---|
| **Not listed** | Default — haven't put it on the site yet |
| **Listed — info pending** | On the site but waiting for ticket link / poster / info |
| **Listed — complete** | Fully published, nothing missing |

---

## Reading the dashboard

The seven tiles at the top of `/bookings` are clickable filters:

| Tile | What it shows |
|---|---|
| **Inquiries to review** | New form submissions waiting for you |
| **Holds** | Quick-held dates that haven't converted yet |
| **Tentative** | Soft-held bookings pending more info |
| **Confirmed upcoming** | Locked-in future gigs |
| **Outstanding fees** | Confirmed/completed gigs unpaid |
| **Not on Squarespace** | Confirmed but not yet on the website |
| **Listing info pending** | On the website but missing info |
| **Door person TBC (≤7 days)** | Gigs within a week with no door person — chase Tomás |

---

## What residency gigs look like

Balaclavas (Wednesdays), Caoimhe Mondays, Larry's Sunday, Pipers'
Tuesday, Dublin Jazz Coop Sundays — these are in-house regulars
tagged as **"Residency Gigs"**.

- Show with a **pink badge** in the bookings list
- Pink colour on the calendar
- Don't need door people or fees (defaults to 0)
- Don't trigger Door TBC warnings
- **Special: Dublin Jazz Coop is non-blocking** — Sunday-evening gigs
  can still book the same date. Note: load-in/soundcheck must be
  **after 6pm** when Jazz Coop is on.

You'll rarely need to touch residency rows — they manage themselves.

---

## When something doesn't go to plan

| Problem | What to do |
|---|---|
| Band says they didn't get the confirmation email | Booking detail → **Send portal link** action, then ask them to check spam |
| Two bands want the same date | Confirm the winner → auto-fires decline email to the loser with a "pick a new date" link |
| Confirmed band needs to change the date | Open booking → edit event_date → save. Calendar auto-updates. Use **Send custom message** to confirm with the band |
| Date is wrong / band name typo | Open booking → edit field → save (Calendar event auto-refreshes for confirmed bookings) |
| A gig got cancelled | Status dropdown → Cancelled. Auto-archives + clears the Calendar event. Use **Cancel + Email Decline** if you want the band to get a polite email |
| Want to un-cancel | Toggle "Show archived" → open booking → **Unarchive** button |

---

## The phone tree

| Issue | Who to call |
|---|---|
| Booking decisions / who plays what | **Tomás** (primary booker) |
| App errors, broken buttons, missing data | **Soraya** (system owner) |
| Sound / day-of-show technical issues | **Shane** — +353 85 175 8254 |
| DKIM / spam complaints from bands | **Soraya** |
| Adding a new manager to the system | **Soraya** |

---

## URLs you'll use

| What | URL |
|---|---|
| Bookings tracker | `/bookings` |
| Calendar view | `/bookings/calendar` |
| Recurring series | `/bookings/series` |
| Band contacts | `/bookings/contacts` |
| Portal intros (multi-gig email sender) | `/bookings/portal-intros` |
| Public gig form | `/book` (share with bands) |
| Public other-events form | `/book/other` (filming, rehearsal, private) |

Production base URL: `https://bookings.cobblestonepub.ie`

---

_Stuck on something? Ring Soraya. Welcome to the team!_

_Last updated: 11 May 2026 (launch day)._
