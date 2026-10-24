import json

import pytest

from tradingagents.dataflows.vietnam_market.report import main


@pytest.mark.unit
def test_offline_report_cli_emits_json_and_explicit_missing_metric_warnings(tmp_path, capsys):
    bars = tmp_path / "bars.csv"
    facts = tmp_path / "facts.csv"
    bars.write_text(
        "symbol,timestamp,open,high,low,close,volume,source,available_at\n"
        "FPT,2026-10-23T15:00:00+07:00,49000,51000,48000,50000,1200,ssi-fixture,"
        "2026-10-23T15:05:00+07:00\n",
        encoding="utf-8",
    )
    facts.write_text(
        "symbol,metric,value,unit,period_start,period_end,source,available_at\n"
        "FPT,shares_outstanding,1000000000,shares,2026-01-01,2026-09-30,statements-fixture,"
        "2026-10-20T10:00:00+07:00\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--symbol", "FPT",
            "--as-of", "2026-10-24T09:00:00+07:00",
            "--bars", str(bars),
            "--facts", str(facts),
            "--price-source", "ssi-fixture",
            "--fundamental-source", "statements-fixture",
            "--price-unit", "VND/share",
            "--currency-unit", "VND",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    report = json.loads(captured.out)
    assert report["symbol"] == "FPT"
    assert report["price_source"] == "ssi-fixture"
    assert report["source"] == "statements-fixture"
    assert report["price"] == "50000"
    assert report["market_cap"] == "50000000000000"
    assert report["pe"] is None
    assert any("TTM net income unavailable" in warning for warning in report["warnings"])


@pytest.mark.unit
def test_offline_report_cli_rejects_timezone_naive_as_of(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--symbol", "FPT",
                "--as-of", "2026-10-24T09:00:00",
                "--bars", str(tmp_path / "bars.csv"),
                "--facts", str(tmp_path / "facts.csv"),
                "--price-source", "fixture",
                "--fundamental-source", "fixture",
                "--price-unit", "VND/share",
                "--currency-unit", "VND",
            ]
        )
    assert exc.value.code == 2

@pytest.mark.unit
def test_checked_in_synthetic_example_runs_end_to_end(capsys):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    exit_code = main(
        [
            "--symbol", "FPT",
            "--as-of", "2026-03-01T19:00:00+07:00",
            "--bars", str(root / "examples/vietnam_market/synthetic_demo_bars.csv"),
            "--facts", str(root / "examples/vietnam_market/synthetic_demo_facts.csv"),
            "--price-source", "synthetic-demo-prices",
            "--fundamental-source", "synthetic-demo-statements",
            "--price-unit", "VND/share",
            "--currency-unit", "VND",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    report = json.loads(captured.out)
    assert report["price"] == "50000"
    assert report["ttm_net_income"] == "40000000000"
    assert report["eps"] == "40"
    assert report["pe"] == "1250"
    assert report["pb"] == "250"
    assert report["ttm_operating_cash_flow"] == "48000000000"
    assert report["free_cash_flow"] == "36000000000"
    assert report["warnings"] == []
