"""Fetch Vnstock VCI quarterly statements and write normalized facts to CSV.

This optional command is intentionally separate from the core install. It sends
read-only market-data requests through the user-installed Vnstock package and
does not use broker credentials or place orders.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.dataflows.vietnam_market.csv_io import (
    CSVDataError,
    write_fundamental_facts_csv,
)
from tradingagents.dataflows.vietnam_market.vnstock_adapter import (
    VnstockNormalizationError,
    normalize_vnstock_vci_statements,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch VCI quarterly income, balance sheet and cash-flow statements "
            "through Vnstock and save normalized fact records to CSV."
        )
    )
    parser.add_argument("--symbol", required=True, help="Vietnam ticker, e.g. FPT or VCB")
    parser.add_argument("--output", required=True, type=Path, help="Destination facts CSV")
    parser.add_argument(
        "--overwrite", action="store_true", help="Explicitly replace an existing output file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        not isinstance(args.symbol, str)
        or not args.symbol.strip().isalnum()
        or not 2 <= len(args.symbol.strip()) <= 12
    ):
        print("ERROR: --symbol must contain 2-12 letters/digits", file=sys.stderr)
        return 2
    if args.output.exists() and not args.overwrite:
        print(
            f"ERROR: output already exists: {args.output}; pass --overwrite to replace it",
            file=sys.stderr,
        )
        return 2

    try:
        from vnstock import Fundamental
    except ImportError:
        print(
            "ERROR: Vnstock v5 is not installed in this Python environment. "
            "Install it from its official package index per the project documentation.",
            file=sys.stderr,
        )
        return 2

    symbol = args.symbol.strip().upper()
    try:
        financials = Fundamental().equity(symbol)
        income = financials.income_statement(
            period="quarter", format="long", source="vci"
        )
        balance = financials.balance_sheet(
            period="quarter", format="long", source="vci"
        )
        cash_flow = financials.cash_flow(
            period="quarter", format="long", source="vci"
        )
        fetched_at = datetime.now(UTC)
        facts = normalize_vnstock_vci_statements(
            symbol, income, balance, cash_flow, fetched_at
        )
        destination = write_fundamental_facts_csv(
            facts, args.output, overwrite=args.overwrite
        )
    except (VnstockNormalizationError, CSVDataError, ValueError, TypeError) as exc:
        print(f"Vnstock normalization/export failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # Vnstock network/provider errors vary by release.
        print(
            f"Vnstock request failed ({type(exc).__name__}). Check network access, "
            "source availability, and your Vnstock installation/entitlement.",
            file=sys.stderr,
        )
        return 1

    supported = sorted({fact.metric for fact in facts})
    periods = sorted({fact.period_end.isoformat() for fact in facts})
    print(f"Vnstock VCI statement export: OK ({len(facts)} facts)")
    print(f"Symbol: {symbol}")
    print(f"Metrics exported: {', '.join(supported)}")
    print(f"Period ends: {', '.join(periods)}")
    print(f"Fetch/availability timestamp: {fetched_at.isoformat()}")
    print(f"Output: {destination}")
    print(
        "NOTICE: available_at is this fetch time, not historical first publication. "
        "Do not use this export as historical point-in-time backtest input."
    )
    print(
        "SCOPE: currently normalizes parent-company net income, total equity and "
        "operating cash flow only. Share counts and capex are intentionally not guessed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
