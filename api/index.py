"""Vercel serverless entry point (FastAPI/ASGI).

GET /            -> interactive dashboard (static file from public/)
GET /api         -> JSON plan on the demo dataset
GET /api?today=YYYY-MM-DD[&forecaster=...][&safety_factor=...][&rescue_value=...]
GET /api/health  -> liveness probe
"""

from __future__ import annotations

import os
import sys

# Ensure the project root (which contains expiry_agent/) is importable both
# locally and inside the Vercel serverless sandbox.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json
from dataclasses import asdict
from datetime import date, datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from expiry_agent.models import TransferPlan
from expiry_agent.pipeline import run_pipeline
from expiry_agent.sample_data import build_sample

app = FastAPI(title="204 Prototype - Expiry Risk & Redistribution Agent")


def _plan_from_query(params: dict) -> tuple[TransferPlan, dict]:
    today_raw = (params.get("today") or "").strip()
    if today_raw:
        try:
            today = datetime.strptime(today_raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("today must be YYYY-MM-DD") from exc
    else:
        today = date.today()

    forecaster = (params.get("forecaster") or "moving_average").strip()
    if forecaster not in ("moving_average", "exp_smoothing"):
        raise ValueError("forecaster must be moving_average or exp_smoothing")

    def _float(name: str, default: float, lo: float, hi: float) -> float:
        raw = (params.get(name) or "").strip()
        if not raw:
            return default
        value = float(raw)
        if not lo <= value <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return value

    safety = _float("safety_factor", 1.0, 0.1, 10.0)
    rescue = _float("rescue_value", 10.0, 0.0, 1000.0)

    batches, sales, locations, lanes = build_sample(today=today)
    plan = run_pipeline(
        batches, sales, locations, lanes,
        today=today, forecaster=forecaster,
        safety_factor=safety, rescue_value_per_unit=rescue,
    )
    meta = {"today": today.isoformat(), "forecaster": forecaster,
            "safety_factor": safety, "rescue_value": rescue}
    return plan, meta


def _plan_payload(plan: TransferPlan, meta: dict) -> dict:
    d = asdict(plan)
    flat = d.pop("candidates")  # tuple keys aren't JSON-serializable
    d["candidates"] = [
        {"sku": sku, "batch_id": bid, "destinations": cands}
        for (sku, bid), cands in flat.items()
    ]
    d["query"] = meta
    return d


@app.get("/api")
@app.get("/api/")
def api(request: Request):
    params = dict(request.query_params)

    if str(params.get("health") or "") in ("1", "true"):
        return JSONResponse({"status": "ok"})

    try:
        plan, meta = _plan_from_query(params)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse({"error": f"internal error: {exc}"}, status_code=500)

    return JSONResponse(
        _plan_payload(plan, meta),
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.get("/api/health")
def health():
    return JSONResponse({"status": "ok"})


@app.get("/api/index")
def api_index(request: Request):
    return api(request)


# Fallback for direct function hits (e.g. /api/index) that bypass the static
# dashboard: redirect clients to the homepage.
@app.get("/")
def root():
    return HTMLResponse(
        '<meta http-equiv="refresh" content="0; url=/index.html">',
        status_code=200,
    )
