# Financial Evidence & Data-Quality Audit

## Purpose and product scope

This work improves the **analysis engine and report evidence**, not the user interface. The app shell/UI is developed separately. The engine must work across supported symbols and providers; FPT is one regression fixture because the repository has an issuer-specific FPT IR adapter, not the product's target universe.

FPT-specific code is allowed only behind an explicit symbol/provider condition. It must not be the default source path for other tickers. Generic audit logic and tests must not assume company names, units, currencies, or statement formats belonging to FPT.

## Required audit domains

| Domain | Data contract that must be visible | Deterministic checks | What the AI must not infer |
|---|---|---|---|
| Price / OHLCV | Canonical symbol, exchange/provider, interval, bar date/time, currency/scale, source URL, retrieval time, adjustment basis and availability/vintage caveat | Reject future rows, impossible OHLC relationships, duplicate/out-of-order bars, mixed symbols/providers, stale/latest-row mismatches and unknown price scales | Exact current prices or support/resistance not present in the verified snapshot |
| Technical indicators | Input price series, indicator name/parameters, calculation date, units and source snapshot | Recompute indicators from the same validated OHLCV series; compare explicit model-reported close/RSI/SMA/EMA/MACD/ATR/Bollinger values to deterministic values; flag missing reconciliation and material mismatches | A crossover date, bounce probability, smart-money direction, or institutional flow from RSI/MACD/OHLCV alone |
| Macro | Series ID/title, unit, frequency, observation date, retrieval timestamp, source URL and data vintage | Reject observations after the as-of date; preserve missing observations; distinguish observation date from retrieval date and current revisions from historical vintages; check derived changes against the same observations | "The Fed will..." as fact from market-implied odds, a forecast, or one macro series alone |
| Financial statements | Issuer/legal entity, consolidated vs standalone, statement type, fiscal period, reporting currency/unit, source, filing/publication date, retrieval time and vintage/revision status | Verify provider and period consistency; do not merge statements from different vendors; distinguish quarterly standalone values from YTD cumulative values; require four contiguous standalone quarters for TTM; test ratio calculations and denominators; keep unavailable values null/explicit | Cash-flow health, leverage, liquidity, margins, P/E/P/B/ROE/EPS, or cheap/undervalued claims from revenue/profit growth alone |
| Valuation / cash quality | Price and timestamp, shares and availability date, equity period/date, TTM inputs, units and currencies | Derive market cap, EPS, P/E, P/B, ROE, free cash flow and cash conversion only from compatible, as-of-available inputs; reject stale/conflicting facts and unit mismatch | A precise valuation multiple or fair value without defensible inputs and method |
| Company / event / news | Issuer identity/ticker, publisher, direct article/filing URL, publication date, retrieval date, event period and whether source is official or secondary | Verify that links are item-level rather than generic landing pages; preserve date and issuer; flag missing/unavailable/empty queries separately; do not treat an appendix URL as a citation for an unlinked narrative claim | A company fact from an unrelated entity, one article as consensus, future opportunity as current cash flow, or absence of filings from an empty provider response |
| Social / insider data | Provider, query window, sample count, post/filing URLs, query success/failure state | Distinguish unavailable, successful-empty, and data returned; keep sample/window limitations visible | Market-wide silence, low interest, no insider activity or capital flows from one empty feed |
| Final decision | Each material claim traceable to evidence, rating consistent across stages, portfolio assumptions explicit | Compare decision/trader/risk/research directions; check trade-level price scale/target order; flag unsupported ratios, probabilities, flows and position-specific instructions | Assume the user already owns the instrument or invent position size, cost basis, or mandatory stop-loss |

## Current implementation notes

- `tradingagents/report_quality.py` performs deterministic text/metadata audits. It is useful for detecting unlinked and unsupported claims, but a source URL by itself does **not** prove that an AI-written number matches the source.
- The verified market snapshot tool computes a deterministic snapshot from OHLCV. The market analyst now preserves the returned OHLCV/indicator values in a `Verified Numeric Evidence` appendix. Exact current-price and indicator claims in the narrative are compared against those preserved values; missing reconciliation is a separate finding from a mismatch.
- The Vietnam-market data contracts use `Decimal`, timezone-aware timestamps, source labels and `available_at`. The current indicator helpers implement SMA, EMA, Wilder RSI, ATR and close-to-close returns deterministically.
- The valuation layer requires compatible price and point-in-time fundamental inputs and avoids TTM aggregation from incomplete/gapped or cumulative-quarter facts.
- FRED outputs preserve series URL, unit/frequency, observation window and vintage information. A keyless public CSV mode is not treated as vintage-safe for historical analysis. The audit also compares a limited set of unambiguous, explicitly named current FRED values (such as Treasury yields, the federal funds rate, unemployment and VIX) against the latest dated value preserved in the appendix. Forecasts, historical claims and prediction-market probabilities are excluded from that current-value comparison.
- Vnstock VCI → KBS fallback must keep the three statements in a summary on one provider. FPT IR remains issuer-specific and is enabled only for `FPT`; it is not a general fundamentals provider.
- News/macro/prediction-market and social appendices are provenance indexes. They help establish what a tool returned; they do not independently validate every narrative assertion on an external website.
- **Known coverage gap:** full financial-statement value reconciliation is not yet normalized across every provider's CSV/XBRL format. Current checks preserve provider/period/unit/source evidence and flag unsupported metrics, but they are not a complete numeric comparison of every income-statement, balance-sheet or cash-flow figure. If a financial number cannot be traced to a normalized metric, it must be marked not reconciled rather than verified.

## Test strategy

All automated correctness tests should be offline and deterministic by default. Use fixtures across more than one market/symbol family (for example FPT/VNM, AAPL/COF, and a supported non-equity symbol where the data contract applies). Live provider smoke tests are opt-in and should log sanitized provider status only.

Release-blocking cases include:
1. A narrative price or indicator differs materially from the deterministic snapshot.
2. A report presents numeric market claims as verified when no compatible numeric snapshot is preserved.
3. A macro statement uses an observation later than its analysis cutoff or mislabels the vintage.
4. Financial statements are mixed across providers, fiscal periods, currencies or cumulative/standalone bases.
5. A financial ratio is presented although required inputs are missing, stale, unit-incompatible or not yet available.
6. An official/company claim has no traceable direct source/date, or an empty/unavailable feed is turned into a factual absence claim.
7. Downstream agents invent unsupported financial strength, valuation, capital flow, direction probability, or portfolio-specific actions.

## Limits and status terminology

The audit must separate:
- **Available and source-linked**: a source block and expected provenance exist.
- **Partially available**: some metrics are source-linked while other required fields/statements are unavailable.
- **Unavailable**: the provider failed, access was denied, or usable data could not be returned.
- **Successful empty result**: the query completed but returned no matching records for its scope/window.
- **Not reconciled**: the report provides an exact number but the engine has no matching verified value to compare it with.
- **Mismatch**: the report's exact number conflicts with the preserved deterministic value beyond the documented display-rounding tolerance.

None of these labels should imply independent external verification unless the implementation actually fetches the underlying public document/filing and validates the specific fact. A passing text audit is evidence of internal consistency and provenance coverage—not a financial recommendation or a blanket fact-check.
