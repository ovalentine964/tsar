"""
Regime Detector — Classify market regime using Hidden Markov Model (HMM).

Role: ANALYSIS (Level 3+)
Model Tier: T0 (indicator math) + T1 (HMM classification)

Regime states: STRONG_TREND_UP, STRONG_TREND_DOWN, RANGING, HIGH_VOLATILITY, UNCERTAIN

Uses hmmlearn's GaussianHMM to learn regime transitions from a feature vector
of ADX, ATR%, BB width, and returns. Falls back to rule-based classification
when hmmlearn is unavailable or data is insufficient.

Subscribes to: tsar:stream:cartography
Publishes to: tsar:stream:regime
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.agents.base import BaseAgent

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.market_data import MarketDataTools
from src.tools.technical_analysis import TechnicalAnalysisTools
from src.tools.volatility import VolatilityAnalyzer
from src.tools.correlation import CorrelationAnalyzer

logger = logging.getLogger(__name__)

# Try importing hmmlearn — graceful fallback if not installed
try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn not installed — regime detection will use rule-based fallback")


# ═══════════════════════════════════════════════════════════════════════
# HMM FEATURE BUILDER
# ═══════════════════════════════════════════════════════════════════════


def _build_hmm_features(df: pd.DataFrame) -> np.ndarray | None:
    """Build feature matrix for HMM from OHLCV data.

    Features (4 dimensions):
        1. Log returns (price momentum)
        2. Normalized ATR (volatility)
        3. ADX (trend strength)
        4. Bollinger Bandwidth (range/volatility)

    Returns:
        (n_samples, 4) ndarray or None if insufficient data.
    """
    if len(df) < 30:
        return None

    try:
        # Log returns
        log_ret = np.log(df["close"] / df["close"].shift(1))

        # Normalized ATR
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        atr_pct = (atr / df["close"]) * 100

        # ADX
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
        adx_val = adx_df["ADX_14"] if adx_df is not None else pd.Series(0.0, index=df.index)

        # Bollinger Bandwidth
        bb = ta.bbands(df["close"], length=20, std=2)
        if bb is not None:
            bb_upper = bb["BBU_20_2.0"]
            bb_lower = bb["BBL_20_2.0"]
            bb_mid = bb["BBM_20_2.0"]
            bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
        else:
            bb_width = pd.Series(0.0, index=df.index)

        features = pd.DataFrame({
            "returns": log_ret,
            "atr_pct": atr_pct,
            "adx": adx_val,
            "bb_width": bb_width,
        }).dropna()

        if len(features) < 20:
            return None

        # Standardize features for HMM
        arr = features.values
        means = np.nanmean(arr, axis=0)
        stds = np.nanstd(arr, axis=0)
        stds[stds < 1e-10] = 1.0  # Avoid division by zero
        arr = (arr - means) / stds

        return arr

    except Exception as e:
        logger.warning("Failed to build HMM features: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════
# HMM REGIME CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════


class HMMRegimeClassifier:
    """Classify market regimes using a Hidden Markov Model.

    Fits a 5-state Gaussian HMM on [returns, ATR%, ADX, BB_width].
    States are mapped to human-readable regime labels based on their
    learned emission parameters.

    Falls back to rule-based classification if HMM fails or is unavailable.
    """

    REGIME_LABELS = [
        "STRONG_TREND_UP",
        "STRONG_TREND_DOWN",
        "RANGING",
        "HIGH_VOLATILITY",
        "UNCERTAIN",
    ]

    def __init__(
        self,
        n_states: int = 5,
        n_iter: int = 100,
        covariance_type: str = "full",
        retrain_interval: int = 50,
        min_samples: int = 50,
    ) -> None:
        self._n_states = n_states
        self._n_iter = n_iter
        self._covariance_type = covariance_type
        self._retrain_interval = retrain_interval
        self._min_samples = min_samples
        self._model: GaussianHMM | None = None
        self._call_count = 0
        self._state_map: dict[int, str] = {}

    def fit_predict(
        self,
        features: np.ndarray,
        current_features: np.ndarray | None = None,
    ) -> tuple[str, float, dict[str, float]]:
        """Fit HMM on features and predict current regime.

        Args:
            features: (n_samples, n_features) training data.
            current_features: (1, n_features) current observation. Uses last row if None.

        Returns:
            (regime_label, confidence, probabilities_dict)
        """
        if not HMM_AVAILABLE:
            return "UNCERTAIN", 0.0, {}

        self._call_count += 1

        # Retrain periodically
        if self._model is None or self._call_count % self._retrain_interval == 0:
            self._fit(features)

        if self._model is None:
            return "UNCERTAIN", 0.0, {}

        # Predict current state
        obs = current_features if current_features is not None else features[-1:]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                state = self._model.predict(obs)[0]
                log_probs = self._model.predict_proba(obs)[0]
        except Exception as e:
            logger.warning("HMM prediction failed: %s", e)
            return "UNCERTAIN", 0.0, {}

        regime = self._state_map.get(state, "UNCERTAIN")
        confidence = float(log_probs[state])

        # Build probability dict
        probs = {}
        for i, label in enumerate(self.REGIME_LABELS):
            # Map model states to labels
            for model_state, mapped_label in self._state_map.items():
                if mapped_label == label:
                    probs[label] = float(log_probs[model_state])
                    break
            else:
                probs[label] = 0.0

        return regime, confidence, probs

    def _fit(self, features: np.ndarray) -> None:
        """Fit the HMM model and map states to regime labels."""
        try:
            model = GaussianHMM(
                n_components=self._n_states,
                covariance_type=self._covariance_type,
                n_iter=self._n_iter,
                random_state=42,
                tol=1e-4,
            )

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model.fit(features)

            self._model = model

            # Map states to regime labels based on learned means
            # Feature order: [returns, atr_pct, adx, bb_width]
            self._state_map = self._map_states_to_regimes(model.means_)

            logger.info(
                "HMM fitted: %d states, score=%.2f, state_map=%s",
                self._n_states,
                model.score(features),
                self._state_map,
            )

        except Exception as e:
            logger.error("HMM fitting failed: %s — using rule-based fallback", e)
            self._model = None

    def _map_states_to_regimes(self, means: np.ndarray) -> dict[int, str]:
        """Map HMM states to regime labels based on emission means.

        Heuristic mapping:
            - Highest return mean → STRONG_TREND_UP
            - Lowest return mean → STRONG_TREND_DOWN
            - Highest ATR + high ADX → HIGH_VOLATILITY
            - Lowest ADX + low BB width → RANGING
            - Remaining → UNCERTAIN
        """
        n = means.shape[0]
        state_map: dict[int, str] = {}
        used_labels: set[str] = set()

        returns_mean = means[:, 0]  # column 0: returns
        atr_mean = means[:, 1]      # column 1: atr_pct
        adx_mean = means[:, 2]      # column 2: adx
        bb_mean = means[:, 3]       # column 3: bb_width

        # Sort by returns
        sorted_by_return = np.argsort(returns_mean)

        # Highest return → STRONG_TREND_UP
        up_state = int(sorted_by_return[-1])
        state_map[up_state] = "STRONG_TREND_UP"
        used_labels.add("STRONG_TREND_UP")

        # Lowest return → STRONG_TREND_DOWN
        down_state = int(sorted_by_return[0])
        if down_state not in state_map:
            state_map[down_state] = "STRONG_TREND_DOWN"
            used_labels.add("STRONG_TREND_DOWN")

        # Highest volatility (ATR + BB combined score) → HIGH_VOLATILITY
        vol_score = atr_mean + bb_mean
        remaining = [i for i in range(n) if i not in state_map]
        if remaining:
            hv_state = int(remaining[np.argmax(vol_score[remaining])])
            state_map[hv_state] = "HIGH_VOLATILITY"
            used_labels.add("HIGH_VOLATILITY")

        # Lowest ADX among remaining → RANGING
        remaining = [i for i in range(n) if i not in state_map]
        if remaining:
            range_state = int(remaining[np.argmin(adx_mean[remaining])])
            state_map[range_state] = "RANGING"
            used_labels.add("RANGING")

        # Any remaining → UNCERTAIN
        for i in range(n):
            if i not in state_map:
                state_map[i] = "UNCERTAIN"

        return state_map


# ═══════════════════════════════════════════════════════════════════════
# RULE-BASED FALLBACK
# ═══════════════════════════════════════════════════════════════════════


def _classify_rule_based(
    adx_val: float,
    atr_pct: float,
    plus_di: float,
    minus_di: float,
    ema_slope: float,
    in_range: bool,
) -> tuple[str, float]:
    """Rule-based regime classification (fallback).

    Returns:
        (regime_label, confidence)
    """
    if atr_pct > 3.0:
        return "HIGH_VOLATILITY", min(atr_pct / 5.0, 1.0)
    elif adx_val > 25 and plus_di > minus_di:
        return "STRONG_TREND_UP", min(adx_val / 50.0, 1.0)
    elif adx_val > 25 and minus_di > plus_di:
        return "STRONG_TREND_DOWN", min(adx_val / 50.0, 1.0)
    elif in_range and adx_val <= 25:
        return "RANGING", min((25 - adx_val) / 25.0, 1.0)
    else:
        return "UNCERTAIN", 0.3


# ═══════════════════════════════════════════════════════════════════════
# REGIME DETECTOR AGENT
# ═══════════════════════════════════════════════════════════════════════


class RegimeDetector(BaseAgent):
    """Classify market regime using HMM with rule-based fallback.

    Configuration (in config dict):
        agents.regime_detector:
            use_hmm: bool = true          # Enable/disable HMM
            hmm_states: int = 5           # Number of HMM states
            hmm_retrain_interval: int = 50  # Retrain every N cycles
            hmm_min_samples: int = 50     # Minimum samples for HMM
            lookback_bars: int = 200      # OHLCV lookback for HMM training
    """

    AGENT_NAME = "regime_detector"
    ROLE = "ANALYSIS"

    REGIMES = ["STRONG_TREND_UP", "STRONG_TREND_DOWN", "RANGING", "HIGH_VOLATILITY", "UNCERTAIN"]

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)
        self.symbols = config.get("exchange", {}).get("symbols", ["BTC/USDT", "ETH/USDT"])
        self.pricing_engine = None
        self.regime_state = None

        # ── Domain Tools (Tools-to-Agents Wiring) ───────
        self._market_data_tools: MarketDataTools | None = None
        self._ta_tools: TechnicalAnalysisTools | None = None
        self._volatility_analyzer: VolatilityAnalyzer | None = None
        self._correlation_analyzer: CorrelationAnalyzer | None = None

        # HMM configuration
        regime_cfg = config.get("agents", {}).get("regime_detector", {})
        self._use_hmm = regime_cfg.get("use_hmm", True) and HMM_AVAILABLE
        self._lookback_bars = regime_cfg.get("lookback_bars", 200)

        if self._use_hmm:
            self._hmm_classifier = HMMRegimeClassifier(
                n_states=regime_cfg.get("hmm_states", 5),
                retrain_interval=regime_cfg.get("hmm_retrain_interval", 50),
                min_samples=regime_cfg.get("hmm_min_samples", 50),
            )
            logger.info("RegimeDetector: HMM enabled (%d states)", self._hmm_classifier._n_states)
        else:
            self._hmm_classifier = None
            logger.info("RegimeDetector: using rule-based classification")

    async def on_initialize(self) -> None:
        """Initialize pricing engine and domain tools."""
        from src.interfaces import get_pricing_engine, get_exchange_gateway

        self.pricing_engine = get_pricing_engine()

        try:
            gateway = get_exchange_gateway()
            self._market_data_tools = MarketDataTools(
                gateway=gateway, config=self.config.get("market_data", {}),
            )
            self._ta_tools = TechnicalAnalysisTools(config=self.config)
            self._volatility_analyzer = VolatilityAnalyzer(config=self.config)
            self._correlation_analyzer = CorrelationAnalyzer(config=self.config)
            logger.info(
                "RegimeDetector tools initialized: [market_data, ta, volatility, correlation]"
            )
        except Exception as e:
            logger.warning("RegimeDetector tool init failed: %s", e)

    async def run_cycle(self) -> None:
        """Classify market regime using HMM or rule-based fallback."""
        if self.pricing_engine is None or self.regime_state is None:
            logger.debug("RegimeDetector: pricing_engine or regime_state not set, skipping")
            return

        for symbol in self.symbols:
            try:
                await self._classify_symbol(symbol)
            except Exception as e:
                logger.error(f"Regime detection failed for {symbol}: {e}")

        return self.regime_state.snapshot_to_dict() if self.regime_state else {}

    async def _classify_symbol(self, symbol: str) -> None:
        """Classify regime for a single symbol."""
        ohlcv = await self.pricing_engine.get_ohlcv(
            symbol, "1h", limit=self._lookback_bars
        )
        if ohlcv is None or len(ohlcv) < 50:
            return

        df = pd.DataFrame(ohlcv)

        # ── Common indicators (used by both HMM and rule-based) ──
        adx = ta.adx(df["high"], df["low"], df["close"], length=14)
        adx_val = adx["ADX_14"].iloc[-1] if adx is not None else 0
        plus_di = adx["DMP_14"].iloc[-1] if adx is not None else 0
        minus_di = adx["DMN_14"].iloc[-1] if adx is not None else 0

        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        atr_pct = (atr.iloc[-1] / df["close"].iloc[-1]) * 100 if atr is not None else 0

        bb = ta.bbands(df["close"], length=20, std=2)
        if bb is not None:
            bb_upper = bb["BBU_20_2.0"].iloc[-1]
            bb_lower = bb["BBL_20_2.0"].iloc[-1]
            price = df["close"].iloc[-1]
            in_range = bb_lower <= price <= bb_upper
        else:
            in_range = False

        ema = ta.ema(df["close"], length=21)
        ema_slope = (ema.iloc[-1] - ema.iloc[-5]) / ema.iloc[-5] * 100 if ema is not None else 0

        # ── Volatility regime from domain tool ──────────────
        vol_regime_label = None
        if self._volatility_analyzer:
            try:
                vol_regime = self._volatility_analyzer.classify_volatility_regime(ohlcv)
                vol_regime_label = vol_regime.regime
                logger.debug(
                    "%s: volatility tool regime=%s (percentile=%.1f)",
                    symbol, vol_regime.regime, vol_regime.percentile,
                )
            except Exception:
                logger.debug("Volatility tool failed for %s", symbol, exc_info=True)

        # ── HMM classification ──
        regime = "UNCERTAIN"
        confidence = 0.0
        probabilities: dict[str, float] = {}

        if self._use_hmm and self._hmm_classifier is not None:
            features = _build_hmm_features(df)
            if features is not None and len(features) >= self._hmm_classifier._min_samples:
                regime, confidence, probabilities = self._hmm_classifier.fit_predict(features)
                logger.debug(
                    "HMM regime: %s = %s (conf=%.3f, probs=%s)",
                    symbol, regime, confidence,
                    {k: f"{v:.3f}" for k, v in probabilities.items()},
                )

        # ── Rule-based fallback / supplement ──
        if regime == "UNCERTAIN" or confidence < 0.3:
            rb_regime, rb_confidence = _classify_rule_based(
                adx_val, atr_pct, plus_di, minus_di, ema_slope, in_range
            )
            # Blend: prefer HMM if confident, else rule-based
            if confidence < 0.3:
                regime = rb_regime
                confidence = rb_confidence
                probabilities = {}

        # ── Store regime state ──
        from src.knowledge.regime_state import RegimeState

        state = RegimeState(
            probabilities=probabilities,
            dominant_regime=regime,
            confidence=confidence,
            indicators={
                "adx": float(adx_val),
                "atr_pct": float(atr_pct),
                "ema_slope": float(ema_slope),
                "plus_di": float(plus_di),
                "minus_di": float(minus_di),
                "bb_width": float(
                    (bb_upper - bb_lower) / bb["BBM_20_2.0"].iloc[-1]
                    if bb is not None else 0
                ),
                "classifier": "hmm" if (self._use_hmm and confidence >= 0.3) else "rule_based",
                "volatility_regime": vol_regime_label or "unknown",
            },
        )
        self.regime_state.update_asset_regime(symbol, state)

        logger.info(
            "Regime: %s = %s (conf=%.3f, classifier=%s)",
            symbol, regime, confidence,
            "hmm" if (self._use_hmm and confidence >= 0.3) else "rule_based",
        )
