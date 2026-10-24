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

## Read-only SSI connectivity smoke test

After the account owner has enabled SSI FastConnect **Market Data-only** access and
installed the optional SDK, run the smoke command locally. It does not place orders
or request trading permissions.

```powershell
python -m pip install -e ".[ssi]"
$env:SSI_CLIENT_ID = "your-client-id"
$env:SSI_API_KEY = "your-api-key"
$env:SSI_API_SECRET = "your-api-secret"
python -m tradingagents.dataflows.vietnam_market.smoke --symbol FPT --from-date 2026-10-20 --to-date 2026-10-23
```

Set these variables only in your own terminal or approved secret manager. Never paste
the values into chat, screenshots, issues, logs, or Git. The smoke command prints a
normalized row count and the latest returned OHLCV bar, but does not print credentials.

**Important:** the command records the time the response was fetched as a conservative
availability timestamp. That is suitable only for checking connectivity and parsing;
it is not the historical publication time and must not be used to claim point-in-time
backtest validity. The smoke command requires a closed-day date range and will reject
a bar whose close is later than the fetch timestamp.

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
