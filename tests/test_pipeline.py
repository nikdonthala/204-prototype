"""End-to-end pipeline test on the generated sample dataset."""

from __future__ import annotations

from datetime import date

from expiry_agent.data_io import (
    load_inventory,
    load_locations,
    load_sales,
    load_transport,
)
from expiry_agent.pipeline import run_pipeline
from expiry_agent.sample_data import generate_sample


def test_pipeline_end_to_end(tmp_path):
    generate_sample(tmp_path, seed=42)
    today = date.today()

    batches = load_inventory(tmp_path / "inventory.csv")
    sales = load_sales(tmp_path / "sales.csv")
    locations = load_locations(tmp_path / "locations.csv")
    lanes = load_transport(tmp_path / "transport.csv")

    plan = run_pipeline(batches, sales, locations, lanes, today)

    # The demo scenario must flag the over-stocked near-expiry W1 batch.
    flagged = {a.batch.batch_id for a in plan.at_risk_batches}
    assert "A-W1-001" in flagged

    # Balanced SKU-B stock must never be flagged.
    assert not any(b.batch.sku == "SKU-B" for b in plan.at_risk_batches)

    # Every transfer must carry a non-empty explanation.
    for t in plan.transfers:
        assert t.explanation, f"missing explanation for {t}"
        assert t.quantity > 0

    # Transfers should rescue units and account for cost/impact.
    assert plan.units_rescued == sum(t.quantity for t in plan.transfers)
    assert plan.total_transport_cost >= 0
    assert plan.writeoff_value_avoided > 0

    # Transfers must respect lane feasibility (transit before expiry).
    for t in plan.transfers:
        lane = next(ln for ln in lanes
                    if ln.source == t.source and ln.destination == t.destination)
        assert t.transit_days == lane.transit_days


def test_pipeline_no_risk(tmp_path):
    """A tiny balanced dataset should produce no transfers."""
    from expiry_agent.models import Location, SalesRecord, SKU_BATCH, TransportLane
    batches = [SKU_BATCH("A", "W1", "b1", "2026-09-30", 50)]
    sales = [SalesRecord("A", "W1", "2026-09-09", 20),
             SalesRecord("A", "W1", "2026-09-08", 20)]
    locations = [Location("W1", "warehouse"), Location("S1", "store")]
    lanes = [TransportLane("W1", "S1", 1, 0.1)]
    plan = run_pipeline(batches, sales, locations, lanes, date(2026, 9, 10))
    assert plan.transfers == []
    assert "No at-risk inventory detected" in plan.notes[0]
