"""Sentiment analyst: one sentiment report from three sources.

The node fetches its sources before calling the model and puts them in the
prompt, so the model reports on data it was given rather than inventing posts:

  1. News headlines: Yahoo Finance
  2. StockTwits messages: the cashtag stream, with Bullish/Bearish tags
  3. Reddit posts: r/wallstreetbets, r/stocks, r/investing, or crypto communities for a crypto pair

Each source is trimmed to the analysis window. With a TypeSafe key, the social
posts are screened by Jev first (see post_screen). These feeds serve recent items
and are not archived, so a historical run's sentiment inputs are not
point-in-time.

The report is a SentimentReport through structured output where the provider
supports it and free text otherwise, so the band, score and confidence header
reads the same across providers.
"""

import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.post_screen import jev_screen
from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.tools import get_news
from tradingagents.dataflows.vendors.reddit import (
    CRYPTO_SUBREDDITS,
    DEFAULT_SUBREDDITS,
    fetch_reddit_posts,
    subreddits_for,
)
from tradingagents.dataflows.vendors.stocktwits import fetch_stocktwits_messages


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch all three sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        # Pass the analysis window so a historical run trims social posts to it
        # instead of leaking today's chatter into a backtest (#1220).
        screen = jev_screen(ticker)
        stocktwits_block = fetch_stocktwits_messages(
            ticker, limit=30, start_date=start_date, end_date=end_date, screen=screen
        )
        subreddits = subreddits_for(ticker)
        reddit_block = fetch_reddit_posts(
            ticker, subreddits, start_date=start_date, end_date=end_date, screen=screen
        )

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
            subreddits=subreddits,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Report what your tools support; another agent decides the trade."
                    # No tool-calling here: the data is pre-fetched into the
                    # prompt, so tool-range wording would only invite a
                    # hallucinated tool call (#1130).
                    " Today's date is {current_date}; treat it as 'now' for all analysis. {instrument_context}"
                    " " + NO_EXTERNAL_TOOLS +
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )
        report_text = _append_sentiment_source_provenance(
            report_text,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node




_ALLOWED_SENTIMENT_SOURCE_HOSTS = {
    "finance.yahoo.com",
    "news.yahoo.com",
    "api.stocktwits.com",
    "stocktwits.com",
    "www.stocktwits.com",
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
}


def _sentiment_source_url(value: str) -> str | None:
    """Keep only HTTPS URLs from providers used by this sentiment node."""
    candidate = (value or "").strip().rstrip(".,;:!?)]}")
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in _ALLOWED_SENTIMENT_SOURCE_HOSTS:
        return None
    return candidate


def _append_sentiment_source_provenance(
    report_text: str,
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Append deterministic citations/coverage for source blocks actually given to the model."""
    if not report_text.strip():
        return report_text

    # Some provider wrappers serialize multiline tool output with literal \\n sequences.
    # Normalize that representation before parsing individual rows, URLs and missing-link markers.
    news_block = (news_block or "").replace("\\n", "\n")
    stocktwits_block = (stocktwits_block or "").replace("\\n", "\n")
    reddit_block = (reddit_block or "").replace("\\n", "\n")

    existing_heading = "### Source URLs and coverage supplied to sentiment analysis"
    lines = [
        "",
        "### Source URLs and coverage supplied to sentiment analysis",
        "",
        f"- Ticker: {ticker}",
        f"- Analysis window: {start_date} through {end_date}",
        "- This index preserves links returned by the source fetchers. It does not independently verify the claims or treat an empty feed as proof of no discussion.",
        "",
    ]
    url_count = 0

    # Replace a model-written source section, if any, with deterministic entries
    # from the exact tool blocks rather than duplicating or trusting an incomplete index.
    if existing_heading in report_text:
        report_text = report_text.split(existing_heading, 1)[0].rstrip()

    # Keep article title, publisher, publication date and URL together so readers
    # can assess each news item without relying on model-generated citations.
    article_chunks = re.split(r"(?m)(?=^###\s+)", news_block or "")
    article_rows = []
    for chunk in article_chunks:
        header = re.search(r"(?m)^###\s+(.+?)(?:\s+\(source:\s*(.+?)\))?\s*$", chunk)
        if not header:
            continue
        title = header.group(1).strip()
        publisher = (header.group(2) or "publisher not labelled").strip()
        date_match = re.search(r"(?im)^\s*Publication date:\s*(.+?)\s*$", chunk)
        link_match = re.search(r"(?im)^\s*Link:\s*(https?://\S+)\s*$", chunk)
        publication_date = date_match.group(1).strip() if date_match else "unavailable from provider"
        url = _sentiment_source_url(link_match.group(1)) if link_match else None
        if url:
            article_rows.append((title, publisher, publication_date, url))
        elif title:
            article_rows.append((title, publisher, publication_date, None))

    lines.append("**Yahoo Finance news items supplied to the sentiment analyst**")
    if not article_rows:
        lines.append("- No article records could be extracted from the fetched news block; this is not proof that no news exists.")
    else:
        for title, publisher, pub_date, url in article_rows[:10]:
            if url:
                lines.append(f"- {title} — {publisher}; publication date: {pub_date}; URL: {url}")
                url_count += 1
            else:
                lines.append(f"- {title} — {publisher}; publication date: {pub_date}; direct article URL was not supplied.")
        if len(article_rows) > 10:
            lines.append(f"- {len(article_rows) - 10} additional fetched article records omitted from this index.")
    lines.append("")

    # Separate the StockTwits provider endpoint from individual message permalinks.
    st_lines = (stocktwits_block or "").splitlines()
    st_endpoint = None
    for row in st_lines:
        match = re.match(r"(?i)^\s*Source URL:\s*(https?://\S+)\s*$", row)
        if match:
            candidate = _sentiment_source_url(match.group(1))
            if candidate and urlparse(candidate).hostname == "api.stocktwits.com":
                st_endpoint = candidate
                break
    st_posts = []
    for row in st_lines:
        match = re.match(r"(?i)^\s*Source URL:\s*(https?://\S+)\s*$", row)
        if not match:
            continue
        candidate = _sentiment_source_url(match.group(1))
        if candidate and urlparse(candidate).hostname in {"stocktwits.com", "www.stocktwits.com"}:
            st_posts.append(candidate)
    lines.append("**StockTwits**")
    if st_endpoint:
        lines.append(f"- Provider endpoint: {st_endpoint}")
        url_count += 1
    st_folded = (stocktwits_block or "").casefold()
    st_no_messages = "no stocktwits messages" in st_folded
    st_screened_all = "none of the" in st_folded and "messages is about" in st_folded
    # Provider rows may be indented; recognize them before deciding that no message was supplied.
    st_has_message_rows = bool(
        re.search(r"(?m)^\s*(?:[-*]\s*)?\[\s*\d{4}[-/]\d{2}[-/]\d{2}\b", stocktwits_block or "")
    )
    # Count explicit missing-link markers separately from found permalinks so
    # partially linked feeds do not hide other fetched messages without URLs.
    st_missing_permalink_count = len(re.findall(
        r"(?i)(?:source|message|post)\s+(?:url|permalink)\s+unavailable from the provider",
        stocktwits_block or "",
    ))
    st_has_missing_permalink = st_missing_permalink_count > 0
    if st_posts:
        for url in dict.fromkeys(st_posts[:10]):
            lines.append(f"- Message permalink: {url}")
            url_count += 1
        if len(set(st_posts)) > 10:
            lines.append(f"- {len(set(st_posts)) - 10} additional message permalinks omitted from this index.")

    if st_has_missing_permalink or (st_has_message_rows and not st_posts):
        lines.append(
            "- Message URL unavailable from the provider for one or more fetched StockTwits messages; "
            "the stream endpoint is not an individual message permalink."
        )
    elif st_no_messages:
        lines.append("- The fetched block reports no matching messages in the stated window; this is feed output, not proof of zero discussion everywhere.")
    elif st_screened_all:
        lines.append("- The screening step retained no on-topic StockTwits messages; no individual post is asserted as evidence.")
    elif any(token in st_folded for token in ("unavailable", "error", "failed")):
        lines.append("- The provider block marks the feed unavailable; no conclusion about underlying market discussion is justified.")
    elif not st_posts:
        lines.append("- No individual message permalink was supplied in the fetched block; do not present a specific post as verified.")
    lines.append("")

    rd_urls = []
    for match in re.finditer(r"(?im)^\s*Source URL:\s*(https?://\S+)\s*$", reddit_block or ""):
        candidate = _sentiment_source_url(match.group(1))
        if candidate and (urlparse(candidate).hostname or "").casefold() in {"reddit.com", "www.reddit.com", "old.reddit.com"}:
            rd_urls.append(candidate)
    lines.append("**Reddit**")
    reddit_folded = (reddit_block or "").casefold()
    rd_has_post_rows = bool(re.search(r"(?m)^\s*\[\d{4}-\d{2}-\d{2}\]", reddit_block or ""))
    rd_has_missing_permalink = "source url unavailable from the provider" in reddit_folded
    if rd_urls:
        for url in dict.fromkeys(rd_urls[:10]):
            lines.append(f"- Post permalink: {url}")
            url_count += 1
        if len(set(rd_urls)) > 10:
            lines.append(f"- {len(set(rd_urls)) - 10} additional post permalinks omitted from this index.")
    elif "no reddit posts found" in reddit_folded or "<no posts found mentioning" in reddit_folded:
        lines.append("- The fetched search block reports no matching posts in the stated window; this is not proof of zero discussion everywhere.")
    elif rd_has_post_rows or rd_has_missing_permalink:
        lines.append("- Post permalink unavailable from the provider for one or more fetched Reddit items.")
    elif "unavailable" in reddit_folded or "fetch failed" in reddit_folded:
        lines.append("- The Reddit source block marks the fetch unavailable; it must not be described as confirmed silence.")
    else:
        lines.append("- No individual Reddit post permalink was supplied in the fetched block.")
    lines.append("")
    lines.append(f"- Direct source URLs preserved in this index: {url_count}")

    return report_text.rstrip() + "\n" + "\n".join(lines) + "\n"


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    if subreddits == DEFAULT_SUBREDDITS:
        character = "r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term"
    elif len(subreddits) > len(CRYPTO_SUBREDDITS):
        character = f"r/{subreddits[0]} leans toward the coin's holders; r/CryptoCurrency and r/CryptoMarkets are broader"
    else:
        character = "r/CryptoCurrency and r/CryptoMarkets are broad crypto communities"
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — {", ".join(f"r/{sub}" for sub in subreddits)} (past 7 days)
Community discussion, without vote or comment counts. Subreddit character matters ({character}).

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone. A block headed "Screened by Jev" has had off-topic posts removed; its stance count is a classifier's read of every on-topic post fetched, labelled or not, of which the posts listed are a sample. Read it alongside the user tags.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Read Reddit posts for substance.** The feed carries no vote or comment counts, so judge a post by its body excerpt, not its title alone, and do not infer engagement.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

9. **Preserve provenance.** Include direct URLs for the Yahoo Finance articles and source/post URLs when present in the source blocks. State the date window and actual sample count for each source where available. An empty source, provider error, and verified absence are different states. Never invent a link, post, headline, event, or sample count; if a source block lacks provenance, label it unverified and reduce confidence.

10. **EMPTY-FEED INFERENCE LIMIT.** A zero-result search, missing headline list, provider error, or symbol stream with no messages only describes that provider and query window. Do not infer low retail interest, silence across the whole market, lack of institutional information, absence of catalysts, low liquidity, smart-money accumulation/distribution, or a price direction from empty feeds alone. State exactly which source returned no items or failed, and require separate evidence for any broader claim.

11. **NO AGGREGATED-SILENCE NARRATIVE.** Do not write that "all sources are silent", "complete absence of data", "market-wide silence", or "the lack of discussion shows..." merely because one or more feeds are empty. Make one separate, bounded statement per provider (queried, successful-empty, failed/unavailable, or records returned); don't turn a collection of incomplete feeds into a global sentiment conclusion. When sources are all empty or unavailable, say the sentiment is unobservable from these inputs rather than claiming Neutral based on evidence of market-wide silence.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""
