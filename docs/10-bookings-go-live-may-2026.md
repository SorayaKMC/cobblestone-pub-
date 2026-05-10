# Backroom Bookings Portal — Go-Live Runbook (May 2026)

This is the one-time playbook for cutting over from spreadsheet/email
bookings to the Cobblestone bookings portal. Once executed, this
document becomes a historical record — day-to-day operations live in
[11-bookings-manager-sop.md](11-bookings-manager-sop.md).

**Target launch date:** Monday, 11 May 2026
**Owner:** Soraya
**On-call (day 1):** Soraya + Tomás

---

## What is "live" today (committed + deployed)

The Render service `cobblestone-pub` already runs the new portal at
`https://cobblestone-pub.onrender.com` (custom subdomain
`bookings.cobblestonepub.ie` pending DNS — see below).

**Public-facing:**
- `/book` — gig inquiry form (Backroom-only for V0; Upstairs hidden)
- `/book/other` — second form for filming, practice, private events
- `/book/<token>` — band-facing portal (poster upload, status, etc.)

**Internal:**
- `/bookings` — tracker list with KPI tiles, status filters, search,
  archive toggle, Quick Hold modal
- `/bookings/calendar` — visual calendar
- `/bookings/<id>` — detail view with Recent Emails panel,
  audit log, archive button
- `/bookings/blackouts`, `/bookings/series`, `/bookings/contacts`

**Email sender:** `bookings@cobblestonepub.ie` via Google Workspace
SMTP. SPF/DKIM/DMARC active on `cobblestonepub.ie`.

**Data state in the production DB:**
- ~90 confirmed bookings (63 form-imported + 27 Balaclavas series)
- ~32 inquiries from form responses (16 needs-review + 16 pending)
- All upcoming events through Dec 30 2026 mirrored in the
  `bookings@cobblestonepub.ie` Google Calendar (color-coded: sage =
  form-backed, lavender = upstairs, graphite = bar/non-Backroom,
  default yellow = calendar-only)
- Email-snippet cache covers 57 of those bookings inline on the detail
  page; rest fall back to the "Open in Gmail" deep-link

---

## Final pre-launch checklist

Tick each before flipping the announcement switch.

### Infrastructure
- [ ] **Custom subdomain** — `bookings.cobblestonepub.ie` CNAME at
  Blacknight points at the Render-supplied target. SSL shows green in
  Render. Update Render env var `PUBLIC_BASE_URL` to
  `https://bookings.cobblestonepub.ie` so portal links in emails use
  the new URL.
- [ ] **DKIM / SPF / DMARC** — send a real test email from the portal
  (`/admin/test-email` or trigger any send) to a personal Gmail.
  Open → Show original → confirm all three say `PASS`. Already verified
  green earlier today; re-test from production if anything has changed
  since.
- [ ] **Auto-forward** — `cobblestonedublin@gmail.com` set to forward
  to `bookings@cobblestonepub.ie` so any band replying to an old thread
  still reaches the new inbox. (Gmail → Settings → Forwarding.)
- [ ] **Render env vars** — confirm: `SQUARE_ACCESS_TOKEN`,
  `SQUARE_LOCATION_ID`, `SMTP_*`, `BOOKING_FROM`, `BOOKING_REPLY_TO`,
  `PUBLIC_BASE_URL`, `GOOGLE_SERVICE_ACCOUNT_JSON`,
  `GOOGLE_CALENDAR_ID_BACKROOM` (= `bookings@cobblestonepub.ie`),
  `AUTH_USERNAME`, `AUTH_PASSWORD`.
- [ ] **DB backup snapshot** — Render Shell:
  `cp /var/data/cobblestone.db /var/data/cobblestone.db.golive-backup`
  Take it Sunday evening so we have a clean rollback point.

### Data
- [ ] **Adjudicate the 16 needs-review conflicts** in the bookings UI.
  Each one is a real conflict (Sweet Jayne vs Josh Fortenbery on May
  22, Allied Irish Bandits vs Limbo Days on Oct 10, etc.). Confirm
  the winner; cancel + send decline email to the loser.
- [ ] **Decide on the 5 calendar conflicts surfaced earlier**:
  - May 16 Brid Sheehan ceili — sound confirmed?
  - May 16 Aislinn (PBP by-election) 3-7pm — same-day conflict with
    ceili — clarify ceili time, decline if needed
  - Jul 17 "Seasons s2 e4" — what is it? (movable for Frank Kane?)
  - Oct 10 Limbo Days vs Allied Irish Bandits — Giada wins (first
    submission, on calendar), apologise to Lee Page
  - Oct 16 Aoife (BAC 7) — confirm matches existing calendar entry
- [ ] **Send portal-intro emails** to confirmed bookings 14+ days out.
  ```bash
  python3 bookings_send_portal_links.py --dry-run
  python3 bookings_send_portal_links.py
  ```
  Default skips bookings within 14 days (mid-prep — don't disturb)
  and skips already-introed (idempotent).

### Comms
- [ ] **Update Squarespace** — replace the existing
  `/book-the-backroom` page (or equivalent) with a redirect/link to
  `https://bookings.cobblestonepub.ie/book`.
- [ ] **Save the canned Gmail reply** in Settings → See all settings →
  Advanced → Templates. Use the copy from the email-templates session
  (the one that nudges email inquirers to use the form). Subject:
  "Re: {subject} — please use our booking form".
- [ ] **Phone signature / WhatsApp template** — update so when bands
  ask via phone, the redirect text matches.

### Soft launch
- [ ] **Submit a real test inquiry** via `/book` from a personal email
  → confirm it lands in `/bookings` as Inquiry → click Confirm →
  verify confirmation email + Shane CC + portal link work
  end-to-end → cancel/delete the test.
- [ ] **Tomás briefed** on the new flow (point him at the manager SOP).
- [ ] **Camille / Nheaca briefed** if they're handling bookings on
  any nights.

---

## Monday morning runbook

**0830** — Coffee. Open the dashboard, tail Render logs in another
tab.

**0900** — Pre-flight check (5 min):
- Open `/bookings` — KPI tiles render, no error banner
- Open `/bookings/calendar` — calendar loads, this week's bookings
  visible, colors correct
- Open `/book` (in incognito, no auth) — public form loads, validates
- Send a test inquiry → verify it lands → cancel/delete

**0930** — Flip the public switch:
- Update Squarespace booking page → live
- Post on Instagram / socials with the new URL
- Email the Cobblestone mailing list (if applicable)

**Throughout the day** — Check `/bookings` every couple of hours.
Any new inquiry should get a quick reply within 24h to set the
expectation.

---

## What's NOT live yet (known gaps)

These are deliberately left for post-launch. Document, but don't
panic about them.

| Gap | Workaround | Plan |
|---|---|---|
| **2-week reminder email auto-fire** | Template exists (`send_two_week_reminder`) but isn't on a scheduler. Manually send via the booking detail page if needed. | Wire up daily cron after launch. |
| **Door-person Yes/No portal endpoint** | The button exists in the 2-week email but the portal route to receive the choice isn't built. Door-person decision still happens via email/phone. | Build the `/book/<token>/door-person` route. |
| **Recent emails inline panel — refresh** | Snippet cache is static (data/email_snippets.json). New emails arriving after today's cache won't appear. The "Open in Gmail" deep-link always works for live data. | Set up Gmail API access from Render with service account + domain-wide delegation, or schedule periodic cache refreshes. |
| **DB schema migration (status collapse 5→3)** | Current schema uses inquiry/tentative/confirmed/completed/cancelled (+ new "hold"). Whiteboard discussed collapsing to pending/booked/etc. | Phase 2 — additive migration. Existing statuses keep working. |
| **Sound engineer fee mode field** | Email templates say "venue fee €150 payable to Shane" — works for current default. The "Cobblestone collects + invoices Shane" mode requires a new schema field. | Phase 2. |
| **Listing status dropdown** | Current model: single Squarespace-published timestamp. Whiteboard had a 3-state dropdown (not created / created waiting info / created live). | Phase 2 schema. |
| **Email enrichment from threads** | URLs and posters from email threads aren't auto-extracted into bookings. Manager must check the Recent Emails panel manually. | Future enhancement. |

---

## Redundancies & rollback

### If the portal is unreachable on Monday morning
1. Check Render dashboard → service status
2. Check the most recent deploy — did it fail? Roll back to previous
   green deploy (Render → Deploys → previous → "Redeploy")
3. Fallback: revert the Squarespace booking page change so the old
   form is restored. Bands keep using the old flow until the portal
   is back.

### If emails aren't sending
1. Check Render logs for `[email] Failed to send` errors
2. Verify SMTP env vars on Render are correct (SMTP_HOST,
   SMTP_USERNAME, SMTP_PASSWORD = the 16-char app password)
3. Test sending one manually via the staff-message action on a
   booking — easier to isolate the failure
4. Fallback: send manually from `bookings@cobblestonepub.ie` Gmail
   directly using the canned template

### If the database is corrupted or you need to roll back imports
1. Render Shell:
   ```bash
   cp /var/data/cobblestone.db.golive-backup /var/data/cobblestone.db
   # restart the app
   ```
2. Re-run the imports from a clean state if needed (scripts are
   idempotent — safe to re-run)

### If a band reports they didn't get an email
1. Check their record in `/bookings/<id>` — confirmation_sent_at field
   tells you if it fired
2. Check audit log — should show the email_sent entry with timestamp
3. Likely culprit: their email provider spam-filtered. Send manually
   from `bookings@cobblestonepub.ie` and ask them to whitelist that
   address.

### If Tomás is unavailable and a band needs an immediate decision
- Check the calendar for conflicts before promising anything
- Use Quick Hold to soft-reserve the date while Tomás is reachable
- Confirm via phone, then create the booking with the manual Add
  Booking form

---

## Day-1 monitoring

Things worth glancing at periodically Monday:

- **Render logs** for `[email] Failed` or `[bookings] error` lines
- **`/bookings`** for new inquiries that need triage
- **Spam folder** of `bookings@cobblestonepub.ie` — first day, check
  twice in case auto-reply rules over-filter
- **Inbox** for replies to portal-intro blasts — bands may say "I
  didn't book this" or "I need to update my date"

A few inquiries that day = healthy. Zero inquiries = something is
broken (form not loading, or social posts didn't go out).

---

## Comms / announcement plan

Suggested phrasing for the Squarespace + Instagram update:

> 🎵 **New booking process for the Cobblestone Backroom**
> If you're a band looking to play the Backroom, our new booking
> portal is live: bookings.cobblestonepub.ie/book
> Submit a request, see real-time availability, and we'll be back to
> you in a few days. Questions? bookings@cobblestonepub.ie or
> +353 85 736 2447.

Don't oversell or apologize for the change — keep it matter-of-fact.

---

## Who to call

| Issue | Who |
|---|---|
| Portal down / app errors | Soraya (technical owner) |
| Booking decisions | Tomás (primary booker) |
| Sound / day-of issues | Shane Hannigan (`onsoundie@gmail.com`, +353 85 175 8254) |
| Render / hosting / DNS | Soraya |
| Workspace / DKIM / email | Soraya |
| Square / payments | Tomás for transaction-level, Soraya for setup |

---

_Last updated: 9 May 2026 (evening before go-live)._
