"""Tests for expiry_agent.forecast."""

from __future__ import annotations

from datetime import date, timedelta

from expiry_agent.forecast import demand_until, exponential_smoothing, moving_average
from expiry_agent.models import SalesRecord


def _make_sales(base: float, days: int, end: date, noise: int = 0) -> list[SalesRecord]:
    import random
    rng = random.Random(7)
    out = []
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        qty = max(0, round(base + rng.uniform(-noise, noise)))
        out.append(SalesRecord(sku="X", location="L1", date=d.isoformat(),
                               quantity=qty))
    return out


def test_moving_average_flat_series():
    end = date(2026, 9, 10)
    sales = _make_sales(10, 30, end)
    daily, _ = moving_average(sales, end, window=14)
    assert abs(daily - 10.0) < 1e-6


def test_moving_average_ignores_old_history():
    end = date(2026, 9, 10)
    sales = [SalesRecord("X", "L1", (end - timedelta(days=60)).isoformat(), 100)]
    sales += _make_sales(5, 20, end)
    daily, _ = moving_average(sales, end, window=14)
    assert abs(daily - 5.0) < 1e-6  # the 100/day spike is outside the window


def test_exp_smoothing_constant_series():
    end = date(2026, 9, 10)
    sales = _make_sales(8, 30, end)
    daily, _ = exponential_smoothing(sales, end, alpha=0.5)
    assert abs(daily - 8.0) < 0.5


def test_no_sales_returns_zero():
    assert moving_average([], date(2026, 9, 10))[0] == 0.0
    assert exponential_smoothing([], date(2026, 9, 10))[0] == 0.0


def test_demand_until_with_lead_time():
    start = date(2026, 9, 10)
    end = date(2026, 9, 20)  # 10 sellable days (end exclusive)
    assert demand_until(2.0, start, end) == 20.0
    # 3 lead days: only 7 sellable days
    assert demand_until(2.0, start, end, lead_days=3) == 14.0
    # lead longer than horizon -> zero
    assert demand_until(2.0, start, end, lead_days=30) == 0.0
