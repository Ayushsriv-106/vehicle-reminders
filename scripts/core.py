"""Core logic shared between reminder script and dashboard builder."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from dateutil.relativedelta import relativedelta


# ---------- Data model ---------------------------------------------------- #

@dataclass
class Item:
    """A single thing that expires — document OR service (next-due date)."""
    vehicle_id: str
    vehicle_name: str
    category: str            # "document" | "service" | "personal"
    type: str                # "Insurance", "PUC", "General Service", ...
    expiry_date: date
    days_left: int
    urgency: str             # "overdue" | "critical" | "warning" | "ok" | "far"
    provider: str = ""
    amount: float | None = None
    file_link: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_due_for_reminder(self) -> bool:
        """True if today's days_left matches any reminder threshold (or overdue)."""
        return self.urgency in ("overdue", "critical", "warning")


# ---------- Loading & computation ----------------------------------------- #

def load_config(path: str | Path = "data/vehicles.yaml") -> dict:
    """Load config from Google Sheet (if SHEET_CSV_URL env var is set) or YAML file."""
    import os
    sheet_url = os.environ.get("SHEET_CSV_URL", "").strip()
    if sheet_url:
        # Import here so yaml-only installs don't fail if sheet_loader has issues
        from sheet_loader import load_config_from_sheet
        return load_config_from_sheet(sheet_url)

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_date(value: Any) -> date:
    """Parse a date from various formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, etc."""
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()

    s = str(value).strip()
    if not s:
        raise ValueError("Empty date value")

    # Try multiple common date formats
    formats = [
        "%Y-%m-%d",      # 2025-04-14 (ISO)
        "%d/%m/%Y",      # 14/04/2025 (Indian/UK)
        "%d-%m-%Y",      # 14-04-2025
        "%m/%d/%Y",      # 04/14/2025 (US)
        "%d/%m/%y",      # 14/04/25
        "%d-%b-%Y",      # 14-Apr-2025
        "%d %b %Y",      # 14 Apr 2025
        "%d-%B-%Y",      # 14-April-2025
        "%Y/%m/%d",      # 2025/04/14
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date: '{s}'. Expected YYYY-MM-DD or DD/MM/YYYY.")


def classify_urgency(days_left: int) -> str:
    if days_left < 0:
        return "overdue"
    if days_left <= 7:
        return "critical"
    if days_left <= 30:
        return "warning"
    if days_left <= 90:
        return "ok"
    return "far"


# ---------- Compliance: which papers each vehicle type legally needs -------- #

# Indian RTO requirements (document-wise). Private cars need valid insurance,
# PUC and RC; commercial/transport vehicles additionally need an annual fitness
# certificate, a permit and road tax.
REQUIRED_DOCS: dict[str, list[str]] = {
    "Car": ["Insurance", "PUC", "Registration (RC)"],
    "Commercial Vehicle": [
        "Insurance", "PUC", "Fitness", "Permit", "Registration (RC)", "Road Tax",
    ],
}
DEFAULT_REQUIRED = ["Insurance", "PUC", "Registration (RC)"]


def required_docs_for(vehicle_type: str) -> list[str]:
    return REQUIRED_DOCS.get((vehicle_type or "").strip(), DEFAULT_REQUIRED)


def missing_required(present_types: set[str], vehicle_type: str) -> list[str]:
    """Required documents that aren't present for this vehicle, in canonical order."""
    return [d for d in required_docs_for(vehicle_type) if d not in present_types]


def owner_group(owner: str) -> str:
    """Bucket a free-text owner string into one of the three real fleets."""
    o = (owner or "").lower()
    if any(k in o for k in ("gopal", "memorial", "g.m.s", "gms", "school")):
        return "GJMS School"
    if any(k in o for k in ("g.b", "gb auto", "automobile")):
        return "G.B. Automobiles"
    return "Family & Personal"


def _make_service_item(vehicle: dict, service: dict, today: date) -> Item | None:
    """Compute next-due date for a service from last_done + interval_months."""
    last_done = service.get("last_done")
    interval = service.get("interval_months")
    if not last_done or not interval:
        return None
    next_due = _parse_date(last_done) + relativedelta(months=int(interval))
    days_left = (next_due - today).days
    return Item(
        vehicle_id=vehicle["id"],
        vehicle_name=vehicle["name"],
        category="service",
        type=service["type"],
        expiry_date=next_due,
        days_left=days_left,
        urgency=classify_urgency(days_left),
        amount=service.get("cost"),
        extra={
            "last_done": str(last_done),
            "interval_months": interval,
            "odometer_km": service.get("odometer_km"),
            "workshop": service.get("workshop", ""),
        },
    )


def build_items(config: dict, today: date | None = None) -> list[Item]:
    today = today or date.today()
    items: list[Item] = []

    for vehicle in config.get("vehicles", []):
        for doc in vehicle.get("documents", []):
            try:
                expiry = _parse_date(doc["expiry_date"])
            except ValueError as e:
                # Skip docs with bad dates rather than failing entire run
                print(f"⚠️  Skipping {vehicle.get('name', '?')} {doc.get('type', '?')}: {e}")
                continue
            days_left = (expiry - today).days
            items.append(Item(
                vehicle_id=vehicle["id"],
                vehicle_name=vehicle["name"],
                category="document",
                type=doc["type"],
                expiry_date=expiry,
                days_left=days_left,
                urgency=classify_urgency(days_left),
                provider=doc.get("provider", ""),
                amount=doc.get("amount"),
                file_link=doc.get("file_link", "") or "",
                extra={"policy_number": doc.get("policy_number", "")},
            ))

        for service in vehicle.get("services", []):
            try:
                item = _make_service_item(vehicle, service, today)
                if item:
                    items.append(item)
            except ValueError as e:
                print(f"⚠️  Skipping service for {vehicle.get('name', '?')}: {e}")
                continue

    for personal in config.get("personal", []):
        try:
            expiry = _parse_date(personal["expiry_date"])
        except ValueError as e:
            print(f"⚠️  Skipping personal {personal.get('type', '?')}: {e}")
            continue
        days_left = (expiry - today).days
        items.append(Item(
            vehicle_id="personal",
            vehicle_name=personal.get("owner", "Personal"),
            category="personal",
            type=personal["type"],
            expiry_date=expiry,
            days_left=days_left,
            urgency=classify_urgency(days_left),
            file_link=personal.get("file_link", "") or "",
            extra={"number": personal.get("number", "")},
        ))

    items.sort(key=lambda i: i.days_left)
    return items


def vehicle_missing_map(config: dict, items: list[Item]) -> list[dict]:
    """Per-vehicle list of legally-required documents that are missing, plus the
    worst urgency present. Shared by the dashboard and the WhatsApp reminder so
    'missing papers' is computed exactly once."""
    out: list[dict] = []
    for v in config.get("vehicles", []):
        v_items = [i for i in items if i.vehicle_id == v["id"]]
        present = {i.type for i in v_items if i.category == "document"}
        missing = missing_required(present, v.get("type", ""))
        if missing:
            out.append({
                "name": v["name"],
                "reg": v.get("registration_number", ""),
                "group": owner_group(v.get("owner", "")),
                "missing": missing,
                "has_any": bool(present),
            })
    return out


def compose_whatsapp_reminder(
    config: dict,
    items: list[Item],
    today: date | None = None,
    dashboard_url: str = "https://garage-fleet.pages.dev/",
    max_missing_lines: int = 8,
) -> str:
    """Build the ready-to-post Hindi/Hinglish message for the 'Car papers'
    WhatsApp group. Auto-derives overdue papers, papers expiring within 30 days,
    and vehicles missing legally-required documents. Returns '' if there is
    genuinely nothing to act on (so the daily automation can stay silent)."""
    today = today or date.today()

    overdue = sorted(
        [i for i in items if i.days_left < 0],
        key=lambda i: i.days_left,
    )
    expiring = sorted(
        [i for i in items if 0 <= i.days_left <= 30],
        key=lambda i: i.days_left,
    )
    missing = vehicle_missing_map(config, items)

    if not (overdue or expiring or missing):
        return ""

    def _reg(i: Item) -> str:
        for v in config.get("vehicles", []):
            if v["id"] == i.vehicle_id:
                return v.get("registration_number", "")
        return ""

    def _days_hi(i: Item) -> str:
        if i.days_left < 0:
            return f"{abs(i.days_left)} din se overdue"
        if i.days_left == 0:
            return "aaj expire"
        if i.days_left == 1:
            return "kal expire"
        return f"{i.days_left} din me"

    L: list[str] = []
    L.append(f"\U0001f697 *Gaadi Kaagaz Reminder* — {today.strftime('%d %b %Y')}")
    L.append("")

    if overdue:
        L.append(f"\U0001f534 *OVERDUE — turant dekhein ({len(overdue)})*")
        for i in overdue:
            reg = _reg(i)
            tail = ""
            # Uninsured commercial vehicle is a real liability — call it out.
            if i.type == "Insurance" and i.category == "document":
                tail = "  ⚠️ bina beema chal rahi hai"
            L.append(f"• {i.vehicle_name}{f' ({reg})' if reg else ''} — {i.type}, {_days_hi(i)}{tail}")
        L.append("")

    if expiring:
        L.append(f"\U0001f7e0 *Jald expire ho rahe ({len(expiring)})*")
        for i in expiring:
            reg = _reg(i)
            L.append(f"• {i.vehicle_name}{f' ({reg})' if reg else ''} — {i.type}, {_days_hi(i)}")
        L.append("")

    if missing:
        total_missing = sum(len(m["missing"]) for m in missing)
        L.append(f"\U0001f4c4 *Kaagaz record me nahi hain ({total_missing} paper, {len(missing)} gaadi)*")
        # Most urgent first: vehicles with NO documents, then those missing Insurance.
        def _rank(m: dict) -> tuple:
            return (0 if not m["has_any"] else 1,
                    0 if "Insurance" in m["missing"] else 1)
        for m in sorted(missing, key=_rank)[:max_missing_lines]:
            reg = f" ({m['reg']})" if m["reg"] else ""
            what = "koi document nahi" if not m["has_any"] else ", ".join(m["missing"])
            L.append(f"• {m['name']}{reg} — {what}")
        extra = len(missing) - max_missing_lines
        if extra > 0:
            L.append(f"• …aur {extra} gaadi (poori list portal par)")
        L.append("")

    L.append(f"\U0001f517 Poora portal: {dashboard_url}")
    L.append("(Jis gaadi ke aap responsible hain, uske kaagaz upload kar dein.)")
    return "\n".join(L)


MONTHLY_PERIOD_DAYS = 30


def items_needing_email(
    items: list[Item],
    reminder_days: list[int],
    overdue_reminder_days: list[int] | None = None,
    monthly_after_days: int | None = None,
) -> list[Item]:
    """Pick the items worth emailing about today — deliberately quiet so the
    daily mail never feels like spam.

    An item is emailed only on a few discrete days:
      * ``reminder_days`` — exact days *before* expiry (e.g. 14, 7, 3, 1, 0).
      * ``overdue_reminder_days`` — exact days *after* expiry (e.g. 1, 3, 7,
        14, 30) — a ramp of nudges right after a lapse.
      * ``monthly_after_days`` — once an item is overdue by *more* than this,
        send a low-frequency "still overdue" heartbeat every 30 days
        (60, 90, 120 … days overdue). Set to ``None`` to disable, in which
        case chronically-overdue items go fully silent and live on only in
        the dashboard.

    The key difference from naive "email everything overdue, every day" logic:
    nothing is emailed daily. A heartbeat at most nudges monthly, so a long
    lapse is never forgotten without becoming spam.
    """
    pre = set(reminder_days)
    post = set(overdue_reminder_days or [])
    out: list[Item] = []
    for i in items:
        d = i.days_left
        if d >= 0:
            if d in pre:
                out.append(i)
            continue
        overdue = -d
        if overdue in post:
            out.append(i)
        elif (
            monthly_after_days is not None
            and overdue > monthly_after_days
            and overdue % MONTHLY_PERIOD_DAYS == 0
        ):
            out.append(i)
    return out
