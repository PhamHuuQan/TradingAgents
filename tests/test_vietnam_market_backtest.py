from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.backtest import (
    BacktestConfig,
    BacktestValidationError,
    TargetExposureSignal,
    run_long_only_backtest,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar


def make_bars(
    prices: list[tuple[str, str]],
    *,
    start_day: int = 1,
    source: str = "fixture",
) -> tuple[list[MarketBar], dict[datetime, datetime]]:
    bars = []
    open_times = {}
    for index, (raw_open, raw_close) in enumerate(prices):
        day = start_day + index
        timestamp = datetime(2026, 1, day, 15, 0, tzinfo=UTC)
        open_at = datetime(2026, 1, day, 9, 0, tzinfo=UTC)
        opened = Decimal(raw_open)
        closed = Decimal(raw_close)
        bars.append(
            MarketBar(
                symbol="FPT",
                timestamp=timestamp,
                open=opened,
                high=max(opened, closed) + Decimal(1),
                low=min(opened, closed) - Decimal(1),
                close=closed,
                volume=100000,
                source=source,
                available_at=timestamp + timedelta(minutes=10),
            )
        )
        open_times[timestamp] = open_at
    return bars, open_times


def config(
    *,
    initial_cash: str = "1000",
    commission_rate: str = "0",
    sell_fee_rate: str = "0",
    slippage_bps: str = "0",
    lot_size: int = 1,
) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=Decimal(initial_cash),
        commission_rate=Decimal(commission_rate),
        sell_fee_rate=Decimal(sell_fee_rate),
        slippage_bps=Decimal(slippage_bps),
        lot_size=lot_size,
    )


def signal(bar: MarketBar, target: str) -> TargetExposureSignal:
    return TargetExposureSignal(
        timestamp=bar.timestamp,
        available_at=bar.available_at,
        target_exposure=Decimal(target),
    )


def test_signal_executes_at_next_open_not_same_bar_close():
    bars, opens = make_bars([("10", "10.5"), ("11", "12")])
    result = run_long_only_backtest(
        bars,
        [signal(bars[0], "1")],
        open_times_by_bar_timestamp=opens,
        config=config(),
    )

    assert result.trades[0].side == "BUY"
    assert result.trades[0].signal_timestamp == bars[0].timestamp
    assert result.trades[0].executed_at == opens[bars[1].timestamp]
    assert result.trades[0].bar_timestamp == bars[1].timestamp
    assert result.trades[0].reference_price == Decimal("11")
    assert result.trades[0].quantity == 90
    assert result.equity_curve[0].shares == 0
    assert result.equity_curve[1].shares == 90
    assert result.ending_equity == Decimal("1090")


def test_signal_not_available_by_open_waits_until_later_bar_open():
    bars, opens = make_bars([("10", "10"), ("10", "10"), ("10", "10")])
    late_signal = TargetExposureSignal(
        timestamp=bars[0].timestamp,
        available_at=opens[bars[1].timestamp] + timedelta(hours=1),
        target_exposure=Decimal("1"),
    )
    result = run_long_only_backtest(
        bars,
        [late_signal],
        open_times_by_bar_timestamp=opens,
        config=config(),
    )

    assert len(result.trades) == 1
    assert result.trades[0].executed_at == opens[bars[2].timestamp]
    assert result.equity_curve[1].shares == 0
    assert result.equity_curve[2].shares == 100


def test_commission_sell_fee_slippage_and_lot_size_are_applied():
    bars, opens = make_bars([("10", "10.5"), ("11", "11.5"), ("12", "12")])
    result = run_long_only_backtest(
        bars,
        [signal(bars[0], "1"), signal(bars[1], "0")],
        open_times_by_bar_timestamp=opens,
        config=config(
            commission_rate="0.01",
            sell_fee_rate="0.002",
            slippage_bps="100",
            lot_size=10,
        ),
    )

    assert [trade.side for trade in result.trades] == ["BUY", "SELL"]
    assert result.trades[0].fill_price == Decimal("11.11")
    assert result.trades[0].quantity % 10 == 0
    assert result.trades[1].fill_price == Decimal("11.88")
    assert result.ending_shares == 0
    assert result.ending_cash < Decimal("1080")


def test_newer_signal_supersedes_stale_signal_arriving_late():
    bars, opens = make_bars([("10", "10")] * 4)
    newer = signal(bars[1], "0")
    delayed_stale = TargetExposureSignal(
        timestamp=bars[0].timestamp,
        available_at=opens[bars[2].timestamp] + timedelta(hours=1),
        target_exposure=Decimal("1"),
    )
    result = run_long_only_backtest(
        bars,
        [delayed_stale, newer],
        open_times_by_bar_timestamp=opens,
        config=config(),
    )

    assert result.trades == ()
    assert result.ending_shares == 0


def test_rejects_signals_that_claim_availability_before_source_bar():
    bars, opens = make_bars([("10", "10"), ("10", "10")])
    bad = TargetExposureSignal(
        timestamp=bars[0].timestamp,
        available_at=bars[0].timestamp,
        target_exposure=Decimal("1"),
    )
    with pytest.raises(BacktestValidationError, match="source bar availability"):
        run_long_only_backtest(
            bars, [bad], open_times_by_bar_timestamp=opens, config=config()
        )


def test_rejects_duplicate_signal_timestamps_and_bad_execution_times():
    bars, opens = make_bars([("10", "10"), ("10", "10")])
    with pytest.raises(BacktestValidationError, match="one target signal"):
        run_long_only_backtest(
            bars,
            [signal(bars[0], "1"), signal(bars[0], "0")],
            open_times_by_bar_timestamp=opens,
            config=config(),
        )
    bad_opens = dict(opens)
    bad_opens[bars[0].timestamp] = bars[0].timestamp
    with pytest.raises(BacktestValidationError, match="must precede"):
        run_long_only_backtest(
            bars, [], open_times_by_bar_timestamp=bad_opens, config=config()
        )


def test_rejects_inconsistent_symbols_and_missing_open_times():
    bars, opens = make_bars([("10", "10"), ("10", "10")])
    other = MarketBar(
        symbol="VIC",
        timestamp=bars[1].timestamp,
        open=Decimal(10),
        high=Decimal(11),
        low=Decimal(9),
        close=Decimal(10),
        volume=100,
        source="fixture",
        available_at=bars[1].available_at,
    )
    with pytest.raises(BacktestValidationError, match="same symbol"):
        run_long_only_backtest(
            [bars[0], other],
            [],
            open_times_by_bar_timestamp=opens,
            config=config(),
        )
    with pytest.raises(BacktestValidationError, match="missing opening timestamp"):
        run_long_only_backtest(
            bars, [], open_times_by_bar_timestamp={bars[0].timestamp: opens[bars[0].timestamp]},
            config=config(),
        )


def test_config_requires_positive_cash_and_explicit_nonnegative_costs():
    with pytest.raises(BacktestValidationError, match="initial_cash"):
        config(initial_cash="0")
    with pytest.raises(BacktestValidationError, match="lot_size"):
        config(lot_size=0)
    with pytest.raises(BacktestValidationError, match="slippage_bps"):
        config(slippage_bps="10000")


def test_empty_backtest_returns_initial_cash():
    result = run_long_only_backtest(
        [],
        [],
        open_times_by_bar_timestamp={},
        config=config(initial_cash="1234.5"),
    )

    assert result.ending_equity == Decimal("1234.5")
    assert result.total_return_pct == 0
    assert result.equity_curve == ()
