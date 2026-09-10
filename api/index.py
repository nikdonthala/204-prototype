"""Vercel serverless entry point.

GET /              -> interactive dashboard (HTML)
GET /api           -> JSON plan on the demo dataset
GET /api?today=YYYY-MM-DD[&forecaster=...][&safety_factor=...]
GET /api?health=1  -> liveness probe
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime

from expiry_agent.models import TransferPlan
from expiry_agent.pipeline import run_pipeline
from expiry_agent.sample_data import build_sample


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


def handler(event, context):  # noqa: ANN001 (Vercel signature)
    path = (event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"

    # ---- API ----
    if path.endswith("/api") or path.endswith("/api/"):
        try:
            if event.get("isBase64Encoded"):
                pass  # GET requests have no body; nothing to decode
            params = event.get("queryStringParameters") or {}

            if str(params.get("health") or "") in ("1", "true"):
                body, status = {"status": "ok"}, 200
            else:
                plan, meta = _plan_from_query(params)
                d = asdict(plan)
                flat = d.pop("candidates")
                d["candidates"] = [
                    {"sku": sku, "batch_id": bid, "destinations": cands}
                    for (sku, bid), cands in flat.items()
                ]
                d["query"] = meta
                body, status = d, 200
        except ValueError as exc:
            body, status = {"error": str(exc)}, 400
        except Exception as exc:  # pragma: no cover - defensive
            body, status = {"error": f"internal error: {exc}"}, 500

        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(body, indent=2),
        }

    # ---- Dashboard ----
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": _DASHBOARD_HTML,
    }


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>204 Prototype — Expiry Risk &amp; Redistribution Agent</title>
<style>
  :root { --bg:#0b1220; --card:#121b2e; --line:#22304d; --ink:#e8eefc;
          --mut:#8fa3c8; --acc:#4da3ff; --ok:#39c98e; --warn:#ffb84d; --bad:#ff6b6b; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--ink);
         font:15px/1.55 system-ui, Segoe UI, Roboto, sans-serif; }
  .wrap { max-width:1080px; margin:0 auto; padding:28px 20px 60px; }
  h1 { font-size:26px; letter-spacing:.2px; }
  .sub { color:var(--mut); margin:6px 0 22px; }
  .flow { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:22px; }
  .flow span { background:var(--card); border:1px solid var(--line);
               border-radius:99px; padding:6px 14px; font-size:13px; color:var(--mut); }
  .flow b { color:var(--acc); font-weight:600; }
  .bar { display:flex; flex-wrap:wrap; gap:10px; align-items:end; margin-bottom:20px; }
  .bar label { display:flex; flex-direction:column; gap:4px; font-size:12px;
               color:var(--mut); }
  .bar input, .bar select { background:var(--card); color:var(--ink);
               border:1px solid var(--line); border-radius:8px; padding:8px 10px;
               min-width:140px; font-size:14px; }
  button { background:var(--acc); color:#06111f; border:0; font-weight:700;
           border-radius:8px; padding:10px 18px; cursor:pointer; font-size:14px; }
  button[disabled] { opacity:.6; cursor:wait; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
           gap:12px; margin-bottom:22px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:14px 16px; }
  .card .k { color:var(--mut); font-size:12px; text-transform:uppercase;
             letter-spacing:.6px; }
  .card .v { font-size:24px; font-weight:700; margin-top:2px; }
  .card .v.ok { color:var(--ok); } .card .v.warn { color:var(--warn); }
  .t { background:var(--card); border:1px solid var(--line); border-radius:12px;
       padding:14px 16px; margin-bottom:10px; }
  .t .route { font-weight:700; }
  .t .route .arrow { color:var(--acc); }
  .t .why { color:var(--mut); font-size:13.5px; margin-top:6px; }
  .pill { display:inline-block; border-radius:99px; padding:2px 10px;
          font-size:12px; margin-left:8px; vertical-align:middle; }
  .p-urg { background:#3a2430; color:var(--bad); }
  .p-soon { background:#3a3224; color:var(--warn); }
  .p-later { background:#1e3a2f; color:var(--ok); }
  .risk { margin-top:18px; }
  .risk h2, .t h3 { font-size:14px; letter-spacing:.4px; color:var(--mut);
        text-transform:uppercase; margin-bottom:8px; }
  .risk .r { display:flex; justify-content:space-between; gap:10px;
             border-bottom:1px dashed var(--line); padding:6px 2px; font-size:14px; }
  .risk .r:last-child { border-bottom:0; }
  .risk .r .q { color:var(--warn); font-weight:600; white-space:nowrap; }
  .err { background:#3a1f24; border:1px solid #632; color:var(--bad);
         border-radius:10px; padding:12px 14px; margin:10px 0; }
  footer { color:var(--mut); font-size:12.5px; margin-top:34px; }
  a { color:var(--acc); }
</style>
</head>
<body>
<div class="wrap">
  <h1>204 Prototype — Expiry Risk &amp; Redistribution Agent</h1>
  <p class="sub">Predicts inventory likely to expire, then recommends where to
     move it so it sells before expiry. Decision support — a human approves
     every transfer.</p>
  <div class="flow">
    <span><b>1</b> Inventory data</span><span>→</span>
    <span><b>2</b> Demand forecast</span><span>→</span>
    <span><b>3</b> Expiry risk</span><span>→</span>
    <span><b>4</b> Best destinations</span><span>→</span>
    <span><b>5</b> Optimize transfer</span><span>→</span>
    <span><b>6</b> Recommendation + why</span>
  </div>
  <div class="bar">
    <label>Reference date
      <input id="today" type="date"></label>
    <label>Forecaster
      <select id="forecaster">
        <option value="moving_average">Moving average</option>
        <option value="exp_smoothing">Exponential smoothing</option>
      </select></label>
    <label>Safety factor (0.1–10)
      <input id="safety" type="number" step="0.1" min="0.1" max="10" value="1"></label>
    <label>Rescue value / unit
      <input id="rescue" type="number" step="1" min="0" max="1000" value="10"></label>
    <button id="go">Run agent</button>
  </div>
  <div id="out"><p class="sub">Loading demo scenario…</p></div>
  <footer>API: <a id="apiLink" href="/api">/api</a> ·
    Demo dataset: 2 warehouses, 4 stores, SKU-A over-stocked at W1 ·
    Solver: OR-Tools LP (greedy fallback)</footer>
</div>
<script>
const $ = id => document.getElementById(id);
function pill(dte) {
  if (dte <= 7)  return '<span class="pill p-urg">' + dte + 'd left</span>';
  if (dte <= 21) return '<span class="pill p-soon">' + dte + 'd left</span>';
  return '<span class="pill p-later">' + dte + 'd left</span>';
}
async function run() {
  const btn = $('go'); btn.disabled = true;
  const q = new URLSearchParams();
  if ($('today').value) q.set('today', $('today').value);
  q.set('forecaster', $('forecaster').value);
  q.set('safety_factor', $('safety').value);
  q.set('rescue_value', $('rescue').value);
  try {
    const res = await fetch('/api?' + q.toString());
    const d = await res.json();
    if (!res.ok) { $('out').innerHTML = '<div class="err">' + d.error + '</div>'; return; }
    const t = d.transfers || [];
    let html = '';
    html += '<div class="cards">'
      + card('Units rescued', d.units_rescued, 'ok')
      + card('Transfers', t.length)
      + card('Transport cost', (d.total_transport_cost||0).toFixed(2))
      + card('Write-off avoided', '≈' + Math.round(d.writeoff_value_avoided||0))
      + card('Units still exposed', d.unassigned_units||0,
             (d.unassigned_units||0) > 0 ? 'warn' : '')
      + '</div>';
    if (t.length === 0) {
      html += '<div class="t">No transfers needed — local demand covers all stock before expiry.</div>';
    }
    for (const x of t) {
      const dte = Math.round((new Date(x.expiry_date) - new Date(d.query.today)) / 86400000);
      html += '<div class="t"><div class="route">' + x.quantity + ' × ' + x.sku
        + ' &nbsp;' + x.source + ' <span class="arrow">→</span> ' + x.destination
        + pill(dte) + '</div>'
        + '<div class="why">' + x.explanation + '</div>'
        + '<div class="why">batch ' + x.batch_id + ' · transit ' + x.transit_days
        + 'd · cost ' + x.transport_cost.toFixed(2) + '</div></div>';
    }
    html += '<div class="risk"><h2>At-risk batches</h2>';
    for (const a of d.at_risk_batches || []) {
      html += '<div class="r"><span>' + a.batch.sku + ' @ ' + a.batch.location
        + ' · batch ' + a.batch.batch_id + ' · expires ' + a.batch.expiry_date
        + '</span><span class="q">' + a.at_risk_units + '/' + a.batch.quantity
        + ' at risk</span></div>';
    }
    html += '</div>';
    $('out').innerHTML = html;
  } catch (e) {
    $('out').innerHTML = '<div class="err">Request failed: ' + e + '</div>';
  }
}
function card(k, v, cls) {
  return '<div class="card"><div class="k">' + k + '</div><div class="v '
    + (cls||'') + '">' + v + '</div></div>';
}
$('go').onclick = run;
$('apiLink').href = '/api';
$('today').value = new Date().toISOString().slice(0,10);
run();
</script>
</body>
</html>
"""
