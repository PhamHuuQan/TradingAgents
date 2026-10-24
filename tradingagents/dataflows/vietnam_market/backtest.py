"""Event-aware, long-only portfolio backtesting over normalized OHLCV bars.

No network, broker, account, or order endpoint is used. Callers must explicitly
supply historical opening timestamps and cost/lot assumptions. Signals are executed
at the first later bar open strictly after the signal became available.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from tradingagents.dataflows.vietnam_market.models import MarketBar

_ZERO = Decimal(0)
_ONE = Decimal(1)
_HUNDRED = Decimal(100)
_BPS_DENOMINATOR = Decimal(10_000)


class BacktestValidationError(ValueError):
    """Raised when the bars, signals, or execution assumptions are inconsistent."""


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Explicit assumptions; rates are fractions, not percentage numbers."""

    initial_cash: Decimal
    commission_rate: Decimal
    sell_fee_rate: Decimal
    slippage_bps: Decimal
    lot_size: int

    def __post_init__(self) -> None:
        if not isinstance(self.initial_cash, Decimal) or not self.initial_cash.is_finite():
            raise BacktestValidationError("initial_cash must be a finite Decimal")
        if self.initial_cash <= _ZERO:
            raise BacktestValidationError("initial_cash must be positive")
        for field_name in ("commission_rate", "sell_fee_rate", "slippage_bps"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise BacktestValidationError(f"{field_name} must be a finite Decimal")
            if value < _ZERO:
                raise BacktestValidationError(f"{field_name} must be non-negative")
        if self.commission_rate + self.sell_fee_rate >= _ONE:
            raise BacktestValidationError("combined sell fee rates must be less than 1")
        if self.slippage_bps >= _BPS_DENOMINATOR:
            raise BacktestValidationError("slippage_bps must be below 10000")
        if isinstance(self.lot_size, bool) or not isinstance(self.lot_size, int) or self.lot_size < 1:
            raise BacktestValidationError("lot_size must be a positive integer")


@dataclass(frozen=True, slots=True)
class TargetExposureSignal:
    """A target stock exposure based on a bar and known only at available_at.

    target_exposure must be between 0 and 1 inclusive. This implementation has
    no short selling, leverage, or borrowing.
    """

    timestamp: datetime
    available_at: datetime
    target_exposure: Decimal

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.timestamp, "signal timestamp")
        _validate_aware_datetime(self.available_at, "signal available_at")
        if self.available_at < self.timestamp:
            raise BacktestValidationError("signal available_at cannot precede signal timestamp")
        if not isinstance(self.target_exposure, Decimal) or not self.target_exposure.is_finite():
            raise BacktestValidationError("target_exposure must be a finite Decimal")
        if not _ZERO <= self.target_exposure <= _ONE:
            raise BacktestValidationError("target_exposure must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    signal_timestamp: datetime
    executed_at: datetime
    bar_timestamp: datetime
    side: Literal["BUY", "SELL"]
    quantity: int
    reference_price: Decimal
    fill_price: Decimal
    commission: Decimal
    sell_fee: Decimal
    cash_after: Decimal


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    cash: Decimal
    shares: int
    close_price: Decimal
    equity: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    symbol: str | None
    source: str | None
    starting_cash: Decimal
    ending_cash: Decimal
    ending_shares: int
    ending_equity: Decimal
    total_return_pct: Decimal
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquityPoint, ...]


def _validate_aware_datetime(value: object, name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise BacktestValidationError(f"{name} must be a timezone-aware datetime")


def _floor_to_lot(quantity: Decimal, lot_size: int) -> int:
    lots = (quantity / Decimal(lot_size)).to_integral_value(rounding=ROUND_FLOOR)
    return int(lots) * lot_size


def run_long_only_backtest(
    bars: Iterable[MarketBar],
    signals: Iterable[TargetExposureSignal],
    *,
    open_times_by_bar_timestamp: Mapping[datetime, datetime],
    config: BacktestConfig,
) -> BacktestResult:
    """Run a single-instrument, cash-only historical simulation.

    Bars must be strictly timestamp-ordered and from one symbol/source. For every
    bar, callers must provide its actual opening timestamp keyed by bar timestamp.
    Signals must refer to an input bar, and their availability may not precede the
    source bar's availability. A signal is eligible only when available_at is
    strictly before a later bar's opening time; execution uses that later bar's
    open price with configured slippage.

    Equity is marked to each bar's close. The simulator does not force-liquidate
    at the end, does not model dividends/corporate actions, and does not model
    trading halts, price limits, queue priority, partial fills, or tiered fee rules.
    """
    if not isinstance(config, BacktestConfig):
        raise TypeError("config must be a BacktestConfig")

    items = tuple(bars)
    targets = tuple(signals)
    if not items:
        if targets:
            raise BacktestValidationError("signals cannot be used without input bars")
        return BacktestResult(
            symbol=None,
            source=None,
            starting_cash=config.initial_cash,
            ending_cash=config.initial_cash,
            ending_shares=0,
            ending_equity=config.initial_cash,
            total_return_pct=_ZERO,
            trades=(),
            equity_curve=(),
        )

    for index, bar in enumerate(items):
        if not isinstance(bar, MarketBar):
            raise TypeError(f"bars[{index}] must be a MarketBar")
        if index == 0:
            continue
        previous = items[index - 1]
        if bar.symbol != previous.symbol:
            raise BacktestValidationError("all bars must belong to the same symbol")
        if bar.source != previous.source:
            raise BacktestValidationError("all bars must use the same data source")
        if bar.timestamp <= previous.timestamp:
            raise BacktestValidationError("bars must be strictly ordered by timestamp")

    by_timestamp = {bar.timestamp: bar for bar in items}
    if len(by_timestamp) != len(items):
        raise BacktestValidationError("bar timestamps must be unique")

    open_times: dict[datetime, datetime] = {}
    previous_open: datetime | None = None
    for bar in items:
        if bar.timestamp not in open_times_by_bar_timestamp:
            raise BacktestValidationError(
                f"missing opening timestamp for bar {bar.timestamp.isoformat()}"
            )
        open_at = open_times_by_bar_timestamp[bar.timestamp]
        _validate_aware_datetime(open_at, "bar open timestamp")
        if open_at >= bar.timestamp:
            raise BacktestValidationError("bar open timestamp must precede bar timestamp")
        if open_at.date() != bar.timestamp.astimezone(open_at.tzinfo).date():
            raise BacktestValidationError("bar open and bar timestamp must be on the same local date")
        if previous_open is not None and open_at <= previous_open:
            raise BacktestValidationError("bar opening timestamps must be strictly ordered")
        open_times[bar.timestamp] = open_at
        previous_open = open_at

    signals_by_timestamp: dict[datetime, TargetExposureSignal] = {}
    for index, signal in enumerate(targets):
        if not isinstance(signal, TargetExposureSignal):
            raise TypeError(f"signals[{index}] must be a TargetExposureSignal")
        source_bar = by_timestamp.get(signal.timestamp)
        if source_bar is None:
            raise BacktestValidationError("each signal timestamp must match an input bar")
        if signal.available_at < source_bar.available_at:
            raise BacktestValidationError(
                "signal available_at cannot precede its source bar availability"
            )
        if signal.timestamp in signals_by_timestamp:
            raise BacktestValidationError("only one target signal is allowed per bar")
        signals_by_timestamp[signal.timestamp] = signal

    pending = tuple(sorted(targets, key=lambda signal: signal.timestamp))
    processed: set[datetime] = set()
    last_applied_signal: datetime | None = None
    cash = config.initial_cash
    shares = 0
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []
    slippage = config.slippage_bps / _BPS_DENOMINATOR

    for bar in items:
        open_at = open_times[bar.timestamp]
        eligible: list[TargetExposureSignal] = []
        for signal in pending:
            if signal.timestamp in processed:
                continue
            if signal.timestamp < bar.timestamp and signal.available_at < open_at:
                processed.add(signal.timestamp)
                if last_applied_signal is None or signal.timestamp > last_applied_signal:
                    eligible.append(signal)

        if eligible:
            selected = max(eligible, key=lambda signal: signal.timestamp)
            equity_at_open = cash + Decimal(shares) * bar.open
            target_shares = _floor_to_lot(
                (equity_at_open * selected.target_exposure) / bar.open,
                config.lot_size,
            )

            if target_shares > shares:
                needed = target_shares - shares
                fill_price = bar.open * (_ONE + slippage)
                per_share_cost = fill_price * (_ONE + config.commission_rate)
                affordable = _floor_to_lot(cash / per_share_cost, config.lot_size)
                quantity = min(needed, affordable)
                quantity = _floor_to_lot(Decimal(quantity), config.lot_size)
                if quantity > 0:
                    notional = fill_price * Decimal(quantity)
                    commission = notional * config.commission_rate
                    cash -= notional + commission
                    shares += quantity
                    trades.append(
                        BacktestTrade(
                            signal_timestamp=selected.timestamp,
                            executed_at=open_at,
                            bar_timestamp=bar.timestamp,
                            side="BUY",
                            quantity=quantity,
                            reference_price=bar.open,
                            fill_price=fill_price,
                            commission=commission,
                            sell_fee=_ZERO,
                            cash_after=cash,
                        )
                    )
            elif target_shares < shares:
                quantity = shares - target_shares
                fill_price = bar.open * (_ONE - slippage)
                notional = fill_price * Decimal(quantity)
                commission = notional * config.commission_rate
                sell_fee = notional * config.sell_fee_rate
                cash += notional - commission - sell_fee
                shares -= quantity
                trades.append(
                    BacktestTrade(
                        signal_timestamp=selected.timestamp,
                        executed_at=open_at,
                        bar_timestamp=bar.timestamp,
                        side="SELL",
                        quantity=quantity,
                        reference_price=bar.open,
                        fill_price=fill_price,
                        commission=commission,
                        sell_fee=sell_fee,
                        cash_after=cash,
                    )
                )

        equity_curve.append(
            EquityPoint(
                timestamp=bar.timestamp,
                cash=cash,
                shares=shares,
                close_price=bar.close,
                equity=cash + Decimal(shares) * bar.close,
            )
        )

    ending_equity = equity_curve[-1].equity
    total_return_pct = (ending_equity / config.initial_cash - _ONE) * _HUNDRED
    return BacktestResult(
        symbol=items[0].symbol,
        source=items[0].source,
        starting_cash=config.initial_cash,
        ending_cash=cash,
        ending_shares=shares,
        ending_equity=ending_equity,
        total_return_pct=total_return_pct,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
    )
