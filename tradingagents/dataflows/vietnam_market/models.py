"""Validated, source-neutral market data models for Vietnam equities.

Prices use Decimal to avoid silently introducing binary floating-point rounding.
Every bar carries its source and the time it became available, so later backtests
can reject data that would not have been observable at the decision timestamp.
This module does not fetch data or imply that a vendor feed is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}$")


class MarketDataValidationError(ValueError):
    """Raised when market data violates the common data contract."""


@dataclass(frozen=True, slots=True)
class MarketBar:
    """One OHLCV bar with explicit provenance and availability time.

    timestamp is the time represented by the bar; available_at is when the
    strategy could first have used this bar. Both timestamps must be
    timezone-aware. For daily bars, callers should use a consistent market
    timezone and set available_at to the actual publication/availability time,
    not automatically to the start of the trading date.
    """

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str
    available_at: datetime

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper() if isinstance(self.symbol, str) else ""
        if not _SYMBOL_RE.fullmatch(symbol):
            raise MarketDataValidationError(
                f"symbol must be 2-12 letters/digits without a vendor suffix, got {self.symbol!r}"
            )
        object.__setattr__(self, "symbol", symbol)

        for field_name in ("timestamp", "available_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise MarketDataValidationError(f"{field_name} must be a timezone-aware datetime")

        if self.available_at < self.timestamp:
            raise MarketDataValidationError("available_at cannot precede the bar timestamp")

        prices = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }
        for field_name, value in prices.items():
            if not isinstance(value, Decimal):
                raise MarketDataValidationError(f"{field_name} must be Decimal, not {type(value).__name__}")
            if not value.is_finite() or value <= 0:
                raise MarketDataValidationError(f"{field_name} must be a finite positive price")

        if self.high < max(self.open, self.close, self.low):
            raise MarketDataValidationError("high must be greater than or equal to open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise MarketDataValidationError("low must be less than or equal to open, close, and high")

        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise MarketDataValidationError("volume must be a non-negative integer")
        if not isinstance(self.source, str) or not self.source.strip():
            raise MarketDataValidationError("source must be a non-empty string")
        object.__setattr__(self, "source", self.source.strip())
