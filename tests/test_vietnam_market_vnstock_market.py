import copy
import sys
from datetime import date, datetime, time, timedelta
from types import ModuleType
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
from tradingagents.dataflows.vendors import vnstock_market
from tradingagents.default_config import DEFAULT_CONFIG

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=VN_TZ)


class FakeFrame:
    def __init__(self, rows, *, source="vci", symbol="FPT"):
        self.rows = rows
        self.columns = ("time", "open", "high", "low", "close", "volume")
        self.empty = not rows
        self.attrs = {"source": source, "symbol": symbol}

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


class FakeEquity:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def ohlcv(self, *, start, end, interval, source, floating):
        self.calls.append((start, end, interval, source, floating))
        return self.frame


@pytest.fixture
def mocked_vnstock(monkeypatch):
    monkeypatch.setattr(vnstock_market, "_now_market", lambda: NOW)
    rows = []
    start = date(2026, 10, 12)
    end = date(2026, 10, 23)
    cursor = start
    index = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append({
                "time": datetime.combine(cursor, time(7, 0), tzinfo=VN_TZ),
                "open": 60.0 + index,
                "high": 61.0 + index,
                "low": 59.0 + index,
                "close": 60.5 + index,
                "volume": 100000 + index,
            })
            index += 1
        cursor += timedelta(days=1)
    equity = FakeEquity(FakeFrame(rows))
    monkeypatch.setattr(vnstock_market, "_market_client", lambda symbol: equity)
    return equity

@pytest.mark.unit
def test_vnstock_ohlcv_converts_thousand_vnd_to_vnd_and_marks_fetch_time(mocked_vnstock):
    output = vnstock_market.get_vnstock_stock_data("fpt", "2026-10-01", "2026-10-25")

    assert "# OHLC prices converted from the source's thousand-VND unit to VND/share." in output
    assert "not historical first-publication time" in output
    assert "Date,Open,High,Low,Close,Volume" in output
    assert "2026-10-23,69000,70000,68000,69500,100009" in output
    # Query through today's requested as-of date; the source returns only completed
    # exchange sessions (the last available row in this fixture is Friday).
    assert mocked_vnstock.calls == [("2026-10-01", "2026-10-25", "1D", "vci", None)]


@pytest.mark.unit
def test_vnstock_ohlcv_refuses_backdated_as_of_before_network(monkeypatch):
    monkeypatch.setattr(vnstock_market, "_now_market", lambda: NOW)
    client = Mock()
    loader = Mock(return_value=client)
    monkeypatch.setattr(vnstock_market, "_market_client", loader)

    with pytest.raises(VendorUnavailableError, match="current-date only"):
        vnstock_market.get_vnstock_stock_data("FPT", "2026-10-01", "2026-10-24")
    loader.assert_not_called()


@pytest.mark.unit
def test_vnstock_ohlcv_rejects_source_metadata_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr(vnstock_market, "_now_market", lambda: NOW)
    bad = FakeEquity(FakeFrame([
        {"time": datetime(2026, 10, 24, 7, 0, tzinfo=VN_TZ),
         "open": 63.5, "high": 65.0, "low": 63.0, "close": 64.5, "volume": 120000},
    ], source="kbs"))
    monkeypatch.setattr(vnstock_market, "_market_client", lambda symbol: bad)

    with pytest.raises(VendorUnavailableError, match="expected 'vci'"):
        vnstock_market.get_vnstock_stock_data("FPT", "2026-10-01", "2026-10-25")


@pytest.mark.unit
def test_vnstock_indicator_and_snapshot_share_vci_series(mocked_vnstock):
    output = vnstock_market.get_vnstock_indicators("FPT", "close_10_ema", "2026-10-25", 5)
    assert "# Vnstock VCI indicator close_10_ema" in output
    assert "VND/share" in output
    assert len(mocked_vnstock.calls) == 1

    snapshot = vnstock_market.build_vnstock_market_snapshot("FPT", "2026-10-25", 3)
    assert "Verified Vnstock VCI market data snapshot" in snapshot
    assert "Source: vnstock-vci" in snapshot
    assert "| Close | 69500 |" in snapshot
    assert len(mocked_vnstock.calls) == 2


@pytest.mark.unit
def test_vnstock_vendor_requires_package_only_when_explicitly_called(monkeypatch):
    monkeypatch.setattr(vnstock_market.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(vnstock_market, "_now_market", lambda: NOW)

    with pytest.raises(VendorNotConfiguredError, match="not installed"):
        vnstock_market.get_vnstock_stock_data("FPT", "2026-10-01", "2026-10-25")


@pytest.mark.unit
def test_default_price_vendor_chain_never_auto_selects_vnstock(monkeypatch):
    monkeypatch.setattr(config_module, "_config", copy.deepcopy(DEFAULT_CONFIG))
    set_config({"data_vendors": {"core_stock_apis": "default"}})
    no_data = Mock(side_effect=NoMarketDataError("FPT", "FPT", "no rows"))
    vnstock = Mock(return_value="SHOULD_NOT_BE_CALLED")
    monkeypatch.setitem(router.VENDOR_METHODS, "get_stock_data", {
        "yfinance": no_data, "vnstock": vnstock,
    })

    result = router.route_to_vendor("get_stock_data", "FPT", "2026-10-01", "2026-10-25")

    assert result.startswith("NO_DATA_AVAILABLE")
    vnstock.assert_not_called()


@pytest.mark.unit
def test_verified_snapshot_uses_vnstock_when_explicit_and_keeps_same_source(monkeypatch):
    from tradingagents.agents import tools as agent_tools
    monkeypatch.setattr(agent_tools, "as_of", lambda requested, trade_date: requested)
    monkeypatch.setattr(agent_tools, "get_vendor", lambda category, method: "vnstock")
    snapshot = Mock(return_value="verified VCI snapshot")
    yahoo = Mock(return_value="wrong-source snapshot")
    monkeypatch.setattr(agent_tools, "build_vnstock_market_snapshot", snapshot)
    monkeypatch.setattr(agent_tools, "build_verified_market_snapshot", yahoo)

    result = agent_tools.get_verified_market_snapshot.func("FPT", "2026-10-25", 5, "2026-10-25")

    assert result == "verified VCI snapshot"
    snapshot.assert_called_once_with("FPT", "2026-10-25", 5)
    yahoo.assert_not_called()

@pytest.mark.unit
def test_domestic_vnstock_index_is_not_scaled_as_stock_price(monkeypatch):
    monkeypatch.setattr(vnstock_market, "_now_market", lambda: NOW)
    frame = FakeFrame(
        [{
            "time": datetime(2026, 10, 23, 7, 0, tzinfo=VN_TZ),
            "open": 1740.54,
            "high": 1745.00,
            "low": 1730.00,
            "close": 1739.25,
            "volume": 911324549,
        }],
        symbol="VNINDEX",
    )
    equity = FakeEquity(frame)
    monkeypatch.setattr(vnstock_market, "_market_client", lambda symbol: equity)

    output = vnstock_market.get_vnstock_stock_data("VNINDEX", "2026-10-01", "2026-10-25")

    assert "# Index OHLC values are measured in index points; no price scaling was applied." in output
    assert "thousand-VND unit" not in output
    assert "2026-10-23,1740.54,1745,1730,1739.25,911324549" in output
    assert equity.calls == [("2026-10-01", "2026-10-25", "1D", "vci", None)]

    snapshot = vnstock_market.build_vnstock_market_snapshot("VNINDEX", "2026-10-25", 3)
    assert "Source: vnstock-vci-index" in snapshot
    assert "Index values are measured in points" in snapshot
    assert "| Close | 1739.25 |" in snapshot


@pytest.mark.unit
def test_vnstock_client_routes_known_domestic_indices_to_index_api(monkeypatch):
    calls = []

    class FakeMarket:
        def equity(self, symbol):
            calls.append(("equity", symbol))
            return ("equity", symbol)

        def index(self, symbol):
            calls.append(("index", symbol))
            return ("index", symbol)

    fake_module = ModuleType("vnstock")
    fake_module.Market = FakeMarket
    monkeypatch.setitem(sys.modules, "vnstock", fake_module)
    monkeypatch.setattr(vnstock_market.importlib.util, "find_spec", lambda name: object())

    assert vnstock_market._market_client("VNINDEX") == ("index", "VNINDEX")
    assert vnstock_market._market_client("HNXINDEX") == ("index", "HNXINDEX")
    assert vnstock_market._market_client("FPT") == ("equity", "FPT")
    assert calls == [
        ("index", "VNINDEX"),
        ("index", "HNXINDEX"),
        ("equity", "FPT"),
    ]

@pytest.mark.unit
@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({}, "source is None"),
        ({"source": "vci"}, "metadata ticker"),
        ({"source": "kbs", "symbol": "FPT"}, "expected 'vci'"),
    ],
)
def test_vnstock_ohlcv_requires_complete_source_and_symbol_metadata(metadata, message):
    frame = FakeFrame([
        {
            "time": datetime(2026, 10, 23, 7, 0, tzinfo=VN_TZ),
            "open": 60.0,
            "high": 61.0,
            "low": 59.0,
            "close": 60.5,
            "volume": 100000,
        }
    ])
    frame.attrs = metadata

    with pytest.raises(VendorUnavailableError, match=message):
        vnstock_market._validate_frame(frame, "FPT")
