from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market import (
    average_true_range,
    exponential_moving_average,
    percentage_returns,
    relative_strength_index,
    simple_moving_average,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar


def make_bars(
    closes: list[str],
    *,
    symbol: str = "FPT",
    source: str = "fixture",
    availability_delay_hours: int = 1,
) -> list[MarketBar]:
    start = datetime(2026, 1, 1, 15, tzinfo=UTC)
    bars = []
    for index, raw_close in enumerate(closes):
        close = Decimal(raw_close)
        timestamp = start + timedelta(days=index)
        bars.append(
            MarketBar(
                symbol=symbol,
                timestamp=timestamp,
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                volume=1000 + index,
                source=source,
                available_at=timestamp + timedelta(hours=availability_delay_hours),
            )
        )
    return bars


def test_sma_uses_rolling_windows_and_original_price_units():
    points = simple_moving_average(make_bars(["10", "12", "14", "13", "15"]), 3)
    assert [point.value for point in points] == [Decimal(12), Decimal(13), Decimal(14)]
    assert points[0].timestamp == datetime(2026, 1, 3, 15, tzinfo=UTC)


def test_ema_uses_sma_seed_then_standard_alpha():
    points = exponential_moving_average(make_bars(["10", "12", "14", "13", "15"]), 3)
    assert [point.value for point in points] == [
        Decimal(12),
        Decimal("12.5"),
        Decimal("13.75"),
    ]


def test_rsi_uses_wilder_smoothing():
    points = relative_strength_index(make_bars(["10", "12", "11", "13"]), period=2)
    assert points[0].value == Decimal(100) - Decimal(100) / Decimal(3)
    assert points[1].value == Decimal(100) - Decimal(100) / Decimal(7)


def test_rsi_handles_flat_prices_without_nan():
    points = relative_strength_index(make_bars(["10", "10", "10"]), period=2)
    assert points[0].value == Decimal(50)


def test_atr_uses_previous_close_for_true_range():
    points = average_true_range(make_bars(["10", "12", "11", "13"]), period=2)
    assert [point.value for point in points] == [Decimal("2.5"), Decimal("2.75")]


def test_percentage_returns_are_percent_not_fraction():
    points = percentage_returns(make_bars(["100", "110", "99"]))
    assert points[0].value == Decimal(10)
    assert points[1].value == Decimal(-10)


def test_period_requires_positive_non_boolean_integer():
    bars = make_bars(["10", "11", "12"])
    for period in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            simple_moving_average(bars, period)


def test_short_series_returns_no_partial_indicator_values():
    bars = make_bars(["10", "11"])
    assert simple_moving_average(bars, 3) == []
    assert exponential_moving_average(bars, 3) == []
    assert relative_strength_index(bars, 2) == []
    assert average_true_range(bars, 2) == []


def test_series_rejects_mixed_symbols_sources_and_out_of_order_bars():
    bars = make_bars(["10", "11", "12"])
    with pytest.raises(ValueError, match="same symbol"):
        simple_moving_average([bars[0], make_bars(["11"], symbol="VIC")[0]], 1)
    with pytest.raises(ValueError, match="same data source"):
        simple_moving_average([bars[0], make_bars(["11"], source="ssi")[0]], 1)
    with pytest.raises(ValueError, match="strictly ordered"):
        simple_moving_average([bars[1], bars[0]], 1)


def test_availability_propagates_conservatively():
    bars = make_bars(["10", "12", "13"])
    late_availability = bars[0].timestamp + timedelta(days=2, hours=1)
    bars[0] = MarketBar(
        symbol=bars[0].symbol,
        timestamp=bars[0].timestamp,
        open=bars[0].open,
        high=bars[0].high,
        low=bars[0].low,
        close=bars[0].close,
        volume=bars[0].volume,
        source=bars[0].source,
        available_at=late_availability,
    )
    assert simple_moving_average(bars, 2)[0].available_at == late_availability
    assert exponential_moving_average(bars, 2)[-1].available_at == late_availability


def test_flat_return_and_empty_input():
    assert percentage_returns(make_bars(["5", "5"]))[0].value == 0
    assert percentage_returns([]) == []
