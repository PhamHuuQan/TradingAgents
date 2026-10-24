from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradingagents.dataflows.vietnam_market.csv_io import (
    CSVDataError,
    read_fundamental_facts_csv,
    read_market_bars_csv,
)


BAR_HEADER = "symbol,timestamp,open,high,low,close,volume,source,available_at\n"
BAR_ROW = "FPT,2026-10-23T15:00:00+07:00,49000,51000,48000,50000,1200,fixture,2026-10-23T15:05:00+07:00\n"


@pytest.mark.unit
def test_reads_normalized_market_bars_and_preserves_timezone_and_decimal(tmp_path):
    path = tmp_path / "bars.csv"
    path.write_text(BAR_HEADER + BAR_ROW, encoding="utf-8")

    bars = read_market_bars_csv(path)

    assert len(bars) == 1
    assert bars[0].symbol == "FPT"
    assert bars[0].close == Decimal("50000")
    assert bars[0].source == "fixture"
    assert bars[0].timestamp.utcoffset().total_seconds() == 7 * 3600
    assert bars[0].available_at.astimezone(UTC).isoformat() == "2026-10-23T08:05:00+00:00"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("symbol,timestamp,close\nFPT,2026-10-23T15:00:00+07:00,50000\n", "missing required"),
        (BAR_HEADER + BAR_ROW.replace("2026-10-23T15:05:00+07:00", "2026-10-23T15:05:00"), "timezone"),
        (BAR_HEADER + BAR_ROW + BAR_ROW, "duplicate bar revision"),
        (BAR_HEADER.replace("volume", "volumne") + BAR_ROW.replace(",1200,", ",1200,"), "missing required"),
    ],
)
def test_rejects_malformed_market_csv(tmp_path, content, message):
    path = tmp_path / "bad-bars.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(CSVDataError, match=message):
        read_market_bars_csv(path)


@pytest.mark.unit
def test_reads_fundamental_facts_and_optional_provenance(tmp_path):
    path = tmp_path / "facts.csv"
    path.write_text(
        "symbol,metric,value,unit,period_start,period_end,source,available_at,published_at,source_record_id\n"
        "FPT,net_income,1250000000,VND,2026-07-01,2026-09-30,fixture,"
        "2026-10-20T10:00:00+07:00,2026-10-20T09:00:00+07:00,record-17\n",
        encoding="utf-8",
    )

    facts = read_fundamental_facts_csv(path)

    assert len(facts) == 1
    assert facts[0].value == Decimal("1250000000")
    assert facts[0].period_end.isoformat() == "2026-09-30"
    assert facts[0].source_record_id == "record-17"
    assert facts[0].published_at == datetime.fromisoformat("2026-10-20T09:00:00+07:00")


@pytest.mark.unit
def test_rejects_naive_fundamental_availability_timestamp(tmp_path):
    path = tmp_path / "facts.csv"
    path.write_text(
        "symbol,metric,value,unit,period_start,period_end,source,available_at\n"
        "FPT,shares_outstanding,1000,shares,2026-01-01,2026-03-31,fixture,2026-04-20T10:00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(CSVDataError, match="timezone"):
        read_fundamental_facts_csv(path)
