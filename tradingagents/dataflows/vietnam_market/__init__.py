"""Vietnam-market data contracts.

This package starts with validated, source-neutral data models. Concrete vendor
adapters and graph integration are intentionally deferred to later changes.
"""

from tradingagents.dataflows.vietnam_market.models import MarketBar, MarketDataValidationError

__all__ = ["MarketBar", "MarketDataValidationError"]
