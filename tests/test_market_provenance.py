from langchain_core.messages import ToolMessage

from tradingagents.agents.analysts.market_analyst import _append_verified_market_provenance


def test_verified_snapshot_provenance_is_appended_verbatim():
    snapshot = """## Verified SSI market data snapshot for FPT

- Requested as-of date: 2026-10-27
- Latest returned trading row: 2026-10-26
- Source: ssi-fastconnect-v3
- Source URL: https://api.ssi.com.vn/api/v3/data/ohlc
- Retrieved at: 2026-10-27T12:30:00+07:00
"""
    report = "## FPT Market Analysis\nClose: 56000"
    messages = [
        ToolMessage(
            content=snapshot,
            tool_call_id="snapshot-call",
            name="get_verified_market_snapshot",
        )
    ]

    actual = _append_verified_market_provenance(report, messages)

    assert "### Market Data Provenance" in actual
    assert "- Provider: ssi-fastconnect-v3" in actual
    assert "- Source URL: https://api.ssi.com.vn/api/v3/data/ohlc" in actual
    assert "- Retrieved at: 2026-10-27T12:30:00+07:00" in actual
    assert "- Requested as-of date: 2026-10-27" in actual
    assert "- Latest returned trading row: 2026-10-26" in actual
    assert "\\n### Market Data Provenance" not in actual


def test_verified_snapshot_provenance_does_not_invent_missing_metadata():
    snapshot = """## Verified market data snapshot for FPT

- Requested as-of date: 2026-10-27
- Latest returned trading row: 2026-10-26
- Source: vendor-x
"""
    messages = [
        ToolMessage(content=snapshot, tool_call_id="snapshot-call", name="get_verified_market_snapshot")
    ]

    actual = _append_verified_market_provenance("Market report", messages)

    assert "- Provider: vendor-x" in actual
    assert "- Source URL: not supplied by provider" in actual
    assert "- Retrieved at: not supplied by provider" in actual


def test_no_snapshot_means_no_fabricated_provenance_section():
    messages = [
        ToolMessage(content="DATA_UNAVAILABLE: no market snapshot", tool_call_id="failed", name="get_verified_market_snapshot")
    ]
    report = "Report without source evidence"

    assert _append_verified_market_provenance(report, messages) == report

def test_later_failed_snapshot_does_not_reuse_older_snapshot_metadata():
    verified = """## Verified SSI market data snapshot for FPT

- Requested as-of date: 2026-10-27
- Latest returned trading row: 2026-10-27
- Source: ssi-fastconnect-v3
- Source URL: https://api.ssi.com.vn/api/v3/data/ohlc
- Retrieved at: 2026-10-27T12:30:00+07:00
"""
    messages = [
        ToolMessage(content=verified, tool_call_id="snapshot-ok", name="get_verified_market_snapshot"),
        ToolMessage(
            content="DATA_UNAVAILABLE: no market snapshot",
            tool_call_id="snapshot-failed",
            name="get_verified_market_snapshot",
        ),
    ]
    report = "Report without current source evidence"

    assert _append_verified_market_provenance(report, messages) == report

def test_model_written_provenance_is_removed_when_no_snapshot_was_called():
    report = (
        "## FPT Market Analysis\nClose: 56000\n\n### Market Data Provenance\n"
        "- Provider: ssi-fastconnect-v3\n- Source URL: https://example.invalid/fake\n"
        "- Retrieved at: 2026-10-27T12:30:00+07:00"
    )

    actual = _append_verified_market_provenance(report, [])

    assert "## FPT Market Analysis" in actual
    assert "Close: 56000" in actual
    assert "Market Data Provenance" not in actual
    assert "example.invalid" not in actual


def test_model_written_provenance_is_removed_after_failed_snapshot():
    report = (
        "## FPT Market Analysis\nClose: 56000\n\n### Market Data Provenance\n"
        "- Provider: ssi-fastconnect-v3\n- Source URL: https://example.invalid/fake"
    )
    messages = [
        ToolMessage(
            content="DATA_UNAVAILABLE: no market snapshot",
            tool_call_id="failed",
            name="get_verified_market_snapshot",
        )
    ]

    actual = _append_verified_market_provenance(report, messages)

    assert "Close: 56000" in actual
    assert "Market Data Provenance" not in actual
    assert "example.invalid" not in actual


def test_incomplete_snapshot_cannot_validate_model_written_provenance():
    report = "Market report\n\n### Market Data Provenance\n- Provider: invented-provider"
    messages = [
        ToolMessage(
            content="## Verified market data snapshot for FPT\n- Source: ssi-fastconnect-v3",
            tool_call_id="incomplete",
            name="get_verified_market_snapshot",
        )
    ]

    actual = _append_verified_market_provenance(report, messages)

    assert actual == "Market report"
    assert "Market Data Provenance" not in actual

