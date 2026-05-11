# Backroom Bookings

> **For day-to-day workflow, see the dedicated docs:**
> - [10 — Go-Live Runbook (May 2026)](10-bookings-go-live-may-2026.md)
> - [11 — Manager SOP](11-bookings-manager-sop.md)
> - [12 — Shane's Quick Reference](12-shane-quick-reference.md)
>
> This file is the high-level system overview.

**URLs:**
- Public gig form: `/book`
- Public other-events form: `/book/other` (filming, rehearsal, private)
- Admin tracker: `/bookings`
- Per-booking detail: `/bookings/<id>`
- Per-booking band portal: `/book/<token>` (one per booking)
- Multi-gig contact portal: `/portal/<token>` (one per email)
- Sound engineer view: `/sound` (Shane's login)

## What it does

End-to-end management for The Backroom (and Upstairs) gigs:

- Bands submit a booking request via the public form.
- Management reviews and confirms (or marks tentative / rejects).
- A confirmation email goes out with a unique band-facing portal link.
- The portal lets bands re-confirm, read the info sheet, see door
  arrangements, and pay venue/door fees via Square Payment Links.
- A separate cron job sends pre-show reminders and door-confirmation
  nudges.
- The admin tracker shows everything past, present, and future, with
  filters and venue / status badges.

There's a separate, more detailed SOP for this module (the
`Cobblestone_Bookings_SOP` PDF in the project root). This brief is the
high-level overview.

## Day-to-day flow

### When a band submits a request

1. New booking lands at `/bookings` with status **Inquiry**.
2. Open it. Review the act, date, attendance estimate, ticketing.
3. Decide:
   - **Confirm** → triggers a confirmation email with a portal link.
   - **Tentative** → soft-hold; can move to Confirmed later.
   - **Reject** → polite decline email.
4. If confirming, double-check the door arrangements and ticketing
   fields are populated before sending.

### Pre-show

- The reminder cron runs once a day. Bookings within ~7 days get a
  "ready to play?" email; bookings within ~2 days get a door-arrangement
  reminder.
- If a band hasn't confirmed door arrangements close to the date, you
  can reach out manually via their email or phone (both shown on the
  booking detail page).

### Day of show

- Door staff look up the act on `/bookings` (filter to today).
- Door fees, if applicable, can be marked paid in the booking detail.
- The Toyota-style Kanban inventory module isn't part of bookings —
  see `/admin` for that.

### After the show

- Auto-complete: a daily cron marks past bookings as **Completed**
  automatically.
- You can still edit or add notes after that for record-keeping.

## Key admin pages

- **`/bookings`** — main list. Filters by venue, status, date range,
  search by act name.
- **`/bookings/blackouts`** — dates the venue is unavailable (private
  events, maintenance). Shows on the public form.
- **`/bookings/series`** — recurring bookings (e.g. weekly residencies).
- **`/bookings/contacts`** — saved band contacts so repeat acts auto-
  fill on the public form.

## Public + portal pages

- **`/book`** — public booking form. Anyone can submit.
- **`/book/<token>`** — band's private portal. Token is unique per
  booking; never expose publicly.
- The portal has tabs for Info Sheet, Tech Spec, Door Arrangements,
  Payments. Each acknowledged action is logged in the booking audit.

## Common questions

- **A band says they didn't get the email:** check Render logs for the
  send timestamp. If it sent, ask them to check spam (the portal link
  often gets flagged on first send). You can re-trigger the
  confirmation email from the booking detail.
- **The public form rejects a date:** that date is on the blackout
  calendar. Either change the blackout or pick a different date.
- **A series booking didn't auto-create:** series generation runs daily.
  If urgent, manually trigger from `/bookings/series`.

## When something looks wrong

- **Portal link is dead:** the token may have been regenerated. Check
  the booking detail page for the current public_token and re-send.
- **Reminder cron not running:** check the `cobblestone-daily-reminders`
  Render service logs. It pings `/admin/run-reminders` once a day.
- **Squarespace payment didn't sync:** verify the Square webhook is
  configured to hit `/admin/square-webhook` on the cobblestone-pub
  service.

For deeper detail on bookings, refer to:
- [11 — Manager SOP](11-bookings-manager-sop.md) — primary day-to-day reference
- [10 — Go-Live Runbook](10-bookings-go-live-may-2026.md) — pre-launch + cutover
- [12 — Shane's Quick Reference](12-shane-quick-reference.md) — engineer view
