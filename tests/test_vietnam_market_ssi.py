"""Unit tests for the SSI market-data adapter using deterministic fixtures."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows.vietnam_market.ssi import SSIAdapterError, SSIMarketDataProvider

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class FakeSSI:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_ohlc_all(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        return self.rows


def row(day="2026/10/23"):
    return {
        "trading_date": day,
        "open_price": "100.0",
        "high_price": "105.0",
        "low_price": "98.0",
        "close_price": "103.0",
        "volume": 120000,
    }


def provider(rows=None):
    client = FakeSSI(rows if rows is not None else [row()])
    return SSIMarketDataProvider(client), client


def available_at(day=date(2026, 10, 23)):
    return datetime(day.year, day.month, day.day, 15, 5, tzinfo=TZ)


def test_maps_ssi_daily_ohlc_to_canonical_market_bar():
    adapter, client = provider()
    bars = adapter.get_daily_bars(
        " fpt ",
        date(2026, 10, 23),
        date(2026, 10, 23),
        available_at_by_date={date(2026, 10, 23): available_at()},
    )

    assert len(bars) == 1
    bar = bars[0]
    assert bar.symbol == "FPT"
    assert bar.open == Decimal("100.0")
    assert bar.high == Decimal("105.0")
    assert bar.low == Decimal("98.0")
    assert bar.close == Decimal("103.0")
    assert bar.volume == 120000
    assert bar.source == "ssi-fastconnect-v3"
    assert bar.timestamp == datetime(2026, 10, 23, 15, 0, tzinfo=TZ)
    assert bar.available_at == available_at()
    assert client.calls[0][1] == "1d"
    assert client.calls[0][2]["ascending"] is True


def test_filters_rows_outside_requested_date_range():
    adapter, _ = provider([row("2026/10/22"), row("2026/10/23"), row("2026/10/24")])
    bars = adapter.get_daily_bars(
        "FPT",
        date(2026, 10, 23),
        date(2026, 10, 23),
        available_at_by_date={date(2026, 10, 23): available_at()},
    )
    assert [bar.timestamp.date() for bar in bars] == [date(2026, 10, 23)]


def test_requires_verified_availability_time():
    adapter, _ = provider()
    with pytest.raises(SSIAdapterError, match="Missing verified availability"):
        adapter.get_daily_bars("FPT", date(2026, 10, 23), date(2026, 10, 23), available_at_by_date={})


def test_rejects_naive_availability_time():
    adapter, _ = provider()
    with pytest.raises(SSIAdapterError, match="timezone-aware"):
        adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={date(2026, 10, 23): datetime(2026, 10, 23, 15, 5)},
        )


def test_rejects_duplicate_daily_rows():
    adapter, _ = provider([row(), row()])
    with pytest.raises(SSIAdapterError, match="Duplicate"):
        adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={date(2026, 10, 23): available_at()},
        )


def test_rejects_missing_ohlc_fields():
    adapter, _ = provider([{"trading_date": "2026/10/23"}])
    with pytest.raises(SSIAdapterError, match="missing required field"):
        adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={date(2026, 10, 23): available_at()},
        )


def test_rejects_availability_before_daily_bar_close():
    adapter, _ = provider()
    with pytest.raises(SSIAdapterError, match="precedes"):
        adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={
                date(2026, 10, 23): datetime(2026, 10, 23, 14, 59, tzinfo=TZ)
            },
        )


def test_rejects_invalid_date_range_and_page_size():
    adapter, _ = provider()
    with pytest.raises(ValueError, match="from_date"):
        adapter.get_daily_bars(
            "FPT", date(2026, 10, 24), date(2026, 10, 23), available_at_by_date={}
        )
    with pytest.raises(ValueError, match="page_size"):
        adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={},
            page_size=1001,
        )
