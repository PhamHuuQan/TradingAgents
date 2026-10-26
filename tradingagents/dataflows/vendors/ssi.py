"""SSI FastConnect market-data provider for Vietnamese equity OHLCV.

Credentials are read only from environment variables:
    SSI_CLIENT_ID, SSI_API_KEY, SSI_API_SECRET

The SDK is imported lazily so SSI remains an optional provider and installations
that use Yahoo/Alpha Vantage do not need the SSI package.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.files import locked, replace_file
from tradingagents.dataflows.symbols import safe_ticker_component
from tradingagents.dataflows.vendors.yahoo.ohlcv import (
    _assert_ohlcv_not_stale,
    _fill_price_gaps,
)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 900
CACHE_REFRESH_OVERLAP_DAYS = 10
_REQUIRED_COLUMNS = ("Date", "Symbol", "Open", "High", "Low", "Close", "Volume", "Value")
_SUPPORTED_INDICATORS = {
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh", "rsi", "boll", "boll_ub",
    "boll_lb", "atr", "vwma", "mfi",
}
_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: medium-term trend and dynamic support/resistance.",
    "close_200_sma": "200 SMA: long-term trend confirmation.",
    "close_10_ema": "10 EMA: responsive short-term trend and momentum.",
    "macd": "MACD: momentum measured by the difference between exponential moving averages.",
    "macds": "MACD Signal: smoothed MACD line used to assess crossovers.",
    "macdh": "MACD Histogram: difference between MACD and its signal.",
    "rsi": "RSI: momentum oscillator commonly interpreted with 70/30 reference levels.",
    "boll": "Bollinger Middle: 20-period moving-average basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: upper volatility band around the moving average.",
    "boll_lb": "Bollinger Lower Band: lower volatility band around the moving average.",
    "atr": "ATR: average true range, a measure of price volatility.",
    "vwma": "VWMA: moving average weighted by trading volume.",
    "mfi": "MFI: money-flow oscillator using price and volume.",
}


def _clean_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("SSI symbol must be a string.")
    value = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,19}", value):
        raise ValueError(f"Invalid SSI ticker symbol: {symbol!r}")
    return value


def _parse_date(value: str, name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"{name} must use YYYY-MM-DD format; received {value!r}.") from None


def _credentials() -> tuple[str, str, str]:
    client_id = os.getenv("SSI_CLIENT_ID", "").strip()
    api_key = os.getenv("SSI_API_KEY", "").strip()
    api_secret = os.getenv("SSI_API_SECRET", "").strip()
    if not all((client_id, api_key, api_secret)):
        raise VendorNotConfiguredError(
            "SSI is selected but credentials are missing. Set SSI_CLIENT_ID, "
            "SSI_API_KEY, and SSI_API_SECRET in the runtime environment."
        )
    return client_id, api_key, api_secret


def _frame_from_bars(symbol: str, bars) -> pd.DataFrame:
    records = []
    for bar in bars or []:
        get = bar.get if isinstance(bar, dict) else lambda key, default=None: getattr(bar, key, default)
        records.append({
            "Date": get("trading_date"),
            "Symbol": (get("symbol") or symbol).strip().upper(),
            "Open": get("open_price"),
            "High": get("high_price"),
            "Low": get("low_price"),
            "Close": get("close_price"),
            "Volume": get("volume"),
            "Value": get("value"),
        })
    if not records:
        return pd.DataFrame(columns=list(_REQUIRED_COLUMNS))
    frame = pd.DataFrame.from_records(records, columns=list(_REQUIRED_COLUMNS))
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    if frame["Date"].isna().any():
        raise VendorUnavailableError("SSI returned OHLCV rows with invalid trading dates.")
    for column in ("Open", "High", "Low", "Close", "Volume", "Value"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise VendorUnavailableError(f"SSI returned non-numeric or missing values in {column}.")
    if not frame["Symbol"].eq(symbol).all():
        raise VendorUnavailableError(f"SSI returned a ticker different from requested {symbol}.")
    if frame["Date"].duplicated().any():
        raise VendorUnavailableError("SSI returned duplicate OHLCV trading dates.")
    if (frame["Volume"] < 0).any() or (frame[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise VendorUnavailableError("SSI returned invalid prices or negative trading volume.")
    invalid = (
        (frame["High"] < frame[["Open", "Close", "Low"]].max(axis=1))
        | (frame["Low"] > frame[["Open", "Close", "High"]].min(axis=1))
    )
    if invalid.any():
        raise VendorUnavailableError(f"SSI returned {int(invalid.sum())} invalid OHLC candle(s).")
    return frame.sort_values("Date").reset_index(drop=True)


def _fetch_from_ssi(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Fetch the entire requested daily range through SSI's official Python SDK."""
    client_id, api_key, api_secret = _credentials()
    try:
        from ssi_sdk import APIError, Auth, AuthenticationError, Config, Data, ValidationError
        from ssi_sdk.enums import Timeframe
    except ImportError:
        raise VendorNotConfiguredError(
            "SSI provider requires the optional dependency. Install it with "
            "pip install ssi-sdk==3.3.2."
        ) from None

    config = Config(client_id=client_id, api_key=api_key, api_secret=api_secret)
    start_text = start.strftime("%Y/%m/%d") + " 00:00:00"
    end_text = end.strftime("%Y/%m/%d") + " 23:59:59"
    try:
        with Auth(config) as auth:
            auth.authenticate()
            with Data(auth) as client:
                bars = client.market_data.get_ohlc_all(
                    symbol,
                    Timeframe.DAY_1,
                    from_date=start_text,
                    to_date=end_text,
                    size=1000,
                    ascending=True,
                )
    except AuthenticationError:
        raise VendorNotConfiguredError(
            "SSI authentication failed. Check the SSI Client ID, API Key, API Secret, "
            "and that the credentials have Market Data access."
        ) from None
    except APIError as exc:
        status = getattr(exc, "status_code", None)
        code = getattr(exc, "code", None)
        if status in (401, 403):
            raise VendorNotConfiguredError(
                f"SSI rejected authentication/permissions (HTTP {status}, code {code}). "
                "Check SSI credentials and Market Data access."
            ) from None
        raise VendorUnavailableError(
            f"SSI Market Data request failed (HTTP {status}, code {code}, "
            f"error type {type(exc).__name__})."
        ) from None
    except ValidationError as exc:
        raise ValueError(
            f"SSI SDK rejected the query parameters ({type(exc).__name__}); "
            "check the symbol and YYYY-MM-DD date range."
        ) from None
    except Exception as exc:
        # Do not include arbitrary exception text: SDK/network errors can contain
        # request details. The class and status above are enough to diagnose safely.
        raise VendorUnavailableError(
            f"SSI Market Data request failed (error type {type(exc).__name__})."
        ) from None

    return _frame_from_bars(symbol, bars)


def _cache_path(symbol: str) -> Path:
    config = get_config()
    root = Path(config.get("data_cache_dir") or Path.home() / ".tradingagents" / "cache")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe_ticker_component(symbol)}-SSI-data.csv"


def _read_cache(path: Path, symbol: str) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path)
        if not set(_REQUIRED_COLUMNS).issubset(frame.columns) or frame.empty:
            return None
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
        for column in ("Open", "High", "Low", "Close", "Volume", "Value"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["Symbol"] = frame["Symbol"].astype(str).str.upper()
        if frame["Date"].isna().any() or frame[list(_REQUIRED_COLUMNS[2:])].isna().any().any():
            return None
        if not frame["Symbol"].eq(symbol).all() or frame["Date"].duplicated().any():
            return None
        return frame.sort_values("Date").reset_index(drop=True)
    except (OSError, ValueError, KeyError, pd.errors.ParserError):
        logger.warning("Ignoring unreadable SSI cache for %s.", symbol)
        return None


def _get_history(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Load a ticker's cached history, extending missing date ranges through SSI."""
    symbol = _clean_symbol(symbol)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start > end:
        raise ValueError(f"start_date ({start}) must not be after end_date ({end}).")

    path = _cache_path(symbol)
    today = date.today()
    recent_request = end >= today - timedelta(days=1)

    # Serialize read/extend/write: the analysts can request the same symbol in parallel.
    with locked(path):
        cached = _read_cache(path, symbol)
        fetch_start = None
        fetch_end = None
        if cached is None or cached.empty:
            fetch_start, fetch_end = start, end
        else:
            cache_start = cached["Date"].min().date()
            cache_end = cached["Date"].max().date()
            age_seconds = max(0.0, time.time() - path.stat().st_mtime)
            needs_current_refresh = recent_request and age_seconds > CACHE_TTL_SECONDS
            if start < cache_start and end > cache_end:
                fetch_start, fetch_end = start, end
            elif start < cache_start:
                fetch_start, fetch_end = start, min(end, cache_start)
            elif end > cache_end:
                fetch_start = max(start, cache_end - timedelta(days=CACHE_REFRESH_OVERLAP_DAYS))
                fetch_end = end
            elif needs_current_refresh:
                fetch_start = max(start, cache_end - timedelta(days=CACHE_REFRESH_OVERLAP_DAYS))
                fetch_end = end

        if fetch_start is not None and fetch_end is not None and fetch_start <= fetch_end:
            fetched = _fetch_from_ssi(symbol, fetch_start, fetch_end)
            if cached is not None and not cached.empty:
                # Overlap deliberately refreshes the trailing bars; keep the new
                # provider response when a date is present in both frames.
                combined = pd.concat([cached, fetched], ignore_index=True)
                combined = combined.drop_duplicates(subset=["Date"], keep="last")
            else:
                combined = fetched
            combined = combined.sort_values("Date").reset_index(drop=True)
            if not combined.empty:
                replace_file(
                    path,
                    lambda temp: combined.to_csv(
                        temp, index=False, encoding="utf-8", date_format="%Y-%m-%d"
                    ),
                )
            cached = combined

    if cached is None or cached.empty:
        raise NoMarketDataError(symbol, symbol, "SSI returned no OHLCV rows for the requested range")
    return cached.copy()


def load_ssi_ohlcv(symbol: str, as_of_date: str, fill_gaps: bool = True) -> pd.DataFrame:
    """Load up to five years of SSI daily bars, strictly filtered at as_of_date."""
    cutoff = _parse_date(as_of_date, "as_of_date")
    start = (pd.Timestamp(cutoff) - pd.DateOffset(years=5)).date()
    data = _get_history(symbol, start.isoformat(), cutoff.isoformat())
    data = data[data["Date"] <= pd.Timestamp(cutoff)].copy()
    if data.empty:
        raise NoMarketDataError(symbol, symbol, f"no SSI OHLCV rows on or before {cutoff}")
    if fill_gaps:
        data = _fill_price_gaps(data)
    else:
        data = data.dropna(subset=["Close"]).copy()
    _assert_ohlcv_not_stale(data, cutoff.isoformat(), symbol, symbol)
    return data.reset_index(drop=True)


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Return SSI daily OHLCV as CSV text, in the same format expected by the agents."""
    symbol = _clean_symbol(symbol)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start > end:
        raise ValueError(f"start_date ({start}) must not be after end_date ({end}).")
    data = _get_history(symbol, start_date, end_date)
    data = data[(data["Date"] >= pd.Timestamp(start)) & (data["Date"] <= pd.Timestamp(end))].copy()
    if data.empty:
        raise NoMarketDataError(symbol, symbol, f"no SSI OHLCV rows between {start_date} and {end_date}")
    _assert_ohlcv_not_stale(data, end_date, symbol, symbol)
    label = f"SSI reported OHLCV for {symbol}"
    return f"# {label} from {start_date} to {end_date}\n# Total records: {len(data)}\n\n" + data.to_csv(index=False)


def get_indicators(
    symbol: str,
    indicator: str,
    as_of_date: str,
    look_back_days: int,
) -> str:
    """Compute a technical indicator from SSI bars, not a different vendor's series."""
    symbol = _clean_symbol(symbol)
    if indicator not in _SUPPORTED_INDICATORS:
        raise NoMarketDataError(
            symbol, symbol, f"SSI provider does not support the {indicator!r} indicator"
        )
    if not isinstance(look_back_days, int) or look_back_days < 0:
        raise ValueError("look_back_days must be a non-negative integer.")
    as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    before = as_of_dt - relativedelta(days=look_back_days)
    data = load_ssi_ohlcv(symbol, as_of_date, fill_gaps=True)
    data = data[data["Date"] <= pd.Timestamp(as_of_date)].copy()
    data = data.sort_values("Date").reset_index(drop=True)
    frame = wrap(data)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame[indicator]  # trigger stockstats calculation
    values = {}
    for _, row in frame.iterrows():
        value = row[indicator]
        values[row["Date"]] = "N/A" if pd.isna(value) else str(value)

    lines = []
    current = as_of_dt
    while current >= before:
        day = current.strftime("%Y-%m-%d")
        value = values.get(day, "N/A: Not a trading day (weekend or holiday)")
        lines.append(f"{day}: {value}")
        current -= relativedelta(days=1)
    return (
        f"## {indicator} values from {before:%Y-%m-%d} to {as_of_date} (SSI)\n\n"
        + "\n".join(lines)
        + "\n\n"
        + _INDICATOR_DESCRIPTIONS[indicator]
    )
