# Backroom Bookings — Manager SOP

For Camille, Nheaca, and anyone else running the bookings portal
day-to-day. Replaces the old spreadsheet workflow.

If something here doesn't match what you're seeing in the app, ping
Soraya — the system is still being polished.

---

## Quick start: the 6 things you'll do most

1. **Triage a new inquiry** → `/bookings`, click into the row,
   Confirm or Cancel.
2. **Quick Hold a date** that someone texted you about → big "Quick
   Hold" button at top of `/bookings`.
3. **Send a band their portal link** if they didn't get the auto
   email → on the booking detail page, "Send portal link" action.
4. **Mark a fee as paid** when cash hits the till → on the booking
   detail page, "Mark venue fee paid" / "Mark door fee paid".
5. **Publish to Squarespace** → on a confirmed booking, click
   **Copy formatted (paste into Text Block)** in the Squarespace
   Listing card, then paste into a Squarespace Text Block. Set the
   listing-status dropdown to match.
6. **Acknowledge band-side changes** → when an amber/pink banner
   appears at the top of a booking ("Times changed" or "Ticket info
   changed"), mirror the change to Squarespace and click
   **Acknowledge** to clear the alert.

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
| **Not on Squarespace** | Confirmed gigs not yet listed on the website | Weekly publishing |
| **Listing info pending** | Listed on Squarespace but waiting for info (ticket link, poster, etc.) | Weekly publishing |
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
   - **Confirm Booking** → fires the approval email (band + Shane
     CC'd), generates a €50 door-fee Square link if applicable, and
     creates the Google Calendar event
   - **Confirm (silent — no emails)** → same as above but skips the
     email + Square link. Useful for re-confirms, internal admin
     fixes, or bookings where you've already coordinated with the
     band by phone/email
   - **Tentative** → mark Tentative if you want to soft-hold while
     you check something
   - **Cancel + Email Decline** → sends the "date now taken" decline
     email with a "Pick another date" link, then archives
   - **Cancel** (silent) → cancels without sending any email
   - **Archive** → if it's spam or clearly not a fit, archive it (it
     drops out of all your lists)

### Editing a confirmed booking

When you edit a booking that's already confirmed (door time, contact
details, support act, notes — anything), the **Google Calendar event
auto-refreshes** with the new info on save. No need to manually
update the calendar. If you change a confirmed booking back to
tentative/hold/inquiry, the calendar event is automatically deleted
so the calendar doesn't show a confirmed-looking event for something
that isn't.

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

### Publish a gig to Squarespace

When a gig is confirmed and ready to go on the website:

1. Open the booking. Scroll to the **Squarespace Listing** card
   (only appears on confirmed bookings that aren't marked
   internal-only — see "Internal-only events" below).
2. The card shows a live preview of how the listing will render
   (H2 act name, H3 support act, description paragraphs, links,
   bold Doors / Gig / Ticket lines).
3. Click **Copy formatted (paste into Text Block)**. This writes
   rich-text HTML to your clipboard.
4. In Squarespace, add a **Text Block** to the event page (NOT a
   Code Block — Text Blocks inherit your site's typography). Paste.
   The H2 / H3 / bold / links all come through with your existing
   site styles.
5. If the band gave a video URL in the description, add a separate
   Squarespace **Video Block** above the text — Text Blocks can't
   render iframes/embeds. There's an inline reminder in the card
   when a video URL is detected.
6. Back in the app, set the **Squarespace listing** dropdown in the
   Fees & Listing card:

| State | When |
|---|---|
| **Not listed** | Default — gig not yet on Squarespace |
| **Listed — info pending** | On the site but missing ticket link / poster / final info |
| **Listed — complete** | Fully published, nothing missing |

The dropdown saves on change. The two intermediate states each have
their own KPI tile so you can chase the gaps weekly without losing
track.

There's also a plain-text fallback (collapsible "Plain-text version"
section) — only useful if you're pasting into a non-Squarespace
destination.

### Assign a door person

On the booking detail, the Door Person field has options:
- `pub` — Cobblestone provides one, €50 door fee charged. Auto-generates a Square payment link the band can use.
- `pub_no_fee` — Cobblestone provides one, no fee (residencies, special arrangements).
- `own` — band brings their own.
- `tbc` — to be confirmed.
- `none` — not needed.

The booking detail page shows a coloured badge at the top of the
header so you can see the current arrangement at a glance.

Confirmed gigs within 7 days with no door person set show a yellow
**Door person TBC** warning badge on the bookings list.

Confirmed gigs where the **pub** is providing (either `pub` or
`pub_no_fee`) show a blue **Doorperson needed** badge on the list
— useful for scanning staffing needs across the week.

### Send a custom message to the band

On the booking detail, **Send message** action:
- Free-text subject + body
- Wrapped in the Cobblestone brand template
- Useful for one-offs ("can you bring extra mic stands?")

### Cancel vs archive

- **Cancel** = the gig isn't happening. Status flips to Cancelled,
  badge goes black, and the booking is auto-archived. Two flavours:
  - **Cancel + Email Decline** → sends the "date now taken" email
  - **Cancel** (default) → silent, no email
- **Archive** = hide it from the active list (KPI tiles too). The
  data is still there — toggle "Show archived" on the bookings list
  to see them. Use for very old completed gigs, spam inquiries, or
  test bookings you don't want cluttering the queue.

Cancelling auto-archives. To unarchive (restore to active list),
flip on "Show archived" toggle, open the booking, and click
**Unarchive**.

### Daytime-only / non-blocking events

Some events (e.g. Dublin Jazz Coop's Sunday afternoon sessions,
private rehearsals before a show) happen during the day and
shouldn't block an evening gig from booking. On the booking
detail, tick **"Doesn't block public calendar"** — this keeps
the booking on your internal views (it shows on `/bookings`,
counts on KPI tiles, appears on the Google Calendar) but the
public booking form treats the date as **available**.

To bulk-flag a recurring contact's bookings, use:
```bash
python3 flag_nonblocking.py --email someone@example.com --confirm
```

### Filter persistence

When you filter the bookings list (status, search, date range,
view) and click into a booking, the **"Back to bookings"** button
remembers the filter and returns you to the same view. Works
through any number of edits/status changes inside the detail page.

### Residency Gigs — the in-house regulars

For events that happen at the Backroom on a recurring basis and
don't follow the normal booking workflow — Balaclavas, Caoimhe's
Monday dance class, Larry's Night, Pipers' Club, Dublin Jazz Coop
— use the **event_type "Residency Gigs"**. This gives them:

- A pink badge in the bookings list (so they read at a glance)
- A pink colour on the Google Calendar event
- Light-pink row tinting in the bookings list
- **Drops out of the "Door person TBC" KPI tile** and warning
  badges — these don't need a door person, so they shouldn't
  trigger the alert
- A **"Hide residency gigs"** filter on the bookings list — flip
  this on when you want to focus on actual external gigs

Fees, door person, and other fields stay editable — these are
defaults, not locked. Override per-booking if a residency night
ever does need fees or a door person.

**To create a new residency series:**
1. `/bookings/series/new`
2. Pick **Event Type: Residency Gigs** from the dropdown
3. Fill in act name, recurrence pattern, start/end dates
4. Submit — all generated bookings inherit the Residency Gigs tag

**Dublin Jazz Coop is special** — they happen on Sunday
afternoons (3pm-6pm), so they're flagged **non-blocking** on the
public form (an evening gig can still book the same Sunday). Each
Jazz Coop booking carries a note:

> Sunday afternoon residency — room is occupied until 6pm. Any
> evening soundcheck/load-in on the same date must be after 6pm.
> Shane handles sound. Jazz Coop manage their own door (no door
> person needed).

When confirming a Sunday-evening booking on a Jazz Coop date,
add a note to that booking's description so the band knows about
the 6pm load-in cutoff.

### What bands can update themselves (via their portal)

Each booking has a band-facing portal at `/book/<token>`. As of
May 2026 the band can update three things post-confirmation:

| Field | Why it matters |
|---|---|
| **Description** | Bio / lineup / blurb for the public listing |
| **Door + gig (start) times** | Set times can shift after confirmation — they often don't have them locked when they request the date |
| **Ticket info** — type, price, link | Bands often don't have the Eventbrite URL or final price at the moment they request the date |

What they **can't** change: the event date, the venue, the contact
details, or anything financial. Date changes still come through us.

All band-side edits write to `booking_audit` (visible at the bottom
of the booking detail page) so there's always a record.

### Acknowledging band-side changes

When a band updates their times or ticket info, an alert surfaces in
two places on your side:

- A **coloured banner** at the top of the booking detail page
  showing old → new values.
- A matching **badge** on the row in the bookings list
  (⏰ Times changed in amber, 🎟️ Ticket info changed in pink).

For **time changes** an email also fires to
`cobblestonedublin@gmail.com` — these are higher-urgency since the
gig is usually imminent.

Workflow when one of these appears:

1. Open the booking from the badge.
2. Read the banner — it shows you the current values inline.
3. Mirror the change to Squarespace (and the Google Calendar event
   if it's a time change — but the calendar updates automatically
   for confirmed bookings, so that's already done).
4. Click **Acknowledge** on the banner. Banner + badge clear, audit
   log records the acknowledgment.

### Info sheet & tech spec acknowledgment

The portal's confirmation checklist asks the band to confirm they've
read the **Info Sheet** (venue info, load-in details) and **Tech
Spec** (PA, monitors, stage layout) PDFs.

Both PDFs stay available on their portal *after* acknowledgment too
— previously the buttons disappeared once acked, but bands kept
asking for the links so they're now permanently visible. After
acking, a small "Acknowledged YYYY-MM-DD" note appears beside the
heading and the helper text changes to "always available here, open
any time."

You'll see the acked / not-acked status on the booking detail
page's checklist column.

### Internal-only events

Some events shouldn't appear on Squarespace at all — private hires,
rehearsals, filming sessions, mate-of-the-pub one-offs. Tick
**"Don't list on website (internal only)"** in the Booking Details
form and click **Save Changes**.

What that does:
- Hides the Squarespace Listing card (rich-text generator) on the
  detail page.
- Replaces the Squarespace status dropdown with a muted "Internal
  only" indicator.
- Swaps the row badge on `/bookings` to a grey **Internal only**
  pill instead of one of the pink/orange/teal listing-status
  badges.
- Excludes the booking from the "Not on Squarespace" and "Listing
  info pending" KPI tile counts.

Untick to bring it back into the listing workflow at any time.

### Weekly run sheet (printable)

`/bookings/week-sheet` — printable summary of the week's confirmed
gigs for whoever's working the door / FOH.

One card per gig with everything operationally relevant: act +
support, doors / gig / end, door person, fee status (paid/unpaid
pills), ticketing, band contact + phone, notes. **Prev / This week
/ Next week** buttons; **Print** button hides the sidebar for clean
A4 output. Cards don't split across page breaks.

Quick workflow: print every Monday and stick it behind the bar so
the team can glance at it through the week.

### Squarespace listing — 3-state dropdown

On the booking detail page, the **Squarespace listing** dropdown
has three options:

| State | Meaning |
|---|---|
| **Not listed** | Default — gig not yet on the website |
| **Listed — info pending** | On the site but waiting for info (ticket link, poster, etc.) |
| **Listed — complete** | Fully published, nothing missing |

KPI tiles match: "Not on Squarespace" + "Listing info pending"
both surface bookings that need your attention. Saves on change
— no extra click.

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
- Cancelling auto-archives, so it falls out of the active list

### A contact has multiple bookings (e.g. residencies)

For acts/promoters with several gigs (Dublin Jazz Coop has 8+ slots,
Pipers' Club is monthly, etc.), the system uses one **multi-gig
portal** per email address at `/portal/<token>`:

- One link per contact email — shows ALL their upcoming bookings
- Each gig in the list deep-links to its individual `/book/<token>`
  page (where they upload posters, ack the info sheet, etc.)
- Used by the **portal-intro mailer** so a contact with 8 dates gets
  ONE email instead of 8 separate ones

If a band lands on a per-booking page (`/book/<token>`) and they have
other active bookings under the same email, a blue **"You have N
other bookings — View all →"** banner appears at the top so they can
jump to the multi-gig view.

To send portal-intro emails to all confirmed bookings 14+ days out:
```bash
python3 bookings_send_portal_links.py --dry-run    # preview
python3 bookings_send_portal_links.py              # actually send
```

Idempotent — won't double-send to anyone who's already had one.

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
| **Weekly run sheet (printable)** | `/bookings/week-sheet` |
| Single booking | `/bookings/<id>` |
| Add booking manually | `/bookings/new` |
| Quick hold | Modal on `/bookings` |
| Recurring series | `/bookings/series` |
| Blackout dates | `/bookings/blackouts` |
| Band contacts | `/bookings/contacts` |
| Public gig form | `/book` |
| Public other form | `/book/other` (filming, rehearsal, private hire) |
| Band per-booking portal | `/book/<token>` (one per booking) |
| Multi-gig contact portal | `/portal/<token>` (one per email) |
| Sound engineer view | `/sound` (Shane's login only) |

Production URL: `https://bookings.cobblestonepub.ie` (or
`https://cobblestone-pub.onrender.com` if the custom domain isn't
fully set up yet).

---

_Last updated: 15 May 2026 — Camille + Nheaca handover._

---

_Last updated: 11 May 2026 (launch day — go-live)._
