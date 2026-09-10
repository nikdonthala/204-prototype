"""Generate a small but realistic demo dataset.

Scenario: two warehouses and four stores sell a perishable SKU family.
Warehouse W1 over-ordered SKU-A; store S4 sells it fast but holds little.
Some stock is close to expiry at W1 -> the agent should recommend moving
it to S4 (and possibly S3) before it expires.

`build_sample()` returns ready-to-use model objects (used by the web API
and tests); `generate_sample()` writes the same scenario as CSVs (used by
the CLI and as a schema example).
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from expiry_agent.models import Location, SalesRecord, SKU_BATCH, TransportLane

LOCATIONS = [
    ("W1", "warehouse", 5000),
    ("W2", "warehouse", 5000),
    ("S1", "store", 400),
    ("S2", "store", 400),
    ("S3", "store", 400),
    ("S4", "store", 600),
]

LANES = [
    # Warehouses ship to all stores; stores never ship.
    ("W1", "S1", 1, 0.10), ("W1", "S2", 1, 0.10),
    ("W1", "S3", 2, 0.15), ("W1", "S4", 2, 0.15),
    ("W2", "S1", 2, 0.15), ("W2", "S2", 2, 0.15),
    ("W2", "S3", 1, 0.10), ("W2", "S4", 1, 0.10),
]

# sku -> (base daily demand per location)
DEMAND = {
    "SKU-A": {"W1": 5, "W2": 5, "S1": 8, "S2": 6, "S3": 12, "S4": 25},
    "SKU-B": {"W1": 3, "W2": 4, "S1": 6, "S2": 5, "S3": 7, "S4": 9},
}

HISTORY_DAYS = 60


def _sales_rows(today: date, rng: random.Random) -> list[list]:
    start = today - timedelta(days=HISTORY_DAYS)
    rows = []
    for sku, by_loc in DEMAND.items():
        for loc, base in by_loc.items():
            d = start
            while d <= today:
                seasonal = 1.3 if d.weekday() in (4, 5) else 1.0  # Fri/Sat bump
                qty = max(0, round(rng.gauss(base * seasonal, base * 0.25)))
                rows.append([sku, loc, d.isoformat(), qty])
                d += timedelta(days=1)
    return rows


def _inventory_rows(today: date) -> list[list]:
    return [
        # sku, location, batch_id, expiry_date, quantity, unit_cost
        # W1: big batch of SKU-A expiring in 12 days, demand there is only ~5/day
        ["SKU-A", "W1", "A-W1-001", (today + timedelta(days=12)).isoformat(),
         600, 2.50],
        ["SKU-A", "W1", "A-W1-002", (today + timedelta(days=40)).isoformat(),
         300, 2.50],
        # W2: healthy levels
        ["SKU-A", "W2", "A-W2-001", (today + timedelta(days=25)).isoformat(),
         150, 2.50],
        # S4 sells ~25/day but only holds a small old batch
        ["SKU-A", "S4", "A-S4-001", (today + timedelta(days=8)).isoformat(),
         80, 2.50],
        # S3 moderate
        ["SKU-A", "S3", "A-S3-001", (today + timedelta(days=20)).isoformat(),
         120, 2.50],
        # SKU-B: balanced everywhere (should NOT be flagged)
        ["SKU-B", "W1", "B-W1-001", (today + timedelta(days=30)).isoformat(),
         90, 1.80],
        ["SKU-B", "S4", "B-S4-001", (today + timedelta(days=30)).isoformat(),
         280, 1.80],
        ["SKU-B", "S3", "B-S3-001", (today + timedelta(days=30)).isoformat(),
         210, 1.80],
    ]


def build_sample(
    today: date | None = None, seed: int = 42
) -> tuple[list[SKU_BATCH], list[SalesRecord], list[Location], list[TransportLane]]:
    """Build the demo scenario as in-memory model objects."""
    today = today or date.today()
    rng = random.Random(seed)

    batches = [
        SKU_BATCH(sku=r[0], location=r[1], batch_id=r[2], expiry_date=r[3],
                  quantity=r[4], unit_cost=r[5])
        for r in _inventory_rows(today)
    ]
    sales = [
        SalesRecord(sku=r[0], location=r[1], date=r[2], quantity=r[3])
        for r in _sales_rows(today, rng)
    ]
    locations = [Location(name=n, kind=k, storage_capacity=c)
                 for n, k, c in LOCATIONS]
    lanes = [TransportLane(source=s, destination=d, transit_days=t,
                           cost_per_unit=c) for s, d, t, c in LANES]
    return batches, sales, locations, lanes


def generate_sample(out_dir: str | Path, seed: int = 42) -> None:
    """Write the demo scenario as CSV files (same data as build_sample)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = date.today()
    rng = random.Random(seed)

    with open(out / "sales.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "location", "date", "quantity"])
        w.writerows(_sales_rows(today, rng))

    with open(out / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "location", "batch_id", "expiry_date", "quantity",
                    "unit_cost"])
        w.writerows(_inventory_rows(today))

    with open(out / "locations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "kind", "storage_capacity"])
        w.writerows(LOCATIONS)

    with open(out / "transport.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "destination", "transit_days", "cost_per_unit"])
        w.writerows(LANES)
