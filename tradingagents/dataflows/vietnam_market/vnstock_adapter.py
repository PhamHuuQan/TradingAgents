"""Normalize documented Vnstock VCI/KBS VAS statement rows into our fact contract.

This module imports no Vnstock or pandas package. The source adapter is kept
pure so normalized semantics can be tested without third-party API calls.
Only a small, explicitly named subset of VAS metrics is mapped; unknown metrics
are ignored rather than guessed.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from tradingagents.dataflows.vietnam_market.fundamentals import FundamentalFact


class VnstockNormalizationError(ValueError):
    """Raised when Vnstock statement rows cannot safely be normalized."""


_VAS_METRICS = {
    "income_statement": {
        "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY": "net_income",
    },
    "balance_sheet": {
        "BS_EQUITY": "total_equity",
    },
    "cash_flow": {
        "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES": "operating_cash_flow",
    },
}
# Backward-compatible alias for callers/tests that used the original VCI name.
_VCI_METRICS = _VAS_METRICS
_CURRENCY_UNITS = {"vnd", "vnđ", "đồng", "dong"}


def _as_records(table: object, report: str) -> list[Mapping[str, object]]:
    """Accept a list of mappings or a DataFrame-like object in long format."""
    if table is None:
        return []
    records: object
    if hasattr(table, "to_dict"):
        try:
            records = table.to_dict("records")  # type: ignore[union-attr]
        except Exception as exc:
            raise VnstockNormalizationError(
                f"{report} table must be in long format with to_dict('records') support"
            ) from exc
    else:
        records = table
    if not isinstance(records, Iterable) or isinstance(records, (str, bytes, Mapping)):
        raise VnstockNormalizationError(
            f"{report} input must be a DataFrame-like table or list of mappings"
        )
    rows: list[Mapping[str, object]] = []
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise VnstockNormalizationError(
                f"{report} row {index} is not a mapping; use format='long'"
            )
        rows.append(row)
    return rows


def _validate_table_metadata(
    table: object, *, report: str, symbol: str, source: str
) -> None:
    attrs = getattr(table, "attrs", None)
    if not isinstance(attrs, Mapping):
        return
    table_source = attrs.get("source")
    expected_source = source.removeprefix("vnstock-")
    if table_source is not None and str(table_source).strip().lower() != expected_source:
        raise VnstockNormalizationError(
            f"{report} table source metadata is {table_source!r}, expected {expected_source!r}"
        )
    table_symbol = attrs.get("symbol")
    if table_symbol is not None and str(table_symbol).strip().upper() != symbol:
        raise VnstockNormalizationError(
            f"{report} table symbol metadata is {table_symbol!r}, expected {symbol!r}"
        )
    table_format = attrs.get("format")
    if table_format is not None and str(table_format).strip().lower() != "long":
        raise VnstockNormalizationError(
            f"{report} table format metadata is {table_format!r}, expected 'long'"
        )


def _period_dates(value: object, *, report: str, row_index: int) -> tuple[date, date]:
    text = str(value).strip() if value is not None else ""
    if (
        len(text) != 7
        or text[4:6] != "-Q"
        or text[-1] not in "1234"
        or not text[:4].isdigit()
    ):
        raise VnstockNormalizationError(
            f"{report} row {row_index}: period must be a quarterly label like '2025-Q4', got {text!r}"
        )
    year = int(text[:4])
    quarter = int(text[-1])
    month = 3 * (quarter - 1) + 1
    start = date(year, month, 1)
    next_year, next_month = (year + 1, 1) if month == 10 else (year, month + 3)
    end = date.fromordinal(date(next_year, next_month, 1).toordinal() - 1)
    return start, end


def _decimal_or_missing(value: object, *, report: str, row_index: int) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "null", "na", "n/a"}:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise VnstockNormalizationError(
            f"{report} row {row_index}: value {value!r} is not numeric"
        ) from exc
    if not amount.is_finite():
        if amount.is_nan():
            return None
        raise VnstockNormalizationError(
            f"{report} row {row_index}: non-finite amount {value!r}"
        )
    return amount


def normalize_vnstock_vci_statements(
    symbol: str,
    income_statement: object,
    balance_sheet: object,
    cash_flow: object,
    fetched_at: datetime,
    *,
    source: str = "vci",
) -> list[FundamentalFact]:
    """Normalize a small, explicit subset of VAS metrics from VCI or KBS.

    fetched_at is recorded as available_at because statement rows do not include
    a historical publication/first-availability timestamp. The function must
    not be presented as recovering historical information availability.
    Both providers use Vnstock V5's documented common VAS metric IDs. For KBS,
    flow metrics remain raw period observations: callers must not sum them into
    TTM totals until standalone-quarter semantics have been independently verified.
    """
    if (
        not isinstance(symbol, str)
        or not symbol.strip().isalnum()
        or not 2 <= len(symbol.strip()) <= 12
    ):
        raise VnstockNormalizationError("symbol must contain 2-12 letters/digits")
    normalized_symbol = symbol.strip().upper()
    if (
        not isinstance(fetched_at, datetime)
        or fetched_at.tzinfo is None
        or fetched_at.utcoffset() is None
    ):
        raise VnstockNormalizationError("fetched_at must be timezone-aware")
    fetched_at = fetched_at.astimezone(UTC)
    normalized_source = source.strip().lower() if isinstance(source, str) else ""
    if normalized_source not in {"vci", "kbs"}:
        raise VnstockNormalizationError("source must be 'vci' or 'kbs'")
    source = f"vnstock-{normalized_source}"
    inputs = {
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
    }
    facts: list[FundamentalFact] = []
    seen: set[tuple[str, date, date]] = set()

    for report, table in inputs.items():
        _validate_table_metadata(table, report=report, symbol=normalized_symbol, source=source)
        records = _as_records(table, report)
        metric_map = _VAS_METRICS[report]
        for row_index, row in enumerate(records, start=1):
            item_id = str(row.get("id", "")).strip().upper()
            metric = metric_map.get(item_id)
            if metric is None:
                continue
            start, end = _period_dates(row.get("period"), report=report, row_index=row_index)
            if end > fetched_at.date():
                raise VnstockNormalizationError(
                    f"{report} row {row_index}: period {row.get('period')!r} ends after fetch date"
                )
            unit_raw = row.get("unit")
            unit = str(unit_raw).strip() if unit_raw is not None else ""
            if unit.lower() not in _CURRENCY_UNITS:
                raise VnstockNormalizationError(
                    f"{report} row {row_index}: unsupported currency unit {unit!r}; expected VND/VNĐ"
                )
            value = _decimal_or_missing(row.get("value"), report=report, row_index=row_index)
            if value is None:
                continue
            key = (metric, start, end)
            if key in seen:
                raise VnstockNormalizationError(
                    f"duplicate normalized {normalized_source.upper()} fact for {normalized_symbol}/{metric}/{row.get('period')}"
                )
            seen.add(key)
            facts.append(
                FundamentalFact(
                    symbol=normalized_symbol,
                    metric=metric,
                    value=value,
                    unit="VND",
                    period_start=start,
                    period_end=end,
                    source=source,
                    available_at=fetched_at,
                    published_at=None,
                    source_record_id=None,
                )
            )
    if not facts:
        raise VnstockNormalizationError(
            f"No supported {normalized_source.upper()} statement facts found. Check Vnstock version, source, "
            "format='long', and exact semantic IDs."
        )
    return sorted(
        facts,
        key=lambda fact: (fact.period_end, fact.metric, fact.period_start),
    )
