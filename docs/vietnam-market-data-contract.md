# Vietnam market data foundation

## Status

This slice provides a validated OHLCV contract, a read-only SSI FastConnect V3 adapter,
offline technical indicators, a point-in-time fundamental-fact model, a configurable
long-only backtest simulator, a reference SMA-crossover signal generator, and portfolio
performance statistics. It does not configure live credentials, change existing Yahoo
Finance routing, alter the agent graph, or place orders.

## OHLCV and point-in-time facts

MarketBar stores normalized OHLCV, provenance, bar time, and data availability.
FundamentalFact stores a reported metric for one explicit period, unit, source, and
available_at timestamp. latest_fundamental_facts_as_of selects revisions known by a
cutoff and keeps sources separate. Neither data contract fetches statements or decides
unit conversions/corporate-action treatment automatically.

## Offline technical indicators and reference strategy

The package exports SMA, EMA, Wilder RSI, Wilder ATR, and close-to-close percentage
returns. IndicatorPoint carries the bar timestamp, Decimal value, and conservative
available_at. Returns exclude dividends; corporate-action adjustments are not automatic.

sma_crossover_signals creates long-only target-exposure signals when a fast SMA is above
or below a slower SMA. Signals are available only after both averages are known. This is
a reference implementation to validate research plumbing, not an investment recommendation
or evidence that the strategy is profitable.

## Long-only backtest simulator

run_long_only_backtest(bars, signals, open_times_by_bar_timestamp=..., config=...)
provides a single-instrument, cash-only historical simulation. Each signal has a target
exposure between zero and one and an explicit availability time. Execution uses the next
bar's open only when its caller-supplied opening timestamp is strictly after the signal's
availability. Equity is marked at each close; the final position is not force-liquidated.

Every BacktestConfig requires initial cash, commission rate, sell-side fee rate, slippage
in basis points, and lot size. Rates are fractions: 0.001 means 0.1%. No Vietnamese tick
size, lot rule, trading calendar, tax, or broker fee is hard-coded.

This engine does not model margin/shorts, dividends, corporate actions, trading halts,
price limits, queue priority, partial fills, tiered commissions, or market impact. Apply
the exact fee schedule, adjusted-price policy, survivorship controls, and point-in-time
rules before using it on real history.

## Performance summary

summarize_backtest reports total return, maximum drawdown, annualized volatility, Sharpe
ratio, average exposure, trade counts, fees, estimated slippage cost, and turnover.
periods_per_year is mandatory so the annualization convention is not hidden. The annual
risk-free rate is a fractional rate, such as 0.03 for 3%; Sharpe uses a simple annual-rate
divided by periods_per_year approximation and sample volatility. Fees include only
configured commission and sell-side fees. Statistics are only as reliable as the price,
calendar, adjustment, and cost assumptions.

## Read-only SSI connectivity smoke test

After the account owner enables SSI FastConnect **Market Data-only** access, there are
two ways to run the check. Both are read-only and do not place orders.

### PowerShell helper (Windows)

From the repository root:

~~~powershell
python -m pip install -e ".[ssi]"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\ssi_readonly_smoke.ps1 -Symbol FPT -FromDate 2026-10-20 -ToDate 2026-10-23
~~~

The script securely prompts for any missing SSI_CLIENT_ID, SSI_API_KEY, and
SSI_API_SECRET; typed inputs are hidden. It sets them only in the current process
environment for the smoke command, then removes/restores those environment values.
It does not write credentials to Git, a .env file, or a local config file. The
PowerShell execution-policy change is scoped to that terminal process.

### Direct command

If the variables are already set in your own terminal:

~~~powershell
python -m pip install -e ".[ssi]"
python -m tradingagents.dataflows.vietnam_market.smoke --symbol FPT --from-date 2026-10-20 --to-date 2026-10-23
~~~

Never paste credentials into chat, screenshots, issues, logs, or Git. The smoke command's
fetched-at time is for connectivity/parsing validation only, not historical point-in-time
data. It is not evidence of when historical SSI bars first became available. No live SSI
request has been made during development.

## Remaining gaps

- No guessed Yahoo suffix mapping for HOSE, HNX, or UPCoM.
- No live SSI credentials or live-data request.
- No statement/fundamental ingestion or historical valuation ratio calculation.
- No validated Vietnamese calendar/tick-size/price-limit/corporate-action source.
- No integration into the current agent graph or production deployment.

Next: verify SSI account entitlements and historical-data/adjustment semantics, then build
permitted source ingestion and corporate-action handling. Main and upstream remain
unchanged; all changes are on the feature branch.
