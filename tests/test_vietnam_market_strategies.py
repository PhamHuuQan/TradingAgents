from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.backtest import BacktestConfig, run_long_only_backtest
from tradingagents.dataflows.vietnam_market.models import MarketBar
from tradingagents.dataflows.vietnam_market.strategies import sma_crossover_signals


def make_bars(closes: list[str]) -> list[MarketBar]:
    bars = []
    start = datetime(2026, 1, 1, 15, tzinfo=UTC)
    for index, value in enumerate(closes):
        close = Decimal(value)
        timestamp = start + timedelta(days=index)
        bars.append(
            MarketBar(
                symbol="FPT",
                timestamp=timestamp,
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                volume=10000,
                source="fixture",
                available_at=timestamp + timedelta(minutes=10),
            )
        )
    return bars


def test_sma_crossover_emits_targets_only_when_state_changes():
    bars = make_bars(["10", "10", "12", "14", "8", "7"])
    signals = sma_crossover_signals(bars, fast_period=2, slow_period=3)

    assert [(signal.timestamp, signal.target_exposure) for signal in signals] == [
        (bars[2].timestamp, Decimal(1)),
        (bars[4].timestamp, Decimal(0)),
    ]
    assert all(signal.available_at >= bars[2].available_at for signal in signals)


def test_sma_crossover_uses_only_data_available_at_the_signal_bar():
    bars = make_bars(["10", "10", "12", "14"])
    signals = sma_crossover_signals(bars, fast_period=2, slow_period=3)

    assert len(signals) == 1
    assert signals[0].timestamp == bars[2].timestamp
    assert signals[0].available_at == bars[2].available_at


def test_sma_crossover_returns_no_signals_for_short_or_empty_series():
    assert sma_crossover_signals([], fast_period=2, slow_period=3) == []
    assert sma_crossover_signals(
        make_bars(["10", "11"]), fast_period=1, slow_period=3
    ) == []


def test_sma_crossover_validates_periods_and_exposure():
    bars = make_bars(["10", "11", "12"])
    for fast, slow in ((0, 3), (True, 3), (3, 3), (4, 3), (1.5, 3)):
        with pytest.raises(ValueError):
            sma_crossover_signals(bars, fast_period=fast, slow_period=slow)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="long_exposure"):
        sma_crossover_signals(
            bars, fast_period=1, slow_period=2, long_exposure=Decimal("1.1")
        )


def test_sma_strategy_runs_through_backtester_without_same_bar_execution():
    bars = make_bars(["10", "10", "12", "14", "8", "7"])
    open_times = {
        bar.timestamp: datetime(
            bar.timestamp.year,
            bar.timestamp.month,
            bar.timestamp.day,
            9,
            tzinfo=UTC,
        )
        for bar in bars
    }
    signals = sma_crossover_signals(bars, fast_period=2, slow_period=3)
    result = run_long_only_backtest(
        bars,
        signals,
        open_times_by_bar_timestamp=open_times,
        config=BacktestConfig(
            initial_cash=Decimal("1000"),
            commission_rate=Decimal("0"),
            sell_fee_rate=Decimal("0"),
            slippage_bps=Decimal("0"),
            lot_size=1,
        ),
    )

    assert [trade.side for trade in result.trades] == ["BUY", "SELL"]
    assert result.trades[0].signal_timestamp == bars[2].timestamp
    assert result.trades[0].executed_at == open_times[bars[3].timestamp]
    assert result.trades[1].signal_timestamp == bars[4].timestamp
    assert result.trades[1].executed_at == open_times[bars[5].timestamp]
    assert result.ending_shares == 0
