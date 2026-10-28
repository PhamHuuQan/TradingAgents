import re

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.turn import take_turn
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_insider_transactions,
)

# The tools this analyst is offered; its tool node is built from the same tuple.
TOOLS = (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_insider_transactions,
)



_FUNDAMENTALS_TOOL_NAMES = {
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_insider_transactions",
}


def _append_fundamentals_tool_evidence(report: str, messages) -> str:
    """Append source metadata from the exact fundamentals ToolMessages.

    This is a provenance index, not an independent validation of the source.
    It preserves only source/period/retrieval metadata and explicit failure
    markers, rather than duplicating full statements in the final report.
    """
    if not report.strip():
        return report

    heading = "### Source records returned by fundamental tools"
    if heading in report:
        report = report.split(heading, 1)[0].rstrip()

    records = []
    failures = []
    metadata_re = re.compile(
        r"(?i)^\s*(?:[-*]\s*)?(?:source|source url|data url|api endpoint|"
        r"retrieved at(?:\s*\([^)]*\))?|publication date|reporting period|"
        r"financial period|scope|as[- ]of date|observation window|data vintage)\s*[:：]"
    )
    failure_re = re.compile(
        r"(?i)\b(?:DATA_UNAVAILABLE|NO_DATA_AVAILABLE|EntitlementError|"
        r"VendorUnavailableError|VendorNotConfiguredError|permission denied|"
        r"forbidden|unavailable|could not retrieve|no records were returned)\b"
    )

    for message in messages or ():
        if not isinstance(message, ToolMessage):
            continue
        tool_name = str(getattr(message, "name", "") or "")
        if tool_name not in _FUNDAMENTALS_TOOL_NAMES:
            continue

        raw_content = getattr(message, "content", "")
        if isinstance(raw_content, list):
            content = "\n".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in raw_content
            )
        else:
            content = str(raw_content or "")
        content = (
            content.replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
        )
        if not content.strip():
            continue

        title_match = re.search(r"(?m)^\s*#{1,6}\s+(.+?)\s*$", content)
        title = title_match.group(1).strip() if title_match else tool_name
        metadata = []
        for line in content.splitlines():
            if metadata_re.match(line):
                clean_line = line.strip()
                if clean_line not in metadata:
                    metadata.append(clean_line)

        has_direct_url = any(
            re.match(r"(?i)^\s*(?:[-*]\s*)?(?:source url|data url|api endpoint)\s*[:：]\s*https?://", line)
            for line in metadata
        )
        key = (tool_name, title, tuple(metadata))
        if metadata and has_direct_url and key not in records:
            records.append(key)
        elif failure_re.search(content):
            detail = re.sub(r"\s+", " ", content).strip()[:280]
            item = (tool_name, detail)
            if item not in failures:
                failures.append(item)

    if not records and not failures:
        return report

    lines = [
        "",
        heading,
        "",
        "- The entries below are copied from tool responses. They identify returned provenance and failures; they do not independently verify the claims.",
        "",
    ]
    for tool_name, title, metadata in records[:20]:
        lines.append(f"- **{tool_name} — {title}**")
        lines.extend(f"  - {item.lstrip('-* ')}" for item in metadata)
    if len(records) > 20:
        lines.append(f"- {len(records) - 20} additional source records omitted from this index.")
    if failures:
        lines.extend(["", "**Unavailable or empty tool responses**"])
        for tool_name, detail in failures[:10]:
            lines.append(f"- {tool_name}: {detail}")
        if len(failures) > 10:
            lines.append(f"- {len(failures) - 10} additional failure records omitted.")
    return report.rstrip() + "\n" + "\n".join(lines) + "\n"


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements, and `get_insider_transactions` for recent insider buying and selling."
            + " EVIDENCE REQUIREMENTS: For every material financial value, include the metric, value, currency/unit, reporting period, source name, and source URL when returned by the tool. Distinguish reporting period from retrieval date. Treat DATA_UNAVAILABLE, NO_DATA_AVAILABLE, EntitlementError, permission/entitlement errors, and unavailable placeholders as missing evidence; do not fill the gap from memory or general company reputation. Never infer that no insider transactions occurred merely because no records were returned or a source failed. Do not claim strong cash flow, margins, solvency, EPS, ROE, P/E or P/B unless the exact supporting facts were returned and their period/unit are known. End with a Data Availability and Limitations section that names each failed/unavailable source and each metric that could not be verified."
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
            report = _append_fundamentals_tool_evidence(report, state.get("messages", []))

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
