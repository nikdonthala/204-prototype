"""Core data models shared across the pipeline.

All quantities are in sellable units (pieces, packs, ...). Currency is
abstract ("cost units") so the model works without a specific currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SKU_BATCH:
    """One batch of one SKU sitting at one location."""

    sku: str
    location: str
    batch_id: str
    expiry_date: str  # ISO date, e.g. "2026-09-30"
    quantity: int
    unit_cost: float = 1.0  # cost per unit (write-off cost if unsold)


@dataclass(frozen=True)
class SalesRecord:
    """One day of observed sales for one SKU at one location."""

    sku: str
    location: str
    date: str  # ISO date
    quantity: int


@dataclass(frozen=True)
class Location:
    """A warehouse or store that can hold or receive stock."""

    name: str
    kind: str  # "warehouse" or "store"
    storage_capacity: int = 10_000  # max units storable


@dataclass(frozen=True)
class TransportLane:
    """A transport lane between two locations."""

    source: str
    destination: str
    transit_days: int
    cost_per_unit: float = 0.0  # transport cost units per unit moved


@dataclass(frozen=True)
class ForecastPoint:
    """Forecast demand for one future day."""

    date: str
    quantity: float


@dataclass(frozen=True)
class AtRiskBatch:
    """A batch classified as at risk of expiring before being sold."""

    batch: SKU_BATCH
    days_to_expiry: int
    expected_demand_before_expiry: float
    at_risk_units: int
    risk_ratio: float  # at_risk / quantity, 0..1
    reason: str


@dataclass(frozen=True)
class CandidateDestination:
    """Why a destination is (or is not) a good home for at-risk stock."""

    location: str
    daily_demand: float
    expected_demand_until_batch_expiry: float
    current_stock: int
    capacity_headroom: int
    transit_days: int
    cost_per_unit: float
    score: float
    notes: str = ""


@dataclass(frozen=True)
class Transfer:
    """One recommended transfer of one batch (or part of it)."""

    sku: str
    batch_id: str
    source: str
    destination: str
    quantity: int
    expiry_date: str
    transit_days: int
    transport_cost: float
    explanation: str


@dataclass
class TransferPlan:
    """The full output of one pipeline run."""

    transfers: list[Transfer] = field(default_factory=list)
    at_risk_batches: list[AtRiskBatch] = field(default_factory=list)
    candidates: dict[tuple[str, str], list[CandidateDestination]] = field(
        default_factory=dict
    )  # (sku, batch_id) -> ranked destinations
    total_transport_cost: float = 0.0
    units_rescued: int = 0
    writeoff_value_avoided: float = 0.0
    unassigned_units: int = 0
    notes: list[str] = field(default_factory=list)
