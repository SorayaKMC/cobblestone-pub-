# Backroom Bookings — Manager SOP

For Tomás, Camille, Nheaca and anyone else using the bookings portal
day-to-day. Replaces the old spreadsheet workflow as of May 2026.

If something here doesn't match what you're seeing in the app, ping
Soraya — the system is still being polished.

---

## Quick start: the 5 things you'll do most

1. **Triage a new inquiry** → `/bookings`, click into the row,
   Approve or Decline.
2. **Quick Hold a date** that someone texted you about → big "Quick
   Hold" button at top of `/bookings`.
3. **Send a band their portal link** if they didn't get the auto
   email → on the booking detail page, "Send portal link" action.
4. **Mark a fee as paid** when cash hits the till → on the booking
   detail page, "Mark venue fee paid" / "Mark door fee paid".
5. **Publish to Squarespace** → on a confirmed booking, copy the
   Squarespace block and paste it as a new event on the website.
   Then tick "Squarespace published".

Everything else is bonus.

---

## The dashboard at a glance

`/bookings` shows six tiles at the top. Each is a clickable filter.

| Tile | What it counts | When to look |
|---|---|---|
| **Inquiries to review** | New form submissions waiting for you | First thing each morning |
| **Holds** | Soft-reserved dates that haven't converted yet | Weekly — chase or release |
| **Tentative** | Bookings on hold pending more info | Weekly |
| **Confirmed upcoming** | Locked-in future gigs | Reference |
| **Outstanding fees** | Confirmed/completed gigs with venue or door fee unpaid | End of week |
| **Need website listing** | Confirmed gigs not yet on Squarespace | Weekly publishing |
| **Door person TBC (≤7 days)** | Confirmed gigs in the next week with no door person assigned | Daily check |

(Tile counts exclude archived rows.)

---

## Workflow: inquiry → confirmed

### When a band submits the form

1. Inquiry lands at `/bookings` with status **Inquiry** (orange badge)
2. Click into it from the bookings list
3. Read through:
   - Act + event date + day of week
   - Contact info
   - Bio / promo text
   - Ticket price + link (if any)
   - Support act, door person request
   - "Recent emails" panel — has there been any back-and-forth via
     email already?
4. Decide:
   - **Confirm** → "Confirm Booking" button → fires the approval
     email (band + Shane CC'd) and creates the Google Calendar event
   - **Tentative** → mark Tentative if you want to soft-hold while
     you check something
   - **Decline** → "Cancel Booking" → sends decline email with a
     "Pick another date" link
   - **Archive** → if it's spam or clearly not a fit, archive it (it
     drops out of all your lists)

### What the confirmation email does

- Sends to the band with full gig details, venue/door fees,
  ticketing recommendations, Shane's contact, and a portal link
- **CCs Shane** so he's looped in for sound coordination
- Attaches an `.ics` calendar invite the band can add to their
  own calendar
- Stamps `confirmation_sent_at` and adds a Google Calendar event

### After confirmation

The booking auto-progresses through these markers as work gets done:

- Band uploads their poster via the portal → shows on detail page
- 2 weeks before: a checklist email goes out (door person ask,
  poster upload reminder, pay-in-advance link)
- 3 days before: countdown reminder
- After the gig: status moves to Completed (manually or via cron)

---

## Quick Hold — soft-reserving a date

When someone texts/calls and says "can I have May 23rd?" but they
haven't filled in the form yet:

1. On `/bookings`, click the **Quick Hold** button (top right, between
   Calendar View and Add Booking)
2. Fill in:
   - **Held for** — the band/person's name (required)
   - **Date** (required)
   - Email + phone (optional)
   - Notes (optional — e.g. "Texted via WhatsApp, will confirm next
     week")
3. Submit → creates a booking with status **Hold** (purple badge)

The hold:
- Marks the date as **tentative on the public form** — bands using
  `/book` won't see it as bookable
- Shows on your internal calendar in **purple**
- Counts on the **Holds** tile
- Doesn't trigger any email to the band

**When the band confirms**, open the hold → change status to
**Confirmed** → fill in the missing details → Approve. The hold
becomes a real booking and triggers the confirmation email.

**If the hold expires** (band ghosted), open it → Cancel or Archive.

---

## Calendar conventions

Open `bookings@cobblestonepub.ie` Google Calendar (subscribe in your
own Google account if you haven't already).

| Color | What |
|---|---|
| 🟢 **Sage green** | Form-backed bookings — band has submitted info |
| 🟡 **Default yellow** | Calendar-only — Tomás added manually, no form info yet |
| 🟣 **Lavender** | Upstairs / workshop events |
| ⚫ **Graphite** | Bar / non-Backroom (table holds, filming) |

The internal app calendar (`/bookings/calendar`) uses different
colors based on **status**, not provenance:
- Green = confirmed
- Yellow/orange = inquiry/tentative
- Purple = hold
- Grey = completed
- Light grey = cancelled

---

## Common tasks

### Send a band their portal link manually

If a band says "I didn't get an email":

1. Open `/bookings/<id>`
2. Verify their email address is right
3. Click **Send portal link** in the actions sidebar
4. Tell them to check spam if it doesn't show within a minute

### Mark venue fee or door fee as paid

On the booking detail:
- **Mark venue fee paid** button (when €150 lands)
- **Mark door fee paid** button (when €50 lands or door takings settle)

These flip the row out of the "Outstanding fees" KPI tile.

### Send the Squarespace block

When a gig is confirmed and ready to go on the website:

1. Open the booking
2. Scroll to the "Squarespace block" panel
3. Click **Copy Squarespace block** — copies a pre-formatted text
   chunk to your clipboard
4. Open Squarespace → Events → New Event → paste it in
5. Back in the app, tick **Squarespace published**

This drops the row out of the "Need website listing" KPI tile.

### Assign a door person

On the booking detail, the Door Person field has options:
- `pub` — the Cobblestone provides one (€50)
- `own` — band brings their own
- `tbc` — to be confirmed
- `none` — not needed

Confirmed gigs within 7 days with no door person set show a
warning badge in the bookings list.

### Send a custom message to the band

On the booking detail, **Send message** action:
- Free-text subject + body
- Wrapped in the Cobblestone brand template
- Useful for one-offs ("can you bring extra mic stands?")

### Cancel vs archive

- **Cancel** = the gig isn't happening. Sends a cancellation email
  to the band (or doesn't, if cancelled by the band themselves).
  Status flips to Cancelled, badge goes black.
- **Archive** = hide it from the active list (KPI tiles too). The
  data is still there — toggle "Show archived" on the bookings list
  to see them. Use for very old completed gigs, spam inquiries, or
  test bookings you don't want cluttering the queue.

You can archive cancelled bookings to clean up the view.

---

## Scenarios

### Two bands want the same date

The system flags conflicts as **needs review** during import, but
when both submit fresh:

1. Open both bookings (same date filter on `/bookings`)
2. Decide who gets the date based on your judgement
3. Confirm the winner → triggers their confirmation email AND
   auto-declines other inquiries on the same date with the
   "date now taken" email (which includes a one-click "Pick another
   date" link)
4. Verify both emails went out

### A confirmed band needs to change date

1. Open the booking
2. Edit the event date inline
3. Use **Send custom message** to confirm the new date with them
4. The Google Calendar event updates automatically

### Band asks via phone or WhatsApp instead of the form

1. **Quick Hold** the date so it's locked while you sort it
2. Send them the form link via reply: `bookings.cobblestonepub.ie/book`
   — the canned Gmail reply has the right wording
3. When they submit, convert the hold to confirmed (or merge
   manually if needed)

### Someone emails `cobblestonedublin@gmail.com` (the old inbox)

- That inbox auto-forwards to `bookings@cobblestonepub.ie`
- Reply with the canned Gmail reply pointing them at the form
- For repeat bookers / known acts, you can also Quick Hold the date
  while they fill the form

### A band doesn't show up

- After the gig date passes, status auto-progresses to **Completed**
  by the daily cron (or you can flip it manually)
- For a no-show specifically, mark **Cancelled** with a note in the
  notes field for future reference
- Optionally archive after a month

---

## When to escalate to Soraya

- Anything sounds like an app bug ("the button doesn't work", error
  messages, missing data)
- A booking shows wrong info that can't be fixed by editing
- Email isn't sending and you've already verified the contact email
- DKIM / spam complaints from bands
- Need to add a new manager to the system
- Need to add a new feature or change a workflow

For day-of-gig technical issues (sound, equipment, etc.) — that's
Shane (`+353 85 175 8254`).

---

## Reference: keyboard shortcuts & URLs

| What | Where |
|---|---|
| Bookings tracker | `/bookings` |
| Calendar view | `/bookings/calendar` |
| Single booking | `/bookings/<id>` |
| Add booking manually | `/bookings/new` |
| Quick hold | Modal on `/bookings` |
| Recurring series | `/bookings/series` |
| Blackout dates | `/bookings/blackouts` |
| Band contacts | `/bookings/contacts` |
| Public gig form | `/book` |
| Public other form | `/book/other` |
| Band-facing portal | `/book/<token>` (shared via email) |

Production URL: `https://bookings.cobblestonepub.ie` (or
`https://cobblestone-pub.onrender.com` if the custom domain isn't
fully set up yet).

---

_Last updated: 9 May 2026._
