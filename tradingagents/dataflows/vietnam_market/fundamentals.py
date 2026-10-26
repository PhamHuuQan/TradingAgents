"""Point-in-time fundamental facts with revision-aware as-of selection.

The module does not scrape filings or infer reporting dates. Callers must supply
the actual data-availability time from a trusted source; publication dates alone
are not proof that a strategy could access a fact at that time.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}$")
_METRIC_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class FundamentalDataValidationError(ValueError):
    """Raised when a reported fundamental fact is malformed."""


class AmbiguousFundamentalFactError(FundamentalDataValidationError):
    """Raised when one source has conflicting facts with the same availability time."""


@dataclass(frozen=True, slots=True)
class FundamentalFact:
    """One reported fundamental value for one specific reporting period.

    unit must state the value's unit (for example VND, VND/share, shares, ratio
    or percent). Values are not currency-converted or rescaled. available_at is
    when this source made this version available to a strategy, not when the
    reporting period ended.

    A correction/restatement is represented as another fact with the same key
    and a later available_at. The earlier version remains valid for as-of queries
    before the correction became available.
    """

    symbol: str
    metric: str
    value: Decimal
    unit: str
    period_start: date
    period_end: date
    source: str
    available_at: datetime
    published_at: datetime | None = None
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper() if isinstance(self.symbol, str) else ""
        if not _SYMBOL_RE.fullmatch(symbol):
            raise FundamentalDataValidationError(
                f"symbol must be 2-12 letters/digits, got {self.symbol!r}"
            )
        object.__setattr__(self, "symbol", symbol)

        metric = self.metric.strip().lower() if isinstance(self.metric, str) else ""
        if not _METRIC_RE.fullmatch(metric):
            raise FundamentalDataValidationError(
                f"metric must be an identifier such as net_income, got {self.metric!r}"
            )
        object.__setattr__(self, "metric", metric)

        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise FundamentalDataValidationError("value must be a finite Decimal")

        if not isinstance(self.unit, str) or not self.unit.strip():
            raise FundamentalDataValidationError("unit must be non-empty")
        object.__setattr__(self, "unit", self.unit.strip())

        if not isinstance(self.period_start, date) or isinstance(self.period_start, datetime):
            raise FundamentalDataValidationError("period_start must be a date")
        if not isinstance(self.period_end, date) or isinstance(self.period_end, datetime):
            raise FundamentalDataValidationError("period_end must be a date")
        if self.period_start > self.period_end:
            raise FundamentalDataValidationError("period_start must be on or before period_end")

        _validate_aware_datetime(self.available_at, "available_at")
        if self.published_at is not None:
            _validate_aware_datetime(self.published_at, "published_at")
            if self.published_at > self.available_at:
                raise FundamentalDataValidationError(
                    "available_at precedes published_at"
                )

        if not isinstance(self.source, str) or not self.source.strip():
            raise FundamentalDataValidationError("source must be non-empty")
        object.__setattr__(self, "source", self.source.strip())

        if self.source_record_id is not None:
            if not isinstance(self.source_record_id, str) or not self.source_record_id.strip():
                raise FundamentalDataValidationError(
                    "source_record_id must be non-empty when supplied"
                )
            object.__setattr__(self, "source_record_id", self.source_record_id.strip())


def _validate_aware_datetime(value: object, name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise FundamentalDataValidationError(f"{name} must be a timezone-aware datetime")


def latest_fundamental_facts_as_of(
    facts: Iterable[FundamentalFact],
    as_of: datetime,
    *,
    symbol: str | None = None,
    source: str | None = None,
) -> list[FundamentalFact]:
    """Return latest versions of source/metric/period/unit facts known at as_of.

    Revisions are selected independently per symbol, source, metric, reporting
    period and unit. Different sources stay separate; this function never
    silently chooses one vendor over another. Conflicting values from one source
    with the same availability time raise an error instead of choosing arbitrarily.

    This returns period facts; it does not derive TTM earnings, ratios, or fiscal
    year comparisons from unlike reporting periods.
    """
    _validate_aware_datetime(as_of, "as_of")
    normalized_symbol = None
    if symbol is not None:
        normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
        if not _SYMBOL_RE.fullmatch(normalized_symbol):
            raise ValueError("symbol must be 2-12 letters/digits")

    normalized_source = None
    if source is not None:
        normalized_source = source.strip() if isinstance(source, str) else ""
        if not normalized_source:
            raise ValueError("source must be non-empty when supplied")

    latest: dict[tuple[str, str, str, date, date, str], FundamentalFact] = {}
    for index, fact in enumerate(facts):
        if not isinstance(fact, FundamentalFact):
            raise TypeError(f"facts[{index}] must be a FundamentalFact")
        if normalized_symbol is not None and fact.symbol != normalized_symbol:
            continue
        if normalized_source is not None and fact.source != normalized_source:
            continue
        if fact.available_at > as_of:
            continue

        key = (
            fact.symbol,
            fact.source,
            fact.metric,
            fact.period_start,
            fact.period_end,
            fact.unit,
        )
        current = latest.get(key)
        if current is None or fact.available_at > current.available_at:
            latest[key] = fact
        elif fact.available_at == current.available_at:
            same_observation = (
                fact.value == current.value
                and fact.published_at == current.published_at
                and fact.source_record_id == current.source_record_id
            )
            if not same_observation:
                raise AmbiguousFundamentalFactError(
                    "Conflicting facts share the same available_at for "
                    f"{fact.symbol}/{fact.source}/{fact.metric}/"
                    f"{fact.period_start}..{fact.period_end}"
                )

    return sorted(
        latest.values(),
        key=lambda fact: (
            fact.symbol,
            fact.metric,
            fact.period_end,
            fact.period_start,
            fact.source,
            fact.unit,
        ),
    )
