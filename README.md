# Expiry Risk & Redistribution Agent

An AI-powered decision-support agent that **predicts which inventory will expire before it can be sold** and **recommends optimal transfers** of that at-risk stock to locations where forecast demand can absorb it before expiry.

> Core idea: instead of alerting users when expiry is *approaching*, predict expiry *risk* early and decide **where the stock should move, how much, and why**.

## How it works

```
Inventory Data ──► Demand Forecast ──► Expiry Risk ──► Candidate
                                                    Destinations
                                                          │
Impact Report ◄── Explained Recommendations ◄── Transfer Optimization
                                              (OR-Tools LP)
```

1. **Demand forecasting** — moving average or exponential smoothing over daily sales history (per SKU per location). Designed so Prophet/XGBoost can be swapped in behind the same interface.
2. **Expiry risk** — `At-Risk Stock = Current Stock − Expected Demand Before Expiry`, computed per batch with **FEFO demand pooling**: earlier-expiring batches of the same SKU at a location consume local demand first.
3. **Destination ranking** — scores every reachable location on unserved forecast demand before the batch's expiry, capacity headroom, transit days, and transport cost. Infeasible lanes (transit arrives after expiry) are excluded.
4. **Transfer optimization** — a linear program (Google OR-Tools) maximizes *rescue value − transport cost* subject to:
   - **supply**: cannot ship more than a batch's at-risk units,
   - **demand (FEFO covering)**: units arriving at a destination before any expiry threshold cannot exceed unserved forecast demand before it,
   - **capacity**: cannot exceed destination storage headroom.
   A greedy fallback runs if the solver is unavailable, so the agent degrades gracefully.
5. **Explained recommendations** — every transfer carries a one-sentence business justification (surplus at source, unserved demand at destination, transit, cost, write-off value avoided).

## Quick start

### Local CLI

```bash
pip install -e ".[dev]"

# generate demo CSVs, then run the agent
python -m expiry_agent.cli --generate-sample data
python -m expiry_agent.cli --data-dir data --today 2026-09-10

# JSON output (for ERP/WMS integration)
python -m expiry_agent.cli --data-dir data --json
```

### Web dashboard (Vercel)

`GET /` serves an interactive dashboard (reference date, forecaster,
safety factor, rescue value) and `GET /api` returns the JSON plan:

```bash
vercel dev        # local: http://localhost:3000
vercel --prod     # deploy
```

The same serverless API runs on Vercel with zero config (`vercel.json`
routes everything to `api/index.py`).

Options: `--forecaster {moving_average,exp_smoothing}`, `--safety-factor` (demand-buffer tuning), `--rescue-value` (optimizer aggressiveness).

## Input data (CSV)

| File | Columns |
|---|---|
| `inventory.csv` | `sku, location, batch_id, expiry_date, quantity[, unit_cost]` |
| `sales.csv` | `sku, location, date, quantity` (daily) |
| `locations.csv` | `name, kind (warehouse\|store)[, storage_capacity]` |
| `transport.csv` | `source, destination, transit_days[, cost_per_unit]` |

The MVP starts from plain CSVs — the same schema an ERP/WMS export would provide.

## Demo scenario

Two warehouses, four stores. Warehouse **W1** over-ordered **SKU-A** (600 units expiring in 12 days, local demand only ~5/day) while store **S4** sells ~27/day but holds little. The agent flags the W1 surplus and recommends e.g.:

> *"Transfer 191 units of SKU-A from W1 → S4 because S4 has sufficient forecast demand before expiry and W1 has surplus inventory."*

Rescue decisions are **decision support**: the report is meant for human approval before any transfer is executed.

## Project layout

```
expiry_agent/
  models.py         # dataclasses: SKU_BATCH, AtRiskBatch, Transfer, TransferPlan, ...
  data_io.py        # CSV loading + validation
  forecast.py       # moving average / exponential smoothing, demand integration
  risk.py           # expiry-risk classification with FEFO demand pooling
  destinations.py   # destination scoring & ranking
  optimizer.py      # OR-Tools LP + greedy fallback
  pipeline.py       # orchestration + explanation generation
  cli.py            # text/JSON reports, sample-data generator
tests/              # 25 unit & end-to-end tests
```

## Extending the MVP

- **Stronger forecasting**: swap `FORECASTERS["moving_average"]` for Prophet/XGBoost (same signature: sales history + today → daily demand).
- **Real-time**: replace CSV loading with an ERP/WMS feed; keep the rest.
- **Multi-stop routing / vehicle constraints**: upgrade the LP to a MILP with the OR-Tools CP-SAT or routing solver.
- **Feedback loop**: log realized sell-through of transferred stock to recalibrate the forecaster.

## Research background

- Estrada-Moreno et al. (2019) — biased-randomized algorithm for redistribution of perishable food inventories in supermarket chains.
- Mallidis et al. (2020) — single-period inventory planning model for perishable product redistribution.
- Trapero et al. (2024) — demand forecasting under lost-sales stock policies.
- *Engineering Applications of AI* (2024) — MILP optimization for perishable products across states (cost, transport time, inventory, vehicle constraints).
- *Cleaner Logistics and Supply Chain* (2025) — stacking-ensemble food demand forecasting as a preventative waste-reduction approach.

## Tests

```bash
python -m pytest tests/ -v
```
