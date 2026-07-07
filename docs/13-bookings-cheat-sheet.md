# Backroom Bookings — Cheat Sheet

Keep this open while you work — covers the 95% of tasks you'll do
day-to-day. For everything else, see the full Manager SOP (doc 11).

**Bookings tracker:** [bookings.cobblestonepub.ie/bookings](https://bookings.cobblestonepub.ie/bookings)

---

## The 6 things you'll do most

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
- Shows as **Tentative** on the public form (still bookable by other
  bands — they get a "your request will be reviewed" message)
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

Booking detail page → scroll to the **"Squarespace Listing"** card
(only appears on confirmed bookings that aren't marked internal-only):

1. The card shows a live preview of the formatted listing.
2. Click **Copy formatted (paste into Text Block)**.
3. In Squarespace, add a **Text Block** to the event page and paste.
   Headings (H2 title, H3 support act), bold (Doors / Gig / Ticket),
   and links inherit your site's existing typography.
4. (If the band gave a video URL, add a separate Squarespace **Video
   Block** — Text Blocks can't render embeds.)
5. Back in the app, set the **Squarespace listing** dropdown in
   Fees & Listing:

| State | When to pick it |
|---|---|
| **Not listed** | Default — haven't put it on the site yet |
| **Listed — info pending** | On the site but waiting for ticket link / poster / info |
| **Listed — complete** | Fully published, nothing missing |

The row badge on `/bookings` flips colour to match: pink → orange → teal.

---

### 6. Acknowledge a band-side change

When a band updates their times or ticket info via their portal, you
get an amber / pink **alert banner** on the booking detail page
*and* a matching badge on the bookings list row.

1. Open the booking — banner shows old → new values.
2. Mirror the change to Squarespace (and the calendar if it's a time
   change — that updates automatically too).
3. Click **Acknowledge** to clear the banner + badge.

Times changes also fire an email to `cobblestonedublin@gmail.com`.
Ticket-info changes don't (less urgent).

---

## Reading the dashboard

The tiles at the top of `/bookings` are clickable filters:

| Tile | What it shows |
|---|---|
| **Inquiries to review** | New form submissions waiting for you |
| **Holds** | Quick-held dates that haven't converted yet |
| **Tentative** | Soft-held bookings pending more info |
| **Confirmed upcoming** | Locked-in future gigs |
| **Outstanding fees** | Confirmed/completed gigs unpaid |
| **Not on Squarespace** | Confirmed but not yet on the website (excludes internal-only) |
| **Listing info pending** | On the website but missing info (excludes internal-only) |
| **Door person TBC (≤7 days)** | Gigs within a week with no door person — chase Soraya/Tomás |

## Row badges on the bookings list

What the coloured pills next to each act name mean:

| Badge | Meaning |
|---|---|
| 🟢 **Residency** (pink) | In-house regular — don't normally need attention |
| 📦 **Archived** (grey) | Cancelled / completed and tucked away |
| ⚠️ **Door person TBC** (yellow) | Confirmed gig within 7 days with no door person assigned |
| ⏰ **Times changed** (amber) | Band updated door / gig times via their portal — acknowledge after mirroring |
| 🎟️ **Ticket info changed** (pink) | Band updated ticketing type / price / link via their portal — acknowledge after mirroring |
| 👤 **Doorperson needed** (blue) | Pub is staffing the door (pub-provided, with or without fee) — for scheduling |
| 👁️‍🗨️ **Internal only** (grey) | "Don't list on website" ticked — won't appear in Squarespace workflow tiles |
| **Listing status** (pink/orange/teal) | Not on website / Needs info / On website |

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

## What bands can update themselves

Bands have always been able to edit their **description** via the
portal. As of May 2026 they can also update:

- **Door / gig times** — fires an email + alert banner + badge to us.
- **Ticket info** (ticketing type, price, link — Eventbrite URL etc.)
  — fires a banner + badge (no email). Useful because they often don't
  have the link at the moment they request the date.

Both edits write to `booking_audit` so you can always see who changed
what when. They're blocked for cancelled / completed bookings.

What they **can't** change: the date, the venue, the contact details,
or anything financial. Date changes still go through us.

---

## Internal-only events

Some events shouldn't appear on Squarespace — private hire, rehearsal,
filming, mate's gig.

Booking detail → Booking Details form → tick **"Don't list on website
(internal only)"** → **Save Changes**.

What that does:
- Hides the Squarespace Listing card and dropdown on the detail page.
- Replaces the pink/orange/teal row badge with a grey **Internal only**.
- Drops out of "Not on Squarespace" / "Listing info pending" tile counts.

Untick to put it back into the listing workflow.

---

## Door person options

| Option | What it means |
|---|---|
| **Pub-provided (€50)** | We staff the door, €50 door fee applies. Auto-generates a Square payment link. |
| **Pub-provided (no fee)** | We staff the door, no fee (residencies, special arrangements). |
| **Bringing own** | Band is bringing their own — we don't need to schedule anyone. |
| **Not needed** | No door person at all (private events, intimate gigs). |
| **TBC** | Still being decided. Triggers the yellow ⚠️ warning if the gig is within 7 days. |

The header badge on the booking detail page shows the current setting
at a glance.

---

## When something doesn't go to plan

| Problem | What to do |
|---|---|
| Band says they didn't get the confirmation email | Booking detail → **Send portal link** action, then ask them to check spam |
| Two bands want the same date | Confirm the winner → auto-fires decline email to the loser with a "pick a new date" link |
| Band asks to change the date | We have to do this — open booking → edit event_date → Save Changes. Calendar auto-updates. Use **Message Band** to confirm with them |
| Band-side time change banner | Open booking → mirror to Squarespace → click **Acknowledge** to clear |
| Band-side ticket info change banner | Open booking → mirror to Squarespace → click **Acknowledge** to clear |
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
| **Weekly run sheet** (printable, for door / FOH) | `/bookings/week-sheet` |
| Recurring series | `/bookings/series` |
| Band contacts | `/bookings/contacts` |
| Public gig form | `/book` (share with bands) |
| Public other-events form | `/book/other` (filming, rehearsal, private) |

Production base URL: `https://bookings.cobblestonepub.ie`

### Weekly run sheet — print every Monday

One card per confirmed gig in the current Mon–Sun window. Shows act,
doors, gig, end, door person, fee status, ticketing, band contact,
notes. Click **Print** at the top of the page; the sidebar hides
automatically for clean A4 output. **Previous week / This week /
Next week** buttons for navigation.

---

_Stuck on something? Ring Soraya. Welcome to the team!_

_Last updated: 15 May 2026 — Camille + Nheaca handover._
