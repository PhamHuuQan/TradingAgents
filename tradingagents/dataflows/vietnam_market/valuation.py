"""Point-in-time valuation metrics derived from normalized fundamental facts.

No filing ingestion or unit inference happens here. TTM flows require four
complete, contiguous, standalone quarterly facts. Cumulative year-to-date facts
are rejected instead of being silently summed more than once.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tradingagents.dataflows.vietnam_market.fundamentals import (
    FundamentalFact,
    latest_fundamental_facts_as_of,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar


class ValuationDataError(ValueError):
    """Raised when point-in-time valuation inputs are ambiguous or inconsistent."""


@dataclass(frozen=True, slots=True)
class ValuationMetrics:
    """Derived valuation and cash-quality metrics; missing values remain explicit."""

    symbol: str
    as_of: datetime
    price_source: str
    source: str
    price: Decimal
    price_unit: str
    price_timestamp: datetime
    price_available_at: datetime
    currency_unit: str
    shares_outstanding: Decimal | None
    shares_period_end: date | None
    shares_available_at: datetime | None
    market_cap: Decimal | None
    latest_equity: Decimal | None
    equity_period_end: date | None
    equity_available_at: datetime | None
    ttm_period_start: date | None
    ttm_period_end: date | None
    ttm_net_income: Decimal | None
    eps: Decimal | None
    pe: Decimal | None
    pb: Decimal | None
    roe: Decimal | None
    ttm_operating_cash_flow: Decimal | None
    ttm_capex: Decimal | None
    free_cash_flow: Decimal | None
    cash_conversion: Decimal | None
    warnings: tuple[str, ...]


# These thresholds are deliberately conservative for listed-company snapshots.
# If a usable source has older facts, keep their dates visible but withhold ratios
# that depend on them instead of quietly valuing with stale balance-sheet data.
MAX_EQUITY_AGE_DAYS = 180
MAX_SHARES_AGE_DAYS = 365


def _aware(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValuationDataError(f"{name} must be a timezone-aware datetime")


def _latest_point_fact(
    facts: list[FundamentalFact], metric: str, unit: str
) -> FundamentalFact | None:
    """Select the latest point-in-time fact; reject conflicting same-date records."""
    candidates = [
        fact for fact in facts
        if fact.metric == metric and fact.unit == unit
        and fact.period_end <= fact.available_at.date()
    ]
    if not candidates:
        return None
    latest_end = max(fact.period_end for fact in candidates)
    same_end = [fact for fact in candidates if fact.period_end == latest_end]
    keys = {(fact.value, fact.period_start, fact.period_end, fact.unit) for fact in same_end}
    if len(keys) != 1:
        raise ValuationDataError(
            f"Ambiguous {metric} facts from one source for period ending {latest_end}"
        )
    return max(same_end, key=lambda fact: fact.available_at)


def _latest_quarters(
    facts: list[FundamentalFact], metric: str, unit: str
) -> tuple[FundamentalFact, ...] | None:
    """Return the latest four discrete, contiguous quarterly observations."""
    candidates = sorted(
        (
            fact for fact in facts
            if fact.metric == metric and fact.unit == unit
            and fact.period_end <= fact.available_at.date()
            and 80 <= (fact.period_end - fact.period_start).days + 1 <= 100
        ),
        key=lambda fact: (fact.period_end, fact.period_start),
    )
    by_period: dict[tuple[date, date], FundamentalFact] = {}
    for fact in candidates:
        key = (fact.period_start, fact.period_end)
        previous = by_period.get(key)
        if previous is not None and previous.value != fact.value:
            raise ValuationDataError(
                f"Ambiguous {metric} facts for {fact.period_start}..{fact.period_end}"
            )
        by_period[key] = fact
    quarters = sorted(by_period.values(), key=lambda fact: fact.period_end)
    if len(quarters) < 4:
        return None
    last_four = tuple(quarters[-4:])
    for previous, current in zip(last_four, last_four[1:], strict=False):
        if (current.period_start - previous.period_end).days != 1:
            return None
    return last_four


def _sum_matching_quarters(
    facts: list[FundamentalFact],
    metric: str,
    unit: str,
    quarters: tuple[FundamentalFact, ...],
) -> Decimal | None:
    by_period = {
        (fact.period_start, fact.period_end): fact
        for fact in facts
        if fact.metric == metric and fact.unit == unit
        and fact.period_end <= fact.available_at.date()
    }
    matched = [by_period.get((fact.period_start, fact.period_end)) for fact in quarters]
    if any(fact is None for fact in matched):
        return None
    return sum((fact.value for fact in matched if fact is not None), Decimal("0"))


def _equity_near(
    facts: list[FundamentalFact],
    *,
    target: date,
    unit: str,
    maximum_age_days: int = 100,
) -> Decimal | None:
    candidates = [
        fact for fact in facts
        if fact.metric == "total_equity" and fact.unit == unit
        and fact.period_end <= target
        and (target - fact.period_end).days <= maximum_age_days
    ]
    if not candidates:
        return None
    fact = _latest_point_fact(candidates, "total_equity", unit)
    return fact.value if fact else None


def build_valuation_metrics(
    symbol: str,
    bars: Iterable[MarketBar],
    facts: Iterable[FundamentalFact],
    as_of: datetime,
    *,
    price_source: str,
    source: str,
    price_unit: str,
    currency_unit: str,
) -> ValuationMetrics:
    """Build a single-source valuation snapshot using only data available by as_of.

    Normalized metric names: net_income, total_equity, shares_outstanding,
    weighted_average_shares, operating_cash_flow, and capital_expenditure.
    Share counts use unit 'shares'; financial values use currency_unit; price
    uses price_unit (for example, VND/share).

    capital_expenditure must be a non-negative spending magnitude. If a source
    records capex as a negative cash-flow line, normalize its sign upstream.
    """
    _aware(as_of, "as_of")
    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not normalized_symbol:
        raise ValuationDataError("symbol must be non-empty")
    if not isinstance(source, str) or not source.strip():
        raise ValuationDataError("source must be non-empty")
    source = source.strip()
    if not isinstance(price_source, str) or not price_source.strip():
        raise ValuationDataError("price_source must be non-empty")
    price_source = price_source.strip()
    if not isinstance(currency_unit, str) or not currency_unit.strip():
        raise ValuationDataError("currency_unit must be non-empty")
    currency_unit = currency_unit.strip()
    expected_price_unit = f"{currency_unit}/share"
    if not isinstance(price_unit, str) or price_unit.strip() != expected_price_unit:
        raise ValuationDataError(
            f"price_unit must be {expected_price_unit!r} for consistent market-cap units"
        )

    usable_bars = [
        bar for bar in bars
        if isinstance(bar, MarketBar) and bar.symbol == normalized_symbol
        and bar.source == price_source
        and bar.timestamp <= as_of and bar.available_at <= as_of
    ]
    if not usable_bars:
        raise ValuationDataError(
            f"No price bar for {normalized_symbol} was timestamped and available by {as_of.isoformat()}"
        )
    latest_bar = max(usable_bars, key=lambda bar: (bar.timestamp, bar.available_at))
    if latest_bar.close <= 0:
        raise ValuationDataError("latest close must be positive for valuation metrics")

    source_facts = latest_fundamental_facts_as_of(
        facts, as_of, symbol=normalized_symbol, source=source
    )
    warnings: list[str] = []

    valuation_date = as_of.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()

    shares_fact = _latest_point_fact(source_facts, "shares_outstanding", "shares")
    shares_period_end = shares_fact.period_end if shares_fact else None
    shares_available_at = shares_fact.available_at if shares_fact else None
    shares_outstanding = shares_fact.value if shares_fact else None
    if shares_fact is None:
        warnings.append("Missing shares_outstanding in unit shares; market capitalization and P/E are unavailable")
    if shares_fact is not None:
        shares_age = (valuation_date - shares_fact.period_end).days
        if shares_age < 0 or shares_age > MAX_SHARES_AGE_DAYS:
            warnings.append(
                f"shares_outstanding is stale ({shares_age} days old; "
                f"limit {MAX_SHARES_AGE_DAYS}); market capitalization and P/E are unavailable"
            )
            shares_outstanding = None
    if shares_outstanding is not None and shares_outstanding <= 0:
        warnings.append("shares_outstanding is non-positive; market cap and P/E are unavailable")
        shares_outstanding = None
    market_cap = latest_bar.close * shares_outstanding if shares_outstanding is not None else None

    equity_fact = _latest_point_fact(source_facts, "total_equity", currency_unit)
    equity_period_end = equity_fact.period_end if equity_fact else None
    equity_available_at = equity_fact.available_at if equity_fact else None
    latest_equity = equity_fact.value if equity_fact else None
    if equity_fact is not None:
        equity_age = (valuation_date - equity_fact.period_end).days
        if equity_age < 0 or equity_age > MAX_EQUITY_AGE_DAYS:
            warnings.append(
                f"total_equity is stale ({equity_age} days old; "
                f"limit {MAX_EQUITY_AGE_DAYS}); P/B is unavailable"
            )
            latest_equity = None
    if latest_equity is None and equity_fact is None:
        warnings.append(f"Missing total_equity fact in {currency_unit}")
    elif latest_equity is not None and latest_equity <= 0:
        warnings.append("total_equity is non-positive; P/B is not meaningful")
    pb = (
        market_cap / latest_equity
        if market_cap is not None and latest_equity is not None and latest_equity > 0
        else None
    )

    net_income_quarters = _latest_quarters(source_facts, "net_income", currency_unit)
    ttm_period_start = net_income_quarters[0].period_start if net_income_quarters else None
    ttm_period_end = net_income_quarters[-1].period_end if net_income_quarters else None
    ttm_net_income = (
        sum((fact.value for fact in net_income_quarters), Decimal("0"))
        if net_income_quarters else None
    )
    if ttm_net_income is None:
        warnings.append(
            "TTM net income unavailable: four contiguous standalone quarterly facts "
            "with verified availability times are required"
        )

    eps = None
    if net_income_quarters:
        matching_shares = [
            next(
                (
                    share_fact for share_fact in source_facts
                    if share_fact.metric == "weighted_average_shares"
                    and share_fact.unit == "shares"
                    and share_fact.period_start == quarter.period_start
                    and share_fact.period_end == quarter.period_end
                ),
                None,
            )
            for quarter in net_income_quarters
        ]
        if all(fact is not None for fact in matching_shares):
            share_facts = [fact for fact in matching_shares if fact is not None]
            total_days = sum(
                (fact.period_end - fact.period_start).days + 1
                for fact in net_income_quarters
            )
            weighted_average = sum(
                (
                    share_fact.value
                    * Decimal((period.period_end - period.period_start).days + 1)
                    for share_fact, period in zip(
                        share_facts, net_income_quarters, strict=True
                    )
                ),
                Decimal("0"),
            ) / Decimal(total_days)
            if weighted_average > 0 and ttm_net_income is not None:
                eps = ttm_net_income / weighted_average
        if eps is None:
            warnings.append(
                "EPS unavailable: matching quarterly weighted_average_shares facts are required"
            )

    # Use price / TTM EPS for P/E so it follows the weighted-average share
    # count used in EPS. Market cap / net income can differ after issuance or
    # buybacks, so it is not used as a silent substitute here.
    pe = None
    if eps is not None:
        if eps > 0:
            pe = latest_bar.close / eps
        else:
            warnings.append("TTM EPS is non-positive; P/E is not meaningful")
    elif ttm_net_income is not None and ttm_net_income > 0:
        warnings.append("P/E unavailable without matching TTM EPS and weighted-average shares")

    roe = None
    if net_income_quarters and ttm_net_income is not None:
        first, last = net_income_quarters[0], net_income_quarters[-1]
        opening_target = date.fromordinal(first.period_start.toordinal() - 1)
        opening_equity = _equity_near(
            source_facts, target=opening_target, unit=currency_unit
        )
        closing_equity = _equity_near(
            source_facts, target=last.period_end, unit=currency_unit
        )
        if (
            opening_equity is not None and closing_equity is not None
            and opening_equity + closing_equity > 0
        ):
            roe = ttm_net_income / (
                (opening_equity + closing_equity) / Decimal("2")
            )
        else:
            warnings.append(
                "ROE unavailable: comparable opening and closing equity facts near the TTM period are required"
            )

    ttm_cfo = (
        _sum_matching_quarters(
            source_facts, "operating_cash_flow", currency_unit, net_income_quarters
        ) if net_income_quarters else None
    )
    ttm_capex = (
        _sum_matching_quarters(
            source_facts, "capital_expenditure", currency_unit, net_income_quarters
        ) if net_income_quarters else None
    )
    free_cash_flow = None
    if ttm_cfo is not None and ttm_capex is not None:
        if ttm_capex < 0:
            warnings.append(
                "Free cash flow unavailable: capital_expenditure must be a non-negative outflow magnitude"
            )
        else:
            free_cash_flow = ttm_cfo - ttm_capex
    cash_conversion = None
    if ttm_cfo is not None and ttm_net_income is not None and ttm_net_income > 0:
        cash_conversion = ttm_cfo / ttm_net_income

    return ValuationMetrics(
        symbol=normalized_symbol,
        as_of=as_of.astimezone(UTC),
        price_source=price_source,
        source=source,
        price=latest_bar.close,
        price_unit=price_unit,
        price_timestamp=latest_bar.timestamp,
        price_available_at=latest_bar.available_at,
        currency_unit=currency_unit,
        shares_outstanding=shares_outstanding,
        shares_period_end=shares_period_end,
        shares_available_at=shares_available_at,
        market_cap=market_cap,
        latest_equity=latest_equity,
        equity_period_end=equity_period_end,
        equity_available_at=equity_available_at,
        ttm_period_start=ttm_period_start,
        ttm_period_end=ttm_period_end,
        ttm_net_income=ttm_net_income,
        eps=eps,
        pe=pe,
        pb=pb,
        roe=roe,
        ttm_operating_cash_flow=ttm_cfo,
        ttm_capex=ttm_capex,
        free_cash_flow=free_cash_flow,
        cash_conversion=cash_conversion,
        warnings=tuple(warnings),
    )
