"""Daily hands-free WhatsApp reminder.

Builds the exact message that should go to the "Car papers" WhatsApp group and
emails it to YOU, ready to post: a clean email with the message + a one-tap
"Share to WhatsApp" button (WhatsApp can't auto-post into a group, so the only
manual step is the single Send tap). Runs from GitHub Actions on the daily cron.

Quiet by design — it does NOT email every day:
  * It fires when a paper crosses a reminder threshold today (the quiet ramp in
    items_needing_email), OR
  * once a week (Monday) if any vehicle is still missing legally-required papers,
    so chronic gaps aren't forgotten without becoming daily spam.
The full live picture always lives on the dashboard.

SMTP creds + recipient come from environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM
  WA_REMINDER_TO  (who gets the ready-to-post email; defaults to the owner)
"""
from __future__ import annotations

import os
import smtplib
import sys
import urllib.parse
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core import (
    build_items,
    compose_whatsapp_reminder,
    items_needing_email,
    load_config,
    vehicle_missing_map,
)

DEFAULT_DASHBOARD_URL = "https://garage-fleet.pages.dev/"
# Send the ready-to-post email here. Single recipient on purpose — the old
# multi-recipient list bounced (a full inbox), which is why email was paused.
DEFAULT_REMINDER_TO = "ayushsrivastava9997@gmail.com"
WEEKLY_NUDGE_WEEKDAY = 0  # Monday — weekly heartbeat for chronic missing papers


def render_email_html(message: str, wa_url: str, dashboard_url: str) -> str:
    safe = (message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return f"""<!DOCTYPE html>
<html><body style="margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#101828;">
  <div style="max-width:560px;margin:0 auto;padding:24px;">
    <h1 style="font-size:19px;margin:0 0 4px;">Fleet papers — ready to post</h1>
    <p style="color:#667085;margin:0 0 18px;font-size:13px;">{date.today().strftime('%A, %d %B %Y')} · tap the button, pick the <b>Car papers</b> group, Send.</p>

    <a href="{wa_url}" style="display:inline-block;background:#1ea463;color:#fff;padding:12px 22px;border-radius:9px;text-decoration:none;font-weight:600;font-size:15px;">Share to WhatsApp →</a>

    <p style="color:#667085;font-size:12px;margin:14px 0 6px;">Message preview (already prepared):</p>
    <pre style="background:#fff;border:1px solid #e4e7ec;border-radius:9px;padding:14px 16px;font-size:13px;line-height:1.55;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,'SF Mono',Menlo,monospace;color:#344054;">{safe}</pre>

    <p style="margin-top:18px;"><a href="{dashboard_url}" style="color:#3538cd;font-size:13px;">Open the full dashboard →</a></p>
    <hr style="margin:26px 0;border:none;border-top:1px solid #e4e7ec;">
    <p style="color:#98a2b3;font-size:11px;">You only get this when something needs action (a renewal due, a lapse, or a weekly missing-papers nudge). Everything is always live on the dashboard.</p>
  </div>
</body></html>"""


def send_email(subject: str, html_body: str, text_body: str, to_addr: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ.get("EMAIL_FROM", user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = to_addr
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(email_from, [to_addr], msg.as_string())


def main() -> int:
    config = load_config()
    settings = config.get("settings", {})
    reminder_days = settings.get("reminder_days", [14, 7, 3, 1, 0])
    overdue_reminder_days = settings.get("overdue_reminder_days", [1, 3, 7, 14, 30])
    monthly_after_days = settings.get("overdue_monthly_after_days", 30)

    items = build_items(config)

    # Time-sensitive nudges hitting a threshold today.
    due = items_needing_email(items, reminder_days, overdue_reminder_days, monthly_after_days)
    # Weekly heartbeat for chronic missing papers (Mondays only).
    missing = vehicle_missing_map(config, items)
    weekly_nudge = (date.today().weekday() == WEEKLY_NUDGE_WEEKDAY) and bool(missing)

    if not due and not weekly_nudge:
        print("Nothing to nudge about today. Staying quiet.")
        return 0

    dashboard_url = os.environ.get("DASHBOARD_URL", "").strip() or DEFAULT_DASHBOARD_URL
    message = compose_whatsapp_reminder(config, items, dashboard_url=dashboard_url)
    if not message:
        print("Nothing to report. Staying quiet.")
        return 0

    wa_url = "https://wa.me/?text=" + urllib.parse.quote(message)

    counts = {
        "overdue": sum(1 for i in items if i.days_left < 0),
        "soon": sum(1 for i in items if 0 <= i.days_left <= 30),
    }
    parts = []
    if counts["overdue"]:
        parts.append(f"{counts['overdue']} overdue")
    if counts["soon"]:
        parts.append(f"{counts['soon']} due soon")
    if missing:
        parts.append(f"{len(missing)} missing papers")
    subject = "🚗 Car papers reminder — " + (", ".join(parts) if parts else "review") + " (tap to post)"

    to_addr = os.environ.get("WA_REMINDER_TO", "").strip() or DEFAULT_REMINDER_TO
    html_body = render_email_html(message, wa_url, dashboard_url)

    try:
        send_email(subject, html_body, message, to_addr)
        print(f"Sent ready-to-post WhatsApp reminder to {to_addr}.")
        return 0
    except Exception as e:
        print(f"Failed to send reminder email: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
