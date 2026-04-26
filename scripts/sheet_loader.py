"""Fetches a published Google Sheet as CSV and converts to the config format
that core.py expects.

The sheet MUST have these columns in any order (header row on row 1):
  - vehicle_id              (required, unique)
  - vehicle_name            (required, e.g. "Swift VXI")
  - registration_number     (required)
  - vehicle_type            (Car / Scooter / Truck / ...)
  - owner                   (optional)
  - notes                   (optional)
  - insurance_expiry        (YYYY-MM-DD)
  - insurance_provider      (optional)
  - insurance_amount        (optional, number)
  - insurance_file          (optional, URL)
  - puc_expiry              (YYYY-MM-DD)
  - puc_amount              (optional)
  - puc_file                (optional)
  - rc_expiry               (YYYY-MM-DD)
  - rc_file                 (optional)
  - fitness_expiry          (optional, YYYY-MM-DD)
  - road_tax_expiry         (optional)
  - last_service_date       (optional, YYYY-MM-DD)
  - service_interval_months (optional, integer, default 6)
  - last_service_cost       (optional)
  - odometer_km             (optional)

Empty cells are ignored — a vehicle without PUC expiry just won't have a PUC item.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import urllib.request
from typing import Any


# ---- Reminder defaults (same as the old YAML settings) ---- #
DEFAULT_SETTINGS = {
    "reminder_days": [60, 30, 15, 7, 3, 1, 0],
    "timezone": "Asia/Kolkata",
}


def fetch_sheet_csv(url: str) -> str:
    """Download the published CSV from Google Sheets."""
    req = urllib.request.Request(url, headers={"User-Agent": "vehicle-reminders/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def _clean(v: Any) -> str:
    """Normalize a cell value: strip whitespace, return empty string for None."""
    if v is None:
        return ""
    return str(v).strip()


def _num(v: Any) -> float | None:
    """Parse a number from a cell; return None if empty or unparseable."""
    s = _clean(v)
    if not s:
        return None
    try:
        # Remove commas and currency symbols
        clean_s = s.replace(",", "").replace("₹", "").replace("Rs", "").strip()
        return float(clean_s)
    except (ValueError, TypeError):
        return None


def _int(v: Any, default: int | None = None) -> int | None:
    n = _num(v)
    return int(n) if n is not None else default


def _row_to_vehicle(row: dict[str, str]) -> dict | None:
    """Convert a single CSV row to a vehicle config dict.

    Returns None if the row doesn't have the minimum required fields."""
    vid = _clean(row.get("vehicle_id"))
    vname = _clean(row.get("vehicle_name"))
    if not vid or not vname:
        return None  # Skip empty/incomplete rows

    vehicle = {
        "id": vid,
        "name": vname,
        "registration_number": _clean(row.get("registration_number")),
        "type": _clean(row.get("vehicle_type")) or "Vehicle",
        "owner": _clean(row.get("owner")),
        "notes": _clean(row.get("notes")),
        "documents": [],
        "services": [],
    }

    # --- Documents (only added if expiry date is present) --- #
    doc_specs = [
        # (type, expiry_col, provider_col, amount_col, file_col)
        ("Insurance", "insurance_expiry", "insurance_provider", "insurance_amount", "insurance_file"),
        ("PUC",       "puc_expiry",        None,                "puc_amount",        "puc_file"),
        ("Registration (RC)", "rc_expiry", None,                None,                "rc_file"),
        ("Fitness",   "fitness_expiry",    None,                None,                None),
        ("Road Tax",  "road_tax_expiry",   None,                None,                None),
    ]
    for dtype, exp_col, prov_col, amt_col, file_col in doc_specs:
        expiry = _clean(row.get(exp_col, ""))
        if not expiry:
            continue
        doc = {"type": dtype, "expiry_date": expiry}
        if prov_col:
            prov = _clean(row.get(prov_col, ""))
            if prov:
                doc["provider"] = prov
        if amt_col:
            amt = _num(row.get(amt_col))
            if amt is not None:
                doc["amount"] = amt
        if file_col:
            link = _clean(row.get(file_col, ""))
            if link:
                doc["file_link"] = link
        vehicle["documents"].append(doc)

    # --- General service (optional) --- #
    last_service = _clean(row.get("last_service_date"))
    if last_service:
        service = {
            "type": "General Service",
            "last_done": last_service,
            "interval_months": _int(row.get("service_interval_months"), 6),
        }
        cost = _num(row.get("last_service_cost"))
        if cost is not None:
            service["cost"] = cost
        odo = _int(row.get("odometer_km"))
        if odo is not None:
            service["odometer_km"] = odo
        vehicle["services"].append(service)

    return vehicle


def load_config_from_sheet(url: str | None = None) -> dict:
    """Main entry point — returns the same dict shape as load_config() in core.py.

    URL can be passed in or read from SHEET_CSV_URL environment variable."""
    url = url or os.environ.get("SHEET_CSV_URL")
    if not url:
        raise RuntimeError(
            "No Google Sheet URL provided. Set SHEET_CSV_URL environment variable "
            "or pass url argument."
        )

    print(f"📥 Fetching sheet data from Google...")
    csv_text = fetch_sheet_csv(url)
    reader = csv.DictReader(io.StringIO(csv_text))

    # Normalize headers: lowercase, underscore, no trailing spaces
    reader.fieldnames = [
        (h or "").strip().lower().replace(" ", "_")
        for h in (reader.fieldnames or [])
    ]

    vehicles = []
    skipped = 0
    for row in reader:
        # Normalize all keys the same way
        norm_row = {
            (k or "").strip().lower().replace(" ", "_"): v
            for k, v in row.items()
        }
        vehicle = _row_to_vehicle(norm_row)
        if vehicle:
            vehicles.append(vehicle)
        else:
            skipped += 1

    print(f"✅ Loaded {len(vehicles)} vehicle(s) from sheet"
          f"{f' (skipped {skipped} empty row(s))' if skipped else ''}")

    return {
        "settings": DEFAULT_SETTINGS,
        "vehicles": vehicles,
        "personal": [],  # Could be extended later with a second sheet/tab
    }


if __name__ == "__main__":
    # Quick test: python scripts/sheet_loader.py <url>
    if len(sys.argv) > 1:
        os.environ["SHEET_CSV_URL"] = sys.argv[1]
    cfg = load_config_from_sheet()
    print(f"\nSettings: {cfg['settings']}")
    print(f"Vehicles: {len(cfg['vehicles'])}")
    for v in cfg["vehicles"]:
        print(f"  - {v['name']} ({v['registration_number']}): "
              f"{len(v['documents'])} doc(s), {len(v['services'])} service(s)")
