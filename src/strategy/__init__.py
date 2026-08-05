"""
TSAR Strategy Module — Trading strategy definitions and evolution.

Components:
  - Base:        Abstract strategy base class
  - Registry:    Strategy registry (active strategies)
  - MeanReversion: Day1 mean reversion strategy
  - Momentum:    Level 2 momentum + funding rates strategy
  - Genome:      Strategy genome encoding (for evolution)
  - BacktestEngine: Historical trade simulation
  - WalkForward: Walk-forward validation
  - MonteCarlo:  Monte Carlo robustness testing
"""

from src.strategy.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestMetrics,
    BacktestResult,
    TradeRecord,
)
from src.strategy.cuopt_optimizer import (
    CuOptStrategyOptimizer,
    OptimizationObjective,
    OptimizationResult,
    ParameterRange,
)
from src.strategy.factor_bench import (
    DecayRow,
    FactorBenchmarker,
    FactorBenchmarkResult,
    FactorScore,
)
from src.strategy.factor_library import (
    FactorLibrary,
    FactorMeta,
    ICRecord,
)
from src.strategy.ml_scorer import MLScorer, ScorerConfig
from src.strategy.monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloSimulator,
    PercentileDistribution,
)
from src.strategy.tsar_strategy.entry_pipeline import EntryPipeline, PipelineResult
from src.strategy.tsar_strategy.fundamental_analyzer import FundamentalAnalyzer, FundamentalBias
from src.strategy.tsar_strategy.level_mapper import LevelMapper, MappedLevels
from src.strategy.tsar_strategy.level_mapper import SRLevel as TSARSRLevel
from src.strategy.tsar_strategy.session_manager import SessionInfo, SessionManager
from src.strategy.tsar_strategy.strategy import TSARStrategy
from src.strategy.tsar_strategy.trend_detector import TrendDetector, TrendState
from src.strategy.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardValidator,
    WindowResult,
)

__all__: list[str] = [
    "MLScorer",
    "ScorerConfig",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestMetrics",
    "BacktestResult",
    "TradeRecord",
    "MonteCarloConfig",
    "MonteCarloResult",
    "MonteCarloSimulator",
    "PercentileDistribution",
    "DecayRow",
    "FactorBenchmarkResult",
    "FactorBenchmarker",
    "FactorLibrary",
    "FactorMeta",
    "FactorScore",
    "ICRecord",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardValidator",
    "WindowResult",
    "CuOptStrategyOptimizer",
    "OptimizationObjective",
    "OptimizationResult",
    "ParameterRange",
    "TSARStrategy",
    "SessionManager",
    "SessionInfo",
    "FundamentalAnalyzer",
    "FundamentalBias",
    "TrendDetector",
    "TrendState",
    "LevelMapper",
    "TSARSRLevel",
    "MappedLevels",
    "EntryPipeline",
    "PipelineResult",
]
