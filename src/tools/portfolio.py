"""
TSAR Domain Tools — Portfolio Management Tools.

What the agent OPTIMIZES. Provides portfolio construction, optimization,
rebalancing, and risk-based allocation across asset classes.

Tools:
  1. Mean-CVaR Optimizer   — GPU-accelerated portfolio optimization (cuFOLIO)
  2. Black-Litterman       — View-based optimization combining equilibrium + views
  3. Rebalancer             — Threshold-based and calendar-based rebalancing
  4. Asset Allocator        — Crypto/gold/forex allocation with risk profiles
  5. Diversification Scorer — HHI and correlation-based diversification metrics
  6. Risk Parity            — Equal risk contribution and inverse volatility weighting

All tools are async. GPU acceleration via cuFOLIO when available,
scipy/numpy fallback otherwise. Operates on shared types from
src.interfaces.types.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


class RiskProfile(StrEnum):
    """Risk tolerance profiles for asset allocation."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class RebalanceFrequency(StrEnum):
    """Rebalancing frequency options."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


@dataclass(frozen=True)
class MeanCVaRResult:
    """Result of Mean-CVaR portfolio optimization.

    Attributes:
        weights: Optimal portfolio weights (symbol → weight, sum ≈ 1.0).
        expected_return: Annualized expected portfolio return.
        expected_risk: Annualized portfolio volatility.
        cvar: Conditional Value at Risk at the specified confidence level.
        sharpe_ratio: Risk-adjusted return metric.
        confidence_level: CVaR confidence level used (e.g. 0.95).
        efficient_frontier: List of (return, risk, weights) frontier points.
        method: Optimization method used ("cufolio" or "scipy").
        gpu_accelerated: Whether GPU acceleration was used.
        converged: Whether the optimizer converged.
        iterations: Number of optimization iterations.
    """

    weights: dict[str, float]
    expected_return: float = 0.0
    expected_risk: float = 0.0
    cvar: float = 0.0
    sharpe_ratio: float = 0.0
    confidence_level: float = 0.95
    efficient_frontier: list[dict[str, Any]] = field(default_factory=list)
    method: str = "scipy"
    gpu_accelerated: bool = False
    converged: bool = False
    iterations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "expected_return": round(self.expected_return, 6),
            "expected_risk": round(self.expected_risk, 6),
            "cvar": round(self.cvar, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "confidence_level": self.confidence_level,
            "efficient_frontier": self.efficient_frontier,
            "method": self.method,
            "gpu_accelerated": self.gpu_accelerated,
            "converged": self.converged,
            "iterations": self.iterations,
        }


@dataclass(frozen=True)
class BlackLittermanResult:
    """Result of Black-Litterman portfolio optimization.

    Attributes:
        weights: Optimal portfolio weights incorporating views.
        posterior_returns: Expected returns after blending equilibrium + views.
        posterior_covariance: Covariance matrix after view incorporation.
        equilibrium_returns: Implied equilibrium excess returns (π).
        view_returns: Expected returns from agent views.
        confidence: View confidence matrix (Ω).
        method: Optimization method used.
        tau: Uncertainty scaling parameter used.
    """

    weights: dict[str, float]
    posterior_returns: dict[str, float] = field(default_factory=dict)
    posterior_covariance: list[list[float]] = field(default_factory=list)
    equilibrium_returns: dict[str, float] = field(default_factory=dict)
    view_returns: dict[str, float] = field(default_factory=dict)
    confidence: list[list[float]] = field(default_factory=list)
    method: str = "scipy"
    tau: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "posterior_returns": {k: round(v, 6) for k, v in self.posterior_returns.items()},
            "equilibrium_returns": {k: round(v, 6) for k, v in self.equilibrium_returns.items()},
            "view_returns": {k: round(v, 6) for k, v in self.view_returns.items()},
            "method": self.method,
            "tau": self.tau,
        }


@dataclass(frozen=True)
class RebalanceResult:
    """Result of a rebalancing operation.

    Attributes:
        needs_rebalance: Whether rebalancing is needed.
        trigger: What triggered the rebalance ("threshold", "calendar", "none").
        current_weights: Current portfolio weights.
        target_weights: Target portfolio weights.
        trades: List of trades needed to rebalance (symbol, side, quantity).
        turnover: Total portfolio turnover (sum of absolute weight changes).
        estimated_cost_bps: Estimated transaction cost in basis points.
        max_drift: Maximum drift from target weights.
        details: Human-readable rebalance details.
    """

    needs_rebalance: bool = False
    trigger: str = "none"
    current_weights: dict[str, float] = field(default_factory=dict)
    target_weights: dict[str, float] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    turnover: float = 0.0
    estimated_cost_bps: float = 0.0
    max_drift: float = 0.0
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_rebalance": self.needs_rebalance,
            "trigger": self.trigger,
            "current_weights": {k: round(v, 6) for k, v in self.current_weights.items()},
            "target_weights": {k: round(v, 6) for k, v in self.target_weights.items()},
            "trades": self.trades,
            "turnover": round(self.turnover, 6),
            "estimated_cost_bps": round(self.estimated_cost_bps, 2),
            "max_drift": round(self.max_drift, 6),
            "details": self.details,
        }


@dataclass(frozen=True)
class AssetAllocationResult:
    """Result of asset allocation.

    Attributes:
        weights: Asset class and individual asset weights.
        risk_profile: Risk profile used for allocation.
        expected_return: Expected annualized portfolio return.
        expected_volatility: Expected annualized volatility.
        asset_class_breakdown: Weights grouped by asset class.
        rationale: Explanation of the allocation logic.
    """

    weights: dict[str, float] = field(default_factory=dict)
    risk_profile: str = "moderate"
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    asset_class_breakdown: dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "risk_profile": self.risk_profile,
            "expected_return": round(self.expected_return, 6),
            "expected_volatility": round(self.expected_volatility, 6),
            "asset_class_breakdown": {k: round(v, 4) for k, v in self.asset_class_breakdown.items()},
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class DiversificationResult:
    """Result of diversification analysis.

    Attributes:
        hhi: Herfindahl-Hirschman Index (0 = perfectly diversified, 1 = concentrated).
        effective_n: Effective number of assets (1/HHI).
        correlation_diversification: Correlation-based diversification ratio.
        average_correlation: Average pairwise correlation between assets.
        max_correlation: Maximum pairwise correlation.
        min_correlation: Minimum pairwise correlation.
        concentration_assets: Top N assets by weight concentration.
        diversification_score: Overall score 0-100 (100 = perfectly diversified).
        recommendations: List of diversification improvement suggestions.
    """

    hhi: float = 0.0
    effective_n: float = 0.0
    correlation_diversification: float = 0.0
    average_correlation: float = 0.0
    max_correlation: float = 0.0
    min_correlation: float = 0.0
    concentration_assets: list[dict[str, Any]] = field(default_factory=list)
    diversification_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hhi": round(self.hhi, 6),
            "effective_n": round(self.effective_n, 2),
            "correlation_diversification": round(self.correlation_diversification, 4),
            "average_correlation": round(self.average_correlation, 4),
            "max_correlation": round(self.max_correlation, 4),
            "min_correlation": round(self.min_correlation, 4),
            "concentration_assets": self.concentration_assets,
            "diversification_score": round(self.diversification_score, 1),
            "recommendations": self.recommendations,
        }


@dataclass(frozen=True)
class RiskParityResult:
    """Result of risk parity optimization.

    Attributes:
        weights: Risk parity portfolio weights.
        risk_contributions: Marginal risk contribution per asset.
        risk_contribution_pct: Percentage risk contribution per asset.
        total_portfolio_risk: Total annualized portfolio volatility.
        method: Method used ("equal_risk_contribution" or "inverse_volatility").
        iterations: Number of solver iterations (for ERC).
        converged: Whether the solver converged.
        target_risk_budget: Target risk budget per asset (equal = 1/N).
    """

    weights: dict[str, float] = field(default_factory=dict)
    risk_contributions: dict[str, float] = field(default_factory=dict)
    risk_contribution_pct: dict[str, float] = field(default_factory=dict)
    total_portfolio_risk: float = 0.0
    method: str = "equal_risk_contribution"
    iterations: int = 0
    converged: bool = False
    target_risk_budget: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "risk_contributions": {k: round(v, 6) for k, v in self.risk_contributions.items()},
            "risk_contribution_pct": {k: round(v, 4) for k, v in self.risk_contribution_pct.items()},
            "total_portfolio_risk": round(self.total_portfolio_risk, 6),
            "method": self.method,
            "iterations": self.iterations,
            "converged": self.converged,
            "target_risk_budget": round(self.target_risk_budget, 4),
        }


# ═══════════════════════════════════════════════════════════════════════
# PORTFOLIO TOOLS — MAIN CLASS
# ═══════════════════════════════════════════════════════════════════════


class PortfolioTools:
    """Portfolio management tools for TSAR agents.

    Provides 6 core portfolio tools:
      1. Mean-CVaR Optimizer — GPU-accelerated via cuFOLIO
      2. Black-Litterman — View-based portfolio optimization
      3. Rebalancer — Threshold and calendar-based rebalancing
      4. Asset Allocator — Risk-profile-based multi-asset allocation
      5. Diversification Scorer — HHI and correlation metrics
      6. Risk Parity — Equal risk contribution optimization

    Usage::

        tools = PortfolioTools(config)
        result = await tools.mean_cvar_optimize(symbols, returns)
        result = await tools.black_litterman(symbols, returns, views)
        result = await tools.check_rebalance(current, target, portfolio_value)
        result = await tools.allocate_assets(assets, risk_profile="moderate")
        result = await tools.score_diversification(weights, returns)
        result = await tools.risk_parity(symbols, returns)
    """

    # ── Default configuration ────────────────────────────────

    DEFAULT_CONFIG: dict[str, Any] = {
        "optimization": {
            "confidence_level": 0.95,
            "max_weight": 0.15,
            "min_weight": 0.0,
            "risk_free_rate": 0.04,
            "max_iterations": 1000,
            "tolerance": 1e-8,
            "frontier_points": 50,
        },
        "rebalance": {
            "threshold_pct": 5.0,
            "transaction_cost_bps": 10.0,
        },
        "black_litterman": {
            "tau": 0.05,
            "risk_aversion": 2.5,
        },
        "risk_parity": {
            "max_iterations": 1000,
            "tolerance": 1e-8,
        },
    }

    # ── Risk profile allocations ─────────────────────────────

    RISK_PROFILES: dict[str, dict[str, float]] = {
        RiskProfile.CONSERVATIVE: {
            "crypto": 0.10,
            "gold": 0.30,
            "forex": 0.25,
            "bonds": 0.25,
            "equities": 0.10,
        },
        RiskProfile.MODERATE: {
            "crypto": 0.25,
            "gold": 0.20,
            "forex": 0.15,
            "bonds": 0.15,
            "equities": 0.25,
        },
        RiskProfile.AGGRESSIVE: {
            "crypto": 0.50,
            "gold": 0.10,
            "forex": 0.10,
            "bonds": 0.05,
            "equities": 0.25,
        },
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._cufolio = None  # Lazy-loaded cuFOLIO backend

    @property
    def description(self) -> str:
        return (
            "Portfolio management tools: Mean-CVaR optimization, "
            "Black-Litterman views, rebalancing, asset allocation, "
            "diversification scoring, and risk parity."
        )

    # ═══════════════════════════════════════════════════════════════
    # 1. MEAN-CVaR OPTIMIZER
    # ═══════════════════════════════════════════════════════════════

    async def mean_cvar_optimize(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        confidence_level: float | None = None,
        risk_free_rate: float | None = None,
        max_weight: float | None = None,
        num_frontier_points: int | None = None,
    ) -> MeanCVaRResult:
        """Optimize portfolio using Mean-CVaR objective.

        Minimizes Conditional Value at Risk (CVaR) while targeting
        maximum risk-adjusted return. GPU-accelerated via cuFOLIO when
        available, scipy fallback otherwise.

        Args:
            symbols: List of asset symbols (e.g. ["BTC/USDT", "ETH/USDT"]).
            returns_matrix: Historical returns (rows=time periods, cols=assets).
            confidence_level: CVaR confidence (default 0.95 = 95th percentile).
            risk_free_rate: Annual risk-free rate (default 0.04 = 4%).
            max_weight: Maximum weight per asset (default 0.15 = 15%).
            num_frontier_points: Number of efficient frontier points.

        Returns:
            MeanCVaRResult with optimal weights, risk metrics, and frontier.
        """
        if not symbols or not returns_matrix:
            return MeanCVaRResult(
                weights={s: 1.0 / len(symbols) for s in symbols} if symbols else {},
                method="equal_weight_fallback",
            )

        conf = confidence_level or self._config["optimization"]["confidence_level"]
        rf = risk_free_rate or self._config["optimization"]["risk_free_rate"]
        mw = max_weight or self._config["optimization"]["max_weight"]
        frontier_n = (
            num_frontier_points
            if num_frontier_points is not None
            else self._config["optimization"]["frontier_points"]
        )

        # Try cuFOLIO GPU backend first
        if self._cufolio_available():
            return await self._mean_cvar_cufolio(
                symbols, returns_matrix, conf, rf, mw, frontier_n
            )

        # Scipy fallback
        return await self._mean_cvar_scipy(
            symbols, returns_matrix, conf, rf, mw, frontier_n
        )

    async def _mean_cvar_cufolio(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        confidence: float,
        risk_free_rate: float,
        max_weight: float,
        frontier_n: int,
    ) -> MeanCVaRResult:
        """GPU-accelerated Mean-CVaR via cuFOLIO."""
        backend = self._get_cufolio()

        allocation = await backend.optimize_portfolio(
            symbols=symbols,
            returns_matrix=returns_matrix,
            risk_free_rate=risk_free_rate,
        )

        frontier_result = await backend.generate_efficient_frontier(
            symbols=symbols,
            returns_matrix=returns_matrix,
            num_points=frontier_n,
        )

        frontier_data = []
        for p in frontier_result.portfolios:
            frontier_data.append({
                "return": round(p.expected_return, 6),
                "risk": round(p.expected_risk, 6),
                "sharpe": round(p.sharpe_ratio, 4),
                "weights": {k: round(v, 6) for k, v in p.weights.items()},
            })

        return MeanCVaRResult(
            weights=allocation.weights,
            expected_return=allocation.expected_return,
            expected_risk=allocation.expected_risk,
            cvar=allocation.cvar,
            sharpe_ratio=allocation.sharpe_ratio,
            confidence_level=confidence,
            efficient_frontier=frontier_data,
            method="cufolio",
            gpu_accelerated=True,
            converged=allocation.metadata.get("converged", True),
            iterations=allocation.metadata.get("iterations", 0),
        )

    async def _mean_cvar_scipy(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        confidence: float,
        risk_free_rate: float,
        max_weight: float,
        frontier_n: int,
    ) -> MeanCVaRResult:
        """Scipy-based Mean-CVaR optimization fallback."""
        from scipy.optimize import minimize

        def _run() -> MeanCVaRResult:
            returns = np.array(returns_matrix)
            n_assets = len(symbols)
            n_periods = len(returns)

            mean_returns = np.mean(returns, axis=0) * 252

            alpha = 1.0 - confidence

            def cvar_objective(weights: np.ndarray) -> float:
                """Minimize portfolio CVaR (expected shortfall)."""
                portfolio_returns = returns @ weights
                sorted_returns = np.sort(portfolio_returns)
                var_idx = max(1, int(np.ceil(alpha * n_periods)))
                tail = sorted_returns[:var_idx]
                cvar = -np.mean(tail) * np.sqrt(252)
                return cvar

            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
            bounds = [(0.0, max_weight)] * n_assets
            x0 = np.ones(n_assets) / n_assets

            result = minimize(
                cvar_objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={
                    "maxiter": self._config["optimization"]["max_iterations"],
                    "ftol": self._config["optimization"]["tolerance"],
                },
            )

            opt_weights = result.x
            weight_dict = {
                symbols[i]: float(opt_weights[i])
                for i in range(n_assets)
                if opt_weights[i] > 1e-6
            }

            port_returns = returns @ opt_weights
            ann_return = float(np.mean(port_returns) * 252)
            ann_risk = float(np.std(port_returns) * np.sqrt(252))
            cvar_val = cvar_objective(opt_weights)
            sharpe = (ann_return - risk_free_rate) / ann_risk if ann_risk > 0 else 0.0

            frontier = self._compute_frontier_scipy(
                symbols, returns, mean_returns, risk_free_rate, max_weight, frontier_n
            )

            return MeanCVaRResult(
                weights=weight_dict,
                expected_return=ann_return,
                expected_risk=ann_risk,
                cvar=cvar_val,
                sharpe_ratio=sharpe,
                confidence_level=confidence,
                efficient_frontier=frontier,
                method="scipy",
                gpu_accelerated=False,
                converged=result.success,
                iterations=result.nit if hasattr(result, "nit") else 0,
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    def _compute_frontier_scipy(
        self,
        symbols: list[str],
        returns: np.ndarray,
        mean_returns: np.ndarray,
        risk_free_rate: float,
        max_weight: float,
        num_points: int,
    ) -> list[dict[str, Any]]:
        """Compute efficient frontier points via scipy."""
        from scipy.optimize import minimize

        n_assets = len(symbols)
        cov = np.cov(returns.T) * 252

        min_ret = float(np.min(mean_returns))
        max_ret = float(np.max(mean_returns))
        target_returns = np.linspace(min_ret, max_ret, num_points)

        frontier = []
        for target in target_returns:
            def portfolio_vol(w: np.ndarray) -> float:
                return float(np.sqrt(w.T @ cov @ w))

            constraints = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                {
                    "type": "eq",
                    "fun": lambda w, t=target: w @ mean_returns - t,
                },
            ]
            bounds = [(0.0, max_weight)] * n_assets
            x0 = np.ones(n_assets) / n_assets

            res = minimize(
                portfolio_vol, x0, method="SLSQP",
                bounds=bounds, constraints=constraints,
            )
            if res.success:
                w = res.x
                vol = portfolio_vol(w)
                sharpe = (target - risk_free_rate) / vol if vol > 0 else 0.0
                weight_dict = {
                    symbols[i]: round(float(w[i]), 6)
                    for i in range(n_assets) if w[i] > 1e-6
                }
                frontier.append({
                    "return": round(float(target), 6),
                    "risk": round(vol, 6),
                    "sharpe": round(sharpe, 4),
                    "weights": weight_dict,
                })

        return frontier

    # ═══════════════════════════════════════════════════════════════
    # 2. BLACK-LITTERMAN
    # ═══════════════════════════════════════════════════════════════

    async def black_litterman(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        views: list[dict[str, Any]],
        market_caps: dict[str, float] | None = None,
        tau: float | None = None,
        risk_aversion: float | None = None,
        risk_free_rate: float = 0.04,
    ) -> BlackLittermanResult:
        """Black-Litterman portfolio optimization.

        Combines market equilibrium returns with agent views to produce
        posterior expected returns and optimal weights.

        The model:
          1. Compute implied equilibrium excess returns (π) from market caps
          2. Express investor views as P (pick matrix) and Q (view returns)
          3. Compute posterior returns via Bayesian update
          4. Optimize weights using posterior returns and covariance

        Args:
            symbols: List of asset symbols.
            returns_matrix: Historical returns (rows=periods, cols=assets).
            views: List of view dicts. Each view has:
                - "asset": str — which asset the view is about
                - "return": float — expected excess return
                - "confidence": float — confidence in the view (0-1)
                OR for relative views:
                - "long": str — asset expected to outperform
                - "short": str — asset expected to underperform
                - "return": float — expected spread
                - "confidence": float — confidence (0-1)
            market_caps: Market cap weights (symbol → cap). If None, equal-weight.
            tau: Uncertainty scaling parameter (default 0.05).
            risk_aversion: Risk aversion coefficient δ (default 2.5).
            risk_free_rate: Annual risk-free rate (default 4%).

        Returns:
            BlackLittermanResult with posterior weights and return estimates.
        """
        if not symbols or not returns_matrix:
            return BlackLittermanResult(weights={})

        t = tau or self._config["black_litterman"]["tau"]
        delta = risk_aversion or self._config["black_litterman"]["risk_aversion"]

        def _run() -> BlackLittermanResult:
            returns = np.array(returns_matrix)
            n = len(symbols)
            symbol_idx = {s: i for i, s in enumerate(symbols)}

            # Covariance matrix (annualized)
            sigma = np.cov(returns.T) * 252

            # Market cap weights (or equal weight)
            if market_caps:
                total_cap = sum(market_caps.get(s, 0.0) for s in symbols)
                if total_cap > 0:
                    w_mkt = np.array(
                        [market_caps.get(s, 0.0) / total_cap for s in symbols]
                    )
                else:
                    w_mkt = np.ones(n) / n
            else:
                w_mkt = np.ones(n) / n

            # Step 1: Implied equilibrium excess returns π = δ * Σ * w_mkt
            pi = delta * sigma @ w_mkt

            # Step 2: Build view matrices P, Q, Ω
            n_views = len(views)
            if n_views == 0:
                weight_dict = {
                    symbols[i]: float(w_mkt[i]) for i in range(n) if w_mkt[i] > 1e-6
                }
                eq_returns = {symbols[i]: float(pi[i]) for i in range(n)}
                return BlackLittermanResult(
                    weights=weight_dict,
                    posterior_returns=eq_returns,
                    equilibrium_returns=eq_returns,
                    view_returns={},
                    method="scipy_no_views",
                    tau=t,
                )

            P = np.zeros((n_views, n))
            Q = np.zeros(n_views)
            omega_diag = np.zeros(n_views)

            for j, view in enumerate(views):
                conf = view.get("confidence", 0.5)
                Q[j] = view.get("return", 0.0)

                if "long" in view and "short" in view:
                    # Relative view: long - short
                    long_idx = symbol_idx.get(view["long"])
                    short_idx = symbol_idx.get(view["short"])
                    if long_idx is not None:
                        P[j, long_idx] = 1.0
                    if short_idx is not None:
                        P[j, short_idx] = -1.0
                else:
                    # Absolute view
                    asset = view.get("asset", "")
                    idx = symbol_idx.get(asset)
                    if idx is not None:
                        P[j, idx] = 1.0

                # Ω_jj = (1/conf - 1) * P_j Σ P_j' (He-Litterman scaling)
                view_variance = P[j] @ sigma @ P[j]
                omega_diag[j] = view_variance * (1.0 / max(conf, 1e-6) - 1.0)

            Omega = np.diag(omega_diag)

            # Step 3: Posterior returns
            # E[R] = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ [(τΣ)⁻¹π + P'Ω⁻¹Q]
            tau_sigma_inv = np.linalg.inv(t * sigma)
            omega_inv = np.linalg.inv(Omega)

            A = tau_sigma_inv + P.T @ omega_inv @ P
            b = tau_sigma_inv @ pi + P.T @ omega_inv @ Q

            posterior_returns = np.linalg.solve(A, b)
            posterior_cov = np.linalg.inv(A)

            # Step 4: Optimal weights: w* = (1/δ) * Σ_post⁻¹ * E[R]
            try:
                optimal_weights = (1.0 / delta) * np.linalg.solve(
                    posterior_cov, posterior_returns
                )
            except np.linalg.LinAlgError:
                optimal_weights = w_mkt

            # Normalize, clip negatives
            optimal_weights = np.maximum(optimal_weights, 0.0)
            total = np.sum(optimal_weights)
            if total > 0:
                optimal_weights = optimal_weights / total
            else:
                optimal_weights = w_mkt

            weight_dict = {
                symbols[i]: float(optimal_weights[i])
                for i in range(n)
                if optimal_weights[i] > 1e-6
            }
            post_ret_dict = {symbols[i]: float(posterior_returns[i]) for i in range(n)}
            eq_ret_dict = {symbols[i]: float(pi[i]) for i in range(n)}
            view_ret_dict = {
                symbols[i]: float(Q[j])
                for j, view in enumerate(views)
                for i in range(n)
                if symbols[i] == view.get("asset", view.get("long", ""))
            }

            return BlackLittermanResult(
                weights=weight_dict,
                posterior_returns=post_ret_dict,
                posterior_covariance=posterior_cov.tolist(),
                equilibrium_returns=eq_ret_dict,
                view_returns=view_ret_dict,
                confidence=Omega.tolist(),
                method="scipy",
                tau=t,
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ═══════════════════════════════════════════════════════════════
    # 3. REBALANCER
    # ═══════════════════════════════════════════════════════════════

    async def check_rebalance(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        portfolio_value: float,
        threshold_pct: float | None = None,
        transaction_cost_bps: float | None = None,
        last_rebalance_time: datetime | None = None,
        frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY,
    ) -> RebalanceResult:
        """Check if portfolio needs rebalancing and compute trades.

        Two triggers:
          1. THRESHOLD: Any asset drifts > threshold_pct from target → rebalance
          2. CALENDAR: Time since last rebalance exceeds frequency → rebalance

        Args:
            current_weights: Current portfolio weights (symbol → weight).
            target_weights: Target portfolio weights (symbol → weight).
            portfolio_value: Current total portfolio value in USD.
            threshold_pct: Drift threshold in percent (default 5%).
            transaction_cost_bps: Transaction cost in basis points (default 10 bps).
            last_rebalance_time: When the portfolio was last rebalanced.
            frequency: Rebalancing frequency for calendar trigger.

        Returns:
            RebalanceResult with rebalancing decision and required trades.
        """
        thresh = (
            threshold_pct
            if threshold_pct is not None
            else self._config["rebalance"]["threshold_pct"]
        )
        cost_bps = (
            transaction_cost_bps
            if transaction_cost_bps is not None
            else self._config["rebalance"]["transaction_cost_bps"]
        )

        def _run() -> RebalanceResult:
            all_symbols = sorted(
                set(list(current_weights.keys()) + list(target_weights.keys()))
            )

            if not all_symbols:
                return RebalanceResult(
                    needs_rebalance=False,
                    trigger="none",
                    details="No assets to rebalance.",
                )

            # Compute drift per asset
            drifts: dict[str, float] = {}
            max_drift = 0.0
            for sym in all_symbols:
                current = current_weights.get(sym, 0.0)
                target = target_weights.get(sym, 0.0)
                drift = abs(current - target) * 100
                drifts[sym] = drift
                max_drift = max(max_drift, drift)

            # Check threshold trigger
            threshold_triggered = max_drift > thresh

            # Check calendar trigger
            calendar_triggered = False
            if last_rebalance_time is not None:
                now = datetime.now(UTC)
                elapsed = now - last_rebalance_time
                freq_days = {
                    RebalanceFrequency.DAILY: 1,
                    RebalanceFrequency.WEEKLY: 7,
                    RebalanceFrequency.MONTHLY: 30,
                    RebalanceFrequency.QUARTERLY: 90,
                }
                calendar_triggered = elapsed.days >= freq_days.get(frequency, 30)
            else:
                calendar_triggered = True

            needs_rebalance = threshold_triggered or calendar_triggered

            if not needs_rebalance:
                return RebalanceResult(
                    needs_rebalance=False,
                    trigger="none",
                    current_weights=current_weights,
                    target_weights=target_weights,
                    max_drift=max_drift,
                    details=(
                        f"Max drift {max_drift:.2f}% < threshold {thresh}%. "
                        "Calendar not due."
                    ),
                )

            trigger = "threshold" if threshold_triggered else "calendar"

            # Compute required trades
            trades = []
            total_turnover = 0.0
            for sym in all_symbols:
                current = current_weights.get(sym, 0.0)
                target = target_weights.get(sym, 0.0)
                weight_diff = target - current
                if abs(weight_diff) < 1e-6:
                    continue

                usd_amount = weight_diff * portfolio_value
                side = "buy" if weight_diff > 0 else "sell"
                trades.append({
                    "symbol": sym,
                    "side": side,
                    "weight_change": round(weight_diff, 6),
                    "usd_amount": round(abs(usd_amount), 2),
                })
                total_turnover += abs(weight_diff)

            turnover = total_turnover / 2.0
            estimated_cost = turnover * cost_bps

            details_parts = [
                f"Trigger: {trigger}",
                f"Max drift: {max_drift:.2f}% (threshold: {thresh}%)",
                f"Turnover: {turnover:.4f}",
                f"Estimated cost: {estimated_cost:.2f} bps",
                f"Trades needed: {len(trades)}",
            ]

            return RebalanceResult(
                needs_rebalance=True,
                trigger=trigger,
                current_weights=current_weights,
                target_weights=target_weights,
                trades=trades,
                turnover=turnover,
                estimated_cost_bps=estimated_cost,
                max_drift=max_drift,
                details=" | ".join(details_parts),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def compute_threshold_rebalance(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        portfolio_value: float,
        threshold_pct: float = 5.0,
        transaction_cost_bps: float = 10.0,
    ) -> RebalanceResult:
        """Convenience: threshold-based rebalance check only."""
        return await self.check_rebalance(
            current_weights=current_weights,
            target_weights=target_weights,
            portfolio_value=portfolio_value,
            threshold_pct=threshold_pct,
            transaction_cost_bps=transaction_cost_bps,
            last_rebalance_time=None,
            frequency=RebalanceFrequency.MONTHLY,
        )

    # ═══════════════════════════════════════════════════════════════
    # 4. ASSET ALLOCATOR
    # ═══════════════════════════════════════════════════════════════

    async def allocate_assets(
        self,
        assets: list[dict[str, Any]],
        risk_profile: str = "moderate",
        custom_weights: dict[str, float] | None = None,
        returns_matrix: list[list[float]] | None = None,
    ) -> AssetAllocationResult:
        """Allocate assets across classes based on risk profile.

        Supports crypto, gold, forex, bonds, and equities.
        Three risk profiles:
          - Conservative: 10% crypto, 30% gold, 25% forex, 25% bonds, 10% equities
          - Moderate:     25% crypto, 20% gold, 15% forex, 15% bonds, 25% equities
          - Aggressive:   50% crypto, 10% gold, 10% forex, 5% bonds, 25% equities

        Args:
            assets: List of asset dicts with at least:
                - "symbol": str
                - "asset_class": str ("crypto", "gold", "forex", "bonds", "equities")
            risk_profile: "conservative", "moderate", or "aggressive".
            custom_weights: Override weights for specific assets.
            returns_matrix: Historical returns for inverse-vol weighting within classes.

        Returns:
            AssetAllocationResult with weights, class breakdown, and rationale.
        """

        def _run() -> AssetAllocationResult:
            profile = risk_profile.lower()
            if profile not in self.RISK_PROFILES:
                profile = "moderate"

            class_weights = dict(self.RISK_PROFILES[profile])

            # Group assets by class
            assets_by_class: dict[str, list[dict[str, Any]]] = {}
            for asset in assets:
                cls = asset.get("asset_class", "crypto").lower()
                assets_by_class.setdefault(cls, []).append(asset)

            # Compute per-asset weights
            weights: dict[str, float] = {}
            for cls, class_w in class_weights.items():
                cls_assets = assets_by_class.get(cls, [])
                if not cls_assets:
                    continue

                n = len(cls_assets)
                if custom_weights:
                    custom_sum = sum(
                        custom_weights.get(a["symbol"], 0.0) for a in cls_assets
                    )
                    remaining = max(0.0, class_w - custom_sum)
                    unspecified = [
                        a for a in cls_assets if a["symbol"] not in custom_weights
                    ]
                    equal_share = remaining / max(len(unspecified), 1)

                    for a in cls_assets:
                        sym = a["symbol"]
                        if sym in custom_weights:
                            weights[sym] = custom_weights[sym]
                        else:
                            weights[sym] = equal_share
                elif returns_matrix and len(returns_matrix[0]) >= len(assets):
                    # Inverse volatility weighting within class
                    returns = np.array(returns_matrix)
                    sym_list = [a["symbol"] for a in assets]
                    inv_vols = []
                    for a in cls_assets:
                        idx = (
                            sym_list.index(a["symbol"])
                            if a["symbol"] in sym_list
                            else -1
                        )
                        if 0 <= idx < returns.shape[1]:
                            vol = np.std(returns[:, idx])
                            inv_vols.append(1.0 / max(vol, 1e-10))
                        else:
                            inv_vols.append(1.0)

                    total_inv = sum(inv_vols)
                    for a, iv in zip(cls_assets, inv_vols):
                        weights[a["symbol"]] = (
                            class_w * (iv / total_inv) if total_inv > 0 else class_w / n
                        )
                else:
                    # Equal weight within class
                    for a in cls_assets:
                        weights[a["symbol"]] = class_w / n

            # Normalize
            total_w = sum(weights.values())
            if total_w > 0:
                weights = {k: v / total_w for k, v in weights.items()}

            # Compute expected metrics if returns available
            expected_return = 0.0
            expected_vol = 0.0
            if returns_matrix:
                returns = np.array(returns_matrix)
                sym_list = [a["symbol"] for a in assets]
                weight_vec = np.array([weights.get(s, 0.0) for s in sym_list])
                mean_rets = np.mean(returns, axis=0) * 252
                cov = np.cov(returns.T) * 252
                expected_return = float(weight_vec @ mean_rets)
                expected_vol = float(np.sqrt(weight_vec @ cov @ weight_vec))

            # Asset class breakdown
            breakdown: dict[str, float] = {}
            for asset in assets:
                cls = asset.get("asset_class", "crypto").lower()
                breakdown[cls] = breakdown.get(cls, 0.0) + weights.get(
                    asset["symbol"], 0.0
                )

            rationale = (
                f"Risk profile '{profile}' allocation: "
                + ", ".join(f"{cls}={w:.1%}" for cls, w in class_weights.items())
                + f". {len(weights)} assets across {len(breakdown)} classes."
            )

            return AssetAllocationResult(
                weights=weights,
                risk_profile=profile,
                expected_return=expected_return,
                expected_volatility=expected_vol,
                asset_class_breakdown=breakdown,
                rationale=rationale,
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ═══════════════════════════════════════════════════════════════
    # 5. DIVERSIFICATION SCORER
    # ═══════════════════════════════════════════════════════════════

    async def score_diversification(
        self,
        weights: dict[str, float],
        returns_matrix: list[list[float]] | None = None,
        symbols: list[str] | None = None,
    ) -> DiversificationResult:
        """Score portfolio diversification using multiple metrics.

        Metrics:
          - HHI (Herfindahl-Hirschman Index): Σ(wᵢ²)
          - Effective N: 1/HHI
          - Correlation diversification ratio: σ_p / Σ(wᵢ·σᵢ)
          - Average pairwise correlation
          - Overall diversification score (0-100)

        Args:
            weights: Portfolio weights (symbol → weight).
            returns_matrix: Historical returns (rows=periods, cols=assets).
            symbols: Asset symbols (order must match returns_matrix columns).

        Returns:
            DiversificationResult with HHI, correlations, score, and recommendations.
        """

        def _run() -> DiversificationResult:
            syms = symbols or list(weights.keys())
            n = len(syms)
            w = np.array([weights.get(s, 0.0) for s in syms])

            # HHI and effective N
            hhi = float(np.sum(w**2))
            effective_n = 1.0 / hhi if hhi > 0 else 0.0

            # Top concentration
            sorted_assets = sorted(weights.items(), key=lambda x: x[1], reverse=True)
            concentration = [
                {
                    "symbol": sym,
                    "weight": round(wt, 6),
                    "pct": round(wt * 100, 2),
                }
                for sym, wt in sorted_assets[:5]
            ]

            avg_corr = 0.0
            max_corr = 0.0
            min_corr = 0.0
            corr_div_ratio = 0.0

            if returns_matrix and len(returns_matrix) > 1:
                returns = np.array(returns_matrix)
                if returns.shape[1] >= n:
                    corr_matrix = np.corrcoef(returns[:, :n].T)
                    mask = ~np.eye(n, dtype=bool)
                    corr_values = corr_matrix[mask]
                    avg_corr = float(np.mean(corr_values))
                    max_corr = float(np.max(corr_values))
                    min_corr = float(np.min(corr_values))

                    # Diversification ratio: σ_p / Σ(wᵢ·σᵢ)
                    asset_vols = np.std(returns[:, :n], axis=0)
                    weighted_vol_sum = float(w @ asset_vols)
                    port_vol = float(np.sqrt(w @ np.cov(returns[:, :n].T) @ w))
                    corr_div_ratio = (
                        port_vol / weighted_vol_sum if weighted_vol_sum > 0 else 1.0
                    )

            # Diversification score (0-100)
            hhi_score = max(0, (1 - hhi) * 100) * 0.4
            corr_score = max(0, (1 - avg_corr) * 100) * 0.4
            en_score = min(100, effective_n / max(n, 1) * 100) * 0.2
            div_score = hhi_score + corr_score + en_score

            # Recommendations
            recs = []
            if hhi > 0.25:
                top = concentration[0] if concentration else {}
                recs.append(
                    f"Concentration risk: top asset ({top.get('symbol', '?')}) "
                    f"holds {top.get('pct', 0):.1f}%. Consider reducing."
                )
            if avg_corr > 0.7:
                recs.append(
                    f"High average correlation ({avg_corr:.2f}). "
                    "Add uncorrelated assets."
                )
            if effective_n < 3:
                recs.append(
                    f"Effective diversification is only {effective_n:.1f} assets. "
                    "Add more positions."
                )
            if corr_div_ratio > 0.9:
                recs.append(
                    "Diversification ratio near 1.0 — assets move together. "
                    "Seek negative-correlation assets."
                )
            if n < 5:
                recs.append(
                    f"Only {n} assets. Consider expanding to 8-15 for better "
                    "diversification."
                )
            if not recs:
                recs.append("Portfolio diversification looks healthy.")

            return DiversificationResult(
                hhi=hhi,
                effective_n=effective_n,
                correlation_diversification=corr_div_ratio,
                average_correlation=avg_corr,
                max_correlation=max_corr,
                min_correlation=min_corr,
                concentration_assets=concentration,
                diversification_score=round(div_score, 1),
                recommendations=recs,
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ═══════════════════════════════════════════════════════════════
    # 6. RISK PARITY
    # ═══════════════════════════════════════════════════════════════

    async def risk_parity(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
        method: str = "equal_risk_contribution",
    ) -> RiskParityResult:
        """Compute risk parity portfolio weights.

        Two methods:
          1. Equal Risk Contribution (ERC): Each asset contributes equally
             to total portfolio risk. Solved iteratively.
          2. Inverse Volatility: Weight proportional to 1/σᵢ.
             Simple closed-form solution.

        Args:
            symbols: List of asset symbols.
            returns_matrix: Historical returns (rows=periods, cols=assets).
            method: "equal_risk_contribution" or "inverse_volatility".

        Returns:
            RiskParityResult with weights and risk contribution breakdown.
        """
        if not symbols or not returns_matrix:
            return RiskParityResult(weights={}, method=method)

        if method == "inverse_volatility":
            return await self._risk_parity_inv_vol(symbols, returns_matrix)
        else:
            return await self._risk_parity_erc(symbols, returns_matrix)

    async def _risk_parity_inv_vol(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
    ) -> RiskParityResult:
        """Inverse volatility weighting — simple risk parity approximation."""

        def _run() -> RiskParityResult:
            returns = np.array(returns_matrix)
            n = len(symbols)

            vols = np.std(returns, axis=0) * np.sqrt(252)
            inv_vols = 1.0 / np.maximum(vols, 1e-10)
            weights = inv_vols / np.sum(inv_vols)

            # Compute risk contributions
            cov = np.cov(returns.T) * 252
            port_vol = float(np.sqrt(weights @ cov @ weights))

            marginal_risk = cov @ weights / port_vol if port_vol > 0 else np.zeros(n)
            risk_contrib = weights * marginal_risk
            total_rc = np.sum(risk_contrib)
            rc_pct = risk_contrib / total_rc if total_rc > 0 else np.zeros(n)

            weight_dict = {
                symbols[i]: float(weights[i]) for i in range(n) if weights[i] > 1e-6
            }
            rc_dict = {symbols[i]: float(risk_contrib[i]) for i in range(n)}
            rcp_dict = {symbols[i]: float(rc_pct[i]) * 100 for i in range(n)}

            return RiskParityResult(
                weights=weight_dict,
                risk_contributions=rc_dict,
                risk_contribution_pct=rcp_dict,
                total_portfolio_risk=port_vol,
                method="inverse_volatility",
                iterations=0,
                converged=True,
                target_risk_budget=round(100.0 / n, 2),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _risk_parity_erc(
        self,
        symbols: list[str],
        returns_matrix: list[list[float]],
    ) -> RiskParityResult:
        """Equal Risk Contribution (ERC) — iterative optimization.

        Minimizes the sum of squared differences between each asset's
        risk contribution and the target (1/N).
        """
        from scipy.optimize import minimize

        def _run() -> RiskParityResult:
            returns = np.array(returns_matrix)
            n = len(symbols)
            cov = np.cov(returns.T) * 252
            target_rc = 1.0 / n

            def risk_parity_objective(weights: np.ndarray) -> float:
                """Sum of squared deviation from equal risk contribution."""
                port_vol = np.sqrt(weights @ cov @ weights)
                if port_vol < 1e-10:
                    return 1e10
                marginal = cov @ weights / port_vol
                rc = weights * marginal
                total_rc = np.sum(rc)
                rc_pct = rc / total_rc if total_rc > 0 else rc
                return float(np.sum((rc_pct - target_rc) ** 2))

            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
            bounds = [(1e-6, 1.0)] * n
            x0 = np.ones(n) / n

            result = minimize(
                risk_parity_objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={
                    "maxiter": self._config["risk_parity"]["max_iterations"],
                    "ftol": self._config["risk_parity"]["tolerance"],
                },
            )

            opt_w = result.x
            port_vol = float(np.sqrt(opt_w @ cov @ opt_w))

            marginal = cov @ opt_w / port_vol if port_vol > 0 else np.zeros(n)
            risk_contrib = opt_w * marginal
            total_rc = np.sum(risk_contrib)
            rc_pct = risk_contrib / total_rc if total_rc > 0 else np.zeros(n)

            weight_dict = {
                symbols[i]: float(opt_w[i]) for i in range(n) if opt_w[i] > 1e-6
            }
            rc_dict = {symbols[i]: float(risk_contrib[i]) for i in range(n)}
            rcp_dict = {symbols[i]: float(rc_pct[i]) * 100 for i in range(n)}

            return RiskParityResult(
                weights=weight_dict,
                risk_contributions=rc_dict,
                risk_contribution_pct=rcp_dict,
                total_portfolio_risk=port_vol,
                method="equal_risk_contribution",
                iterations=result.nit if hasattr(result, "nit") else 0,
                converged=result.success,
                target_risk_budget=round(target_rc * 100, 2),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ═══════════════════════════════════════════════════════════════
    # cuFOLIO HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _cufolio_available(self) -> bool:
        """Check if cuFOLIO GPU backend is available."""
        try:
            from src.backends.python.cufolio_backend import CUFOLIO_AVAILABLE

            return CUFOLIO_AVAILABLE
        except ImportError:
            return False

    def _get_cufolio(self):
        """Get or create the cuFOLIO backend instance."""
        if self._cufolio is None:
            from src.backends.python.cufolio_backend import CuFOLIOBackend

            self._cufolio = CuFOLIOBackend(config=self._config)
        return self._cufolio

    # ═══════════════════════════════════════════════════════════════
    # STATUS / HEALTH
    # ═══════════════════════════════════════════════════════════════

    def status(self) -> dict[str, Any]:
        """Return portfolio tools status."""
        return {
            "tools": [
                "mean_cvar_optimize",
                "black_litterman",
                "check_rebalance",
                "allocate_assets",
                "score_diversification",
                "risk_parity",
            ],
            "gpu_accelerated": self._cufolio_available(),
            "risk_profiles": list(self.RISK_PROFILES.keys()),
            "config": self._config,
        }
