from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.fundamentals import (
    AmbiguousFundamentalFactError,
    FundamentalDataValidationError,
    FundamentalFact,
    latest_fundamental_facts_as_of,
)

PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 12, 31)
PUBLISHED = datetime(2026, 3, 1, 2, tzinfo=UTC)
AVAILABLE = datetime(2026, 3, 1, 3, tzinfo=UTC)


def fact(
    value: str = "100",
    *,
    metric: str = "net_income",
    symbol: str = "FPT",
    source: str = "vendor-a",
    period_start: date = PERIOD_START,
    period_end: date = PERIOD_END,
    published_at: datetime | None = PUBLISHED,
    available_at: datetime = AVAILABLE,
    unit: str = "VND",
    source_record_id: str | None = "record-1",
) -> FundamentalFact:
    return FundamentalFact(
        symbol=symbol,
        metric=metric,
        value=Decimal(value),
        unit=unit,
        period_start=period_start,
        period_end=period_end,
        source=source,
        published_at=published_at,
        available_at=available_at,
        source_record_id=source_record_id,
    )


def test_fact_normalizes_symbol_and_metric_without_changing_value_units():
    result = fact("125.50", symbol=" fpt ", metric=" Net_Income ", unit=" VND ")

    assert result.symbol == "FPT"
    assert result.metric == "net_income"
    assert result.value == Decimal("125.50")
    assert result.unit == "VND"


def test_fact_rejects_non_finite_values_bad_periods_and_naive_times():
    with pytest.raises(FundamentalDataValidationError, match="finite Decimal"):
        fact("NaN")
    with pytest.raises(FundamentalDataValidationError, match="period_start"):
        fact(period_start=date(2026, 1, 1), period_end=date(2025, 12, 31))
    with pytest.raises(FundamentalDataValidationError, match="timezone-aware"):
        fact(available_at=datetime(2026, 3, 1, 3))
    with pytest.raises(FundamentalDataValidationError, match="precedes published_at"):
        fact(
            published_at=datetime(2026, 3, 1, 4, tzinfo=UTC),
            available_at=AVAILABLE,
        )


def test_as_of_excludes_facts_not_yet_available():
    assert latest_fundamental_facts_as_of([fact()], AVAILABLE - timedelta(seconds=1)) == []


def test_as_of_preserves_earlier_value_before_a_restatement_and_newer_after():
    earlier = fact("100", source_record_id="original")
    restated = fact(
        "80",
        source_record_id="restatement",
        published_at=datetime(2026, 4, 1, 2, tzinfo=UTC),
        available_at=datetime(2026, 4, 1, 3, tzinfo=UTC),
    )

    before = latest_fundamental_facts_as_of(
        [earlier, restated], datetime(2026, 3, 20, tzinfo=UTC)
    )
    after = latest_fundamental_facts_as_of(
        [earlier, restated], datetime(2026, 4, 2, tzinfo=UTC)
    )

    assert [item.value for item in before] == [Decimal("100")]
    assert [item.value for item in after] == [Decimal("80")]


def test_selector_keeps_sources_separate_and_supports_filters():
    facts = [
        fact("100", source="vendor-a"),
        fact("99", source="vendor-b"),
        fact("70", symbol="VIC", source="vendor-a"),
    ]

    all_facts = latest_fundamental_facts_as_of(facts, AVAILABLE)
    fpt_a = latest_fundamental_facts_as_of(
        facts, AVAILABLE, symbol="fpt", source="vendor-a"
    )

    assert {(item.symbol, item.source, item.value) for item in all_facts} == {
        ("FPT", "vendor-a", Decimal("100")),
        ("FPT", "vendor-b", Decimal("99")),
        ("VIC", "vendor-a", Decimal("70")),
    }
    assert len(fpt_a) == 1
    assert fpt_a[0].value == Decimal("100")


def test_selector_keeps_distinct_reporting_periods():
    prior = fact(
        "90",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        available_at=datetime(2025, 3, 1, 3, tzinfo=UTC),
        published_at=datetime(2025, 3, 1, 2, tzinfo=UTC),
        source_record_id="prior-year",
    )
    current = fact("100", source_record_id="current-year")

    result = latest_fundamental_facts_as_of([current, prior], AVAILABLE)

    assert [item.value for item in result] == [Decimal("90"), Decimal("100")]


def test_selector_raises_on_same_source_conflicting_same_time_facts():
    first = fact("100", source_record_id="row-1")
    second = fact("101", source_record_id="row-2")

    with pytest.raises(AmbiguousFundamentalFactError, match="Conflicting facts"):
        latest_fundamental_facts_as_of([first, second], AVAILABLE)


def test_identical_duplicate_fact_is_stable():
    item = fact()
    assert latest_fundamental_facts_as_of([item, item], AVAILABLE) == [item]


def test_invalid_selector_arguments_fail_early():
    with pytest.raises(ValueError, match="symbol"):
        latest_fundamental_facts_as_of([], AVAILABLE, symbol="bad ticker!")
    with pytest.raises(ValueError, match="timezone-aware"):
        latest_fundamental_facts_as_of([], datetime(2026, 3, 1))
    with pytest.raises(TypeError, match="facts"):
        latest_fundamental_facts_as_of(["not-a-fact"], AVAILABLE)  # type: ignore[list-item]
