"""Offline tests for the SSI connectivity smoke command."""

import pytest

from tradingagents.dataflows.vietnam_market.smoke import build_parser, main


def test_smoke_parser_accepts_explicit_date_range():
    args = build_parser().parse_args(
        ["--symbol", "FPT", "--from-date", "2026-10-20", "--to-date", "2026-10-23"]
    )
    assert args.symbol == "FPT"
    assert args.from_date.isoformat() == "2026-10-20"
    assert args.to_date.isoformat() == "2026-10-23"
    assert args.page_size == 100


def test_smoke_parser_rejects_non_iso_date():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["--symbol", "FPT", "--from-date", "20/10/2026", "--to-date", "2026-10-23"]
        )


def test_smoke_rejects_reversed_date_range(capsys):
    result = main(
        ["--symbol", "FPT", "--from-date", "2026-10-24", "--to-date", "2026-10-23"]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert "--from-date must be on or before --to-date" in captured.err


def test_smoke_rejects_invalid_page_size(capsys):
    result = main(
        [
            "--symbol", "FPT",
            "--from-date", "2026-10-20",
            "--to-date", "2026-10-23",
            "--page-size", "1001",
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert "--page-size must be between 1 and 1000" in captured.err
