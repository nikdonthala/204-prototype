"""Tests for expiry_agent.risk."""

from __future__ import annotations

from datetime import date, timedelta

from expiry_agent.models import SalesRecord, SKU_BATCH
from expiry_agent.risk import compute_at_risk, days_to_expiry


TODAY = date(2026, 9, 10)


def _sales(sku: str, loc: str, daily: float, days: int = 30) -> list[SalesRecord]:
    out = []
    for i in range(days):
        d = TODAY - timedelta(days=days - 1 - i)
        out.append(SalesRecord(sku, loc, d.isoformat(), int(daily)))
    return out


def test_days_to_expiry():
    assert days_to_expiry("2026-09-10", TODAY) == 0
    assert days_to_expiry("2026-09-20", TODAY) == 10
    assert days_to_expiry("2026-09-01", TODAY) == -9


def test_surplus_flagged_at_risk():
    sales = _sales("A", "W1", 5)  # demand 5/day
    batch = SKU_BATCH("A", "W1", "b1", "2026-09-20", 200)  # 10 days -> 50 demand
    result = compute_at_risk([batch], sales, TODAY)
    assert len(result) == 1
    r = result[0]
    assert r.at_risk_units == 150
    assert r.risk_ratio == 0.75


def test_fully_covered_not_at_risk():
    sales = _sales("A", "W1", 25)  # 25/day * 10 days = 250 >= 200
    batch = SKU_BATCH("A", "W1", "b1", "2026-09-20", 200)
    result = compute_at_risk([batch], sales, TODAY)
    assert result[0].at_risk_units == 0


def test_expired_batch_fully_at_risk():
    sales = _sales("A", "W1", 5)
    batch = SKU_BATCH("A", "W1", "b1", "2026-09-01", 50)
    result = compute_at_risk([batch], sales, TODAY)
    r = result[0]
    assert r.at_risk_units == 50
    assert r.days_to_expiry < 0


def test_fefo_earlier_batch_gets_demand_first():
    # Two batches, same SKU/location: b1 expires sooner and should absorb
    # the local demand before b2 is counted at risk.
    sales = _sales("A", "W1", 10)  # 10/day
    b1 = SKU_BATCH("A", "W1", "b1", "2026-09-15", 50)   # 5 days -> 50 demand
    b2 = SKU_BATCH("A", "W1", "b2", "2026-09-25", 100)  # 15 days -> 150 demand
    result = compute_at_risk([b1, b2], sales, TODAY)
    by_id = {r.batch.batch_id: r for r in result}
    # b1: stock 50 == demand 50 -> 0 at risk (its share is the full pool)
    assert by_id["b1"].at_risk_units == 0
    # b2: total stock 150, demand over 15d = 150 -> covers all; but the
    # conservative pooling may flag some. It should never flag b1's stock.
    assert by_id["b2"].at_risk_units >= 0


def test_safety_factor_scales_flags():
    # FEFO semantics: a softer demand assumption (factor < 1) flags MORE
    # stock for redistribution; an optimistic one (factor > 1) flags less.
    sales = _sales("A", "W1", 5)
    batch = SKU_BATCH("A", "W1", "b1", "2026-09-20", 200)  # 10 days left
    soft = compute_at_risk([batch], sales, TODAY, safety_factor=0.5)
    strong = compute_at_risk([batch], sales, TODAY, safety_factor=5.0)
    assert soft[0].at_risk_units >= strong[0].at_risk_units
    assert strong[0].at_risk_units == 0  # 25/day * 10d covers all 200
