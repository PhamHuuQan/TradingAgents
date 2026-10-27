from tradingagents.report_quality import (
    build_decision_evidence_guardrails,
    build_report_quality_audit,
    render_report_quality_markdown,
)


def _sample_state():
    return {
        "trade_date": "2026-10-27",
        "market_report": "Verified market snapshot: FPT close 56000, date 2026-10-26.",
        "sentiment_report": "Low confidence; no social posts were returned.",
        "news_report": "News about FPT: a partnership was reported.",
        "fundamentals_report": (
            "Financial statements could not be retrieved (EntitlementError); "
            "financial ratios unavailable."
        ),
        "investment_debate_state": {
            "history": (
                "Bull Analyst: FPT has a strong financial position and stable operating cash flow."
                "\nBear Analyst: financial statements were not available."
            ),
            "bull_history": "FPT has a strong financial position and stable operating cash flow.",
            "bear_history": "financial statements were not available.",
        },
        "investment_plan": "Recommendation: Underweight. Rationale references strong financial position.",
        "trader_investment_plan": "Action: SELL\n**Entry Price**: not provided\n**Stop Loss**: not provided",
        "risk_debate_state": {"history": "Conservative Analyst: Hold."},
        "final_rating": "Underweight",
        "final_trade_decision": "Rating: Underweight\nExecutive Summary: trim exposure.",
    }


def test_unavailable_fundamentals_trigger_high_severity_and_guardrails():
    state = _sample_state()
    audit = build_report_quality_audit(state)

    assert audit["overall_status"] == "REVIEW REQUIRED"
    assert any(item["code"] == "FUNDAMENTALS_UNAVAILABLE" for item in audit["findings"])
    assert any(item["code"] == "UNSUPPORTED_FINANCIAL_STRENGTH" for item in audit["findings"])

    guardrails = build_decision_evidence_guardrails(state)
    assert "Do not assert strong/weak cash flow" in guardrails
    assert "Do not write 'no insider transactions'" in guardrails


def test_news_without_urls_is_flagged_and_asks_for_provenance():
    state = _sample_state()
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "NEWS_CITATIONS_MISSING" for item in audit["findings"])
    assert any(item["code"] == "SENTIMENT_CITATIONS_MISSING" for item in audit["findings"])
    assert "no direct URLs" in build_decision_evidence_guardrails(state)


def test_no_fabrication_flag_when_financial_strength_has_a_source_url():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Financial strength is supported by the annual report: https://example.test/annual-report. "
        "Statement values: ..."
    )
    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "UNSUPPORTED_FINANCIAL_STRENGTH" for item in audit["findings"])


def test_insider_absence_claim_needs_a_traceable_successful_query():
    state = _sample_state()
    state["investment_debate_state"]["history"] += "\nNo insider transactions were reported."
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "INSIDER_ABSENCE_UNVERIFIED" for item in audit["findings"])


def test_rating_mismatch_is_flagged():
    state = _sample_state()
    state["final_trade_decision"] = "Rating: Buy\nExecutive Summary: add position."
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "FINAL_RATING_MISMATCH" for item in audit["findings"])


def test_actual_fpt_report_failure_patterns_are_detected():
    state = {
        "trade_date": "2026-10-27",
        "news_report": (
            "Business Wire reported a company partnership; prediction market probability was stated as 96%."
        ),
        "sentiment_report": "Overall Sentiment: Mildly Bullish; Confidence: Low.",
        "fundamentals_report": (
            "Financial statements could not be extracted due to technical error (EntitlementError); "
            "detailed financial ratios are temporarily unavailable through the API. "
            "Không có báo cáo giao dịch nội bộ bất thường nào được ghi nhận."
        ),
        "investment_debate_state": {
            "history": (
                "Bull: FPT has a strong financial position and stable operating cash flow. "
                "The company has a nền tảng tài chính thép and dòng tiền đều đặn."
            )
        },
        "investment_plan": "Recommendation: Underweight.",
        "trader_investment_plan": "Entry Price: not provided\nStop Loss: not provided",
        "final_rating": "Underweight",
        "final_trade_decision": "Rating: Underweight",
    }
    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "FUNDAMENTALS_UNAVAILABLE" in codes
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" in codes
    assert "INSIDER_ABSENCE_UNVERIFIED" in codes
    assert "NEWS_CITATIONS_MISSING" in codes
    assert "SENTIMENT_CITATIONS_MISSING" in codes
    assert "TRADE_PLAN_LEVELS_MISSING" in codes
    assert audit["overall_status"] == "REVIEW REQUIRED"


def test_missing_company_fundamentals_are_not_a_blocker_for_crypto():
    state = {
        "asset_type": "crypto",
        "trade_date": "2026-10-27",
        "market_report": "BTC market snapshot.",
        "news_report": "",
        "sentiment_report": "",
        "fundamentals_report": "",
        "investment_plan": "Recommendation: Hold.",
        "trader_investment_plan": "Action: Hold.",
        "final_rating": "Hold",
        "final_trade_decision": "Rating: Hold",
    }
    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "FUNDAMENTALS_UNAVAILABLE" for item in audit["findings"])


def test_rendered_quality_section_never_claims_external_fact_check():
    rendered = render_report_quality_markdown(build_report_quality_audit(_sample_state()))
    assert "REVIEW REQUIRED" in rendered
    assert "does not independently validate external sources" in rendered
