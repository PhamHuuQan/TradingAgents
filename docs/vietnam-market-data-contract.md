# Vietnam market data foundation

## Status

This slice provides validated OHLCV and fundamental-fact contracts, optional read-only SSI
current-date market routing, optional Vnstock VCI/KBS statement normalization/export, offline
technical indicators, valuation metrics, a cash-only backtest simulator, and performance
statistics. Existing Yahoo Finance defaults remain unchanged; SSI is explicitly opt-in.
The integration does not place orders and does not recover historical first-availability times.

## OHLCV and point-in-time facts

MarketBar stores normalized OHLCV, provenance, bar time, and data availability.
FundamentalFact stores a reported metric for one explicit period, unit, source, and
available_at timestamp. latest_fundamental_facts_as_of selects revisions known by a
cutoff and keeps sources separate. Neither contract by itself decides source semantics or corporate-action treatment.

## Optional Vnstock VCI → KBS quarterly fundamentals

The optional Vnstock fetch command retrieves quarterly income, balance-sheet and
cash-flow tables through the read-only VCI source first, then retries KBS when VCI
fails. It normalizes only three explicitly mapped common VAS fields and writes them
to the same normalized facts CSV contract. The three statements in a fundamentals
summary must come from one provider; the adapter never silently combines VCI and KBS
rows in a single statement set:

- Parent-company net profit attributable to shareholders, mapped to net_income.
- Total equity (BS_EQUITY), mapped to total_equity.
- Net cash from operating activities, mapped to operating_cash_flow.

The quarterly VCI income-statement and cash-flow endpoints are documented as
standalone-quarter data; the normalizer does not subtract cumulative quarters.
Unknown metrics are ignored. It does not guess share counts, weighted-average
shares, capital expenditure, or publication times, so EPS, P/E and free-cash-flow
coverage may remain unavailable until those mappings are verified. available_at
is the local fetch completion time, not the first date a historical filing was
publicly available; do not use these exports as historical point-in-time inputs.

VCI is attempted first and KBS is the fallback by default. Set
`TRADINGAGENTS_VNSTOCK_FUNDAMENTALS_SOURCES=kbs` to pin the statement adapters to KBS,
or `vci,kbs` to explicitly retain the default order. Each response carries the source
that actually returned the data. KBS TTM flow totals are deliberately not derived until
standalone-quarter versus cumulative-flow semantics have been verified for the selected
KBS methods. Raw KBS statements and balance-sheet observations can still be displayed
with source and retrieval metadata.

Vnstock is installed from its own package index rather than the standard PyPI
index. Its official documentation describes a personal-use licence and says
third-party source data remains subject to the source provider's terms. Review
the current licence and data-provider terms before use or redistribution. The
adapter does not bundle Vnstock or add it to the base dependencies.

Official references: [Vnstock v5 financial-statement API](https://www.vnstocks.com/docs/vnstock/co-ban-fundamental),
[quarterly VCI value semantics](https://www.vnstocks.com/blog/phan-tich-bao-cao-tai-chinh-tu-cau-truc-du-lieu-vnstock),
[installation](https://www.vnstocks.com/docs/vnstock/cai-dat),
and [licensing and scope](https://www.vnstocks.com/docs/vnstock/gioi-thieu).

Run the optional fetch after installing Vnstock in your own Python environment:

~~~powershell
py -m pip install -U --extra-index-url https://vnstocks.com/api/packages vnstock
python -m tradingagents.dataflows.vietnam_market.fetch_vnstock_facts --symbol FPT --output data\fpt_facts.csv
~~~

Use --overwrite only when you explicitly intend to replace an existing file.
This read-only path does not require broker trading credentials or trading permissions.
Vnstock's current automated-run rules may require a personal `VNSTOCK_API_KEY`; if
the SDK requests it, store it in an environment variable or Colab Secrets, never in
source code, a notebook output, or a commit. This key is separate from SSI credentials
and does not enable the bot to place orders.

### Select Vnstock/SSI sources without editing Python code

The same source selectors can be set before launching the CLI. For Vnstock prices,
indicators, and the verified snapshot, run these in PowerShell from the project
environment:

~~~powershell
$env:TRADINGAGENTS_CORE_STOCK_APIS = "vnstock"
$env:TRADINGAGENTS_TECHNICAL_INDICATORS = "vnstock"
tradingagents
~~~

To route the fundamentals tools to Vnstock too, add:

~~~powershell
$env:TRADINGAGENTS_FUNDAMENTAL_DATA = "vnstock"
~~~

To try SSI instead, set both `TRADINGAGENTS_CORE_STOCK_APIS` and
`TRADINGAGENTS_TECHNICAL_INDICATORS` to `ssi`, and configure `SSI_API_KEY` and `SSI_API_SECRET` privately in that same shell. These environment
overrides are read when the process starts; open a fresh CLI process after
changing them. Blank variables do not override the defaults. Leaving the variables
unset preserves existing Yahoo Finance / SEC EDGAR defaults.

## Optional Vnstock source inside the TradingAgents graph

Vnstock fundamentals can be selected explicitly for all four fundamentals tools; each statement call tries VCI then KBS by default without
changing the default US-market sources. Install Vnstock from its official package
index (see the installation instructions above), then pass a copied config to the
graph:

~~~python
from copy import deepcopy
from tradingagents.default_config import DEFAULT_CONFIG

config = deepcopy(DEFAULT_CONFIG)
config["data_vendors"]["fundamental_data"] = "vnstock"
~~~

Use `TradingAgentsGraph(..., config=config)`. The package is imported only when
the Vnstock source is called, and the normal/default vendor chain never auto-selects
it. The adapter calls Vnstock with `period="quarter"` or `period="year"`,
`format="long"`, and `source="vci"` or `source="kbs"`; it validates that the response's
source, ticker, format, and required columns match the request.

The `get_fundamentals` summary derives TTM parent-company net income and operating
cash flow only when four contiguous standalone-quarter facts exist. It reports
the latest total equity as a point-in-time balance. It does not call the premium
`ratio()` endpoint, infer weighted-average shares, shares outstanding, capex, EPS,
P/E, P/B, ROE, or free cash flow. The detailed statement tools return source-tagged
long-format CSV.

Because these statement responses do not provide an exact historical first-
publication timestamp, historical `as_of` requests are withheld before the API is
called. Each response labels its fetch timestamp; it is for current-date research,
not an historical point-in-time backtest feed. Existing default `fundamental_data`
routing remains unchanged.

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

## Optional Vnstock VCI OHLCV route

Vnstock V5 exposes daily historical bars with `Market().equity(symbol).ohlcv(start=..., end=..., interval="1D", source="vci")`. The published VCI example reports OHLC prices in thousand VND; the opt-in adapter validates source metadata and converts OHLC to VND/share before computing indicators or returning CSV. VCI and KBS price histories can differ because their corporate-action adjustments differ, so this adapter chooses VCI explicitly and never silently switches sources. See the [Vnstock V5 Market documentation](https://www.vnstocks.com/docs/vnstock/thi-truong-market) and [Vnstock data-source documentation](https://www.vnstocks.com/docs/vnstock/tham-khao/data-sources).

Set both price and indicator categories to `vnstock` to use one provider for chart data, indicators, and verified snapshot:

~~~python
from copy import deepcopy
from tradingagents.default_config import DEFAULT_CONFIG

config = deepcopy(DEFAULT_CONFIG)
config["data_vendors"]["core_stock_apis"] = "vnstock"
config["data_vendors"]["technical_indicators"] = "vnstock"
~~~

Domestic index tickers `VNINDEX`, `VN30`, `HNXINDEX`, and `UPCOMINDEX`
are routed through Vnstock's `Market().index(symbol)` instead of `equity(symbol)`.
Their values are measured in index points and are **not** multiplied by 1,000;
only stock/ETF-style VCI OHLC values in thousand VND are converted to VND/share.
The adapter deliberately recognizes only these explicitly documented domestic
index identifiers and does not guess whether an unknown ticker is an index.

The route is current-date-only. It fetches historical rows for current-date chart context, but their `available_at` is the retrieval time, not the historical first-publication time; the graph rejects backdated analysis dates for this source. Do not use this live route as point-in-time-safe backtest input. The default price source remains Yahoo, and Vnstock is never added to the implicit `default` vendor chain.

## SSI FastConnect REST authentication and OHLC endpoint

The read-only integration uses the official REST API rather than the Python SDK:

- Authenticate with `POST https://api.ssi.com.vn/api/v3/auth/token`, JSON body `{"apiKey":"...","apiSecret":"..."}`. For Market Data-only access, the documentation says `otp` is not required.
- Fetch daily bars with `GET https://api.ssi.com.vn/api/v3/data/ohlc`, bearer token, and query parameters `symbol`, `from`, `to`, `timeFrame=1d`, `pageIndex`, and `pageSize`. Daily `from`/`to` dates use `YYYY/MM/DD`.
- Official references: [auth-token](https://developers.ssi.com.vn/docs/api-reference/auth-token) and [data-ohlc](https://developers.ssi.com.vn/docs/api-reference/data-ohlc).

The adapter requires only `SSI_API_KEY` and `SSI_API_SECRET`. Do not store credentials or bearer tokens in notebooks, source control, screenshots, or logs. The notebook prompts for credentials at runtime and clears local references after use.

## Optional SSI source inside the TradingAgents graph

SSI can be selected explicitly for both price data and technical indicators in the
existing `data_vendors` configuration. Leave the default source unchanged for other
markets; for a Vietnam current-date snapshot, set both categories to `ssi`:

~~~python
from copy import deepcopy
from tradingagents.default_config import DEFAULT_CONFIG

config = deepcopy(DEFAULT_CONFIG)
config["data_vendors"]["core_stock_apis"] = "ssi"
config["data_vendors"]["technical_indicators"] = "ssi"
~~~

Pass `config` to `TradingAgentsGraph(..., config=config)`. SSI API Key and Secret are checked only when the SSI source is called. The special `default` vendor chain will never select SSI automatically. Configure `SSI_API_KEY` and `SSI_API_SECRET` locally or in an approved secret manager, never in Git.

This route is deliberately current-date-only. It computes price and common indicators
from the same SSI OHLCV response and uses an SSI-backed deterministic verification
snapshot. Backdated requests are blocked because an old bar returned today does not
prove when it first became available. The adapter is not a financial-statement source
or a validated historical backtesting feed. No trading SDK or order-placement endpoint
is used.

## Official FPT Investor Relations earnings-summary fallback

For current-date research on `FPT`, the fundamentals vendor chain may opt in to the issuer-specific
public IR parser after Vnstock VCI and Yahoo Finance:

~~~python
config["data_vendors"]["fundamental_data"] = "vnstock,yfinance,fpt_ir"
~~~

`fpt_ir` only supports FPT. It finds the latest period-labelled nine-month revenue/PBT release on the
official [FPT Investor Relations page](https://fpt.com/en/ir), parses the publication date and reported
revenue, PBT, parent-company PAT and EPS, and records the article URL and retrieval timestamp.
It fails closed if the official article, date, period or expected metric pattern cannot be verified.
The source is deliberately explicit-only and is not added to the implicit `default` vendor chain.

This release is an earnings-performance summary, **not** a full financial-statement package. It does not
supply a complete balance sheet, cash-flow statement, all valuation ratios or insider-transaction coverage.
A report must not infer those missing metrics from revenue/PBT/PAT/EPS alone. The adapter is also blocked
for historical as-of dates because discovering the latest release now does not reconstruct exactly which
public disclosures were available on a past decision date.
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
python -m pip install -e .
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\ssi_readonly_smoke.ps1 -Symbol FPT -FromDate 2026-10-20 -ToDate 2026-10-23
~~~

The script securely prompts for any missing SSI_API_KEY and SSI_API_SECRET; typed inputs are hidden. It sets them only in the current process
environment for the smoke command, then removes/restores those environment values.
It does not write credentials to Git, a .env file, or a local config file. The
PowerShell execution-policy change is scoped to that terminal process.

### Export SSI OHLCV to the normalized CSV format

After `SSI_API_KEY` and `SSI_API_SECRET` are set privately in your local PowerShell terminal, export bars
without placing orders:

~~~powershell
python -m pip install -e .
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
python -m pip install -e .
python -m tradingagents.dataflows.vietnam_market.smoke --symbol FPT --from-date 2026-10-20 --to-date 2026-10-23
~~~

Never paste credentials into chat, screenshots, issues, logs, or Git. The smoke command's
fetched-at time is for connectivity/parsing validation only, not historical point-in-time
data. It is not evidence of when historical SSI bars first became available. No live SSI
request has been made during development.

## Remaining gaps

- No guessed Yahoo suffix mapping for HOSE, HNX, or UPCoM.
- No live SSI credentials or live-data request.
- Vnstock VCI OHLCV is opt-in and normalizes price units; historical first-availability and adjusted-price vintage are not reconstructed. Vnstock statements are partial, read-only and fetch-time stamped; no share-count/capex mapping or audited completeness guarantee yet.
- No validated Vietnamese calendar/tick-size/price-limit/corporate-action source.
- No SSI historical first-availability timestamps, Vietnamese exchange calendar, or automatic corporate-action adjustment.

Next: verify SSI account entitlements and historical adjustment semantics, validate VCI coverage across banks/securities/insurance/regular-company taxonomies, and add share-count/capex mappings only when the official IDs and units are verified. Main and upstream remain
unchanged; all changes are on the feature branch.
