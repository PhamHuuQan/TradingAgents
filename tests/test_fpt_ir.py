from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradingagents.dataflows import date_window, router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors import fpt_ir


_HOME = """
<!doctype html><html><body>
<a href="/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0">
FPT's 9 months 2026 revenue and PBT increase 12.4% and 17.0%
</a>
<a href="/en/news/another-unrelated-story">Another FPT story</a>
</body></html>
"""

_ARTICLE = """
<!doctype html><html><body>
<time>10/21/2026</time>
<p>In the first nine months of 2026, FPT posted revenue of VND 40,023 billion
and profit before tax (PBT) of VND 8,770 billion, up 12.4% and 17.0% year
on year, respectively. Profit after tax attributable to shareholders of
the parent company reached VND 7,778 billion, increasing 13.3% year on
year, while EPS rose 12.8% to VND 4,142/share.</p>
<p>From 2026, the Group will account for FPT Telecom using the equity method.</p>
</body></html>
"""


class FakeResponse:
    def __init__(self, url: str, text: str, status_code: int = 200):
        self.url = url
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fpt_ir.requests.HTTPError(f"HTTP {self.status_code}")


def _mock_pages(monkeypatch, article=_ARTICLE):
    def fake_get(url, **kwargs):
        assert kwargs.get("timeout") == fpt_ir._TIMEOUT_SECONDS
        if url == fpt_ir._IR_HOME:
            return FakeResponse(url, _HOME)
        if url == "https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0":
            return FakeResponse(url, article)
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setattr(fpt_ir.requests, "get", fake_get)
    monkeypatch.setattr(date_window, "get_current_date", lambda: "2026-10-27")
    monkeypatch.setattr(fpt_ir, "get_current_date", lambda: "2026-10-27")


@pytest.mark.unit
def test_official_9m_summary_contains_values_period_and_provenance(monkeypatch):
    _mock_pages(monkeypatch)

    out = fpt_ir.get_fpt_ir_fundamentals("FPT", "2026-10-27")

    assert "Official Investor-Relations Performance Summary" in out
    assert "Reporting period: nine months ended September 30, 2026" in out
    assert "Publication date: 2026-10-21" in out
    assert "VND 40,023 billion" in out
    assert "VND 8,770 billion" in out
    assert "VND 7,778 billion" in out
    assert "VND 4,142 per share" in out
    assert "Source URL: https://fpt.com/en/news/fpt-s-9-months-2026-revenue-and-pbt-increase-12-4-and-17-0" in out
    assert "not a complete financial-statement package" in out
    assert "Retrieved at (UTC):" in out


@pytest.mark.unit
def test_only_fpt_is_supported_and_no_request_is_made_for_other_tickers(monkeypatch):
    get = Mock()
    monkeypatch.setattr(fpt_ir.requests, "get", get)

    with pytest.raises(VendorUnavailableError, match="covers FPT only"):
        fpt_ir.get_fpt_ir_fundamentals("VIC", "2026-10-27")

    get.assert_not_called()


@pytest.mark.unit
def test_historical_run_is_withheld_before_fetching_current_ir_summary(monkeypatch):
    _mock_pages(monkeypatch)
    get = Mock(side_effect=AssertionError("historical run must not fetch live IR page"))
    monkeypatch.setattr(fpt_ir.requests, "get", get)

    out = fpt_ir.get_fpt_ir_fundamentals("FPT", "2026-10-20")

    assert "withheld" in out.lower()
    get.assert_not_called()


@pytest.mark.unit
def test_publication_after_analysis_date_is_rejected(monkeypatch):
    future_article = _ARTICLE.replace("10/21/2026", "10/28/2026")
    _mock_pages(monkeypatch, article=future_article)

    with pytest.raises(VendorUnavailableError, match="after the current date"):
        fpt_ir.get_fpt_ir_fundamentals("FPT", "2026-10-27")


@pytest.mark.unit
def test_unrecognized_article_format_fails_closed(monkeypatch):
    _mock_pages(monkeypatch, article="<html><body><p>FPT released new information.</p></body></html>")

    with pytest.raises(VendorUnavailableError, match="publication date"):
        fpt_ir.get_fpt_ir_fundamentals("FPT", "2026-10-27")


@pytest.mark.unit
def test_router_registers_fpt_ir_as_explicit_only_fundamentals_fallback(monkeypatch):
    assert router.VENDOR_METHODS["get_fundamentals"]["fpt_ir"] is fpt_ir.get_fpt_ir_fundamentals
    assert "fpt_ir" in router.EXPLICIT_ONLY_VENDORS

    _mock_pages(monkeypatch)
    # The caller chooses this issuer-specific endpoint intentionally.
    set_config({"data_vendors": {"fundamental_data": "fpt_ir"}})
    out = router.route_to_vendor("get_fundamentals", "FPT", "2026-10-27")

    assert "VND 40,023 billion" in out
    assert "Source URL:" in out
