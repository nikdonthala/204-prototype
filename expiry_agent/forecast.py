"""Demand forecasting: moving average and exponential smoothing.

Both forecasters take an ordered list of SalesRecord (one SKU/location),
which may contain gaps (days with zero sales are simply missing). They
return a daily-average demand over a horizon plus the first ForecastPoint
per day, so the risk module can integrate demand up to an expiry date.

Design goal for the MVP: simple, explainable baselines. Prophet/XGBoost
can be swapped in behind the same `Forecast` protocol later.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import fmean

from expiry_agent.models import ForecastPoint, SalesRecord


def _daily_series(records: list[SalesRecord], end_date: date) -> list[float]:
    """Expand sparse sales records into a dense daily series ending at end_date.

    Days without a sales record count as zero-demand days. The series length
    is capped so long gaps before the first sale don't dominate.
    """
    if not records:
        return []
    by_date = {r.date: r.quantity for r in records}
    dates = sorted(by_date)
    first = datetime.strptime(dates[0], "%Y-%m-%d").date()
    # Cap history at 120 days to keep old gaps from washing out recent signal.
    start = max(first, end_date - timedelta(days=119))
    series = []
    d = start
    while d <= end_date:
        series.append(float(by_date.get(d.isoformat(), 0)))
        d += timedelta(days=1)
    return series


def moving_average(
    records: list[SalesRecord], end_date: date, window: int = 14
) -> tuple[float, list[ForecastPoint]]:
    """Flat forecast at the mean daily demand of the last `window` days."""
    series = _daily_series(records, end_date)
    recent = series[-window:] if series else []
    daily = fmean(recent) if recent else 0.0
    return daily, []


def exponential_smoothing(
    records: list[SalesRecord], end_date: date, alpha: float = 0.3
) -> tuple[float, list[ForecastPoint]]:
    """Flat forecast via simple exponential smoothing of daily demand."""
    series = _daily_series(records, end_date)
    if not series:
        return 0.0, []
    level = series[0]
    for x in series[1:]:
        level = alpha * x + (1 - alpha) * level
    return level, []


FORECASTERS = {
    "moving_average": moving_average,
    "exp_smoothing": exponential_smoothing,
}


def demand_until(
    daily_demand: float,
    start_date: date,
    end_date: date,
    lead_days: int = 0,
) -> float:
    """Expected demand between start_date (inclusive) and end_date (exclusive).

    The expiry day itself is not counted as sellable - a conservative
    choice that slightly understates demand and flags stock earlier.

    `lead_days` discounts demand during transit: stock arriving at a
    destination is only sellable after it lands, so the first `lead_days`
    of the destination's demand cannot be served by this batch.
    """
    days = (end_date - start_date).days
    if days <= 0:
        return 0.0
    sellable_days = max(days - lead_days, 0)
    return daily_demand * sellable_days
