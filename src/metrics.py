"""Deterministic quantitative helpers used by strategic analysis."""

from __future__ import annotations

from src.strategy_models import ComputedGrowth, MarketSeries


def calculate_cagr(
    start_value: float,
    end_value: float,
    periods: int,
) -> float:
    """Return CAGR as a percentage, e.g. 10.0 means ten percent."""

    if start_value <= 0:
        raise ValueError("start_value must be positive")
    if end_value < 0:
        raise ValueError("end_value must not be negative")
    if periods <= 0:
        raise ValueError("periods must be positive")
    return round(((end_value / start_value) ** (1 / periods) - 1) * 100, 4)


def calculate_yoy(previous_value: float, current_value: float) -> float:
    """Return year-over-year growth as a percentage."""

    if previous_value <= 0:
        raise ValueError("previous_value must be positive")
    if current_value < 0:
        raise ValueError("current_value must not be negative")
    return round((current_value / previous_value - 1) * 100, 4)


def compute_market_series_growth(series: MarketSeries) -> ComputedGrowth:
    first = series.points[0]
    last = series.points[-1]
    periods = last.year - first.year
    return ComputedGrowth(
        start_year=first.year,
        end_year=last.year,
        start_value=first.value,
        end_value=last.value,
        cagr_percent=calculate_cagr(first.value, last.value, periods),
    )
