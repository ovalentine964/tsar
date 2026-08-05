"""
Market Cartographer — Cross-asset correlation and structural analysis.

Role: ANALYSIS (Level 3+)
Model Tier: T0 (correlation math) + T1 (PCA, cointegration)

Correlation pairs:
  BTC ↔ ETH, BTC ↔ SOL, ETH ↔ SOL (crypto-native)
  BTC ↔ DXY, BTC ↔ US10Y, BTC ↔ Gold (macro cross-asset)

Subscribes to: tsar:stream:regime, tsar:stream:fills
Publishes to: tsar:stream:cartography
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.agents.base import BaseAgent

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.correlation import CorrelationAnalyzer
from src.tools.fundamental import FundamentalAnalysisTools
from src.tools.market_data import MarketDataTools

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CorrelationMatrix:
    """Rolling correlation matrix between assets."""

    symbols: list[str] = field(default_factory=list)
    matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    lookback_hours: int = 72
    computed_at: float = 0.0

    def get(self, sym_a: str, sym_b: str) -> float:
        """Get correlation between two symbols."""
        return self.matrix.get(sym_a, {}).get(sym_b, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "matrix": self.matrix,
            "lookback_hours": self.lookback_hours,
            "computed_at": self.computed_at,
        }


@dataclass
class CorrelationAnomaly:
    """Detected correlation regime shift."""

    pair: str
    current_corr: float
    historical_corr: float
    z_score: float
    description: str
    severity: str = "info"  # info | warning | critical


@dataclass
class CartographyResult:
    """Full cartography cycle output."""

    crypto_correlations: CorrelationMatrix | None = None
    macro_correlations: CorrelationMatrix | None = None
    anomalies: list[CorrelationAnomaly] = field(default_factory=list)
    regime_divergence: dict[str, str] = field(default_factory=dict)
    computed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "crypto_correlations": self.crypto_correlations.to_dict()
            if self.crypto_correlations
            else None,
            "macro_correlations": self.macro_correlations.to_dict()
            if self.macro_correlations
            else None,
            "anomalies": [
                {
                    "pair": a.pair,
                    "current_corr": a.current_corr,
                    "historical_corr": a.historical_corr,
                    "z_score": a.z_score,
                    "description": a.description,
                    "severity": a.severity,
                }
                for a in self.anomalies
            ],
            "regime_divergence": self.regime_divergence,
            "computed_at": self.computed_at,
        }


# ═══════════════════════════════════════════════════════════════════════
# CORRELATION ENGINE
# ═══════════════════════════════════════════════════════════════════════


class CorrelationEngine:
    """Compute rolling correlations and detect anomalies.

    Uses log returns for stable correlation estimation.
    Supports both crypto-native (BTC↔ETH↔SOL) and macro cross-asset
    (BTC↔DXY, BTC↔US10Y) correlation pairs.
    """

    # Default crypto correlation pairs
    CRYPTO_PAIRS = [
        ("BTC/USDT", "ETH/USDT"),
        ("BTC/USDT", "SOL/USDT"),
        ("ETH/USDT", "SOL/USDT"),
    ]

    # Default macro cross-asset pairs
    MACRO_PAIRS = [
        ("BTC/USDT", "DXY"),
        ("BTC/USDT", "US10Y"),
        ("BTC/USDT", "GOLD"),
        ("DXY", "GOLD"),
        ("DXY", "US10Y"),
    ]

    def __init__(
        self,
        lookback_hours: int = 72,
        anomaly_z_threshold: float = 2.0,
        min_samples: int = 20,
    ) -> None:
        self._lookback = lookback_hours
        self._anomaly_z = anomaly_z_threshold
        self._min_samples = min_samples
        # Historical correlation cache for anomaly detection
        self._historical_corrs: dict[str, list[float]] = {}

    def compute_pairwise_correlation(
        self,
        returns_a: pd.Series,
        returns_b: pd.Series,
    ) -> float:
        """Compute Pearson correlation between two return series.

        Aligns indices and drops NaN before computing.
        """
        combined = pd.DataFrame({"a": returns_a, "b": returns_b}).dropna()
        if len(combined) < self._min_samples:
            return 0.0
        return float(combined["a"].corr(combined["b"]))

    def compute_correlation_matrix(
        self,
        returns_dict: dict[str, pd.Series],
        pairs: list[tuple[str, str]],
    ) -> CorrelationMatrix:
        """Compute correlation matrix for given pairs.

        Args:
            returns_dict: Symbol -> returns series mapping.
            pairs: List of (symbol_a, symbol_b) pairs.

        Returns:
            CorrelationMatrix with pairwise correlations.
        """
        symbols = list(set(s for pair in pairs for s in pair))
        matrix: dict[str, dict[str, float]] = {s: {} for s in symbols}

        for sym_a, sym_b in pairs:
            ret_a = returns_dict.get(sym_a)
            ret_b = returns_dict.get(sym_b)
            if ret_a is None or ret_b is None:
                continue
            corr = self.compute_pairwise_correlation(ret_a, ret_b)
            matrix[sym_a][sym_b] = round(corr, 4)
            matrix[sym_b][sym_a] = round(corr, 4)

        # Diagonal = 1.0
        for s in symbols:
            matrix[s][s] = 1.0

        return CorrelationMatrix(
            symbols=symbols,
            matrix=matrix,
            lookback_hours=self._lookback,
            computed_at=time.time(),
        )

    def detect_anomalies(
        self,
        current_matrix: CorrelationMatrix,
        pairs: list[tuple[str, str]],
    ) -> list[CorrelationAnomaly]:
        """Detect correlation regime shifts by comparing to history.

        Tracks rolling correlation history and flags pairs where the
        current correlation deviates by > z_threshold standard deviations.
        """
        anomalies: list[CorrelationAnomaly] = []

        for sym_a, sym_b in pairs:
            pair_key = f"{sym_a}:{sym_b}"
            current_corr = current_matrix.get(sym_a, sym_b)

            # Update history
            if pair_key not in self._historical_corrs:
                self._historical_corrs[pair_key] = []
            self._historical_corrs[pair_key].append(current_corr)

            history = self._historical_corrs[pair_key]
            if len(history) < 10:
                continue

            hist_mean = np.mean(history)
            hist_std = np.std(history)

            if hist_std < 0.01:
                continue

            z_score = abs(current_corr - hist_mean) / hist_std

            if z_score > self._anomaly_z:
                severity = "critical" if z_score > 3.0 else "warning"
                direction = "strengthened" if current_corr > hist_mean else "weakened"
                anomalies.append(
                    CorrelationAnomaly(
                        pair=pair_key,
                        current_corr=round(current_corr, 4),
                        historical_corr=round(hist_mean, 4),
                        z_score=round(z_score, 2),
                        description=(
                            f"{sym_a}↔{sym_b} correlation {direction}: "
                            f"{current_corr:.3f} vs historical {hist_mean:.3f} "
                            f"(z={z_score:.1f})"
                        ),
                        severity=severity,
                    )
                )

        return anomalies


# ═══════════════════════════════════════════════════════════════════════
# MARKET CARTOGRAPHER AGENT
# ═══════════════════════════════════════════════════════════════════════


class MarketCartographer(BaseAgent):
    """Map cross-asset correlations and detect structural anomalies.

    Computes rolling correlations between:
    - Crypto-native: BTC↔ETH, BTC↔SOL, ETH↔SOL
    - Macro cross-asset: BTC↔DXY, BTC↔US10Y, BTC↔GOLD

    Detects correlation regime shifts and divergence between assets.

    Configuration:
        agents.market_cartographer:
            cycle_interval_s: 300       # Compute every 5 min
            lookback_hours: 72          # 3-day rolling window
            anomaly_z_threshold: 2.0    # Z-score for anomaly detection
            macro_symbols: ["DXY", "US10Y", "GOLD"]
    """

    AGENT_NAME = "market_cartographer"
    ROLE = "ANALYSIS"

    PUBLISH_STREAM = "cartography"
    SUBSCRIBE_STREAMS = ["regime", "trades"]

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)

        carto_cfg = config.get("agents", {}).get("market_cartographer", {})
        self._cycle_interval = carto_cfg.get("cycle_interval_s", 300)
        self._lookback = carto_cfg.get("lookback_hours", 72)
        self._anomaly_z = carto_cfg.get("anomaly_z_threshold", 2.0)

        # Crypto symbols from exchange config
        self._crypto_symbols = config.get("exchange", {}).get("symbols", ["BTC/USDT", "ETH/USDT"])

        # Ensure SOL is included
        if "SOL/USDT" not in self._crypto_symbols:
            self._crypto_symbols.append("SOL/USDT")

        # Macro symbols
        self._macro_symbols = carto_cfg.get("macro_symbols", ["DXY", "US10Y", "GOLD"])

        # Engine (inline CorrelationEngine for backward compat)
        self._engine = CorrelationEngine(
            lookback_hours=self._lookback,
            anomaly_z_threshold=self._anomaly_z,
        )

        # ── Domain Tools (Tools-to-Agents Wiring) ───────
        self._correlation_analyzer: CorrelationAnalyzer | None = None
        self._market_data_tools: MarketDataTools | None = None
        self._fundamental_tools: FundamentalAnalysisTools | None = None

        # State
        self._pricing_engine = None
        self._last_scan_time = 0.0
        self._latest_result: CartographyResult | None = None

    async def on_initialize(self) -> None:
        """Initialize pricing engine and domain tools."""
        from src.interfaces import get_exchange_gateway, get_pricing_engine

        self._pricing_engine = get_pricing_engine()

        # Initialize domain tools
        try:
            gateway = get_exchange_gateway()
            self._correlation_analyzer = CorrelationAnalyzer(config=self.config)
            self._market_data_tools = MarketDataTools(
                gateway=gateway,
                config=self.config.get("market_data", {}),
            )
            self._fundamental_tools = FundamentalAnalysisTools(config=self.config)
            logger.info(
                "MarketCartographer initialized: crypto=%s, macro=%s, "
                "tools=[correlation, market_data, fundamental]",
                self._crypto_symbols,
                self._macro_symbols,
            )
        except Exception as e:
            logger.warning("MarketCartographer tool init failed: %s", e)

    async def run_cycle(self) -> None:
        """Compute cross-asset correlations and detect anomalies."""
        now = time.monotonic()
        if now - self._last_scan_time < self._cycle_interval:
            return

        if self._pricing_engine is None:
            logger.debug("MarketCartographer: pricing_engine not set, skipping")
            return

        try:
            result = await self._compute_cartography()
            self._latest_result = result
            self._last_scan_time = now

            # Publish cartography event
            await self.publish_event(
                stream="cartography",
                event_type="tsar.cartography.updated.v1",
                data=result.to_dict(),
                priority=2,
            )

            # Log anomalies
            for anomaly in result.anomalies:
                if anomaly.severity == "critical":
                    logger.warning("⚠️ CORRELATION ANOMALY: %s", anomaly.description)
                else:
                    logger.info("📊 Correlation shift: %s", anomaly.description)

        except Exception as e:
            logger.error("Cartography computation failed: %s", e, exc_info=True)

    async def _compute_cartography(self) -> CartographyResult:
        """Run full cartography cycle."""
        result = CartographyResult(computed_at=time.time())

        # ── Fetch crypto returns ──
        crypto_returns: dict[str, pd.Series] = {}
        for symbol in self._crypto_symbols:
            returns = await self._fetch_returns(symbol)
            if returns is not None:
                crypto_returns[symbol] = returns

        # ── Compute crypto correlations ──
        crypto_pairs = [
            (a, b)
            for a, b in CorrelationEngine.CRYPTO_PAIRS
            if a in crypto_returns and b in crypto_returns
        ]
        if crypto_pairs:
            result.crypto_correlations = self._engine.compute_correlation_matrix(
                crypto_returns, crypto_pairs
            )

            # Detect anomalies
            result.anomalies.extend(
                self._engine.detect_anomalies(result.crypto_correlations, crypto_pairs)
            )

        # ── Fetch macro returns (if pricing engine supports them) ──
        macro_returns: dict[str, pd.Series] = {}
        for symbol in self._macro_symbols:
            returns = await self._fetch_returns(symbol)
            if returns is not None:
                macro_returns[symbol] = returns

        # Add BTC to macro computation
        if "BTC/USDT" in crypto_returns:
            macro_returns["BTC/USDT"] = crypto_returns["BTC/USDT"]

        # ── Compute macro cross-asset correlations ──
        macro_pairs = [
            (a, b)
            for a, b in CorrelationEngine.MACRO_PAIRS
            if a in macro_returns and b in macro_returns
        ]
        if macro_pairs:
            result.macro_correlations = self._engine.compute_correlation_matrix(
                macro_returns, macro_pairs
            )
            result.anomalies.extend(
                self._engine.detect_anomalies(result.macro_correlations, macro_pairs)
            )

        # ── Detect regime divergence between crypto assets ──
        result.regime_divergence = self._detect_regime_divergence(crypto_returns)

        logger.info(
            "Cartography complete: %d crypto pairs, %d macro pairs, %d anomalies",
            len(crypto_pairs),
            len(macro_pairs),
            len(result.anomalies),
        )

        return result

    async def _fetch_returns(self, symbol: str) -> pd.Series | None:
        """Fetch OHLCV and compute log returns for a symbol."""
        try:
            ohlcv = await self._pricing_engine.get_ohlcv(symbol, "1h", limit=self._lookback + 10)
            if ohlcv is None or len(ohlcv) < 20:
                logger.debug(
                    "Insufficient data for %s (%d bars)", symbol, len(ohlcv) if ohlcv else 0
                )
                return None

            df = pd.DataFrame(ohlcv)
            returns = np.log(df["close"] / df["close"].shift(1)).dropna()
            return returns

        except Exception as e:
            logger.warning("Failed to fetch returns for %s: %s", symbol, e)
            return None

    def _detect_regime_divergence(
        self,
        crypto_returns: dict[str, pd.Series],
    ) -> dict[str, str]:
        """Detect when correlated assets diverge in behavior.

        If BTC is trending up but ETH is ranging, that's a divergence
        that may signal regime change.
        """
        divergence: dict[str, str] = {}

        if len(crypto_returns) < 2:
            return divergence

        # Compute recent momentum for each symbol
        momentum: dict[str, float] = {}
        for symbol, returns in crypto_returns.items():
            if len(returns) >= 24:
                recent = returns.iloc[-24:]  # Last 24h
                momentum[symbol] = float(recent.mean())

        # Check for divergences
        symbols = list(momentum.keys())
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                sym_a, sym_b = symbols[i], symbols[j]
                mom_a, mom_b = momentum[sym_a], momentum[sym_b]

                # Divergence: one positive, one negative with significant magnitude
                if mom_a > 0.001 and mom_b < -0.001:
                    divergence[f"{sym_a}:{sym_b}"] = (
                        f"{sym_a} bullish ({mom_a:.4f}) while {sym_b} bearish ({mom_b:.4f})"
                    )
                elif mom_a < -0.001 and mom_b > 0.001:
                    divergence[f"{sym_a}:{sym_b}"] = (
                        f"{sym_a} bearish ({mom_a:.4f}) while {sym_b} bullish ({mom_b:.4f})"
                    )

        return divergence

    def get_latest_result(self) -> CartographyResult | None:
        """Get the most recent cartography result."""
        return self._latest_result
