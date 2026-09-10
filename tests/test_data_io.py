"""Tests for CSV loaders and validation errors."""

from __future__ import annotations

import pytest

from expiry_agent.data_io import (
    load_inventory,
    load_locations,
    load_sales,
    load_transport,
)


def test_load_inventory(tmp_path):
    f = tmp_path / "inventory.csv"
    f.write_text(
        "sku,location,batch_id,expiry_date,quantity,unit_cost\n"
        "A,W1,b1,2026-09-20,100,2.5\n"
        "A,W1,b1,2026-09-20,50,2.5\n"
        "A,S1,b2,2026-09-25,10\n",
        encoding="utf-8",
    )
    batches = load_inventory(f)
    assert len(batches) == 2
    by_id = {b.batch_id: b for b in batches}
    assert by_id["b1"].quantity == 150  # duplicates summed
    assert by_id["b1"].unit_cost == 2.5
    assert by_id["b2"].unit_cost == 1.0  # default


def test_load_sales_sums_duplicates(tmp_path):
    f = tmp_path / "sales.csv"
    f.write_text(
        "sku,location,date,quantity\n"
        "A,W1,2026-09-01,5\n"
        "A,W1,2026-09-01,7\n",
        encoding="utf-8",
    )
    records = load_sales(f)
    assert len(records) == 1
    assert records[0].quantity == 12


def test_load_locations(tmp_path):
    f = tmp_path / "locations.csv"
    f.write_text(
        "name,kind,storage_capacity\n"
        "W1,warehouse,5000\n"
        "S1,store\n",
        encoding="utf-8",
    )
    locs = load_locations(f)
    assert locs[0].storage_capacity == 5000
    assert locs[1].storage_capacity == 10_000  # default


def test_load_locations_bad_kind(tmp_path):
    f = tmp_path / "locations.csv"
    f.write_text("name,kind\nX,depot\n", encoding="utf-8")
    with pytest.raises(ValueError, match="kind"):
        load_locations(f)


def test_load_transport_defaults(tmp_path):
    f = tmp_path / "transport.csv"
    f.write_text("source,destination,transit_days\nW1,S1,2\n", encoding="utf-8")
    lanes = load_transport(f)
    assert lanes[0].cost_per_unit == 0.0


def test_missing_column_raises(tmp_path):
    f = tmp_path / "inventory.csv"
    f.write_text("sku,location,batch_id,expiry_date\nA,W1,b1,2026-09-20\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        load_inventory(f)


def test_bad_date_raises(tmp_path):
    f = tmp_path / "inventory.csv"
    f.write_text(
        "sku,location,batch_id,expiry_date,quantity\nA,W1,b1,09/20/2026,10\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expiry_date"):
        load_inventory(f)
