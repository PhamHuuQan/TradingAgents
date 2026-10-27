from tradingagents.agents.analysts.sentiment_analyst import _append_sentiment_source_provenance


def test_sentiment_report_preserves_fetched_article_and_post_links():
    report = "Overall Sentiment: Neutral (Score: 5.0/10)\nConfidence: Low\nSparse social data."
    news_block = """## FPT News
### FPT partnership update (source: Yahoo Finance)
Publication date: 2026-10-20
A quantum partnership was announced.
Link: https://finance.yahoo.com/technology/ai/articles/fpt-niels-bohr-institute-advance-180700712.html
"""
    stocktwits_block = """Source: StockTwits public symbol stream
Source URL: https://api.stocktwits.com/api/2/streams/symbol/FPT.json
Retrieved at (UTC): 2026-10-27T05:30:00+00:00
Bullish: 1 (100%) · Bearish: 0 (0%) · Unlabeled: 0 · Total: 1 most-recent messages

[2026-10-26 · @user1 · Bullish] FPT long
  Source URL: https://stocktwits.com/user1/message/123
"""
    reddit_block = """r/stocks — 1 recent posts mentioning FPT:
  [2026-10-25] Thoughts on FPT
    Source URL: https://www.reddit.com/r/stocks/comments/abc/thoughts_on_fpt/
"""

    actual = _append_sentiment_source_provenance(
        report,
        ticker="FPT",
        start_date="2026-10-20",
        end_date="2026-10-27",
        news_block=news_block,
        stocktwits_block=stocktwits_block,
        reddit_block=reddit_block,
    )

    assert "### Source URLs and coverage supplied to sentiment analysis" in actual
    assert "publication date: 2026-10-20" in actual
    assert "https://finance.yahoo.com/technology/ai/articles/fpt-niels-bohr-institute-advance-180700712.html" in actual
    assert "Provider endpoint: https://api.stocktwits.com/api/2/streams/symbol/FPT.json" in actual
    assert "https://stocktwits.com/user1/message/123" in actual
    assert "https://www.reddit.com/r/stocks/comments/abc/thoughts_on_fpt/" in actual
    assert "Direct source URLs preserved in this index: 4" in actual
    assert "\\n### Source URLs and coverage" not in actual


def test_sentiment_provenance_does_not_invent_links_for_unavailable_sources():
    report = "Overall Sentiment: Neutral (Score: 5.0/10)\nConfidence: Low"
    actual = _append_sentiment_source_provenance(
        report,
        ticker="FPT",
        start_date="2026-10-20",
        end_date="2026-10-27",
        news_block="<Yahoo Finance news unavailable: timeout>",
        stocktwits_block="<stocktwits unavailable: timeout>",
        reddit_block="<Reddit unavailable: fetch failed; this is not an absence of discussion>",
    )

    assert "not proof that no news exists" in actual
    assert "feed unavailable" in actual
    assert "not be described as confirmed silence" in actual
    assert "https://finance.yahoo.com/" not in actual
    assert "https://reddit.com/" not in actual
    assert "Direct source URLs preserved in this index: 0" in actual


def test_existing_sentiment_provenance_section_is_not_duplicated():
    report = "Report\n\n### Source URLs and coverage supplied to sentiment analysis\nExisting index."
    actual = _append_sentiment_source_provenance(
        report,
        ticker="FPT",
        start_date="2026-10-20",
        end_date="2026-10-27",
        news_block="",
        stocktwits_block="",
        reddit_block="",
    )
    assert actual == report
