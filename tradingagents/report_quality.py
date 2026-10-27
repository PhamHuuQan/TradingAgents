"""Deterministic evidence-quality checks for generated TradingAgents reports.

These checks do not decide whether to buy or sell. They surface missing data,
unlinked factual claims, and common inconsistencies so readers do not mistake
an LLM-generated narrative for independently verified evidence.
"""
from __future__ import annotations

import re
from typing import Any

_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(
    r"\b(?:DATA_UNAVAILABLE|NO_DATA_AVAILABLE|EntitlementError|VendorUnavailableError)\b"
    r"|data\s+(?:is\s+)?unavailable|not available|unavailable via (?:the )?api"
    r"|temporarily unavailable|currently unavailable|tạm thời (?:chưa )?khả dụng|không thể trích xuất|không lấy được dữ liệu"
    r"|dữ liệu .*?không khả dụng|thiếu dữ liệu (?:tài chính|cơ bản)",
    re.IGNORECASE,
)
_NO_DATA_RE = re.compile(
    r"\bNO_DATA_AVAILABLE\b|no usable (?:market|fundamental) data|"
    r"no data (?:was|were) returned|không có dữ liệu sử dụng được",
    re.IGNORECASE,
)
_PARTIAL_FUNDAMENTALS_RE = re.compile(
    r"not a complete financial[- ]statement package|not a complete set of financial statements"
    r"|does not provide (?:a )?complete balance sheet|summary only|limited earnings summary"
    r"|partial fundamentals|incomplete financial statements|chỉ là tóm tắt kết quả kinh doanh"
    r"|không thay thế (?:đầy đủ )?(?:bảng cân đối|báo cáo lưu chuyển tiền tệ)"
    r"|does not provide .*?cash-flow statement|metrics not inferred"
    r"|this VCI mapping does not currently validate|does not claim EPS, P/E, P/B, ROE"
    r"|TTM (?:net income|operating cash flow): unavailable; four contiguous standalone quarter facts are required"
    r"|unavailable from the supported VCI mappings"
    r"|ngoại trừ\s+(?:4|bốn)\s+chỉ tiêu tổng quan"
    r"|các cấu phần chi tiết.{0,220}không có dữ liệu xác thực"
    r"|bảng cân đối kế toán[\s\S]{0,220}(?:không khả dụng|không có dữ liệu xác nhận|không thể truy xuất|DATA_UNAVAILABLE)"
    r"|báo cáo lưu chuyển tiền tệ[\s\S]{0,220}(?:không khả dụng|không có dữ liệu|không thể xác thực|không thể truy xuất)"
    r"|(?:toàn bộ )?dữ liệu chi tiết.{0,240}(?:không thể xác thực|không khả dụng|không có dữ liệu)",
    re.IGNORECASE,
)
_FINANCIAL_STRENGTH_RE = re.compile(
    r"\bstrong financial position\b|\bstrong financial foundation\b"
    r"|\b(?:stable|steady|robust|healthy) (?:operating )?cash flow\b"
    r"|nền tảng tài chính\s+(?:vững|thép|mạnh|xuất sắc|rất tốt)"
    r"|tài chính\s+[\"“]?(?:thép|vững mạnh|vững chắc)"
    r"|dòng tiền(?: hoạt động)?\s+(?:đều đặn|ổn định|mạnh|vững chắc|dồi dào|rất tốt)"
    r"|biên lợi nhuận\s+(?:xuất sắc|cao|mạnh|ổn định)"
    r"|financial (?:position|foundation|health).{0,45}\b(?:strong|robust|excellent|solid)\b"
    r"|\bstrong (?:cash flow|balance sheet|financials)\b"
    r"|\brobust cash flow\b"
    r"|\b(?:operating |free )?cash flow.{0,30}\b(?:strong|stable|steady|robust|healthy|positive|improving|increased|grew)\b"
    r"|\b(?:balance sheet|financial position|solvency|liquidity).{0,30}\b(?:strong|stable|healthy|robust|solid|sound|improved)\b"
    # These are condition/quality claims; plain revenue/PBT/EPS growth is not enough to trigger them.
    r"|(?:nền tảng|sức khỏe|tình hình)\s+tài chính.{0,35}(?:[\"'“”‘’]?\s*)(?:thép|vững(?: mạnh| chắc)?|mạnh|tốt|xuất sắc|ổn định)"
    r"|tài chính\s+[\"'“”‘’]?(?:thép|vững mạnh|vững chắc|mạnh|xuất sắc)"
    r"|(?:dòng tiền|biên lợi nhuận|khả năng sinh lời|năng lực tài chính).{0,45}(?:đều đặn|ổn định|mạnh|vững chắc|dồi dào|xuất sắc|cao|tốt|bền vững)"
    r"|(?:quản trị|quản lý|kiểm soát|tạo ra|duy trì|sở hữu).{0,55}(?:dòng tiền|biên lợi nhuận|khả năng sinh lời).{0,45}(?:đều đặn|ổn định|mạnh|vững chắc|dồi dào|xuất sắc|cao|tốt)"
    r"|cỗ máy in tiền.{0,30}(?:mạnh|bền vững|ổn định|đều đặn)",
    re.IGNORECASE,
)
_INSIDER_ABSENCE_RE = re.compile(
    r"không có (?:báo cáo )?(?:giao dịch|hoạt động giao dịch) nội bộ"
    r"|chưa có (?:báo cáo )?(?:giao dịch|hoạt động giao dịch) nội bộ"
    r"|no (?:unusual )?insider (?:transactions|trading|activity)"
    r"|no insider trades",
    re.IGNORECASE,
)
_UNSUPPORTED_FINANCIAL_METRIC_RE = re.compile(
    r"\b(?:free cash flow|operating cash flow|cash flow|P/E|P/B|ROE|return on equity|"
    r"current ratio|debt[- ]to[- ]equity|solvency|liquidity|operating margin|profit margin|net margin)\b"
    r".{0,40}\b(?:is|was|of|at|reached|stood at|equals?|around|approximately|improved to|rose to)?\s*"
    r"(?:VND|USD|EUR|GBP)?\s*\d[\d,.]*(?:\s*%|\s*x|\s*(?:billion|million|trillion))?"
    r"|\b\d[\d,.]*\s*%\s*(?:ROE|return on equity|P/E|P/B|operating margin|profit margin|net margin)\b",
    re.IGNORECASE,
)
_INSIDER_QUALIFIER_RE = re.compile(
    r"not proof (?:that )?(?:no|there (?:was|were) no) insider"
    r"|not proof of (?:no|absence of) insider"
    r"|not exhaustive|no records were returned|empty result from one provider"
    r"|not evidence that (?:there are|there were|any) no insider"
    r"|không phải bằng chứng rằng không có|không chứng minh không có"
    r"|không đồng nghĩa(?: với việc)? không có"
    r"|không thể kết luận(?: rằng| là)? không có"
    r"|không phải là bằng chứng khẳng định",
    re.IGNORECASE,
)
_MISSING_TRADE_LEVEL_RE = re.compile(
    r"(?:\*\*)?(?:entry price|stop[\s-]?loss|price target)(?:\*\*)?\s*[:：]\s*(?:not provided|not specified|n/?a|chưa có|không có)",
    re.IGNORECASE,
)
_TRADE_PRICE_TOKEN = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_EQUAL_ENTRY_STOP_LOSS_RE = re.compile(
    rf"(?:accumulate(?:\s+small position)?|entry(?:\s+price|\s+position)?|"
    rf"mở\s+(?:một\s+)?vị thế(?:\s+thăm dò)?|tích lũy(?:\s+từng phần)?)"
    rf"[\s\S]{{0,300}}?(?:at|tại|around)\s*(?P<entry>{_TRADE_PRICE_TOKEN})"
    rf"[\s\S]{{0,300}}?(?:strict\s+)?(?:stop[\s-]?loss|cắt lỗ|mức cắt lỗ)"
    rf"[\s\S]{{0,80}}?(?:at|tại|=|:)\s*(?P<stop>{_TRADE_PRICE_TOKEN})",
    re.IGNORECASE,
)

_TRADE_LEVEL_FIELD_RE = re.compile(
    rf"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?P<label>entry price|stop[\s-]?loss|price target|target price)(?:\*\*)?\s*[:：]\s*(?P<value>{_TRADE_PRICE_TOKEN})"
)


def _parse_trade_price_token(value: str) -> float | None:
    """Parse common English/Vietnamese price formatting for internal consistency checks."""
    token = re.sub(r"[^0-9.,]", "", value or "")
    if not token:
        return None
    if "." in token and "," in token:
        # The final separator is the decimal mark; the other is a thousands separator.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "." in token or "," in token:
        separator = "." if "." in token else ","
        chunks = token.split(separator)
        if len(chunks) > 1 and all(len(chunk) == 3 for chunk in chunks[1:]):
            token = "".join(chunks)
        else:
            token = token.replace(separator, ".")
    try:
        return float(token)
    except ValueError:
        return None


_RATING_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?(?:recommendation|rating)(?:\*\*)?\s*[:：]\s*(buy|overweight|hold|underweight|sell)\b"
)
_TRADER_ACTION_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?action(?:\*\*)?\s*[:：]\s*(buy|hold|sell)\b"
)
_MISSING_NEWS_DATE_RE = re.compile(
    r"publication date:\s*unavailable|no publication date|undated (?:source|article)",
    re.IGNORECASE,
)
_FRED_SOURCE_CLAIM_RE = re.compile(r"\bFRED\s*:|FRED series|Federal Reserve Economic Data", re.IGNORECASE)
_POLYMARKET_PROBABILITY_RE = re.compile(
    r"(?:Polymarket|prediction[- ]market|market[- ]implied)[\s\S]{0,120}\b\d+(?:\.\d+)?\s*%"
    r"|\b\d+(?:\.\d+)?\s*%[\s\S]{0,100}(?:Polymarket|prediction[- ]market|market[- ]implied)",
    re.IGNORECASE,
)
_POLYMARKET_URL_RE = re.compile(r"https?://(?:www\.)?polymarket\.com/", re.IGNORECASE)

_MARKET_URL_MISSING_RE = re.compile(
    r"Market URL:\s*(?:unavailable|not provided|missing)|market link unavailable",
    re.IGNORECASE,
)
_SOCIAL_POST_URL_MISSING_RE = re.compile(
    r"Source URL unavailable from the provider|post permalink unavailable|message URL unavailable",
    re.IGNORECASE,
)
_NEWS_ITEM_URL_MISSING_RE = re.compile(
    r"Source URL unavailable from the provider|article URL unavailable|news link unavailable",
    re.IGNORECASE,
)
_NEWS_UNLINKED_SOURCE_CUE_RE = re.compile(
    r"xem chi tiết tại nguồn|xem tại nguồn|xem nguồn|link bài viết|"
    r"see (?:the )?source|read more at the source|source link unavailable",
    re.IGNORECASE,
)


_MARKET_SOURCE_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:source|provider|nguồn(?: dữ liệu)?)\s*[:：]"
)
_MARKET_SOURCE_URL_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:source url|data url|url nguồn|link nguồn)\s*[:：]\s*https?://"
)
_MARKET_RETRIEVAL_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:retrieved at(?: \(utc\))?|retrieval time|"
    r"thời điểm truy xuất|thời gian truy xuất|thời điểm lấy dữ liệu)\s*[:：]"
)
_MARKET_NUMERIC_CLAIM_RE = re.compile(
    r"\b(?:close|open|high|low|price|volume|rsi|atr|macd|ema|sma|boll(?:inger)?(?:\s+bands?)?)\b"
    r".{0,120}\d[\d,.]*"
    r"|\b(?:giá (?:đóng cửa|hiện tại|gần nhất)|chỉ số rsi|rsi|atr|macd|ema|sma|"
    r"dải bollinger|biên độ dao động|khối lượng giao dịch)\b.{0,100}\d[\d,.]*"
    r"|\d[\d,.]*\s*(?:VND|VNĐ|đồng)\b",
    re.IGNORECASE,
)


def _market_provenance_missing(text: str) -> bool:
    """Require provider, direct source URL, and retrieval time when numeric market claims appear."""
    if not text.strip():
        return False
    if not _MARKET_NUMERIC_CLAIM_RE.search(text) and "verified market data snapshot" not in text.casefold():
        return False
    return not (
        _MARKET_SOURCE_LINE_RE.search(text)
        and _MARKET_SOURCE_URL_LINE_RE.search(text)
        and _MARKET_RETRIEVAL_LINE_RE.search(text)
    )


def _has_unlinked_news_source_cue(text: str) -> bool:
    """Catch prose that points to a source without a nearby usable direct URL."""
    for match in _NEWS_UNLINKED_SOURCE_CUE_RE.finditer(text or ""):
        context = text[max(0, match.start() - 160):min(len(text), match.end() + 160)]
        if not _urls(context):
            return True
    return False


def _text(value: Any) -> str:
    """Normalize optional report values without assuming their type."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return "\n".join(_text(item) for item in value)
    return str(value)


def _status(text: str) -> str:
    if not text.strip():
        return "MISSING"
    if _NO_DATA_RE.search(text):
        return "NO USABLE DATA RETURNED"
    if _UNAVAILABLE_RE.search(text):
        return "LIMITED / SOURCE UNAVAILABLE"
    return "PRESENT — NOT INDEPENDENTLY VERIFIED"


def _urls(text: str) -> list[str]:
    # Narrative punctuation is not part of the URL.
    values = (url.rstrip(".,;:!?") for url in _URL_RE.findall(text or ""))
    return list(dict.fromkeys(url for url in values if url))


def _has_source_linked_summary_metrics(text: str) -> bool:
    """True when a report supplies a source URL and at least two numeric earnings-summary metrics."""
    metric_patterns = (
        r"(?:\brevenue\b|doanh thu).{0,180}\d[\d,.]*",
        r"(?:\bPBT\b|\bLNTT\b|lợi nhuận trước thuế).{0,180}\d[\d,.]*",
        r"(?:\bPAT\b|\bLNST\b|lợi nhuận sau thuế).{0,180}\d[\d,.]*",
        r"(?:\bEPS\b|lãi cơ bản trên (?:mỗi )?cổ phiếu).{0,180}\d[\d,.]*",
    )
    metric_count = sum(
        bool(re.search(pattern, text or "", re.IGNORECASE | re.DOTALL))
        for pattern in metric_patterns
    )
    return metric_count >= 2 and bool(_urls(text))


def _downstream_text(state: dict[str, Any]) -> str:
    pieces = [
        _text(state.get("investment_plan")),
        _text(state.get("trader_investment_plan")),
        _text(state.get("final_trade_decision")),
    ]
    for key in ("investment_debate_state", "risk_debate_state"):
        value = state.get(key) or {}
        if isinstance(value, dict):
            pieces.extend(_text(value.get(name)) for name in (
                "history", "bull_history", "bear_history",
                "aggressive_history", "conservative_history", "neutral_history",
                "current_response", "current_aggressive_response",
                "current_conservative_response", "current_neutral_response",
            ))
        else:
            pieces.append(_text(value))
    return "\n".join(piece for piece in pieces if piece)


def _requires_fundamentals(state: dict[str, Any]) -> bool:
    """Stock/equity reports need fundamental coverage; crypto narratives need not."""
    asset_type = str(state.get("asset_type") or "stock").strip().casefold()
    return asset_type not in {"crypto", "cryptocurrency", "forex", "fx", "commodity"}


def build_decision_evidence_guardrails(state: dict[str, Any]) -> str:
    """Return concise prompt instructions grounded in the reports already collected."""
    fundamentals = _text(state.get("fundamentals_report"))
    news = _text(state.get("news_report"))
    sentiment = _text(state.get("sentiment_report"))
    guardrails = [
        "EVIDENCE QUALITY RULES:",
        "- Only treat values, events, and source coverage explicitly present in the supplied reports/tool results as evidence.",
        "- Distinguish 'source unavailable', 'query returned no matching data', and 'verified absence'; these are not interchangeable.",
        "- Label interpretation as inference. Never invent financial values, citations, publication dates, market probabilities, or insider-activity conclusions.",
        "- Prefer a neutral/low-confidence conclusion when a key claim cannot be substantiated; explain which evidence would change the view.",
        "- TRADE-LEVEL CONSISTENCY: keep entry, stop-loss and target in the same currency and price scale. For a buy, the target must be strictly above entry and stop-loss below entry; never label an entry/support price as a profit target.",
    ]
    market = _text(state.get("market_report"))
    if (
        not market.strip()
        or _UNAVAILABLE_RE.search(market)
        or _NO_DATA_RE.search(market)
    ):
        guardrails.append(
            "- MARKET DATA LIMITATION: no usable market/technical report is present. Do not state exact prices, indicators, support/resistance levels, "
            "or execution levels as verified without a separate named, dated source. Say which market data is unavailable."
        )
    elif _market_provenance_missing(market):
        guardrails.append(
            "- MARKET DATA PROVENANCE LIMITATION: numeric price/indicator claims are present but the market report does not preserve a labeled provider, direct source URL, and retrieval timestamp. "
            "Do not describe these figures as source-traceable until all three are included."
        )
    if _requires_fundamentals(state) and (
        not fundamentals.strip()
        or _UNAVAILABLE_RE.search(fundamentals)
        or _NO_DATA_RE.search(fundamentals)
    ):
        guardrails.append(
            "- FUNDAMENTALS LIMITATION: financial statements/ratios are unavailable or not usable in the supplied fundamentals report. "
            "Do not assert strong/weak cash flow, margins, solvency, valuation ratios, EPS/ROE, or a strong financial position "
            "unless that specific claim is supported by another named, dated source in the supplied evidence. State the limitation."
        )
        guardrails.append(
            "- Do not write 'no insider transactions' or 'no unusual insider activity' unless the supplied tool result explicitly confirms "
            "that the relevant source was queried successfully for a stated period."
        )
    if _requires_fundamentals(state) and _PARTIAL_FUNDAMENTALS_RE.search(fundamentals):
        guardrails.append(
            "- PARTIAL FUNDAMENTALS COVERAGE: the supplied source is an earnings-performance summary, not a complete financial-statement package. "
            "Use only the exact metrics, reporting period, unit and growth rates it provides. Do not infer operating/free cash flow, cash balances, debt, "
            "liquidity, solvency, equity, margins, P/E, P/B, ROE, debt ratios, or insider activity unless another supplied source explicitly provides those values. "
            "State that those metrics remain unverified."
        )
    if news.strip() and _has_unlinked_news_source_cue(news):
        guardrails.append(
            "- NEWS ITEM LINK LIMITATION: at least one item points readers to a source but has no direct URL nearby. Keep that item unverified until its own source link is supplied."
        )
    if not _urls(news) and news.strip():
        guardrails.append(
            "- NEWS PROVENANCE LIMITATION: the supplied news report contains no direct URLs. Do not present a named event, macro value, "
            "or prediction-market probability as verified unless another supplied source gives its URL and observation/publication date."
        )
    if sentiment.strip() and _SOCIAL_POST_URL_MISSING_RE.search(sentiment):
        guardrails.append(
            "- SOCIAL POST PROVENANCE LIMITATION: at least one Reddit/StockTwits item has no provider-supplied permalink. Do not describe it as individually verified; keep the missing link visible and rely only on sourceable items for specific claims."
        )
    if not _urls(sentiment) and sentiment.strip():
        guardrails.append(
            "- SENTIMENT PROVENANCE LIMITATION: the supplied sentiment report contains no direct URLs; treat source-specific social/news "
            "claims as unverified and describe the sample size/window or missing coverage when available."
        )
    if fundamentals.strip() and not _urls(fundamentals) and not (
        _UNAVAILABLE_RE.search(fundamentals) or _NO_DATA_RE.search(fundamentals)
    ):
        guardrails.append(
            "- FUNDAMENTALS PROVENANCE LIMITATION: the supplied fundamentals report has no direct source URL. "
            "Name the provider and reporting period, but do not describe its financial claims as independently verified."
        )
    return "\n".join(guardrails)


def build_report_quality_audit(final_state: dict[str, Any]) -> dict[str, Any]:
    """Summarize availability and detectable evidence gaps in completed graph state."""
    report_keys = {
        "Market report": "market_report",
        "Sentiment report": "sentiment_report",
        "News report": "news_report",
        "Fundamentals report": "fundamentals_report",
    }
    source_statuses = {
        label: _status(_text(final_state.get(key)))
        for label, key in report_keys.items()
    }
    market = _text(final_state.get("market_report"))
    news = _text(final_state.get("news_report"))
    sentiment = _text(final_state.get("sentiment_report"))
    fundamentals = _text(final_state.get("fundamentals_report"))
    fundamentals_has_summary_metrics = _has_source_linked_summary_metrics(fundamentals)
    fundamentals_has_unavailable_sections = bool(
        _UNAVAILABLE_RE.search(fundamentals) or _NO_DATA_RE.search(fundamentals)
    )
    # A report can contain source-linked revenue/PBT/PAT/EPS and still lack
    # balance-sheet/cash-flow/valuation detail. Treat that as partial coverage,
    # not as if every fundamental metric were unavailable.
    fundamentals_are_partial = bool(_PARTIAL_FUNDAMENTALS_RE.search(fundamentals)) or (
        fundamentals_has_summary_metrics and fundamentals_has_unavailable_sections
    )
    if (
        _requires_fundamentals(final_state)
        and fundamentals_are_partial
        and fundamentals_has_summary_metrics
    ):
        source_statuses["Fundamentals report"] = (
            "PARTIAL — SOURCE-LINKED SUMMARY METRICS; FULL STATEMENTS UNAVAILABLE"
        )
    downstream = _downstream_text(final_state)
    findings: list[dict[str, str]] = []

    if source_statuses["Market report"] in {
        "MISSING", "LIMITED / SOURCE UNAVAILABLE", "NO USABLE DATA RETURNED"
    }:
        findings.append({
            "severity": "HIGH",
            "code": "MARKET_DATA_UNAVAILABLE",
            "finding": (
                "The market/technical report is missing or unavailable. Exact price, volume, indicator, "
                "support/resistance and trade-level claims are unverified without a separate source."
            ),
        })

    if _market_provenance_missing(market):
        findings.append({
            "severity": "MEDIUM",
            "code": "MARKET_SOURCE_METADATA_MISSING",
            "finding": (
                "Numeric price/indicator claims are present but the market report is missing a labeled provider, direct source URL, and/or retrieval timestamp. "
                "Preserve all three fields so exact OHLCV and indicator claims can be traced to a source."
            ),
        })

    if _requires_fundamentals(final_state) and (
        source_statuses["Fundamentals report"] in {"MISSING", "NO USABLE DATA RETURNED"}
        or (
            source_statuses["Fundamentals report"] == "LIMITED / SOURCE UNAVAILABLE"
            and not (fundamentals_are_partial and fundamentals_has_summary_metrics)
        )
    ):
        findings.append({
            "severity": "HIGH",
            "code": "FUNDAMENTALS_UNAVAILABLE",
            "finding": (
                "Financial statements or ratios are missing/unavailable. Treat valuation, earnings, "
                "cash flow, margins, balance-sheet strength and ROE as unverified unless separately sourced."
            ),
        })

    if _requires_fundamentals(final_state) and fundamentals_are_partial:
        findings.append({
            "severity": "MEDIUM",
            "code": "FUNDAMENTALS_PARTIAL_COVERAGE",
            "finding": (
                "The supplied fundamentals source is only an earnings-performance summary, not a complete set of financial statements. "
                "Revenue/PBT/PAT/EPS may be reported, but cash flow, balance-sheet strength, margins, valuation ratios and insider activity "
                "remain unverified unless separately sourced."
            ),
        })

    fundamentals_limitations = (
        not fundamentals.strip()
        or bool(_UNAVAILABLE_RE.search(fundamentals))
        or bool(_NO_DATA_RE.search(fundamentals))
        or fundamentals_are_partial
    )
    if (
        _requires_fundamentals(final_state)
        and fundamentals_limitations
        and _FINANCIAL_STRENGTH_RE.search(downstream)
    ):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_FINANCIAL_STRENGTH",
            "finding": (
                "Downstream debate/decision text asserts balance-sheet strength, liquidity, margins, or cash-flow quality "
                "while the supplied fundamentals evidence is unavailable or partial. Keep such claims only when a named source "
                "supports that specific metric; sourced revenue/PBT/PAT/EPS growth alone does not prove balance-sheet or cash-flow strength."
            ),
        })

    if _requires_fundamentals(final_state) and fundamentals_limitations and _UNSUPPORTED_FINANCIAL_METRIC_RE.search(downstream):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_FINANCIAL_METRIC",
            "finding": (
                "Downstream report assigns a numeric value to a financial metric that is not substantiated by the supplied "
                "fundamentals data. Remove the value or cite a separate source with metric definition, unit and reporting period."
            ),
        })

    downstream_insider_claim = (
        _INSIDER_ABSENCE_RE.search(downstream)
        and not _INSIDER_QUALIFIER_RE.search(downstream)
    )
    fundamentals_insider_claim = (
        _INSIDER_ABSENCE_RE.search(fundamentals)
        and not _INSIDER_QUALIFIER_RE.search(fundamentals)
    )
    if downstream_insider_claim or fundamentals_insider_claim:
        findings.append({
            "severity": "HIGH",
            "code": "INSIDER_ABSENCE_UNVERIFIED",
            "finding": (
                "The report says there were no insider transactions/activity, but the supplied report state "
                "does not provide a clearly traceable source and successful query result for that conclusion."
            ),
        })

    if fundamentals.strip() and not _urls(fundamentals) and not (
        _UNAVAILABLE_RE.search(fundamentals) or _NO_DATA_RE.search(fundamentals)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "FUNDAMENTALS_CITATIONS_MISSING",
            "finding": (
                "Fundamentals report contains no direct source URL. Financial statements and ratios cannot "
                "be traced from the generated report alone."
            ),
        })

    if news.strip() and not _urls(news):
        findings.append({
            "severity": "MEDIUM",
            "code": "NEWS_CITATIONS_MISSING",
            "finding": (
                "News report contains no direct source URLs. Named company events and macro claims are not "
                "auditable from the generated report alone."
            ),
        })

    if news.strip() and (
        _NEWS_ITEM_URL_MISSING_RE.search(news) or _has_unlinked_news_source_cue(news)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "NEWS_ITEM_URLS_MISSING",
            "finding": (
                "One or more news items lack an individual source URL even though other report links may be present. "
                "Do not use the unlinked item as independently traceable evidence."
            ),
        })

    if news.strip() and _urls(news) and (
        _MISSING_NEWS_DATE_RE.search(news)
        or not re.search(r"(?i)\b(?:publication date|published|ngày công bố)\s*[:：]", news)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "NEWS_PUBLICATION_DATES_MISSING",
            "finding": (
                "One or more news items lack a source publication date. Keep them visibly undated and do not "
                "use them in time-sensitive or point-in-time claims."
            ),
        })

    if news.strip() and _FRED_SOURCE_CLAIM_RE.search(news) and not re.search(
        r"https?://fred\.stlouisfed\.org/series/", news, re.IGNORECASE
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "FRED_SERIES_CITATION_MISSING",
            "finding": (
                "News report refers to FRED macro data but contains no direct series page URL. "
                "A generic Fed/news link does not identify the time series behind the quoted value."
            ),
        })

    if news.strip() and _POLYMARKET_PROBABILITY_RE.search(news):
        has_market_url = bool(_POLYMARKET_URL_RE.search(news))
        if not has_market_url or _MARKET_URL_MISSING_RE.search(news):
            findings.append({
                "severity": "MEDIUM",
                "code": "PREDICTION_MARKET_URL_MISSING",
                "finding": (
                    "News report discusses a prediction-market probability without a verifiable Polymarket market URL. "
                    "The generic Gamma API endpoint is not a substitute for the specific market page."
                ),
            })
        if not re.search(r"Observed at \(UTC\):|Retrieved at \(UTC\):", news, re.IGNORECASE):
            findings.append({
                "severity": "MEDIUM",
                "code": "PREDICTION_MARKET_TIMESTAMP_MISSING",
                "finding": (
                    "News report discusses live prediction-market odds without an observation/retrieval timestamp. "
                    "Live probabilities must not be presented as timeless facts."
                ),
            })

    if sentiment.strip() and _SOCIAL_POST_URL_MISSING_RE.search(sentiment):
        findings.append({
            "severity": "MEDIUM",
            "code": "SENTIMENT_POST_URLS_MISSING",
            "finding": (
                "At least one Reddit/StockTwits item lacks a provider-supplied permalink. The source stream URL proves which feed was queried, "
                "but not which individual post supports a particular sentiment claim."
            ),
        })

    if sentiment.strip() and not _urls(sentiment):
        findings.append({
            "severity": "MEDIUM",
            "code": "SENTIMENT_CITATIONS_MISSING",
            "finding": (
                "Sentiment report contains no direct source URLs. Preserve source name, sample size/window, "
                "and links so readers can distinguish an empty feed from unavailable coverage."
            ),
        })

    execution_text = "\n".join((
        _text(final_state.get("trader_investment_plan")),
        _text(final_state.get("final_trade_decision")),
    ))
    if _MISSING_TRADE_LEVEL_RE.search(execution_text):
        findings.append({
            "severity": "MEDIUM",
            "code": "TRADE_PLAN_LEVELS_MISSING",
            "finding": (
                "Trader plan explicitly leaves one or more entry, stop-loss, or price-target fields blank. "
                "Treat the signal as directional analysis, not a fully specified execution plan."
            ),
        })

    parsed_levels: dict[str, float] = {}
    for level_match in _TRADE_LEVEL_FIELD_RE.finditer(execution_text):
        label = re.sub(r"[^a-z]", "", level_match.group("label").casefold())
        canonical_label = (
            "entry" if label == "entryprice"
            else "stop" if label == "stoploss"
            else "target" if label in {"pricetarget", "targetprice"}
            else label
        )
        parsed = _parse_trade_price_token(level_match.group("value"))
        if parsed is not None:
            parsed_levels.setdefault(canonical_label, parsed)

    entry_level = parsed_levels.get("entry")
    stop_level = parsed_levels.get("stop")
    target_level = parsed_levels.get("target")
    trader_action_for_levels = _TRADER_ACTION_RE.search(_text(final_state.get("trader_investment_plan")))

    if entry_level is not None and stop_level is not None:
        if min(entry_level, stop_level) > 0 and max(entry_level, stop_level) / min(entry_level, stop_level) >= 20:
            findings.append({
                "severity": "HIGH",
                "code": "TRADE_LEVEL_UNIT_MISMATCH",
                "finding": (
                    "Entry and stop-loss values parse to price levels more than 20x apart. This often indicates inconsistent "
                    "thousands/decimal notation or units; normalize all VND prices before using the plan."
                ),
            })

    if (
        trader_action_for_levels
        and trader_action_for_levels.group(1).casefold() == "buy"
        and entry_level is not None
        and target_level is not None
        and target_level <= entry_level
    ):
        findings.append({
            "severity": "HIGH",
            "code": "TRADE_TARGET_NOT_ABOVE_ENTRY",
            "finding": (
                "The Trader action is Buy, but the Portfolio/decision price target is not above the entry price. "
                "A long trade needs a target with positive price upside; reconcile the target or relabel it as an entry/support level."
            ),
        })

    risk_text = "\n".join((
        _text(final_state.get("trader_investment_plan")),
        _text(final_state.get("investment_plan")),
        _text(final_state.get("risk_debate_state")),
        _text(final_state.get("final_trade_decision")),
    ))
    for proposed_levels in _EQUAL_ENTRY_STOP_LOSS_RE.finditer(risk_text):
        entry_digits = re.sub(r"\D", "", proposed_levels.group("entry"))
        stop_digits = re.sub(r"\D", "", proposed_levels.group("stop"))
        if entry_digits and entry_digits == stop_digits:
            findings.append({
                "severity": "HIGH",
                "code": "TRADE_ENTRY_EQUALS_STOP_LOSS",
                "finding": (
                    f"A proposed trade uses the same price for entry ({proposed_levels.group('entry')}) "
                    f"and stop-loss ({proposed_levels.group('stop')}). This is not a usable risk limit; "
                    "reconcile entry, stop distance, fees/slippage, and position sizing before treating it as executable."
                ),
            })
            break

    reported_rating = str(final_state.get("final_rating") or "").strip()
    decision_text = _text(final_state.get("final_trade_decision"))
    rating_match = re.search(
        r"(?im)^\s*(?:\*\*)?rating(?:\*\*)?\s*[:：]\s*(buy|overweight|hold|underweight|sell)\b",
        decision_text,
    )
    if reported_rating and rating_match and reported_rating.casefold() != rating_match.group(1).casefold():
        findings.append({
            "severity": "HIGH",
            "code": "FINAL_RATING_MISMATCH",
            "finding": (
                f"Structured final_rating ({reported_rating}) conflicts with the rating rendered in "
                f"final_trade_decision ({rating_match.group(1)}). Reconcile before relying on the report."
            ),
        })

    research_rating_match = _RATING_RE.search(_text(final_state.get("investment_plan")))
    trader_action_match = _TRADER_ACTION_RE.search(_text(final_state.get("trader_investment_plan")))
    final_rating_match = _RATING_RE.search(decision_text)

    def _direction(label: str) -> int:
        normalized = label.strip().casefold()
        if normalized in {"buy", "overweight"}:
            return 1
        if normalized in {"sell", "underweight"}:
            return -1
        return 0

    # Underweight and Sell share a negative direction but are not identical in
    # strength. Flag opposing directions, not the normal rating/action mapping.
    if trader_action_match:
        trader_direction = _direction(trader_action_match.group(1))
        for label, match in (
            ("Research Manager", research_rating_match),
            ("Portfolio Manager", final_rating_match),
        ):
            if match and _direction(match.group(1)) != trader_direction:
                findings.append({
                    "severity": "HIGH",
                    "code": "DECISION_DIRECTION_MISMATCH",
                    "finding": (
                        f"Trader action ({trader_action_match.group(1)}) points in a different direction "
                        f"from {label} rating ({match.group(1)}). Reconcile before relying on the signal."
                    ),
                })
                break

    high_count = sum(item["severity"] == "HIGH" for item in findings)
    overall = "REVIEW REQUIRED" if findings else "NO AUTOMATED FLAGS"
    return {
        "overall_status": overall,
        "analysis_date": _text(final_state.get("trade_date")) or "not recorded",
        "source_statuses": source_statuses,
        "fundamentals_url_count": len(_urls(fundamentals)),
        "news_url_count": len(_urls(news)),
        "sentiment_url_count": len(_urls(sentiment)),
        "findings": findings,
        "high_severity_count": high_count,
        "notice": (
            "This deterministic audit checks report text and metadata only. It is not a fact-check, "
            "does not independently validate external sources, and never changes the model's rating."
        ),
    }


def render_report_quality_markdown(audit: dict[str, Any]) -> str:
    """Render the deterministic audit for inclusion in Markdown and HTML reports."""
    lines = [
        f"**Automated evidence status:** {audit['overall_status']}",
        f"**Analysis date:** {audit['analysis_date']}",
        "",
        "| Report/source block | Availability status |",
        "|---|---|",
    ]
    for label, status in audit["source_statuses"].items():
        lines.append(f"| {label} | {status} |")
    lines.extend([
        "",
        f"- Direct URLs in Fundamentals report: {audit['fundamentals_url_count']}",
        f"- Direct URLs in News report: {audit['news_url_count']}",
        f"- Direct URLs in Sentiment report: {audit['sentiment_url_count']}",
        "",
        "### Findings",
        "",
    ])
    if audit["findings"]:
        for finding in audit["findings"]:
            lines.append(f"- **{finding['severity']} · {finding['code']}** — {finding['finding']}")
    else:
        lines.append("- No predefined text-pattern issues were detected. This does not mean all claims have been independently verified.")
    lines.extend(["", f"> {audit['notice']}", ""])
    return "\n".join(lines)
