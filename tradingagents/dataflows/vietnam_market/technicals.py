"""Deterministic technical indicators over validated Vietnam-market OHLCV bars.

These functions are vendor-neutral and offline. Outputs carry timestamps and conservative
data-availability times so research cannot consume a signal before its inputs were observed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tradingagents.dataflows.vietnam_market.models import MarketBar

_ZERO = Decimal(0)
_ONE = Decimal(1)
_TWO = Decimal(2)
_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class IndicatorPoint:
    """One indicator value and the earliest safe time to consume that value."""

    timestamp: datetime
    value: Decimal
    available_at: datetime


def _validated_series(bars: Iterable[MarketBar]) -> tuple[MarketBar, ...]:
    items = tuple(bars)
    for index, bar in enumerate(items):
        if not isinstance(bar, MarketBar):
            raise TypeError(f"bars[{index}] must be a MarketBar")
        if index == 0:
            continue
        previous = items[index - 1]
        if bar.symbol != previous.symbol:
            raise ValueError("all bars must belong to the same symbol")
        if bar.source != previous.source:
            raise ValueError("all bars must use the same data source; do not mix vendor prices")
        if bar.timestamp <= previous.timestamp:
            raise ValueError("bars must be strictly ordered by timestamp with no duplicates")
    return items


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")


def _availability(
    bars: tuple[MarketBar, ...], end_index: int, start_index: int = 0
) -> datetime:
    """Return the latest availability time among all inputs needed for a value."""
    return max(bar.available_at for bar in bars[start_index : end_index + 1])


def simple_moving_average(
    bars: Iterable[MarketBar], period: int
) -> list[IndicatorPoint]:
    """Calculate close-price SMA, first emitted at index period - 1."""
    _validate_period(period)
    items = _validated_series(bars)
    if len(items) < period:
        return []

    points: list[IndicatorPoint] = []
    running_sum = sum((bar.close for bar in items[:period]), _ZERO)
    for index in range(period - 1, len(items)):
        if index >= period:
            running_sum += items[index].close - items[index - period].close
        points.append(
            IndicatorPoint(
                timestamp=items[index].timestamp,
                value=running_sum / Decimal(period),
                available_at=_availability(items, index, index - period + 1),
            )
        )
    return points


def exponential_moving_average(
    bars: Iterable[MarketBar], period: int
) -> list[IndicatorPoint]:
    """Calculate EMA using an SMA seed and alpha = 2 / (period + 1)."""
    _validate_period(period)
    items = _validated_series(bars)
    if len(items) < period:
        return []

    ema = sum((bar.close for bar in items[:period]), _ZERO) / Decimal(period)
    alpha = _TWO / Decimal(period + 1)
    points = [
        IndicatorPoint(
            timestamp=items[period - 1].timestamp,
            value=ema,
            available_at=_availability(items, period - 1),
        )
    ]
    for index in range(period, len(items)):
        ema = items[index].close * alpha + ema * (_ONE - alpha)
        points.append(
            IndicatorPoint(
                timestamp=items[index].timestamp,
                value=ema,
                available_at=_availability(items, index),
            )
        )
    return points


def relative_strength_index(
    bars: Iterable[MarketBar], period: int = 14
) -> list[IndicatorPoint]:
    """Calculate Wilder RSI; a flat window maps to 50 and gain-only to 100."""
    _validate_period(period)
    items = _validated_series(bars)
    if len(items) <= period:
        return []

    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(items, items[1:]):
        change = current.close - previous.close
        gains.append(max(change, _ZERO))
        losses.append(max(-change, _ZERO))

    average_gain = sum(gains[:period], _ZERO) / Decimal(period)
    average_loss = sum(losses[:period], _ZERO) / Decimal(period)
    points: list[IndicatorPoint] = []

    for index in range(period, len(items)):
        if index > period:
            average_gain = (
                average_gain * Decimal(period - 1) + gains[index - 1]
            ) / Decimal(period)
            average_loss = (
                average_loss * Decimal(period - 1) + losses[index - 1]
            ) / Decimal(period)

        if average_loss == _ZERO:
            rsi = Decimal(50) if average_gain == _ZERO else _HUNDRED
        else:
            rsi = _HUNDRED - _HUNDRED / (
                _ONE + average_gain / average_loss
            )
        points.append(
            IndicatorPoint(
                timestamp=items[index].timestamp,
                value=rsi,
                available_at=_availability(items, index),
            )
        )
    return points


def average_true_range(
    bars: Iterable[MarketBar], period: int = 14
) -> list[IndicatorPoint]:
    """Calculate Wilder ATR from period true ranges and the previous close."""
    _validate_period(period)
    items = _validated_series(bars)
    if len(items) <= period:
        return []

    true_ranges: list[Decimal] = []
    for previous, current in zip(items, items[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    atr = sum(true_ranges[:period], _ZERO) / Decimal(period)
    points = [
        IndicatorPoint(
            timestamp=items[period].timestamp,
            value=atr,
            available_at=_availability(items, period),
        )
    ]
    for index in range(period + 1, len(items)):
        atr = (
            atr * Decimal(period - 1) + true_ranges[index - 1]
        ) / Decimal(period)
        points.append(
            IndicatorPoint(
                timestamp=items[index].timestamp,
                value=atr,
                available_at=_availability(items, index),
            )
        )
    return points


def percentage_returns(bars: Iterable[MarketBar]) -> list[IndicatorPoint]:
    """Calculate close-to-close percentage price returns, excluding dividends."""
    items = _validated_series(bars)
    points: list[IndicatorPoint] = []
    for index in range(1, len(items)):
        change_pct = (items[index].close / items[index - 1].close - _ONE) * _HUNDRED
        points.append(
            IndicatorPoint(
                timestamp=items[index].timestamp,
                value=change_pct,
                available_at=_availability(items, index),
            )
        )
    return points
