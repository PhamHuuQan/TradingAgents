"""Tests for source-neutral Vietnam market data contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.models import (
    MarketBar,
    MarketDataValidationError,
)


def valid_bar(**overrides):
    values = {
        "symbol": " fpt ",
        "timestamp": datetime(2026, 10, 23, 9, 0, tzinfo=UTC),
        "open": Decimal("100.0"),
        "high": Decimal("105.0"),
        "low": Decimal("98.0"),
        "close": Decimal("103.0"),
        "volume": 120000,
        "source": "  example-fixture  ",
        "available_at": datetime(2026, 10, 23, 9, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return MarketBar(**values)


def test_normalizes_symbol_and_source_without_losing_provenance():
    bar = valid_bar()
    assert bar.symbol == "FPT"
    assert bar.source == "example-fixture"
    assert bar.available_at > bar.timestamp


@pytest.mark.parametrize("field", ["timestamp", "available_at"])
def test_rejects_naive_timestamps(field):
    with pytest.raises(MarketDataValidationError, match="timezone-aware"):
        valid_bar(**{field: datetime(2026, 10, 23, 9, 0)})


def test_rejects_data_that_was_not_available_at_bar_time():
    with pytest.raises(MarketDataValidationError, match="cannot precede"):
        valid_bar(available_at=datetime(2026, 10, 23, 8, 59, tzinfo=UTC))


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_rejects_float_prices(field):
    with pytest.raises(MarketDataValidationError, match="must be Decimal"):
        valid_bar(**{field: 100.0})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", Decimal("0")),
        ("close", Decimal("-1")),
        ("high", Decimal("NaN")),
        ("low", Decimal("Infinity")),
    ],
)
def test_rejects_non_positive_or_non_finite_prices(field, value):
    with pytest.raises(MarketDataValidationError):
        valid_bar(**{field: value})


def test_rejects_impossible_ohlc_relationships():
    with pytest.raises(MarketDataValidationError, match="high"):
        valid_bar(high=Decimal("101"), close=Decimal("103"))
    with pytest.raises(MarketDataValidationError, match="low"):
        valid_bar(low=Decimal("104"))


@pytest.mark.parametrize("volume", [-1, 1.5, True])
def test_rejects_invalid_volume(volume):
    with pytest.raises(MarketDataValidationError, match="volume"):
        valid_bar(volume=volume)


@pytest.mark.parametrize("symbol", ["", "../FPT", "FPT.VN", "A B", "TOO-LONG-SYMBOL"])
def test_rejects_non_canonical_vendor_symbols(symbol):
    with pytest.raises(MarketDataValidationError, match="symbol"):
        valid_bar(symbol=symbol)


def test_rejects_missing_source():
    with pytest.raises(MarketDataValidationError, match="source"):
        valid_bar(source="  ")
