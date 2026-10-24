# Vietnam market data foundation

## Status

This slice provides a validated OHLCV contract, a read-only SSI FastConnect V3 adapter,
offline technical indicators, a point-in-time fundamental-fact model, a configurable
long-only backtest simulator, and a reference SMA-crossover signal generator. It does not
configure live credentials, change existing Yahoo Finance routing, alter the agent graph,
or place orders.

## OHLCV contract

The MarketBar record stores a normalized ticker, timezone-aware bar and availability
timestamps, Decimal OHLC prices, non-negative integer volume, and source provenance.
It rejects impossible OHLC values and data marked available before the bar timestamp.

Adapters must set available_at to the time data was actually available, not just the
start of a trading date. Backtests must use availability metadata to avoid look-ahead bias.

## Point-in-time fundamental facts

FundamentalFact stores one reported metric for one explicit reporting period, with a
Decimal value, explicit unit, source identifier, publication time when known, and
mandatory timezone-aware available_at. Values are not rescaled, currency-converted,
annualized, or interpreted automatically.

latest_fundamental_facts_as_of(facts, as_of, symbol=..., source=...) selects the latest
version of each source/metric/period/unit record available by the requested cutoff.
Later revisions are excluded from earlier as-of dates. Different sources are kept
separately; conflicting same-source values at an identical availability timestamp
raise an error rather than silently choosing a value.

This is a data contract, not a vendor ingestion pipeline. It does not calculate EPS,
ROE, P/E, P/B or TTM values; such calculations need consistent statement types, share
counts, units/currencies, restatement treatment, and a clear point-in-time policy.

## Offline technical indicators and reference strategy

The package exports deterministic calculations over MarketBar data: SMA, EMA, Wilder
RSI, Wilder ATR, and close-to-close percentage returns. IndicatorPoint carries its bar
timestamp, Decimal value, and conservative available_at. The calculations make no
network calls. Returns exclude dividends, and corporate-action adjustments are not
performed automatically.

sma_crossover_signals creates long-only target-exposure signals when a fast SMA rises
above or falls below a slower SMA. It emits only target changes after both averages
are available; the initial target is established at the first aligned calculation.
This is a reference implementation for validating the research plumbing, not an
investment recommendation or evidence that the strategy is profitable.

## Configurable long-only backtest simulator

run_long_only_backtest(bars, signals, open_times_by_bar_timestamp=..., config=...)
provides an offline single-instrument, cash-only simulator. TargetExposureSignal describes
a target stock exposure between zero and one, with an explicit availability time. The
simulator executes a signal only at a later bar open whose caller-supplied timestamp is
strictly after the signal became available, using that bar's open price plus configured
slippage. Equity is marked to each close; the final position is marked-to-market, not
automatically liquidated.

Every BacktestConfig requires initial cash, commission rate, sell-side fee rate, slippage
in basis points, and trading lot size. Rates are fractions (for example 0.001 means 0.1%);
values are not silently interpreted as percentage numbers. No Vietnamese exchange tick
size, lot rule, trading calendar, tax, or broker fee is hard-coded; configure actual rules
for the market and period under study.

The simulator does not model margin/shorts, dividends, corporate actions, trading halts,
price limits, queue priority, partial fills, tiered commissions, or liquidity/market-impact
constraints. Results using synthetic fixtures are code validation, not evidence of
strategy profitability. Apply the exact market fee schedule, adjusted-price policy,
survivorship controls, and point-in-time data rules before using real historical prices.

## Read-only SSI connectivity smoke test

After the account owner has enabled SSI FastConnect Market Data-only access and installed
the optional SDK, run the command locally. It does not place orders.

~~~powershell
python -m pip install -e ".[ssi]"
$env:SSI_CLIENT_ID = "your-client-id"
$env:SSI_API_KEY = "your-api-key"
$env:SSI_API_SECRET = "your-api-secret"
python -m tradingagents.dataflows.vietnam_market.smoke --symbol FPT --from-date 2026-10-20 --to-date 2026-10-23
~~~

Set these variables only in your own terminal or approved secret manager. Never paste
secrets into chat, screenshots, issues, logs, or Git. The smoke command's fetched-at
time is for connectivity/parsing validation only, not historical point-in-time data.
No live SSI request has been made during development.

## Remaining gaps

- No guessed Yahoo suffix mapping for HOSE, HNX, or UPCoM.
- No live SSI credentials or live-data request.
- No statement/fundamental ingestion or historical valuation ratio calculation.
- No validated Vietnamese calendar/tick-size/price-limit/corporate-action source.
- No integration into the current agent graph or production deployment.

Next: verify SSI account entitlements and historical-data/adjustment semantics, then build
permitted source ingestion and corporate-action handling. Only after these are verified
should a research graph use this data for historical comparisons and strategy reports.
Main and upstream remain unchanged; all changes are on the feature branch.
