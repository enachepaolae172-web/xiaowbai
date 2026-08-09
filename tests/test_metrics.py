import pytest

from src.metrics import calculate_cagr, calculate_yoy, compute_market_series_growth
from src.strategy_models import MarketDataPoint, MarketSeries


def point(year: int, value: float) -> MarketDataPoint:
    return MarketDataPoint(
        year=year,
        value=value,
        region="中国",
        unit="亿元",
        statistical_scope="同口径市场收入",
        source_id="S01",
    )


def test_calculate_cagr_returns_percentage() -> None:
    assert calculate_cagr(100, 121, 2) == pytest.approx(10.0)
    assert calculate_cagr(100, 0, 2) == -100.0


@pytest.mark.parametrize(
    ("start", "end", "periods"),
    [(0, 100, 2), (-1, 100, 2), (100, -1, 2), (100, 120, 0)],
)
def test_calculate_cagr_rejects_invalid_inputs(
    start: float,
    end: float,
    periods: int,
) -> None:
    with pytest.raises(ValueError):
        calculate_cagr(start, end, periods)


def test_calculate_yoy_returns_percentage() -> None:
    assert calculate_yoy(80, 100) == 25.0


def test_compute_market_series_growth_uses_first_and_last_year() -> None:
    series = MarketSeries(
        metric_name="市场规模",
        points=[point(2024, 100), point(2025, 120), point(2026, 144)],
    )

    growth = compute_market_series_growth(series)

    assert growth.start_year == 2024
    assert growth.end_year == 2026
    assert growth.cagr_percent == pytest.approx(20.0)
