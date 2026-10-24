from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows.vietnam_market.fundamentals import FundamentalFact
from tradingagents.dataflows.vietnam_market.models import MarketBar
from tradingagents.dataflows.vietnam_market.valuation import (
    ValuationDataError,
    build_valuation_metrics,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
SOURCE = "test-feed"
CURRENCY = "VND"


def _fact(metric, value, unit, start, end, available):
    return FundamentalFact(
        symbol="FPT",
        metric=metric,
        value=Decimal(str(value)),
        unit=unit,
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        source=SOURCE,
        available_at=available,
    )


def _fixture():
    periods = [
        ("2025-01-01", "2025-03-31", 10_000_000_000),
        ("2025-04-01", "2025-06-30", 10_000_000_000),
        ("2025-07-01", "2025-09-30", 10_000_000_000),
        ("2025-10-01", "2025-12-31", 10_000_000_000),
    ]
    facts = []
    for start, end, income in periods:
        available = datetime.fromisoformat(end).replace(
            hour=16, minute=0, tzinfo=VN_TZ
        )
        available = available.astimezone(UTC)
        facts.extend(
            [
                _fact("net_income", income, CURRENCY, start, end, available),
                _fact(
                    "weighted_average_shares",
                    1_000_000_000,
                    "shares",
                    start,
                    end,
                    available,
                ),
                _fact(
                    "operating_cash_flow",
                    12_000_000_000,
                    CURRENCY,
                    start,
                    end,
                    available,
                ),
                _fact(
                    "capital_expenditure",
                    3_000_000_000,
                    CURRENCY,
                    start,
                    end,
                    available,
                ),
            ]
        )
    facts.extend(
        [
            _fact(
                "total_equity",
                100_000_000_000,
                CURRENCY,
                "2024-10-01",
                "2024-12-31",
                datetime(2025, 1, 30, tzinfo=UTC),
            ),
            _fact(
                "total_equity",
                200_000_000_000,
                CURRENCY,
                "2025-10-01",
                "2025-12-31",
                datetime(2026, 1, 30, tzinfo=UTC),
            ),
            _fact(
                "shares_outstanding",
                1_000_000_000,
                "shares",
                "2025-10-01",
                "2025-12-31",
                datetime(2026, 1, 30, tzinfo=UTC),
            ),
        ]
    )
    bar = MarketBar(
        symbol="FPT",
        timestamp=datetime(2026, 2, 27, 15, 0, tzinfo=VN_TZ),
        open=Decimal("49000"),
        high=Decimal("51000"),
        low=Decimal("48000"),
        close=Decimal("50000"),
        volume=100000,
        source="test-prices",
        available_at=datetime(2026, 2, 27, 15, 5, tzinfo=VN_TZ),
    )
    return [bar], facts


@pytest.mark.unit
def test_builds_ratios_from_consistent_point_in_time_quarters():
    bars, facts = _fixture()
    result = build_valuation_metrics(
        "fpt",
        bars,
        facts,
        AS_OF,
        source=SOURCE,
        price_unit="VND/share",
        currency_unit=CURRENCY,
    )

    assert result.symbol == "FPT"
    assert result.as_of == AS_OF
    assert result.market_cap == Decimal("50000000000000")
    assert result.ttm_net_income == Decimal("40000000000")
    assert result.eps == Decimal("40")
    assert result.pe == Decimal("1250")
    assert result.pb == Decimal("250")
    assert result.roe == Decimal("40000000000") / Decimal("150000000000")
    assert result.ttm_operating_cash_flow == Decimal("48000000000")
    assert result.ttm_capex == Decimal("12000000000")
    assert result.free_cash_flow == Decimal("36000000000")
    assert result.cash_conversion == Decimal("1.2")
    assert not result.warnings


@pytest.mark.unit
def test_excludes_facts_and_prices_not_available_by_cutoff():
    bars, facts = _fixture()
    future_bar = MarketBar(
        symbol="FPT",
        timestamp=datetime(2026, 3, 2, 15, 0, tzinfo=VN_TZ),
        open=Decimal("50000"),
        high=Decimal("52000"),
        low=Decimal("49000"),
        close=Decimal("51000"),
        volume=150000,
        source="test-prices",
        available_at=datetime(2026, 3, 2, 15, 5, tzinfo=VN_TZ),
    )
    facts.append(
        _fact(
            "shares_outstanding",
            2_000_000_000,
            "shares",
            "2026-01-01",
            "2026-02-28",
            datetime(2026, 3, 5, tzinfo=UTC),
        )
    )
    result = build_valuation_metrics(
        "FPT",
        [*bars, future_bar],
        facts,
        AS_OF,
        source=SOURCE,
        price_unit="VND/share",
        currency_unit=CURRENCY,
    )
    assert result.price == Decimal("50000")
    assert result.shares_outstanding == Decimal("1000000000")


@pytest.mark.unit
def test_does_not_sum_cumulative_or_gapped_periods_into_ttm():
    bars, facts = _fixture()
    facts = [
        fact for fact in facts
        if not (
            fact.metric == "net_income"
            and fact.period_start == date(2025, 7, 1)
        )
    ]
    result = build_valuation_metrics(
        "FPT",
        bars,
        facts,
        AS_OF,
        source=SOURCE,
        price_unit="VND/share",
        currency_unit=CURRENCY,
    )
    assert result.ttm_net_income is None
    assert result.pe is None
    assert any("TTM net income unavailable" in warning for warning in result.warnings)


@pytest.mark.unit
def test_does_not_mix_sources_or_accept_inconsistent_units():
    bars, facts = _fixture()
    other_source = [
        FundamentalFact(
            symbol=fact.symbol,
            metric=fact.metric,
            value=fact.value * Decimal("10"),
            unit=fact.unit,
            period_start=fact.period_start,
            period_end=fact.period_end,
            source="another-feed",
            available_at=fact.available_at,
        )
        for fact in facts
    ]
    result = build_valuation_metrics(
        "FPT",
        bars,
        [*facts, *other_source],
        AS_OF,
        source=SOURCE,
        price_unit="VND/share",
        currency_unit=CURRENCY,
    )
    assert result.ttm_net_income == Decimal("40000000000")

    with pytest.raises(ValuationDataError, match="price_unit"):
        build_valuation_metrics(
            "FPT",
            bars,
            facts,
            AS_OF,
            source=SOURCE,
            price_unit="USD/share",
            currency_unit=CURRENCY,
        )


@pytest.mark.unit
def test_rejects_price_snapshot_without_availability_time_at_cutoff():
    bars, facts = _fixture()
    bars[0] = MarketBar(
        symbol="FPT",
        timestamp=datetime(2026, 2, 27, 15, 0, tzinfo=VN_TZ),
        open=Decimal("49000"),
        high=Decimal("51000"),
        low=Decimal("48000"),
        close=Decimal("50000"),
        volume=100000,
        source="test-prices",
        available_at=datetime(2026, 3, 2, 15, 5, tzinfo=VN_TZ),
    )
    with pytest.raises(ValuationDataError, match="No price bar"):
        build_valuation_metrics(
            "FPT",
            bars,
            facts,
            AS_OF,
            source=SOURCE,
            price_unit="VND/share",
            currency_unit=CURRENCY,
        )
