from langchain_core.messages import ToolMessage

from tradingagents.agents.analysts.news_analyst import (
    _append_macro_prediction_tool_evidence,
    _append_news_tool_evidence,
    _prediction_market_relevance_guardrail,
)


def test_news_report_preserves_tool_returned_publication_dates_and_urls():
    tool_result = """## FPT News, from 2026-10-20 to 2026-10-27:

### FPT and Niels Bohr advance quantum talent (source: Yahoo Finance)
Publication date: 2026-10-20
A news summary from the provider.
Link: https://finance.yahoo.com/technology/ai/articles/fpt-niels-bohr-institute-advance-180700712.html
"""
    messages = [
        ToolMessage(content=tool_result, tool_call_id="news-call", name="get_news")
    ]

    actual = _append_news_tool_evidence("News analysis text", messages)

    assert "### Source records returned by news tools" in actual
    assert "FPT and Niels Bohr advance quantum talent" in actual
    assert "publication date: 2026-10-20" in actual
    assert "https://finance.yahoo.com/technology/ai/articles/fpt-niels-bohr-institute-advance-180700712.html" in actual
    assert "\\n### Source records returned by news tools" not in actual


def test_news_evidence_index_preserves_missing_date_as_missing():
    tool_result = """### Macro story (source: Yahoo Finance)
Publication date: unavailable from the provider
A news summary.
Link: https://finance.yahoo.com/news/example.html
"""
    messages = [
        ToolMessage(content=tool_result, tool_call_id="news-call", name="get_global_news")
    ]

    actual = _append_news_tool_evidence("News analysis text", messages)

    assert "publication date: unavailable from the provider" in actual
    assert "https://finance.yahoo.com/news/example.html" in actual


def test_news_helper_does_not_invent_articles_without_tool_evidence():
    messages = [
        ToolMessage(content="DATA_UNAVAILABLE: news provider failed", tool_call_id="failed", name="get_news")
    ]
    actual = _append_news_tool_evidence("News analysis text", messages)

    assert "### Source records returned by news tools" in actual
    assert "get_news: DATA_UNAVAILABLE: news provider failed" in actual
    assert "https://finance.yahoo.com/" not in actual

def test_empty_news_query_is_distinguished_from_provider_failure():
    messages = [
        ToolMessage(
            content="No news found for FPT between 2026-10-20 and 2026-10-27",
            tool_call_id="empty-query",
            name="get_news",
        )
    ]

    actual = _append_news_tool_evidence("News analysis text", messages)

    assert "Queries with no matching news returned for the requested window" in actual
    assert "Provider or retrieval failures" not in actual
    assert "No article-level records" in actual



def test_macro_and_prediction_market_tool_evidence_preserves_urls_values_and_times():
    fred = """## FRED: Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity (DGS10)
- Source: Federal Reserve Bank of St. Louis, FRED
- Source URL: https://fred.stlouisfed.org/series/DGS10
- Data URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10
- Retrieved at (UTC): 2026-10-28T05:31:00+00:00
- Units: Percent
- Observation window: 2026-10-20 to 2026-10-28
**Latest:** 5.00 (2026-10-26)
**Change from 2026-10-20 to 2026-10-26:** -0.12 (-2.34%), from 5.12
"""
    polymarket = """## Polymarket prediction markets: "Fed rate cuts in 2026"
- Source: Polymarket public Gamma API
- API endpoint: https://gamma-api.polymarket.com/public-search
- Retrieved at (UTC): 2026-10-28T05:31:02+00:00
- **How many Fed rate cuts in 2026?** — 0 (0 bps) 96% ($54,886,710 volume, resolves 2026-12-31)
  - Observed at (UTC): 2026-10-28T05:31:02+00:00
  - Market URL: https://polymarket.com/event/how-many-fed-rate-cuts-in-2026/will-no-fed-rate-cuts-happen-in-2026
"""
    messages = [
        ToolMessage(content=fred, tool_call_id="fred-call", name="get_macro_indicators"),
        ToolMessage(content=polymarket, tool_call_id="market-call", name="get_prediction_markets"),
    ]

    actual = _append_macro_prediction_tool_evidence("News analysis text", messages)

    assert "### Macro and prediction-market records returned by tools" in actual
    assert "https://fred.stlouisfed.org/series/DGS10" in actual
    assert "5.00 (2026-10-26)" in actual
    assert "https://polymarket.com/event/how-many-fed-rate-cuts-in-2026/will-no-fed-rate-cuts-happen-in-2026" in actual
    assert "96%" in actual and "54,886,710 volume" in actual
    assert "2026-10-28T05:31:02+00:00" in actual


def test_auxiliary_evidence_does_not_invent_links_for_unavailable_tools():
    messages = [
        ToolMessage(
            content="DATA_UNAVAILABLE: FRED API key not configured",
            tool_call_id="fred-fail",
            name="get_macro_indicators",
        )
    ]

    actual = _append_macro_prediction_tool_evidence("News analysis text", messages)

    assert "get_macro_indicators" in actual or "FRED API key not configured" in actual
    assert "https://fred.stlouisfed.org/series/" not in actual

def test_news_prompt_excludes_prediction_markets_unrelated_to_investment_thesis():
    rule = _prediction_market_relevance_guardrail()

    assert "PREDICTION-MARKET RELEVANCE" in rule
    assert "Exclude unrelated sports, entertainment" in rule
    assert "clear transmission channel" in rule


