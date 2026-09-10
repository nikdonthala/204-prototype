"""Pipeline orchestration: data -> risk -> candidates -> optimize -> plan.

This module also builds the human-readable explanation for every
recommendation, which is the core "decision support" deliverable.
"""

from __future__ import annotations

from datetime import date

from expiry_agent.destinations import rank_destinations
from expiry_agent.models import (
    AtRiskBatch,
    CandidateDestination,
    Location,
    SalesRecord,
    SKU_BATCH,
    Transfer,
    TransferPlan,
    TransportLane,
)
from expiry_agent.optimizer import Assignment, OptimizationResult, optimize_transfers
from expiry_agent.risk import compute_at_risk


def _explain(
    b: AtRiskBatch,
    c: CandidateDestination,
    qty: int,
) -> str:
    """One-sentence business justification for a transfer."""
    lane_txt = (
        f"{c.transit_days}-day transit"
        if c.transit_days
        else "same-day transfer"
    )
    parts = [
        f"{b.batch.location} holds {b.at_risk_units} surplus units of "
        f"{b.batch.sku} (batch {b.batch.batch_id}) expiring {b.batch.expiry_date} "
        f"({b.days_to_expiry} days left), but local demand covers only "
        f"{b.expected_demand_before_expiry:.0f} of them",
        f"{c.location} has {c.expected_demand_until_batch_expiry:.0f} units of "
        f"unserved forecast demand before that expiry (daily {c.daily_demand:.1f})",
        f"{lane_txt} at {c.cost_per_unit:.2f} per unit",
        f"moving {qty} units avoids ~{qty * b.batch.unit_cost:.0f} in write-off value",
    ]
    if c.notes:
        parts.append(f"note: {c.notes}")
    return "; ".join(parts) + "."


def _to_transfer(
    a: Assignment,
    explanation: str,
    lanes: list[TransportLane],
) -> Transfer:
    lane = next(
        (ln for ln in lanes
         if ln.source == a.batch.batch.location and ln.destination == a.destination),
        None,
    )
    transit = lane.transit_days if lane else 0
    cost = lane.cost_per_unit * a.quantity if lane else 0.0
    return Transfer(
        sku=a.batch.batch.sku,
        batch_id=a.batch.batch.batch_id,
        source=a.batch.batch.location,
        destination=a.destination,
        quantity=a.quantity,
        expiry_date=a.batch.batch.expiry_date,
        transit_days=transit,
        transport_cost=cost,
        explanation=explanation,
    )


def run_pipeline(
    batches: list[SKU_BATCH],
    sales: list[SalesRecord],
    locations: list[Location],
    lanes: list[TransportLane],
    today: date,
    forecaster: str = "moving_average",
    safety_factor: float = 1.0,
    rescue_value_per_unit: float = 10.0,
) -> TransferPlan:
    """Run the full expiry-risk -> redistribution pipeline."""
    plan = TransferPlan()

    # 1. Expiry risk.
    at_risk = compute_at_risk(batches, sales, today,
                              forecaster=forecaster,
                              safety_factor=safety_factor)
    at_risk = [a for a in at_risk if a.at_risk_units > 0]
    plan.at_risk_batches = at_risk

    if not at_risk:
        plan.notes.append("No at-risk inventory detected - no transfers needed.")
        return plan

    # 2. Candidate destinations per at-risk batch.
    candidates: dict[tuple[str, str], list[CandidateDestination]] = {}
    for a in at_risk:
        ranked = rank_destinations(
            batch=a.batch,
            at_risk_units=a.at_risk_units,
            today=today,
            batches=batches,
            sales=sales,
            locations=locations,
            lanes=lanes,
            forecaster=forecaster,
        )
        candidates[(a.batch.sku, a.batch.batch_id)] = ranked
    plan.candidates = candidates

    # 3. Optimize transfer quantities.
    result: OptimizationResult = optimize_transfers(
        at_risk, candidates, lanes,
        rescue_value_per_unit=rescue_value_per_unit,
    )
    plan.notes.append(f"solver: {result.solver_used}")

    # 4. Build explained recommendations.
    for a in result.assignments:
        cands = candidates[(a.batch.batch.sku, a.batch.batch.batch_id)]
        c = next((cc for cc in cands if cc.location == a.destination), None)
        if c is None:
            continue
        explanation = _explain(a.batch, c, a.quantity)
        plan.transfers.append(_to_transfer(a, explanation, lanes))

    # Sort: most urgent expiries first.
    plan.transfers.sort(key=lambda t: (t.expiry_date, -t.quantity))

    plan.total_transport_cost = sum(t.transport_cost for t in plan.transfers)
    plan.units_rescued = sum(t.quantity for t in plan.transfers)
    plan.writeoff_value_avoided = sum(
        t.quantity * next(b.unit_cost for b in batches
                          if b.sku == t.sku and b.batch_id == t.batch_id)
        for t in plan.transfers
    )
    plan.unassigned_units = result.unassigned_units
    plan.notes.append(
        f"rescued {plan.units_rescued} units across {len(plan.transfers)} "
        f"transfers; transport cost {plan.total_transport_cost:.2f}; "
        f"write-off value avoided ~{plan.writeoff_value_avoided:.0f}"
    )
    return plan
