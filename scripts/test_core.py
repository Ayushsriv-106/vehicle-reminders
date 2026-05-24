"""Tests for the reminder-selection logic — locks in the "no daily spam" rule.

Run from the repo root:  python scripts/test_core.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from core import build_items, classify_urgency, items_needing_email

REMINDER_DAYS = [14, 7, 3, 1, 0]
OVERDUE_DAYS = [1, 3, 7, 14, 30]


def _doc(days_from_today: int) -> dict:
    """A config with one vehicle + one PUC doc expiring `days_from_today` away."""
    expiry = date.today() + timedelta(days=days_from_today)
    return {
        "settings": {},
        "vehicles": [{
            "id": "v1", "name": "Test Car", "registration_number": "UP00X0000",
            "documents": [{"type": "PUC", "expiry_date": expiry.isoformat()}],
            "services": [],
        }],
        "personal": [],
    }


def _emails_on(days_from_today: int) -> bool:
    items = build_items(_doc(days_from_today))
    due = items_needing_email(items, REMINDER_DAYS, OVERDUE_DAYS)
    return len(due) == 1


def run() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool) -> None:
        if not cond:
            failures.append(label)

    # --- The actual spam complaint: long-overdue items must go SILENT --- #
    check("1227d-overdue PUC must NOT email (was daily spam)", not _emails_on(-1227))
    check("265d-overdue insurance must NOT email (was daily spam)", not _emails_on(-265))
    check("31d overdue (just past grace) must NOT email", not _emails_on(-31))

    # --- Capped post-expiry nudges DO fire on their exact days --- #
    for d in OVERDUE_DAYS:
        check(f"{d}d overdue should email", _emails_on(-d))

    # --- The "week or two" warning ramp before expiry --- #
    for d in REMINDER_DAYS:
        check(f"{d}d before expiry should email", _emails_on(d))
    check("expiry day (0) should email", _emails_on(0))

    # --- Quiet days in between must NOT email (no daily spam) --- #
    check("60d out must NOT email (too early now)", not _emails_on(60))
    check("21d out must NOT email (between ramp steps)", not _emails_on(21))
    check("10d out must NOT email (between 14 and 7)", not _emails_on(10))
    check("5d out must NOT email (between 7 and 3)", not _emails_on(5))
    check("20d overdue must NOT email (between 14 and 30)", not _emails_on(-20))

    # --- urgency classification sanity --- #
    check("negative days = overdue", classify_urgency(-1) == "overdue")
    check("<=7 days = critical", classify_urgency(5) == "critical")
    check("<=30 days = warning", classify_urgency(20) == "warning")

    if failures:
        print(f"FAIL: {len(failures)} test(s) failed:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("PASS: All reminder-selection tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
