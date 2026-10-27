"""FPT's public investor-relations performance release.

This is a current-date-only summary source, not a replacement for full financial
statements. It intentionally supports FPT only and fails closed if the official
IR page, publication date, or expected metrics cannot be parsed.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from tradingagents.dataflows.date_window import get_current_date, is_historical
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.symbols import normalize_symbol

_IR_HOME = "https://fpt.com/en/ir"
_ALLOWED_HOSTS = {"fpt.com", "www.fpt.com"}
_TIMEOUT_SECONDS = 12
_MAX_RELEASE_AGE_DAYS = 180
_USER_AGENT = "TradingAgents/0.7 (public FPT investor-relations data; contact via project repository)"
_MONTHS_PATTERN = re.compile(
    r"\b(?:(?P<word_months>9)\s*months?\s*(?P<word_year>20\d{2})|"
    r"(?P<short_months>9)M(?P<short_year>20\d{2}))\b",
    re.IGNORECASE,
)
_PUBLISHED_DATE_PATTERN = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>20\d{2})\b")
_METRICS_PATTERN = re.compile(
    r"In the first nine months of (?P<year>20\d{2}), FPT posted revenue of VND\s*"
    r"(?P<revenue>[\d,]+)\s*billion and profit before tax\s*\(PBT\)\s*of VND\s*"
    r"(?P<pbt>[\d,]+)\s*billion, up\s*(?P<revenue_growth>[\d.]+)% and\s*"
    r"(?P<pbt_growth>[\d.]+)% year on year, respectively\.\s*"
    r"Profit after tax attributable to shareholders of the parent company reached VND\s*"
    r"(?P<parent_pat>[\d,]+)\s*billion, increasing\s*(?P<parent_pat_growth>[\d.]+)% "
    r"year on year, while EPS rose\s*(?P<eps_growth>[\d.]+)% to VND\s*"
    r"(?P<eps>[\d,]+)/share",
    re.IGNORECASE,
)


class _AnchorParser(HTMLParser):
    """Collect ordinary page anchors without requiring BeautifulSoup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a" and self._href is None:
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None
            self._text = []


class _VisibleTextParser(HTMLParser):
    """Extract visible text while ignoring script/style/navigation payloads."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _visible_text(document: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(document)
    return " ".join(parser.parts)


def _fetch_html(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise VendorUnavailableError("FPT IR vendor refused a URL outside fpt.com")
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise VendorUnavailableError(f"FPT IR public page could not be retrieved ({type(exc).__name__})") from exc

    final_url = getattr(response, "url", url) or url
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname not in _ALLOWED_HOSTS:
        raise VendorUnavailableError("FPT IR request redirected outside the official fpt.com domain")
    if not isinstance(response.text, str) or not response.text.strip():
        raise VendorUnavailableError("FPT IR public page returned an empty response")
    return response.text


def _period_key(title: str) -> tuple[int, int] | None:
    match = _MONTHS_PATTERN.search(title or "")
    if not match:
        return None
    year = int(match.group("word_year") or match.group("short_year"))
    months = int(match.group("word_months") or match.group("short_months"))
    return year, months


def _find_latest_9m_release(home_html: str) -> tuple[str, str, tuple[int, int]]:
    parser = _AnchorParser()
    parser.feed(home_html)
    candidates = []
    for href, title in parser.anchors:
        lower = title.casefold()
        if "revenue" not in lower or not ("pbt" in lower or "profit before tax" in lower):
            continue
        period = _period_key(title)
        if period is None:
            continue
        url = urljoin(_IR_HOME, href)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
            continue
        candidates.append((period, title, url))

    if not candidates:
        raise VendorUnavailableError(
            "No period-labelled FPT nine-month revenue/PBT release was found on the official IR page"
        )
    period, title, url = max(candidates, key=lambda item: item[0])
    return title, url, period


def _parse_release(
    article_html: str,
    source_url: str,
    retrieved_at: str,
    period: tuple[int, int],
    as_of_date: str | None = None,
) -> str:
    text = _visible_text(article_html)
    published = _PUBLISHED_DATE_PATTERN.search(text)
    if not published:
        raise VendorUnavailableError("FPT IR release did not expose a parseable publication date")
    publication_date = (
        f"{int(published.group('year')):04d}-{int(published.group('month')):02d}-"
        f"{int(published.group('day')):02d}"
    )
    try:
        publication_dt = datetime.strptime(publication_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise VendorUnavailableError("FPT IR release publication date is invalid") from exc
    current_date = get_current_date()
    analysis_cutoff = min(as_of_date or current_date, current_date)
    if publication_date > analysis_cutoff:
        raise VendorUnavailableError("FPT IR release publication date is after the analysis cutoff")
    age_days = (datetime.strptime(analysis_cutoff, "%Y-%m-%d").date() - publication_dt).days
    if age_days > _MAX_RELEASE_AGE_DAYS:
        raise VendorUnavailableError(
            f"FPT IR 9M summary is stale ({age_days} days since publication; "
            f"maximum allowed is {_MAX_RELEASE_AGE_DAYS} days). Do not substitute it for a newer period."
        )

    metrics = _METRICS_PATTERN.search(text)
    if not metrics:
        raise VendorUnavailableError(
            "FPT IR release did not match the expected revenue/PBT/PAT/EPS disclosure format"
        )
    if int(metrics.group("year")) != period[0] or period[1] != 9:
        raise VendorUnavailableError("FPT IR release title and reported financial period do not match")
    if publication_dt.year < period[0]:
        raise VendorUnavailableError("FPT IR release publication predates its reported period")

    g = metrics.group
    return "\n".join([
        f"# FPT Official Investor-Relations Performance Summary — 9M{period[0]}",
        "",
        "- Company: FPT Corporation (HOSE: FPT)",
        f"- Reporting period: nine months ended September 30, {period[0]}",
        f"- Publication date: {publication_date}",
        "- Source: FPT Corporation official Investor Relations news release",
        f"- Retrieved at (UTC): {retrieved_at}",
        f"- Source URL: {source_url}",
        "- Scope: company earnings-performance summary; not a complete financial-statement package.",
        "",
        "| Metric | Reported value | Year-on-year change |",
        "|---|---:|---:|",
        f"| Revenue | VND {g('revenue')} billion | +{g('revenue_growth')}% |",
        f"| Profit before tax (PBT) | VND {g('pbt')} billion | +{g('pbt_growth')}% |",
        f"| Profit after tax attributable to parent shareholders | VND {g('parent_pat')} billion | +{g('parent_pat_growth')}% |",
        f"| Earnings per share (EPS) | VND {g('eps')} per share | +{g('eps_growth')}% |",
        "",
        "### Limitations",
        "",
        "- These figures are taken from the company's published 9M performance summary, not independently audited by this adapter.",
        "- This source does not provide a complete balance sheet, cash-flow statement, full income statement, current valuation multiples, or insider-trading records.",
        "- The official release notes that the group accounts for FPT Telecom using the equity method from 2026 and restates 2025 comparatives on the same basis.",
        "- This current public-release adapter is withheld for historical point-in-time runs; it must not be used to backfill an earlier decision date.",
        "",
    ])


def get_fpt_ir_fundamentals(ticker: str, as_of_date: str | None = None) -> str:
    """Get FPT's official 9M earnings summary as a current-date-only fallback."""
    canonical = normalize_symbol(ticker)
    if canonical.upper() != "FPT":
        raise VendorUnavailableError(
            f"FPT IR source covers FPT only; received {canonical!r}"
        )

    if is_historical(as_of_date):
        return (
            f"# FPT IR fundamentals withheld for historical run: {as_of_date}\n\n"
            "- This adapter discovers the latest public FPT IR earnings release at retrieval time. "
            "It does not reconstruct the exact release set available on a past analysis date. "
            "Using it would risk look-ahead bias; use a point-in-time filings source instead."
        )

    home_html = _fetch_html(_IR_HOME)
    _title, source_url, period = _find_latest_9m_release(home_html)
    article_html = _fetch_html(source_url)
    retrieved_at = datetime.now(UTC).isoformat()
    return _parse_release(article_html, source_url, retrieved_at, period, as_of_date)
