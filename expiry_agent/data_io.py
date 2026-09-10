"""CSV data loading and validation.

Expected CSV schemas (headers are matched case-insensitively):

inventory.csv:  sku, location, batch_id, expiry_date, quantity, [unit_cost]
sales.csv:      sku, location, date, quantity
locations.csv:  name, kind, [storage_capacity]
transport.csv:  source, destination, transit_days, [cost_per_unit]
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from expiry_agent.models import (
    Location,
    SalesRecord,
    SKU_BATCH,
    TransportLane,
)


def _parse_date(value: str, field: str, file: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"{file}: invalid {field} '{value}' (expected YYYY-MM-DD)"
        ) from exc


def _parse_int(value: str, field: str, file: str) -> int:
    try:
        return int(float(value))
    except ValueError as exc:
        raise ValueError(f"{file}: invalid integer for {field}: '{value}'") from exc


def _parse_float(value: str, field: str, file: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{file}: invalid number for {field}: '{value}'") from exc


def _require_columns(row: dict, required: list[str], file: str, lineno: int) -> None:
    missing = [c for c in required if row.get(c) in (None, "")]
    if missing:
        raise ValueError(f"{file} line {lineno}: missing column(s) {missing}")


def load_inventory(path: str | Path) -> list[SKU_BATCH]:
    """Load inventory batches. Groups quantity by (sku, location, batch)."""
    batches: dict[tuple[str, str, str], SKU_BATCH] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            _require_columns(
                row, ["sku", "location", "batch_id", "expiry_date", "quantity"],
                str(path), lineno,
            )
            key = (
                row["sku"].strip(),
                row["location"].strip(),
                row["batch_id"].strip(),
            )
            qty = _parse_int(row["quantity"], "quantity", str(path))
            cost = (
                _parse_float(row["unit_cost"], "unit_cost", str(path))
                if row.get("unit_cost")
                else 1.0
            )
            expiry = _parse_date(row["expiry_date"], "expiry_date", str(path))
            if key in batches:
                # Same key appearing twice: sum quantities, keep first expiry/cost.
                prev = batches[key]
                batches[key] = SKU_BATCH(
                    sku=key[0], location=key[1], batch_id=key[2],
                    expiry_date=prev.expiry_date, quantity=prev.quantity + qty,
                    unit_cost=prev.unit_cost,
                )
            else:
                batches[key] = SKU_BATCH(
                    sku=key[0], location=key[1], batch_id=key[2],
                    expiry_date=expiry.isoformat(),
                    quantity=qty, unit_cost=cost,
                )
    return list(batches.values())


def load_sales(path: str | Path) -> list[SalesRecord]:
    """Load daily sales history. Sums duplicate (sku, location, date) rows."""
    records: dict[tuple[str, str, str], SalesRecord] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            _require_columns(row, ["sku", "location", "date", "quantity"],
                             str(path), lineno)
            key = (
                row["sku"].strip(),
                row["location"].strip(),
                row["date"].strip(),
            )
            qty = _parse_int(row["quantity"], "quantity", str(path))
            if key in records:
                prev = records[key]
                records[key] = SalesRecord(*key, quantity=prev.quantity + qty)
            else:
                records[key] = SalesRecord(*key, quantity=qty)
    return list(records.values())


def load_locations(path: str | Path) -> list[Location]:
    locations = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            _require_columns(row, ["name", "kind"], str(path), lineno)
            kind = row["kind"].strip().lower()
            if kind not in ("warehouse", "store"):
                raise ValueError(
                    f"{str(path)} line {lineno}: kind must be 'warehouse' or 'store',"
                    f" got '{row['kind']}'"
                )
            capacity = (
                _parse_int(row["storage_capacity"], "storage_capacity", str(path))
                if row.get("storage_capacity")
                else 10_000
            )
            locations.append(Location(name=row["name"].strip(), kind=kind,
                                      storage_capacity=capacity))
    return locations


def load_transport(path: str | Path) -> list[TransportLane]:
    lanes = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            _require_columns(
                row, ["source", "destination", "transit_days"], str(path), lineno
            )
            lanes.append(
                TransportLane(
                    source=row["source"].strip(),
                    destination=row["destination"].strip(),
                    transit_days=_parse_int(row["transit_days"], "transit_days",
                                            str(path)),
                    cost_per_unit=(
                        _parse_float(row["cost_per_unit"], "cost_per_unit",
                                     str(path))
                        if row.get("cost_per_unit")
                        else 0.0
                    ),
                )
            )
    return lanes
