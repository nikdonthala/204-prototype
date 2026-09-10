"""Tests for expiry_agent.optimizer."""

from __future__ import annotations

from expiry_agent.models import AtRiskBatch, CandidateDestination, SKU_BATCH, TransportLane
from expiry_agent.optimizer import optimize_transfers


def _batch(batch_id="b1", sku="A", loc="W1", qty=100):
    return SKU_BATCH(sku, loc, batch_id, "2026-09-20", qty)


def _at_risk(batch, units=100):
    return AtRiskBatch(batch=batch, days_to_expiry=10,
                       expected_demand_before_expiry=0, at_risk_units=units,
                       risk_ratio=units / batch.quantity, reason="test")


def _cand(loc, demand=50, headroom=1000, transit=1, cost=0.1, score=0):
    return CandidateDestination(
        location=loc, daily_demand=5,
        expected_demand_until_batch_expiry=demand, current_stock=0,
        capacity_headroom=headroom, transit_days=transit,
        cost_per_unit=cost, score=score,
    )


LANES = [TransportLane("W1", "S1", 1, 0.10), TransportLane("W1", "S2", 1, 0.10)]


def test_lp_rescues_within_demand_limits():
    b = _at_risk(_batch(), 100)
    cands = {("A", "b1"): [_cand("S1", demand=60), _cand("S2", demand=30)]}
    result = optimize_transfers([b], cands, LANES)
    assert result.solver_used == "ortools_lp"
    moved = sum(a.quantity for a in result.assignments)
    assert moved == 90  # demand-limited
    by_dest = {a.destination: a.quantity for a in result.assignments}
    assert by_dest["S1"] == 60
    assert by_dest["S2"] == 30


def test_capacity_limits_transfers():
    b = _at_risk(_batch(), 100)
    cands = {("A", "b1"): [_cand("S1", demand=200, headroom=40)]}
    result = optimize_transfers([b], cands, LANES)
    moved = sum(a.quantity for a in result.assignments)
    assert moved == 40
    assert result.unassigned_units == 60


def test_no_candidates_means_all_unassigned():
    b = _at_risk(_batch(), 100)
    result = optimize_transfers([b], {}, LANES)
    assert result.assignments == []
    assert result.unassigned_units == 100


def test_two_batches_share_destination_demand_pool():
    # Two source batches of the same SKU feeding one destination with
    # 50 units of unserved demand: combined shipments must not exceed 50.
    b1 = _at_risk(_batch("b1", loc="W1"), 100)
    b2 = _at_risk(_batch("b2", loc="W2"), 100)
    cands = {
        ("A", "b1"): [_cand("S1", demand=50)],
        ("A", "b2"): [_cand("S1", demand=50)],
    }
    lanes = LANES + [TransportLane("W2", "S1", 1, 0.10)]
    result = optimize_transfers([b1, b2], cands, lanes)
    moved = sum(a.quantity for a in result.assignments
                if a.destination == "S1")
    assert moved <= 50


def test_greedy_fallback_matches_lp_on_simple_case():
    b = _at_risk(_batch(), 100)
    cands = {("A", "b1"): [_cand("S1", demand=60), _cand("S2", demand=30)]}
    lp = optimize_transfers([b], cands, LANES)
    # Force greedy by importing the fallback directly.
    from expiry_agent.optimizer import _greedy_fallback
    greedy = _greedy_fallback([b], cands)
    assert sum(a.quantity for a in lp.assignments) == \
           sum(a.quantity for a in greedy.assignments) == 90
