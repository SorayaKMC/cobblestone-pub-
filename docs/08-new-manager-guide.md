# First Day for a New Manager

This is the onboarding sequence for anyone new taking over Cobblestone
operations using this app. Designed to take roughly half a day of
focused time over the first week.

## Before Day 1 — accounts and access

Whoever's onboarding the new manager needs to set up:

1. **A Cobblestone Workspace email** (e.g. `name@cobblestonepub.ie`)
   created in Google Workspace Admin.
2. **Add them to Square** as a Team Member with the right role.
3. **Add them to the Cobblestone Drive** invoices folder as a Viewer
   (or Editor if they'll handle invoice approval).
4. **Decide if they need Render access** — usually no. Only the person
   responsible for deploys + env var changes needs it.
5. **Send them this docs folder URL** ahead of Day 1 so they can read.

## Day 1 — orientation (90 min)

Sit with them and walk through:

1. **Open the app** at the Render URL. Sign in if Basic Auth is set.
2. **Dashboard tour** (15 min). Point out:
   - The KPI strip (yesterday's net sales, YoY uplift, payroll % of net,
     T-shirt totals)
   - Daily sales chart vs 2025
   - VAT periods at the bottom
3. **Settings tour** (15 min). Show the employee directory. Show what
   each Category means. Show the Sync from Square button.
4. **Bookkeeping tour** (20 min). Show the pending invoice queue. Open
   one to show the AI extraction. Approve one together. Show the Drive
   watcher status panel and click Scan Drive Now.
5. **Payroll tour** (20 min). Open the previous (already-finalized)
   week. Walk through the columns. Open the Accountant Files page.
6. **PTO tour** (10 min). Show the summary. Log a fake leave entry then
   delete it (so they see the flow without messing up real data).
7. **Bookings tour** (10 min). Show the active bookings list. Open one
   to show the detail page + portal link.

Don't try to teach them everything. The goal is "they know where things
are."

## Week 1 — shadow

For the first weekly cycle, the new manager **watches** while you do
each step:

- Monday-Tuesday: payroll preparation
- Wednesday-Thursday: process Peter's reply, generate drafts
- Friday: invoice approval
- Sunday: review next week's bookings

Have them keep notes on questions. Answer at the end of each session.

## Week 2 — co-pilot

The new manager does the daily and weekly tasks **with you watching**:

- They click the buttons.
- They confirm the values.
- They make decisions about edge cases.
- You confirm before they hit Save / Send.

Common pitfalls to call out:

- **Don't click Send on draft emails until you've checked attachments.**
- **Always Save Tips, Cleaning & Bonus before clicking Finalize Week.**
  Once finalized, edits need the admin password.
- **Approve only when you've verified the supplier name.** "Unknown"
  shows up when Claude can't read the supplier; always fix before
  approving.
- **Sync from Square before adding emails manually.** Avoids the
  manual edit getting overwritten.

## Week 3 onwards — solo

The new manager runs the cycle on their own. You stay reachable for
questions but don't sit with them.

A useful habit: at the end of week 4, do a 30-minute review together —
what's been smooth, what's been confusing, what would they change.
Update these docs based on their feedback.

## Reference materials

Hand them these as a reading list:

1. [SOP.md](SOP.md) — bookmark this; refer to the troubleshooting table
   any time something looks wrong.
2. The numbered briefs (01-07) — read in order over the first week.
3. `Cobblestone_Bookings_SOP.pdf` — only if they're handling bookings;
   it's the full deep-dive.
4. `Cobblestone_Manager_Guide.html` — older training material; still
   relevant for general operations philosophy.

## When they're stuck

If they hit something not in the docs:

1. Check the **flash messages** at the top of the page — almost always
   say what's wrong in plain English.
2. Check the **troubleshooting table** in SOP.md.
3. If still stuck, the Render logs (cobblestone-pub → Logs) usually
   tell the full story. Look for `[gmail]`, `[drive]`, `[pto-weekly]`
   prefixes.
4. Last resort — ping the person who set up the app.

## Granting them more access later

As they grow into the role:

- **Render access** — if they'll be responsible for deploys or env var
  changes, add them as a collaborator.
- **GCP access** — only needed if they'll rotate the service account
  key or change Workspace delegation. Most managers never need this.
- **Stripe / payments** — separate from this app; out of scope.
