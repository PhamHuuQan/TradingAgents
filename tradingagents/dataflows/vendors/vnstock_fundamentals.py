"""Optional, current-date-only Vnstock VCI fundamentals vendor.

The standard Vnstock V5 Fundamental API returns VAS-normalized long-format
statements. This adapter validates source metadata and blocks historical
as-of dates because fetched statements do not carry their first-publication
time. It never calls premium ratio() endpoints and never infers missing share
counts or capex.
"""
from __future__ import annotations

import logging
import os
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

_REQUIRED_COLUMNS = {"period", "id", "unit", "value"}
_VALID_SOURCES = {"vci", "kbs"}
_DEFAULT_SOURCES = ("vci", "kbs")
_SOURCES_ENV = "TRADINGAGENTS_VNSTOCK_FUNDAMENTALS_SOURCES"
logger = logging.getLogger(__name__)


def _configured_sources() -> tuple[str, ...]:
    """Return the explicitly ordered, validated Vnstock statement source chain."""
    raw = os.getenv(_SOURCES_ENV, ",".join(_DEFAULT_SOURCES)).strip()
    sources = tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip()))
    if not sources:
        sources = _DEFAULT_SOURCES
    invalid = [source for source in sources if source not in _VALID_SOURCES]
    if invalid:
        raise VendorNotConfiguredError(
            f"{_SOURCES_ENV} only accepts comma-separated vci and/or kbs; "
            f"received: {', '.join(invalid)}"
        )
    return sources


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
            f"Vnstock client initialization failed ({type(exc).__name__}); "
            "check installation, network access, and source entitlement."
        ) from exc


def _validate_frame(frame: object, symbol: str, report: str, source: str = "vci") -> None:
    expected_source = source.strip().lower()
    if expected_source not in _VALID_SOURCES:
        raise VendorNotConfiguredError(f"Unsupported Vnstock source: {expected_source!r}")
    if frame is None or bool(getattr(frame, "empty", False)):
        raise NoMarketDataError(
            symbol, symbol, f"Vnstock {expected_source.upper()} returned no {report} rows"
        )
    # Vnstock's VCI provider does not consistently attach attrs; KBS attaches
    # source/symbol but may omit format. Explicit source= never auto-switches
    # providers, so missing metadata is acceptable when the request is explicit
    # and the returned schema is long-form. Any metadata that IS present must match.
    attrs = getattr(frame, "attrs", None)
    if isinstance(attrs, Mapping):
        frame_source = attrs.get("source")
        if frame_source not in (None, "") and str(frame_source).strip().lower() != expected_source:
            raise VendorUnavailableError(
                f"Vnstock {report} metadata source is {frame_source!r}; expected '{expected_source}'"
            )
        frame_symbol = attrs.get("symbol")
        if frame_symbol not in (None, "") and str(frame_symbol).strip().upper() != symbol:
            raise VendorUnavailableError(
                f"Vnstock {report} metadata ticker is {frame_symbol!r}; expected {symbol!r}"
            )
        frame_format = attrs.get("format")
        if frame_format not in (None, "") and str(frame_format).strip().lower() != "long":
            raise VendorUnavailableError(
                f"Vnstock {report} metadata format is {frame_format!r}; expected 'long'"
            )

    columns = {str(name) for name in getattr(frame, "columns", ())}
    if not _REQUIRED_COLUMNS.issubset(columns):
        missing = sorted(_REQUIRED_COLUMNS - columns)
        raise VendorUnavailableError(
            f"Vnstock {report} response is missing required long-format columns: {', '.join(missing)}"
        )
    if not callable(getattr(frame, "to_csv", None)) or not callable(getattr(frame, "to_dict", None)):
        raise VendorUnavailableError(
            f"Vnstock {report} response is not a supported DataFrame-like long-format table"
        )


def _fetch_frame(client: Any, name: str, symbol: str, period: str, source: str = "vci") -> object:
    source = source.strip().lower()
    if source not in _VALID_SOURCES:
        raise VendorNotConfiguredError(f"Unsupported Vnstock source: {source!r}")
    getter = getattr(client, name, None)
    if not callable(getter):
        raise VendorUnavailableError(f"Installed Vnstock client does not support {name}()")
    try:
        frame = getter(period=period, format="long", source=source)
    except (NoMarketDataError, VendorNotConfiguredError, VendorUnavailableError):
        raise
    except Exception as exc:
        raise VendorUnavailableError(
            f"Vnstock {source.upper()} {name} request failed ({type(exc).__name__}); "
            "check source availability, API-key status, and package compatibility."
        ) from exc
    _validate_frame(frame, symbol, name, source)
    return frame


def _fetch_frame_with_fallback(
    client: Any, name: str, symbol: str, period: str
) -> tuple[object, str]:
    """Try configured sources in order and return the frame plus its real source."""
    errors: list[tuple[str, Exception]] = []
    for source in _configured_sources():
        try:
            return _fetch_frame(client, name, symbol, period, source), source
        except (NoMarketDataError, VendorNotConfiguredError, VendorUnavailableError) as exc:
            logger.warning("Vnstock %s unavailable for %s/%s: %s", source, symbol, name, exc)
            errors.append((source, exc))
    details = "; ".join(f"{source}: {error}" for source, error in errors)
    if any(not isinstance(error, NoMarketDataError) for _, error in errors):
        raise VendorUnavailableError(
            f"All configured Vnstock sources failed for {name} ({details})"
        )
    raise NoMarketDataError(symbol, symbol, f"Vnstock sources returned no {name} rows ({details})")


def _csv_response(frame: object, symbol: str, title: str, period: str, source: str) -> str:
    fetched_at = datetime.now(UTC)
    try:
        csv_text = frame.to_csv(index=False)
    except Exception as exc:
        raise VendorUnavailableError(
            f"Could not serialize Vnstock {title} response ({type(exc).__name__})"
        ) from exc
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise NoMarketDataError(symbol, symbol, f"Vnstock {source.upper()} returned empty {title} CSV")
    attrs = getattr(frame, "attrs", None)
    observed_source = attrs.get("source") if isinstance(attrs, Mapping) else None
    if observed_source not in (None, "") and str(observed_source).strip().lower() == source:
        source_evidence = "confirmed by response metadata"
    else:
        source_evidence = (
            "determined by the explicit source argument; this provider response "
            "does not expose a source attribute"
        )
    return (
        f"# {title} for {symbol} from Vnstock {source.upper()}\n"
        f"# Provider source: vnstock-{source}; source evidence: {source_evidence}\n"
        f"# Period: {period}; retrieved at: {fetched_at.isoformat()}\n"
        "# Vnstock explicit source requests do not silently switch to another provider.\n"
        "# Availability is fetch-time only; this response has no historical first-publication time.\n"
        "# Use only for current-date analysis, not historical point-in-time backtests.\n\n"
        + csv_text
    )


def get_vnstock_balance_sheet(
    ticker: str, freq: str = "quarterly", as_of_date: str | None = None
) -> str:
    """Return the validated VCI/KBS balance sheet as long-format CSV."""
    symbol = _symbol(ticker)
    period = _period(freq)
    withheld = _guard_as_of(as_of_date, symbol, "Balance Sheet")
    if withheld:
        return withheld
    client = _fundamental_client(symbol)
    frame, source = _fetch_frame_with_fallback(client, "balance_sheet", symbol, period)
    return _csv_response(frame, symbol, "Balance Sheet", period, source)


def get_vnstock_cashflow(
    ticker: str, freq: str = "quarterly", as_of_date: str | None = None
) -> str:
    """Return the validated VCI/KBS cash-flow statement as long-format CSV."""
    symbol = _symbol(ticker)
    period = _period(freq)
    withheld = _guard_as_of(as_of_date, symbol, "Cash Flow")
    if withheld:
        return withheld
    client = _fundamental_client(symbol)
    frame, source = _fetch_frame_with_fallback(client, "cash_flow", symbol, period)
    return _csv_response(frame, symbol, "Cash Flow", period, source)


def get_vnstock_income_statement(
    ticker: str, freq: str = "quarterly", as_of_date: str | None = None
) -> str:
    """Return the validated VCI/KBS income statement as long-format CSV."""
    symbol = _symbol(ticker)
    period = _period(freq)
    withheld = _guard_as_of(as_of_date, symbol, "Income Statement")
    if withheld:
        return withheld
    client = _fundamental_client(symbol)
    frame, source = _fetch_frame_with_fallback(client, "income_statement", symbol, period)
    return _csv_response(frame, symbol, "Income Statement", period, source)


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
    """Summarize validated VCI/KBS facts without silently mixing source data."""
    symbol = _symbol(ticker)
    withheld = _guard_as_of(as_of_date, symbol, "Fundamentals")
    if withheld:
        return withheld

    client = _fundamental_client(symbol)
    fetched_at = datetime.now(UTC)
    errors: list[tuple[str, Exception]] = []
    facts: list[FundamentalFact] | None = None
    selected_source: str | None = None

    # Keep the entire three-statement summary on one provider. If any VCI report
    # fails, discard that partial set and retry all three from KBS.
    for source in _configured_sources():
        try:
            income = _fetch_frame(client, "income_statement", symbol, "quarter", source)
            balance = _fetch_frame(client, "balance_sheet", symbol, "quarter", source)
            cash_flow = _fetch_frame(client, "cash_flow", symbol, "quarter", source)
            facts = normalize_vnstock_vci_statements(
                symbol, income, balance, cash_flow, fetched_at, source=source
            )
            selected_source = source
            break
        except (
            NoMarketDataError,
            VendorNotConfiguredError,
            VendorUnavailableError,
            VnstockNormalizationError,
        ) as exc:
            logger.warning("Vnstock %s statement set unavailable for %s: %s", source, symbol, exc)
            errors.append((source, exc))

    if facts is None or selected_source is None:
        details = "; ".join(f"{source}: {error}" for source, error in errors)
        if any(not isinstance(error, NoMarketDataError) for _, error in errors):
            raise VendorUnavailableError(
                f"All configured Vnstock sources failed to provide a validated three-statement set ({details})"
            )
        raise NoMarketDataError(
            symbol, symbol, f"Vnstock sources returned no complete three-statement set ({details})"
        )

    latest_equity = max(
        (fact for fact in facts if fact.metric == "total_equity"),
        key=lambda fact: fact.period_end,
        default=None,
    )
    # VCI quarterly flow semantics are verified as standalone quarters. KBS is
    # supported for raw statements and point-in-time balances, but its flow
    # semantics are deliberately not assumed when producing TTM totals.
    net_income_ttm = _ttm_sum(facts, "net_income") if selected_source == "vci" else None
    operating_cash_flow_ttm = (
        _ttm_sum(facts, "operating_cash_flow") if selected_source == "vci" else None
    )

    lines = [
        f"# Current {selected_source.upper()} fundamentals for {symbol}",
        "",
        f"- Source: vnstock-{selected_source}",
        "- Retrieval library: Vnstock; this is not the issuer filing URL.",
        f"- Retrieved at: {fetched_at.isoformat()}",
        "- Statement periods are reported by the source; this fetch timestamp is not their historical publication time.",
        "- This is a current snapshot. It is withheld for historical as-of dates.",
        "",
        f"## Normalized {selected_source.upper()} facts",
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
    elif selected_source == "kbs":
        lines.append(
            "- TTM net income: not derived from KBS; standalone-quarter versus cumulative-flow semantics have not been verified."
        )
    else:
        lines.append("- TTM net income: unavailable; four contiguous standalone quarter facts are required.")
    if operating_cash_flow_ttm is not None:
        amount, start, end = operating_cash_flow_ttm
        lines.append(f"- TTM operating cash flow: {amount:,.0f} VND ({start}..{end}).")
    elif selected_source == "kbs":
        lines.append(
            "- TTM operating cash flow: not derived from KBS; standalone-quarter versus cumulative-flow semantics have not been verified."
        )
    else:
        lines.append("- TTM operating cash flow: unavailable; four contiguous standalone quarter facts are required.")
    if latest_equity is not None:
        lines.append(
            f"- Latest total equity: {latest_equity.value:,.0f} VND "
            f"(period end {latest_equity.period_end})."
        )
    else:
        lines.append(f"- Total equity: unavailable from the supported {selected_source.upper()} mappings.")

    lines.extend(
        [
            "",
            "## Metrics not inferred",
            "",
            f"This {selected_source.upper()} mapping does not currently validate shares outstanding, weighted-average "
            "shares, or capital expenditure. Therefore it does not claim EPS, P/E, P/B, ROE, "
            "market capitalization, or free cash flow. Add those metrics only after their "
            "semantic IDs, unit/sign conventions, and source coverage are verified.",
            "",
            "Historical backtests must not use these fetched rows as point-in-time observations: "
            "available_at records retrieval time, not first-publication time.",
        ]
    )
    return "\n".join(lines)
