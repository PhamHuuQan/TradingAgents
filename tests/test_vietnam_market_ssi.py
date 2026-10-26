"""Unit tests for the SSI market-data adapter using deterministic fixtures."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import tradingagents.dataflows.vietnam_market.ssi as ssi_module
from tradingagents.dataflows.vietnam_market.ssi import (
    SSIAdapterError,
    SSIMarketDataProvider,
    authenticated_ssi_provider_from_env,
)

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
    timeframe = client.calls[0][1]
    assert getattr(timeframe, "value", timeframe) in ("1d", "DAY_1")
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



@pytest.mark.parametrize("volume", [-1, 1.5, "bad"])
def test_rejects_invalid_volume_instead_of_silently_truncating(volume):
    bad_row = row()
    bad_row["volume"] = volume
    adapter, _ = provider([bad_row])
    with pytest.raises(SSIAdapterError, match="volume"):
        adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={date(2026, 10, 23): available_at()},
        )



class FakeHTTPResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeHTTPSession:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        self.closed = True

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeHTTPResponse(200, {"accessToken": "token-for-test"})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeHTTPResponse(
            200,
            {
                "pageIndex": 1,
                "pageSize": 100,
                "data": [
                    {
                        "symbol": "FPT",
                        "tradingDate": "2026/10/23",
                        "open": "100",
                        "high": "105",
                        "low": "98",
                        "close": "103",
                        "volume": "120000",
                    }
                ],
            },
        )


def test_rest_auth_and_ohlc_use_documented_api_without_client_id(monkeypatch):
    monkeypatch.setenv("SSI_API_KEY", "test-api-key")
    monkeypatch.setenv("SSI_API_SECRET", "test-api-secret")
    monkeypatch.delenv("SSI_CLIENT_ID", raising=False)
    session = FakeHTTPSession()
    monkeypatch.setattr(ssi_module.requests, "Session", lambda: session)

    with authenticated_ssi_provider_from_env() as adapter:
        bars = adapter.get_daily_bars(
            "FPT",
            date(2026, 10, 23),
            date(2026, 10, 23),
            available_at_by_date={date(2026, 10, 23): available_at()},
            page_size=100,
        )

    assert len(bars) == 1
    assert bars[0].close == Decimal("103")
    token_url, token_kwargs = session.posts[0]
    assert token_url == "https://api.ssi.com.vn/api/v3/auth/token"
    assert token_kwargs["json"] == {
        "apiKey": "test-api-key",
        "apiSecret": "test-api-secret",
    }
    ohlc_url, ohlc_kwargs = session.gets[0]
    assert ohlc_url == "https://api.ssi.com.vn/api/v3/data/ohlc"
    assert ohlc_kwargs["headers"]["Authorization"] == "Bearer token-for-test"
    assert ohlc_kwargs["params"] == {
        "symbol": "FPT",
        "from": "2026/10/23 00:00:00",
        "to": "2026/10/23 23:59:59",
        "timeFrame": "1d",
        "pageIndex": 1,
        "pageSize": 100,
    }
    assert session.closed is True


def test_rest_auth_failure_reports_status_without_response_body(monkeypatch):
    monkeypatch.setenv("SSI_API_KEY", "test-api-key")
    monkeypatch.setenv("SSI_API_SECRET", "test-api-secret")

    class FailedSession(FakeHTTPSession):
        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeHTTPResponse(403, {"msg": "secret should never appear"})

    session = FailedSession()
    monkeypatch.setattr(ssi_module.requests, "Session", lambda: session)

    with pytest.raises(RuntimeError, match="HTTP 403") as exc_info:
        with authenticated_ssi_provider_from_env():
            pass
    assert "secret should never appear" not in str(exc_info.value)
    assert session.closed is True
