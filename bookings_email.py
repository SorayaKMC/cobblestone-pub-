"""Email helpers for the Cobblestone Pub backroom booking system.

Sends auto-acknowledgement and (in Phase 3) confirmation emails to bands.

All email settings are optional — if SMTP is not configured the functions log
a message and return False so the booking flow continues uninterrupted.

Required environment variables (all optional):
    SMTP_HOST        — SMTP server hostname (e.g. smtp.gmail.com)
    SMTP_PORT        — defaults to 587
    SMTP_USERNAME    — sender account / email address
    SMTP_PASSWORD    — password or app password
    BOOKING_FROM     — "from" display address (defaults to SMTP_USERNAME)
    BOOKING_REPLY_TO — reply-to address (defaults to bookings@cobblestonepub.ie)
    PUBLIC_BASE_URL  — base URL for portal links in emails
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _smtp_configured():
    return bool(config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD)


def _send(to_email, subject, body_html, body_text=None):
    """Compose and send one email. Returns True on success, False on failure."""
    if not _smtp_configured():
        print(f"[email] SMTP not configured — skipped: {subject!r} → {to_email}")
        return False

    from_addr = config.BOOKING_FROM or config.SMTP_USERNAME
    reply_to  = config.BOOKING_REPLY_TO or from_addr

    msg = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = from_addr
    msg["To"]       = to_email
    msg["Reply-To"] = reply_to

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(from_addr, to_email, msg.as_string())
        print(f"[email] Sent {subject!r} → {to_email}")
        return True
    except Exception as e:
        print(f"[email] Failed to send to {to_email}: {e}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_booking_ack(booking, base_url=None):
    """Send the auto-acknowledgement email to the band after form submission.

    booking  — sqlite3.Row returned by db.get_booking()
    base_url — optional override; falls back to config.PUBLIC_BASE_URL
    """
    if not booking["contact_email"]:
        return False

    base = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    portal_url = f"{base}/book/{booking['public_token']}"
    act        = booking["act_name"]
    name       = booking["contact_name"] or "there"
    event_date = booking["event_date"]
    venue      = booking["venue"]

    subject = f"Cobblestone Pub — Booking inquiry received: {act}"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <!-- Header -->
        <tr>
          <td style="background:#1c1c2e;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">🍺 Cobblestone Pub</h2>
            <p  style="margin:4px 0 0;color:#aaa;font-size:13px;">
              Backroom &amp; Upstairs Bookings
            </p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;font-size:16px;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              Thanks for reaching out — we've received your booking inquiry for
              <strong>{act}</strong> at the Cobblestone Pub ({venue}) on
              <strong>{event_date}</strong>.
            </p>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#333;">
              Tomás will review and get back to you within 2–3 working days.
              In the meantime you can check your booking status at any time:
            </p>
            <!-- CTA button -->
            <table cellpadding="0" cellspacing="0" style="margin:0 auto 24px;">
              <tr>
                <td style="background:#2563eb;border-radius:6px;">
                  <a href="{portal_url}"
                     style="display:block;padding:14px 28px;color:#fff;
                            text-decoration:none;font-weight:bold;font-size:15px;">
                    View your booking →
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 16px;font-size:13px;color:#777;">
              Or copy this link: <a href="{portal_url}" style="color:#2563eb;">{portal_url}</a>
            </p>
            <p style="margin:0 0 8px;font-size:15px;color:#333;">
              If you have any questions just reply to this email.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              Thanks,<br>
              <strong>The Cobblestone Pub team</strong>
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8f8f8;padding:16px 32px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;·&nbsp;
            <a href="https://cobblestonepub.ie" style="color:#999;">cobblestonepub.ie</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    text = f"""Hi {name},

Thanks for reaching out — we've received your booking inquiry for {act} at the
Cobblestone Pub ({venue}) on {event_date}.

Tomás will review and get back to you within 2–3 working days.

Check your booking status here:
{portal_url}

If you have any questions, reply to this email.

Thanks,
The Cobblestone Pub team

--
77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, text)


def send_booking_confirmation(booking, base_url=None):
    """Send confirmation email to the band when Tomás confirms the booking.

    booking  — sqlite3.Row returned by db.get_booking()
    base_url — optional override; falls back to config.PUBLIC_BASE_URL
    """
    if not booking["contact_email"]:
        return False

    base       = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    portal_url = f"{base}/book/{booking['public_token']}"
    act        = booking["act_name"]
    name       = booking["contact_name"] or "there"
    venue      = booking["venue"]
    door_time  = booking["door_time"]  or "TBC"
    start_time = booking["start_time"] or "TBC"

    try:
        from datetime import datetime as _dt
        d = _dt.strptime(booking["event_date"], "%Y-%m-%d")
        date_str = d.strftime("%A, %-d %B %Y")
    except Exception:
        date_str = booking["event_date"]

    times_str = f"Doors {door_time}"
    if start_time != "TBC":
        times_str += f" · Music starts {start_time}"

    subject = f"Cobblestone Pub — Booking Confirmed: {act} on {date_str}"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <tr>
          <td style="background:#16a34a;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">✅ Booking Confirmed!</h2>
            <p style="margin:4px 0 0;color:#dcfce7;font-size:13px;">
              Cobblestone Pub — Backroom &amp; Upstairs Bookings
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;font-size:16px;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              Great news — your booking at the <strong>Cobblestone Pub</strong> is confirmed! 🎉
            </p>
            <!-- Booking summary box -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#f0fdf4;border:1px solid #bbf7d0;
                          border-radius:8px;margin:0 0 24px;">
              <tr>
                <td style="padding:20px;">
                  <table width="100%" cellpadding="4" cellspacing="0"
                         style="font-size:14px;color:#333;">
                    <tr>
                      <td style="color:#6b7280;width:100px;">Act</td>
                      <td><strong>{act}</strong></td>
                    </tr>
                    <tr>
                      <td style="color:#6b7280;">Date</td>
                      <td><strong>{date_str}</strong></td>
                    </tr>
                    <tr>
                      <td style="color:#6b7280;">Venue</td>
                      <td><strong>{venue}, Cobblestone Pub</strong></td>
                    </tr>
                    <tr>
                      <td style="color:#6b7280;">Times</td>
                      <td><strong>{times_str}</strong></td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              You can view your booking details and upload any remaining files
              (poster, artist bio) via your booking portal:
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 auto 24px;">
              <tr>
                <td style="background:#16a34a;border-radius:6px;">
                  <a href="{portal_url}"
                     style="display:block;padding:14px 28px;color:#fff;
                            text-decoration:none;font-weight:bold;font-size:15px;">
                    View your booking →
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 8px;font-size:14px;color:#555;">
              If you have any questions, just reply to this email.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              Looking forward to it!<br>
              <strong>The Cobblestone Pub team</strong>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f8f8;padding:16px 32px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;·&nbsp;
            <a href="https://cobblestonepub.ie" style="color:#999;">cobblestonepub.ie</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    text = f"""Hi {name},

Great news — your booking at the Cobblestone Pub is confirmed! 🎉

Act:   {act}
Date:  {date_str}
Venue: {venue}, Cobblestone Pub
Times: {times_str}

View your booking and upload files (poster, bio) here:
{portal_url}

If you have any questions, reply to this email.

Looking forward to it!
The Cobblestone Pub team

--
77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, text)


def send_booking_reminder(booking, base_url=None):
    """Send a 3-day reminder email to the band.

    Called by the /admin/run-reminders cron endpoint.
    """
    if not booking["contact_email"]:
        return False

    base       = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    portal_url = f"{base}/book/{booking['public_token']}"
    act        = booking["act_name"]
    name       = booking["contact_name"] or "there"
    venue      = booking["venue"]
    door_time  = booking["door_time"]  or "TBC"
    start_time = booking["start_time"] or "TBC"

    try:
        from datetime import datetime as _dt
        d = _dt.strptime(booking["event_date"], "%Y-%m-%d")
        date_str = d.strftime("%A, %-d %B %Y")
    except Exception:
        date_str = booking["event_date"]

    times_str = f"Doors {door_time}"
    if start_time != "TBC":
        times_str += f" · Music starts {start_time}"

    subject = f"See you in 3 days! {act} at Cobblestone Pub — {date_str}"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <tr>
          <td style="background:#2563eb;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">⏰ 3 Days to Go!</h2>
            <p style="margin:4px 0 0;color:#bfdbfe;font-size:13px;">
              Cobblestone Pub — Backroom &amp; Upstairs Bookings
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;font-size:16px;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              Just a quick reminder — <strong>{act}</strong> plays the Cobblestone Pub
              in <strong>3 days</strong>. Here are the details:
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#eff6ff;border:1px solid #bfdbfe;
                          border-radius:8px;margin:0 0 24px;">
              <tr>
                <td style="padding:20px;">
                  <table width="100%" cellpadding="4" cellspacing="0"
                         style="font-size:14px;color:#333;">
                    <tr>
                      <td style="color:#6b7280;width:100px;">Date</td>
                      <td><strong>{date_str}</strong></td>
                    </tr>
                    <tr>
                      <td style="color:#6b7280;">Venue</td>
                      <td><strong>{venue}, Cobblestone Pub</strong><br>
                          <span style="color:#6b7280;font-size:12px;">
                            77 King St N, Smithfield, Dublin 7
                          </span>
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#6b7280;">Times</td>
                      <td><strong>{times_str}</strong></td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 16px;font-size:14px;color:#555;">
              If you haven't already, you can upload your poster or artist bio
              via your booking portal before the show:
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 auto 24px;">
              <tr>
                <td style="background:#2563eb;border-radius:6px;">
                  <a href="{portal_url}"
                     style="display:block;padding:12px 24px;color:#fff;
                            text-decoration:none;font-weight:bold;font-size:14px;">
                    View your booking →
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 8px;font-size:14px;color:#555;">
              Any questions? Reply to this email or call us at the pub.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              See you soon!<br>
              <strong>The Cobblestone Pub team</strong>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f8f8;padding:16px 32px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;·&nbsp;
            <a href="https://cobblestonepub.ie" style="color:#999;">cobblestonepub.ie</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    text = f"""Hi {name},

Just a quick reminder — {act} plays the Cobblestone Pub in 3 days!

Date:  {date_str}
Venue: {venue}, Cobblestone Pub
       77 King St N, Smithfield, Dublin 7
Times: {times_str}

Upload your poster or artist bio here if you haven't already:
{portal_url}

Any questions? Reply to this email or call us at the pub.

See you soon!
The Cobblestone Pub team

--
77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, text)
