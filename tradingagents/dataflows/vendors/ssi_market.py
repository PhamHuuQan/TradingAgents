"""Optional SSI FastConnect V3 REST vendor for current-date Vietnamese-equity research.

This adapter is deliberately current-date-only. Historical SSI bars fetched today
do not reveal when each observation first became available, so backdated requests
are rejected rather than presented as point-in-time-safe. It uses the documented
read-only Market Data REST endpoints and requires only API Key and API Secret.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar
from tradingagents.dataflows.vietnam_market.ssi import authenticated_ssi_provider_from_env
from tradingagents.dataflows.vietnam_market.technicals import (
    IndicatorPoint,
    average_true_range,
    exponential_moving_average,
    relative_strength_index,
    simple_moving_average,
)

_MARKET_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_FINAL_DAILY_BAR_TIME = time(15, 5)
_MAX_PAGE_SIZE = 1000
_MAX_LOOKBACK_ROWS = 300
_SNAPSHOT_INDICATORS = (
    "close_10_ema", "close_50_sma", "close_200_sma", "rsi",
    "boll", "boll_ub", "boll_lb", "macd", "macds", "macdh", "atr", "vwma",
)


def _now_market() -> datetime:
    return datetime.now(_MARKET_TZ)


def _parse_date(value: str | date, field: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD format") from exc
    if result.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD format")
    return result


def _check_configuration() -> None:
    missing = [name for name in ("SSI_API_KEY", "SSI_API_SECRET") if not os.getenv(name)]
    if missing:
        raise VendorNotConfiguredError(
            "SSI was explicitly selected but required environment variable(s) are missing: "
            f"{', '.join(missing)}. Configure these values privately; never commit credentials to Git."
        )


def _fetch_current_bars(
    symbol: str,
    start_date: str | date,
    end_date: str | date,
) -> tuple[list[MarketBar], datetime]:
    """Fetch rows for a current-date analysis and record only fetch-time availability."""
    normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not normalized or not normalized.isalnum() or not 2 <= len(normalized) <= 12:
        raise ValueError("symbol must contain 2-12 letters/digits")
    start = _parse_date(start_date, "start_date")
    requested_end = _parse_date(end_date, "end_date")
    fetched_at = _now_market()
    today = fetched_at.date()

    if requested_end != today:
        raise VendorUnavailableError(
            "SSI integration is current-date only. Backdated requests are blocked because "
            "historical first-availability time is unknown; use a verified PIT source for backtests."
        )

    # If today's daily candle may still be forming, request only through yesterday.
    # On weekends/holidays the end date is still safe: SSI returns its latest completed session.
    complete_end = (
        today
        if fetched_at.timetz().replace(tzinfo=None) >= _FINAL_DAILY_BAR_TIME
        else today - timedelta(days=1)
    )
    if start > complete_end:
        raise NoMarketDataError(
            normalized, normalized,
            "requested range contains no completed daily bar at the current time",
        )

    _check_configuration()
    available_at_by_date = {
        start + timedelta(days=offset): fetched_at
        for offset in range((complete_end - start).days + 1)
    }
    try:
        with authenticated_ssi_provider_from_env() as provider:
            bars = provider.get_daily_bars(
                normalized,
                start,
                complete_end,
                available_at_by_date=available_at_by_date,
                page_size=_MAX_PAGE_SIZE,
            )
    except (VendorNotConfiguredError, VendorUnavailableError, NoMarketDataError):
        raise
    except Exception as exc:
        # Do not put SDK request payloads or credentials into the report/log message.
        detail = f"invalid SSI response ({type(exc).__name__})" if isinstance(exc, (ValueError, TypeError)) else type(exc).__name__
        raise VendorUnavailableError(
            f"SSI FastConnect Market Data request failed ({detail}); check network, "
            "read-only Market Data access, and current API status."
        ) from exc

    if not bars:
        raise NoMarketDataError(
            normalized, normalized, f"SSI returned no daily OHLC bars from {start} to {complete_end}"
        )
    if len(bars) >= _MAX_PAGE_SIZE:
        raise VendorUnavailableError(
            "SSI returned the 1,000-row safety limit; narrow the requested date range."
        )
    return bars, fetched_at


def _format_decimal(value: Decimal, digits: int = 4) -> str:
    return format(value.quantize(Decimal(1).scaleb(-digits)).normalize(), "f")


def get_ssi_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Route target for get_stock_data: source-provenance CSV from SSI OHLCV."""
    bars, fetched_at = _fetch_current_bars(symbol, start_date, end_date)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Date", "Open", "High", "Low", "Close", "Volume"))
    for bar in bars:
        writer.writerow((
            bar.timestamp.date().isoformat(), str(bar.open), str(bar.high),
            str(bar.low), str(bar.close), bar.volume,
        ))
    header = [
        f"# SSI FastConnect V3 read-only OHLCV for {symbol.strip().upper()}",
        f"# Requested as-of date: {_parse_date(end_date, 'end_date')}",
        f"# Retrieved at: {fetched_at.isoformat()}",
        "# Historical bars have fetch-time availability only; not point-in-time-safe for backtesting.",
        f"# Returned rows: {len(bars)}",
        "",
    ]
    return "\n".join(header) + output.getvalue()


def _macd_series(bars: list[MarketBar]) -> dict[str, list[IndicatorPoint]]:
    ema12 = {point.timestamp: point for point in exponential_moving_average(bars, 12)}
    ema26 = {point.timestamp: point for point in exponential_moving_average(bars, 26)}
    line = []
    for bar in bars:
        if bar.timestamp in ema12 and bar.timestamp in ema26:
            a, b = ema12[bar.timestamp], ema26[bar.timestamp]
            line.append(IndicatorPoint(bar.timestamp, a.value - b.value, max(a.available_at, b.available_at)))
    if len(line) < 9:
        return {"macd": line, "macds": [], "macdh": []}

    alpha = Decimal(2) / Decimal(10)
    signal = sum((point.value for point in line[:9]), Decimal(0)) / Decimal(9)
    signals = [IndicatorPoint(line[8].timestamp, signal, line[8].available_at)]
    for point in line[9:]:
        signal = point.value * alpha + signal * (Decimal(1) - alpha)
        signals.append(IndicatorPoint(point.timestamp, signal, max(point.available_at, signals[-1].available_at)))
    line_by_date = {point.timestamp: point for point in line}
    hist = [
        IndicatorPoint(
            point.timestamp,
            line_by_date[point.timestamp].value - point.value,
            max(line_by_date[point.timestamp].available_at, point.available_at),
        )
        for point in signals
    ]
    return {"macd": line, "macds": signals, "macdh": hist}


def _bollinger_series(bars: list[MarketBar], period: int = 20) -> dict[str, list[IndicatorPoint]]:
    middle, upper, lower = [], [], []
    for index in range(period - 1, len(bars)):
        window = bars[index - period + 1 : index + 1]
        closes = [bar.close for bar in window]
        mean = sum(closes, Decimal(0)) / Decimal(period)
        variance = sum(((value - mean) ** 2 for value in closes), Decimal(0)) / Decimal(period)
        deviation = variance.sqrt()
        available_at = max(bar.available_at for bar in window)
        middle.append(IndicatorPoint(bars[index].timestamp, mean, available_at))
        upper.append(IndicatorPoint(bars[index].timestamp, mean + 2 * deviation, available_at))
        lower.append(IndicatorPoint(bars[index].timestamp, mean - 2 * deviation, available_at))
    return {"boll": middle, "boll_ub": upper, "boll_lb": lower}


def _vwma_series(bars: list[MarketBar], period: int = 20) -> list[IndicatorPoint]:
    result = []
    for index in range(period - 1, len(bars)):
        window = bars[index - period + 1 : index + 1]
        total_volume = sum(bar.volume for bar in window)
        if total_volume <= 0:
            continue
        total_value = sum((bar.close * Decimal(bar.volume) for bar in window), Decimal(0))
        result.append(IndicatorPoint(
            bars[index].timestamp,
            total_value / Decimal(total_volume),
            max(bar.available_at for bar in window),
        ))
    return result


def _indicator_series(bars: list[MarketBar], indicator: str) -> list[IndicatorPoint]:
    name = indicator.strip().lower()
    if name == "close_10_ema":
        return exponential_moving_average(bars, 10)
    if name == "close_50_sma":
        return simple_moving_average(bars, 50)
    if name == "close_200_sma":
        return simple_moving_average(bars, 200)
    if name == "rsi":
        return relative_strength_index(bars, 14)
    if name == "atr":
        return average_true_range(bars, 14)
    if name in {"macd", "macds", "macdh"}:
        return _macd_series(bars)[name]
    if name in {"boll", "boll_ub", "boll_lb"}:
        return _bollinger_series(bars)[name]
    if name == "vwma":
        return _vwma_series(bars)
    raise ValueError(
        "SSI supports: close_10_ema, close_50_sma, close_200_sma, rsi, atr, "
        "macd, macds, macdh, boll, boll_ub, boll_lb, vwma."
    )


def get_ssi_indicators(
    symbol: str, indicator: str, curr_date: str, look_back_days: int = 30
) -> str:
    """Route target for get_indicators: technical indicators computed from SSI bars."""
    if isinstance(look_back_days, bool) or not isinstance(look_back_days, int) or not 1 <= look_back_days <= _MAX_LOOKBACK_ROWS:
        raise ValueError(f"look_back_days must be an integer from 1 to {_MAX_LOOKBACK_ROWS}")
    as_of = _parse_date(curr_date, "curr_date")
    calendar_days = min(1300, max(450, look_back_days * 3 + 450))
    bars, fetched_at = _fetch_current_bars(
        symbol, as_of - timedelta(days=calendar_days), as_of
    )
    points = _indicator_series(bars, indicator)
    if not points:
        raise NoMarketDataError(symbol, symbol, f"not enough bars to calculate {indicator!r}")

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Date", indicator.strip().lower()))
    for point in points[-look_back_days:]:
        writer.writerow((point.timestamp.date().isoformat(), _format_decimal(point.value)))
    return (
        f"# SSI FastConnect V3 indicator {indicator.strip().lower()} for {symbol.strip().upper()}\n"
        f"# Retrieved at: {fetched_at.isoformat()}\n"
        "# Historical bars have fetch-time availability only; backdated PIT use is blocked.\n"
        + output.getvalue()
    )


def build_ssi_market_snapshot(symbol: str, as_of_date: str, look_back_days: int = 30) -> str:
    """Deterministic OHLCV/indicator snapshot with SSI as the sole price source."""
    if isinstance(look_back_days, bool) or not isinstance(look_back_days, int) or look_back_days < 1:
        raise ValueError("look_back_days must be a positive integer")
    as_of = _parse_date(as_of_date, "as_of_date")
    bars, fetched_at = _fetch_current_bars(symbol, as_of - timedelta(days=500), as_of)
    latest = bars[-1]
    indicator_values = {}
    for name in _SNAPSHOT_INDICATORS:
        points = _indicator_series(bars, name)
        indicator_values[name] = _format_decimal(points[-1].value) if points else "N/A (not enough bars)"
    recent = bars[-min(look_back_days, 30):]
    lines = [
        f"## Verified SSI market data snapshot for {symbol.strip().upper()}",
        "",
        f"- Requested as-of date: {as_of.isoformat()}",
        f"- Latest returned trading row: {latest.timestamp.date().isoformat()}",
        f"- Source: {latest.source}",
        f"- Retrieved at: {fetched_at.isoformat()}",
        "- SSI route is current-date only; historical first-availability time is unknown.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Open | {latest.open} |",
        f"| High | {latest.high} |",
        f"| Low | {latest.low} |",
        f"| Close | {latest.close} |",
        f"| Volume | {latest.volume} |",
        "",
        "### Verified technical indicators (SSI OHLCV)",
        "",
        "| Indicator | Value |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in indicator_values.items())
    lines.extend(["", f"### Recent verified closes (last {len(recent)} rows)", "", "| Date | Close |", "|---|---:|"])
    lines.extend(f"| {bar.timestamp.date().isoformat()} | {bar.close} |" for bar in recent)
    lines.extend([
        "",
        "Use this snapshot for exact price/indicator claims when SSI is the selected source. "
        "Do not treat fetched history as point-in-time evidence for backdated analysis or backtesting.",
    ])
    return "\n".join(lines)
