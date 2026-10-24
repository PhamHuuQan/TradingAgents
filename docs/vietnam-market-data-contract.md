# Vietnam market data foundation

## Status

This isolated implementation slice provides a validated OHLCV contract, a read-only
SSI FastConnect V3 daily-OHLC adapter, offline technical indicators, and a point-in-time
fundamental-fact model. It does not configure live credentials, change existing Yahoo
Finance routing, alter the agent graph, or place orders.

## OHLCV contract

The tradingagents.dataflows.vietnam_market.models.MarketBar record stores a normalized
ticker, timezone-aware bar and availability timestamps, Decimal OHLC prices, non-negative
integer volume, and source provenance. It rejects impossible OHLC values and data marked
available before the bar timestamp.

Daily-bar adapters must set available_at to the actual time data was published or
otherwise accessible, not merely the beginning of the trading date. Backtests must use
the availability timestamp to avoid look-ahead bias.

## Point-in-time fundamental facts

The FundamentalFact record stores one reported metric for one explicit reporting period,
with a Decimal value, an explicit unit, source identifier, publication time when known,
and mandatory timezone-aware available_at. Values are not rescaled, currency-converted,
annualized, or interpreted automatically.

latest_fundamental_facts_as_of(facts, as_of, symbol=..., source=...) selects the latest
version of each source/metric/period/unit record available by the requested cutoff.
Later revisions are excluded from earlier as-of dates. Different sources are kept
separately; conflicting same-source values at an identical availability timestamp
raise an error rather than silently choosing a value.

This is a data contract, not a vendor ingestion pipeline. It does not calculate EPS,
ROE, P/E, P/B or TTM values; such calculations require consistent statement types,
share counts, units/currencies, restatement treatment, and a clear point-in-time policy.
Do not treat a period end or public filing date as proof that a value was available to a
strategy at a particular time. The caller must provide verified availability metadata.

## Read-only SSI connectivity smoke test

After the account owner has enabled SSI FastConnect Market Data-only access and
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

The command records response-fetch time as a conservative availability timestamp.
That is suitable only for connectivity/parsing validation; it is not historical
publication time and must not be used to claim point-in-time backtest validity.

## Offline technical indicators

The tradingagents.dataflows.vietnam_market package exports deterministic calculations
over MarketBar data without vendor calls or an LLM:

- simple_moving_average(bars, period) and exponential_moving_average(bars, period);
- relative_strength_index(bars, period=14) using Wilder smoothing;
- average_true_range(bars, period=14) using the prior close;
- percentage_returns(bars) for close-to-close price changes in percent.

Each IndicatorPoint carries the represented bar timestamp, a Decimal value, and
conservative available_at. Series must be time-ordered and cannot mix symbols or sources.
These are calculation primitives, not trade signals. Percentage returns exclude
dividends, and corporate-action adjustments are not performed automatically.

## Current gaps and next steps

- No guessed Yahoo suffix mapping for HOSE, HNX, or UPCoM.
- No live SSI credentials, live-data requests, or trading scopes.
- No portfolio simulation or order execution.
- Verify data-source entitlement, historical depth, publication timing and adjustment
  semantics before integrating a provider into historical backtests.
- Implement source-specific ingestion and corporate-action adjustments, then add a
  backtester with cash, fees, slippage, lot/tick rules, liquidity constraints, benchmark
  comparisons, and explicit survivorship/look-ahead controls.
- Keep market-data adapters separate from the agent graph until parity tests are reviewed.

All development remains on feature/vietnam-market-foundation; main and upstream are
left unchanged.
