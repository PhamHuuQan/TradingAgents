# Vietnam market data source review

Review date: 2026-10-24

This is a design comparison, not a statement that any source has been authenticated or
that its data may be redistributed. Before implementation, verify current service terms,
coverage, historical depth, adjustment conventions, and account entitlements.

## Candidate A — SSI FastConnect Data

Official documentation:
- Overview: https://developers.ssi.com.vn/docs/getting-started/overview
- Data API list: https://guide.ssi.com.vn/ssi-products/tieng-viet/fastconnect-data/danh-sach-cac-api
- Service overview and registration: https://developers.ssi.com.vn/docs/faq/service-overview

Documented strengths:
- Explicit support for securities on HOSE, HNX, and UPCoM.
- Market data endpoints include securities lists, daily and intraday OHLC, daily index data,
  and daily stock prices.
- Authentication uses a consumer ID and consumer secret to obtain an access token.

Questions before adoption:
- Confirm historical depth and pagination limits for each endpoint.
- Confirm adjustment handling for splits, dividends, and rights issues.
- Confirm which market-data entitlements and request limits apply to the user's account.
- Use a read-only market-data key; do not request trading scopes for the research application.

## Candidate B — TCBS OpenAPI

Official portal: https://developers.tcbs.com.vn/

Documented strengths:
- Official REST and WebSocket APIs for Vietnamese equities on HOSE, HNX, and UPCoM, plus
  Vietnamese derivatives.
- Authentication uses an API key and OTP to obtain a JWT bearer token.
- The portal recommends one WebSocket connection per token and fewer than 10 REST requests
  per second unless a higher throughput arrangement is agreed.

Questions before adoption:
- Confirm the exact historical OHLC and fundamental-data endpoints available to this account.
- Confirm data retention, rate limits, terms of use, and whether delayed or real-time feeds
  are available.
- Keep the initial integration read-only; never enable order endpoints in the research app.

## Candidate C — vnstock as an adapter library

Documentation:
- Market API: https://www.vnstocks.com/docs/vnstock/thi-truong-market
- Data entitlement overview: https://www.vnstocks.com/docs/vnstock/vnstock-data-v3/gioi-thieu-vnstock-data
- Public project: https://github.com/vnstock-official/vnstock

Documented strengths:
- Convenient Python interface for historical OHLCV and multiple asset classes.
- Current documentation distinguishes community and expanded tiers. The community tier
  documents domestic data sources such as KBS and VCI; other routes can require a different
  entitlement.

Risks and questions:
- vnstock is a client library that retrieves data from upstream sources, not itself a guarantee
  of a licensed market-data feed or service-level agreement.
- Upstream APIs, access rules, rate limits, and output formats can change.
- Pin and test the library version, inspect the applicable license and upstream terms, and
  retain source metadata in every normalized record.

## Recommendation

1. Prototype with one source only after reviewing its account terms and available access.
2. Keep a provider interface independent of the TradingAgents graph, so the source can be
   replaced without rewriting analysts.
3. Store raw response snapshots for test fixtures where permitted; normalize all records into
   the MarketBar contract and preserve source, timezone, and actual availability timestamp.
4. Add a second source only after parity tests quantify differences in prices, volume, adjusted
   values, timestamps, missing sessions, and corporate-action handling.
5. Keep market-data access read-only. Trading API integration is out of scope for this phase.

No API key, OTP, consumer secret, or other credential should be committed to Git.

## Decision — SSI selected for the first adapter (2026-10-24)

SSI FastConnect V3 is selected as the first Vietnamese-equity market-data integration.
The first implementation slice is read-only daily OHLCV through the official SSI Python
SDK's MarketDataService interface. The low-level adapter does not request trading scopes,
send orders, or authenticate. An optional context manager handles SDK market-data
authentication using environment variables, without requesting OTP or creating a Trading
client. Existing TradingAgents routing remains unchanged.

Relevant current official references:
- V3 overview and market-data capabilities: https://developers.ssi.com.vn/docs/getting-started/overview
- Python SDK market-data methods, including historical OHLC and pagination:
  https://developers.ssi.com.vn/docs/sdk/python/service-classes
- API key and token security: https://developers.ssi.com.vn/docs/getting-started/api-keys
- Current V3 release notes: https://developers.ssi.com.vn/docs/api-reference/release-notes

The official portal states that an SSI brokerage account is required for FastConnect API
access and that API keys can be scoped separately. Before a live smoke test, confirm the
user's account has Market Data scope and verify current terms/rate limits in the portal.
No credentials have been requested or added to this repository.

Important limitation: the historical OHLC response does not establish the exact first
availability time of each past bar. The adapter requires caller-supplied, verified
availability timestamps and rejects missing or implausible timestamps. This is a safety
guard, not evidence that SSI provides historical point-in-time timestamps. Do not use
guessed availability times in a backtest.
