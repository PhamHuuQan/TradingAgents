from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.fundamentals import FundamentalFact
from tradingagents.dataflows.vietnam_market.vnstock_adapter import (
    VnstockNormalizationError,
    normalize_vnstock_vci_statements,
)


FETCHED = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def _row(period, item_id, value, unit="VNĐ"):
    return {"period": period, "id": item_id, "value": value, "unit": unit}


def _inputs():
    income = [
        _row("2025-Q1", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 10_000_000_000),
        _row("2025-Q2", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 11_000_000_000),
        _row("2025-Q3", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 12_000_000_000),
        _row("2025-Q4", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 13_000_000_000),
        _row("2025-Q4", "IS_NET_REVENUE", 999_000_000_000),
    ]
    balance = [
        _row("2025-Q3", "BS_EQUITY", 180_000_000_000),
        _row("2025-Q4", "BS_EQUITY", 200_000_000_000),
    ]
    cash_flow = [
        _row("2025-Q1", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 12_000_000_000),
        _row("2025-Q2", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 13_000_000_000),
        _row("2025-Q3", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 14_000_000_000),
        _row("2025-Q4", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 15_000_000_000),
    ]
    return income, balance, cash_flow


@pytest.mark.unit
def test_normalizes_only_explicitly_supported_vci_metrics():
    income, balance, cash_flow = _inputs()

    facts = normalize_vnstock_vci_statements("fpt", income, balance, cash_flow, FETCHED)

    assert len(facts) == 10
    assert all(isinstance(fact, FundamentalFact) for fact in facts)
    assert {fact.symbol for fact in facts} == {"FPT"}
    assert {fact.source for fact in facts} == {"vnstock-vci"}
    assert all(fact.unit == "VND" for fact in facts)
    assert all(fact.available_at == FETCHED for fact in facts)
    assert all(fact.published_at is None for fact in facts)
    net_income = [fact for fact in facts if fact.metric == "net_income"]
    assert [fact.value for fact in net_income] == [
        Decimal("10000000000"),
        Decimal("11000000000"),
        Decimal("12000000000"),
        Decimal("13000000000"),
    ]
    assert not any(fact.metric == "net_revenue" for fact in facts)


@pytest.mark.unit
def test_normalizer_accepts_dataframe_like_long_tables_with_source_metadata():
    class FakeFrame:
        def __init__(self, rows, attrs):
            self.rows = rows
            self.attrs = attrs

        def to_dict(self, orient):
            assert orient == "records"
            return self.rows

    income, balance, cash_flow = _inputs()
    tables = [
        FakeFrame(rows, {"source": "vci", "symbol": "FPT", "format": "long"})
        for rows in (income, balance, cash_flow)
    ]

    facts = normalize_vnstock_vci_statements("FPT", *tables, FETCHED)

    assert len(facts) == 10


@pytest.mark.unit
def test_rejects_wrong_source_or_symbol_metadata():
    class FakeFrame:
        attrs = {"source": "kbs", "symbol": "FPT", "format": "long"}

        def to_dict(self, orient):
            return [_row("2025-Q4", "BS_EQUITY", 200_000_000_000)]

    with pytest.raises(VnstockNormalizationError, match="source metadata"):
        normalize_vnstock_vci_statements("FPT", None, FakeFrame(), None, FETCHED)

    class WrongSymbol:
        attrs = {"source": "vci", "symbol": "VCB", "format": "long"}

        def to_dict(self, orient):
            return [_row("2025-Q4", "BS_EQUITY", 200_000_000_000)]

    with pytest.raises(VnstockNormalizationError, match="symbol metadata"):
        normalize_vnstock_vci_statements("FPT", None, WrongSymbol(), None, FETCHED)


@pytest.mark.unit
def test_rejects_annual_periods_and_unsupported_units_instead_of_guessing():
    with pytest.raises(VnstockNormalizationError, match="quarterly label"):
        normalize_vnstock_vci_statements(
            "FPT",
            [_row("2025", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 1_000_000)],
            None,
            None,
            FETCHED,
        )

    with pytest.raises(VnstockNormalizationError, match="unsupported currency unit"):
        normalize_vnstock_vci_statements(
            "FPT",
            None,
            [_row("2025-Q4", "BS_EQUITY", 1_000_000, unit="million VND")],
            None,
            FETCHED,
        )


@pytest.mark.unit
def test_rejects_future_periods_duplicate_facts_and_naive_fetch_times():
    with pytest.raises(VnstockNormalizationError, match="ends after fetch date"):
        normalize_vnstock_vci_statements(
            "FPT",
            [_row("2026-Q4", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 1_000_000)],
            None,
            None,
            datetime(2026, 10, 25, tzinfo=UTC),
        )

    with pytest.raises(VnstockNormalizationError, match="duplicate normalized VCI fact"):
        normalize_vnstock_vci_statements(
            "FPT",
            [
                _row("2025-Q4", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 1_000_000),
                _row("2025-Q4", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 1_100_000),
            ],
            None,
            None,
            FETCHED,
        )

    with pytest.raises(VnstockNormalizationError, match="timezone-aware"):
        normalize_vnstock_vci_statements(
            "FPT",
            None,
            [_row("2025-Q4", "BS_EQUITY", 200_000_000_000)],
            None,
            datetime(2026, 10, 25, 9, 0),
        )


@pytest.mark.unit
def test_empty_or_null_supported_values_are_not_fabricated():
    income = [_row("2025-Q4", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", float("nan"))]
    balance = [_row("2025-Q4", "BS_EQUITY", None)]
    cash_flow = [_row("2025-Q4", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", "NaN")]

    with pytest.raises(VnstockNormalizationError, match="No supported VCI statement facts"):
        normalize_vnstock_vci_statements("FPT", income, balance, cash_flow, FETCHED)
