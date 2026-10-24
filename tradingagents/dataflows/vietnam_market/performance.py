"""Risk and cost summaries for offline backtest results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradingagents.dataflows.vietnam_market.backtest import BacktestResult

_ZERO = Decimal(0)
_ONE = Decimal(1)
_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    """Portfolio-level statistics; percentages are returned on a 0-100 scale."""

    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    annualized_volatility_pct: Decimal | None
    sharpe_ratio: Decimal | None
    average_exposure_pct: Decimal
    observation_count: int
    trade_count: int
    buy_count: int
    sell_count: int
    total_fees: Decimal
    estimated_slippage_cost: Decimal
    turnover_pct_of_starting_cash: Decimal


def summarize_backtest(
    result: BacktestResult,
    *,
    periods_per_year: int,
    annual_risk_free_rate: Decimal = _ZERO,
) -> PerformanceSummary:
    """Summarize equity, drawdown, volatility, Sharpe, exposure, and costs.

    periods_per_year is an explicit annualization assumption (for example 252
    for an assumed daily series). annual_risk_free_rate is a fraction, so 0.03
    represents 3% per year. Its per-period approximation is the annual rate
    divided by periods_per_year. Volatility uses sample standard deviation.
    Sharpe is undefined when fewer than two returns exist or volatility is zero.

    Fee totals include only configured commission and sell-side fee amounts.
    Estimated slippage cost is the absolute difference between reference and
    fill price multiplied by quantity. Turnover counts both sides of each trade.
    """
    if not isinstance(result, BacktestResult):
        raise TypeError("result must be a BacktestResult")
    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, int)
        or periods_per_year < 1
    ):
        raise ValueError("periods_per_year must be a positive integer")
    if (
        not isinstance(annual_risk_free_rate, Decimal)
        or not annual_risk_free_rate.is_finite()
        or annual_risk_free_rate <= -_ONE
    ):
        raise ValueError("annual_risk_free_rate must be a finite Decimal greater than -1")

    curve = result.equity_curve
    previous_timestamp = None
    previous_equity = None
    peak = result.starting_cash
    max_drawdown = _ZERO
    exposures: list[Decimal] = []
    returns: list[Decimal] = []

    for index, point in enumerate(curve):
        if previous_timestamp is not None and point.timestamp <= previous_timestamp:
            raise ValueError("equity curve timestamps must be strictly increasing")
        if point.equity <= _ZERO:
            raise ValueError("equity curve values must remain positive")
        if point.equity != point.cash + Decimal(point.shares) * point.close_price:
            raise ValueError("equity point does not reconcile to cash plus marked positions")
        if previous_equity is not None:
            returns.append(point.equity / previous_equity - _ONE)
        previous_timestamp = point.timestamp
        previous_equity = point.equity
        peak = max(peak, point.equity)
        drawdown = (peak - point.equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
        exposures.append(Decimal(point.shares) * point.close_price / point.equity)

    volatility_pct: Decimal | None = None
    sharpe: Decimal | None = None
    if len(returns) >= 2:
        mean_return = sum(returns, _ZERO) / Decimal(len(returns))
        variance = sum(
            ((period_return - mean_return) ** 2 for period_return in returns),
            _ZERO,
        ) / Decimal(len(returns) - 1)
        standard_deviation = variance.sqrt()
        volatility_pct = standard_deviation * Decimal(periods_per_year).sqrt() * _HUNDRED
        if standard_deviation > _ZERO:
            periodic_risk_free_rate = annual_risk_free_rate / Decimal(periods_per_year)
            sharpe = (
                (mean_return - periodic_risk_free_rate)
                / standard_deviation
                * Decimal(periods_per_year).sqrt()
            )

    fees = sum(
        (trade.commission + trade.sell_fee for trade in result.trades),
        _ZERO,
    )
    slippage_cost = sum(
        (
            abs(trade.fill_price - trade.reference_price) * Decimal(trade.quantity)
            for trade in result.trades
        ),
        _ZERO,
    )
    turnover = sum(
        (trade.fill_price * Decimal(trade.quantity) for trade in result.trades),
        _ZERO,
    )
    turnover_pct = turnover / result.starting_cash * _HUNDRED
    average_exposure = (
        sum(exposures, _ZERO) / Decimal(len(exposures)) * _HUNDRED
        if exposures
        else _ZERO
    )

    return PerformanceSummary(
        total_return_pct=result.total_return_pct,
        max_drawdown_pct=max_drawdown * _HUNDRED,
        annualized_volatility_pct=volatility_pct,
        sharpe_ratio=sharpe,
        average_exposure_pct=average_exposure,
        observation_count=len(curve),
        trade_count=len(result.trades),
        buy_count=sum(trade.side == "BUY" for trade in result.trades),
        sell_count=sum(trade.side == "SELL" for trade in result.trades),
        total_fees=fees,
        estimated_slippage_cost=slippage_cost,
        turnover_pct_of_starting_cash=turnover_pct,
    )
