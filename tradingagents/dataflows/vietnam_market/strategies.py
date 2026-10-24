"""Reference signal generators for offline strategy research.

These helpers create time-aware target-exposure signals; they do not place orders
or make claims that a strategy is profitable.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from tradingagents.dataflows.vietnam_market.backtest import TargetExposureSignal
from tradingagents.dataflows.vietnam_market.models import MarketBar
from tradingagents.dataflows.vietnam_market.technicals import simple_moving_average

_ZERO = Decimal(0)
_ONE = Decimal(1)


def sma_crossover_signals(
    bars: Iterable[MarketBar],
    *,
    fast_period: int = 20,
    slow_period: int = 50,
    long_exposure: Decimal = _ONE,
) -> list[TargetExposureSignal]:
    """Go long when fast SMA is above slow SMA; otherwise target cash.

    The first decision is emitted as soon as both moving averages are available,
    rather than claiming to have observed an earlier crossover outside the data
    window. Thereafter a signal is emitted only when the target exposure changes.
    Signal availability is the later availability timestamp of its two inputs.
    """
    for name, period in (("fast_period", fast_period), ("slow_period", slow_period)):
        if isinstance(period, bool) or not isinstance(period, int) or period < 1:
            raise ValueError(f"{name} must be a positive integer")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")
    if not isinstance(long_exposure, Decimal) or not long_exposure.is_finite():
        raise ValueError("long_exposure must be a finite Decimal")
    if not _ZERO <= long_exposure <= _ONE:
        raise ValueError("long_exposure must be between 0 and 1")

    items = tuple(bars)
    if not items:
        return []
    fast = simple_moving_average(items, fast_period)
    slow = simple_moving_average(items, slow_period)
    fast_by_timestamp = {point.timestamp: point for point in fast}
    current_target = _ZERO
    signals: list[TargetExposureSignal] = []

    for slow_point in slow:
        fast_point = fast_by_timestamp.get(slow_point.timestamp)
        if fast_point is None:
            continue
        next_target = long_exposure if fast_point.value > slow_point.value else _ZERO
        if next_target == current_target:
            continue
        signals.append(
            TargetExposureSignal(
                timestamp=slow_point.timestamp,
                available_at=max(fast_point.available_at, slow_point.available_at),
                target_exposure=next_target,
            )
        )
        current_target = next_target

    return signals
