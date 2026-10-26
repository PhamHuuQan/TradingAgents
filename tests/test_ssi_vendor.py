"""Offline tests for the optional SSI FastConnect provider."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from tradingagents.dataflows import router
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.vendors import ssi


def _bar(day: date, *, symbol: str = "FPT", open_=100, high=105, low=99, close=103, volume=1000):
    return SimpleNamespace(
        symbol=symbol,
        trading_date=f"{day:%Y/%m/%d} 00:00:00",
        open_price=open_,
        high_price=high,
        low_price=low,
        close_price=close,
        volume=volume,
        value=close * volume,
    )


def _frame(start: date, count: int = 3) -> pd.DataFrame:
    bars = [
        _bar(start + timedelta(days=i), open_=100 + i, high=105 + i, low=99 + i,
             close=103 + i, volume=1000 + i)
        for i in range(count)
    ]
    return ssi._frame_from_bars("FPT", bars)


@pytest.mark.unit
def test_ssi_credentials_are_required_and_never_printed(monkeypatch):
    monkeypatch.delenv("SSI_CLIENT_ID", raising=False)
    monkeypatch.delenv("SSI_API_KEY", raising=False)
    monkeypatch.delenv("SSI_API_SECRET", raising=False)
    with pytest.raises(VendorNotConfiguredError, match="SSI_CLIENT_ID"):
        ssi._credentials()


@pytest.mark.unit
def test_maps_official_sdk_bars_to_clean_ohlcv_frame():
    today = date.today()
    frame = ssi._frame_from_bars("FPT", [_bar(today - timedelta(days=1)), _bar(today)])
    assert list(frame.columns) == ["Date", "Symbol", "Open", "High", "Low", "Close", "Volume", "Value"]
    assert len(frame) == 2
    assert frame.iloc[-1]["Symbol"] == "FPT"
    assert frame.iloc[-1]["Close"] == 103
    assert frame.iloc[-1]["Value"] == 103000


@pytest.mark.unit
def test_invalid_candles_and_wrong_symbols_are_rejected():
    today = date.today()
    with pytest.raises(VendorUnavailableError, match="invalid OHLC"):
        ssi._frame_from_bars(
            "FPT",
            [_bar(today, open_=110, high=105, low=99, close=103)],
        )
    with pytest.raises(VendorUnavailableError, match="different from requested"):
        ssi._frame_from_bars("FPT", [_bar(today, symbol="VNM")])


@pytest.mark.unit
def test_history_cache_reuses_fetched_range(monkeypatch, tmp_path):
    today = date.today()
    monkeypatch.setattr(ssi, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    calls = []

    def fake_fetch(symbol, start, end):
        calls.append((symbol, start, end))
        first = max(start, today - timedelta(days=1))
        return ssi._frame_from_bars(symbol, [_bar(first), _bar(today)])

    monkeypatch.setattr(ssi, "_fetch_from_ssi", fake_fetch)
    start = (today - timedelta(days=10)).isoformat()
    end = today.isoformat()
    first = ssi._get_history("FPT", start, end)
    second = ssi._get_history("FPT", start, end)

    assert len(first) == 2
    assert len(second) == 2
    assert len(calls) == 1
    assert (tmp_path / "FPT-SSI-data.csv").exists()


@pytest.mark.unit
def test_stock_data_output_is_date_filtered_and_csv_shaped(monkeypatch):
    today = date.today()
    start = today - timedelta(days=1)
    data = ssi._frame_from_bars("FPT", [_bar(start), _bar(today), _bar(today + timedelta(days=1))])
    monkeypatch.setattr(ssi, "_get_history", lambda *args: data)
    monkeypatch.setattr(ssi, "_assert_ohlcv_not_stale", lambda *args, **kwargs: None)

    out = ssi.get_stock_data("fpt", start.isoformat(), today.isoformat())

    assert "SSI reported OHLCV for FPT" in out
    assert "Date,Symbol,Open,High,Low,Close,Volume,Value" in out
    assert f"{today + timedelta(days=1):%Y-%m-%d}" not in out
    assert f"{today:%Y-%m-%d}" in out


@pytest.mark.unit
def test_ssi_indicators_do_not_use_future_rows(monkeypatch):
    as_of = date.today()
    dates = pd.date_range(end=pd.Timestamp(as_of + timedelta(days=1)), periods=280, freq="D")
    frame = pd.DataFrame({
        "Date": dates,
        "Symbol": "FPT",
        "Open": [100.0 + i for i in range(len(dates))],
        "High": [102.0 + i for i in range(len(dates))],
        "Low": [99.0 + i for i in range(len(dates))],
        "Close": [101.0 + i for i in range(len(dates))],
        "Volume": [1000 + i for i in range(len(dates))],
        "Value": [101000 + i for i in range(len(dates))],
    })
    monkeypatch.setattr(ssi, "load_ssi_ohlcv", lambda *args, **kwargs: frame)

    out = ssi.get_indicators("FPT", "close_50_sma", as_of.isoformat(), 2)

    assert as_of.isoformat() in out
    assert (as_of - timedelta(days=2)).isoformat() in out
    assert (as_of + timedelta(days=1)).isoformat() not in out
    assert "(SSI)" in out


@pytest.mark.unit
def test_router_registers_ssi_for_prices_and_indicators():
    assert "ssi" in router.VENDOR_METHODS["get_stock_data"]
    assert "ssi" in router.VENDOR_METHODS["get_indicators"]
    assert router.VENDOR_METHODS["get_stock_data"]["ssi"] is ssi.get_stock_data
    assert router.VENDOR_METHODS["get_indicators"]["ssi"] is ssi.get_indicators


@pytest.mark.unit
def test_empty_ssi_history_is_not_treated_as_valid_data(monkeypatch, tmp_path):
    today = date.today()
    monkeypatch.setattr(ssi, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(ssi, "_fetch_from_ssi", lambda *args: pd.DataFrame(columns=list(ssi._REQUIRED_COLUMNS)))
    with pytest.raises(NoMarketDataError, match="no OHLCV rows"):
        ssi._get_history("FPT", today.isoformat(), today.isoformat())

