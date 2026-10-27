import re

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.turn import take_turn
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.tools import (
    get_global_news,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
)

# The tools this analyst is offered; its tool node is built from the same tuple.
TOOLS = (
    get_news,
    get_global_news,
    get_macro_indicators,
    get_prediction_markets,
)




def _append_news_tool_evidence(report: str, messages) -> str:
    """Append source dates/URLs present in the exact news-tool results."""
    if not report.strip():
        return report
    heading = "### Source records returned by news tools"
    if heading in report:
        report = report.split(heading, 1)[0].rstrip()

    records = []
    unavailable_blocks = []
    for message in messages or ():
        if not isinstance(message, ToolMessage):
            continue
        tool_name = str(getattr(message, "name", "") or "")
        content = str(getattr(message, "content", "") or "")
        if tool_name not in {"get_news", "get_global_news"} and not re.search(
            r"(?m)^###\s+.+\nPublication date:", content
        ):
            continue
        if any(token in content.casefold() for token in ("data_unavailable", "unavailable:", "no news found", "no global news found")):
            unavailable_blocks.append((tool_name or "news tool", content[:260].replace("\n", " ")))
        for chunk in re.split(r"(?m)(?=^###\s+)", content):
            title_match = re.search(r"(?m)^###\s+(.+?)(?:\s+\(source:\s*(.+?)\))?\s*$", chunk)
            if not title_match:
                continue
            title = title_match.group(1).strip()
            publisher = (title_match.group(2) or "publisher not labelled").strip()
            date_match = re.search(r"(?im)^\s*Publication date:\s*(.+?)\s*$", chunk)
            url_match = re.search(r"(?im)^\s*Link:\s*(https?://\S+)\s*$", chunk)
            publication_date = date_match.group(1).strip() if date_match else "unavailable from provider"
            url = url_match.group(1).strip().rstrip(".,;:!?)]}") if url_match else None
            if url and not url.startswith("https://"):
                url = None
            key = (title, publisher, publication_date, url)
            if key not in records:
                records.append(key)

    if not records and not unavailable_blocks:
        return report

    lines = ["", heading, "", "- The following records were copied from the news tools' returned blocks; their presence does not independently validate the article or claim.", ""]
    if records:
        for title, publisher, pub_date, url in records[:20]:
            suffix = f"; URL: {url}" if url else "; Source URL unavailable from the provider"
            lines.append(f"- {title} — {publisher}; publication date: {pub_date}{suffix}")
        if len(records) > 20:
            lines.append(f"- {len(records) - 20} additional tool-returned news records omitted from this index.")
    else:
        lines.append("- No article-level records with publisher/date/URL were available in the supplied tool results.")
    if unavailable_blocks:
        lines.append("")
        lines.append("**Tool coverage limitations**")
        for tool_name, detail in list(dict.fromkeys(unavailable_blocks))[:5]:
            lines.append(f"- {tool_name}: {detail}")
    return report.rstrip() + "\n" + "\n".join(lines) + "\n"


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        system_message = (
            f"You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(start_date, end_date) for news about the {asset_label} under analysis, get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news, get_macro_indicators(indicator, curr_date, look_back_days) to ground macro commentary in actual data from FRED (e.g. 'cpi', 'core_pce', 'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve'), and get_prediction_markets(topic, limit) for live market-implied probabilities of forward-looking events (e.g. 'Fed rate cut', 'recession 2026', geopolitical or sector events). Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + " SOURCE-PROVENANCE REQUIREMENTS: Preserve direct URLs, publisher/provider names, and publication dates exactly as returned by news tools. For macro time series, state series/title, unit, observation date, value and source. For prediction-market probabilities, include market URL, observed probability, retrieval/observation time, volume/liquidity context if returned, and label the figure as market-implied rather than fact. If a source returns DATA_UNAVAILABLE or an unavailable/error placeholder, say it could not be checked. If a query returns no matching items, distinguish that from a provider failure and do not claim this proves no event/news occurred. Never invent a source URL, event, probability, date, or macro number. Add a Sources table with direct links for the claims that materially affect the thesis."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Report what your tools support; another agent decides the trade."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in TOOLS]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        result, report = take_turn(prompt, llm, TOOLS, state["messages"])
        if report:
            report = _append_news_tool_evidence(report, state.get("messages", []))

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
