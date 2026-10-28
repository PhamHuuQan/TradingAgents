from langchain_core.messages import ToolMessage

from tradingagents.agents.analysts.fundamentals_analyst import (
    _append_fundamentals_tool_evidence,
)


def test_fundamentals_report_preserves_official_ir_url_and_reporting_period():
    tool_output = """# FPT Official Investor-Relations Performance Summary — 9M2026
- Reporting period: nine months ended September 30, 2026
- Publication date: 2026-10-21
- Source: FPT Corporation official Investor Relations news release
- Retrieved at (UTC): 2026-10-28T05:30:00+00:00
- Source URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0
- Scope: company earnings-performance summary; not a complete financial-statement package.
"""
    messages = [
        ToolMessage(content=tool_output, tool_call_id="fundamentals-call", name="get_fundamentals")
    ]

    actual = _append_fundamentals_tool_evidence(
        "FPT revenue 40.023 tỷ VND; PBT 8.770 tỷ VND.", messages
    )

    assert "### Source records returned by fundamental tools" in actual
    assert "Reporting period: nine months ended September 30, 2026" in actual
    assert "Publication date: 2026-10-21" in actual
    assert "https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0" in actual
    assert "not independently verify the claims" in actual


def test_fundamentals_provenance_does_not_invent_a_source_link_for_failed_vendor():
    messages = [
        ToolMessage(
            content="DATA_UNAVAILABLE: EntitlementError while retrieving balance sheet",
            tool_call_id="balance-sheet-call",
            name="get_balance_sheet",
        )
    ]

    actual = _append_fundamentals_tool_evidence(
        "Balance sheet unavailable (EntitlementError).", messages
    )

    assert "get_balance_sheet" in actual
    assert "EntitlementError" in actual
    assert "https://fpt.com/" not in actual
