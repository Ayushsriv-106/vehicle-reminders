"""Daily reminder script — sends one email summarising everything due soon.

Triggered by GitHub Actions cron. Reads SMTP creds from environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO, EMAIL_FROM
"""
from __future__ import annotations

import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core import Item, build_items, items_needing_email, load_config


URGENCY_META = {
    "overdue":  {"emoji": "🚨", "label": "OVERDUE",  "color": "#c1121f"},
    "critical": {"emoji": "🔴", "label": "URGENT",   "color": "#e85d04"},
    "warning":  {"emoji": "🟡", "label": "Upcoming", "color": "#d4a017"},
}


def _fmt_days(days: int) -> str:
    if days < 0:
        return f"{abs(days)} day{'s' if abs(days) != 1 else ''} overdue"
    if days == 0:
        return "expires TODAY"
    return f"in {days} day{'s' if days != 1 else ''}"


def render_email_html(items: list[Item]) -> str:
    today = date.today().strftime("%A, %d %B %Y")

    # Group by urgency
    groups: dict[str, list[Item]] = {"overdue": [], "critical": [], "warning": []}
    for i in items:
        if i.urgency in groups:
            groups[i.urgency].append(i)

    sections_html = []
    for key in ("overdue", "critical", "warning"):
        group_items = groups[key]
        if not group_items:
            continue
        meta = URGENCY_META[key]
        rows = []
        for i in group_items:
            amount = f"₹{i.amount:,.0f}" if i.amount else "—"
            link = (
                f'<a href="{i.file_link}" style="color:#0066cc;text-decoration:none;">📄 View</a>'
                if i.file_link else "—"
            )
            rows.append(f"""
              <tr style="border-bottom:1px solid #eee;">
                <td style="padding:10px 8px;font-weight:600;">{i.vehicle_name}</td>
                <td style="padding:10px 8px;">{i.type}</td>
                <td style="padding:10px 8px;color:{meta['color']};font-weight:600;">
                  {i.expiry_date.strftime('%d %b %Y')}<br>
                  <span style="font-size:12px;font-weight:400;">{_fmt_days(i.days_left)}</span>
                </td>
                <td style="padding:10px 8px;">{amount}</td>
                <td style="padding:10px 8px;">{link}</td>
              </tr>
            """)
        sections_html.append(f"""
          <h2 style="color:{meta['color']};margin:24px 0 8px;font-size:18px;">
            {meta['emoji']} {meta['label']} ({len(group_items)})
          </h2>
          <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <thead>
              <tr style="background:#f7f7f7;text-align:left;">
                <th style="padding:10px 8px;">Vehicle</th>
                <th style="padding:10px 8px;">Document</th>
                <th style="padding:10px 8px;">Expires</th>
                <th style="padding:10px 8px;">Amount</th>
                <th style="padding:10px 8px;">File</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        """)

    dashboard_url = os.environ.get("DASHBOARD_URL", "")
    dashboard_link = (
        f'<p style="margin-top:24px;"><a href="{dashboard_url}" '
        f'style="background:#111;color:#fff;padding:10px 18px;border-radius:6px;'
        f'text-decoration:none;display:inline-block;">Open full dashboard →</a></p>'
        if dashboard_url else ""
    )

    return f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:720px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h1 style="font-size:22px;margin:0 0 4px;">Vehicle Reminders</h1>
  <p style="color:#666;margin:0 0 16px;font-size:14px;">{today}</p>
  <p style="font-size:15px;">You have <b>{len(items)}</b> item(s) that need attention.</p>
  {''.join(sections_html)}
  {dashboard_link}
  <hr style="margin:32px 0;border:none;border-top:1px solid #eee;">
  <p style="color:#999;font-size:12px;">Automated by your vehicle-reminders repo. Edit data/vehicles.yaml to update.</p>
</body></html>"""


def render_email_text(items: list[Item]) -> str:
    today = date.today().strftime("%A, %d %B %Y")
    lines = [f"Vehicle Reminders — {today}", "=" * 50, ""]
    for i in items:
        meta = URGENCY_META.get(i.urgency, {"emoji": "•", "label": ""})
        lines.append(f"{meta['emoji']} [{meta['label']}] {i.vehicle_name} — {i.type}")
        lines.append(f"   Expires: {i.expiry_date} ({_fmt_days(i.days_left)})")
        if i.amount:
            lines.append(f"   Amount: ₹{i.amount:,.0f}")
        if i.file_link:
            lines.append(f"   File: {i.file_link}")
        lines.append("")
    return "\n".join(lines)


def send_email(subject: str, html_body: str, text_body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ.get("EMAIL_FROM", user)
    email_to = os.environ["EMAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(email_from, [a.strip() for a in email_to.split(",")], msg.as_string())


def main() -> int:
    config = load_config()
    settings = config.get("settings", {})
    reminder_days = settings.get("reminder_days", [30, 15, 7, 3, 1, 0])

    items = build_items(config)
    due = items_needing_email(items, reminder_days)

    if not due:
        print("✅ Nothing to remind about today. Skipping email.")
        return 0

    counts = {k: sum(1 for i in due if i.urgency == k) for k in ("overdue", "critical", "warning")}
    parts = []
    if counts["overdue"]:
        parts.append(f"{counts['overdue']} overdue")
    if counts["critical"]:
        parts.append(f"{counts['critical']} urgent")
    if counts["warning"]:
        parts.append(f"{counts['warning']} upcoming")
    subject = "🚗 Vehicle reminder: " + ", ".join(parts)

    html_body = render_email_html(due)
    text_body = render_email_text(due)

    try:
        send_email(subject, html_body, text_body)
        print(f"✅ Email sent with {len(due)} items.")
        return 0
    except Exception as e:
        print(f"❌ Failed to send email: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
