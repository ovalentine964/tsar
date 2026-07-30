"""
TSAR Domain Tools — Risk Management Tools.

What the agent PROTECTS. Extended risk tools beyond the basic
PythonRiskEngine, providing portfolio-level risk analytics.

Tools:
  - Portfolio Correlation Matrix — cross-asset correlation analysis
  - Exposure Calculator — total, per-asset, per-sector exposure
  - Circuit Breaker — multi-level drawdown protection
  - Value at Risk (VaR) — parametric and historical VaR
  - Conditional VaR (CVaR) — expected shortfall
  - Stress Testing — scenario-based portfolio stress tests
  - Margin Calculator — leverage and margin requirements
  - Risk-Adjusted Returns — Sharpe, Sortino, Calmar, Information Ratio

All tools are deterministic — no LLM, no external calls.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CorrelationMatrixResult:
    """Portfolio correlation matrix.

    Attributes:
        symbols: Asset symbols.
        matrix: Correlation matrix as nested dict.
        avg_correlation: Average pairwise correlation.
        max_correlation: Maximum pairwise correlation.
        min_correlation: Minimum pairwise correlation.
        diversification_score: Diversification benefit (0-1).
            Lower average correlation = better diversification.
    """

    symbols: tuple[str, ...]
    matrix: dict[str, dict[str, float]]
    avg_correlation: float
    max_correlation: float
    min_correlation: float
    diversification_score: float


@dataclass(frozen=True)
class ExposureResult:
    """Portfolio exposure breakdown.

    Attributes:
        total_exposure_usd: Total notional exposure in USD.
        long_exposure_usd: Total long exposure in USD.
        short_exposure_usd: Total short exposure in USD.
        net_exposure_usd: Net exposure (long - short).
        gross_exposure_usd: Gross exposure (long + short).
        exposure_by_asset: Per-asset exposure breakdown.
        exposure_by_sector: Per-sector exposure breakdown.
        leverage: Effective leverage (gross / equity).
        concentration_risk: Largest single-asset concentration (0-1).
    """

    total_exposure_usd: float
    long_exposure_usd: float
    short_exposure_usd: float
    net_exposure_usd: float
    gross_exposure_usd: float
    exposure_by_asset: dict[str, float]
    exposure_by_sector: dict[str, float]
    leverage: float
    concentration_risk: float


@dataclass(frozen=True)
class VaRResult:
    """Value at Risk calculation.

    Attributes:
        var_95: 95% VaR (5% chance of exceeding this loss).
        var_99: 99% VaR (1% chance of exceeding this loss).
        cvar_95: Conditional VaR at 95% (expected loss beyond VaR).
        cvar_99: Conditional VaR at 99%.
        method: Calculation method ("parametric", "historical", "monte_carlo").
        holding_period: Holding period in days.
        confidence: Confidence level used.
    """

    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    method: str
    holding_period: int = 1
    confidence: float = 0.95


@dataclass(frozen=True)
class StressTestResult:
    """Stress test scenario result.

    Attributes:
        scenario: Scenario name.
        description: Scenario description.
        portfolio_impact_usd: Portfolio impact in USD.
        portfolio_impact_pct: Portfolio impact as percentage.
        worst_position: Position with largest loss.
        worst_position_loss: Loss on worst position.
        recovery_estimate_days: Estimated recovery time in days.
    """

    scenario: str
    description: str
    portfolio_impact_usd: float
    portfolio_impact_pct: float
    worst_position: str = ""
    worst_position_loss: float = 0.0
    recovery_estimate_days: int = 0


@dataclass(frozen=True)
class MarginRequirement:
    """Margin requirement calculation.

    Attributes:
        symbol: Trading pair.
        position_size: Position size in base asset.
        notional_value: Notional value in USD.
        initial_margin: Initial margin required.
        maintenance_margin: Maintenance margin required.
        margin_ratio: Margin as percentage of notional.
        liquidation_price: Estimated liquidation price.
        free_margin: Available margin after this position.
        margin_level: Margin level percentage.
    """

    symbol: str
    position_size: float
    notional_value: float
    initial_margin: float
    maintenance_margin: float
    margin_ratio: float
    liquidation_price: float
    free_margin: float
    margin_level: float


@dataclass(frozen=True)
class RiskAdjustedReturns:
    """Risk-adjusted return metrics.

    Attributes:
        total_return: Total return percentage.
        annualized_return: Annualized return percentage.
        volatility: Annualized volatility.
        sharpe_ratio: Sharpe ratio (excess return / volatility).
        sortino_ratio: Sortino ratio (excess return / downside dev).
        calmar_ratio: Calmar ratio (return / max drawdown).
        max_drawdown: Maximum drawdown percentage.
        win_rate: Win rate percentage.
        profit_factor: Gross profit / gross loss.
        expectancy: Expected value per trade.
    """

    total_return: float
    annualized_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy: float


@dataclass(frozen=True)
class CircuitBreakerStatus:
    """Circuit breaker status.

    Attributes:
        level: Current level ("GREEN", "YELLOW", "ORANGE", "RED").
        current_drawdown_pct: Current drawdown from HWM.
        daily_pnl_pct: Today's P&L as percentage.
        trading_allowed: Whether new trades are permitted.
        position_size_multiplier: Size adjustment (1.0 = normal).
        consecutive_losses: Number of consecutive losing trades.
        time_since_last_trade_s: Seconds since last trade.
        reason: Reason for current level.
    """

    level: str
    current_drawdown_pct: float
    daily_pnl_pct: float
    trading_allowed: bool
    position_size_multiplier: float
    consecutive_losses: int
    time_since_last_trade_s: float
    reason: str


# ═══════════════════════════════════════════════════════════════════════
# ASSET CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

_ASSET_SECTORS: dict[str, str] = {
    "BTC": "store_of_value",
    "ETH": "smart_contract",
    "SOL": "smart_contract",
    "BNB": "exchange",
    "XRP": "payment",
    "ADA": "smart_contract",
    "DOGE": "meme",
    "DOT": "interoperability",
    "AVAX": "smart_contract",
    "MATIC": "layer2",
    "LINK": "oracle",
    "UNI": "defi",
    "AAVE": "defi",
    "MKR": "defi",
    "COMP": "defi",
    "CRV": "defi",
    "SNX": "defi",
    "ATOM": "interoperability",
    "NEAR": "smart_contract",
    "FTM": "smart_contract",
}


# ═══════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT TOOLS
# ═══════════════════════════════════════════════════════════════════════


class RiskManagementTools:
    """Extended risk management tools for portfolio-level analysis.

    Provides correlation analysis, exposure calculation, VaR, stress
    testing, margin requirements, and risk-adjusted return metrics.
    """

    description = "Risk management: correlation, exposure, VaR, stress testing, margin, risk-adjusted returns"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        # Exposure limits (from config or defaults)
        self._max_total_exposure_pct = self._config.get("max_total_exposure_pct", 2.0)  # 200% gross
        self._max_single_asset_pct = self._config.get("max_single_asset_pct", 0.30)   # 30%
        self._max_sector_pct = self._config.get("max_sector_pct", 0.50)               # 50%
        self._max_leverage = self._config.get("max_leverage", 3.0)                     # 3x

    # ── Portfolio Correlation Matrix ─────────────────────────────────

    def compute_correlation_matrix(
        self,
        returns: dict[str, pd.Series],
        min_periods: int = 20,
    ) -> CorrelationMatrixResult:
        """Compute pairwise correlation matrix for portfolio assets.

        Uses log returns for stable correlation estimation.
        Identifies diversification opportunities and concentration risk.

        Args:
            returns: Dict mapping symbol to returns series.
            min_periods: Minimum observations for valid correlation.

        Returns:
            CorrelationMatrixResult with full matrix and summary stats.
        """
        if not returns:
            return CorrelationMatrixResult(
                symbols=(), matrix={}, avg_correlation=0,
                max_correlation=0, min_correlation=0, diversification_score=1,
            )

        symbols = list(returns.keys())
        df = pd.DataFrame(returns)
        corr_df = df.corr(min_periods=min_periods)

        matrix: dict[str, dict[str, float]] = {}
        correlations: list[float] = []

        for s1 in symbols:
            matrix[s1] = {}
            for s2 in symbols:
                val = float(corr_df.loc[s1, s2]) if s1 in corr_df.index and s2 in corr_df.columns else 0.0
                matrix[s1][s2] = round(val, 4)
                if s1 < s2:  # Avoid double counting
                    correlations.append(val)

        avg_corr = float(np.mean(correlations)) if correlations else 0.0
        max_corr = float(np.max(correlations)) if correlations else 0.0
        min_corr = float(np.min(correlations)) if correlations else 0.0

        # Diversification score: 1 - avg_correlation
        diversification = max(0.0, 1.0 - abs(avg_corr))

        return CorrelationMatrixResult(
            symbols=tuple(symbols),
            matrix=matrix,
            avg_correlation=round(avg_corr, 4),
            max_correlation=round(max_corr, 4),
            min_correlation=round(min_corr, 4),
            diversification_score=round(diversification, 4),
        )

    # ── Exposure Calculator ──────────────────────────────────────────

    def calculate_exposure(
        self,
        positions: list[dict[str, Any]],
        equity: float,
    ) -> ExposureResult:
        """Calculate total portfolio exposure breakdown.

        Computes long/short exposure, per-asset and per-sector breakdown,
        effective leverage, and concentration risk.

        Args:
            positions: List of position dicts with keys:
                symbol, side, quantity, current_price.
            equity: Current portfolio equity.

        Returns:
            ExposureResult with full exposure breakdown.
        """
        if not positions:
            return ExposureResult(
                total_exposure_usd=0, long_exposure_usd=0, short_exposure_usd=0,
                net_exposure_usd=0, gross_exposure_usd=0,
                exposure_by_asset={}, exposure_by_sector={},
                leverage=0, concentration_risk=0,
            )

        long_usd = 0.0
        short_usd = 0.0
        by_asset: dict[str, float] = {}

        for pos in positions:
            symbol = pos.get("symbol", "")
            side = pos.get("side", "buy")
            qty = float(pos.get("quantity", 0))
            price = float(pos.get("current_price", 0))

            notional = abs(qty * price)
            base = symbol.split("/")[0] if "/" in symbol else symbol

            if side == "buy":
                long_usd += notional
            else:
                short_usd += notional

            by_asset[base] = by_asset.get(base, 0) + notional

        gross = long_usd + short_usd
        net = long_usd - short_usd

        # Sector breakdown
        by_sector: dict[str, float] = {}
        for asset, notional in by_asset.items():
            sector = _ASSET_SECTORS.get(asset.upper(), "other")
            by_sector[sector] = by_sector.get(sector, 0) + notional

        # Leverage
        leverage = gross / equity if equity > 0 else 0

        # Concentration risk: largest single-asset / gross
        max_asset = max(by_asset.values()) if by_asset else 0
        concentration = max_asset / gross if gross > 0 else 0

    def check_exposure_limits(
        self,
        exposure: ExposureResult,
    ) -> dict[str, Any]:
        """Check if portfolio exposure exceeds configured limits.

        Args:
            exposure: ExposureResult from calculate_exposure.

        Returns:
            Dict with violations and warnings.
        """
        violations: list[str] = []
        warnings: list[str] = []

        # Check total gross exposure
        if exposure.total_exposure_usd > 0:
            # Leverage check
            if exposure.leverage > self._max_leverage:
                violations.append(
                    f"Leverage {exposure.leverage:.2f}x > max {self._max_leverage:.1f}x"
                )

        # Check per-asset concentration
        for asset, notional in exposure.exposure_by_asset.items():
            asset_pct = notional / exposure.total_exposure_usd if exposure.total_exposure_usd > 0 else 0
            if asset_pct > self._max_single_asset_pct:
                violations.append(
                    f"Asset {asset} concentration {asset_pct:.1%} > max {self._max_single_asset_pct:.1%}"
                )
            elif asset_pct > self._max_single_asset_pct * 0.8:
                warnings.append(
                    f"Asset {asset} concentration {asset_pct:.1%} approaching max"
                )

        # Check per-sector concentration
        for sector, notional in exposure.exposure_by_sector.items():
            sector_pct = notional / exposure.total_exposure_usd if exposure.total_exposure_usd > 0 else 0
            if sector_pct > self._max_sector_pct:
                violations.append(
                    f"Sector {sector} concentration {sector_pct:.1%} > max {self._max_sector_pct:.1%}"
                )

        return {
            "within_limits": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "max_leverage": self._max_leverage,
            "max_single_asset_pct": self._max_single_asset_pct,
            "max_sector_pct": self._max_sector_pct,
        }

        return ExposureResult(
            total_exposure_usd=round(gross, 2),
            long_exposure_usd=round(long_usd, 2),
            short_exposure_usd=round(short_usd, 2),
            net_exposure_usd=round(net, 2),
            gross_exposure_usd=round(gross, 2),
            exposure_by_asset={k: round(v, 2) for k, v in by_asset.items()},
            exposure_by_sector={k: round(v, 2) for k, v in by_sector.items()},
            leverage=round(leverage, 2),
            concentration_risk=round(concentration, 4),
        )

    # ── Value at Risk ────────────────────────────────────────────────

    def calculate_var(
        self,
        returns: pd.Series,
        portfolio_value: float,
        holding_period: int = 1,
        method: str = "parametric",
    ) -> VaRResult:
        """Calculate Value at Risk (VaR) and Conditional VaR.

        VaR answers: "What is the maximum loss at X% confidence?"
        CVaR answers: "If we exceed VaR, what's the expected loss?"

        Args:
            returns: Historical return series.
            portfolio_value: Current portfolio value.
            holding_period: Holding period in days.
            method: "parametric" (normal distribution) or "historical".

        Returns:
            VaRResult with VaR and CVaR at 95% and 99% confidence.
        """
        if returns.empty or portfolio_value <= 0:
            return VaRResult(
                var_95=0, var_99=0, cvar_95=0, cvar_99=0,
                method=method, holding_period=holding_period,
            )

        # Scale returns for holding period
        if holding_period > 1:
            scaled_returns = returns * math.sqrt(holding_period)
        else:
            scaled_returns = returns

        if method == "parametric":
            mu = float(scaled_returns.mean())
            sigma = float(scaled_returns.std(ddof=1))

            # Z-scores for confidence levels
            z_95 = 1.645
            z_99 = 2.326

            var_95 = portfolio_value * (mu - z_95 * sigma)
            var_99 = portfolio_value * (mu - z_99 * sigma)

            # CVaR (expected shortfall) for normal distribution
            from scipy.stats import norm
            cvar_95 = portfolio_value * (mu - sigma * norm.pdf(z_95) / 0.05)
            cvar_99 = portfolio_value * (mu - sigma * norm.pdf(z_99) / 0.01)

        else:  # Historical
            sorted_returns = np.sort(scaled_returns)
            n = len(sorted_returns)

            var_95 = portfolio_value * float(sorted_returns[int(n * 0.05)])
            var_99 = portfolio_value * float(sorted_returns[int(n * 0.01)])

            # CVaR = average of returns below VaR
            cvar_95 = portfolio_value * float(np.mean(sorted_returns[:int(n * 0.05)]))
            cvar_99 = portfolio_value * float(np.mean(sorted_returns[:int(n * 0.01)]))

        return VaRResult(
            var_95=round(abs(var_95), 2),
            var_99=round(abs(var_99), 2),
            cvar_95=round(abs(cvar_95), 2),
            cvar_99=round(abs(cvar_99), 2),
            method=method,
            holding_period=holding_period,
        )

    # ── Stress Testing ───────────────────────────────────────────────

    def run_stress_test(
        self,
        positions: list[dict[str, Any]],
        equity: float,
        scenarios: list[dict[str, Any]] | None = None,
    ) -> list[StressTestResult]:
        """Run stress test scenarios on the portfolio.

        Tests portfolio resilience under extreme market conditions.

        Args:
            positions: Current positions.
            equity: Current portfolio equity.
            scenarios: Custom scenarios (uses defaults if None).

        Returns:
            List of StressTestResult, one per scenario.
        """
        if scenarios is None:
            scenarios = [
                {
                    "name": "crypto_crash_30pct",
                    "description": "Crypto market crashes 30% (Luna-style)",
                    "shocks": {"BTC": -0.30, "ETH": -0.35, "SOL": -0.40, "default": -0.30},
                },
                {
                    "name": "flash_crash_15pct",
                    "description": "Flash crash, 15% drop in minutes",
                    "shocks": {"default": -0.15},
                },
                {
                    "name": "stablecoin_depeg",
                    "description": "Major stablecoin depegs, 10% market drop",
                    "shocks": {"default": -0.10},
                },
                {
                    "name": "fed_hawkish",
                    "description": "Fed raises rates unexpectedly, 20% drop",
                    "shocks": {"BTC": -0.20, "ETH": -0.25, "default": -0.20},
                },
                {
                    "name": "black_swan_50pct",
                    "description": "Black swan event, 50% market crash",
                    "shocks": {"default": -0.50},
                },
            ]

        results: list[StressTestResult] = []

        for scenario in scenarios:
            name = scenario.get("name", "unknown")
            desc = scenario.get("description", "")
            shocks = scenario.get("shocks", {"default": -0.20})

            total_impact = 0.0
            worst_loss = 0.0
            worst_symbol = ""

            for pos in positions:
                symbol = pos.get("symbol", "")
                side = pos.get("side", "buy")
                qty = float(pos.get("quantity", 0))
                price = float(pos.get("current_price", 0))
                notional = qty * price

                base = symbol.split("/")[0] if "/" in symbol else symbol
                shock = shocks.get(base, shocks.get("default", -0.20))

                # Long positions lose on negative shocks, shorts gain
                if side == "buy":
                    impact = notional * shock
                else:
                    impact = notional * (-shock)

                total_impact += impact

                if impact < worst_loss:
                    worst_loss = impact
                    worst_symbol = symbol

            impact_pct = total_impact / equity * 100 if equity > 0 else 0

            # Recovery estimate (simple: assume 5% monthly recovery)
            recovery_days = 0
            if total_impact < 0:
                months_to_recover = abs(impact_pct) / 5
                recovery_days = int(months_to_recover * 30)

            results.append(StressTestResult(
                scenario=name,
                description=desc,
                portfolio_impact_usd=round(total_impact, 2),
                portfolio_impact_pct=round(impact_pct, 2),
                worst_position=worst_symbol,
                worst_position_loss=round(worst_loss, 2),
                recovery_estimate_days=recovery_days,
            ))

        return results

    # ── Margin Calculator ────────────────────────────────────────────

    def calculate_margin(
        self,
        symbol: str,
        position_size: float,
        entry_price: float,
        leverage: float,
        side: str = "buy",
        maintenance_margin_rate: float = 0.005,
    ) -> MarginRequirement:
        """Calculate margin requirements for a leveraged position.

        Computes initial margin, maintenance margin, liquidation price,
        and available margin.

        Args:
            symbol: Trading pair.
            position_size: Position size in base asset.
            entry_price: Entry price.
            leverage: Leverage multiplier.
            side: "buy" or "sell".
            maintenance_margin_rate: Maintenance margin rate.

        Returns:
            MarginRequirement with all margin details.
        """
        notional = position_size * entry_price
        initial_margin = notional / leverage
        maintenance_margin = notional * maintenance_margin_rate

        # Liquidation price
        if side == "buy":
            # Long: liquidation when loss = initial_margin - maintenance_margin
            margin_buffer = initial_margin - maintenance_margin
            liq_price = entry_price - (margin_buffer / position_size) if position_size > 0 else 0
        else:
            margin_buffer = initial_margin - maintenance_margin
            liq_price = entry_price + (margin_buffer / position_size) if position_size > 0 else 0

        margin_ratio = initial_margin / notional * 100 if notional > 0 else 0

        return MarginRequirement(
            symbol=symbol,
            position_size=position_size,
            notional_value=round(notional, 2),
            initial_margin=round(initial_margin, 2),
            maintenance_margin=round(maintenance_margin, 2),
            margin_ratio=round(margin_ratio, 2),
            liquidation_price=round(max(0, liq_price), 8),
            free_margin=round(initial_margin, 2),
            margin_level=round(100 * leverage, 2),
        )

    # ── Risk-Adjusted Returns ────────────────────────────────────────

    def calculate_risk_adjusted_returns(
        self,
        equity_curve: list[float],
        risk_free_rate: float = 0.04,
        trading_days_per_year: int = 365,
    ) -> RiskAdjustedReturns:
        """Calculate comprehensive risk-adjusted return metrics.

        Computes Sharpe, Sortino, Calmar ratios and other key metrics
        from an equity curve.

        Args:
            equity_curve: Portfolio equity at each period.
            risk_free_rate: Annualized risk-free rate.
            trading_days_per_year: Trading days per year.

        Returns:
            RiskAdjustedReturns with all metrics.
        """
        if len(equity_curve) < 2:
            return RiskAdjustedReturns(
                total_return=0, annualized_return=0, volatility=0,
                sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
                max_drawdown=0, win_rate=0, profit_factor=0, expectancy=0,
            )

        eq = np.array(equity_curve, dtype=float)
        returns = np.diff(eq) / eq[:-1]
        returns = returns[np.isfinite(returns)]

        if len(returns) < 2:
            return RiskAdjustedReturns(
                total_return=0, annualized_return=0, volatility=0,
                sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
                max_drawdown=0, win_rate=0, profit_factor=0, expectancy=0,
            )

        # Total return
        total_return = (eq[-1] - eq[0]) / eq[0]

        # Annualized return
        n_periods = len(returns)
        years = n_periods / trading_days_per_year
        ann_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # Volatility
        vol = float(np.std(returns, ddof=1)) * math.sqrt(trading_days_per_year)

        # Sharpe ratio
        daily_rf = risk_free_rate / trading_days_per_year
        excess = returns - daily_rf
        sharpe = float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(trading_days_per_year)) if np.std(excess) > 0 else 0

        # Sortino ratio
        downside = excess[excess < 0]
        if len(downside) > 0:
            downside_dev = float(np.std(downside, ddof=1))
            sortino = float(np.mean(excess) / downside_dev * math.sqrt(trading_days_per_year)) if downside_dev > 0 else 0
        else:
            sortino = float("inf") if np.mean(excess) > 0 else 0

        # Max drawdown
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak
        max_dd = float(np.max(dd))

        # Calmar ratio
        calmar = ann_return / max_dd if max_dd > 0 else float("inf")

        # Win rate
        wins = returns[returns > 0]
        losses = returns[returns <= 0]
        win_rate = len(wins) / len(returns) if len(returns) > 0 else 0

        # Profit factor
        gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0
        gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Expectancy
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
        avg_loss = abs(float(np.mean(losses))) if len(losses) > 0 else 0
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

        return RiskAdjustedReturns(
            total_return=round(total_return * 100, 2),
            annualized_return=round(ann_return * 100, 2),
            volatility=round(vol * 100, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2) if sortino != float("inf") else 999.99,
            calmar_ratio=round(calmar, 2) if calmar != float("inf") else 999.99,
            max_drawdown=round(max_dd * 100, 2),
            win_rate=round(win_rate * 100, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
            expectancy=round(expectancy * 100, 4),
        )

    # ── Circuit Breaker ──────────────────────────────────────────────

    def evaluate_circuit_breaker(
        self,
        current_equity: float,
        high_water_mark: float,
        daily_pnl: float,
        consecutive_losses: int,
        time_since_last_trade_s: float,
        max_drawdown_pct: float = 5.0,
        daily_loss_limit_pct: float = 2.0,
    ) -> CircuitBreakerStatus:
        """Evaluate circuit breaker status.

        Multi-level circuit breaker that protects capital:
        - GREEN: Normal operation
        - YELLOW: Reduce position sizes 50%
        - ORANGE: No new entries
        - RED: Kill switch, flatten everything

        Also considers consecutive losses and trading frequency.

        Args:
            current_equity: Current portfolio equity.
            high_water_mark: Peak portfolio value.
            daily_pnl: Today's P&L.
            consecutive_losses: Number of consecutive losing trades.
            time_since_last_trade_s: Seconds since last trade.
            max_drawdown_pct: Maximum drawdown percentage.
            daily_loss_limit_pct: Daily loss limit percentage.

        Returns:
            CircuitBreakerStatus with current level and trading permissions.
        """
        # Drawdown
        if high_water_mark > 0:
            drawdown_pct = (high_water_mark - current_equity) / high_water_mark * 100
        else:
            drawdown_pct = 0.0

        # Daily P&L
        daily_pnl_pct = (daily_pnl / current_equity * 100) if current_equity > 0 else 0

        # Determine level
        if drawdown_pct >= max_drawdown_pct:
            level = "RED"
            reason = f"Drawdown {drawdown_pct:.1f}% >= {max_drawdown_pct}% limit"
        elif drawdown_pct >= max_drawdown_pct * 0.6:
            level = "ORANGE"
            reason = f"Drawdown {drawdown_pct:.1f}% approaching limit"
        elif drawdown_pct >= max_drawdown_pct * 0.4:
            level = "YELLOW"
            reason = f"Drawdown {drawdown_pct:.1f}% — reducing exposure"
        elif daily_pnl_pct < -daily_loss_limit_pct:
            level = "ORANGE"
            reason = f"Daily loss {abs(daily_pnl_pct):.1f}% >= {daily_loss_limit_pct}% limit"
        elif consecutive_losses >= 5:
            level = "YELLOW"
            reason = f"{consecutive_losses} consecutive losses"
        elif consecutive_losses >= 3:
            level = "YELLOW"
            reason = f"{consecutive_losses} consecutive losses — caution"
        else:
            level = "GREEN"
            reason = "Normal operation"

        # Trading permissions and size multiplier
        if level == "RED":
            trading_allowed = False
            multiplier = 0.0
        elif level == "ORANGE":
            trading_allowed = False
            multiplier = 0.0
        elif level == "YELLOW":
            trading_allowed = True
            multiplier = 0.5
        else:
            trading_allowed = True
            multiplier = 1.0

        return CircuitBreakerStatus(
            level=level,
            current_drawdown_pct=round(drawdown_pct, 2),
            daily_pnl_pct=round(daily_pnl_pct, 2),
            trading_allowed=trading_allowed,
            position_size_multiplier=multiplier,
            consecutive_losses=consecutive_losses,
            time_since_last_trade_s=time_since_last_trade_s,
            reason=reason,
        )
