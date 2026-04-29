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
from email.mime.base import MIMEBase
from email import encoders as _encoders

import config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _smtp_configured():
    return bool(config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD)


def _send(to_email, subject, body_html, body_text=None, attachments=None):
    """Compose and send one email. Returns True on success, False on failure.

    attachments — optional list of (filename, mimetype, str_or_bytes) tuples
                  e.g. [("event.ics", "text/calendar", ics_string)]
    """
    if not _smtp_configured():
        print(f"[email] SMTP not configured — skipped: {subject!r} → {to_email}")
        return False

    from_addr = config.BOOKING_FROM or config.SMTP_USERNAME
    reply_to  = config.BOOKING_REPLY_TO or from_addr

    if attachments:
        # multipart/mixed wrapper so attachments sit alongside the body
        outer = MIMEMultipart("mixed")
        outer["Subject"]  = subject
        outer["From"]     = from_addr
        outer["To"]       = to_email
        outer["Reply-To"] = reply_to

        # Wrap text + html in an inner alternative part
        alt = MIMEMultipart("alternative")
        if body_text:
            alt.attach(MIMEText(body_text, "plain", "utf-8"))
        alt.attach(MIMEText(body_html, "html", "utf-8"))
        outer.attach(alt)

        for att_name, att_type, att_data in attachments:
            maintype, subtype = att_type.split("/", 1)
            if isinstance(att_data, str):
                att_data = att_data.encode("utf-8")
            part = MIMEBase(maintype, subtype)
            part.set_payload(att_data)
            _encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=att_name)
            if maintype == "text" and subtype == "calendar":
                # Some clients need this for auto-add-to-calendar
                part.add_header("Content-Type", "text/calendar; method=REQUEST")
            outer.attach(part)

        msg = outer
    else:
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


def _make_ics(booking):
    """Build a VCALENDAR ICS string for a confirmed booking.

    Returns None if the booking data is too incomplete to build a valid event.
    """
    try:
        from datetime import datetime as _dt, timedelta

        event_date = booking["event_date"]           # YYYY-MM-DD
        start_time = (booking["start_time"] or "20:00").replace(":", "")[:4]  # HHMM
        door_time  = (booking["door_time"]  or "19:00").replace(":", "")[:4]
        end_time   = booking["end_time"]

        date_nodash = event_date.replace("-", "")
        dtstart = f"{date_nodash}T{start_time}00"

        if end_time:
            dtend = f"{date_nodash}T{end_time.replace(':', '')[:4]}00"
        else:
            # Default: 3 hours after start
            st = _dt.strptime(f"{event_date} {booking['start_time'] or '20:00'}", "%Y-%m-%d %H:%M")
            dtend = (st + timedelta(hours=3)).strftime("%Y%m%dT%H%M%S")

        def _esc(s):
            return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

        act    = _esc(booking["act_name"])
        venue  = _esc(booking["venue"])
        desc   = _esc((booking["description"] or "")[:400])
        uid    = f"cobblestone-{booking['id']}@cobblestonepub.ie"
        stamp  = _dt.utcnow().strftime("%Y%m%dT%H%M%SZ")

        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Cobblestone Pub//Booking System//EN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{stamp}\r\n"
            f"DTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\n"
            f"SUMMARY:{act} | Live at Cobblestone Pub ({venue})\r\n"
            f"DESCRIPTION:{desc}\r\n"
            f"LOCATION:Cobblestone Pub\\, {venue}\\, 77 King St N\\, Smithfield\\, Dublin 7\r\n"
            "STATUS:CONFIRMED\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
    except Exception as e:
        print(f"[email] ICS generation failed: {e}")
        return None


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
              The Cobblestone staff will review and get back to you within 2–3 working days.
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

The Cobblestone staff will review and get back to you within 2–3 working days.

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
    """Send confirmation email to the band when a booking is confirmed.

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
            <!-- Useful info box -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#f8f8f8;border:1px solid #e5e7eb;
                          border-radius:8px;margin:0 0 24px;">
              <tr>
                <td style="padding:20px;">
                  <p style="margin:0 0 12px;font-size:13px;font-weight:bold;
                             color:#1c1c2e;text-transform:uppercase;letter-spacing:.5px;">
                    Reminders
                  </p>
                  <table width="100%" cellpadding="3" cellspacing="0"
                         style="font-size:13px;color:#444;">
                    <tr>
                      <td style="width:16px;vertical-align:top;">⭐</td>
                      <td><strong>Venue fee (€150)</strong> is payable directly to our sound engineer Shane on the night. This includes Shane's services and a bartender.</td>
                    </tr>
                    <tr>
                      <td style="vertical-align:top;">⭐</td>
                      <td><strong>Door person (€50)</strong> is payable to the Cobblestone on the night — cash or card. We provide a cash float. Please let us know at least one week in advance if you need one.</td>
                    </tr>
                    <tr>
                      <td style="vertical-align:top;">🎟️</td>
                      <td><strong>Ticketing</strong> is your responsibility. We recommend Eventbrite for advance sales. We don't provide a card machine at the door — bring your own if needed.</td>
                    </tr>
                    <tr>
                      <td style="vertical-align:top;">📍</td>
                      <td><strong>Access</strong> via Red Cow Lane — enter through the Cobblestone Pub. Free parking after 7pm &amp; Sundays.</td>
                    </tr>
                  </table>
                  <table cellpadding="0" cellspacing="0" style="margin-top:16px;">
                    <tr>
                      <td style="padding-right:10px;">
                        <a href="{base}/static/docs/Cobblestone_Backroom_Info_Sheet.pdf"
                           style="display:inline-block;background:#1c1c2e;color:#fff;
                                  padding:10px 18px;border-radius:6px;text-decoration:none;
                                  font-size:13px;font-weight:bold;">
                          📄 Info Sheet
                        </a>
                      </td>
                      <td>
                        <a href="{base}/static/docs/Cobblestone_Backroom_Tech_Spec.pdf"
                           style="display:inline-block;background:#f3f4f6;color:#1c1c2e;
                                  border:1px solid #d1d5db;padding:10px 18px;border-radius:6px;
                                  text-decoration:none;font-size:13px;font-weight:bold;">
                          🎛️ Tech Spec
                        </a>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- Shane callout -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1c1c2e;border-radius:8px;margin:0 0 24px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 4px;font-size:11px;font-weight:bold;
                             color:#9ca3af;text-transform:uppercase;letter-spacing:.8px;">
                    Your sound engineer
                  </p>
                  <p style="margin:0 0 12px;font-size:18px;font-weight:bold;color:#fff;">
                    🎤 Shane Hannigan
                  </p>
                  <table cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="padding-right:24px;">
                        <a href="tel:+353851758254"
                           style="color:#93c5fd;text-decoration:none;font-size:14px;">
                          📞 +353 (85) 175 8254
                        </a>
                      </td>
                      <td>
                        <a href="mailto:onsoundie@gmail.com"
                           style="color:#93c5fd;text-decoration:none;font-size:14px;">
                          ✉️ onsoundie@gmail.com
                        </a>
                      </td>
                    </tr>
                  </table>
                  <p style="margin:12px 0 0;font-size:13px;color:#d1d5db;line-height:1.5;">
                    Please contact Shane directly to arrange your <strong style="color:#fff;">sound check,
                    load-in, and load-out</strong>. He'll be there on the night and is your main
                    point of contact for anything technical.
                  </p>
                  <p style="margin:8px 0 0;font-size:12px;color:#f87171;">
                    ⚠️ No drum backline available — please arrange hire in advance if needed.
                  </p>
                </td>
              </tr>
            </table>

            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              You can view your booking, upload your poster or artist bio, and
              check all the details via your booking portal:
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
              If you have any questions, just reply to this email or call us on
              <a href="tel:+353894770682" style="color:#555;">+353 89 477 06 82</a>.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              Looking forward to it!<br>
              <strong>The Cobblestone staff</strong>
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

── REMINDERS ─────────────────────────────────────────────────────
⭐ Venue fee (€150) is payable directly to Shane on the night —
   includes use of the room, sound engineer, and staffed bar.
⭐ Door person (€50) payable to the Cobblestone on the night.
   Let us know at least one week in advance if you need one.
── YOUR SOUND ENGINEER ───────────────────────────────────────────
🎤 Shane Hannigan
   📞 +353 (85) 175 8254
   ✉️ onsoundie@gmail.com

   Please contact Shane directly to arrange your sound check,
   load-in, and load-out. He is your main technical contact
   for the night.
   ⚠️ No drum backline available — arrange hire in advance if needed.
🎟️ Ticketing is your responsibility. We recommend Eventbrite or
   Ticket Tailor. No card machine at the door — bring your own.
📍 Access via Red Cow Lane — enter through the Cobblestone Pub.
   Free parking after 7pm & Sundays.

📄 Info Sheet: {base}/static/docs/Cobblestone_Backroom_Info_Sheet.pdf
🎛️ Tech Spec:  {base}/static/docs/Cobblestone_Backroom_Tech_Spec.pdf
──────────────────────────────────────────────────────────────────

View your booking and upload your poster/bio here:
{portal_url}

If you have any questions, reply to this email.

Looking forward to it!
The Cobblestone Pub team

--
77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    ics = _make_ics(booking)
    atts = [("cobblestone_event.ics", "text/calendar", ics)] if ics else None
    return _send(booking["contact_email"], subject, html, text, attachments=atts)


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


def send_staff_message(booking, subject, body_text, base_url=None):
    """Send a staff-composed custom message to the band.

    The message body is wrapped in the standard Cobblestone HTML frame so it
    looks polished in the band's inbox, and the portal link is appended.

    booking   — sqlite3.Row from db.get_booking()
    subject   — email subject line (staff writes this)
    body_text — plain text message body (staff writes this)
    base_url  — optional override for the portal URL
    """
    if not booking["contact_email"]:
        return False

    base       = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    portal_url = f"{base}/book/{booking['public_token']}"
    act        = booking["act_name"]

    # Convert plain text to simple HTML paragraphs
    html_body  = "".join(
        f"<p style='margin:0 0 12px;font-size:15px;line-height:1.6;color:#333;'>{line}</p>"
        for line in (body_text or "").split("\n") if line.strip()
    ) or "<p style='color:#333;'>—</p>"

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
          <td style="background:#1c1c2e;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">🍺 Cobblestone Pub</h2>
            <p style="margin:4px 0 0;color:#aaa;font-size:13px;">
              Message re: {act}
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            {html_body}
            <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
            <p style="margin:0;font-size:13px;color:#777;">
              View your booking status at any time:
              <a href="{portal_url}" style="color:#2563eb;">{portal_url}</a>
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

    plain = f"""{body_text}

---
View your booking: {portal_url}

77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, plain)


def send_cancellation_alert_to_pub(booking, base_url=None, cancelled_by="band", reason=""):
    """Alert the pub's inbox when a band cancels their own booking.

    Sent to BOOKING_FROM (the staff inbox) so the Cobblestone staff see it immediately.
    """
    staff_email = config.BOOKING_FROM or config.SMTP_USERNAME
    if not staff_email:
        return False

    base         = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    detail_url   = f"{base}/bookings/{booking['id']}"
    act          = booking["act_name"]
    event_date   = booking["event_date"]
    contact      = booking["contact_name"] or booking["contact_email"] or "unknown"
    reason_line  = reason or "No reason given"

    subject = f"Booking cancelled by band: {act} ({event_date})"

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
          <td style="background:#dc2626;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">Booking Cancelled by Band</h2>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <table width="100%" cellpadding="4" cellspacing="0"
                   style="font-size:14px;color:#333;margin-bottom:20px;">
              <tr><td style="color:#6b7280;width:120px;">Act</td><td><strong>{act}</strong></td></tr>
              <tr><td style="color:#6b7280;">Date</td><td><strong>{event_date}</strong></td></tr>
              <tr><td style="color:#6b7280;">Venue</td><td>{booking['venue']}</td></tr>
              <tr><td style="color:#6b7280;">Contact</td><td>{contact}</td></tr>
              <tr><td style="color:#6b7280;">Email</td><td>{booking['contact_email'] or '—'}</td></tr>
              <tr><td style="color:#6b7280;">Reason</td><td><em>{reason_line}</em></td></tr>
            </table>
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="background:#1c1c2e;border-radius:6px;">
                  <a href="{detail_url}"
                     style="display:block;padding:12px 24px;color:#fff;
                            text-decoration:none;font-weight:bold;font-size:14px;">
                    View booking →
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    plain = f"""BOOKING CANCELLED BY BAND

Act:     {act}
Date:    {event_date}
Venue:   {booking['venue']}
Contact: {contact}
Email:   {booking['contact_email'] or '—'}
Reason:  {reason_line}

View booking: {detail_url}
"""

    return _send(staff_email, subject, html, plain)


def send_band_cancellation_confirmation(booking, base_url=None):
    """Send a cancellation confirmation to the band after they cancel via the portal."""
    if not booking["contact_email"]:
        return False

    name  = booking["contact_name"] or "there"
    act   = booking["act_name"]
    date_ = booking["event_date"]

    subject = f"Booking cancelled: {act} at Cobblestone Pub ({date_})"

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
          <td style="background:#1c1c2e;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">🍺 Cobblestone Pub</h2>
            <p style="margin:4px 0 0;color:#aaa;font-size:13px;">Booking update</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;font-size:16px;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              We've received your cancellation request for <strong>{act}</strong>
              on <strong>{date_}</strong>. Your booking has been cancelled.
            </p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              If you cancelled by mistake or would like to rebook, please get in
              touch and we'll do our best to accommodate you.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              Thanks,<br>
              <strong>The Cobblestone Pub team</strong>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f8f8;padding:16px 32px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;·&nbsp;
            <a href="https://cobblestonepub.ie" style="color:#999;">cobblestonepub.ie</a>
            &nbsp;·&nbsp;
            <a href="mailto:bookings@cobblestonepub.ie" style="color:#999;">
              bookings@cobblestonepub.ie
            </a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    plain = f"""Hi {name},

We've received your cancellation request for {act} on {date_}.
Your booking has been cancelled.

If you cancelled by mistake or would like to rebook, please get in touch.

Thanks,
The Cobblestone Pub team

--
77 King St N, Smithfield, Dublin 7
bookings@cobblestonepub.ie
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, plain)


def send_portal_intro(booking, base_url=None):
    """Send a short 'here's your portal link' email to a band.

    Used when introducing the booking portal to bands that were already
    confirmed before the portal existed (e.g. imported from spreadsheet).
    Deliberately short — not a full confirmation re-send.

    Returns True on success, False on failure.
    """
    if not booking["contact_email"]:
        return False

    base       = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    portal_url = f"{base}/book/{booking['public_token']}"
    act        = booking["act_name"]
    name       = booking["contact_name"] or "there"
    venue      = booking["venue"]

    try:
        from datetime import datetime as _dt
        d = _dt.strptime(booking["event_date"], "%Y-%m-%d")
        date_str = d.strftime("%A, %-d %B %Y")
    except Exception:
        date_str = booking["event_date"]

    subject = f"Cobblestone Pub — your booking portal: {act}, {date_str}"

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
          <td style="background:#1c1c2e;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">&#127866; Cobblestone Pub</h2>
            <p  style="margin:4px 0 0;color:#aaa;font-size:13px;">
              Backroom &amp; Upstairs Bookings
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;font-size:16px;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              We've set up a new booking portal where you can view your upcoming booking
              for <strong>{act}</strong> at the Cobblestone Pub ({venue}) on
              <strong>{date_str}</strong>.
            </p>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#333;">
              Through your portal you can check your booking status, upload a poster or
              artist bio, and see any updates from us. Bookmark the link below — it's yours:
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 auto 24px;">
              <tr>
                <td style="background:#16a34a;border-radius:6px;">
                  <a href="{portal_url}"
                     style="display:block;padding:14px 28px;color:#fff;
                            text-decoration:none;font-weight:bold;font-size:15px;">
                    View your booking &#8594;
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 20px;font-size:13px;color:#777;text-align:center;">
              <a href="{portal_url}" style="color:#2563eb;">{portal_url}</a>
            </p>
            <p style="margin:0 0 8px;font-size:14px;color:#555;">
              If you have any questions just reply to this email or contact us at
              <a href="tel:+353894770682" style="color:#555;">+353 89 477 06 82</a>.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              Looking forward to seeing you!<br>
              <strong>The Cobblestone staff</strong>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f8f8;padding:16px 32px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;&middot;&nbsp;
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

We've set up a new booking portal for your upcoming booking at the Cobblestone Pub.

Act:   {act}
Date:  {date_str}
Venue: {venue}, Cobblestone Pub

View your booking, check your status, and upload a poster or bio here:
{portal_url}

Bookmark this link — it's yours to keep.

Any questions? Just reply to this email or call us on +353 89 477 06 82.

Looking forward to seeing you!
The Cobblestone Pub team

--
77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, text)


def send_date_taken_decline(booking, base_url=None):
    """Notify a band that their requested date has been taken by another booking.

    Sent automatically when a competing booking is confirmed for the same
    date and venue.  Includes a one-click 'Pick a new date' rebook link so
    the band can choose a different date without re-filling the whole form.

    Returns True on success, False on failure.
    """
    if not booking["contact_email"]:
        return False

    base       = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    rebook_url = f"{base}/book/{booking['public_token']}/rebook"
    act        = booking["act_name"]
    name       = booking["contact_name"] or "there"
    venue      = booking["venue"]

    try:
        from datetime import datetime as _dt
        d = _dt.strptime(booking["event_date"], "%Y-%m-%d")
        date_str = d.strftime("%A, %-d %B %Y")
    except Exception:
        date_str = booking["event_date"]

    subject = f"Re: your inquiry for {date_str} — date now taken"

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
          <td style="background:#1c1c2e;padding:28px 32px;">
            <h2 style="margin:0;color:#fff;font-size:22px;">&#127866; Cobblestone Pub</h2>
            <p style="margin:4px 0 0;color:#aaa;font-size:13px;">
              Backroom &amp; Upstairs Bookings
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;font-size:16px;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#333;">
              Thanks for your interest in playing the Cobblestone Pub.
              Unfortunately <strong>{date_str}</strong> at the <strong>{venue}</strong>
              has just been confirmed for another event, so we're unable to accommodate
              <strong>{act}</strong> on that date.
            </p>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#333;">
              We'd love to have you here — use the button below to check availability
              and pick a new date. Your details are already saved, so you won't need
              to fill in the form again.
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 auto 24px;">
              <tr>
                <td style="background:#2563eb;border-radius:6px;">
                  <a href="{rebook_url}"
                     style="display:block;padding:14px 28px;color:#fff;
                            text-decoration:none;font-weight:bold;font-size:15px;">
                    Pick a new date &#8594;
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 20px;font-size:13px;color:#777;text-align:center;">
              <a href="{rebook_url}" style="color:#2563eb;">{rebook_url}</a>
            </p>
            <p style="margin:0 0 8px;font-size:14px;color:#555;">
              If you have any questions, just reply to this email or call us on
              <a href="tel:+353894770682" style="color:#555;">+353 89 477 06 82</a>.
            </p>
            <p style="margin:24px 0 0;font-size:15px;color:#333;">
              Hope to see you at the Cobblestone soon,<br>
              <strong>The Cobblestone staff</strong>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f8f8;padding:16px 32px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;&middot;&nbsp;
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

Thanks for your interest in playing the Cobblestone Pub. Unfortunately
{date_str} at the {venue} has just been confirmed for another event,
so we can't accommodate {act} on that date.

We'd love to have you here — pick a new date using the link below.
Your details are already saved so you won't need to fill in the form again:

{rebook_url}

Any questions? Just reply to this email or call us on +353 89 477 06 82.

Hope to see you at the Cobblestone soon,
The Cobblestone staff

--
77 King St N, Smithfield, Dublin 7
https://cobblestonepub.ie
"""

    return _send(booking["contact_email"], subject, html, text)


# ---------------------------------------------------------------------------
# Shane Hannigan — sound engineer notification
# ---------------------------------------------------------------------------

SHANE_EMAIL = "onsoundie@gmail.com"
SHANE_NAME  = "Shane Hannigan"


def send_shane_notification(booking, base_url=None, sender_name=None):
    """Email Shane Hannigan a booking briefing sheet.

    Sends all logistical details he needs: act, date, times, door person,
    contact info, and notes.  Called manually via the 'Notify Shane' button
    on the booking detail page.

    Returns True on success, False on failure.
    """
    base   = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    act    = booking["act_name"]
    venue  = booking["venue"]

    try:
        from datetime import datetime as _dt
        d = _dt.strptime(booking["event_date"], "%Y-%m-%d")
        date_str = d.strftime("%A, %-d %B %Y")
    except Exception:
        date_str = booking["event_date"]

    door_time  = booking["door_time"]  or "TBC"
    start_time = booking["start_time"] or "TBC"
    end_time   = booking["end_time"]   or "TBC"

    dp = booking["door_person"]
    if dp == "pub":
        door_line = "Pub providing door person (€50 — band pays on night)"
    elif dp == "own":
        door_line = "Band providing their own door person"
    elif dp == "none":
        door_line = "No door person required"
    else:
        door_line = "TBC"

    subject = f"Cobblestone gig — {act}, {date_str}"

    def _row(label, value, bg="#fff"):
        return (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:8px 12px;color:#6b7280;font-size:13px;width:130px;"
            f"border-bottom:1px solid #f3f4f6;'>{label}</td>"
            f"<td style='padding:8px 12px;font-size:13px;font-weight:600;"
            f"border-bottom:1px solid #f3f4f6;'>{value}</td>"
            f"</tr>"
        )

    notes_block = (
        f"<p style='margin:0 0 16px;font-size:13px;background:#fffbeb;"
        f"border-left:3px solid #f59e0b;padding:12px;border-radius:4px;'>"
        f"<strong>Notes:</strong> {booking['notes']}</p>"
        if booking.get("notes") else ""
    )
    desc_block = (
        f"<p style='margin:0 0 16px;font-size:13px;background:#f0f9ff;"
        f"border-left:3px solid #38bdf8;padding:12px;border-radius:4px;'>"
        f"<strong>Description:</strong> {booking['description']}</p>"
        if booking.get("description") else ""
    )

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <tr>
          <td style="background:#1c1c2e;padding:24px 28px;">
            <h2 style="margin:0;color:#fff;font-size:20px;">&#127866; Cobblestone Pub — Gig Briefing</h2>
          </td>
        </tr>
        <tr>
          <td style="padding:28px;">
            <p style="margin:0 0 20px;font-size:15px;color:#333;">Hi {SHANE_NAME},</p>
            <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#333;">
              Here are the details for an upcoming booking.
              Please get in touch with the act directly to arrange load-in,
              sound check, and any technical requirements.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e5e7eb;border-radius:6px;
                          border-collapse:collapse;margin-bottom:20px;">
              {_row("Act",          act,                     "#f9fafb")}
              {_row("Date",         date_str                          )}
              {_row("Venue",        venue + " — Cobblestone", "#f9fafb")}
              {_row("Doors open",   door_time                         )}
              {_row("Show starts",  start_time,              "#f9fafb")}
              {_row("End time",     end_time                          )}
              {_row("Door person",  door_line,               "#f9fafb")}
              {_row("Contact",      booking['contact_name']  or "—"  )}
              {_row("Email",        booking['contact_email'] or "—",  "#f9fafb")}
              {_row("Phone",        booking['contact_phone'] or "—"  )}
            </table>
            {notes_block}{desc_block}
            <p style="margin:16px 0 0;font-size:13px;color:#777;">
              Questions? Reply here or email
              <a href="mailto:bookings@cobblestonepub.ie" style="color:#2563eb;">
                bookings@cobblestonepub.ie
              </a>.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f8f8;padding:14px 28px;
                     border-top:1px solid #eee;font-size:12px;color:#999;">
            77 King St N, Smithfield, Dublin 7 &nbsp;&middot;&nbsp;
            <a href="https://cobblestonepub.ie" style="color:#999;">cobblestonepub.ie</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    text = f"""Hi {SHANE_NAME},

Here are the details for an upcoming Cobblestone booking.
Please contact the act directly to arrange load-in and sound check.

Act:          {act}
Date:         {date_str}
Venue:        {venue} — Cobblestone Pub
Doors open:   {door_time}
Show starts:  {start_time}
End time:     {end_time}
Door person:  {door_line}

Contact:      {booking['contact_name']  or '—'}
Email:        {booking['contact_email'] or '—'}
Phone:        {booking['contact_phone'] or '—'}
{"Notes:        " + booking['notes'] if booking.get('notes') else ""}

Questions? Reply here or email bookings@cobblestonepub.ie.

--
Cobblestone Pub · 77 King St N, Smithfield, Dublin 7
"""

    return _send(SHANE_EMAIL, subject, html, text)


# ---------------------------------------------------------------------------
# Staff alert — door person unconfirmed within 7 days
# ---------------------------------------------------------------------------

def send_door_person_alert(bookings, base_url=None):
    """Send a digest email to staff listing confirmed bookings within the next
    7 days where the door person arrangement has not yet been set.

    Returns True if the email was sent, False otherwise.
    """
    if not bookings:
        return False

    base    = (base_url or config.PUBLIC_BASE_URL).rstrip("/")
    to_addr = config.BOOKING_REPLY_TO or config.SMTP_USERNAME
    count   = len(bookings)
    subject = (
        f"⚠️ Action needed: door person unconfirmed for {count} "
        f"upcoming gig{'s' if count != 1 else ''}"
    )

    rows_html = ""
    for b in bookings:
        detail_url = f"{base}/bookings/{b['id']}"
        rows_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">
            <a href="{detail_url}" style="color:#2563eb;text-decoration:none;font-weight:600;">
              {b['event_date']}
            </a>
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{b['act_name']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{b['venue']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{b['start_time'] or 'TBC'}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">
            <a href="{detail_url}" style="color:#2563eb;">Set now →</a>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;font-size:15px;color:#1f2937;margin:0;padding:0;">
<div style="max-width:640px;margin:32px auto;padding:0 16px;">

  <div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:16px 20px;
              border-radius:4px;margin-bottom:24px;">
    <p style="margin:0;font-weight:700;font-size:16px;">⚠️ Door person not yet confirmed</p>
    <p style="margin:8px 0 0;">
      The following {count} confirmed gig{'s are' if count != 1 else ' is'} within the next
      7 days but the door person arrangement has <strong>not been set</strong>.
      Decide whether the pub will provide a door person, the band will,
      or none is needed — then update the booking so the roster can be finalised.
    </p>
  </div>

  <table style="width:100%;border-collapse:collapse;font-size:14px;">
    <thead>
      <tr style="background:#f3f4f6;">
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;
                   color:#6b7280;">Date</th>
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;
                   color:#6b7280;">Act</th>
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;
                   color:#6b7280;">Venue</th>
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;
                   color:#6b7280;">Show</th>
        <th style="padding:8px 12px;"></th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>

  <p style="margin-top:24px;">
    <a href="{base}/bookings?view=upcoming&amp;status=confirmed"
       style="background:#2563eb;color:#fff;padding:10px 20px;border-radius:6px;
              text-decoration:none;font-weight:600;font-size:14px;">
      Open booking tracker →
    </a>
  </p>

  <p style="margin-top:32px;font-size:12px;color:#9ca3af;">
    This is an automated daily reminder from the Cobblestone booking system.
    Once the door person field is filled in on a booking, it will stop appearing here.
  </p>
</div>
</body>
</html>"""

    lines = []
    for b in bookings:
        lines.append(
            f"  {b['event_date']}  {b['act_name']}  ({b['venue']})  "
            f"— {base}/bookings/{b['id']}"
        )

    text = (
        "ACTION NEEDED — Door person unconfirmed\n\n"
        "The following confirmed gigs are within 7 days and the door person\n"
        "arrangement has not been set. Please update each booking now.\n\n"
        + "\n".join(lines)
        + f"\n\nOpen tracker: {base}/bookings?view=upcoming&status=confirmed\n\n"
        "--\nCobblestone Pub booking system · automated daily reminder\n"
    )

    return _send(to_addr, subject, html, text)

