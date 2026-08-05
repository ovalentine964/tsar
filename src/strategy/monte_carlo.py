"""
Monte Carlo Simulator — Statistical robustness testing for backtest results.

Takes completed trade results and runs N random permutations of trade order
to compute confidence intervals for key metrics. This reveals whether
a strategy's performance is sensitive to the specific sequence of trades.

Usage::

    from src.strategy.monte_carlo import MonteCarloSimulator, MonteCarloConfig

    simulator = MonteCarloSimulator(config=MonteCarloConfig(n_simulations=1000))
    result = simulator.run(backtest_result)
    print(result.confidence_intervals["sharpe_ratio"])
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.strategy.backtest_engine import BacktestResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MonteCarloConfig:
    """Configuration for Monte Carlo simulation.

    Attributes:
        n_simulations: Number of random permutations to run.
        confidence_levels: Percentile levels for confidence intervals
            (e.g. [5, 25, 50, 75, 95]).
        random_seed: Seed for reproducibility. None for non-deterministic.
        initial_capital: Starting capital for each simulation.
        risk_free_rate: Annualized risk-free rate for Sharpe computation.
        trading_days_per_year: Trading days per year for annualization.
    """

    n_simulations: int = 1000
    confidence_levels: tuple[float, ...] = (5.0, 25.0, 50.0, 75.0, 95.0)
    random_seed: int | None = None
    initial_capital: float = 100_000.0
    risk_free_rate: float = 0.04
    trading_days_per_year: int = 365


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PercentileDistribution:
    """Percentile distribution for a single metric.

    Attributes:
        metric_name: Name of the metric.
        percentiles: Mapping of percentile level to value.
        mean: Mean value across all simulations.
        std: Standard deviation across all simulations.
        min_val: Minimum observed value.
        max_val: Maximum observed value.
        original: The original (non-permuted) backtest value.
    """

    metric_name: str
    percentiles: dict[float, float]
    mean: float
    std: float
    min_val: float
    max_val: float
    original: float


@dataclass(frozen=True)
class MonteCarloResult:
    """Complete Monte Carlo simulation result.

    Attributes:
        distributions: Per-metric percentile distributions.
        confidence_intervals: Dict mapping metric name to percentile dict.
        n_simulations: Number of simulations run.
        n_trades: Number of trades per simulation.
        original_result: The original backtest result.
        probability_of_profit: Fraction of simulations with positive return.
        probability_of_ruin: Fraction of simulations that went below 50% of capital.
    """

    distributions: dict[str, PercentileDistribution]
    confidence_intervals: dict[str, dict[float, float]]
    n_simulations: int
    n_trades: int
    original_result: BacktestResult
    probability_of_profit: float
    probability_of_ruin: float


# ═══════════════════════════════════════════════════════════════════════
# MONTE CARLO SIMULATOR
# ═══════════════════════════════════════════════════════════════════════


class MonteCarloSimulator:
    """Runs Monte Carlo simulations by randomly permuting trade order.

    Takes the completed trades from a backtest and shuffles their order
    N times to generate a distribution of possible outcomes. This reveals
    path dependency: if the strategy's edge is real, performance should
    be robust across different trade orderings.

    Args:
        config: Monte Carlo configuration.
    """

    def __init__(self, config: MonteCarloConfig | None = None) -> None:
        self._config = config or MonteCarloConfig()

    def run(self, backtest_result: BacktestResult) -> MonteCarloResult:
        """Run Monte Carlo simulation on backtest trade results.

        Args:
            backtest_result: A completed backtest with trades.

        Returns:
            MonteCarloResult with distributions and confidence intervals.

        Raises:
            ValueError: If backtest has no trades.
        """
        trades = list(backtest_result.trades)
        if not trades:
            raise ValueError("Cannot run Monte Carlo on backtest with no trades")

        config = self._config
        rng = np.random.default_rng(config.random_seed)
        n_sims = config.n_simulations

        # Extract trade PnL percentages (the shuffled variable)
        pnl_pcts = np.array([t.pnl_pct for t in trades], dtype=float)

        # Collect simulation results
        sim_total_returns = np.zeros(n_sims)
        sim_sharpes = np.zeros(n_sims)
        sim_max_drawdowns = np.zeros(n_sims)
        sim_win_rates = np.zeros(n_sims)
        sim_profit_factors = np.zeros(n_sims)
        sim_calmar_ratios = np.zeros(n_sims)

        for i in range(n_sims):
            # Shuffle trade order
            shuffled_idx = rng.permutation(len(pnl_pcts))
            shuffled_pnl_pcts = pnl_pcts[shuffled_idx]

            # Simulate equity curve from shuffled trades
            equity = self._simulate_equity_curve(shuffled_pnl_pcts)

            # Compute metrics for this simulation
            sim_total_returns[i] = (equity[-1] - config.initial_capital) / config.initial_capital
            sim_sharpes[i] = self._compute_sharpe(equity)
            sim_max_drawdowns[i] = self._compute_max_drawdown(equity)
            sim_win_rates[i] = float(np.mean(shuffled_pnl_pcts > 0))
            sim_profit_factors[i] = self._compute_profit_factor(shuffled_pnl_pcts)
            sim_calmar_ratios[i] = self._compute_calmar(equity, sim_max_drawdowns[i])

        # Build distributions
        metrics_data = {
            "total_return": (sim_total_returns, backtest_result.metrics.total_return),
            "sharpe_ratio": (sim_sharpes, backtest_result.metrics.sharpe_ratio),
            "max_drawdown": (sim_max_drawdowns, backtest_result.metrics.max_drawdown),
            "win_rate": (sim_win_rates, backtest_result.metrics.win_rate),
            "profit_factor": (sim_profit_factors, backtest_result.metrics.profit_factor),
            "calmar_ratio": (sim_calmar_ratios, backtest_result.metrics.calmar_ratio),
        }

        distributions: dict[str, PercentileDistribution] = {}
        confidence_intervals: dict[str, dict[float, float]] = {}

        for metric_name, (values, original) in metrics_data.items():
            # Filter out inf/nan for stats
            finite_values = values[np.isfinite(values)]

            if len(finite_values) == 0:
                # All values were inf/nan — use fallback
                percentiles = {p: 0.0 for p in config.confidence_levels}
                distributions[metric_name] = PercentileDistribution(
                    metric_name=metric_name,
                    percentiles=percentiles,
                    mean=0.0,
                    std=0.0,
                    min_val=0.0,
                    max_val=0.0,
                    original=round(original, 6),
                )
                confidence_intervals[metric_name] = percentiles
                continue

            percentiles = {}
            for p in config.confidence_levels:
                percentiles[p] = round(float(np.percentile(finite_values, p)), 6)

            distributions[metric_name] = PercentileDistribution(
                metric_name=metric_name,
                percentiles=percentiles,
                mean=round(float(np.mean(finite_values)), 6),
                std=round(
                    float(np.std(finite_values, ddof=1)) if len(finite_values) > 1 else 0.0, 6
                ),
                min_val=round(float(np.min(finite_values)), 6),
                max_val=round(float(np.max(finite_values)), 6),
                original=round(original, 6),
            )
            confidence_intervals[metric_name] = percentiles

        # Probability of profit / ruin
        prob_profit = float(np.mean(sim_total_returns > 0))
        ruin_threshold = config.initial_capital * 0.5
        # Simulate which runs ended below ruin threshold
        prob_ruin = float(
            np.mean(config.initial_capital * (1 + sim_total_returns) < ruin_threshold)
        )

        logger.info(
            f"Monte Carlo complete: {n_sims} simulations, "
            f"P(profit)={prob_profit:.2%}, P(ruin)={prob_ruin:.2%}"
        )

        return MonteCarloResult(
            distributions=distributions,
            confidence_intervals=confidence_intervals,
            n_simulations=n_sims,
            n_trades=len(trades),
            original_result=backtest_result,
            probability_of_profit=round(prob_profit, 4),
            probability_of_ruin=round(prob_ruin, 4),
        )

    # ── Simulation helpers ───────────────────────────────────

    def _simulate_equity_curve(self, pnl_pcts: np.ndarray) -> np.ndarray:
        """Simulate an equity curve from shuffled trade PnL percentages.

        Args:
            pnl_pcts: Array of per-trade return fractions.

        Returns:
            Array of equity values (length = len(pnl_pcts) + 1).
        """
        capital = self._config.initial_capital
        equity = np.zeros(len(pnl_pcts) + 1)
        equity[0] = capital

        for i, ret in enumerate(pnl_pcts):
            capital *= 1 + ret
            equity[i + 1] = capital

        return equity

    def _compute_sharpe(self, equity: np.ndarray) -> float:
        """Compute annualized Sharpe ratio from an equity curve."""
        if len(equity) < 3:
            return 0.0

        returns = np.diff(equity) / equity[:-1]
        returns = returns[np.isfinite(returns)]

        if len(returns) < 2 or np.std(returns) == 0:
            return 0.0

        daily_rf = self._config.risk_free_rate / self._config.trading_days_per_year
        excess = returns - daily_rf
        std = float(np.std(excess, ddof=1))
        if std == 0:
            return 0.0

        return float(np.mean(excess) / std * math.sqrt(self._config.trading_days_per_year))

    @staticmethod
    def _compute_max_drawdown(equity: np.ndarray) -> float:
        """Compute maximum drawdown from an equity curve."""
        if len(equity) < 2:
            return 0.0

        peak = equity[0]
        max_dd = 0.0

        for val in equity:
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    @staticmethod
    def _compute_profit_factor(pnl_pcts: np.ndarray) -> float:
        """Compute profit factor from trade PnL percentages."""
        winners = pnl_pcts[pnl_pcts > 0]
        losers = pnl_pcts[pnl_pcts <= 0]

        gross_profit = float(np.sum(winners)) if len(winners) > 0 else 0.0
        gross_loss = float(np.abs(np.sum(losers))) if len(losers) > 0 else 0.0

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def _compute_calmar(self, equity: np.ndarray, max_dd: float) -> float:
        """Compute Calmar ratio (CAGR / max drawdown)."""
        if max_dd == 0:
            return float("inf") if equity[-1] > equity[0] else 0.0

        n_bars = len(equity) - 1
        if n_bars <= 0 or equity[0] <= 0:
            return 0.0

        years = n_bars / self._config.trading_days_per_year
        if years <= 0:
            return 0.0

        cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
        return cagr / max_dd
