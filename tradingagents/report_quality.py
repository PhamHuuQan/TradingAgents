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
    r"|dữ liệu .*?không khả dụng|thiếu dữ liệu (?:tài chính|cơ bản)"
    r"|(?:revenue|profit before tax|PBT|profit after tax|PAT|EPS|financial statement|financial ratio)"
    r"\s+(?:details?|values?|metrics?)\s+(?:are|were|is|was)?\s*(?:unavailable|not available|not supplied)"
    r"|values?\s+(?:were|was|are)\s+not supplied"
    r"|(?:provider|source|feed|vendor|StockTwits|Reddit|Yahoo Finance|FRED|Vnstock)\b.{0,60}\b(?:unavailable|failed|error|timeout|timed out|not accessible)\b"
    r"|\b(?:HTTPError|TimeoutError|ConnectionError)\b",
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
    r"|(?:cải thiện|mở rộng|tăng).{0,45}biên lợi nhuận hoạt động"
    r"|operating margin.{0,45}(?:expanded|improved|increased|widened)"
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
_UNSUPPORTED_VALUATION_CLAIM_RE = re.compile(
    r"\b(?:undervalued|underpriced|mispriced|cheaply valued|bargain[- ]priced|bargain|deep[- ]value)\b"
    r"|\bgift at this price\b"
    r"|(?:định giá thấp|được định giá thấp|đang bị thị trường định giá thấp|định giá hấp dẫn|mức định giá hấp dẫn|"
    r"giá rẻ|mua rẻ|chiết khấu sâu|vùng giá chiết khấu|giá chiết khấu|món hời|món quà(?: từ trên trời rơi xuống)?)"
    r"|priced irrationally low|trading below intrinsic value",
    re.IGNORECASE,
)
_NUMERIC_VALUATION_MULTIPLE_RE = re.compile(
    r"(?i)(?:\bP\s*/\s*E\b|\bP\s*/\s*B\b|\bEV\s*/\s*EBITDA\b|"
    r"price[- ]to[- ]earnings|price[- ]to[- ]book)"
    r"[^\n]{0,45}?[:=]?\s*\d[\d,.]*(?:\s*x|\s*times|倍)?"
)

_UNSUPPORTED_REVERSAL_PROBABILITY_RE = re.compile(
    r"(?:xác suất|khả năng).{0,35}(?:bật hồi|hồi phục|đảo chiều|tăng giá).{0,50}(?:rất cao|cao|lớn|gần như chắc chắn|áp đảo)"
    r"|(?:very high|high) probability of (?:a )?(?:technical )?(?:bounce|rebound|reversal|recovery)"
    r"|highly likely.{0,60}(?:bounce|rebound|reversal)",
    re.IGNORECASE,
)
_UNSUPPORTED_DIRECTIONAL_PROBABILITY_RE = re.compile(
    r"(?:xác suất|khả năng).{0,70}(?:thủng hỗ trợ|phá vỡ hỗ trợ|mất mốc hỗ trợ|giảm sâu|rơi tiếp|"
    r"tiếp tục giảm|sụt giảm|bán tháo|giảm giá|breakdown|break support).{0,40}"
    r"(?:rất cao|cao|lớn|gần như chắc chắn|áp đảo)"
    r"|(?:very high|high) probability.{0,80}(?:break(?:ing)? support|breakdown|fall further|sell[- ]off|decline further)",
    re.IGNORECASE,
)
_REVERSAL_EVIDENCE_RE = re.compile(
    r"\bbacktest(?:ed|ing)?\b|\bwin rate\b|\bhit rate\b|historical (?:frequency|hit rate|reversal rate)"
    r"|sample of \d+|based on \d+ (?:observations|trades|cases)"
    r"|kiểm định lịch sử|tỷ lệ thành công lịch sử|mẫu gồm \d+",
    re.IGNORECASE,
)
_UNSUPPORTED_NUMERIC_RISK_RE = re.compile(
    r"(?:rủi ro|xác suất|khả năng|nguy cơ|risk|probability|chance)"
    r"[^\n.!?]{0,70}\b\d{1,3}(?:[.,]\d+)?\s*%"
    r"|\b\d{1,3}(?:[.,]\d+)?\s*%[^\n.!?]{0,70}"
    r"(?:rủi ro|xác suất|khả năng|nguy cơ|risk|probability|chance)",
    re.IGNORECASE,
)
_CAPITAL_FLOW_INFERENCE_RE = re.compile(
    r"(?:dòng tiền\s+(?:lớn|tổ chức|thông minh).{0,65}(?:rút ra|thoát ra|đang rời|tháo chạy|đang gom|thu gom|tích lũy)"
    r"|(?:institutional|smart money|large capital|large institutional money|institutional money|institutional capital)\s+(?:flows?\s+)?(?:(?:are|is)\s+)?(?:exiting|flowing out|accumulating|buying up|selling off|withdrawing)"
    r"|(?:khối ngoại|nhà đầu tư tổ chức).{0,55}(?:rút vốn|bán tháo|gom hàng|thoát hàng|đang bán ròng))",
    re.IGNORECASE,
)
_CAPITAL_FLOW_QUANTIFIED_EVIDENCE_RE = re.compile(
    r"(?:khối ngoại.{0,50}(?:mua ròng|bán ròng).{0,45}\d[\d,.]*"
    r"|(?:foreign net (?:buy|sell)|institutional net (?:buy|sell)|net foreign (?:buying|selling))"
    r".{0,55}\d[\d,.]*)",
    re.IGNORECASE,
)
_INSIDER_QUALIFIER_RE = re.compile(
    r"not proof (?:that )?(?:no|there (?:was|were) no) insider"
    r"|not proof of (?:no|absence of) insider"
    r"|not (?:definitive|conclusive) evidence (?:that )?(?:no|there (?:was|were) no) insider"
    r"|not exhaustive|no records were returned|empty result from one provider"
    r"|not evidence that (?:there are|there were|any) no insider"
    r"|không phải bằng chứng rằng không có|không chứng minh không có"
    r"|không đồng nghĩa(?: với việc)? không có"
    r"|không thể kết luận(?: rằng| là)? không có"
    r"|không phải là bằng chứng khẳng định"
    r"|kết quả trống từ một nguồn cung cấp dữ liệu duy nhất"
    r"|không phải là bằng chứng(?: xác thực)?(?: tuyệt đối)?[\s\S]{0,120}(?:không có|không diễn ra)"
    r"|không chứng minh(?: được)?(?: rằng)? không có",
    re.IGNORECASE,
)
_UNSUPPORTED_PORTFOLIO_ACTION_RE = re.compile(
    r"\b(?:maintain|keep|retain)\s+(?:your\s+|the\s+)?(?:current|existing)\s+(?:holdings|position|allocation|weight|exposure)\b"
    r"|(?:duy trì|giữ nguyên|tiếp tục duy trì)\s+(?:vị thế hiện tại|tỷ trọng hiện tại|cổ phiếu đang nắm giữ)"
    r"|tỷ trọng trung bình trong danh mục chuẩn"
    r"|medium allocation in (?:the )?standard portfolio",
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



_MARKET_REFERENCE_PRICE_RE = re.compile(
    r"(?i)(?:giá\s+(?:hiện tại|đóng cửa|gần nhất)|(?:closing|current|last)\s+price|\bclose\b)"
    r"[^\n]{0,45}?(\d[\d,.]*\d|\d)"
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
_FRED_SOURCE_CLAIM_RE = re.compile(r"\bFRED\b|Federal Reserve Economic Data", re.IGNORECASE)
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
_SOCIAL_SILENCE_CLAIM_RE = re.compile(
    r"hoàn toàn không có (?:dữ liệu|thảo luận).{0,100}(?:stocktwits|reddit|mạng xã hội|nhà đầu tư)?"
    r"|vắng bóng hoàn toàn.{0,100}(?:thảo luận|cộng đồng|nhà đầu tư)"
    r"|trống rỗng hoàn toàn.{0,100}(?:kênh tin tức|diễn đàn|thảo luận|cộng đồng|nhà đầu tư)"
    r"|mức độ quan tâm.{0,70}(?:không đáng kể|gần như không có|rất thấp|thấp)"
    r"|sự thiếu hụt thông tin định hướng.{0,90}(?:tổ chức|thị trường)"
    r"|dòng tiền thông minh.{0,75}(?:đang theo dõi|vẫn đang theo dõi|bắt đầu gom|đang gom)"
    r"|sự im lặng.{0,80}(?:từ )?(?:thị trường|cộng đồng|diễn đàn|nhà đầu tư)"
    r"|absence of catalysts.{0,80}(?:shows|suggests|indicates|reflects)"
    r"|cạn kiệt thanh khoản quan tâm"
    r"|low investor attention|low retail attention|limited investor interest|investor interest is low"
    r"|complete absence of (?:social|retail) discussion"
    r"|there (?:is|was) no social (?:discussion|activity) (?:at all|anywhere)"
    r"|lack of social discussion.{0,80}(?:shows|demonstrates|indicates)"
    r"|thiếu hụt hoàn toàn.{0,70}(?:dữ liệu|thông tin|nguồn)"
    r"|sự im lặng của mọi nguồn.{0,70}(?:thông tin|dữ liệu|cung cấp)"
    r"|mọi nguồn cung cấp thông tin.{0,70}(?:im lặng|không ghi nhận)",
    re.IGNORECASE,
)
_SOCIAL_COVERAGE_LIMITATION_RE = re.compile(
    r"(?:provider|feed|source).{0,45}(?:unavailable|failed|error|timed out|not available)"
    r"|no reddit posts found|no matching posts|not proof of zero discussion"
    r"|no individual (?:post|message) permalink was supplied"
    r"|provider block marks the feed unavailable",
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


_NEWS_PLACEHOLDER_CITATION_RE = re.compile(
    r"(?i)\b(?:report link|placeholder link|source link unavailable|link unavailable)\b"
)
_TECHNICAL_CROSSOVER_CLAIM_RE = re.compile(r"(?i)\b(?:death cross|golden cross)\b")
_TECHNICAL_CROSSOVER_DATE_RE = re.compile(
    r"(?i)(?:\b(?:death cross|golden cross)\b[^\n]{0,100}"
    r"(?:\b(?:on|occurred|formed|crossed|happened|xảy ra|hình thành)\b)[^\n]{0,35}"
    r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})"
    r"|(?:crossover date|crossing date|ngày giao cắt|thời điểm giao cắt)[^\n]{0,40}"
    r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}))"
)
_UNSUPPORTED_STOP_LOSS_INSTRUCTION_RE = re.compile(
    r"(?i)(?:\b(?:đặt|thiết lập|cần đặt|nên đặt|phải đặt|set|place|put)\b)"
    r"[^\n.!?]{0,50}(?:stop[\s-]?loss|cắt lỗ|ngưỡng cắt lỗ)"
    r"[^\n.!?]{0,70}\d[\d,.]*"
    r"|(?:stop[\s-]?loss|cắt lỗ|ngưỡng cắt lỗ)[^\n.!?]{0,40}"
    r"(?:at|tại|ở)\s*\d[\d,.]*"
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


def _status(text: str, source_kind: str | None = None) -> str:
    """Classify coverage without letting a failed secondary feed erase usable evidence."""
    if not text.strip():
        return "MISSING"

    has_no_data = bool(_NO_DATA_RE.search(text))
    has_unavailable = bool(_UNAVAILABLE_RE.search(text))
    has_urls = bool(_urls(text))

    if source_kind == "market_report":
        has_numeric_market_claim = bool(_MARKET_NUMERIC_CLAIM_RE.search(text))
        has_snapshot_provenance = not _market_provenance_missing(text)
        if has_numeric_market_claim and has_urls and has_snapshot_provenance:
            if has_no_data or has_unavailable:
                return "PARTIAL COVERAGE — SOURCE-LINKED MARKET DATA; SECONDARY FEED UNAVAILABLE"
            return "AVAILABLE — SOURCE-LINKED MARKET DATA"

    if source_kind in {"news_report", "sentiment_report"} and has_urls:
        label = "NEWS" if source_kind == "news_report" else "SENTIMENT"
        if has_unavailable or has_no_data:
            return f"PARTIAL COVERAGE — SOURCE-LINKED {label}; SECONDARY FEED UNAVAILABLE"
        return f"AVAILABLE — SOURCE-LINKED {label}"

    if source_kind == "fundamentals_report":
        has_summary_metrics = _has_source_linked_summary_metrics(text)
        if has_summary_metrics and (
            _PARTIAL_FUNDAMENTALS_RE.search(text) or has_unavailable or has_no_data
        ):
            return "PARTIAL — SOURCE-LINKED SUMMARY METRICS; FULL STATEMENTS UNAVAILABLE"
        if has_summary_metrics:
            return "AVAILABLE — SOURCE-LINKED SUMMARY METRICS"

    if has_no_data:
        return "NO USABLE DATA RETURNED"
    if has_unavailable:
        return "LIMITED / SOURCE UNAVAILABLE"
    return "PRESENT — NOT INDEPENDENTLY VERIFIED"


def _urls(text: str) -> list[str]:
    # Narrative punctuation is not part of the URL.
    values = (url.rstrip(".,;:!?") for url in _URL_RE.findall(text or ""))
    return list(dict.fromkeys(url for url in values if url))


def _has_source_linked_summary_metrics(text: str) -> bool:
    """True when a report supplies a source URL and at least two numeric earnings-summary metrics."""
    # The analyst may put the value in the next Markdown bullet (e.g. a metric
    # heading followed by "- Giá trị: 40.023 tỷ VND"). Allow that layout while
    # still requiring at least two distinct financial metric families and a URL.
    numeric_financial_value = (
        r"\d[\d,.]*\s*(?:%|VND|VNĐ|USD|EUR|GBP|"
        r"billion|million|trillion|\btỷ\b|\bđồng\b|"
        r"cổ phiếu|per share|/share)"
    )
    metric_patterns = (
        rf"(?:\brevenue\b|doanh thu(?: hợp nhất| thuần)?).{{0,180}}{numeric_financial_value}",
        rf"(?:\bPBT\b|\bLNTT\b|lợi nhuận trước thuế|profit before tax).{{0,180}}{numeric_financial_value}",
        rf"(?:\bPAT\b|\bLNST\b|lợi nhuận sau thuế|profit after tax).{{0,180}}{numeric_financial_value}",
        rf"(?:\bEPS\b|lãi cơ bản trên (?:mỗi )?cổ phiếu|lợi nhuận trên mỗi cổ phiếu|earnings per share).{{0,180}}{numeric_financial_value}",
    )
    metric_count = sum(
        bool(re.search(pattern, text or "", re.IGNORECASE | re.DOTALL))
        for pattern in metric_patterns
    )
    return metric_count >= 2 and bool(_urls(text))


def _has_numeric_valuation_multiple(text: str) -> bool:
    """True only when a valuation multiple is attached to a numeric value."""
    return bool(_NUMERIC_VALUATION_MULTIPLE_RE.search(text or ""))


# These patterns intentionally focus on explicit *numeric current-market claims*,
# not qualitative phrases such as "RSI is oversold". A URL is not enough to
# establish that the number in the model's prose matches the fetched data.
_MARKET_NUMERIC_CLAIM_PATTERNS: dict[str, tuple[str, ...]] = {
    "close": (
        r"(?i)\b(?:current|closing|last|share|stock)\s+price\b[^\n]{0,40}?"
        r"(?:at|is|of|around|approximately|[:=])?\s*(-?\d[\d.,]*)",
        r"(?i)\b(?:giá hiện tại|giá đóng cửa|giá gần nhất|giá cổ phiếu)\b[^\n]{0,40}?"
        r"(?:ở mức|tại|là|khoảng|[:=])?\s*(-?\d[\d.,]*)",
        r"(?i)\bclose(?:\s+price)?\s*(?::|=|\b(?:at|is|of)\b)?\s*(-?\d[\d.,]*)",
    ),
    "close_10_ema": (
        r"(?i)\bEMA\s*[- ]?10\b[^\n]{0,35}?(-?\d[\d.,]*)",
    ),
    "close_50_sma": (
        r"(?i)\bSMA\s*[- ]?50\b[^\n]{0,35}?(-?\d[\d.,]*)",
    ),
    "close_200_sma": (
        r"(?i)\bSMA\s*[- ]?200\b[^\n]{0,35}?(-?\d[\d.,]*)",
    ),
    "rsi": (
        r"(?i)\bRSI(?:\s*\d+)?(?:\s*[:=]\s*|\s+(?:at|is|of|around|approximately|"
        r"ở mức|tại|là|đạt)\s+|\s+)(-?\d[\d.,]*)",
    ),
    "macd": (
        r"(?i)\bMACD\b(?!\s*(?:hist(?:ogram)?|signal|macdh|macds))"
        r"(?:\s*[:=]\s*|\s+(?:at|is|of|around|approximately|ở mức|tại|là)\s+|\s+)"
        r"(-?\d[\d.,]*)",
    ),
    "macds": (
        r"(?i)\bMACD\s*(?:signal|signal line|macds)\b[^\n]{0,35}?(-?\d[\d.,]*)",
    ),
    "macdh": (
        r"(?i)\b(?:MACD\s*(?:histogram|hist|macdh)|histogram)\b"
        r"(?:\s*[:=]\s*|\s+(?:is|at|of|approximately|ở mức|là)\s+|\s+)"
        r"(-?\d[\d.,]*)",
    ),
    "atr": (
        r"(?i)\bATR(?:\s*\d+)?(?:\s*[:=]\s*|\s+(?:at|is|of|around|approximately|ở mức|là)\s+|\s+)"
        r"(-?\d[\d.,]*)",
    ),
    "boll_lb": (
        r"(?i)(?:\blower Bollinger(?: band)?|Bollinger(?: band)? lower|dải Bollinger dưới)"
        r"[^\n]{0,35}?(-?\d[\d.,]*)",
    ),
    "boll_ub": (
        r"(?i)(?:\bupper Bollinger(?: band)?|Bollinger(?: band)? upper|dải Bollinger trên)"
        r"[^\n]{0,35}?(-?\d[\d.,]*)",
    ),
}


def _market_narrative(text: str) -> str:
    """Exclude source appendices from the text whose claims are independently checked."""
    return re.split(
        r"(?im)^\s*#{1,6}\s*(?:market data provenance|verified numeric evidence)\s*$",
        text or "",
        maxsplit=1,
    )[0]


def _verified_market_snapshot_values(text: str) -> dict[str, float]:
    """Read the numeric evidence appendix copied from the verified snapshot tool."""
    appendix = re.split(
        r"(?im)^\s*#{1,6}\s*verified numeric evidence\s*$",
        text or "",
        maxsplit=1,
    )
    if len(appendix) < 2:
        return {}
    evidence = re.split(r"(?m)^\s*#{1,6}\s+", appendix[1], maxsplit=1)[0]
    values: dict[str, float] = {}
    for line in evidence.splitlines():
        match = re.match(
            r"(?i)^\s*-\s*Verified (OHLCV|indicator)\s+([A-Za-z][A-Za-z0-9_]*)\s*:\s*(-?[\d.,]+)\s*$",
            line,
        )
        if not match:
            continue
        kind, label, token = match.groups()
        key = label.casefold()
        if kind.casefold() == "ohlcv":
            key = {"close": "close"}.get(key, f"ohlcv_{key}")
        parsed = _parse_trade_price_token(token)
        if parsed is not None:
            values[key] = parsed
    return values


def _market_numeric_claims(text: str) -> list[tuple[str, float, str]]:
    """Extract explicit current-price/indicator values for deterministic comparison."""
    narrative = _market_narrative(text)
    claims: list[tuple[str, float, str]] = []
    for metric, patterns in _MARKET_NUMERIC_CLAIM_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, narrative):
                token = match.group(1)
                parsed = _parse_trade_price_token(token)
                if parsed is not None:
                    claims.append((metric, parsed, token))
    # One sentence can match two patterns for the same label; deduplicate identical claims.
    return list(dict.fromkeys(claims))


def _market_numeric_discrepancies(
    text: str,
) -> tuple[list[tuple[str, float, float, str]], list[tuple[str, str]]]:
    """Compare narrative values with the independently generated numeric snapshot.

    A claim is considered unreconciled when the report names a metric but the
    snapshot appendix does not contain that metric. This does not prove external
    truth: it only verifies internal consistency with the source data that was
    fetched and preserved by the deterministic snapshot tool.
    """
    snapshot = _verified_market_snapshot_values(text)
    discrepancies: list[tuple[str, float, float, str]] = []
    unreconciled: list[tuple[str, str]] = []
    seen: set[tuple[str, float, float]] = set()
    for metric, reported, token in _market_numeric_claims(text):
        expected = snapshot.get(metric)
        if expected is None:
            item = (metric, token)
            if item not in unreconciled:
                unreconciled.append(item)
            continue
        # Permit display rounding but not meaningful value/scale mismatches.
        tolerance = max(0.03, abs(expected) * 0.0005)
        if abs(reported - expected) > tolerance:
            identity = (metric, reported, expected)
            if identity not in seen:
                seen.add(identity)
                discrepancies.append((metric, reported, expected, token))
    return discrepancies, unreconciled


_MACRO_NUMERIC_CLAIM_PATTERNS: dict[str, tuple[str, ...]] = {
    "DGS10": (
        r"(?i)\bDGS10\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
        r"(?i)\b(?:10[- ]year|10y)\s+(?:U\.S\.\s+)?Treasury\s+(?:security\s+)?yield\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
    ),
    "DGS2": (
        r"(?i)\bDGS2\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
        r"(?i)\b2[- ]year\s+(?:U\.S\.\s+)?Treasury\s+(?:security\s+)?yield\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
    ),
    "DGS30": (
        r"(?i)\bDGS30\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
        r"(?i)\b30[- ]year\s+(?:U\.S\.\s+)?Treasury\s+(?:security\s+)?yield\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
    ),
    "FEDFUNDS": (
        r"(?i)\bFEDFUNDS\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
        r"(?i)\b(?:Federal Funds Effective Rate|federal funds rate|Fed funds rate)\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
    ),
    "UNRATE": (
        r"(?i)\bUNRATE\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
        r"(?i)\b(?:U\.S\.\s+)?unemployment rate\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)\s*%?",
    ),
    "VIXCLS": (
        r"(?i)\bVIXCLS\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)",
        r"(?i)\bVIX(?: index| level)?\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])\s*(-?\d[\d.,]*)",
    ),
    "T10Y2Y": (
        r"(?i)\bT10Y2Y\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)",
        r"(?i)\b(?:10[- ]year\s*(?:minus|[-/])\s*2[- ]year|10y\s*(?:minus|[-/])\s*2y)\s+(?:Treasury\s+)?(?:yield\s+)?spread\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)",
    ),
    "DTWEXBGS": (
        r"(?i)\bDTWEXBGS\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])?\s*(-?\d[\d.,]*)",
        r"(?i)\b(?:broad\s+)?U\.S\.\s+dollar index\b[^\n]{0,45}?(?:at|is|was|of|around|approximately|stood at|[:=])\s*(-?\d[\d.,]*)",
    ),
}


_MACRO_FORECAST_CUE_RE = re.compile(
    r"(?i)\b(?:forecast|forecasted|project(?:ed|ion)?|expect(?:ed|ation)?|estimate(?:d)?|"
    r"market[- ]implied|prediction market|probability|will likely|is likely to|could reach|"
    r"may reach|dự báo|kỳ vọng|ước tính|xác suất|có thể đạt|có khả năng sẽ)\b"
)
_MACRO_HISTORICAL_CUE_RE = re.compile(
    r"(?i)\b(?:historical(?:ly)?|in the past|previously|last year|years ago|"
    r"trong quá khứ|năm ngoái|trước đây)\b|\b(?:19|20)\d{2}\b"
)


def _verified_macro_series_values(text: str) -> dict[str, tuple[float, str, str]]:
    """Return latest FRED values preserved in the tool-provenance appendix.

    The parser only accepts series records with a direct FRED series URL and a
    labeled latest observation date. It does not treat URLs alone as numeric evidence.
    """
    marker = re.search(
        r"(?im)^\s*#{1,6}\s*macro and prediction-market records returned by tools\s*$",
        text or "",
    )
    if not marker:
        return {}
    appendix = text[marker.end():]
    starts = list(re.finditer(
        r"(?im)^\s*-\s*\*\*get_macro_indicators\s+—\s*(.+?)\*\*\s*$",
        appendix,
    ))
    values: dict[str, tuple[float, str, str]] = {}
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(appendix)
        block = appendix[start.end():end]
        url_match = re.search(
            r"(?im)^\s*-\s*Source URL\s*[:：]\s*https?://fred\.stlouisfed\.org/series/([A-Z0-9]+)\s*$",
            block,
        )
        if not url_match:
            continue
        series_id = url_match.group(1).upper()
        latest_match = re.search(
            r"(?im)^\s*-\s*\**Latest\**\s*:\s*\**\s*(-?[\d,.]+)\s*\((\d{4}-\d{2}-\d{2})\)",
            block,
        )
        unit_match = re.search(r"(?im)^\s*-\s*Units\s*[:：]\s*(.+?)\s*$", block)
        if not latest_match or not unit_match:
            continue
        latest_value = _parse_trade_price_token(latest_match.group(1))
        if latest_value is None:
            continue
        values[series_id] = (latest_value, unit_match.group(1).strip(), latest_match.group(2))
    return values


def _macro_numeric_claims(text: str) -> list[tuple[str, float, str]]:
    """Extract current, directly named FRED metric values; ignore forecasts/history."""
    claims: list[tuple[str, float, str]] = []
    for series_id, patterns in _MACRO_NUMERIC_CLAIM_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text or ""):
                context = text[max(0, match.start() - 70):min(len(text), match.end() + 45)]
                if _MACRO_FORECAST_CUE_RE.search(context) or _MACRO_HISTORICAL_CUE_RE.search(context):
                    continue
                token = match.group(1)
                value = _parse_trade_price_token(token)
                if value is not None:
                    claims.append((series_id, value, token))
    return list(dict.fromkeys(claims))


def _macro_numeric_discrepancies(
    news_report: str,
) -> tuple[list[tuple[str, float, float, str, str]], list[tuple[str, str]]]:
    """Compare current macro claims to latest source-linked FRED values in the report.

    This compares only a short allowlist of unambiguous, directly comparable
    series. It deliberately does not compare forecasts, market probabilities,
    historical claims, or ambiguous inflation/GDP transformations.
    """
    narrative = re.split(
        r"(?im)^\s*#{1,6}\s*(?:source records returned by news tools|macro and prediction-market records returned by tools|unavailable or empty tool responses)\s*$",
        news_report or "",
        maxsplit=1,
    )[0]
    source_values = _verified_macro_series_values(news_report)
    discrepancies: list[tuple[str, float, float, str, str]] = []
    unreconciled: list[tuple[str, str]] = []
    seen = set()
    for series_id, reported, token in _macro_numeric_claims(narrative):
        source = source_values.get(series_id)
        if source is None:
            item = (series_id, token)
            if item not in unreconciled:
                unreconciled.append(item)
            continue
        expected, unit, observation_date = source
        tolerance = max(0.02, abs(expected) * 0.0005)
        if abs(reported - expected) > tolerance:
            identity = (series_id, reported, expected)
            if identity not in seen:
                seen.add(identity)
                discrepancies.append((series_id, reported, expected, token, unit))
    return discrepancies, unreconciled


def _downstream_text(state: dict[str, Any]) -> str:
    pieces = [
        _text(state.get("investment_plan")),
        _text(state.get("trader_investment_plan")),
        _text(state.get("final_trade_decision")),
    ]
    for key in ("investment_debate_state", "risk_debate_state"):
        value = state.get(key) or {}
        if isinstance(value, dict):
            # State schemas can add/rename debate fields across graph revisions.
            # Include all textual values so the audit does not miss an unsupported
            # claim simply because it moved to a newly named history/response key.
            for name, nested in value.items():
                if isinstance(nested, (str, dict, list, tuple)):
                    pieces.append(f"{name}: {_text(nested)}")
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
        "- REVERSAL PROBABILITY LIMITATION: RSI below 30 or proximity to a Bollinger band does not quantify reversal odds. Do not call a bounce high-probability unless a cited historical test gives its sample, time horizon, and hit rate.",
        "- DIRECTIONAL PROBABILITY LIMITATION: do not call a support break, selloff, continuation move, or rebound 'high probability' without a cited quantitative method/backtest, defined sample, and time horizon. State it as a scenario, not a measured probability.",
        "- CAPITAL-FLOW INFERENCE LIMITATION: OHLC prices, moving averages, RSI, MACD, Bollinger bands, or volume alone do not prove that institutional investors or 'smart money' are exiting, accumulating, or selling net. State that flow direction is unknown unless the supplied evidence contains quantified, source-linked flow data.",
        "- NUMERIC RISK-PROBABILITY LIMITATION: do not assign a percentage to loss risk, rebound probability, or reversal odds without a cited quantitative method/backtest, defined sample and time horizon. Do not use unsupported claims such as '99% risk' based only on technical indicators.",
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
    fundamentals_has_summary_metrics = _has_source_linked_summary_metrics(fundamentals)
    fundamentals_has_unavailable_sections = bool(
        _UNAVAILABLE_RE.search(fundamentals) or _NO_DATA_RE.search(fundamentals)
    )
    fundamentals_are_partial = bool(_PARTIAL_FUNDAMENTALS_RE.search(fundamentals)) or (
        fundamentals_has_summary_metrics and fundamentals_has_unavailable_sections
    )
    fundamentals_fully_unavailable = (
        not fundamentals.strip()
        or (
            not fundamentals_has_summary_metrics
            and (
                _UNAVAILABLE_RE.search(fundamentals)
                or _NO_DATA_RE.search(fundamentals)
            )
        )
    )
    if _requires_fundamentals(state) and fundamentals_fully_unavailable:
        guardrails.append(
            "- FUNDAMENTALS LIMITATION: usable source-linked earnings metrics and financial statements/ratios "
            "are unavailable in the supplied fundamentals report. Do not invent revenue, PBT, PAT, EPS, "
            "cash flow, margins, solvency, valuation ratios, or a strong financial position. "
            "Do not assert strong/weak cash flow, balance-sheet strength, or liquidity without a source for that exact metric. "
            "State the limitation."
        )
    if _requires_fundamentals(state) and (
        fundamentals_fully_unavailable or fundamentals_are_partial
    ):
        guardrails.append(
            "- Do not write 'no insider transactions' or 'no unusual insider activity' unless the supplied tool result explicitly confirms "
            "that the relevant source was queried successfully for a stated period."
        )
    if _requires_fundamentals(state) and fundamentals_are_partial:
        guardrails.append(
            "- PARTIAL FUNDAMENTALS COVERAGE: the supplied report includes only source-linked summary metrics, "
            "not a complete financial-statement package. Use the exact supported revenue/PBT/PAT/EPS values, "
            "reporting period, units and growth rates it provides. Do not infer operating/free cash flow, cash balances, debt, "
            "liquidity, solvency, equity, margins, P/E, P/B, ROE, debt ratios, or insider activity unless another supplied "
            "source explicitly provides those values. State that those metrics remain unverified."
        )
    has_financial_data_limits = (
        not fundamentals.strip()
        or bool(_UNAVAILABLE_RE.search(fundamentals))
        or bool(_NO_DATA_RE.search(fundamentals))
        or bool(_PARTIAL_FUNDAMENTALS_RE.search(fundamentals))
    )
    if (
        _requires_fundamentals(state)
        and has_financial_data_limits
        and not _has_numeric_valuation_multiple(fundamentals)
    ):
        guardrails.append(
            "- VALUATION EVIDENCE LIMITATION: revenue/PBT/EPS growth or an oversold RSI does not establish that a stock is cheap or undervalued. "
            "Do not claim undervaluation, a bargain price, or a discount to intrinsic value without a dated, sourced valuation multiple or valuation model inputs."
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
    if sentiment.strip() and _SOCIAL_COVERAGE_LIMITATION_RE.search(sentiment):
        guardrails.append(
            "- SOCIAL COVERAGE LIMITATION: distinguish provider failure, a successful empty query, and a record without an individual permalink. "
            "An empty Yahoo Finance/StockTwits/Reddit result only describes that provider and requested window. Do not infer low retail interest, lack of institutional information or catalysts, market-wide silence, low liquidity, smart-money accumulation/distribution, or any price direction from it. "
            "State the exact provider, date window, and sample/coverage limitation; require separate evidence for any broader claim."
        )
    if not (isinstance(state.get("portfolio_context"), str) and state["portfolio_context"].strip()):
        guardrails.append(
            "- PORTFOLIO CONTEXT LIMITATION: current holdings, cost basis, allocation, cash, and personal risk limits were not supplied. Do not assume the user owns the asset or is fully invested. Do not tell the user to maintain or change an existing position, specify a portfolio allocation/weight, or refer to a 'standard portfolio' unless that portfolio is explicitly defined in the supplied context. For Hold, describe the recommendation conditionally (if already held, reassess against stated evidence; if not held, do not imply an existing position). Do not invent a personalized mandatory stop-loss; any numeric price threshold from the debate must be labelled as a conditional review/invalidation level, not an order instruction."
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
        label: _status(_text(final_state.get(key)), source_kind=key)
        for label, key in report_keys.items()
    }
    market = _text(final_state.get("market_report"))
    news = _text(final_state.get("news_report"))
    sentiment = _text(final_state.get("sentiment_report"))
    fundamentals = _text(final_state.get("fundamentals_report"))
    news_narrative = re.split(
        r"(?im)^\s*#{0,6}\s*(?:source records returned by news tools|macro and prediction-market records returned by tools|unavailable or empty tool responses)\s*$",
        news,
        maxsplit=1,
    )[0]
    sentiment_narrative = re.split(
        r"(?im)^\s*#{0,6}\s*source urls and coverage supplied to sentiment analysis\s*$",
        sentiment,
        maxsplit=1,
    )[0]
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

    macro_discrepancies, macro_unreconciled = _macro_numeric_discrepancies(news)
    if macro_discrepancies:
        examples = "; ".join(
            f"{series_id}: report={reported:g}, FRED={expected:g} {unit} (observation {observation_date})"
            for series_id, reported, expected, _token, unit in macro_discrepancies[:5]
            for _source in [ _verified_macro_series_values(news).get(series_id, (expected, unit, "")) ]
            for observation_date in [_source[2]]
        )
        findings.append({
            "severity": "HIGH",
            "code": "MACRO_NUMERIC_CLAIM_MISMATCH",
            "finding": (
                "A current macroeconomic number in the news/market context conflicts with the latest source-linked FRED value preserved in the tool appendix. "
                f"Correct the narrative or explicitly identify and source the distinct observation/date. Discrepancies: {examples}."
            ),
        })
    if macro_unreconciled:
        series_labels = ", ".join(dict.fromkeys(series_id for series_id, _token in macro_unreconciled))
        findings.append({
            "severity": "MEDIUM",
            "code": "MACRO_CLAIMS_NOT_RECONCILED_TO_FRED",
            "finding": (
                "A directly named macro series appears with a numeric value, but no matching latest value with a direct FRED series URL, units and observation date "
                f"was preserved in the tool appendix. Metrics: {series_labels}. A prose citation alone does not establish numeric agreement."
            ),
        })

    market_discrepancies, market_unreconciled = _market_numeric_discrepancies(market)
    if market_discrepancies:
        examples = "; ".join(
            f"{metric}: report={reported:g}, verified={expected:g}"
            for metric, reported, expected, _token in market_discrepancies[:5]
        )
        findings.append({
            "severity": "HIGH",
            "code": "MARKET_NUMERIC_CLAIM_MISMATCH",
            "finding": (
                "At least one explicit current-price/technical-indicator value in the market narrative conflicts "
                "with the deterministic verified snapshot. Recalculate or correct the narrative from the preserved "
                f"source values. Discrepancies: {examples}."
            ),
        })
    if market_unreconciled:
        labels = ", ".join(dict.fromkeys(metric for metric, _token in market_unreconciled))
        findings.append({
            "severity": "MEDIUM",
            "code": "MARKET_CLAIMS_NOT_RECONCILED_TO_SNAPSHOT",
            "finding": (
                "The narrative includes exact current-market numbers that cannot be compared with the verified numeric "
                f"snapshot; the relevant values were absent from the evidence appendix or no validated snapshot was preserved. Metrics: {labels}. "
                "A source URL and retrieval timestamp alone do not confirm that the number in the prose is correct."
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

    if (
        _requires_fundamentals(final_state)
        and fundamentals_limitations
        and _UNSUPPORTED_VALUATION_CLAIM_RE.search(downstream)
        and not _has_numeric_valuation_multiple(fundamentals)
    ):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_VALUATION_CLAIM",
            "finding": (
                "Downstream debate/decision text calls the stock undervalued, cheap, a bargain, or below intrinsic value "
                "without a numeric, source-linked valuation multiple in the supplied fundamentals report. "
                "Oversold technical indicators and earnings growth alone do not establish valuation."
            ),
        })

    if (
        _UNSUPPORTED_REVERSAL_PROBABILITY_RE.search(downstream)
        and not _REVERSAL_EVIDENCE_RE.search(downstream)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "UNSUPPORTED_REVERSAL_PROBABILITY",
            "finding": (
                "The report describes a technical bounce/reversal as highly probable without a cited historical test, "
                "sample definition, time horizon, or hit rate. RSI oversold conditions and Bollinger proximity alone "
                "do not establish a quantified probability."
            ),
        })

    if (
        _UNSUPPORTED_DIRECTIONAL_PROBABILITY_RE.search(downstream)
        and not _REVERSAL_EVIDENCE_RE.search(downstream)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "UNSUPPORTED_DIRECTIONAL_PROBABILITY",
            "finding": (
                "The report describes a directional risk (such as support breaking or a further selloff) as highly probable "
                "without a cited quantitative method, defined sample, and time horizon. Rephrase as a possible scenario or provide reproducible evidence."
            ),
        })

    if (
        _UNSUPPORTED_NUMERIC_RISK_RE.search(downstream)
        and not _REVERSAL_EVIDENCE_RE.search(downstream)
    ):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_NUMERIC_RISK_PROBABILITY",
            "finding": (
                "Downstream analysis assigns a numeric percentage to risk, loss, or probability without a cited "
                "quantitative method, defined sample, and time horizon. Remove the percentage or provide a reproducible source."
            ),
        })

    if (
        _CAPITAL_FLOW_INFERENCE_RE.search(downstream)
        and not _CAPITAL_FLOW_QUANTIFIED_EVIDENCE_RE.search("\n".join((market, news, sentiment, fundamentals)))
    ):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_CAPITAL_FLOW_INFERENCE",
            "finding": (
                "Downstream analysis infers institutional or 'smart money' inflows/outflows from price/technical signals "
                "without quantified, source-linked flow evidence. OHLC and momentum indicators do not identify investor class or net capital flow."
            ),
        })

    has_portfolio_context = (
        isinstance(final_state.get("portfolio_context"), str)
        and bool(final_state["portfolio_context"].strip())
    )
    if not has_portfolio_context and _UNSUPPORTED_PORTFOLIO_ACTION_RE.search(downstream):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_PORTFOLIO_CONTEXT_ACTION",
            "finding": (
                "The recommendation assumes existing holdings or specifies an allocation/weight although no portfolio context was supplied. "
                "State Hold conditionally and leave holdings, position size and allocation unspecified until the user's portfolio is known."
            ),
        })

    if (
        _TECHNICAL_CROSSOVER_CLAIM_RE.search(market)
        and not _TECHNICAL_CROSSOVER_DATE_RE.search(market)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "TECHNICAL_CROSSOVER_DATE_UNVERIFIED",
            "finding": (
                "The market report names a Death Cross/Golden Cross but supplies no dated crossover event. "
                "SMA50 below SMA200 establishes the current ordering, not when the crossover occurred."
            ),
        })

    has_portfolio_context_for_trade = (
        isinstance(final_state.get("portfolio_context"), str)
        and bool(final_state["portfolio_context"].strip())
    )
    if (
        not has_portfolio_context_for_trade
        and _UNSUPPORTED_STOP_LOSS_INSTRUCTION_RE.search(downstream)
    ):
        findings.append({
            "severity": "HIGH",
            "code": "UNSUPPORTED_STOP_LOSS_INSTRUCTION",
            "finding": (
                "The debate contains an executable stop-loss instruction with a numeric level although no user portfolio context was supplied. "
                "Rephrase it as a conditional review/invalidation threshold rather than a personalized order instruction."
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

    asset_type = str(final_state.get("asset_type") or "stock").strip().casefold()
    # Tool-provenance blocks may faithfully preserve irrelevant search results that
    # the analyst explicitly excluded. Relevance checks should assess the narrative,
    # not flag a source merely because it appears in the raw audit trail.
    news_for_relevance = re.split(
        r"(?im)^\s*(?:source records returned by news tools|macro and prediction-market records returned by tools)",
        news,
        maxsplit=1,
    )[0]
    exclusion_only_line = re.compile(
        r"(?i)(?:thị trường dự đoán về )?thể thao.{0,100}(?:được loại trừ|đã loại trừ|không đưa vào phân tích|excluded|not included)"
        r"|(?:AFC Asian Cup|sports prediction market).{0,100}(?:được loại trừ|đã loại trừ|không đưa vào phân tích|excluded|not included)"
    )
    news_for_relevance = "\n".join(
        line for line in news_for_relevance.splitlines()
        if not exclusion_only_line.search(line)
    )
    sports_market_mention = re.search(
        r"(?is)(?:polymarket|prediction market|thị trường dự báo).{0,260}"
        r"(?:afc asian cup|world cup|champions league|premier league|nba|nfl|mlb|nhl|"
        r"olympics?|grand prix|football|soccer|basketball|tennis|sports event|sự kiện thể thao)"
        r"|(?:afc asian cup|world cup|champions league|premier league|nba|nfl|mlb|nhl|"
        r"olympics?|grand prix|football|soccer|basketball|tennis|sports event|sự kiện thể thao)"
        r".{0,260}(?:polymarket|prediction market|thị trường dự báo)",
        news_for_relevance,
    ) if news_for_relevance.strip() else None
    if sports_market_mention and asset_type not in {"sports", "sports event"}:
        findings.append({
            "severity": "MEDIUM",
            "code": "PREDICTION_MARKET_RELEVANCE_UNVERIFIED",
            "finding": (
                "The news report includes a sports/entertainment prediction market in an investment analysis. "
                "Unless the event has a documented transmission channel to the analyzed instrument, exclude it "
                "from the thesis and source summary rather than treating a search result as relevant evidence."
            ),
        })

    if news_narrative.strip():
        placeholder_without_url = any(
            _NEWS_PLACEHOLDER_CITATION_RE.search(line) and not _urls(line)
            for line in news_narrative.splitlines()
        )
        if placeholder_without_url:
            findings.append({
                "severity": "MEDIUM",
                "code": "NEWS_PLACEHOLDER_CITATIONS",
                "finding": (
                    "The news narrative contains generic placeholder citation text such as 'Report Link' without a target URL. "
                    "A URL appearing later in the raw tool-evidence appendix does not link that narrative claim to its source."
                ),
            })

    if news_narrative.strip() and _FRED_SOURCE_CLAIM_RE.search(news_narrative) and not re.search(
        r"https?://fred\.stlouisfed\.org/series/", news_narrative, re.IGNORECASE
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "FRED_SERIES_CITATION_MISSING",
            "finding": (
                "News report refers to FRED macro data but contains no direct series page URL. "
                "A generic Fed/news link does not identify the time series behind the quoted value."
            ),
        })

    if news_narrative.strip() and _POLYMARKET_PROBABILITY_RE.search(news_narrative):
        has_market_url = bool(_POLYMARKET_URL_RE.search(news_narrative))
        if not has_market_url or _MARKET_URL_MISSING_RE.search(news_narrative):
            findings.append({
                "severity": "MEDIUM",
                "code": "PREDICTION_MARKET_URL_MISSING",
                "finding": (
                    "News report discusses a prediction-market probability without a verifiable Polymarket market URL. "
                    "The generic Gamma API endpoint is not a substitute for the specific market page."
                ),
            })
        if not re.search(r"Observed at \(UTC\):|Retrieved at \(UTC\):", news_narrative, re.IGNORECASE):
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

    if _SOCIAL_SILENCE_CLAIM_RE.search(sentiment_narrative):
        findings.append({
            "severity": "MEDIUM",
            "code": "SENTIMENT_EMPTY_FEED_OVERSTATEMENT",
            "finding": (
                "The sentiment narrative uses absolute or market-wide silence language despite bounded, provider-specific feeds. "
                "Describe only what each queried provider returned for the stated window; do not claim every source or the entire market was silent."
            ),
        })

    if (
        _SOCIAL_SILENCE_CLAIM_RE.search(downstream)
        and sentiment.strip()
        and _SOCIAL_COVERAGE_LIMITATION_RE.search(sentiment)
    ):
        findings.append({
            "severity": "MEDIUM",
            "code": "SOCIAL_SILENCE_EXTRAPOLATION",
            "finding": (
                "Downstream analysis generalizes an unavailable provider or an empty search window into market-wide social silence, "
                "investor inattention, or weak liquidity. A provider failure and a successful zero-result query are different, "
                "and neither alone establishes overall investor attention or the stock's trading liquidity."
            ),
        })

    execution_text = "\n".join((
        _text(final_state.get("trader_investment_plan")),
        _text(final_state.get("final_trade_decision")),
    ))
    trader_action_for_missing_levels = _TRADER_ACTION_RE.search(
        _text(final_state.get("trader_investment_plan"))
    )
    # A Hold/no-new-order plan does not need a new entry price or upside target.
    # Keep the check strict for actionable Buy/Sell plans and for a missing action.
    requires_execution_levels = (
        trader_action_for_missing_levels is None
        or trader_action_for_missing_levels.group(1).casefold() != "hold"
    )
    if requires_execution_levels and _MISSING_TRADE_LEVEL_RE.search(execution_text):
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

    unit_mismatch_reasons: list[str] = []
    if entry_level is not None and stop_level is not None:
        if min(entry_level, stop_level) > 0 and max(entry_level, stop_level) / min(entry_level, stop_level) >= 20:
            unit_mismatch_reasons.append(
                "Entry and stop-loss values parse to price levels more than 20x apart"
            )

    # Compare execution levels with the reference market price too. This catches
    # reports such as a 55.400 VND price paired with a 51.5 stop-loss, where the
    # formatting likely mixes thousands and decimal notation even if Entry is blank.
    market_reference_price = None
    for price_match in _MARKET_REFERENCE_PRICE_RE.finditer(market):
        market_reference_price = _parse_trade_price_token(price_match.group(1))
        if market_reference_price is not None and market_reference_price > 0:
            break
    if market_reference_price is not None:
        for label, level in parsed_levels.items():
            if level > 0 and max(market_reference_price, level) / min(market_reference_price, level) >= 100:
                unit_mismatch_reasons.append(
                    f"the reported market price and {label} level differ by at least 100x"
                )
                break

    if unit_mismatch_reasons:
        findings.append({
            "severity": "HIGH",
            "code": "TRADE_LEVEL_UNIT_MISMATCH",
            "finding": (
                "; ".join(unit_mismatch_reasons)
                + ". This often indicates inconsistent thousands/decimal notation or units; "
                "normalize all stock prices before using the plan."
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

    # A market analyst and the trader can disagree; expose direct Buy-vs-Underweight
    # contradictions rather than letting the portfolio manager's final label hide them.
    market_rating_match = _RATING_RE.search(market)
    if trader_action_match and market_rating_match:
        trader_direction = _direction(trader_action_match.group(1))
        market_direction = _direction(market_rating_match.group(1))
        if trader_direction != 0 and market_direction != 0 and trader_direction != market_direction:
            findings.append({
                "severity": "HIGH",
                "code": "MARKET_TRADER_DIRECTION_MISMATCH",
                "finding": (
                    f"Market Analyst rating ({market_rating_match.group(1)}) conflicts with "
                    f"Trader action ({trader_action_match.group(1)}). Reconcile the technical view "
                    "and proposed execution before relying on the signal."
                ),
            })

    # Underweight and Sell share a negative direction but are not identical in
    # strength. Flag opposing directional ratings; a neutral label is not a direct opposition.
    if trader_action_match:
        trader_direction = _direction(trader_action_match.group(1))
        if trader_direction != 0:
            for label, match in (
                ("Research Manager", research_rating_match),
                ("Portfolio Manager", final_rating_match),
            ):
                if not match:
                    continue
                other_direction = _direction(match.group(1))
                if other_direction != 0 and other_direction != trader_direction:
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
