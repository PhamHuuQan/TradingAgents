from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows.vietnam_market.csv_io import read_market_bars_csv
from tradingagents.dataflows.vietnam_market.export_ssi_bars import (
    ExportDataError,
    main,
    write_market_bars_csv,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _bar(day=23, close="50000", source="ssi-fastconnect-v3"):
    timestamp = datetime(2026, 10, day, 15, 0, tzinfo=VN_TZ)
    return MarketBar(
        symbol="FPT",
        timestamp=timestamp,
        open=Decimal("49000"),
        high=Decimal("51000"),
        low=Decimal("48000"),
        close=Decimal(close),
        volume=1200,
        source=source,
        available_at=datetime(2026, 10, 25, 9, 0, tzinfo=VN_TZ),
    )


@pytest.mark.unit
def test_write_export_roundtrips_normalized_schema_and_provenance(tmp_path):
    target = write_market_bars_csv([_bar(22), _bar(23, "50500")], tmp_path / "bars.csv")

    bars = read_market_bars_csv(target)
    assert [bar.symbol for bar in bars] == ["FPT", "FPT"]
    assert [bar.close for bar in bars] == [Decimal("50000"), Decimal("50500")]
    assert all(bar.source == "ssi-fastconnect-v3" for bar in bars)
    assert all(bar.available_at == datetime(2026, 10, 25, 9, 0, tzinfo=VN_TZ) for bar in bars)


@pytest.mark.unit
def test_export_refuses_to_overwrite_without_explicit_flag(tmp_path):
    target = tmp_path / "bars.csv"
    target.write_text("keep this content", encoding="utf-8")

    with pytest.raises(ExportDataError, match="Pass --overwrite"):
        write_market_bars_csv([_bar()], target)

    assert target.read_text(encoding="utf-8") == "keep this content"


@pytest.mark.unit
def test_export_rejects_mixed_sources_and_unsorted_rows(tmp_path):
    with pytest.raises(ExportDataError, match="one symbol and one source"):
        write_market_bars_csv([_bar(), _bar(24, source="other-feed")], tmp_path / "mixed.csv")
    with pytest.raises(ExportDataError, match="ordered oldest to newest"):
        write_market_bars_csv([_bar(23), _bar(22)], tmp_path / "unsorted.csv")


@pytest.mark.unit
def test_export_cli_uses_read_only_provider_and_stamps_actual_fetch_time(
    tmp_path, monkeypatch, capsys
):
    class FakeProvider:
        def get_daily_bars(
            self, symbol, from_date, to_date, *, available_at_by_date, page_size
        ):
            assert symbol == "FPT"
            assert from_date.isoformat() == "2026-10-22"
            assert to_date.isoformat() == "2026-10-23"
            assert page_size == 1000
            assert set(available_at_by_date) == {
                datetime(2026, 10, 22).date(),
                datetime(2026, 10, 23).date(),
            }
            return [
                MarketBar(
                    symbol="FPT",
                    timestamp=datetime(2026, 10, 23, 15, 0, tzinfo=VN_TZ),
                    open=Decimal("49000"),
                    high=Decimal("51000"),
                    low=Decimal("48000"),
                    close=Decimal("50000"),
                    volume=1200,
                    source="ssi-fastconnect-v3",
                    available_at=available_at_by_date[datetime(2026, 10, 23).date()],
                )
            ]

    fake = FakeProvider()

    @contextmanager
    def fake_context():
        yield fake

    monkeypatch.setattr(
        "tradingagents.dataflows.vietnam_market.export_ssi_bars.authenticated_ssi_provider_from_env",
        fake_context,
    )
    output = tmp_path / "bars.csv"
    result = main([
        "--symbol", "FPT",
        "--from-date", "2026-10-22",
        "--to-date", "2026-10-23",
        "--output", str(output),
    ])

    captured = capsys.readouterr()
    assert result == 0, captured.err
    assert "SSI read-only export: OK (1 bars)" in captured.out
    assert "historical point-in-time" in captured.out
    bars = read_market_bars_csv(output)
    assert len(bars) == 1
    assert bars[0].source == "ssi-fastconnect-v3"
    assert bars[0].available_at >= bars[0].timestamp


@pytest.mark.unit
def test_export_cli_does_not_overwrite_existing_output_without_flag(tmp_path, monkeypatch, capsys):
    output = tmp_path / "bars.csv"
    output.write_text("preserve", encoding="utf-8")
    called = False

    @contextmanager
    def forbidden_provider():
        nonlocal called
        called = True
        yield object()

    monkeypatch.setattr(
        "tradingagents.dataflows.vietnam_market.export_ssi_bars.authenticated_ssi_provider_from_env",
        forbidden_provider,
    )
    result = main([
        "--symbol", "FPT",
        "--from-date", "2026-10-22",
        "--to-date", "2026-10-23",
        "--output", str(output),
    ])

    captured = capsys.readouterr()
    assert result == 2
    assert "already exists" in captured.err
    assert called is False
    assert output.read_text(encoding="utf-8") == "preserve"


@pytest.mark.unit
def test_export_rejects_invalid_range_before_connecting(tmp_path, monkeypatch, capsys):
    called = False

    @contextmanager
    def forbidden_provider():
        nonlocal called
        called = True
        yield object()

    monkeypatch.setattr(
        "tradingagents.dataflows.vietnam_market.export_ssi_bars.authenticated_ssi_provider_from_env",
        forbidden_provider,
    )
    result = main([
        "--symbol", "FPT",
        "--from-date", "2026-10-24",
        "--to-date", "2026-10-23",
        "--output", str(tmp_path / "bars.csv"),
    ])

    captured = capsys.readouterr()
    assert result == 2
    assert "on or before" in captured.err
    assert called is False
