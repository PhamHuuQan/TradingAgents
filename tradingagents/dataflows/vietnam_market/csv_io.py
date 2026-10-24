"""Strict CSV readers for normalized point-in-time market and fundamental records.

This layer never fetches external data, infers publication timestamps, converts
currencies, or guesses units. Input rows must already satisfy the documented
common data contracts.
"""
from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tradingagents.dataflows.vietnam_market.fundamentals import FundamentalFact
from tradingagents.dataflows.vietnam_market.models import MarketBar


class CSVDataError(ValueError):
    """Raised when a normalized CSV file is malformed or ambiguous."""


_BAR_COLUMNS = {
    "symbol", "timestamp", "open", "high", "low", "close",
    "volume", "source", "available_at",
}
_FACT_COLUMNS = {
    "symbol", "metric", "value", "unit", "period_start",
    "period_end", "source", "available_at",
}
_FACT_OPTIONAL_COLUMNS = {"published_at", "source_record_id"}


def _rows(
    path: str | Path,
    required: set[str],
    optional: set[str] | None = None,
) -> Iterator[tuple[int, dict[str, str | None]]]:
    file_path = Path(path)
    try:
        handle = file_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise CSVDataError(f"Cannot read {file_path}: {exc}") from exc

    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise CSVDataError(f"{file_path}: missing CSV header")
        normalized_headers = [name.strip() if name else "" for name in reader.fieldnames]
        if any(not name for name in normalized_headers):
            raise CSVDataError(f"{file_path}: column names must be non-empty")
        if len(set(normalized_headers)) != len(normalized_headers):
            raise CSVDataError(f"{file_path}: duplicate column names after trimming whitespace")
        reader.fieldnames = normalized_headers
        headers = set(normalized_headers)
        missing = sorted(required - headers)
        if missing:
            raise CSVDataError(
                f"{file_path}: missing required column(s): {', '.join(missing)}"
            )
        allowed = required | (optional or set())
        unknown = sorted(headers - allowed)
        # Extra columns are rejected to catch misspelled schema fields, rather
        # than silently ignoring a field the caller expected this reader to use.
        if unknown:
            raise CSVDataError(
                f"{file_path}: unexpected column(s): {', '.join(unknown)}"
            )
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise CSVDataError(
                    f"{file_path}:{line_number}: more values than CSV columns"
                )
            yield line_number, {
                (key.strip() if key else ""): value
                for key, value in row.items()
            }


def _required(
    row: dict[str, str | None], name: str, path: str | Path, line: int
) -> str:
    value = row.get(name)
    if value is None or not value.strip():
        raise CSVDataError(f"{path}:{line}: {name} must be non-empty")
    return value.strip()


def _decimal(value: str, field: str, path: str | Path, line: int) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise CSVDataError(f"{path}:{line}: {field} must be a decimal number") from exc
    if not result.is_finite():
        raise CSVDataError(f"{path}:{line}: {field} must be finite")
    return result


def _datetime(value: str, field: str, path: str | Path, line: int) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CSVDataError(
            f"{path}:{line}: {field} must be an ISO-8601 datetime with a timezone"
        ) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CSVDataError(
            f"{path}:{line}: {field} must include a timezone offset, for example +07:00 or Z"
        )
    return result


def _date(value: str, field: str, path: str | Path, line: int) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise CSVDataError(f"{path}:{line}: {field} must use YYYY-MM-DD") from exc
    return result


def read_market_bars_csv(path: str | Path) -> list[MarketBar]:
    """Read normalized OHLCV rows, allowing distinct available-at revisions."""
    bars: list[MarketBar] = []
    seen: set[tuple[str, datetime, str, datetime]] = set()
    for line, row in _rows(path, _BAR_COLUMNS):
        try:
            values = {
                "symbol": _required(row, "symbol", path, line),
                "timestamp": _datetime(_required(row, "timestamp", path, line), "timestamp", path, line),
                "open": _decimal(_required(row, "open", path, line), "open", path, line),
                "high": _decimal(_required(row, "high", path, line), "high", path, line),
                "low": _decimal(_required(row, "low", path, line), "low", path, line),
                "close": _decimal(_required(row, "close", path, line), "close", path, line),
                "volume": int(_required(row, "volume", path, line)),
                "source": _required(row, "source", path, line),
                "available_at": _datetime(
                    _required(row, "available_at", path, line), "available_at", path, line
                ),
            }
            bar = MarketBar(**values)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, CSVDataError):
                raise
            raise CSVDataError(f"{path}:{line}: invalid OHLCV record: {exc}") from exc

        key = (bar.symbol, bar.timestamp, bar.source, bar.available_at)
        if key in seen:
            raise CSVDataError(
                f"{path}:{line}: duplicate bar revision for {bar.symbol} at "
                f"{bar.timestamp.isoformat()} available {bar.available_at.isoformat()}"
            )
        seen.add(key)
        bars.append(bar)

    if not bars:
        raise CSVDataError(f"{path}: no market bars found")
    return bars


def read_fundamental_facts_csv(path: str | Path) -> list[FundamentalFact]:
    """Read normalized reported facts, retaining source and availability time."""
    facts: list[FundamentalFact] = []
    for line, row in _rows(path, _FACT_COLUMNS, _FACT_OPTIONAL_COLUMNS):
        try:
            published_text = (row.get("published_at") or "").strip()
            record_id = (row.get("source_record_id") or "").strip()
            fact = FundamentalFact(
                symbol=_required(row, "symbol", path, line),
                metric=_required(row, "metric", path, line),
                value=_decimal(_required(row, "value", path, line), "value", path, line),
                unit=_required(row, "unit", path, line),
                period_start=_date(
                    _required(row, "period_start", path, line), "period_start", path, line
                ),
                period_end=_date(
                    _required(row, "period_end", path, line), "period_end", path, line
                ),
                source=_required(row, "source", path, line),
                available_at=_datetime(
                    _required(row, "available_at", path, line), "available_at", path, line
                ),
                published_at=(
                    _datetime(published_text, "published_at", path, line)
                    if published_text else None
                ),
                source_record_id=record_id or None,
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, CSVDataError):
                raise
            raise CSVDataError(f"{path}:{line}: invalid fundamental fact: {exc}") from exc
        facts.append(fact)

    if not facts:
        raise CSVDataError(f"{path}: no fundamental facts found")
    return facts
