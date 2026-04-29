"""Send 'here is your portal link' emails to confirmed bookings.

Run this once to introduce the booking portal to bands that were already
confirmed before the portal existed (e.g. imported from the spreadsheet).

Usage:
    python3 bookings_send_portal_links.py [options]

Options:
    --dry-run          Preview what would be sent without actually sending anything.
    --status STATUS    Which statuses to include. Default: confirmed
                       Can be a comma-separated list, e.g. confirmed,tentative
    --min-date DATE    Only include bookings on or after this date (YYYY-MM-DD).
                       Default: today.
    --max-date DATE    Only include bookings on or before this date (YYYY-MM-DD).
    --include-all      Include bookings that already have confirmation_sent_at set
                       (i.e. bands who already received a confirmation email).
                       By default these are skipped to avoid duplicate emails.
    --base-url URL     Override the base URL for portal links.
                       Default: https://cobblestone-pub.onrender.com
    --delay SECS       Seconds to wait between emails (default: 2).

Examples:
    # Preview all confirmed upcoming bookings that haven't been emailed
    python3 bookings_send_portal_links.py --dry-run

    # Send to all confirmed bookings from today onwards
    python3 bookings_send_portal_links.py

    # Send to inquiry + tentative + confirmed, starting from a specific date
    python3 bookings_send_portal_links.py --status confirmed,tentative,inquiry --min-date 2026-05-01

    # Re-send to everyone including those who already got a confirmation email
    python3 bookings_send_portal_links.py --include-all --dry-run
"""

import sys
import time
import argparse
from datetime import date

import db
import bookings_email


DEFAULT_BASE_URL = "https://cobblestone-pub.onrender.com"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send portal intro emails to confirmed bookings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — don't send any emails.")
    parser.add_argument("--status", default="confirmed",
                        help="Comma-separated statuses to include (default: confirmed).")
    parser.add_argument("--min-date", default=None,
                        help="Only include bookings on or after this date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--max-date", default=None,
                        help="Only include bookings on or before this date.")
    parser.add_argument("--include-all", action="store_true",
                        help="Include bookings that already have confirmation_sent_at set.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"Base URL for portal links (default: {DEFAULT_BASE_URL}).")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to pause between emails (default: 2).")
    return parser.parse_args()


def main():
    args = parse_args()

    db.init_db()

    statuses = [s.strip() for s in args.status.split(",") if s.strip()]
    min_date = args.min_date or date.today().isoformat()
    max_date = args.max_date or None
    base_url = args.base_url.rstrip("/")

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Cobblestone portal link mailer")
    print(f"  Statuses  : {', '.join(statuses)}")
    print(f"  From date : {min_date}")
    if max_date:
        print(f"  To date   : {max_date}")
    print(f"  Base URL  : {base_url}")
    print(f"  Skip already-emailed: {not args.include_all}")
    print()

    # Fetch candidates
    bookings = db.list_bookings(
        status=statuses,
        start_date=min_date,
        end_date=max_date,
        limit=5000,
    )

    # Filter: must have an email address
    bookings = [b for b in bookings if b["contact_email"]]

    # Filter: skip already-emailed unless --include-all
    if not args.include_all:
        skipped_already = [b for b in bookings if b["confirmation_sent_at"]]
        bookings = [b for b in bookings if not b["confirmation_sent_at"]]
        if skipped_already:
            print(f"  Skipping {len(skipped_already)} booking(s) that already received a "
                  f"confirmation email (use --include-all to include them):")
            for b in skipped_already:
                print(f"    #{b['id']:>4}  {b['event_date']}  {b['act_name']}")
            print()

    if not bookings:
        print("No bookings to email. Done.")
        return

    print(f"Found {len(bookings)} booking(s) to email:\n")
    for b in bookings:
        already_flag = " [already confirmed]" if b["confirmation_sent_at"] else ""
        print(f"  #{b['id']:>4}  {b['event_date']}  {b['status']:<10}  "
              f"{b['act_name']:<30}  → {b['contact_email']}{already_flag}")

    if args.dry_run:
        print(f"\nDRY RUN complete — {len(bookings)} email(s) would be sent. "
              "Run without --dry-run to send for real.")
        return

    print()
    confirm = input(f"Send {len(bookings)} email(s)? Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    print()
    sent = failed = 0
    for b in bookings:
        print(f"  Sending to {b['contact_email']} ({b['act_name']}, {b['event_date']}) ... ", end="", flush=True)
        try:
            ok = bookings_email.send_portal_intro(b, base_url)
            if ok:
                db.add_booking_audit(
                    b["id"], "system", "email_sent",
                    "Portal intro email sent via bookings_send_portal_links.py",
                )
                print("sent ✓")
                sent += 1
            else:
                print("FAILED (check SMTP config)")
                failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

        if args.delay > 0 and b != bookings[-1]:
            time.sleep(args.delay)

    print(f"\nDone. Sent: {sent}  Failed: {failed}")
    if failed:
        print("Check SMTP settings — SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD must be set as env vars.")


if __name__ == "__main__":
    main()
