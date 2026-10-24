# Vietnam market data foundation

## Status

This isolated implementation slice adds a validated OHLCV data contract and a read-only
SSI FastConnect V3 daily-OHLC adapter. It does **not** configure live credentials, change
the existing Yahoo Finance routing, alter the agent graph, or place orders.

## Contract

The module tradingagents.dataflows.vietnam_market.models.MarketBar records:

- a normalized local ticker symbol (without a vendor-specific suffix);
- timezone-aware bar timestamp and data-availability timestamp;
- OHLC prices represented as Decimal;
- non-negative integer volume;
- a non-empty source identifier.

The model rejects impossible OHLC values and rejects data marked available before
the bar timestamp. Backtests must use available_at to avoid look-ahead bias.
Daily-bar adapters must set this field to the actual time the data was published or
otherwise accessible, not merely the beginning of the trading day.

## Deliberately not included yet

- no assumed Yahoo suffix mapping for HOSE, HNX, or UPCoM;
- no live or paid vendor credentials;
- no scraping, API calls, or network access;
- no changes to existing data vendor selection;
- no portfolio simulation or trade execution.

## Next increments

1. Confirm SSI API account access, current terms, rate limits, and historical-data behavior.
2. Run fixture tests and a separately opted-in read-only smoke test with Market Data-only scope.
3. Verify corporate-action adjustment policy and add point-in-time fundamentals/corporate actions.
4. Add a portfolio backtester with cash, position sizing, costs, liquidity constraints,
   benchmark comparisons, and explicit survivorship/look-ahead controls.
5. Integrate SSI into the graph only after tests and a reviewed design.

All development is on feature/vietnam-market-foundation; the upstream project and
its main branch are left untouched.
