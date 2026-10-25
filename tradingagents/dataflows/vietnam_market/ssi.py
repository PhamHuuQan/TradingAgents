"""Read-only adapter for SSI FastConnect V3 daily OHLC data via documented REST API.

Authentication uses SSI_API_KEY and SSI_API_SECRET to obtain a Market Data
Bearer token. No SDK, Client ID, Private Key, OTP, or trading endpoint is needed.
Historical availability timestamps must be supplied by the caller because SSI
OHLC history does not establish when each historical bar first became available.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import requests

from tradingagents.dataflows.vietnam_market.models import MarketBar

_MARKET_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class SSIAdapterError(ValueError):
    """Raised when SSI data cannot be normalized safely."""


def _read_field(row: object, *names: str) -> object:
    """Read a field from a REST record, SDK model, or mapping, tolerating naming styles."""
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


def _as_volume(value: object) -> int:
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SSIAdapterError(f"Invalid SSI volume value: {value!r}") from exc
    if not numeric.is_finite() or numeric < 0 or numeric != numeric.to_integral_value():
        raise SSIAdapterError(f"SSI volume must be a non-negative integer: {value!r}")
    return int(numeric)


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
            raise TypeError("market_data must expose the get_ohlc_all method")
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

        # The REST API documents "1d" for daily candles; no vendor SDK is required.
        daily_timeframe = "1d"

        rows = self._market_data.get_ohlc_all(
            normalized_symbol,
            daily_timeframe,
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
                    open=_as_decimal(_read_field(row, "open_price", "Open", "open"), "open"),
                    high=_as_decimal(_read_field(row, "high_price", "High", "high"), "high"),
                    low=_as_decimal(_read_field(row, "low_price", "Low", "low"), "low"),
                    close=_as_decimal(_read_field(row, "close_price", "Close", "close"), "close"),
                    volume=_as_volume(_read_field(row, "volume", "Volume")),
                    source=self.source,
                    available_at=available_at,
                )
            )

        return sorted(bars, key=lambda bar: bar.timestamp)


class _SSIRestMarketDataClient:
    """Minimal read-only REST client compatible with SSIMarketDataProvider."""

    _BASE_URL = "https://api.ssi.com.vn"
    _MAX_ROWS = 1000

    def __init__(self, access_token: str, session: requests.Session) -> None:
        self._access_token = access_token
        self._session = session

    def clear(self) -> None:
        """Release the token reference when the credential context exits."""
        self._access_token = ""

    def get_ohlc_all(
        self,
        symbol: str,
        timeframe: object,
        *,
        from_date: str,
        to_date: str,
        size: int = 1000,
        ascending: bool = False,
    ) -> list[object]:
        """Fetch documented OHLC pages with a conservative 1,000-row cap."""
        if not 1 <= size <= self._MAX_ROWS:
            raise ValueError(f"SSI page size must be between 1 and {self._MAX_ROWS}")

        timeframe_value = getattr(timeframe, "value", timeframe)
        timeframe_text = str(timeframe_value).strip().lower()
        if timeframe_text in {"day_1", "timeframe.day_1"}:
            timeframe_text = "1d"
        if timeframe_text not in {"1d", "1m", "3m", "5m", "15m", "30m", "1h"}:
            raise ValueError("Unsupported SSI OHLC timeframe")

        rows: list[object] = []
        max_pages = (self._MAX_ROWS + size - 1) // size
        for page_index in range(1, max_pages + 1):
            try:
                response = self._session.get(
                    f"{self._BASE_URL}/api/v3/data/ohlc",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                        "Accept-Language": "en",
                    },
                    params={
                        "symbol": symbol,
                        "from": from_date,
                        "to": to_date,
                        "timeFrame": timeframe_text,
                        "pageIndex": page_index,
                        "pageSize": size,
                    },
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise SSIAdapterError(
                    f"SSI OHLC request failed ({type(exc).__name__})"
                ) from None

            if response.status_code == 204:
                break
            if response.status_code != 200:
                raise SSIAdapterError(
                    f"SSI OHLC request failed (HTTP {response.status_code})"
                )
            try:
                payload = response.json()
            except ValueError:
                raise SSIAdapterError("SSI OHLC response was not valid JSON") from None
            if not isinstance(payload, Mapping):
                raise SSIAdapterError("SSI OHLC response had an unexpected shape")

            page_rows = payload.get("data")
            if page_rows is None and str(payload.get("code", "")) == "204":
                page_rows = []
            if not isinstance(page_rows, list):
                raise SSIAdapterError("SSI OHLC response did not contain a data array")
            if not page_rows:
                break

            rows.extend(page_rows)
            if len(rows) >= self._MAX_ROWS:
                raise SSIAdapterError(
                    "SSI OHLC response reached the 1,000-row safety limit; narrow the date range"
                )
            if len(page_rows) < size:
                break

        if ascending:
            rows.sort(
                key=lambda row: _as_date(
                    _read_field(row, "trading_date", "TradingDate", "tradingDate")
                )
            )
        return rows


@contextmanager
def authenticated_ssi_provider_from_env() -> Iterator[SSIMarketDataProvider]:
    """Yield an SSI REST-backed provider with Market Data-only authentication.

    Required environment variables: SSI_API_KEY and SSI_API_SECRET. The
    documented REST authentication call does not require a Client ID or OTP
    for Market Data access. No trading client or order endpoint is instantiated.
    """
    credentials = {
        "SSI_API_KEY": os.getenv("SSI_API_KEY"),
        "SSI_API_SECRET": os.getenv("SSI_API_SECRET"),
    }
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing SSI environment variable(s): " + ", ".join(missing)
        )

    session = requests.Session()
    client: _SSIRestMarketDataClient | None = None
    access_token: str | None = None
    try:
        try:
            response = session.post(
                "https://api.ssi.com.vn/api/v3/auth/token",
                json={
                    "apiKey": credentials["SSI_API_KEY"],
                    "apiSecret": credentials["SSI_API_SECRET"],
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"SSI authentication request failed ({type(exc).__name__})"
            ) from None

        if response.status_code != 200:
            raise RuntimeError(
                f"SSI authentication failed (HTTP {response.status_code}); "
                "check key/secret, key status, and Market Data permissions"
            )
        try:
            token_payload = response.json()
        except ValueError:
            raise RuntimeError("SSI authentication response was not valid JSON") from None
        if not isinstance(token_payload, Mapping):
            raise RuntimeError("SSI authentication response had an unexpected shape")
        access_token = token_payload.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError("SSI authentication response did not contain accessToken")

        client = _SSIRestMarketDataClient(access_token, session)
        yield SSIMarketDataProvider(client)
    finally:
        if client is not None:
            client.clear()
        access_token = None
        token_payload = None
        credentials = {}
        session.close()
