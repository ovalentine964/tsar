"""TSAR — cuFOLIO GPU-Accelerated Portfolio Optimization Backend.

Provides GPU-accelerated portfolio optimization using NVIDIA cuFOLIO:
- Mean-CVaR portfolio optimization
- Efficient frontier generation
- Scenario generation (Monte Carlo)
- Portfolio backtesting and rebalancing

cuFOLIO is optional — falls back to scipy if unavailable.
All methods are async to integrate with TSAR's PricingEngine pattern.

Requires: nvidia-cufolio (pip install nvidia-cufolio)
GPU: NVIDIA GPU with CUDA 12.x+
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── cuFOLIO availability check ──────────────────────────────

try:
    # cuFOLIO Python bindings (part of NVIDIA RAPIDS ecosystem)
    import cupy as cp
    from cufolio import (
        EfficientFrontier,
        MeanCVaROptimizer,
        PortfolioBacktester,
        ScenarioGenerator,
    )

    CUFOLIO_AVAILABLE = True
    logger.info("cufolio_available", msg="GPU-accelerated portfolio optimization enabled")
except ImportError:
    CUFOLIO_AVAILABLE = False
    cp = None  # type: ignore[assignment]

    # Stub classes for when cuFOLIO is not installed
    class _Stub:
        """Stub for missing cuFOLIO classes."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError("cuFOLIO not installed. Install with: pip install nvidia-cufolio")

    MeanCVaROptimizer = _Stub  # type: ignore[assignment,misc]
    EfficientFrontier = _Stub  # type: ignore[assignment,misc]
    ScenarioGenerator = _Stub  # type: ignore[assignment,misc]
    PortfolioBacktester = _Stub  # type: ignore[assignment,misc]


# ── Data classes ─────────────────────────────────────────────


@dataclass
class PortfolioAllocation:
    """Result of portfolio optimization."""

    weights: dict[str, float]  # symbol → weight (0.0-1.0)
    expected_return: float = 0.0
    expected_risk: float = 0.0
    cvar: float = 0.0  # Conditional Value at Risk
    sharpe_ratio: float = 0.0
    method: str = "cufolio_mean_cvar"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "expected_return": round(self.expected_return, 6),
            "expected_risk": round(self.expected_risk, 6),
            "cvar": round(self.cvar, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "method": self.method,
            "metadata": self.metadata,
        }


@dataclass
class EfficientFrontierResult:
    """Points along the efficient frontier."""

    portfolios: list[PortfolioAllocation] = field(default_factory=list)
    method: str = "cufolio_frontier"

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolios": [p.to_dict() for p in self.portfolios],
            "method": self.method,
            "count": len(self.portfolios),
        }


@dataclass
class BacktestResult:
    """Portfolio backtest results."""

    total_return: float = 0.0
    annualized_return: float = 0.0
    annualized_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    num_rebalances: int = 0
    turnover: float = 0.0
    method: str = "cufolio_backtest"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": round(self.total_return, 6),
            "annualized_return": round(self.annualized_return, 6),
            "annualized_volatility": round(self.annualized_volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 6),
            "num_rebalances": self.num_rebalances,
            "turnover": round(self.turnover, 6),
            "method": self.method,
            "metadata": self.metadata,
        }


# ── Main Backend ─────────────────────────────────────────────


class CuFOLIOBackend:
    """GPU-accelerated portfolio optimization using NVIDIA cuFOLIO.

    Provides Mean-CVaR optimization, efficient frontier generation,
    scenario-based Monte Carlo simulation, and portfolio backtesting.

    Falls back to scipy-based optimization if cuFOLIO is unavailable.

    Usage::

        backend = CuFOLIOBackend(config)
        allocation = await backend.optimize_portfolio(
            symbols=["BTC/USDT", "ETH/USDT"],
            returns_matrix=historical_returns,
            current_weights={"BTC/USDT": 0.6, "ETH/USDT": 0.4},
        )
        print(f"Optimal weights: {allocation.weights}")
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._available = CUFOLIO_AVAILABLE
        self._fallback = self._config.get("fallback", "scipy")

        if not self._available:
            logger.warning(
                "cufolio_not_available",
                msg=f"cuFOLIO not installed. Using {self._fallback} fallback.",
            )

    @property
    def available(self) -> bool:
        """Check if cuFOLIO GPU backend is available."""
        return self._available

    @property
    def method(self) -> str:
        """Return the active optimization method name."""
        return "cufolio_mean_cvar" if self._available else f"fallback_{self._fallback}"

    # ── Portfolio Optimization ───────────────────────────────

    async def optimize_portfolio(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        current_weights: dict[str, float] | None = None,
        risk_free_rate: float = 0.04,
    ) -> PortfolioAllocation:
        """Optimize portfolio allocation using Mean-CVaR.

        Args:
            symbols: List of asset symbols.
            returns_matrix: Historical returns (rows=periods, cols=assets).
            current_weights: Current portfolio weights (for turnover constraint).
            risk_free_rate: Annual risk-free rate (default 4%).

        Returns:
            PortfolioAllocation with optimal weights and metrics.
        """
        if not symbols or not returns_matrix:
            return PortfolioAllocation(
                weights={s: 1.0 / len(symbols) for s in symbols} if symbols else {},
                method="equal_weight_fallback",
            )

        if self._available:
            return await self._cufolio_optimize(
                symbols, returns_matrix, current_weights, risk_free_rate
            )
        else:
            return await self._scipy_fallback_optimize(
                symbols, returns_matrix, current_weights, risk_free_rate
            )

    async def _cufolio_optimize(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        current_weights: dict[str, float] | None,
        risk_free_rate: float,
    ) -> PortfolioAllocation:
        """GPU-accelerated Mean-CVaR optimization via cuFOLIO."""
        assert cp is not None

        def _run() -> PortfolioAllocation:
            # Transfer returns to GPU
            returns_gpu = cp.array(returns_matrix, dtype=cp.float64)
            num_assets = len(symbols)

            # Get config params
            opt_cfg = self._config.get("optimization", {})
            confidence = opt_cfg.get("confidence_level", 0.95)
            max_iter = opt_cfg.get("max_iterations", 1000)
            tol = opt_cfg.get("tolerance", 1e-6)

            # Initialize Mean-CVaR optimizer
            optimizer = MeanCVaROptimizer(
                returns=returns_gpu,
                confidence_level=confidence,
                max_iterations=max_iter,
                tolerance=tol,
            )

            # Set constraints
            if current_weights:
                current = cp.array(
                    [current_weights.get(s, 0.0) for s in symbols],
                    dtype=cp.float64,
                )
                optimizer.set_turnover_constraint(
                    current_weights=current,
                    max_turnover=0.5,  # Max 50% turnover per rebalance
                )

            # Bounds: each asset 0-15% (from risk.yaml max_single_position_pct)
            optimizer.set_weight_bounds(
                lower=cp.zeros(num_assets),
                upper=cp.full(num_assets, 0.15),
            )

            # Optimize
            result = optimizer.optimize()

            # Extract results
            weights_gpu = result.weights
            weights_cpu = cp.asnumpy(weights_gpu)

            weight_dict = {
                symbols[i]: float(weights_cpu[i])
                for i in range(num_assets)
                if weights_cpu[i] > 1e-6  # Skip near-zero weights
            }

            return PortfolioAllocation(
                weights=weight_dict,
                expected_return=float(result.expected_return),
                expected_risk=float(result.risk),
                cvar=float(result.cvar),
                sharpe_ratio=float(result.sharpe_ratio),
                method="cufolio_mean_cvar",
                metadata={
                    "confidence_level": confidence,
                    "iterations": int(result.iterations),
                    "converged": result.converged,
                    "gpu_accelerated": True,
                },
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _scipy_fallback_optimize(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        current_weights: dict[str, float] | None,
        risk_free_rate: float,
    ) -> PortfolioAllocation:
        """Scipy-based fallback when cuFOLIO is unavailable."""
        import numpy as np
        from scipy.optimize import minimize

        def _run() -> PortfolioAllocation:
            returns = np.array(returns_matrix)
            num_assets = len(symbols)
            mean_returns = np.mean(returns, axis=0)
            cov_matrix = np.cov(returns.T)

            # Objective: minimize negative Sharpe ratio
            def neg_sharpe(weights: np.ndarray) -> float:
                port_return = np.dot(weights, mean_returns) * 252
                port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix * 252, weights)))
                if port_vol == 0:
                    return 0.0
                return -(port_return - risk_free_rate) / port_vol

            # Constraints: weights sum to 1
            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
            bounds = [(0.0, 0.15)] * num_assets  # Max 15% per asset
            x0 = np.ones(num_assets) / num_assets

            result = minimize(
                neg_sharpe,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
            )

            weights = result.x
            weight_dict = {
                symbols[i]: float(weights[i]) for i in range(num_assets) if weights[i] > 1e-6
            }

            port_return = np.dot(weights, mean_returns) * 252
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix * 252, weights)))

            return PortfolioAllocation(
                weights=weight_dict,
                expected_return=float(port_return),
                expected_risk=float(port_vol),
                cvar=0.0,  # Approximation not available in scipy fallback
                sharpe_ratio=float(-result.fun),
                method="fallback_scipy",
                metadata={
                    "converged": result.success,
                    "gpu_accelerated": False,
                },
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── Efficient Frontier ───────────────────────────────────

    async def generate_efficient_frontier(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        num_points: int = 100,
    ) -> EfficientFrontierResult:
        """Generate the efficient frontier.

        Args:
            symbols: List of asset symbols.
            returns_matrix: Historical returns.
            num_points: Number of frontier points.

        Returns:
            EfficientFrontierResult with list of optimal portfolios.
        """
        if not symbols or not returns_matrix:
            return EfficientFrontierResult()

        if self._available:
            return await self._cufolio_frontier(symbols, returns_matrix, num_points)
        else:
            return await self._scipy_frontier(symbols, returns_matrix, num_points)

    async def _cufolio_frontier(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        num_points: int,
    ) -> EfficientFrontierResult:
        """GPU-accelerated efficient frontier via cuFOLIO."""
        assert cp is not None

        def _run() -> EfficientFrontierResult:
            returns_gpu = cp.array(returns_matrix, dtype=cp.float64)

            frontier = EfficientFrontier(
                returns=returns_gpu,
                num_points=num_points,
            )

            frontier_result = frontier.compute()
            portfolios = []

            for i in range(len(frontier_result.weights)):
                w = cp.asnumpy(frontier_result.weights[i])
                weight_dict = {symbols[j]: float(w[j]) for j in range(len(symbols)) if w[j] > 1e-6}
                portfolios.append(
                    PortfolioAllocation(
                        weights=weight_dict,
                        expected_return=float(frontier_result.returns[i]),
                        expected_risk=float(frontier_result.risks[i]),
                        sharpe_ratio=float(frontier_result.sharpes[i]),
                        method="cufolio_frontier",
                    )
                )

            return EfficientFrontierResult(
                portfolios=portfolios,
                method="cufolio_frontier",
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _scipy_frontier(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        num_points: int,
    ) -> EfficientFrontierResult:
        """Scipy fallback for efficient frontier."""
        import numpy as np
        from scipy.optimize import minimize

        def _run() -> EfficientFrontierResult:
            returns = np.array(returns_matrix)
            num_assets = len(symbols)
            mean_returns = np.mean(returns, axis=0) * 252
            cov_matrix = np.cov(returns.T) * 252

            # Find range of achievable returns
            min_ret = float(np.min(mean_returns))
            max_ret = float(np.max(mean_returns))
            target_returns = np.linspace(min_ret, max_ret, num_points)

            portfolios = []
            for target in target_returns:
                # Minimize variance for target return
                def portfolio_vol(weights: np.ndarray) -> float:
                    return float(np.dot(weights.T, np.dot(cov_matrix, weights)))

                constraints = [
                    {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                    {"type": "eq", "fun": lambda w, t=target: np.dot(w, mean_returns) - t},
                ]
                bounds = [(0.0, 0.15)] * num_assets
                x0 = np.ones(num_assets) / num_assets

                result = minimize(
                    portfolio_vol,
                    x0,
                    method="SLSQP",
                    bounds=bounds,
                    constraints=constraints,
                )

                if result.success:
                    w = result.x
                    weight_dict = {
                        symbols[i]: float(w[i]) for i in range(num_assets) if w[i] > 1e-6
                    }
                    vol = np.sqrt(portfolio_vol(w))
                    sharpe = (target - 0.04) / vol if vol > 0 else 0.0
                    portfolios.append(
                        PortfolioAllocation(
                            weights=weight_dict,
                            expected_return=float(target),
                            expected_risk=float(vol),
                            sharpe_ratio=float(sharpe),
                            method="fallback_scipy_frontier",
                        )
                    )

            return EfficientFrontierResult(
                portfolios=portfolios,
                method="fallback_scipy_frontier",
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── Scenario Generation ──────────────────────────────────

    async def generate_scenarios(
        self,
        returns_matrix: list[list[float]],
        num_scenarios: int = 10000,
    ) -> list[list[float]]:
        """Generate Monte Carlo scenarios for portfolio stress testing.

        Args:
            returns_matrix: Historical returns.
            num_scenarios: Number of scenarios to generate.

        Returns:
            List of scenario return vectors.
        """
        if not returns_matrix:
            return []

        if self._available:
            return await self._cufolio_scenarios(returns_matrix, num_scenarios)
        else:
            return await self._numpy_scenarios(returns_matrix, num_scenarios)

    async def _cufolio_scenarios(
        self,
        returns_matrix: list[list[float]],
        num_scenarios: int,
    ) -> list[list[float]]:
        """GPU-accelerated scenario generation via cuFOLIO."""
        assert cp is not None

        def _run() -> list[list[float]]:
            returns_gpu = cp.array(returns_matrix, dtype=cp.float64)
            opt_cfg = self._config.get("scenarios", {})
            method = opt_cfg.get("method", "historical")

            generator = ScenarioGenerator(
                returns=returns_gpu,
                num_scenarios=num_scenarios,
                method=method,
            )

            scenarios_gpu = generator.generate()
            scenarios_cpu = cp.asnumpy(scenarios_gpu)
            return scenarios_cpu.tolist()

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _numpy_scenarios(
        self,
        returns_matrix: list[list[float]],
        num_scenarios: int,
    ) -> list[list[float]]:
        """Numpy fallback for scenario generation."""
        import numpy as np

        def _run() -> list[list[float]]:
            returns = np.array(returns_matrix)
            mean = np.mean(returns, axis=0)
            cov = np.cov(returns.T)

            # Parametric bootstrap from multivariate normal
            scenarios = np.random.multivariate_normal(mean, cov, size=num_scenarios)
            return scenarios.tolist()

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── Backtesting ──────────────────────────────────────────

    async def backtest_portfolio(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        initial_weights: dict[str, float],
        rebalance_frequency: str = "weekly",
    ) -> BacktestResult:
        """Backtest a portfolio allocation strategy.

        Args:
            symbols: List of asset symbols.
            returns_matrix: Historical returns.
            initial_weights: Starting portfolio weights.
            rebalance_frequency: How often to rebalance.

        Returns:
            BacktestResult with performance metrics.
        """
        if not symbols or not returns_matrix:
            return BacktestResult()

        if self._available:
            return await self._cufolio_backtest(
                symbols, returns_matrix, initial_weights, rebalance_frequency
            )
        else:
            return await self._numpy_backtest(
                symbols, returns_matrix, initial_weights, rebalance_frequency
            )

    async def _cufolio_backtest(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        initial_weights: dict[str, float],
        rebalance_frequency: str,
    ) -> BacktestResult:
        """GPU-accelerated backtesting via cuFOLIO."""
        assert cp is not None

        def _run() -> BacktestResult:
            returns_gpu = cp.array(returns_matrix, dtype=cp.float64)
            weights = cp.array(
                [initial_weights.get(s, 0.0) for s in symbols],
                dtype=cp.float64,
            )

            bt_cfg = self._config.get("backtest", {})
            cost_bps = bt_cfg.get("transaction_cost_bps", 10)

            backtester = PortfolioBacktester(
                returns=returns_gpu,
                initial_weights=weights,
                rebalance_frequency=rebalance_frequency,
                transaction_cost_bps=cost_bps,
            )

            result = backtester.run()

            return BacktestResult(
                total_return=float(result.total_return),
                annualized_return=float(result.annualized_return),
                annualized_volatility=float(result.annualized_volatility),
                sharpe_ratio=float(result.sharpe_ratio),
                max_drawdown=float(result.max_drawdown),
                num_rebalances=int(result.num_rebalances),
                turnover=float(result.turnover),
                method="cufolio_backtest",
                metadata={"gpu_accelerated": True},
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _numpy_backtest(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        initial_weights: dict[str, float],
        rebalance_frequency: str,
    ) -> BacktestResult:
        """Simple numpy backtest fallback."""
        import numpy as np

        def _run() -> BacktestResult:
            returns = np.array(returns_matrix)
            weights = np.array([initial_weights.get(s, 0.0) for s in symbols])

            # Rebalance interval in periods (assume daily data)
            freq_map = {"daily": 1, "weekly": 5, "monthly": 21}
            interval = freq_map.get(rebalance_frequency, 5)

            # Simulate
            portfolio_returns = []
            for i in range(len(returns)):
                period_return = np.dot(weights, returns[i])
                portfolio_returns.append(period_return)

                # Drift weights
                weights = weights * (1 + returns[i])
                weights = weights / np.sum(weights)

                # Rebalance
                if (i + 1) % interval == 0:
                    weights = np.array([initial_weights.get(s, 0.0) for s in symbols])

            port_returns = np.array(portfolio_returns)
            cumulative = np.cumprod(1 + port_returns)
            total_return = float(cumulative[-1] - 1) if len(cumulative) > 0 else 0.0

            # Annualized metrics
            n_days = len(port_returns)
            ann_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
            ann_vol = float(np.std(port_returns) * np.sqrt(252))
            sharpe = (ann_return - 0.04) / ann_vol if ann_vol > 0 else 0.0

            # Max drawdown
            peak = np.maximum.accumulate(cumulative)
            drawdown = (cumulative - peak) / peak
            max_dd = float(np.min(drawdown)) if len(drawdown) > 0 else 0.0

            return BacktestResult(
                total_return=total_return,
                annualized_return=float(ann_return),
                annualized_volatility=ann_vol,
                sharpe_ratio=float(sharpe),
                max_drawdown=max_dd,
                num_rebalances=n_days // interval,
                turnover=0.0,
                method="fallback_numpy_backtest",
                metadata={"gpu_accelerated": False},
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── Health / Status ──────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return backend status information."""
        return {
            "available": self._available,
            "method": self.method,
            "fallback": self._fallback,
            "gpu_accelerated": self._available,
        }
