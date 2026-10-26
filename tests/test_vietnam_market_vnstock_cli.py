import sys
from types import SimpleNamespace

import pytest

from tradingagents.dataflows.vietnam_market.fetch_vnstock_facts import main


def _frame(rows, *, symbol="FPT", source="vci"):
    return SimpleNamespace(
        attrs={"symbol": symbol, "source": source, "format": "long"},
        to_dict=lambda orient: rows if orient == "records" else pytest.fail("unexpected orient"),
    )


def _fake_vnstock():
    income = _frame([
        {
            "period": "2025-Q4",
            "id": "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY",
            "unit": "VNĐ",
            "value": 1_250_000_000,
        }
    ])
    balance = _frame([
        {
            "period": "2025-Q4",
            "id": "BS_EQUITY",
            "unit": "VNĐ",
            "value": 200_000_000_000,
        }
    ])
    cash_flow = _frame([
        {
            "period": "2025-Q4",
            "id": "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES",
            "unit": "VNĐ",
            "value": 1_500_000_000,
        }
    ])

    class FakeEquity:
        def income_statement(self, **kwargs):
            assert kwargs == {"period": "quarter", "format": "long", "source": "vci"}
            return income

        def balance_sheet(self, **kwargs):
            assert kwargs == {"period": "quarter", "format": "long", "source": "vci"}
            return balance

        def cash_flow(self, **kwargs):
            assert kwargs == {"period": "quarter", "format": "long", "source": "vci"}
            return cash_flow

    class FakeFundamental:
        def equity(self, symbol):
            assert symbol == "FPT"
            return FakeEquity()

    return SimpleNamespace(Fundamental=FakeFundamental)


@pytest.mark.unit
def test_vnstock_cli_fetches_vci_statements_and_exports_csv(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "vnstock", _fake_vnstock())
    output = tmp_path / "fpt-facts.csv"

    result = main(["--symbol", "fpt", "--output", str(output)])

    captured = capsys.readouterr()
    assert result == 0, captured.err
    assert "Vnstock VCI statement export: OK (3 facts)" in captured.out
    assert "available_at is this fetch time" in captured.out
    assert output.exists()
    raw = output.read_text(encoding="utf-8")
    assert "net_income" in raw
    assert "total_equity" in raw
    assert "operating_cash_flow" in raw
    assert "2025-Q4" not in raw  # CSV stores exact normalized start/end dates.


@pytest.mark.unit
def test_vnstock_cli_refuses_overwrite_before_loading_provider(tmp_path, monkeypatch, capsys):
    output = tmp_path / "facts.csv"
    output.write_text("preserve", encoding="utf-8")
    provider = SimpleNamespace(Fundamental=lambda: pytest.fail("provider must not be loaded"))
    monkeypatch.setitem(sys.modules, "vnstock", provider)

    result = main(["--symbol", "FPT", "--output", str(output)])

    captured = capsys.readouterr()
    assert result == 2
    assert "already exists" in captured.err
    assert output.read_text(encoding="utf-8") == "preserve"


@pytest.mark.unit
def test_vnstock_cli_rejects_export_from_wrong_source_metadata(tmp_path, monkeypatch, capsys):
    wrong = _frame([
        {
            "period": "2025-Q4",
            "id": "BS_EQUITY",
            "unit": "VNĐ",
            "value": 200_000_000_000,
        }
    ], source="kbs")

    class WrongSourceEquity:
        def income_statement(self, **kwargs):
            return wrong

        def balance_sheet(self, **kwargs):
            return wrong

        def cash_flow(self, **kwargs):
            return wrong

    class WrongSourceFundamental:
        def equity(self, symbol):
            return WrongSourceEquity()

    monkeypatch.setitem(
        sys.modules,
        "vnstock",
        SimpleNamespace(Fundamental=WrongSourceFundamental),
    )
    output = tmp_path / "facts.csv"

    result = main(["--symbol", "FPT", "--output", str(output)])

    captured = capsys.readouterr()
    assert result == 1
    assert "source metadata" in captured.err
    assert not output.exists()
