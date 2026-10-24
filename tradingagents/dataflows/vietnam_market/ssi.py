"""Read-only adapter for SSI FastConnect V3 daily OHLC data.

Accepts an already-authenticated SSI SDK market-data service. It does not
authenticate, store credentials, or expose trading methods. Historical
availability timestamps must be supplied by the caller because SSI OHLC
history does not itself establish when each historical bar first became available.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Mapping
from zoneinfo import ZoneInfo

from tradingagents.dataflows.vietnam_market.models import MarketBar

_MARKET_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class SSIAdapterError(ValueError):
    """Raised when SSI data cannot be normalized safely."""


def _read_field(row: object, *names: str) -> object:
    """Read a field from an SDK model or mapping, tolerating naming styles."""
    for name in names:
        if isinstance(row, Mapping) and name in row:
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
    raise SSIAdapterError(f"SSI OHLC record is missing required field: {names[0]}")


def _as_decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SSIAdapterError(f"Invalid SSI {field} value: {value!r}") from exc
    if not result.is_finite():
        raise SSIAdapterError(f"SSI {field} must be finite")
    return result


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise SSIAdapterError(f"Unrecognized SSI trading date: {value!r}")


class SSIMarketDataProvider:
    """Normalize SSI SDK daily OHLC records to the shared MarketBar model.

    market_data is an authenticated SSI SDK MarketDataService instance.
    Authentication remains the responsibility of the calling application, so
    credentials can stay in environment variables or a secret manager.

    available_at_by_date is mandatory because historical OHLC responses do not
    prove when each bar was first available to a strategy. Do not guess these
    timestamps for point-in-time backtests.
    """

    source = "ssi-fastconnect-v3"

    def __init__(self, market_data: object) -> None:
        if not callable(getattr(market_data, "get_ohlc_all", None)):
            raise TypeError("market_data must expose the SSI SDK get_ohlc_all method")
        self._market_data = market_data

    def get_daily_bars(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        *,
        available_at_by_date: Mapping[date, datetime],
        page_size: int = 1000,
    ) -> list[MarketBar]:
        """Fetch and normalize daily bars for one symbol, oldest first."""
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol.isalnum() or not 2 <= len(normalized_symbol) <= 12:
            raise ValueError("symbol must contain 2-12 letters/digits")
        if from_date > to_date:
            raise ValueError("from_date must be on or before to_date")
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")

        # SSI Python SDK documents the daily timeframe as 1d.
        rows = self._market_data.get_ohlc_all(
            normalized_symbol,
            "1d",
            from_date=from_date.strftime("%Y/%m/%d"),
            to_date=to_date.strftime("%Y/%m/%d"),
            size=page_size,
            ascending=True,
        )

        bars: list[MarketBar] = []
        seen_dates: set[date] = set()
        for row in rows:
            trading_date = _as_date(_read_field(row, "trading_date", "TradingDate", "tradingDate"))
            if not from_date <= trading_date <= to_date:
                continue
            if trading_date in seen_dates:
                raise SSIAdapterError(f"Duplicate SSI daily bar for {normalized_symbol} on {trading_date}")
            seen_dates.add(trading_date)

            available_at = available_at_by_date.get(trading_date)
            if available_at is None:
                raise SSIAdapterError(
                    f"Missing verified availability timestamp for {normalized_symbol} on {trading_date}"
                )
            if available_at.tzinfo is None or available_at.utcoffset() is None:
                raise SSIAdapterError(f"Availability timestamp for {trading_date} must be timezone-aware")

            # Daily bars represent the end of the Vietnam trading day, not midnight.
            bar_timestamp = datetime.combine(trading_date, time(15, 0), tzinfo=_MARKET_TZ)
            if available_at < bar_timestamp:
                raise SSIAdapterError(
                    f"Availability timestamp for {trading_date} precedes the daily bar close"
                )

            bars.append(
                MarketBar(
                    symbol=normalized_symbol,
                    timestamp=bar_timestamp,
                    open=_as_decimal(_read_field(row, "open_price", "Open", "open")),
                    high=_as_decimal(_read_field(row, "high_price", "High", "high")),
                    low=_as_decimal(_read_field(row, "low_price", "Low", "low")),
                    close=_as_decimal(_read_field(row, "close_price", "Close", "close")),
                    volume=int(_read_field(row, "volume", "Volume")),
                    source=self.source,
                    available_at=available_at,
                )
            )

        return sorted(bars, key=lambda bar: bar.timestamp)
