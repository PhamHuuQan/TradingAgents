"""Optional, current-date-only Vnstock VCI fundamentals vendor.

The standard Vnstock V5 Fundamental API returns VAS-normalized long-format
statements. This adapter validates source metadata and blocks historical
as-of dates because fetched statements do not carry their first-publication
time. It never calls premium ratio() endpoints and never infers missing share
counts or capex.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from tradingagents.dataflows.date_window import (
    get_current_date,
    withhold_undated_statements,
)
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.vietnam_market.fundamentals import FundamentalFact
from tradingagents.dataflows.vietnam_market.vnstock_adapter import (
    VnstockNormalizationError,
    normalize_vnstock_vci_statements,
)

_SOURCE = "vnstock-vci"
_REQUIRED_COLUMNS = {"period", "id", "unit", "value"}


def _symbol(value: str) -> str:
    normalized = value.strip().upper() if isinstance(value, str) else ""
    if not normalized or not normalized.isalnum() or not 2 <= len(normalized) <= 12:
        raise ValueError("ticker must contain 2-12 letters/digits")
    return normalized


def _period(freq: str) -> str:
    normalized = freq.strip().lower() if isinstance(freq, str) else ""
    if normalized in {"quarter", "quarterly"}:
        return "quarter"
    if normalized in {"year", "annual", "yearly"}:
        return "year"
    raise ValueError("freq must be 'quarterly' or 'annual'")


def _guard_as_of(as_of_date: str | None, symbol: str, report: str) -> str | None:
    """Block future dates and withhold undated live statements for historical runs."""
    if as_of_date is not None:
        normalized = str(as_of_date)
        try:
            parsed = date.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("as_of_date must use YYYY-MM-DD format") from exc
        if parsed.isoformat() != normalized:
            raise ValueError("as_of_date must use YYYY-MM-DD format")
        if normalized > get_current_date():
            raise ValueError("Vnstock live statements do not support future as-of dates")
        return withhold_undated_statements(normalized, symbol, report)
    return None


def _fundamental_client(symbol: str) -> Any:
    """Import the optional package lazily so base-install users keep working."""
    try:
        from vnstock import Fundamental
    except ImportError as exc:
        raise VendorNotConfiguredError(
            "Vnstock is not installed in this Python environment. Install it from the "
            "official Vnstock package index as described in docs/vietnam-market-data-contract.md."
        ) from exc
    try:
        return Fundamental().equity(symbol)
    except Exception as exc:
        raise VendorUnavailableError(
            f"Vnstock VCI client initialization failed ({type(exc).__name__}); "
            "check installation, network access, and source entitlement."
        ) from exc


def _validate_frame(frame: object, symbol: str, report: str) -> None:
    if frame is None or bool(getattr(frame, "empty", False)):
        raise NoMarketDataError(symbol, symbol, f"Vnstock VCI returned no {report} rows")
    attrs = getattr(frame, "attrs", None)
    if isinstance(attrs, Mapping):
        source = attrs.get("source")
        if source is not None and str(source).strip().lower() != "vci":
            raise VendorUnavailableError(
                f"Vnstock {report} metadata source is {source!r}; expected 'vci'"
            )
        frame_symbol = attrs.get("symbol")
        if frame_symbol is not None and str(frame_symbol).strip().upper() != symbol:
            raise VendorUnavailableError(
                f"Vnstock {report} metadata ticker is {frame_symbol!r}; expected {symbol!r}"
            )
        frame_format = attrs.get("format")
        if frame_format is not None and str(frame_format).strip().lower() != "long":
            raise VendorUnavailableError(
                f"Vnstock {report} metadata format is {frame_format!r}; expected 'long'"
            )

    columns = {str(name) for name in getattr(frame, "columns", ())}
    if columns and not _REQUIRED_COLUMNS.issubset(columns):
        missing = sorted(_REQUIRED_COLUMNS - columns)
        raise VendorUnavailableError(
            f"Vnstock {report} response is missing required long-format columns: {', '.join(missing)}"
        )
    if not callable(getattr(frame, "to_csv", None)) or not callable(getattr(frame, "to_dict", None)):
        raise VendorUnavailableError(
            f"Vnstock {report} response is not a supported DataFrame-like long-format table"
        )


def _fetch_frame(client: Any, name: str, symbol: str, period: str) -> object:
    getter = getattr(client, name, None)
    if not callable(getter):
        raise VendorUnavailableError(f"Installed Vnstock client does not support {name}()")
    try:
        frame = getter(period=period, format="long", source="vci")
    except (NoMarketDataError, VendorNotConfiguredError, VendorUnavailableError):
        raise
    except Exception as exc:
        raise VendorUnavailableError(
            f"Vnstock VCI {name} request failed ({type(exc).__name__}); "
            "check source availability and package compatibility."
        ) from exc
    _validate_frame(frame, symbol, name)
    return frame


def _csv_response(frame: object, symbol: str, title: str, period: str) -> str:
    fetched_at = datetime.now(UTC)
    try:
        csv_text = frame.to_csv(index=False)
    except Exception as exc:
        raise VendorUnavailableError(
            f"Could not serialize Vnstock {title} response ({type(exc).__name__})"
        ) from exc
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise NoMarketDataError(symbol, symbol, f"Vnstock VCI returned empty {title} CSV")
    return (
        f"# {title} for {symbol} from Vnstock VCI\n"
        f"# Period: {period}; retrieved at: {fetched_at.isoformat()}\n"
        "# Availability is fetch-time only; this response has no historical first-publication time.\n"
        "# Use only for current-date analysis, not historical point-in-time backtests.\n\n"
        + csv_text
    )


def get_vnstock_balance_sheet(
    ticker: str, freq: str = "quarterly", as_of_date: str | None = None
) -> str:
    """Return the validated VCI balance sheet as long-format CSV."""
    symbol = _symbol(ticker)
    period = _period(freq)
    withheld = _guard_as_of(as_of_date, symbol, "Balance Sheet")
    if withheld:
        return withheld
    client = _fundamental_client(symbol)
    frame = _fetch_frame(client, "balance_sheet", symbol, period)
    return _csv_response(frame, symbol, "Balance Sheet", period)


def get_vnstock_cashflow(
    ticker: str, freq: str = "quarterly", as_of_date: str | None = None
) -> str:
    """Return the validated VCI cash-flow statement as long-format CSV."""
    symbol = _symbol(ticker)
    period = _period(freq)
    withheld = _guard_as_of(as_of_date, symbol, "Cash Flow")
    if withheld:
        return withheld
    client = _fundamental_client(symbol)
    frame = _fetch_frame(client, "cash_flow", symbol, period)
    return _csv_response(frame, symbol, "Cash Flow", period)


def get_vnstock_income_statement(
    ticker: str, freq: str = "quarterly", as_of_date: str | None = None
) -> str:
    """Return the validated VCI income statement as long-format CSV."""
    symbol = _symbol(ticker)
    period = _period(freq)
    withheld = _guard_as_of(as_of_date, symbol, "Income Statement")
    if withheld:
        return withheld
    client = _fundamental_client(symbol)
    frame = _fetch_frame(client, "income_statement", symbol, period)
    return _csv_response(frame, symbol, "Income Statement", period)


def _ttm_sum(
    facts: list[FundamentalFact], metric: str
) -> tuple[Decimal, date, date] | None:
    candidates = sorted(
        (
            fact
            for fact in facts
            if fact.metric == metric
            and fact.unit == "VND"
            and 80 <= (fact.period_end - fact.period_start).days + 1 <= 100
        ),
        key=lambda fact: (fact.period_end, fact.period_start),
    )
    if len(candidates) < 4:
        return None
    quarters = candidates[-4:]
    for previous, current in zip(quarters, quarters[1:], strict=False):
        if (current.period_start - previous.period_end).days != 1:
            return None
    return (
        sum((fact.value for fact in quarters), Decimal(0)),
        quarters[0].period_start,
        quarters[-1].period_end,
    )


def get_vnstock_fundamentals(ticker: str, as_of_date: str | None = None) -> str:
    """Summarize explicitly mapped VCI facts; do not call premium ratio endpoints."""
    symbol = _symbol(ticker)
    withheld = _guard_as_of(as_of_date, symbol, "Fundamentals")
    if withheld:
        return withheld

    client = _fundamental_client(symbol)
    income = _fetch_frame(client, "income_statement", symbol, "quarter")
    balance = _fetch_frame(client, "balance_sheet", symbol, "quarter")
    cash_flow = _fetch_frame(client, "cash_flow", symbol, "quarter")
    fetched_at = datetime.now(UTC)
    try:
        facts = normalize_vnstock_vci_statements(
            symbol, income, balance, cash_flow, fetched_at
        )
    except VnstockNormalizationError as exc:
        raise VendorUnavailableError(
            f"Vnstock VCI data could not be normalized safely: {exc}"
        ) from exc

    latest_equity = max(
        (fact for fact in facts if fact.metric == "total_equity"),
        key=lambda fact: fact.period_end,
        default=None,
    )
    net_income_ttm = _ttm_sum(facts, "net_income")
    operating_cash_flow_ttm = _ttm_sum(facts, "operating_cash_flow")

    lines = [
        f"# Current VCI fundamentals for {symbol}",
        "",
        f"- Source: {_SOURCE}",
        f"- Retrieved at: {fetched_at.isoformat()}",
        "- Statement periods are reported by the source; this fetch timestamp is not their historical publication time.",
        "- This is a current snapshot. It is withheld for historical as-of dates.",
        "",
        "## Normalized VCI facts",
        "",
        "| Metric | Period | Value | Unit |",
        "|---|---|---:|---|",
    ]
    for fact in sorted(facts, key=lambda item: (item.metric, item.period_end, item.period_start)):
        lines.append(
            f"| {fact.metric} | {fact.period_start}..{fact.period_end} | "
            f"{fact.value:,.0f} | {fact.unit} |"
        )

    lines.extend(["", "## Derived summary (only where inputs are complete)", ""])
    if net_income_ttm is not None:
        amount, start, end = net_income_ttm
        lines.append(f"- TTM parent-company net income: {amount:,.0f} VND ({start}..{end}).")
    else:
        lines.append("- TTM net income: unavailable; four contiguous standalone quarter facts are required.")
    if operating_cash_flow_ttm is not None:
        amount, start, end = operating_cash_flow_ttm
        lines.append(f"- TTM operating cash flow: {amount:,.0f} VND ({start}..{end}).")
    else:
        lines.append("- TTM operating cash flow: unavailable; four contiguous standalone quarter facts are required.")
    if latest_equity is not None:
        lines.append(
            f"- Latest total equity: {latest_equity.value:,.0f} VND "
            f"(period end {latest_equity.period_end})."
        )
    else:
        lines.append("- Total equity: unavailable from the supported VCI mappings.")

    lines.extend(
        [
            "",
            "## Metrics not inferred",
            "",
            "This VCI mapping does not currently validate shares outstanding, weighted-average "
            "shares, or capital expenditure. Therefore it does not claim EPS, P/E, P/B, ROE, "
            "market capitalization, or free cash flow. Add those metrics only after their "
            "semantic IDs, unit/sign conventions, and source coverage are verified.",
            "",
            "Historical backtests must not use these fetched rows as point-in-time observations: "
            "available_at records retrieval time, not first-publication time.",
        ]
    )
    return "\n".join(lines)
