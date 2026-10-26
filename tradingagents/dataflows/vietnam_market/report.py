"""Offline CLI for a point-in-time valuation snapshot from normalized CSV files."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from tradingagents.dataflows.vietnam_market.csv_io import (
    CSVDataError,
    read_fundamental_facts_csv,
    read_market_bars_csv,
)
from tradingagents.dataflows.vietnam_market.valuation import (
    ValuationDataError,
    build_valuation_metrics,
)


def _as_of(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; a timezone offset is mandatory."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "as-of must be an ISO-8601 datetime, e.g. 2026-10-23T16:00:00+07:00"
        ) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "as-of must include a timezone offset (for example +07:00 or Z)"
        )
    return result


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__} to JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an offline point-in-time valuation snapshot from normalized "
            "market-bar and fundamental-fact CSV files. No network access is used."
        )
    )
    parser.add_argument("--symbol", required=True, help="Ticker, e.g. FPT")
    parser.add_argument(
        "--as-of",
        required=True,
        type=_as_of,
        help="Decision timestamp in ISO-8601 format with timezone",
    )
    parser.add_argument("--bars", required=True, type=Path, help="Normalized OHLCV CSV")
    parser.add_argument("--facts", required=True, type=Path, help="Normalized fundamental facts CSV")
    parser.add_argument(
        "--price-source", required=True,
        help="Exact MarketBar.source to use; never inferred from the fundamentals source",
    )
    parser.add_argument(
        "--fundamental-source", required=True,
        help="Exact FundamentalFact.source to use for every valuation input",
    )
    parser.add_argument(
        "--price-unit", required=True, help="Price unit, e.g. VND/share or USD/share"
    )
    parser.add_argument(
        "--currency-unit", required=True, help="Currency unit of financial facts, e.g. VND or USD"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bars = read_market_bars_csv(args.bars)
        facts = read_fundamental_facts_csv(args.facts)
        metrics = build_valuation_metrics(
            args.symbol,
            bars,
            facts,
            args.as_of,
            price_source=args.price_source,
            source=args.fundamental_source,
            price_unit=args.price_unit,
            currency_unit=args.currency_unit,
        )
    except (CSVDataError, ValuationDataError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: cannot access input file: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(metrics), default=_json_default, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
