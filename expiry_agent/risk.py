"""Expiry-risk classification: which stock will likely go unsold?

At-Risk Stock = Current Stock - Expected Demand Before Expiry

A batch is flagged when expected demand at its own location over the
remaining shelf life cannot absorb the batch quantity, or when the
remaining shelf life is too short to even complete a transfer elsewhere.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from expiry_agent.forecast import FORECASTERS, demand_until
from expiry_agent.models import AtRiskBatch, SalesRecord, SKU_BATCH


def days_to_expiry(expiry_date: str, today: date) -> int:
    return (datetime.strptime(expiry_date, "%Y-%m-%d").date() - today).days


def compute_at_risk(
    batches: list[SKU_BATCH],
    sales: list[SalesRecord],
    today: date,
    forecaster: str = "moving_average",
    safety_factor: float = 1.0,
) -> list[AtRiskBatch]:
    """Return batches whose on-hand stock exceeds expected demand before expiry.

    Demand is pooled per (sku, location) and allocated FEFO: earlier-expiring
    batches consume local demand first; a batch is at risk when the demand
    left over after earlier stock sells cannot absorb its quantity.

    safety_factor scales the demand forecast: > 1 inflates expected demand
    (service-level buffer -> fewer units flagged as surplus), < 1 assumes
    softer demand (flags more stock as movable).
    """
    forecast_fn = FORECASTERS[forecaster]

    sales_by_key: dict[tuple[str, str], list[SalesRecord]] = defaultdict(list)
    for r in sales:
        sales_by_key[(r.sku, r.location)].append(r)

    # Group batches by (sku, location) for FEFO demand pooling.
    groups: dict[tuple[str, str], list[SKU_BATCH]] = defaultdict(list)
    for b in batches:
        groups[(b.sku, b.location)].append(b)

    at_risk: list[AtRiskBatch] = []
    for (sku, loc), group in sorted(groups.items()):
        records = sales_by_key.get((sku, loc), [])
        daily, _ = forecast_fn(records, today)
        total_stock = sum(x.quantity for x in group)

        stock_earlier = 0  # stock of batches expiring before this one
        for b in sorted(group, key=lambda x: x.expiry_date):
            dte = days_to_expiry(b.expiry_date, today)
            expiry = datetime.strptime(b.expiry_date, "%Y-%m-%d").date()

            if dte <= 0:
                at_risk_units = b.quantity
                batch_expected = 0.0
                reason = f"batch already expired on {b.expiry_date}"
            else:
                horizon_demand = demand_until(
                    daily * safety_factor, today, expiry
                )
                # Earlier stock sells first (FEFO); this batch only gets
                # the leftover demand within its own remaining shelf life.
                sellable = max(horizon_demand - stock_earlier, 0.0)
                at_risk_units = max(b.quantity - int(round(sellable)), 0)
                batch_expected = min(sellable, float(b.quantity))
                reason = (
                    f"expected demand at {loc} before {b.expiry_date} is "
                    f"{horizon_demand:.0f} units vs {total_stock} on hand "
                    f"(daily forecast {daily:.1f})"
                )
                if at_risk_units == 0:
                    reason += " - local demand covers this batch, no action needed"

            stock_earlier += b.quantity
            risk_ratio = at_risk_units / b.quantity if b.quantity else 0.0
            at_risk.append(
                AtRiskBatch(
                    batch=b,
                    days_to_expiry=dte,
                    expected_demand_before_expiry=batch_expected,
                    at_risk_units=at_risk_units,
                    risk_ratio=risk_ratio,
                    reason=reason,
                )
            )
    return at_risk
