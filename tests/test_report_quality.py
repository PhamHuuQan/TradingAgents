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


def test_unlinked_news_source_cue_is_flagged_even_if_other_items_have_urls():
    state = _sample_state()
    state["news_report"] = (
        "Nguồn tin chính thức: Business Wire (Ngày công bố: 2026-10-20). "
        "Xem chi tiết tại nguồn.\n"
        + ("Bối cảnh mô tả không cung cấp liên kết riêng cho sự kiện này. " * 8)
        + "\nPolymarket market-implied probability was 96%. "
        "Market URL: https://polymarket.com/event/how-many-fed-rate-cuts-in-2026. "
        "Observed at (UTC): 2026-10-27T04:40:00Z"
    )

    audit = build_report_quality_audit(state)
    assert any(item["code"] == "NEWS_ITEM_URLS_MISSING" for item in audit["findings"])
    assert "NEWS ITEM LINK LIMITATION" in build_decision_evidence_guardrails(state)


def test_unavailable_fundamentals_flag_unsupported_vietnamese_financial_strength_claims():
    state = _sample_state()
    claim = (
        "FPT có nền tảng tài chính 'thép', sở hữu khả năng quản trị dòng tiền, "
        "biên lợi nhuận và ngoại hối cực kỳ xuất sắc, tạo ra dòng tiền đều đặn."
    )
    state["investment_debate_state"]["history"] += "\n" + claim
    state["investment_debate_state"]["bull_history"] = claim

    audit = build_report_quality_audit(state)
    assert any(
        item["code"] == "UNSUPPORTED_FINANCIAL_STRENGTH"
        for item in audit["findings"]
    )


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


def test_fpt_ir_summary_metrics_are_partial_not_fully_unavailable():
    state = _sample_state()
    state["fundamentals_report"] = (
        "FPT 9M2026 summary. Doanh thu: 40.023 tỷ VND, tăng 12,4%. "
        "Lợi nhuận trước thuế (PBT): 8.770 tỷ VND, tăng 17,0%. "
        "Lợi nhuận sau thuế: 7.778 tỷ VND, tăng 13,3%. "
        "EPS: 4.142 VND/cổ phiếu, tăng 12,8%. "
        "Nguồn chính thức FPT IR: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Dữ liệu không khả dụng: Bảng cân đối kế toán, báo cáo lưu chuyển tiền tệ "
        "và báo cáo kết quả kinh doanh chi tiết không thể truy xuất do EntitlementError."
    )

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["source_statuses"]["Fundamentals report"].startswith("PARTIAL")
    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" in codes
    guardrails = build_decision_evidence_guardrails(state)
    assert "PARTIAL FUNDAMENTALS COVERAGE" in guardrails
    assert "Do not infer operating/free cash flow" in guardrails
    assert "FUNDAMENTALS LIMITATION:" not in guardrails


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


def test_vietnamese_market_report_with_numeric_claims_requires_provenance():
    state = _sample_state()
    state["market_report"] = (
        "Phân tích chi tiết xu hướng FPT: giá đóng cửa 56,000 VND; "
        "RSI 27.25; close_50_sma 62,724.68 VND; ATR 1,413.09 VND."
    )

    audit = build_report_quality_audit(state)
    assert any(
        item["code"] == "MARKET_SOURCE_METADATA_MISSING"
        for item in audit["findings"]
    )
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


def test_fpt_report_with_linked_9m_metrics_and_unverified_statements_is_partial_not_unavailable():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Dữ liệu tài chính cốt lõi 9 tháng đầu năm 2026: "
        "Doanh thu 40.023 tỷ VND (+12,4% YoY), LNTT 8.770 tỷ VND (+17,0% YoY), "
        "LNST cổ đông công ty mẹ 7.778 tỷ VND (+13,3% YoY), EPS 4.142 VND/cổ phiếu (+12,8% YoY). "
        "Nguồn: FPT IR News Release "
        "https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Unverified Metrics: Toàn bộ dữ liệu chi tiết về Bảng cân đối kế toán, "
        "Báo cáo lưu chuyển tiền tệ và các hệ số định giá không thể xác thực trong phiên chạy này."
    )

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["source_statuses"]["Fundamentals report"].startswith("PARTIAL")
    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes


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


def test_oversold_rsi_does_not_support_high_reversal_probability_without_backtest():
    state = _sample_state()
    state["investment_debate_state"] = {
        "history": (
            "Bull: RSI is 27.3 and the stock is near the Bollinger lower band. "
            "This creates a very high probability of a technical bounce."
        )
    }
    state["investment_plan"] = "Recommendation: Hold."
    state["trader_investment_plan"] = "Action: HOLD"
    state["final_rating"] = "Hold"
    state["final_trade_decision"] = "Rating: Hold"

    audit = build_report_quality_audit(state)
    assert any(
        item["code"] == "UNSUPPORTED_REVERSAL_PROBABILITY"
        for item in audit["findings"]
    )
    assert "REVERSAL PROBABILITY LIMITATION" in build_decision_evidence_guardrails(state)


def test_partial_earnings_summary_does_not_support_undervaluation_claims():
    state = _sample_state()
    state["fundamentals_report"] = (
        "FPT 9M2026 summary: revenue 40,023 billion VND (+12.4%), "
        "PBT 8,770 billion VND (+17.0%), EPS 4,142 VND. "
        "Official source: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Balance sheet and cash-flow details unavailable; P/E and P/B not available."
    )
    state["investment_debate_state"] = {
        "history": (
            "Bull: FPT is being priced irrationally low and is a gift from the market. "
            "The sourced earnings summary does not include valuation multiples."
        )
    }
    state["investment_plan"] = "Recommendation: Hold."
    state["trader_investment_plan"] = "Action: HOLD"
    state["final_rating"] = "Hold"
    state["final_trade_decision"] = "Rating: Hold"

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes
    assert "UNSUPPORTED_VALUATION_CLAIM" in codes
    assert "VALUATION EVIDENCE LIMITATION" in build_decision_evidence_guardrails(state)


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

def test_source_linked_fpt_summary_is_partial_not_wholly_unavailable_or_unsupported_growth():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Theo thông cáo IR công bố ngày 21/10/2026. "
        "Ngoại trừ 4 chỉ tiêu tổng quan được trích xuất từ thông cáo IR nói trên, "
        "các cấu phần chi tiết hiện không có dữ liệu xác thực. "
        "Doanh thu hợp nhất: Giá trị công bố: 40.023 tỷ VND; tăng trưởng YoY: 12,4%. "
        "Lợi nhuận trước thuế (LNTT / PBT): 8.770 tỷ VND; tăng trưởng YoY: 17,0%. "
        "LNST cổ đông công ty mẹ: 7.778 tỷ VND; EPS: 4.142 VND/cổ phiếu. "
        "Nguồn: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Bảng cân đối kế toán không có dữ liệu xác nhận. "
        "Báo cáo lưu chuyển tiền tệ hiện không khả dụng."
    )
    state["investment_debate_state"] = {
        "history": (
            "FPT duy trì đà tăng trưởng ổn định ở cả doanh thu và lợi nhuận; "
            "số liệu công bố cho thấy tăng trưởng hai chữ số."
        )
    }
    state["investment_plan"] = "Recommendation: Hold. Revenue and PBT growth are source-reported."
    state["trader_investment_plan"] = "Action: HOLD"
    state["risk_debate_state"] = {"history": "Cash flow and balance-sheet details remain unverified."}
    state["final_rating"] = "Hold"
    state["final_trade_decision"] = "Rating: Hold"

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["source_statuses"]["Fundamentals report"] == (
        "PARTIAL — SOURCE-LINKED SUMMARY METRICS; FULL STATEMENTS UNAVAILABLE"
    )
    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes
    # Sourced revenue/PBT growth is not an unsupported claim about financial condition.
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" not in codes


def test_caveated_empty_insider_query_is_not_flagged_due_to_unrelated_unavailable_statements():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Không có bản ghi giao dịch nội bộ nào được trả về từ Yahoo Finance. "
        "Đây chỉ là kết quả trả về rỗng từ một điểm cuối của bên thứ ba, "
        "không đồng nghĩa và không thể kết luận là không có giao dịch nội bộ nào phát sinh tại HOSE. "
        "Bảng cân đối kế toán không khả dụng (EntitlementError). "
        "Source: https://finance.yahoo.com/quote/FPT/insider-transactions/; "
        "retrieved at 2026-10-27T05:30:28Z."
    )
    state["investment_debate_state"] = {"history": "The Yahoo query returned no insider records."}
    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "INSIDER_ABSENCE_UNVERIFIED" for item in audit["findings"])


def test_buy_plan_flags_target_at_entry_and_mixed_price_scale():
    state = _sample_state()
    state["investment_plan"] = "Recommendation: Overweight"
    state["trader_investment_plan"] = (
        "Action: Buy\n**Entry Price**: 54.075\n**Stop Loss**: 52.0"
    )
    state["final_rating"] = "Overweight"
    state["final_trade_decision"] = (
        "Rating: Overweight\n**Price Target**: 54.075"
    )

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "TRADE_TARGET_NOT_ABOVE_ENTRY" in codes
    assert "TRADE_LEVEL_UNIT_MISMATCH" in codes
    assert "TRADE-LEVEL CONSISTENCY" in build_decision_evidence_guardrails(state)


def test_equal_entry_and_stop_loss_price_is_flagged_as_unusable_execution_plan():
    state = _sample_state()
    state["investment_plan"] = "Recommendation: Hold."
    state["trader_investment_plan"] = "Action: HOLD"
    state["risk_debate_state"] = {
        "history": (
            "FINAL TRANSACTION PROPOSAL: ACCUMULATE SMALL POSITION (SCALE-IN) AT 54.200 "
            "WITH STRICT STOP LOSS AT 54.200."
        )
    }
    state["final_rating"] = "Hold"
    state["final_trade_decision"] = "Rating: Hold"

    audit = build_report_quality_audit(state)
    equal_level_findings = [
        item for item in audit["findings"]
        if item["code"] == "TRADE_ENTRY_EQUALS_STOP_LOSS"
    ]
    assert equal_level_findings
    assert equal_level_findings[0]["severity"] == "HIGH"

def test_partial_fpt_summary_does_not_support_cash_machine_claims():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Ngoại trừ 4 chỉ tiêu tổng quan được trích xuất từ thông cáo IR, "
        "các cấu phần chi tiết hiện không có dữ liệu xác thực. "
        "Doanh thu 40.023 tỷ VND (+12,4% YoY), LNTT 8.770 tỷ VND (+17,0% YoY), "
        "LNST cổ đông công ty mẹ 7.778 tỷ VND (+13,3% YoY), EPS 4.142 VND/cổ phiếu (+12,8% YoY). "
        "Nguồn: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Bảng cân đối kế toán không có dữ liệu xác nhận; báo cáo lưu chuyển tiền tệ hiện không khả dụng."
    )
    state["investment_debate_state"] = {
        "history": "Aggressive Analyst: FPT là một cỗ máy in tiền mạnh mẽ."
    }
    state["investment_plan"] = "Recommendation: Hold based on the available evidence."
    state["trader_investment_plan"] = "Action: HOLD"
    state["risk_debate_state"] = {"history": "Cash flow remains unverified."}
    state["final_rating"] = "Hold"
    state["final_trade_decision"] = "Rating: Hold"

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" in codes

def test_source_linked_9m_metrics_with_unavailable_detail_are_partial_not_unavailable():
    state = _sample_state()
    state["fundamentals_report"] = (
        "FPT ghi nhận doanh thu 40.023 tỷ VND, tăng 12,4%; "
        "lợi nhuận trước thuế 8.770 tỷ VND, tăng 17,0%; "
        "lợi nhuận sau thuế cổ đông công ty mẹ 7.778 tỷ VND, tăng 13,3%; "
        "EPS 4.142 VND/cổ phiếu, tăng 12,8%. "
        "Nguồn: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Dữ liệu không khả dụng: bảng cân đối kế toán, báo cáo lưu chuyển tiền tệ "
        "và báo cáo kết quả kinh doanh chi tiết không thể truy xuất do EntitlementError."
    )
    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["source_statuses"]["Fundamentals report"].startswith("PARTIAL")
    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes


def test_news_items_with_inline_publication_dates_are_not_flagged_as_undated():
    state = _sample_state()
    state["news_report"] = (
        "Source records returned by news tools:\n"
        "FPT partnership — Business Wire; publication date: 2026-10-20; "
        "URL: https://example.test/fpt-news\n"
        "IBM AI announcement — PR Newswire; publication date: 2026-10-27; "
        "URL: https://example.test/ibm-news"
    )
    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["news_url_count"] == 2
    assert "NEWS_PUBLICATION_DATES_MISSING" not in codes

def test_opposing_market_analyst_and_trader_directions_are_flagged():
    state = _sample_state()
    state["market_report"] = "Market analysis of FPT.\nRating: Underweight\nFINAL TRANSACTION PROPOSAL: Wait."
    state["investment_plan"] = "Recommendation: Overweight"
    state["trader_investment_plan"] = "Action: Buy\nEntry Price: 54.075\nStop Loss: 52.0"
    state["final_rating"] = "Overweight"
    state["final_trade_decision"] = "Rating: Overweight\nPrice Target: 56.000"

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "MARKET_TRADER_DIRECTION_MISMATCH" in codes




def test_report5_style_source_linked_earnings_summary_is_partial_not_unavailable():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Báo cáo nghiên cứu cơ bản về cổ phiếu FPT cập nhật đến ngày 27/10/2026. "
        "Dữ liệu tài chính cốt lõi (9 tháng đầu năm 2026). "
        "Dựa trên báo cáo tóm tắt kết quả kinh doanh chính thức từ FPT IR "
        "(công bố 21/10/2026; kỳ báo cáo kết thúc 30/09/2026; "
        "URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0): "
        "**Doanh thu (Revenue):**\n- Giá trị: 40.023 tỷ VND\n- Tăng trưởng: 12,4%. "
        "**Lợi nhuận trước thuế (Profit before tax - PBT):**\n- Giá trị: 8.770 tỷ VND\n- Tăng trưởng: 17,0%. "
        "**Lợi nhuận sau thuế thuộc về cổ đông công ty mẹ (PAT):**\n- Giá trị: 7.778 tỷ VND. "
        "**Lợi nhuận trên mỗi cổ phiếu (EPS):**\n- Giá trị: 4.142 VND/cổ phiếu. "
        "Bảng cân đối kế toán không có dữ liệu xác nhận (EntitlementError); "
        "báo cáo lưu chuyển tiền tệ và báo cáo kết quả kinh doanh chi tiết không thể truy xuất."
    )
    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["source_statuses"]["Fundamentals report"].startswith("PARTIAL")
    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes


def test_hold_plan_does_not_require_new_entry_or_upside_target():
    state = _sample_state()
    state["trader_investment_plan"] = (
        "Action: Hold\\nEntry Price: not provided\\n"
        "Stop Loss: not provided\\nPosition Sizing: not provided"
    )
    state["final_rating"] = "Hold"
    state["final_trade_decision"] = "Rating: Hold\\nPrice Target: not provided"

    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "TRADE_PLAN_LEVELS_MISSING" for item in audit["findings"])


def test_audit_checks_newer_debate_state_fields_for_unsupported_valuation_claims():
    state = _sample_state()
    state["fundamentals_report"] = (
        "FPT 9M2026 summary: Revenue VND 40,023 billion; PBT VND 8,770 billion. "
        "Source: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Balance sheet and cash flow are unavailable (EntitlementError)."
    )
    state["risk_debate_state"] = {
        "aggressive_case": "The RSI proves FPT is a bargain and a gift at this price."
    }

    audit = build_report_quality_audit(state)
    assert any(item["code"] == "UNSUPPORTED_VALUATION_CLAIM" for item in audit["findings"])


def test_irrelevant_sports_prediction_market_is_flagged_in_equity_news():
    state = _sample_state()
    state["asset_type"] = "stock"
    state["news_report"] = (
        "Polymarket prediction markets: AFC Asian Cup 2027 Group E winner. "
        "https://polymarket.com/event/afc-asian-cup-2027-group-e-winner"
    )

    audit = build_report_quality_audit(state)
    assert any(
        item["code"] == "PREDICTION_MARKET_RELEVANCE_UNVERIFIED"
        for item in audit["findings"]
    )


def test_fpt_insider_empty_result_with_explicit_nonproof_language_is_qualified():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Yahoo Finance returned no insider transaction records. "
        "This is an empty result from one provider and is not definitive evidence that no insider transactions occurred. "
        "https://finance.yahoo.com/quote/FPT/insider-transactions/"
    )
    state["investment_debate_state"] = {
        "history": "The provider query returned no records; underlying activity remains unknown."
    }

    audit = build_report_quality_audit(state)
    assert not any(item["code"] == "INSIDER_ABSENCE_UNVERIFIED" for item in audit["findings"])



def test_market_wide_social_silence_is_not_inferred_from_unavailable_and_empty_feeds():
    state = _sample_state()
    state["sentiment_report"] = (
        "StockTwits provider unavailable due to HTTPError. "
        "Reddit returned no matching posts in the requested window; "
        "this is not proof of zero discussion everywhere."
    )
    state["investment_debate_state"] = {
        "history": (
            "Hoàn toàn không có dữ liệu hay thảo luận nào trên StockTwits và Reddit. "
            "Sự vắng bóng hoàn toàn của cộng đồng nhà đầu tư cho thấy FPT cạn kiệt thanh khoản quan tâm."
        )
    }

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}
    assert "SOCIAL_SILENCE_EXTRAPOLATION" in codes
    assert "SOCIAL COVERAGE LIMITATION" in build_decision_evidence_guardrails(state)



def test_bear_report_does_not_turn_empty_news_social_feeds_into_market_wide_silence():
    state = _sample_state()
    state["sentiment_report"] = (
        "Yahoo Finance returned no matching FPT articles in the stated window. "
        "StockTwits provider unavailable due to HTTPError. "
        "Reddit returned no matching posts in the requested window; "
        "this is not proof of zero discussion everywhere."
    )
    state["investment_debate_state"] = {
        "history": (
            "Dữ liệu phân tích tâm lý cho thấy sự trống rỗng hoàn toàn trên các kênh tin tức "
            "và diễn đàn (Yahoo Finance, StockTwits, Reddit đều không có thảo luận). "
            "Trong đầu tư, sự thờ ơ của đám đông thường là điềm báo cho việc thiếu động lực tăng giá."
        )
    }

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}
    assert "SOCIAL_SILENCE_EXTRAPOLATION" in codes




def test_fpt_report_catches_empty_feed_inference_and_unverified_operating_margin_claims():
    state = _sample_state()
    state["sentiment_report"] = (
        "Yahoo Finance returned no article records. "
        "StockTwits provider unavailable due to HTTPError. "
        "Reddit returned no matching posts; this is not proof of zero discussion everywhere."
    )
    state["fundamentals_report"] = (
        "Revenue 40.023 tỷ VND (+12,4%); PBT 8.770 tỷ VND (+17,0%). "
        "Source URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "DATA_UNAVAILABLE: balance sheet and cash flow statements unavailable."
    )
    state["investment_debate_state"] = {
        "history": (
            "Mức độ quan tâm của cộng đồng giao dịch bán lẻ trên StockTwits "
            "là không đáng kể. Tăng trưởng PBT là minh chứng cho cải thiện biên lợi nhuận hoạt động. "
            "Dòng tiền thông minh vẫn đang theo dõi sát sao kết quả kinh doanh."
        )
    }

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}
    assert "SOCIAL_SILENCE_EXTRAPOLATION" in codes
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" in codes


def test_report5_regression_flags_known_claims_and_avoids_known_false_positives():
    state = {
        "trade_date": "2026-10-27",
        "asset_type": "stock",
        "market_report": (
            "FPT close 55,400; RSI 25.43; SMA50 62,574.48.\n"
            "### Market Data Provenance\n"
            "- Provider: ssi-fastconnect-v3\n"
            "- Source URL: https://api.ssi.com.vn/api/v3/data/ohlc\n"
            "- Retrieved at: 2026-10-27T16:15:01+07:00\n"
            "- Requested as-of date: 2026-10-27\n"
            "- Latest returned trading row: 2026-10-27"
        ),
        "sentiment_report": (
            "Overall Sentiment: Neutral; Confidence: Low. "
            "FPT partnership: https://finance.yahoo.com/technology/ai/articles/"
            "fpt-niels-bohr-institute-advance-180700712.html. "
            "StockTwits provider unavailable due to HTTPError. "
            "Reddit returned no matching posts in the requested window; "
            "this is not proof of zero discussion everywhere."
        ),
        "news_report": (
            "FPT / Niels Bohr partnership. Publication date: 2026-10-20. "
            "Source URL: https://finance.yahoo.com/technology/ai/articles/"
            "fpt-niels-bohr-institute-advance-180700712.html. "
            "Polymarket prediction markets mainly returned AFC Asian Cup 2027 Group E winner. "
            "Market URL: https://polymarket.com/event/afc-asian-cup-2027-group-e-winner. "
            "Observed at (UTC): 2026-10-27T09:15:00Z."
        ),
        "fundamentals_report": (
            "FPT 9M2026 source-linked earnings summary. "
            "Revenue: VND 40,023 billion (+12.4% YoY). "
            "Profit before tax (PBT): VND 8,770 billion (+17.0% YoY). "
            "Profit after tax attributable to parent (PAT): VND 7,778 billion (+13.3% YoY). "
            "Earnings per share (EPS): VND 4,142 (+12.8% YoY). "
            "Published 2026-10-21; reporting period ended 2026-09-30. "
            "Source URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
            "Balance sheet and cash flow statements are unavailable (EntitlementError). "
            "Yahoo Finance returned no insider transaction records. "
            "This is an empty result from one provider and not definitive evidence that no insider transactions occurred. "
            "https://finance.yahoo.com/quote/FPT/insider-transactions/"
        ),
        "investment_debate_state": {
            "history": (
                "FPT đang bị thị trường định giá thấp; FPT là một cỗ máy in tiền mạnh mẽ. "
                "Hoàn toàn không có dữ liệu hay thảo luận nào trên StockTwits và Reddit. "
                "Sự vắng bóng hoàn toàn của cộng đồng nhà đầu tư cho thấy FPT cạn kiệt thanh khoản quan tâm."
            )
        },
        "investment_plan": "Recommendation: Hold. The growth data is sourced but valuation remains unverified.",
        "trader_investment_plan": (
            "Action: Hold\nEntry Price: not provided\nStop Loss: not provided\n"
            "Position Sizing: not provided"
        ),
        "risk_debate_state": {
            "aggressive_history": (
                "FINAL TRANSACTION PROPOSAL: ACCUMULATE SMALL POSITION (SCALE-IN) "
                "AT 54.200 WITH STRICT STOP LOSS AT 54.200."
            )
        },
        "final_rating": "Hold",
        "final_trade_decision": "Rating: Hold\nPrice Target: not provided",
    }

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert audit["source_statuses"]["Fundamentals report"].startswith("PARTIAL")
    assert "FUNDAMENTALS_PARTIAL_COVERAGE" in codes
    assert "FUNDAMENTALS_UNAVAILABLE" not in codes
    assert "MARKET_SOURCE_METADATA_MISSING" not in codes
    assert "INSIDER_ABSENCE_UNVERIFIED" not in codes
    assert "SENTIMENT_CITATIONS_MISSING" not in codes
    assert "NEWS_PUBLICATION_DATES_MISSING" not in codes
    assert "TRADE_PLAN_LEVELS_MISSING" not in codes
    assert "UNSUPPORTED_FINANCIAL_STRENGTH" in codes
    assert "UNSUPPORTED_VALUATION_CLAIM" in codes
    assert "PREDICTION_MARKET_RELEVANCE_UNVERIFIED" in codes
    assert "SOCIAL_SILENCE_EXTRAPOLATION" in codes
    assert "TRADE_ENTRY_EQUALS_STOP_LOSS" in codes



def test_publication_dates_alone_do_not_count_as_source_linked_financial_metrics():
    state = _sample_state()
    state["fundamentals_report"] = (
        "FPT earnings report overview. Revenue details are unavailable. "
        "Profit before tax details are unavailable. "
        "Published 2026-10-21; reporting period ended 2026-09-30. "
        "Source URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0. "
        "Values were not supplied in the fetched disclosure."
    )

    audit = build_report_quality_audit(state)
    assert audit["source_statuses"]["Fundamentals report"] != (
        "PARTIAL — SOURCE-LINKED SUMMARY METRICS; FULL STATEMENTS UNAVAILABLE"
    )
    assert "FUNDAMENTALS_UNAVAILABLE" in {
        item["code"] for item in audit["findings"]
    }


def test_market_price_and_trade_level_with_mixed_thousands_decimal_scale_are_flagged():
    state = _sample_state()
    state["market_report"] = (
        "FPT market report. Giá hiện tại (55.400); RSI 25,43.\n"
        "Provider: ssi-fastconnect-v3\n"
        "Source URL: https://api.ssi.com.vn/api/v3/data/ohlc\n"
        "Retrieved at: 2026-10-27T17:37:49+07:00"
    )
    state["trader_investment_plan"] = (
        "Action: Hold\nEntry Price: not provided\nStop Loss: 51.5\n"
        "Position Sizing: giữ nguyên tỷ trọng hiện tại"
    )
    state["final_trade_decision"] = "Rating: Hold\nPrice Target: not provided"

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "TRADE_LEVEL_UNIT_MISMATCH" in codes


def test_vietnamese_mua_re_claim_is_flagged_without_verified_valuation_data():
    state = _sample_state()
    state["fundamentals_report"] = (
        "Financial statements unavailable (EntitlementError); "
        "P/E, P/B and ROE are unavailable."
    )
    state["investment_debate_state"] = {
        "history": "FPT is an cơ hội mua rẻ không tưởng near technical support."
    }
    state["investment_plan"] = "Recommendation: Hold"
    state["trader_investment_plan"] = (
        "Action: Hold\nEntry Price: not provided\nStop Loss: not provided"
    )
    state["final_trade_decision"] = "Rating: Hold\nPrice Target: not provided"

    audit = build_report_quality_audit(state)
    codes = {item["code"] for item in audit["findings"]}

    assert "UNSUPPORTED_VALUATION_CLAIM" in codes

