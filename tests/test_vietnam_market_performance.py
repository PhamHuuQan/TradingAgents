from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.backtest import (
    BacktestResult,
    BacktestTrade,
    EquityPoint,
)
from tradingagents.dataflows.vietnam_market.performance import summarize_backtest


def make_result(equities: list[str], *, trades: tuple[BacktestTrade, ...] = ()) -> BacktestResult:
    start = datetime(2026, 1, 1, 15, tzinfo=UTC)
    curve = tuple(
        EquityPoint(
            timestamp=start + timedelta(days=index),
            cash=Decimal(value),
            shares=0,
            close_price=Decimal(10),
            equity=Decimal(value),
        )
        for index, value in enumerate(equities)
    )
    ending_equity = Decimal(equities[-1]) if equities else Decimal(1000)
    total_return = (
        (ending_equity / Decimal(1000) - Decimal(1)) * Decimal(100)
        if equities
        else Decimal(0)
    )
    return BacktestResult(
        symbol="FPT",
        source="fixture",
        starting_cash=Decimal(1000),
        ending_cash=ending_equity,
        ending_shares=0,
        ending_equity=ending_equity,
        total_return_pct=total_return,
        trades=trades,
        equity_curve=curve,
    )


def test_summary_calculates_total_return_and_maximum_drawdown():
    result = make_result(["1000", "1200", "900", "1100"])

    summary = summarize_backtest(result, periods_per_year=252)

    assert summary.total_return_pct == Decimal(10)
    assert summary.max_drawdown_pct == Decimal(25)
    assert summary.observation_count == 4
    assert summary.average_exposure_pct == 0


def test_summary_calculates_annualized_volatility_and_sharpe():
    result = make_result(["1000", "1010", "990", "1030", "1020"])

    summary = summarize_backtest(
        result, periods_per_year=252, annual_risk_free_rate=Decimal("0.03")
    )

    assert summary.annualized_volatility_pct is not None
    assert summary.annualized_volatility_pct > 0
    assert summary.sharpe_ratio is not None


def test_summary_reports_fees_slippage_turnover_and_trade_counts():
    time = datetime(2026, 1, 1, 15, tzinfo=UTC)
    trades = (
        BacktestTrade(
            signal_timestamp=time,
            executed_at=time + timedelta(hours=1),
            bar_timestamp=time + timedelta(hours=6),
            side="BUY",
            quantity=2,
            reference_price=Decimal("10"),
            fill_price=Decimal("10.1"),
            commission=Decimal("0.2"),
            sell_fee=Decimal(0),
            cash_after=Decimal("979.6"),
        ),
        BacktestTrade(
            signal_timestamp=time + timedelta(days=1),
            executed_at=time + timedelta(days=1, hours=1),
            bar_timestamp=time + timedelta(days=1, hours=6),
            side="SELL",
            quantity=2,
            reference_price=Decimal("12"),
            fill_price=Decimal("11.9"),
            commission=Decimal("0.238"),
            sell_fee=Decimal("0.1"),
            cash_after=Decimal("1003.062"),
        ),
    )
    result = make_result(["1000", "1003", "1003"], trades=trades)

    summary = summarize_backtest(result, periods_per_year=252)

    assert summary.trade_count == 2
    assert summary.buy_count == 1
    assert summary.sell_count == 1
    assert summary.total_fees == Decimal("0.538")
    assert summary.estimated_slippage_cost == Decimal("0.4")
    assert summary.turnover_pct_of_starting_cash == Decimal("4.4")


def test_summary_handles_short_curves_and_constant_equity():
    empty = make_result([])
    constant = make_result(["1000", "1000", "1000"])

    empty_summary = summarize_backtest(empty, periods_per_year=252)
    constant_summary = summarize_backtest(constant, periods_per_year=252)

    assert empty_summary.observation_count == 0
    assert empty_summary.annualized_volatility_pct is None
    assert empty_summary.sharpe_ratio is None
    assert constant_summary.annualized_volatility_pct == 0
    assert constant_summary.sharpe_ratio is None


def test_summary_rejects_invalid_frequency_and_non_reconciled_equity():
    result = make_result(["1000", "1100"])
    with pytest.raises(ValueError, match="periods_per_year"):
        summarize_backtest(result, periods_per_year=0)

    bad_point = EquityPoint(
        timestamp=datetime(2026, 1, 1, 15, tzinfo=UTC),
        cash=Decimal(1000),
        shares=0,
        close_price=Decimal(10),
        equity=Decimal(999),
    )
    malformed = BacktestResult(
        symbol="FPT",
        source="fixture",
        starting_cash=Decimal(1000),
        ending_cash=Decimal(1000),
        ending_shares=0,
        ending_equity=Decimal(999),
        total_return_pct=Decimal("-0.1"),
        trades=(),
        equity_curve=(bad_point,),
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        summarize_backtest(malformed, periods_per_year=252)
