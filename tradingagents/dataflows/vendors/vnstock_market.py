"""Optional Vnstock VCI OHLCV vendor for current-date Vietnam-market research.

V5 VCI stock OHLCV prices are documented in thousand VND; this adapter converts
them to VND/share. Domestic index OHLCV is measured in index points and is not
scaled. VCI and KBS can have different corporate-action-adjusted values,
so source selection is explicit. This adapter is for current-date research only:
all retrieved rows receive fetch-time availability, not historical first-publication
timestamps, and backdated-as-of requests are rejected.
"""
from __future__ import annotations

import csv
import importlib.util
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.vendors.ssi_market import (
    _SNAPSHOT_INDICATORS,
    _format_decimal,
    _indicator_series,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar

_MARKET_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_FINAL_DAILY_BAR_TIME = time(15, 5)
_PRICE_SCALE = Decimal(1000)
_REQUIRED_COLUMNS = {"time", "open", "high", "low", "close", "volume"}
_SOURCE = "vnstock-vci"
_INDEX_SOURCE = "vnstock-vci-index"
_INDEX_SYMBOLS = frozenset({"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"})
_MAX_LOOKBACK_ROWS = 300


def _now_market() -> datetime:
    return datetime.now(_MARKET_TZ)


def _is_index(symbol: str) -> bool:
    """Return whether symbol is a documented domestic Vnstock market index."""
    return symbol.strip().upper() in _INDEX_SYMBOLS


def _parse_date(value: str | date, field: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD format") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD format")
    return parsed


def _check_configuration() -> None:
    if importlib.util.find_spec("vnstock") is None:
        raise VendorNotConfiguredError(
            "Vnstock is not installed. Install Vnstock V5 from its official package index "
            "according to docs/vietnam-market-data-contract.md before selecting this source."
        )


def _market_client(symbol: str):
    _check_configuration()
    try:
        from vnstock import Market
    except ImportError as exc:
        raise VendorNotConfiguredError(
            "Vnstock could not be imported. Check the installation for this Python environment."
        ) from exc
    try:
        market = Market()
        if _is_index(symbol):
            return market.index(symbol)
        return market.equity(symbol)
    except Exception as exc:
        raise VendorUnavailableError(
            f"Vnstock market client initialization failed ({type(exc).__name__})."
        ) from exc


def _validate_frame(frame: object, symbol: str) -> list[dict[str, object]]:
    if frame is None or bool(getattr(frame, "empty", False)):
        raise NoMarketDataError(symbol, symbol, "Vnstock VCI returned no OHLCV rows")

    attrs = getattr(frame, "attrs", None)
    if not isinstance(attrs, dict) and not hasattr(attrs, "get"):
        raise VendorUnavailableError(
            "Vnstock OHLCV response lacks source metadata; refusing to infer its source."
        )
    actual_source = attrs.get("source")
    if str(actual_source or "").strip().lower() != "vci":
        raise VendorUnavailableError(
            f"Vnstock OHLCV metadata source is {actual_source!r}; expected 'vci'."
        )
    actual_symbol = attrs.get("symbol")
    if actual_symbol is not None and str(actual_symbol).strip().upper() != symbol:
        raise VendorUnavailableError(
            f"Vnstock OHLCV metadata ticker is {actual_symbol!r}; expected {symbol!r}."
        )

    columns = {str(name) for name in getattr(frame, "columns", ())}
    if not _REQUIRED_COLUMNS.issubset(columns):
        missing = sorted(_REQUIRED_COLUMNS - columns)
        raise VendorUnavailableError(
            f"Vnstock OHLCV response is missing required column(s): {', '.join(missing)}."
        )
    to_dict = getattr(frame, "to_dict", None)
    if not callable(to_dict):
        raise VendorUnavailableError("Vnstock OHLCV response does not support to_dict('records').")
    try:
        records = to_dict("records")
    except Exception as exc:
        raise VendorUnavailableError(
            f"Vnstock OHLCV response could not be read ({type(exc).__name__})."
        ) from exc
    if not isinstance(records, list) or any(not hasattr(row, "get") for row in records):
        raise VendorUnavailableError("Vnstock OHLCV records must be a list of row mappings.")
    return records


def _row_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_python = getattr(value, "to_pydatetime", None)
    if callable(to_python):
        converted = to_python()
        if isinstance(converted, datetime):
            return converted.date()
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"unrecognized Vnstock OHLCV time value: {value!r}") from exc
        return dt.date()


def _decimal(
    value: object, field: str, *, scale: Decimal, require_integral: bool
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Vnstock OHLCV {field} is not numeric") from exc
    if not result.is_finite():
        raise ValueError(f"Vnstock OHLCV {field} must be finite")
    result *= scale
    if result <= 0:
        raise ValueError(f"Vnstock OHLCV {field} must be positive")
    if require_integral:
        if result != result.to_integral_value():
            raise ValueError(
                f"Vnstock OHLCV {field} does not convert exactly to whole VND/share"
            )
        return result.quantize(Decimal("1"))
    return result


def _volume(value: object) -> int:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Vnstock OHLCV volume is not numeric") from exc
    if not result.is_finite() or result < 0 or result != result.to_integral_value():
        raise ValueError("Vnstock OHLCV volume must be a non-negative integer")
    return int(result)


def _fetch_current_bars(
    symbol: str,
    start_date: str | date,
    end_date: str | date,
) -> tuple[list[MarketBar], datetime]:
    """Fetch VCI rows for a current-date analysis with honest retrieval-time provenance."""
    normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not normalized or not normalized.isalnum() or not 2 <= len(normalized) <= 12:
        raise ValueError("symbol must contain 2-12 letters/digits")
    start = _parse_date(start_date, "start_date")
    requested_end = _parse_date(end_date, "end_date")
    fetched_at = _now_market()
    today = fetched_at.date()
    if requested_end != today:
        raise VendorUnavailableError(
            "Vnstock VCI market-data integration is current-date only. Backdated requests are "
            "blocked because historical first-availability and adjustment vintage are not known."
        )

    complete_end = (
        today
        if fetched_at.timetz().replace(tzinfo=None) >= _FINAL_DAILY_BAR_TIME
        else today - timedelta(days=1)
    )
    if start > complete_end:
        raise NoMarketDataError(
            normalized, normalized,
            "requested range contains no completed daily bars at the current time",
        )

    index_symbol = _is_index(normalized)
    price_scale = Decimal(1) if index_symbol else _PRICE_SCALE
    client = _market_client(normalized)
    try:
        frame = client.ohlcv(
            start=start.isoformat(),
            end=complete_end.isoformat(),
            interval="1D",
            source="vci",
            floating=None,
        )
    except (NoMarketDataError, VendorNotConfiguredError, VendorUnavailableError):
        raise
    except Exception as exc:
        raise VendorUnavailableError(
            f"Vnstock VCI OHLCV request failed ({type(exc).__name__}); "
            "check package/source entitlement and API availability."
        ) from exc

    records = _validate_frame(frame, normalized)
    bars = []
    seen: set[date] = set()
    for row in records:
        try:
            day = _row_date(row.get("time"))
        except (TypeError, ValueError) as exc:
            raise VendorUnavailableError(
                f"Vnstock VCI returned an invalid OHLCV time value ({type(exc).__name__})."
            ) from exc
        if day < start or day > complete_end:
            continue
        if day in seen:
            raise VendorUnavailableError(
                f"Vnstock VCI returned duplicate daily bars for {normalized} on {day}."
            )
        seen.add(day)
        try:
            bars.append(MarketBar(
                symbol=normalized,
                timestamp=datetime.combine(day, time(15, 0), tzinfo=_MARKET_TZ),
                open=_decimal(
                    row.get("open"), "open", scale=price_scale,
                    require_integral=not index_symbol,
                ),
                high=_decimal(
                    row.get("high"), "high", scale=price_scale,
                    require_integral=not index_symbol,
                ),
                low=_decimal(
                    row.get("low"), "low", scale=price_scale,
                    require_integral=not index_symbol,
                ),
                close=_decimal(
                    row.get("close"), "close", scale=price_scale,
                    require_integral=not index_symbol,
                ),
                volume=_volume(row.get("volume")),
                source=_INDEX_SOURCE if index_symbol else _SOURCE,
                available_at=fetched_at,
            ))
        except (TypeError, ValueError) as exc:
            raise VendorUnavailableError(
                f"Vnstock VCI returned an invalid OHLCV row for {normalized} on {day}: {exc}"
            ) from exc

    if not bars:
        raise NoMarketDataError(
            normalized, normalized, f"Vnstock VCI returned no daily bars between {start} and {complete_end}"
        )
    return sorted(bars, key=lambda bar: bar.timestamp), fetched_at


def _format_csv(bars: list[MarketBar], symbol: str, title: str, fetched_at: datetime) -> str:
    is_index = _is_index(symbol)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Date", "Open", "High", "Low", "Close", "Volume"))
    for bar in bars:
        price_digits = 2 if is_index else 0
        writer.writerow((
            bar.timestamp.date().isoformat(),
            _format_decimal(bar.open, digits=price_digits),
            _format_decimal(bar.high, digits=price_digits),
            _format_decimal(bar.low, digits=price_digits),
            _format_decimal(bar.close, digits=price_digits),
            bar.volume,
        ))
    if is_index:
        source_label = "Vnstock VCI domestic index"
        unit_notice = "# Index OHLC values are measured in index points; no price scaling was applied.\n"
        source_notice = "# Domestic index source: VCI; values from different sources may differ.\n"
    else:
        source_label = "Vnstock VCI equity"
        unit_notice = "# OHLC prices converted from the source's thousand-VND unit to VND/share.\n"
        source_notice = "# VCI's corporate-action-adjusted history can differ from KBS/Yahoo history.\n"
    return (
        f"# {title} for {symbol} from {source_label}\n"
        f"# Retrieved at: {fetched_at.isoformat()}\n"
        + unit_notice
        + source_notice
        + "# Fetch-time availability is not historical first-publication time; do not use for historical PIT backtests.\n\n"
        + output.getvalue()
    )


def get_vnstock_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Router target for domestic-stock OHLCV or explicitly supported domestic indices."""
    bars, fetched_at = _fetch_current_bars(symbol, start_date, end_date)
    return _format_csv(bars, symbol.strip().upper(), "Read-only daily OHLCV", fetched_at)


def get_vnstock_indicators(
    symbol: str, indicator: str, curr_date: str, look_back_days: int = 30
) -> str:
    """Router target for indicators computed from the same VCI OHLCV source."""
    if (
        isinstance(look_back_days, bool)
        or not isinstance(look_back_days, int)
        or not 1 <= look_back_days <= _MAX_LOOKBACK_ROWS
    ):
        raise ValueError(f"look_back_days must be an integer from 1 to {_MAX_LOOKBACK_ROWS}")
    as_of = _parse_date(curr_date, "curr_date")
    start = as_of - timedelta(days=min(1300, max(450, look_back_days * 3 + 450)))
    bars, fetched_at = _fetch_current_bars(symbol, start, as_of)
    try:
        points = _indicator_series(bars, indicator)
    except ValueError:
        raise
    if not points:
        raise NoMarketDataError(symbol, symbol, f"not enough Vnstock VCI bars to calculate {indicator!r}")
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Date", indicator.strip().lower()))
    for point in points[-look_back_days:]:
        writer.writerow((point.timestamp.date().isoformat(), _format_decimal(point.value)))
    return (
        f"# Vnstock VCI indicator {indicator.strip().lower()} for {symbol.strip().upper()}\n"
        f"# Retrieved at: {fetched_at.isoformat()}\n"
        "# Price series is normalized to VND/share before indicator calculation.\n"
        "# Fetch-time availability is not historical first-publication time.\n\n"
        + output.getvalue()
    )


def build_vnstock_market_snapshot(
    symbol: str, as_of_date: str, look_back_days: int = 30
) -> str:
    """Deterministic OHLCV snapshot and indicators from one VCI price response."""
    if isinstance(look_back_days, bool) or not isinstance(look_back_days, int) or look_back_days < 1:
        raise ValueError("look_back_days must be a positive integer")
    as_of = _parse_date(as_of_date, "as_of_date")
    bars, fetched_at = _fetch_current_bars(
        symbol, as_of - timedelta(days=500), as_of
    )
    latest = bars[-1]
    indicator_values = {}
    for name in _SNAPSHOT_INDICATORS:
        points = _indicator_series(bars, name)
        indicator_values[name] = _format_decimal(points[-1].value) if points else "N/A (not enough bars)"
    recent = bars[-min(look_back_days, 30):]
    lines = [
        f"## Verified Vnstock VCI market data snapshot for {symbol.strip().upper()}",
        "",
        f"- Requested as-of date: {as_of.isoformat()}",
        f"- Latest returned trading row: {latest.timestamp.date().isoformat()}",
        f"- Source: {latest.source}",
        f"- Retrieved at: {fetched_at.isoformat()}",
        (
            "- Index values are measured in points; no scale conversion applied."
            if _is_index(symbol)
            else "- Daily stock prices are converted from thousand VND to VND/share."
        ),
        "- VCI and KBS history may differ due to source-specific adjustment conventions.",
        "- Current-date only; historical first-publication time is unknown.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Open | {_format_decimal(latest.open, digits=2 if _is_index(symbol) else 0)} |",
        f"| High | {_format_decimal(latest.high, digits=2 if _is_index(symbol) else 0)} |",
        f"| Low | {_format_decimal(latest.low, digits=2 if _is_index(symbol) else 0)} |",
        f"| Close | {_format_decimal(latest.close, digits=2 if _is_index(symbol) else 0)} |",
        f"| Volume | {latest.volume} |",
        "",
        "### Verified technical indicators (VCI OHLCV)",
        "",
        "| Indicator | Value |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in indicator_values.items())
    close_unit = "index points" if _is_index(symbol) else "VND/share"
    price_digits = 2 if _is_index(symbol) else 0
    lines.extend([
        "",
        f"### Recent verified closes (last {len(recent)} rows)",
        "",
        f"| Date | Close ({close_unit}) |",
        "|---|---:|",
    ])
    lines.extend(
        f"| {bar.timestamp.date().isoformat()} | {_format_decimal(bar.close, digits=price_digits)} |"
        for bar in recent
    )
    lines.extend([
        "",
        "Use this snapshot for exact values when Vnstock VCI is the selected source. "
        "Do not use fetched history as point-in-time evidence for backdated analysis or backtesting.",
    ])
    return "\n".join(lines)
