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


def test_fundamentals_without_a_source_url_are_flagged_when_values_are_present():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Revenue (TTM): VND 40,023 billion. PBT: VND 8,770 billion. "
        "Reporting period: 9M2026."
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "FUNDAMENTALS_CITATIONS_MISSING" for item in audit["findings"])
    assert audit["fundamentals_url_count"] == 0


def test_individual_news_item_without_url_is_flagged_even_when_other_urls_exist():
    state = _sample_state()
    state["news_report"] = (
        "### First item\nPublication date: 2026-10-21\nSource URL: https://example.test/one\n"
        "### Second item\nPublication date: 2026-10-22\nSource URL unavailable from the provider"
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "NEWS_ITEM_URLS_MISSING" for item in audit["findings"])


def test_verified_market_snapshot_requires_provider_and_retrieval_metadata():
    state = _sample_state()
    state["market_report"] = (
        "## Verified market data snapshot for FPT\n"
        "| Close | 56,900 |\n"
        "| rsi | 43.2 |"
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "MARKET_SOURCE_METADATA_MISSING" for item in audit["findings"])
    assert "MARKET DATA PROVENANCE LIMITATION" in build_decision_evidence_guardrails(state)


def test_market_snapshot_with_source_and_retrieval_time_passes_metadata_check():
    state = _sample_state()
    state["market_report"] = (
        "## Verified market data snapshot for FPT\n"
        "- Source: Yahoo Finance chart history (yfinance)\n"
        "- Source URL: https://finance.yahoo.com/quote/FPT/history/\n"
        "- Retrieved at (UTC): 2026-10-27T02:00:00+00:00\n"
        "| Close | 56,900 |"
    )
    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "MARKET_SOURCE_METADATA_MISSING" for item in audit["findings"])


def test_missing_market_report_gets_high_severity_and_prompt_guardrail():
    state = _sample_state()
    state["market_report"] = "DATA_UNAVAILABLE: no configured vendor could serve price data."
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "MARKET_DATA_UNAVAILABLE" for item in audit["findings"])
    assert "MARKET DATA LIMITATION" in build_decision_evidence_guardrails(state)


def test_linked_news_without_any_publication_date_field_is_flagged():
    state = _sample_state()
    state["news_report"] = "A dated-looking story title: https://example.test/news"
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "NEWS_PUBLICATION_DATES_MISSING" for item in audit["findings"])


def test_partial_fpt_ir_summary_is_not_mistaken_for_complete_fundamentals():
    state = _sample_state()
    state["fundamentals_report"] = (
        "# FPT Official Investor-Relations Performance Summary — 9M2026\n"
        "- Reporting period: nine months ended September 30, 2026\n"
        "- Source URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0\n"
        "- Scope: company earnings-performance summary; not a complete financial-statement package.\n"
        "Revenue: VND 40,023 billion; PBT: VND 8,770 billion; parent PAT: VND 7,778 billion; EPS: VND 4,142/share."
    )
    state["investment_debate_state"]["history"] = (
        "Bull Analyst: FPT's operating cash flow is stable, the balance sheet is sound, and the financial position remains strong."
    )
    state["investment_plan"] = "Recommendation: Buy because the financial position is strong."
    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" in codes

    guardrails = build_decision_evidence_guardrails(state)
    assert "PARTIAL FUNDAMENTALS COVERAGE" in guardrails
    assert "Do not infer operating/free cash flow" in guardrails


def test_vnstock_metrics_not_inferred_section_is_a_partial_coverage_warning():
    state = _sample_state()
    state["fundamentals_report"] = (
        "# Current VCI fundamentals for FPT\n"
        "- Source: vnstock-vci\n"
        "## Derived summary (only where inputs are complete)\n"
        "- TTM operating cash flow: unavailable; four contiguous standalone quarter facts are required.\n"
        "## Metrics not inferred\n"
        "This VCI mapping does not currently validate shares outstanding. Therefore it does not claim EPS, P/E, P/B, ROE, market capitalization, or free cash flow."
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "FUNDAMENTALS_PARTIAL_COVERAGE" for item in audit["findings"])
    guardrails = build_decision_evidence_guardrails(state)
    assert "PARTIAL FUNDAMENTALS COVERAGE" in guardrails


def test_prediction_market_probability_requires_specific_market_url_and_timestamp():
    state = _sample_state()
    state["news_report"] = (
        "Polymarket market-implied probability was 96%. "
        "API endpoint: https://gamma-api.polymarket.com/public-search. "
        "Retrieved at (UTC): 2026-10-27T00:00:00+00:00."
    )
    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}
    assert "PREDICTION_MARKET_URL_MISSING" in codes
    assert "PREDICTION_MARKET_TIMESTAMP_MISSING" not in codes


def test_prediction_market_probability_without_timestamp_is_flagged():
    state = _sample_state()
    state["news_report"] = (
        "Polymarket probability: 96%. "
        "Market URL: https://polymarket.com/event/fed-rate-cut-2026."
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "PREDICTION_MARKET_TIMESTAMP_MISSING" for item in audit["findings"])


def test_fred_macro_claim_requires_direct_series_page_url():
    state = _sample_state()
    state["news_report"] = "FRED: Unemployment Rate (UNRATE), latest value 4.4."
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "FRED_SERIES_CITATION_MISSING" for item in audit["findings"])


def test_partial_fundamentals_cannot_support_numeric_roE_or_cashflow_claims():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Official FPT IR 9M2026 earnings summary: "
        "https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Scope: earnings-performance summary; not a complete financial-statement package."
    )
    state["investment_debate_state"]["history"] = (
        "Bull Analyst: FPT ROE of 22% and operating cash flow of VND 5,000 billion."
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "UNSUPPORTED_FINANCIAL_METRIC" for item in audit["findings"])


def test_source_url_counter_strips_terminal_sentence_punctuation():
    state = _sample_state()
    state["news_report"] = "Source: https://example.test/article."
    audit = build_report_quality_audit(state)
    assert audit["news_url_count"] == 1
    assert audit["news_url_count"] == len(["https://example.test/article"])


def test_sentiment_posts_without_provider_permalinks_are_flagged():
    state = _sample_state()
    state["sentiment_report"] = (
        "Source: StockTwits public symbol stream\n"
        "Source URL: https://api.stocktwits.com/api/2/streams/symbol/FPT.json\n"
        "Retrieved at (UTC): 2026-10-27T00:00:00+00:00\n"
        "Bullish: 1 (100%)\n"
        "[2026-10-27 · @trader · Bullish] FPT looks good\n"
        "  Source URL unavailable from the provider"
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "SENTIMENT_POST_URLS_MISSING" for item in audit["findings"])
    assert "SOCIAL POST PROVENANCE LIMITATION" in build_decision_evidence_guardrails(state)


def test_sentiment_with_sourceable_post_permalinks_does_not_trigger_missing_permalink_flag():
    state = _sample_state()
    state["sentiment_report"] = (
        "Source: StockTwits public symbol stream\n"
        "Source URL: https://api.stocktwits.com/api/2/streams/symbol/FPT.json\n"
        "Retrieved at (UTC): 2026-10-27T00:00:00+00:00\n"
        "[2026-10-27 · @trader · Bullish] FPT looks good\n"
        "  Source URL: https://stocktwits.com/trader/message/123"
    )
    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "SENTIMENT_POST_URLS_MISSING" for item in audit["findings"])


def test_news_item_without_publication_date_is_flagged_even_with_a_url():
    state = _sample_state()
    state["news_report"] = (
        "### FPT announcement\nPublication date: unavailable from the provider\n"
        "Source URL: https://example.test/fpt-news"
    )
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "NEWS_PUBLICATION_DATES_MISSING" for item in audit["findings"])


def test_portfolio_price_target_is_checked_when_trader_plan_has_no_entry_levels():
    state = _sample_state()
    state["trader_investment_plan"] = "Action: SELL"
    state["final_trade_decision"] = "Rating: Underweight\n**Price Target**: not provided"
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "TRADE_PLAN_LEVELS_MISSING" for item in audit["findings"])


def test_opposing_research_and_trader_directions_are_flagged():
    state = _sample_state()
    state["investment_plan"] = "Recommendation: Underweight"
    state["trader_investment_plan"] = "Action: BUY"
    state["final_trade_decision"] = "Rating: Underweight"
    audit = build_report_quality_audit(state)
    assert any(item["code"] == "DECISION_DIRECTION_MISMATCH" for item in audit["findings"])


def test_rendered_quality_section_never_claims_external_fact_check():
    rendered = render_report_quality_markdown(build_report_quality_audit(_sample_state()))
    assert "REVIEW REQUIRED" in rendered
    assert "does not independently validate external sources" in rendered
