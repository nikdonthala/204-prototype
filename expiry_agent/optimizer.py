"""Transfer optimization.

Given at-risk batches and their candidate destinations, decide how many
units go where. Two solvers:

1. OR-Tools linear program (default): maximizes rescue value minus
   transport cost, subject to
   - supply: cannot ship more than the at-risk units of a batch,
   - demand (FEFO covering): for every destination/SKU and every expiry
     threshold, units arriving from batches expiring by that threshold
     cannot exceed the destination's unserved forecast demand before it,
   - capacity: cannot exceed storage headroom at the destination.
2. Greedy fallback: batches (FEFO, most urgent first) send units to their
   best destination with remaining demand/capacity headroom. Used when
   OR-Tools is unavailable or the LP fails, so the agent degrades
   gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date  # noqa: F401  (re-exported for typing)

try:  # OR-Tools is optional: the greedy fallback keeps the agent working
    from ortools.linear_solver import pywraplp  # type: ignore

    _HAS_ORTOOLS = True
except Exception:  # pragma: no cover - depends on deployment env
    pywraplp = None  # type: ignore[assignment]
    _HAS_ORTOOLS = False

from expiry_agent.models import AtRiskBatch, CandidateDestination, TransportLane


@dataclass(frozen=True)
class Assignment:
    """Units from one at-risk batch assigned to one destination."""

    batch: AtRiskBatch
    destination: str
    quantity: int


@dataclass
class OptimizationResult:
    assignments: list[Assignment] = field(default_factory=list)
    unassigned_units: int = 0
    solver_used: str = "none"


def _candidate_value(
    candidates: dict[tuple[str, str], list[CandidateDestination]],
    sku: str,
    batch_id: str,
    dest: str,
) -> CandidateDestination | None:
    return next(
        (c for c in candidates.get((sku, batch_id), []) if c.location == dest),
        None,
    )


def _usable_batches(
    at_risk: list[AtRiskBatch],
    candidates: dict[tuple[str, str], list[CandidateDestination]],
) -> list[AtRiskBatch]:
    return [
        b for b in at_risk
        if b.at_risk_units > 0 and candidates.get((b.batch.sku, b.batch.batch_id))
    ]


def optimize_transfers(
    at_risk: list[AtRiskBatch],
    candidates: dict[tuple[str, str], list[CandidateDestination]],
    lanes: list[TransportLane],
    rescue_value_per_unit: float = 10.0,
) -> OptimizationResult:
    """Maximize (rescue value - transport cost) via LP; greedy on failure.

    rescue_value_per_unit is the effective value of rescuing one unit
    (avoided write-off). Higher values push the optimizer to move more
    aggressively; lower values make it cost-cautious.
    """
    usable = _usable_batches(at_risk, candidates)
    total_at_risk = sum(b.at_risk_units for b in at_risk)
    if not usable:
        return OptimizationResult(unassigned_units=total_at_risk,
                                  solver_used="none")

    result = _solve_lp(usable, candidates, lanes, rescue_value_per_unit)
    if result is None:
        result = _greedy_fallback(usable, candidates)
    moved = sum(a.quantity for a in result.assignments)
    result.unassigned_units = max(total_at_risk - moved, 0)
    return result


def _solve_lp(
    usable: list[AtRiskBatch],
    candidates: dict[tuple[str, str], list[CandidateDestination]],
    lanes: list[TransportLane],
    rescue_value_per_unit: float,
) -> OptimizationResult | None:
    lane_by_pair = {(ln.source, ln.destination): ln for ln in lanes}
    batch_by_key = {(b.batch.sku, b.batch.batch_id): b for b in usable}

    solver = pywraplp.Solver.CreateSolver("GLOP") if _HAS_ORTOOLS else None
    if solver is None:
        return None

    # Variable x[(sku, batch_id, dest)] = units moved from batch to dest.
    # Skip destinations with no unserved demand: nothing there can absorb
    # the stock, so a variable would only invite wasteful shipments.
    x: dict[tuple[str, str, str], object] = {}
    for b in usable:
        for c in candidates[(b.batch.sku, b.batch.batch_id)]:
            if c.expected_demand_until_batch_expiry <= 0:
                continue
            x[(b.batch.sku, b.batch.batch_id, c.location)] = solver.NumVar(
                0, b.at_risk_units,
                f"x_{b.batch.sku}_{b.batch.batch_id}_{c.location}",
            )

    if not x:
        return OptimizationResult(
            unassigned_units=sum(b.at_risk_units for b in usable),
            solver_used="lp_no_feasible_moves",
        )

    # Supply constraints (per batch).
    for b in usable:
        vars_b = [v for (s, bid, _d), v in x.items()
                  if s == b.batch.sku and bid == b.batch.batch_id]
        if vars_b:
            solver.Add(solver.Sum(vars_b) <= b.at_risk_units)

    # Demand constraints (FEFO covering) per (destination, sku):
    # for every distinct expiry threshold E, the units shipped there from
    # batches expiring by E cannot exceed the demand available before E.
    vars_by_dest_sku: dict[tuple[str, str], dict[str, list[object]]] = {}
    pool_by_dest_sku_expiry: dict[tuple[str, str, str], float] = {}
    for (sku, batch_id, dest), var in x.items():
        b = batch_by_key[(sku, batch_id)]
        vars_by_dest_sku.setdefault((dest, sku), {})\
            .setdefault(b.batch.expiry_date, []).append(var)
        c = _candidate_value(candidates, sku, batch_id, dest)
        assert c is not None
        key = (dest, sku, b.batch.expiry_date)
        pool_by_dest_sku_expiry[key] = max(
            pool_by_dest_sku_expiry.get(key, 0.0),
            c.expected_demand_until_batch_expiry,
        )

    for (dest, sku), by_expiry in vars_by_dest_sku.items():
        expiries = sorted(by_expiry)
        for threshold in expiries:
            vars_up_to = [v for e in expiries if e <= threshold
                          for v in by_expiry[e]]
            pool = pool_by_dest_sku_expiry[(dest, sku, threshold)]
            if vars_up_to:
                solver.Add(solver.Sum(vars_up_to) <= pool)

    # Capacity constraints (per destination, all skus).
    headroom: dict[str, float] = {}
    for b in usable:
        for c in candidates[(b.batch.sku, b.batch.batch_id)]:
            if c.location not in headroom:
                headroom[c.location] = c.capacity_headroom
            else:
                headroom[c.location] = min(headroom[c.location],
                                           c.capacity_headroom)
    for dest, cap in headroom.items():
        vars_c = [v for (_s, _bid, d), v in x.items() if d == dest]
        if vars_c:
            solver.Add(solver.Sum(vars_c) <= cap)

    # Objective: rescue value per unit moved, minus transport cost.
    objective = solver.Objective()
    for (sku, batch_id, dest), var in x.items():
        b = batch_by_key[(sku, batch_id)]
        lane = lane_by_pair[(b.batch.location, dest)]
        objective.SetCoefficient(var, rescue_value_per_unit - lane.cost_per_unit)
    objective.SetMaximization()

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return None

    assignments = [
        Assignment(batch=batch_by_key[(sku, batch_id)], destination=dest,
                   quantity=int(round(var.solution_value())))
        for (sku, batch_id, dest), var in x.items()
        if int(round(var.solution_value())) > 0
    ]
    return OptimizationResult(assignments=assignments, solver_used="ortools_lp")


def _greedy_fallback(
    usable: list[AtRiskBatch],
    candidates: dict[tuple[str, str], list[CandidateDestination]],
) -> OptimizationResult:
    """FEFO greedy: earliest expiry ships first to the best destination."""
    total_at_risk = sum(b.at_risk_units for b in usable)
    demand_used: dict[tuple[str, str], float] = {}
    capacity_left: dict[str, float] = {}
    assignments: list[Assignment] = []
    supply_left: dict[tuple[str, str], int] = {
        (b.batch.sku, b.batch.batch_id): b.at_risk_units for b in usable
    }

    # Most urgent first: earliest expiry, then largest risk ratio.
    for b in sorted(usable, key=lambda x: (x.days_to_expiry, -x.risk_ratio)):
        key_b = (b.batch.sku, b.batch.batch_id)
        cands = [c for c in candidates[key_b]
                 if c.expected_demand_until_batch_expiry > 0]
        for c in sorted(cands, key=lambda c: c.score, reverse=True):
            qty = min(
                supply_left[key_b],
                int(c.expected_demand_until_batch_expiry
                    - demand_used.get((c.location, b.batch.sku), 0.0)),
                int(capacity_left.get(c.location, c.capacity_headroom)),
            )
            if qty <= 0:
                continue
            assignments.append(Assignment(batch=b, destination=c.location,
                                          quantity=qty))
            supply_left[key_b] -= qty
            demand_used[(c.location, b.batch.sku)] = \
                demand_used.get((c.location, b.batch.sku), 0.0) + qty
            capacity_left[c.location] = \
                capacity_left.get(c.location, c.capacity_headroom) - qty
            if supply_left[key_b] <= 0:
                break

    return OptimizationResult(assignments=assignments, solver_used="greedy",
                              unassigned_units=total_at_risk)
