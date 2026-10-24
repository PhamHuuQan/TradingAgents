import copy
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows import config as config_module, router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.vendors import ssi_market
from tradingagents.dataflows.vietnam_market.models import MarketBar
from tradingagents.default_config import DEFAULT_CONFIG

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = date(2026, 10, 25)
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=VN_TZ)


def _bars(start: date, end: date, available_at: datetime = NOW) -> list[MarketBar]:
    rows = []
    cursor = start
    index = 1
    while cursor <= end:
        close = Decimal(1000 + index)
        rows.append(MarketBar(
            symbol="FPT",
            timestamp=datetime.combine(cursor, time(15, 0), tzinfo=VN_TZ),
            open=close - Decimal(2),
            high=close + Decimal(3),
            low=close - Decimal(4),
            close=close,
            volume=1000 + index,
            source="ssi-fastconnect-v3",
            available_at=available_at,
        ))
        cursor += timedelta(days=1)
        index += 1
    return rows


class FakeProvider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_daily_bars(self, symbol, from_date, to_date, *, available_at_by_date, page_size=1000):
        self.calls.append((symbol, from_date, to_date, available_at_by_date, page_size))
        return [
            row for row in self.rows
            if from_date <= row.timestamp.date() <= to_date
        ]


@pytest.fixture
def configured_ssi(monkeypatch):
    monkeypatch.setattr(ssi_market, "_now_market", lambda: NOW)
    original_find_spec = ssi_market.importlib.util.find_spec
    monkeypatch.setattr(
        ssi_market.importlib.util,
        "find_spec",
        lambda name: object() if name == "ssi_sdk" else original_find_spec(name),
    )
    monkeypatch.setenv("SSI_CLIENT_ID", "test-client")
    monkeypatch.setenv("SSI_API_KEY", "test-key")
    monkeypatch.setenv("SSI_API_SECRET", "test-secret")


def _install_fake_provider(monkeypatch, provider):
    @contextmanager
    def fake_context():
        yield provider
    monkeypatch.setattr(ssi_market, "authenticated_ssi_provider_from_env", fake_context)


@pytest.mark.unit
def test_ssi_vendor_emits_csv_with_explicit_fetch_time_warning(monkeypatch, configured_ssi):
    provider = FakeProvider(_bars(date(2026, 10, 1), AS_OF))
    _install_fake_provider(monkeypatch, provider)

    result = ssi_market.get_ssi_stock_data("FPT", "2026-10-01", "2026-10-25")

    assert "# SSI FastConnect V3 read-only OHLCV for FPT" in result
    assert "# Retrieved at: 2026-10-25T20:00:00+07:00" in result
    assert "not point-in-time-safe for backtesting" in result
    assert "Date,Open,High,Low,Close,Volume" in result
    # Synthetic fixture has one row per calendar day, so 25 October is row 25.
    assert "2026-10-25,1023,1028,1021,1025,1025" in result


@pytest.mark.unit
def test_ssi_vendor_refuses_historical_as_of_date_before_network_or_auth(
    monkeypatch, configured_ssi
):
    called = False

    @contextmanager
    def forbidden_context():
        nonlocal called
        called = True
        yield object()

    monkeypatch.setattr(ssi_market, "authenticated_ssi_provider_from_env", forbidden_context)
    with pytest.raises(VendorUnavailableError, match="current-date only"):
        ssi_market.get_ssi_stock_data("FPT", "2026-09-01", "2026-10-24")
    assert called is False


@pytest.mark.unit
def test_ssi_vendor_requires_credentials_only_when_selected(monkeypatch):
    for name in ("SSI_CLIENT_ID", "SSI_API_KEY", "SSI_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ssi_market, "_now_market", lambda: NOW)
    with pytest.raises(VendorNotConfiguredError, match="missing"):
        ssi_market.get_ssi_stock_data("FPT", "2026-10-01", "2026-10-25")


@pytest.mark.unit
def test_ssi_indicators_use_same_source_and_return_200_sma(monkeypatch, configured_ssi):
    provider = FakeProvider(_bars(date(2025, 8, 1), AS_OF))
    _install_fake_provider(monkeypatch, provider)
    result = ssi_market.get_ssi_indicators("FPT", "close_200_sma", "2026-10-25", 5)

    assert "# SSI FastConnect V3 indicator close_200_sma" in result
    assert "fetch-time availability only" in result
    assert "2026-10-25" in result
    assert len(provider.calls) == 1
    assert provider.calls[0][0] == "FPT"


@pytest.mark.unit
def test_ssi_snapshot_uses_ssi_prices_and_indicators(monkeypatch, configured_ssi):
    provider = FakeProvider(_bars(date(2025, 8, 1), AS_OF))
    _install_fake_provider(monkeypatch, provider)
    result = ssi_market.build_ssi_market_snapshot("FPT", "2026-10-25", 5)

    assert "Verified SSI market data snapshot" in result
    assert "Source: ssi-fastconnect-v3" in result
    assert "| Close | 1451 |" in result
    assert "historical first-availability time is unknown" in result
    assert len(provider.calls) == 1


@pytest.mark.unit
def test_default_vendor_chain_never_auto_selects_ssi(monkeypatch):
    # Isolate the process-wide config this test mutates from the rest of the suite.
    monkeypatch.setattr(config_module, "_config", copy.deepcopy(DEFAULT_CONFIG))
    set_config({"data_vendors": {"core_stock_apis": "default"}})
    no_data = Mock(side_effect=NoMarketDataError("FPT", "FPT", "no rows"))
    ssi = Mock(return_value="SHOULD_NOT_BE_CALLED")
    monkeypatch.setitem(
        router.VENDOR_METHODS,
        "get_stock_data",
        {"yfinance": no_data, "ssi": ssi},
    )
    result = router.route_to_vendor("get_stock_data", "FPT", "2026-10-01", "2026-10-25")
    assert result.startswith("NO_DATA_AVAILABLE")
    ssi.assert_not_called()

@pytest.mark.unit
def test_verified_snapshot_uses_explicit_yfinance_fallback_when_ssi_has_no_bars(monkeypatch):
    from tradingagents.agents import tools as agent_tools

    monkeypatch.setattr(agent_tools, "as_of", lambda curr_date, trade_date: curr_date)
    monkeypatch.setattr(agent_tools, "get_vendor", lambda category, method: "ssi,yfinance")
    monkeypatch.setattr(
        agent_tools,
        "build_ssi_market_snapshot",
        Mock(side_effect=NoMarketDataError("FPT", "FPT", "no rows")),
    )
    yahoo = Mock(return_value="verified Yahoo fallback")
    monkeypatch.setattr(agent_tools, "build_verified_market_snapshot", yahoo)

    result = agent_tools.get_verified_market_snapshot.func(
        "FPT", "2026-10-25", 5, "2026-10-25"
    )

    assert result == "verified Yahoo fallback"
    yahoo.assert_called_once_with("FPT", "2026-10-25", 5)


@pytest.mark.unit
def test_verified_snapshot_does_not_fallback_to_unselected_yfinance(monkeypatch):
    from tradingagents.agents import tools as agent_tools

    monkeypatch.setattr(agent_tools, "as_of", lambda curr_date, trade_date: curr_date)
    monkeypatch.setattr(agent_tools, "get_vendor", lambda category, method: "ssi")
    monkeypatch.setattr(
        agent_tools,
        "build_ssi_market_snapshot",
        Mock(side_effect=VendorNotConfiguredError("SSI SDK is missing")),
    )
    yahoo = Mock(return_value="must not be called")
    monkeypatch.setattr(agent_tools, "build_verified_market_snapshot", yahoo)

    result = agent_tools.get_verified_market_snapshot.func(
        "FPT", "2026-10-25", 5, "2026-10-25"
    )

    assert result.startswith("DATA_UNAVAILABLE")
    yahoo.assert_not_called()


@pytest.mark.unit
def test_ssi_missing_credentials_does_not_escape_stock_tool(monkeypatch):
    from tradingagents.agents import tools as agent_tools

    monkeypatch.setattr(agent_tools, "as_of_window", lambda start, end, trade: (start, end))
    monkeypatch.setattr(
        agent_tools,
        "route_to_vendor",
        Mock(side_effect=VendorNotConfiguredError("SSI credentials missing")),
    )

    result = agent_tools.get_stock_data.func(
        "FPT", "2026-10-01", "2026-10-25", "2026-10-25"
    )

    assert result.startswith("DATA_UNAVAILABLE")
    assert "SSI credentials missing" in result
