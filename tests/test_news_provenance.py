from langchain_core.messages import ToolMessage

from tradingagents.agents.analysts.news_analyst import _append_news_tool_evidence


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

