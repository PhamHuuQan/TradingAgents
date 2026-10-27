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
    r"|tạm thời không khả dụng|không thể trích xuất|không lấy được dữ liệu"
    r"|dữ liệu .*?không khả dụng|thiếu dữ liệu (?:tài chính|cơ bản)",
    re.IGNORECASE,
)
_NO_DATA_RE = re.compile(
    r"\bNO_DATA_AVAILABLE\b|no usable (?:market|fundamental) data|"
    r"no data (?:was|were) returned|không có dữ liệu sử dụng được",
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
    r"|\brobust cash flow\b",
    re.IGNORECASE,
)
_INSIDER_ABSENCE_RE = re.compile(
    r"không có (?:báo cáo )?(?:giao dịch|hoạt động giao dịch) nội bộ"
    r"|chưa có (?:báo cáo )?(?:giao dịch|hoạt động giao dịch) nội bộ"
    r"|no (?:unusual )?insider (?:transactions|trading|activity)"
    r"|no insider trades",
    re.IGNORECASE,
)
_INSIDER_QUALIFIER_RE = re.compile(
    r"not proof (?:that )?(?:no|there (?:was|were) no) insider"
    r"|not proof of (?:no|absence of) insider"
    r"|not exhaustive|no records were returned|empty result from one provider"
    r"|không phải bằng chứng rằng không có|không chứng minh không có",
    re.IGNORECASE,
)
_MISSING_TRADE_LEVEL_RE = re.compile(
    r"(?:entry price|stop[\s-]?loss|price target)\s*[:：]\s*(?:not provided|not specified|n/?a|chưa có|không có)",
    re.IGNORECASE,
)


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
    return list(dict.fromkeys(_URL_RE.findall(text or "")))


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
    ]
    if not fundamentals.strip() or _UNAVAILABLE_RE.search(fundamentals) or _NO_DATA_RE.search(fundamentals):
        guardrails.append(
            "- FUNDAMENTALS LIMITATION: financial statements/ratios are unavailable or not usable in the supplied fundamentals report. "
            "Do not assert strong/weak cash flow, margins, solvency, valuation ratios, EPS/ROE, or a strong financial position "
            "unless that specific claim is supported by another named, dated source in the supplied evidence. State the limitation."
        )
        guardrails.append(
            "- Do not write 'no insider transactions' or 'no unusual insider activity' unless the supplied tool result explicitly confirms "
            "that the relevant source was queried successfully for a stated period."
        )
    if not _urls(news) and news.strip():
        guardrails.append(
            "- NEWS PROVENANCE LIMITATION: the supplied news report contains no direct URLs. Do not present a named event, macro value, "
            "or prediction-market probability as verified unless another supplied source gives its URL and observation/publication date."
        )
    if not _urls(sentiment) and sentiment.strip():
        guardrails.append(
            "- SENTIMENT PROVENANCE LIMITATION: the supplied sentiment report contains no direct URLs; treat source-specific social/news "
            "claims as unverified and describe the sample size/window or missing coverage when available."
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
    news = _text(final_state.get("news_report"))
    sentiment = _text(final_state.get("sentiment_report"))
    fundamentals = _text(final_state.get("fundamentals_report"))
    downstream = _downstream_text(final_state)
    combined_news = news + "\n" + sentiment
    findings: list[dict[str, str]] = []

    if source_statuses["Fundamentals report"] in {"MISSING", "LIMITED / SOURCE UNAVAILABLE", "NO USABLE DATA RETURNED"}:
        findings.append({
            "severity": "HIGH",
            "code": "FUNDAMENTALS_UNAVAILABLE",
            "finding": (
                "Financial statements or ratios are missing/unavailable. Treat valuation, earnings, "
                "cash flow, margins, balance-sheet strength and ROE as unverified unless separately sourced."
            ),
        })

    if fundamentals and _UNAVAILABLE_RE.search(fundamentals) and _FINANCIAL_STRENGTH_RE.search(downstream):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_FINANCIAL_STRENGTH",
            "finding": (
                "Downstream debate/decision text asserts financial strength while the fundamentals report "
                "contains an unavailable-data marker. Remove the assertion or attach a separately verified source."
            ),
        })

    downstream_insider_claim = (
        _INSIDER_ABSENCE_RE.search(downstream)
        and not _INSIDER_QUALIFIER_RE.search(downstream)
    )
    fundamentals_insider_claim = (
        _INSIDER_ABSENCE_RE.search(fundamentals)
        and (
            _UNAVAILABLE_RE.search(fundamentals)
            or not _INSIDER_QUALIFIER_RE.search(fundamentals)
        )
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

    if news.strip() and not _urls(news):
        findings.append({
            "severity": "MEDIUM",
            "code": "NEWS_CITATIONS_MISSING",
            "finding": (
                "News report contains no direct source URLs. Named company events and macro claims are not "
                "auditable from the generated report alone."
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

    if _MISSING_TRADE_LEVEL_RE.search(_text(final_state.get("trader_investment_plan"))):
        findings.append({
            "severity": "MEDIUM",
            "code": "TRADE_PLAN_LEVELS_MISSING",
            "finding": (
                "Trader plan explicitly leaves one or more entry, stop-loss, or price-target fields blank. "
                "Treat the signal as directional analysis, not a fully specified execution plan."
            ),
        })

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

    high_count = sum(item["severity"] == "HIGH" for item in findings)
    overall = "REVIEW REQUIRED" if findings else "NO AUTOMATED FLAGS"
    return {
        "overall_status": overall,
        "analysis_date": _text(final_state.get("trade_date")) or "not recorded",
        "source_statuses": source_statuses,
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
