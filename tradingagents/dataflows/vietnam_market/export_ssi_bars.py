"""Export read-only SSI daily OHLCV to the normalized CSV contract.

Availability is stamped at the actual fetch time. The resulting file can be
used for current/as-fetched research, but it cannot reconstruct historical
point-in-time availability and must not be used for historical PIT backtests.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.dataflows.vietnam_market.csv_io import read_market_bars_csv
from tradingagents.dataflows.vietnam_market.models import MarketBar
from tradingagents.dataflows.vietnam_market.smoke import _date
from tradingagents.dataflows.vietnam_market.ssi import (
    SSIAdapterError,
    authenticated_ssi_provider_from_env,
)

_MARKET_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_COLUMNS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "available_at",
)


class ExportDataError(ValueError):
    """Raised when SSI export output cannot be written safely."""


def write_market_bars_csv(
    bars: list[MarketBar], path: str | Path, *, overwrite: bool = False
) -> Path:
    """Atomically write validated normalized daily bars as CSV."""
    if not bars:
        raise ExportDataError("Refusing to write an empty SSI bar export")
    symbol = bars[0].symbol
    source = bars[0].source
    previous_timestamp = None
    seen: set[datetime] = set()
    for index, bar in enumerate(bars):
        if not isinstance(bar, MarketBar):
            raise TypeError(f"bars[{index}] must be a MarketBar")
        if bar.symbol != symbol or bar.source != source:
            raise ExportDataError("one export file must contain one symbol and one source")
        if bar.timestamp in seen:
            raise ExportDataError(f"duplicate bar timestamp: {bar.timestamp.isoformat()}")
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise ExportDataError("bars must be ordered oldest to newest")
        seen.add(bar.timestamp)
        previous_timestamp = bar.timestamp

    destination = Path(path)
    if destination.exists() and not overwrite:
        raise ExportDataError(
            f"Output already exists: {destination}. Pass --overwrite to replace it."
        )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_COLUMNS)
            for bar in bars:
                writer.writerow(
                    (
                        bar.symbol,
                        bar.timestamp.isoformat(),
                        str(bar.open),
                        str(bar.high),
                        str(bar.low),
                        str(bar.close),
                        bar.volume,
                        bar.source,
                        bar.available_at.isoformat(),
                    )
                )
        if destination.exists() and not overwrite:
            os.unlink(temporary_name)
            raise ExportDataError(
                f"Output appeared during export: {destination}. Nothing was replaced."
            )
        os.replace(temporary_name, destination)
    except (OSError, csv.Error) as exc:
        try:
            if "temporary_name" in locals() and os.path.exists(temporary_name):
                os.unlink(temporary_name)
        except OSError:
            pass
        raise ExportDataError(f"Could not write export to {destination}: {exc}") from exc

    # Read the file back through the strict schema reader before reporting success.
    validated = read_market_bars_csv(destination)
    if len(validated) != len(bars):
        raise ExportDataError("Post-write validation returned a different row count")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch SSI daily OHLCV (read-only) and export normalized CSV. "
            "Availability is fetch-time, not historical first-available time."
        )
    )
    parser.add_argument("--symbol", required=True, help="Vietnam ticker, e.g. FPT")
    parser.add_argument("--from-date", required=True, type=_date, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", required=True, type=_date, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", required=True, type=Path, help="Destination CSV path")
    parser.add_argument(
        "--page-size", type=int, default=1000, help="Maximum rows requested (1-1000)"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Explicitly replace an existing output file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_date > args.to_date:
        print("ERROR: --from-date must be on or before --to-date", file=sys.stderr)
        return 2
    if not 1 <= args.page_size <= 1000:
        print("ERROR: --page-size must be between 1 and 1000", file=sys.stderr)
        return 2
    if not isinstance(args.symbol, str) or not args.symbol.strip().isalnum() or not 2 <= len(args.symbol.strip()) <= 12:
        print("ERROR: --symbol must contain 2-12 letters/digits", file=sys.stderr)
        return 2
    if args.output.exists() and not args.overwrite:
        print(
            f"ERROR: output already exists: {args.output}; pass --overwrite to replace it",
            file=sys.stderr,
        )
        return 2

    # Use actual fetch time as availability, so as-of backtests before this fetch
    # will exclude the bars rather than pretending their first publication time
    # is known. A partially formed current-day bar is rejected by the SSI adapter.
    fetched_at = datetime.now(_MARKET_TZ)
    availability = {
        args.from_date.toordinal() + offset: fetched_at
        for offset in range((args.to_date - args.from_date).days + 1)
    }
    availability_by_date = {
        date.fromordinal(ordinal): timestamp
        for ordinal, timestamp in availability.items()
    }

    try:
        with authenticated_ssi_provider_from_env() as provider:
            bars = provider.get_daily_bars(
                args.symbol,
                args.from_date,
                args.to_date,
                available_at_by_date=availability_by_date,
                page_size=args.page_size,
            )
        destination = write_market_bars_csv(bars, args.output, overwrite=args.overwrite)
    except (RuntimeError, SSIAdapterError, ExportDataError, ValueError, TypeError) as exc:
        print(f"SSI CSV export failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # SDK/network exceptions are implementation-specific.
        print(
            f"SSI CSV export failed ({type(exc).__name__}). "
            "Check network access, SSI Market Data entitlement, and API status.",
            file=sys.stderr,
        )
        return 1

    print(f"SSI read-only export: OK ({len(bars)} bars)")
    print(f"Symbol: {args.symbol.strip().upper()}")
    print(f"Range: {args.from_date} .. {args.to_date}")
    print(f"Output: {destination}")
    print(f"Source: {bars[0].source}")
    print(f"Fetch/availability timestamp: {fetched_at.isoformat()}")
    if len(bars) == args.page_size:
        print("WARNING: row count reached --page-size; the requested range may be truncated.")
    print(
        "NOTICE: availability records this export time only. Do not use this file "
        "as historical point-in-time backtest input."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
