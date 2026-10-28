import copy
from unittest.mock import Mock

import pytest

from tradingagents.dataflows import config as config_module, date_window, router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.vendors import vnstock_fundamentals
from tradingagents.default_config import DEFAULT_CONFIG


def _row(period, item_id, value, unit="VNĐ"):
    return {"period": period, "id": item_id, "level": 1, "unit": unit, "value": value}


class FakeFrame:
    def __init__(self, rows, symbol="FPT", source="vci"):
        self.rows = rows
        self.columns = tuple(rows[0].keys()) if rows else ("period", "id", "level", "unit", "value")
        self.empty = not rows
        self.attrs = {"source": source, "symbol": symbol, "format": "long"}

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows

    def to_csv(self, index=False):
        assert index is False
        import csv
        import io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=self.columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return output.getvalue()


def _frames():
    income = [
        _row("2025-Q1", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 10_000_000_000),
        _row("2025-Q2", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 11_000_000_000),
        _row("2025-Q3", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 12_000_000_000),
        _row("2025-Q4", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", 13_000_000_000),
    ]
    balance = [
        _row("2024-Q4", "BS_EQUITY", 150_000_000_000),
        _row("2025-Q4", "BS_EQUITY", 200_000_000_000),
    ]
    cash_flow = [
        _row("2025-Q1", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 12_000_000_000),
        _row("2025-Q2", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 13_000_000_000),
        _row("2025-Q3", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 14_000_000_000),
        _row("2025-Q4", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", 15_000_000_000),
    ]
    return FakeFrame(income), FakeFrame(balance), FakeFrame(cash_flow)


class FakeClient:
    def __init__(self):
        self.income_frame, self.balance_frame, self.cash_flow_frame = _frames()
        income, balance, cash_flow = _frames()
        self.kbs_income_frame = FakeFrame(income.rows, source="kbs")
        self.kbs_balance_frame = FakeFrame(balance.rows, source="kbs")
        self.kbs_cash_flow_frame = FakeFrame(cash_flow.rows, source="kbs")
        self.failed_sources = set()
        self.failed_requests = set()
        self.calls = []

    def _fetch(self, name, period, format, source, vci_frame, kbs_frame):
        self.calls.append((name, period, format, source))
        if source in self.failed_sources or (source, name) in self.failed_requests:
            raise RuntimeError(f"simulated {source.upper()} {name} outage")
        return vci_frame if source == "vci" else kbs_frame

    def income_statement(self, *, period, format, source):
        return self._fetch(
            "income_statement", period, format, source,
            self.income_frame, self.kbs_income_frame,
        )

    def balance_sheet(self, *, period, format, source):
        return self._fetch(
            "balance_sheet", period, format, source,
            self.balance_frame, self.kbs_balance_frame,
        )

    def cash_flow(self, *, period, format, source):
        return self._fetch(
            "cash_flow", period, format, source,
            self.cash_flow_frame, self.kbs_cash_flow_frame,
        )


@pytest.fixture
def fake_vnstock(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(vnstock_fundamentals, "_fundamental_client", lambda symbol: client)
    # Freeze both references: the adapter imports get_current_date directly,
    # while withhold_undated_statements resolves it through date_window at call time.
    # Keep the explicit as-of date equal to simulated today so these tests exercise
    # the source adapters rather than the historical-data safety guard.
    monkeypatch.setattr(vnstock_fundamentals, "get_current_date", lambda: "2026-10-25")
    monkeypatch.setattr(date_window, "get_current_date", lambda: "2026-10-25")
    return client


@pytest.mark.unit
def test_vnstock_statement_route_returns_validated_long_csv(fake_vnstock):
    output = vnstock_fundamentals.get_vnstock_income_statement(
        "fpt", "quarterly", "2026-10-25"
    )
    assert "# Income Statement for FPT from Vnstock VCI" in output
    assert "historical first-publication time" in output
    assert "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY" in output
    assert fake_vnstock.calls == [("income_statement", "quarter", "long", "vci")]


@pytest.mark.unit
def test_vnstock_statement_falls_back_to_kbs_and_labels_the_actual_source(fake_vnstock):
    fake_vnstock.failed_sources.add("vci")

    output = vnstock_fundamentals.get_vnstock_balance_sheet(
        "FPT", "quarterly", "2026-10-25"
    )

    assert "# Balance Sheet for FPT from Vnstock KBS" in output
    assert "# Provider source: vnstock-kbs;" in output
    assert [call[3] for call in fake_vnstock.calls] == ["vci", "kbs"]
    assert all(call[2] == "long" for call in fake_vnstock.calls)


@pytest.mark.unit
def test_vnstock_kbs_frame_with_wrong_source_metadata_is_rejected(fake_vnstock):
    fake_vnstock.failed_sources.add("vci")
    # Simulate the KBS request unexpectedly returning a VCI-tagged frame.
    fake_vnstock.kbs_balance_frame = FakeFrame(
        fake_vnstock.kbs_balance_frame.rows, source="vci"
    )

    with pytest.raises(VendorUnavailableError, match="expected 'kbs'"):
        vnstock_fundamentals.get_vnstock_balance_sheet(
            "FPT", "quarterly", "2026-10-25"
        )


@pytest.mark.unit
def test_vnstock_fundamentals_summary_falls_back_as_a_complete_kbs_set(fake_vnstock):
    fake_vnstock.failed_sources.add("vci")

    output = vnstock_fundamentals.get_vnstock_fundamentals("FPT", "2026-10-25")

    assert "# Current KBS fundamentals for FPT" in output
    assert "- Source: vnstock-kbs" in output
    assert "Source fallback: VCI unavailable; selected KBS." in output
    assert "TTM net income: not derived from KBS" in output
    assert "TTM operating cash flow: not derived from KBS" in output
    assert "Latest total equity: 200,000,000,000 VND" in output
    assert [call[3] for call in fake_vnstock.calls] == [
        "vci", "kbs", "kbs", "kbs"
    ]


@pytest.mark.unit
def test_vnstock_summary_never_mixes_partial_vci_with_kbs_statements(fake_vnstock):
    # VCI returns the income statement but fails on the balance sheet. The full
    # three-statement set must be retried with KBS rather than mixing providers.
    fake_vnstock.failed_requests.add(("vci", "balance_sheet"))

    output = vnstock_fundamentals.get_vnstock_fundamentals("FPT", "2026-10-25")

    assert "# Current KBS fundamentals for FPT" in output
    assert "- Source: vnstock-kbs" in output
    assert [call[3] for call in fake_vnstock.calls] == [
        "vci", "vci", "kbs", "kbs", "kbs"
    ]


@pytest.mark.unit
def test_vnstock_source_chain_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_VNSTOCK_FUNDAMENTALS_SOURCES", "vci,unknown")

    with pytest.raises(vnstock_fundamentals.VendorNotConfiguredError, match="only accepts"):
        vnstock_fundamentals._configured_sources()


@pytest.mark.unit
def test_vnstock_statement_withholds_historical_request_before_loading_client(monkeypatch):
    client = Mock()
    loader = Mock(return_value=client)
    monkeypatch.setattr(vnstock_fundamentals, "_fundamental_client", loader)
    monkeypatch.setattr(vnstock_fundamentals, "get_current_date", lambda: "2026-10-25")
    monkeypatch.setattr(date_window, "get_current_date", lambda: "2026-10-25")

    output = vnstock_fundamentals.get_vnstock_income_statement(
        "FPT", "quarterly", "2026-10-01"
    )

    assert "withheld" in output.lower() or "point-in-time" in output.lower()
    loader.assert_not_called()


@pytest.mark.unit
def test_vnstock_fundamentals_summary_only_derives_complete_ttm_flows(fake_vnstock):
    output = vnstock_fundamentals.get_vnstock_fundamentals("FPT", "2026-10-25")
    assert "TTM parent-company net income: 46,000,000,000 VND" in output
    assert "TTM operating cash flow: 54,000,000,000 VND" in output
    assert "Latest total equity: 200,000,000,000 VND" in output
    assert "does not currently validate shares outstanding" in output
    assert all(call[2:] == ("long", "vci") for call in fake_vnstock.calls)


@pytest.mark.unit
def test_vnstock_rejects_wrong_source_metadata():
    client = FakeClient()
    client.income_frame = FakeFrame(client.income_frame.rows, source="kbs")
    with pytest.raises(VendorUnavailableError, match="expected 'vci'"):
        vnstock_fundamentals._validate_frame(client.income_frame, "FPT", "income_statement")


@pytest.mark.unit
def test_vnstock_router_is_explicit_only_in_default_chain(monkeypatch):
    monkeypatch.setattr(config_module, "_config", copy.deepcopy(DEFAULT_CONFIG))
    set_config({"data_vendors": {"fundamental_data": "default"}})
    unavailable = Mock(side_effect=NoMarketDataError("FPT", "FPT", "no VCI rows"))
    vnstock = Mock(return_value="SHOULD_NOT_BE_CALLED")
    monkeypatch.setitem(
        router.VENDOR_METHODS,
        "get_fundamentals",
        {"yfinance": unavailable, "vnstock": vnstock},
    )

    result = router.route_to_vendor("get_fundamentals", "FPT", "2026-10-25")

    assert result.startswith("NO_DATA_AVAILABLE")
    vnstock.assert_not_called()

@pytest.mark.unit
@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"source": "kbs", "symbol": "FPT", "format": "long"}, "expected 'vci'"),
        ({"source": "vci", "symbol": "VCB", "format": "long"}, "metadata ticker"),
        ({"source": "vci", "symbol": "FPT", "format": "wide"}, "metadata format"),
    ],
)
def test_vnstock_rejects_conflicting_response_metadata(metadata, message):
    client = FakeClient()
    client.income_frame.attrs = metadata

    with pytest.raises(VendorUnavailableError, match=message):
        vnstock_fundamentals._validate_frame(client.income_frame, "FPT", "income_statement")


@pytest.mark.unit
def test_vnstock_accepts_explicit_source_when_provider_omits_optional_attrs():
    client = FakeClient()
    # The VCI provider may expose no attrs; the request explicitly selects VCI
    # and the long-form data contract is independently checked by required columns.
    client.income_frame.attrs = {}
    vnstock_fundamentals._validate_frame(client.income_frame, "FPT", "income_statement", "vci")

    # KBS reports source/ticker but may omit format. Existing metadata must match,
    # while long-form columns establish the returned shape.
    client.kbs_balance_frame.attrs = {
        "source": "KBS",
        "symbol": "FPT",
        "report_type": "balance_sheet",
        "period": "quarter",
    }
    vnstock_fundamentals._validate_frame(
        client.kbs_balance_frame, "FPT", "balance_sheet", "kbs"
    )
