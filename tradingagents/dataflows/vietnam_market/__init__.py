"""Vietnam-market data contracts, read-only adapters, and offline analytics."""

from tradingagents.dataflows.vietnam_market.backtest import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
    BacktestValidationError,
    EquityPoint,
    TargetExposureSignal,
    run_long_only_backtest,
)
from tradingagents.dataflows.vietnam_market.csv_io import (
    CSVDataError,
    read_fundamental_facts_csv,
    read_market_bars_csv,
)
from tradingagents.dataflows.vietnam_market.fundamentals import (
    AmbiguousFundamentalFactError,
    FundamentalDataValidationError,
    FundamentalFact,
    latest_fundamental_facts_as_of,
)
from tradingagents.dataflows.vietnam_market.models import MarketBar, MarketDataValidationError
from tradingagents.dataflows.vietnam_market.performance import (
    PerformanceSummary,
    summarize_backtest,
)
from tradingagents.dataflows.vietnam_market.ssi import (
    SSIAdapterError,
    SSIMarketDataProvider,
    authenticated_ssi_provider_from_env,
)
from tradingagents.dataflows.vietnam_market.strategies import sma_crossover_signals
from tradingagents.dataflows.vietnam_market.technicals import (
    IndicatorPoint,
    average_true_range,
    exponential_moving_average,
    percentage_returns,
    relative_strength_index,
    simple_moving_average,
)
from tradingagents.dataflows.vietnam_market.valuation import (
    ValuationDataError,
    ValuationMetrics,
    build_valuation_metrics,
)

__all__ = [
    "AmbiguousFundamentalFactError",
    "BacktestConfig",
    "BacktestResult",
    "BacktestTrade",
    "BacktestValidationError",
    "CSVDataError",
    "EquityPoint",
    "FundamentalDataValidationError",
    "FundamentalFact",
    "IndicatorPoint",
    "MarketBar",
    "MarketDataValidationError",
    "PerformanceSummary",
    "SSIAdapterError",
    "SSIMarketDataProvider",
    "TargetExposureSignal",
    "ValuationDataError",
    "ValuationMetrics",
    "authenticated_ssi_provider_from_env",
    "build_valuation_metrics",
    "average_true_range",
    "exponential_moving_average",
    "latest_fundamental_facts_as_of",
    "percentage_returns",
    "read_fundamental_facts_csv",
    "read_market_bars_csv",
    "relative_strength_index",
    "run_long_only_backtest",
    "simple_moving_average",
    "sma_crossover_signals",
    "summarize_backtest",
]
