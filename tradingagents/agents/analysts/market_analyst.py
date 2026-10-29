import re

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.turn import take_turn
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.tools import get_indicators, get_stock_data, get_verified_market_snapshot

# The tools this analyst is offered; its tool node is built from the same tuple.
TOOLS = (
    get_stock_data,
    get_indicators,
    get_verified_market_snapshot,
)


_MARKET_PROVENANCE_HEADING = re.compile(r"(?im)^\s*#{1,6}\s*Market Data Provenance\s*$")


def _strip_unverified_market_provenance(report: str) -> str:
    """Remove a model-written provenance section unless a tool snapshot validates it."""
    match = _MARKET_PROVENANCE_HEADING.search(report or "")
    if not match:
        return report
    # The prompt asks for this section at the end. Never keep its claims after a
    # missing, failed, or malformed snapshot, because they may be model-generated.
    return report[:match.start()].rstrip()


def _append_verified_market_provenance(report: str, messages) -> str:
    """Append provenance only from a complete, successful verified snapshot tool result."""
    if not report.strip():
        return report

    # First remove any provenance written by the model. It is replaced only after
    # a tool result has supplied the minimum evidence required below.
    clean_report = _strip_unverified_market_provenance(report)

    matching_messages = [
        message for message in (messages or ())
        if isinstance(message, ToolMessage)
        and getattr(message, "name", None) == "get_verified_market_snapshot"
    ]
    if not matching_messages:
        return clean_report

    # The latest invocation is authoritative. Do not reuse an older success if
    # a later snapshot call failed.
    message = matching_messages[-1]
    raw_content = getattr(message, "content", "")
    if isinstance(raw_content, list):
        content = "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in raw_content
        )
    else:
        content = str(raw_content)
    content = (
        content.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
    )
    content = content.replace("\ufeff", "").replace("\u200b", "").strip()
    content_folded = content.casefold().lstrip()

    unavailable_pattern = re.compile(
        r"\b(?:DATA_UNAVAILABLE|NO_DATA_AVAILABLE|VendorUnavailableError|"
        r"VendorNotConfiguredError|NoMarketDataError|EntitlementError)\b"
        r"|no market snapshot|snapshot unavailable|could not retrieve.*snapshot"
        r"|no usable market data",
        re.IGNORECASE,
    )
    if unavailable_pattern.search(content) or content_folded.startswith((
        "error:", "failed:", "<error",
    )):
        return clean_report

    verified_heading = bool(re.search(
        r"(?im)^\s*#{1,6}\s*Verified(?: SSI)? market data snapshot\b", content
    ))
    # Different verified providers use equivalent labels for the same date fields.
    required_fields = (
        r"(?im)^\s*[-*]?\s*Requested (?:as-of|analysis) date\s*:\s*\S+",
        r"(?im)^\s*[-*]?\s*Latest (?:returned trading row|trading row used)\s*:\s*\S+",
        r"(?im)^\s*[-*]?\s*Source\s*:\s*\S+",
    )
    has_required_metadata = all(re.search(pattern, content) for pattern in required_fields)
    if not (verified_heading and has_required_metadata):
        return clean_report

    fields = (
        ("Provider", r"(?im)^\s*(?:[-*]\s*)?Source\s*[:：]\s*(.+)$"),
        ("Source URL", r"(?im)^\s*(?:[-*]\s*)?(?:Source URL|Data URL|URL nguồn|Link nguồn)\s*[:：]\s*(.+)$"),
        ("Retrieved at", r"(?im)^\s*(?:[-*]\s*)?Retrieved at(?: \(UTC\))?\s*[:：]\s*(.+)$"),
        ("Requested as-of date", r"(?im)^\s*(?:[-*]\s*)?Requested (?:as-of|analysis) date\s*[:：]\s*(.+)$"),
        ("Latest returned trading row", r"(?im)^\s*(?:[-*]\s*)?Latest (?:returned trading row|trading row used)\s*[:：]\s*(.+)$"),
    )
    lines = ["", "### Market Data Provenance", ""]
    for label, pattern in fields:
        match = re.search(pattern, content)
        if match:
            lines.append(f"- {label}: {match.group(1).strip()}")
        elif label in {"Provider", "Source URL", "Retrieved at"}:
            lines.append(f"- {label}: not supplied by provider")
    base = clean_report.rstrip()
    provenance = "\n".join(lines).strip("\n") + "\n"

    # Copy numeric evidence from the validated tool response verbatim, rather
    # than leaving the audit with only a source URL and timestamp. This appendix
    # is parsed by report_quality.py to compare exact numbers in the narrative.
    numeric_rows = []
    section = None
    for raw_line in content.splitlines():
        heading = raw_line.strip().casefold()
        if heading.startswith("### latest verified ohlcv row"):
            section = "ohlcv"
            continue
        if heading.startswith("### verified technical indicators"):
            section = "indicators"
            continue
        if heading.startswith("### "):
            section = None
        if section is None:
            continue
        match = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", raw_line.strip())
        if not match:
            continue
        label, value = match.group(1).strip(), match.group(2).strip()
        if not label or set(label) <= {"-", ":", " "} or not value:
            continue
        if value.casefold() == "n/a" or value.casefold().startswith("n/a "):
            continue
        if not re.fullmatch(r"-?\d[\d,.]*", value):
            continue
        if section == "ohlcv":
            if label.casefold() in {"open", "high", "low", "close", "volume"}:
                numeric_rows.append(f"- Verified OHLCV {label.title()}: {value}")
        else:
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", label):
                numeric_rows.append(f"- Verified indicator {label.lower()}: {value}")

    if numeric_rows:
        numeric_evidence = (
            "\n### Verified Numeric Evidence\n\n"
            + "\n".join(numeric_rows)
            + "\n"
        )
        return f"{base}\n\n{provenance}{numeric_evidence}" if base else f"{provenance}{numeric_evidence}"
    return f"{base}\n\n{provenance}" if base else provenance


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_stock_data first to retrieve the CSV that is needed to generate indicators. Then use get_indicators with the specific indicator names.

Before writing the final report, call get_verified_market_snapshot for this ticker and the current date, and treat it as the source of truth for any exact OHLCV, price-level, or indicator-value claim. If another tool's output conflicts with the verified snapshot, flag the discrepancy rather than inventing a reconciled number. Do not claim historical validation, support/resistance bounces, or exact percentage moves unless they are directly supported by tool output with concrete dates and prices.

MANDATORY PROVENANCE: Include a clearly labelled "Market Data Provenance" section at the end. Copy the provider/source, exact "Source URL", "Retrieved at" timestamp, requested as-of date, and latest returned trading-row date from get_verified_market_snapshot. Do not silently drop those metadata lines. If the snapshot lacks a field, explicitly write "not supplied by provider"; never invent one or substitute a general home page for a data endpoint.

Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
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
            report = _append_verified_market_provenance(report, state.get("messages", []))

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
