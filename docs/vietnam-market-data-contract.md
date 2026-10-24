# Vietnam market data foundation

## Status

This slice provides a validated OHLCV contract, a read-only SSI FastConnect V3 adapter,
offline technical indicators, a point-in-time fundamental-fact model, a configurable
long-only backtest simulator, a reference SMA-crossover signal generator, portfolio
performance statistics, and point-in-time valuation metric derivation. It does not configure live credentials, change existing Yahoo
Finance routing, alter the agent graph, or place orders.

## OHLCV and point-in-time facts

MarketBar stores normalized OHLCV, provenance, bar time, and data availability.
FundamentalFact stores a reported metric for one explicit period, unit, source, and
available_at timestamp. latest_fundamental_facts_as_of selects revisions known by a
cutoff and keeps sources separate. Neither data contract fetches statements or decides
unit conversions/corporate-action treatment automatically.

## Point-in-time valuation metrics

build_valuation_metrics derives market capitalization, TTM P/E, P/B, EPS, ROE,
free cash flow, and operating-cash-flow-to-net-income from explicitly normalized
facts. All facts and price bars must be available by the as-of timestamp, and
fundamentals are restricted to one named source and consistent units. TTM flow
metrics require four complete, contiguous standalone quarterly periods; YTD
cumulative records are not summed as if they were separate quarters. EPS also
requires matching quarterly weighted-average-share facts. ROE requires opening
and closing equity facts near the TTM endpoints. Missing, negative, or ambiguous
inputs result in unavailable metrics and warnings, not guessed values.

The valuation module consumes normalized facts only. It does not fetch filings,
calculate vendor-specific TTM values from raw statements, or convert currencies.
Before using results for investment decisions, verify whether the chosen source
reports standalone-quarter values, per-share units, capex sign conventions,
share counts, and accounting restatements as expected.

Each snapshot returns the selected price bar's timestamp and availability time,
the period end/availability time of the selected share count and equity facts,
and the start/end dates of the TTM earnings window. These are input provenance,
not a guarantee that a vendor's historical record is complete. The current
conservative age limits are 180 days for balance-sheet equity and 365 days for
shares outstanding; stale facts remain visible by period date but ratios
depending on them are withheld with a warning. Review those policy limits
before relying on a snapshot for an instrument/market with different filing
cadence or corporate-action frequency.

## Offline CSV-to-valuation report

The normalized CSV readers provide a no-network path for validating data and
calculations before enabling any vendor access. Headers are strict so common
misspellings do not silently drop data. The OHLCV file requires:

`symbol,timestamp,open,high,low,close,volume,source,available_at`

The fundamentals file requires:

`symbol,metric,value,unit,period_start,period_end,source,available_at`

It may additionally include `published_at` and `source_record_id`. Timestamps
must be ISO-8601 and timezone-aware. Values must already be normalized to one
explicit currency/share unit and to standalone quarter periods for TTM metrics.

Run the bundled **synthetic demo** from the repository root after installing
the project. These files are test values only, not real FPT market data:

~~~powershell
python -m tradingagents.dataflows.vietnam_market.report --symbol FPT --as-of 2026-03-01T19:00:00+07:00 --bars examples/vietnam_market/synthetic_demo_bars.csv --facts examples/vietnam_market/synthetic_demo_facts.csv --price-source synthetic-demo-prices --fundamental-source synthetic-demo-statements --price-unit VND/share --currency-unit VND
~~~

The CLI prints a JSON snapshot. Missing ratios are returned as `null` with
warnings rather than guessed numbers. The price-source and fundamental-source
must be selected separately and exactly; source names do not imply that the
feed is authorized, complete, adjusted, or historically point-in-time. To use
your own inputs, keep the same CSV headers and replace the demo files with
normalized, sourced observations whose availability timestamps you have verified.

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

### Export SSI OHLCV to the normalized CSV format

After credentials are set privately in your local PowerShell terminal, export bars
without placing orders:

~~~powershell
python -m pip install -e ".[ssi]"
python -m tradingagents.dataflows.vietnam_market.export_ssi_bars --symbol FPT --from-date 2025-10-01 --to-date 2026-10-23 --output data\fpt_bars.csv
~~~

The exporter writes the same strict OHLCV schema consumed by the offline valuation
CLI. It refuses to overwrite an existing file unless `--overwrite` is passed.
The `available_at` field is the time this export was fetched, not the historical
first-availability time; use the result for current/as-fetched research only, not
for historical point-in-time backtests. A request reaching the 1,000-row limit
emits a possible-truncation warning.

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
- No statement/fundamental ingestion; valuation ratios require normalized facts supplied by a caller.
- No validated Vietnamese calendar/tick-size/price-limit/corporate-action source.
- No integration into the current agent graph or production deployment.

Next: build a source-specific, point-in-time statement ingestion layer and verify SSI historical-data/adjustment semantics before connecting these primitives to the agent graph. Main and upstream remain
unchanged; all changes are on the feature branch.
