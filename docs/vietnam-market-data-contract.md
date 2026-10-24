# Vietnam market data foundation

## Status

This is the first isolated implementation slice for Vietnam-market support. It adds a
validated OHLCV data contract only. It does **not** connect a live data vendor, change
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

1. Compare candidate Vietnam data sources for coverage, historical depth, licensing,
   adjustment policy, timestamps, and rate limits.
2. Implement one adapter behind a source-neutral interface, with fixtures and tests.
3. Add point-in-time fundamentals and corporate actions.
4. Add a portfolio backtester with cash, position sizing, costs, liquidity constraints,
   benchmark comparisons, and explicit survivorship/look-ahead controls.
5. Integrate the new provider into the graph only after tests and a reviewed design.

All development is on feature/vietnam-market-foundation; the upstream project and
its main branch are left untouched.
