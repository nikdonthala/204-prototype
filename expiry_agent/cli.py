"""Command-line interface.

Usage:
    python -m expiry_agent.cli --data-dir ./data --today 2026-09-10
    python -m expiry_agent.cli --generate-sample ./data   # creates demo CSVs first
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from expiry_agent.data_io import (
    load_inventory,
    load_locations,
    load_sales,
    load_transport,
)
from expiry_agent.models import TransferPlan
from expiry_agent.pipeline import run_pipeline


def _print_plan(plan: TransferPlan) -> None:
    print("=" * 78)
    print("EXPIRY RISK & REDISTRIBUTION - RECOMMENDATION REPORT")
    print("=" * 78)

    print(f"\nAt-risk batches: {len(plan.at_risk_batches)}")
    for a in plan.at_risk_batches:
        print(
            f"  - {a.batch.sku} @ {a.batch.location} (batch {a.batch.batch_id}): "
            f"{a.at_risk_units}/{a.batch.quantity} units at risk, "
            f"expires {a.batch.expiry_date} ({a.days_to_expiry}d)"
        )

    print(f"\nRecommended transfers: {len(plan.transfers)}")
    for i, t in enumerate(plan.transfers, 1):
        print(f"\n#{i}  {t.quantity} x {t.sku}  {t.source} -> {t.destination}")
        print(f"    batch {t.batch_id} | expires {t.expiry_date} | "
              f"transit {t.transit_days}d | cost {t.transport_cost:.2f}")
        print(f"    WHY: {t.explanation}")

    print("\n" + "-" * 78)
    for note in plan.notes:
        print(f"* {note}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="expiry-agent",
        description="Predict expiry risk and recommend inventory transfers.",
    )
    parser.add_argument("--data-dir", default="data",
                        help="directory containing inventory.csv, sales.csv, "
                             "locations.csv, transport.csv")
    parser.add_argument("--today", default=None,
                        help="reference date, YYYY-MM-DD (default: today)")
    parser.add_argument("--forecaster", default="moving_average",
                        choices=["moving_average", "exp_smoothing"],
                        help="demand forecasting method")
    parser.add_argument("--safety-factor", type=float, default=1.0,
                        help=">1 conservative demand forecast, <1 aggressive")
    parser.add_argument("--rescue-value", type=float, default=10.0,
                        help="value per rescued unit used by the optimizer")
    parser.add_argument("--generate-sample", metavar="DIR", default=None,
                        help="write demo CSVs to DIR and exit")
    parser.add_argument("--json", action="store_true",
                        help="print plan as JSON instead of text")
    args = parser.parse_args(argv)

    if args.generate_sample:
        from expiry_agent.sample_data import generate_sample
        generate_sample(args.generate_sample)
        print(f"Sample data written to {args.generate_sample}/")
        return 0

    today = (
        datetime.strptime(args.today, "%Y-%m-%d").date()
        if args.today else date.today()
    )
    data_dir = Path(args.data_dir)
    try:
        batches = load_inventory(data_dir / "inventory.csv")
        sales = load_sales(data_dir / "sales.csv")
        locations = load_locations(data_dir / "locations.csv")
        lanes = load_transport(data_dir / "transport.csv")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    plan = run_pipeline(
        batches=batches, sales=sales, locations=locations, lanes=lanes,
        today=today, forecaster=args.forecaster,
        safety_factor=args.safety_factor,
        rescue_value_per_unit=args.rescue_value,
    )

    if args.json:
        import json
        from dataclasses import asdict
        d = asdict(plan)
        # tuple keys aren't JSON-serializable: flatten candidates to a list
        flat = d.pop("candidates")
        d["candidates"] = [
            {"sku": sku, "batch_id": batch_id, "destinations": cands}
            for (sku, batch_id), cands in flat.items()
        ]
        print(json.dumps(d, indent=2))
    else:
        _print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
