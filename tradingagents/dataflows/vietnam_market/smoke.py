"""Read-only SSI connectivity smoke test for daily Vietnamese-equity OHLCV.

This command validates credentials, SDK access, and response normalization. It is
not a backtest data loader: the only availability time it can prove here is the
time this client fetched the historical response.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone

from tradingagents.dataflows.vietnam_market.ssi import (
    SSIAdapterError,
    authenticated_ssi_provider_from_env,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only SSI FastConnect daily OHLCV connectivity check."
    )
    parser.add_argument("--symbol", required=True, help="Vietnam ticker, e.g. FPT")
    parser.add_argument("--from-date", required=True, type=_date, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", required=True, type=_date, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Maximum rows requested (1-1000; default: 100)",
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

    # This timestamp records when this smoke-test client fetched the data.
    # It is deliberately conservative and must not be treated as historical
    # point-in-time availability for backtesting.
    fetched_at = datetime.now(timezone.utc)
    day_count = (args.to_date - args.from_date).days
    availability = {
        args.from_date + timedelta(days=offset): fetched_at
        for offset in range(day_count + 1)
    }

    try:
        with authenticated_ssi_provider_from_env() as provider:
            bars = provider.get_daily_bars(
                args.symbol,
                args.from_date,
                args.to_date,
                available_at_by_date=availability,
                page_size=args.page_size,
            )
    except (RuntimeError, SSIAdapterError, ValueError, TypeError) as exc:
        print(f"SSI read-only smoke test failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # SDK/network failures may use vendor-specific exception types.
        print(
            f"SSI read-only smoke test failed ({type(exc).__name__}). "
            "Check network access, SSI account entitlements, and current API status.",
            file=sys.stderr,
        )
        return 1

    print(f"SSI read-only connection: OK")
    print(f"Symbol: {args.symbol.strip().upper()}")
    print(f"Requested range: {args.from_date} .. {args.to_date}")
    print(f"Normalized daily bars: {len(bars)}")
    if bars:
        latest = bars[-1]
        print(
            "Latest returned bar: "
            f"{latest.timestamp.date()} O={latest.open} H={latest.high} "
            f"L={latest.low} C={latest.close} V={latest.volume}"
        )
    else:
        print("No bars returned for this symbol/date range.")
    print("NOTICE: fetched-at availability is for connectivity validation only; do not use it as historical PIT data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
