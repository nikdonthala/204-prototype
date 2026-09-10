"""Rank candidate destinations for an at-risk batch.

A destination is attractive when it has high unserved forecast demand
before the batch's expiry, enough capacity headroom, and a fast/cheap
lane from the source. The score is a simple, explainable weighted sum;
the final *quantities* come from the optimizer, not this score.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from expiry_agent.forecast import FORECASTERS, demand_until
from expiry_agent.models import (
    AtRiskBatch,
    CandidateDestination,
    Location,
    SalesRecord,
    SKU_BATCH,
    TransportLane,
)

# Weights for the explainable destination score.
W_DEMAND = 1.0
W_TRANSIT = -0.5   # per day of transit (penalty)
W_COST = -2.0      # per cost unit (penalty)


def rank_destinations(
    batch: SKU_BATCH,
    at_risk_units: int,
    today: date,
    batches: list[SKU_BATCH],
    sales: list[SalesRecord],
    locations: list[Location],
    lanes: list[TransportLane],
    forecaster: str = "moving_average",
) -> list[CandidateDestination]:
    """Rank all other locations that can receive this batch before expiry."""
    if at_risk_units <= 0:
        return []

    forecast_fn = FORECASTERS[forecaster]
    expiry = datetime.strptime(batch.expiry_date, "%Y-%m-%d").date()

    stock_by_loc: dict[str, int] = {}
    for b in batches:
        if b.sku == batch.sku:
            stock_by_loc[b.location] = stock_by_loc.get(b.location, 0) + b.quantity

    sales_by_loc: dict[str, list[SalesRecord]] = {}
    for r in sales:
        if r.sku == batch.sku:
            sales_by_loc.setdefault(r.location, []).append(r)

    capacity_by_loc = {loc.name: loc for loc in locations}
    lanes_by_pair = {(ln.source, ln.destination): ln for ln in lanes}

    candidates: list[CandidateDestination] = []
    for loc in locations:
        if loc.name == batch.location:
            continue
        lane = lanes_by_pair.get((batch.location, loc.name))
        if lane is None:
            continue  # no direct lane -> not reachable in the MVP
        # Stock must land before expiry AND before it expires in transit.
        if today + timedelta(days=lane.transit_days) > expiry:
            cand = CandidateDestination(
                location=loc.name, daily_demand=0.0,
                expected_demand_until_batch_expiry=0.0,
                current_stock=stock_by_loc.get(loc.name, 0),
                capacity_headroom=max(loc.storage_capacity
                                      - stock_by_loc.get(loc.name, 0), 0),
                transit_days=lane.transit_days,
                cost_per_unit=lane.cost_per_unit,
                score=0.0,
                notes="transit arrives after expiry - infeasible lane",
            )
            candidates.append(cand)
            continue

        records = sales_by_loc.get(loc.name, [])
        daily, _ = forecast_fn(records, today)
        horizon_days = (expiry - today).days
        demand = demand_until(daily, today, expiry,
                              lead_days=lane.transit_days)

        # Demand already claimed by stock already sitting at the destination
        # that expires no later than this batch (they sell first, FEFO).
        competing = sum(
            b.quantity for b in batches
            if b.sku == batch.sku and b.location == loc.name
            and b.expiry_date <= batch.expiry_date
        )
        unserved = max(demand - competing, 0.0)

        headroom = max(loc.storage_capacity - stock_by_loc.get(loc.name, 0), 0)
        if headroom < at_risk_units:
            notes = f"limited headroom ({headroom} < {at_risk_units})"
        else:
            notes = ""

        score = (W_DEMAND * unserved
                 + W_TRANSIT * lane.transit_days
                 + W_COST * lane.cost_per_unit * at_risk_units)
        candidates.append(
            CandidateDestination(
                location=loc.name,
                daily_demand=daily,
                expected_demand_until_batch_expiry=unserved,
                current_stock=stock_by_loc.get(loc.name, 0),
                capacity_headroom=headroom,
                transit_days=lane.transit_days,
                cost_per_unit=lane.cost_per_unit,
                score=score,
                notes=notes,
            )
        )
    return sorted(candidates, key=lambda c: c.score, reverse=True)
