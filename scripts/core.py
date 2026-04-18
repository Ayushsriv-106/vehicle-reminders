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
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value), "%Y-%m-%d").date()


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
            expiry = _parse_date(doc["expiry_date"])
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
            item = _make_service_item(vehicle, service, today)
            if item:
                items.append(item)

    for personal in config.get("personal", []):
        expiry = _parse_date(personal["expiry_date"])
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


def items_needing_email(items: list[Item], reminder_days: list[int]) -> list[Item]:
    """Filter to items whose days_left is in the reminder list, or overdue."""
    thresholds = set(reminder_days)
    return [
        i for i in items
        if i.days_left in thresholds or i.days_left < 0
    ]
