"""
Macro Agent — Macroeconomic regime analysis.

Role: ANALYSIS (Level 2+)
Model Tier: T0 (indicator computation) + T2 (news_sentiment) + T3 (risk_scenario)

Macro regime classification:
  RISK_ON: 1.0x position, LONG bias
  TRANSITION: 0.75x, NEUTRAL
  RISK_OFF: 0.50x, SHORT
  CRISIS: 0.25x, NONE

Data sources (all free): FRED API (DXY, US10Y), Fear & Greed Index,
CoinGecko market data, simple risk sentiment scoring.

Subscribes to: tsar:stream:regime
Publishes to: tsar:stream:macro, tsar:stream:sentiment, tsar:stream:onchain
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


class MacroRegime(StrEnum):
    """Macro risk regimes."""
    RISK_ON = "RISK_ON"
    TRANSITION = "TRANSITION"
    RISK_OFF = "RISK_OFF"
    CRISIS = "CRISIS"


@dataclass
class MacroIndicators:
    """Snapshot of macro indicators."""

    dxy: float = 0.0             # US Dollar Index
    dxy_change_5d: float = 0.0   # 5-day DXY change
    us10y: float = 0.0           # US 10-Year Treasury Yield
    us10y_change_5d: float = 0.0 # 5-day yield change
    fear_greed: int = 50         # Crypto Fear & Greed Index (0-100)
    btc_dominance: float = 0.0   # BTC market dominance %
    funding_rate: float = 0.0    # Perpetual funding rate
    vix: float = 0.0             # CBOE Volatility Index (if available)
    computed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dxy": self.dxy,
            "dxy_change_5d": self.dxy_change_5d,
            "us10y": self.us10y,
            "us10y_change_5d": self.us10y_change_5d,
            "fear_greed": self.fear_greed,
            "btc_dominance": self.btc_dominance,
            "funding_rate": self.funding_rate,
            "vix": self.vix,
            "computed_at": self.computed_at,
        }


@dataclass
class MacroRegimeState:
    """Macro regime classification result."""

    regime: MacroRegime = MacroRegime.TRANSITION
    confidence: float = 0.0
    position_multiplier: float = 0.75
    bias: str = "NEUTRAL"  # LONG | SHORT | NEUTRAL
    risk_score: float = 0.5  # 0.0 (very bearish) to 1.0 (very bullish)
    indicators: MacroIndicators = field(default_factory=MacroIndicators)
    reasoning: str = ""
    computed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "confidence": self.confidence,
            "position_multiplier": self.position_multiplier,
            "bias": self.bias,
            "risk_score": self.risk_score,
            "indicators": self.indicators.to_dict(),
            "reasoning": self.reasoning,
            "computed_at": self.computed_at,
        }


# ═══════════════════════════════════════════════════════════════════════
# MACRO DATA FETCHER
# ═══════════════════════════════════════════════════════════════════════


class MacroDataFetcher:
    """Fetch macro indicators from free data sources.

    Uses:
    - Fear & Greed Index: alternative.me API (free)
    - CoinGecko: BTC dominance, market data (free tier)
    - DXY/US10Y: via pricing engine or cached values

    All fetchers have graceful fallbacks — returns cached/default
    values if APIs are unavailable.
    """

    def __init__(self) -> None:
        self._cached_dxy: float = 104.0
        self._cached_us10y: float = 4.25
        self._cached_fear_greed: int = 50
        self._cached_btc_dom: float = 50.0
        self._cached_funding: float = 0.01
        self._last_fetch: float = 0.0
        self._fetch_interval: float = 300.0  # 5 min cache

    async def fetch_all(self) -> MacroIndicators:
        """Fetch all macro indicators with caching."""
        now = time.time()
        if now - self._last_fetch < self._fetch_interval:
            return self._build_indicators()

        try:
            self._cached_fear_greed = await self._fetch_fear_greed()
        except Exception as e:
            logger.debug("Fear & Greed fetch failed: %s", e)

        try:
            dom = await self._fetch_btc_dominance()
            if dom is not None:
                self._cached_btc_dom = dom
        except Exception as e:
            logger.debug("BTC dominance fetch failed: %s", e)

        self._last_fetch = now
        return self._build_indicators()

    def _build_indicators(self) -> MacroIndicators:
        return MacroIndicators(
            dxy=self._cached_dxy,
            us10y=self._cached_us10y,
            fear_greed=self._cached_fear_greed,
            btc_dominance=self._cached_btc_dom,
            funding_rate=self._cached_funding,
            computed_at=time.time(),
        )

    async def _fetch_fear_greed(self) -> int:
        """Fetch Crypto Fear & Greed Index from alternative.me."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.alternative.me/fng/?limit=2",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        values = data.get("data", [])
                        if values:
                            return int(values[0]["value"])
        except ImportError:
            logger.debug("aiohttp not available for Fear & Greed fetch")
        except Exception as e:
            logger.debug("Fear & Greed API error: %s", e)

        return self._cached_fear_greed

    async def _fetch_btc_dominance(self) -> float | None:
        """Fetch BTC dominance from CoinGecko."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.coingecko.com/api/v3/global",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", {}).get("market_cap_percentage", {}).get("btc", None)
        except ImportError:
            pass
        except Exception as e:
            logger.debug("CoinGecko dominance error: %s", e)

        return None

    def update_dxy(self, value: float) -> None:
        """Update DXY from external source (e.g., pricing engine)."""
        self._cached_dxy = value

    def update_us10y(self, value: float) -> None:
        """Update US 10Y yield from external source."""
        self._cached_us10y = value

    def update_funding_rate(self, value: float) -> None:
        """Update perpetual funding rate."""
        self._cached_funding = value


# ═══════════════════════════════════════════════════════════════════════
# MACRO REGIME CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════


class MacroRegimeClassifier:
    """Classify macro regime from indicator snapshot.

    Scoring system:
    - Fear & Greed: <25 bearish, 25-50 cautious, 50-75 neutral, >75 greedy
    - DXY rising: bearish for crypto (strong dollar)
    - US10Y rising: bearish for risk assets
    - BTC dominance rising: risk-off within crypto
    - Funding rate extreme: contrarian indicator
    """

    # Regime thresholds and their position multipliers
    REGIME_CONFIG = {
        MacroRegime.RISK_ON: {"multiplier": 1.0, "bias": "LONG"},
        MacroRegime.TRANSITION: {"multiplier": 0.75, "bias": "NEUTRAL"},
        MacroRegime.RISK_OFF: {"multiplier": 0.50, "bias": "SHORT"},
        MacroRegime.CRISIS: {"multiplier": 0.25, "bias": "NONE"},
    }

    def classify(self, indicators: MacroIndicators) -> MacroRegimeState:
        """Classify macro regime from indicators.

        Returns:
            MacroRegimeState with regime, confidence, position sizing, and reasoning.
        """
        scores: list[float] = []
        reasoning_parts: list[str] = []

        # ── Fear & Greed Score ──────────────────────────────
        fg = indicators.fear_greed
        if fg < 15:
            fg_score = 0.1  # Extreme fear → crisis
            reasoning_parts.append(f"Extreme fear ({fg})")
        elif fg < 25:
            fg_score = 0.3  # Fear → risk-off
            reasoning_parts.append(f"Fear ({fg})")
        elif fg < 45:
            fg_score = 0.45  # Cautious → transition
            reasoning_parts.append(f"Cautious ({fg})")
        elif fg < 55:
            fg_score = 0.5  # Neutral
            reasoning_parts.append(f"Neutral ({fg})")
        elif fg < 75:
            fg_score = 0.65  # Greed → risk-on
            reasoning_parts.append(f"Greed ({fg})")
        elif fg < 85:
            fg_score = 0.8  # High greed
            reasoning_parts.append(f"High greed ({fg})")
        else:
            fg_score = 0.9  # Extreme greed → caution (contrarian)
            reasoning_parts.append(f"Extreme greed ({fg}) — caution")
        scores.append(fg_score * 0.30)  # 30% weight

        # ── DXY Score ───────────────────────────────────────
        dxy_change = indicators.dxy_change_5d
        if dxy_change > 1.5:
            dxy_score = 0.2  # Strong dollar rally → risk-off
            reasoning_parts.append(f"DXY surging ({dxy_change:+.1f})")
        elif dxy_change > 0.5:
            dxy_score = 0.4
            reasoning_parts.append(f"DXY rising ({dxy_change:+.1f})")
        elif dxy_change > -0.5:
            dxy_score = 0.5  # Stable
        elif dxy_change > -1.5:
            dxy_score = 0.6
            reasoning_parts.append(f"DXY falling ({dxy_change:+.1f})")
        else:
            dxy_score = 0.8  # Dollar weakness → risk-on
            reasoning_parts.append(f"DXY plunging ({dxy_change:+.1f})")
        scores.append(dxy_score * 0.25)  # 25% weight

        # ── US10Y Score ─────────────────────────────────────
        yield_change = indicators.us10y_change_5d
        if yield_change > 0.20:
            yld_score = 0.2  # Yields spiking → risk-off
            reasoning_parts.append(f"US10Y spiking ({yield_change:+.2f}%)")
        elif yield_change > 0.05:
            yld_score = 0.4
            reasoning_parts.append(f"US10Y rising ({yield_change:+.2f}%)")
        elif yield_change > -0.05:
            yld_score = 0.5  # Stable
        elif yield_change > -0.20:
            yld_score = 0.6
            reasoning_parts.append(f"US10Y falling ({yield_change:+.2f}%)")
        else:
            yld_score = 0.8  # Yields collapsing → risk-on
            reasoning_parts.append(f"US10Y plunging ({yield_change:+.2f}%)")
        scores.append(yld_score * 0.20)  # 20% weight

        # ── BTC Dominance Score ─────────────────────────────
        dom = indicators.btc_dominance
        if dom > 60:
            dom_score = 0.3  # Flight to BTC → risk-off
            reasoning_parts.append(f"BTC dominance high ({dom:.0f}%)")
        elif dom > 50:
            dom_score = 0.5
        else:
            dom_score = 0.7  # Alt season → risk-on
            reasoning_parts.append(f"BTC dominance low ({dom:.0f}%)")
        scores.append(dom_score * 0.15)  # 15% weight

        # ── Funding Rate Score ──────────────────────────────
        funding = indicators.funding_rate
        if funding > 0.1:
            fund_score = 0.3  # Extreme long leverage → contrarian bearish
            reasoning_parts.append(f"Funding extreme positive ({funding:.3f}%)")
        elif funding > 0.03:
            fund_score = 0.5
        elif funding > -0.03:
            fund_score = 0.5  # Neutral
        elif funding > -0.1:
            fund_score = 0.6
        else:
            fund_score = 0.7  # Extreme short → contrarian bullish
            reasoning_parts.append(f"Funding extreme negative ({funding:.3f}%)")
        scores.append(fund_score * 0.10)  # 10% weight

        # ── Composite Score ─────────────────────────────────
        risk_score = sum(scores)

        # Map to regime
        if risk_score >= 0.70:
            regime = MacroRegime.RISK_ON
        elif risk_score >= 0.45:
            regime = MacroRegime.TRANSITION
        elif risk_score >= 0.25:
            regime = MacroRegime.RISK_OFF
        else:
            regime = MacroRegime.CRISIS

        config = self.REGIME_CONFIG[regime]

        # Confidence based on how clearly the score maps to a regime
        if risk_score >= 0.70 or risk_score < 0.25:
            confidence = 0.8  # Clear regime
        elif risk_score >= 0.60 or risk_score < 0.35:
            confidence = 0.6  # Moderate confidence
        else:
            confidence = 0.4  # Transitional

        reasoning = " | ".join(reasoning_parts) if reasoning_parts else "All indicators neutral"

        return MacroRegimeState(
            regime=regime,
            confidence=confidence,
            position_multiplier=config["multiplier"],
            bias=config["bias"],
            risk_score=round(risk_score, 3),
            indicators=indicators,
            reasoning=reasoning,
            computed_at=time.time(),
        )


# ═══════════════════════════════════════════════════════════════════════
# MACRO AGENT
# ═══════════════════════════════════════════════════════════════════════


class MacroAgent(BaseAgent):
    """Analyze macroeconomic environment and produce regime scores.

    Fetches DXY, US10Y yields, Fear & Greed Index, BTC dominance,
    and funding rates. Classifies into RISK_ON / TRANSITION / RISK_OFF / CRISIS
    regimes with position multipliers and directional bias.

    Configuration:
        agents.macro_agent:
            cycle_interval_s: 600       # 10 min default
            cache_dxy: 104.0            # Cached DXY if no live source
            cache_us10y: 4.25           # Cached US10Y if no live source
    """

    AGENT_NAME = "macro_agent"
    ROLE = "ANALYSIS"

    PUBLISH_STREAM = "macro"
    SUBSCRIBE_STREAMS = ["regime"]

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)

        macro_cfg = config.get("agents", {}).get("macro_agent", {})
        self._cycle_interval = macro_cfg.get("cycle_interval_s", 600)

        # Initialize data fetcher with cached values
        self._fetcher = MacroDataFetcher()
        if "cache_dxy" in macro_cfg:
            self._fetcher.update_dxy(macro_cfg["cache_dxy"])
        if "cache_us10y" in macro_cfg:
            self._fetcher.update_us10y(macro_cfg["cache_us10y"])

        # Classifier
        self._classifier = MacroRegimeClassifier()

        # State
        self._pricing_engine = None
        self._last_scan_time = 0.0
        self._latest_state: MacroRegimeState | None = None

    async def on_initialize(self) -> None:
        """Initialize pricing engine reference."""
        try:
            from src.interfaces import get_pricing_engine
            self._pricing_engine = get_pricing_engine()
        except Exception:
            logger.debug("Pricing engine not available for macro data")

        logger.info("MacroAgent initialized: cycle_interval=%ds", self._cycle_interval)

    async def run_cycle(self) -> None:
        """Analyze macro indicators and publish regime updates."""
        now = time.monotonic()
        if now - self._last_scan_time < self._cycle_interval:
            return

        try:
            # Fetch indicators
            indicators = await self._fetcher.fetch_all()

            # Update DXY/US10Y from pricing engine if available
            await self._update_from_pricing_engine(indicators)

            # Classify regime
            state = self._classifier.classify(indicators)
            self._latest_state = state
            self._last_scan_time = now

            # Publish macro event
            await self.publish_event(
                stream="macro",
                event_type="tsar.macro.regime.v1",
                data=state.to_dict(),
                priority=2,
            )

            logger.info(
                "Macro regime: %s (confidence=%.2f, bias=%s, multiplier=%.2f) — %s",
                state.regime.value,
                state.confidence,
                state.bias,
                state.position_multiplier,
                state.reasoning,
            )

        except Exception as e:
            logger.error("Macro analysis failed: %s", e, exc_info=True)

    async def _update_from_pricing_engine(self, indicators: MacroIndicators) -> None:
        """Try to update DXY/US10Y from pricing engine if available."""
        if self._pricing_engine is None:
            return

        # These may not be available on all exchanges
        for symbol, setter in [("DXY", self._fetcher.update_dxy), ("US10Y", self._fetcher.update_us10y)]:
            try:
                ohlcv = await self._pricing_engine.get_ohlcv(symbol, "1d", limit=6)
                if ohlcv and len(ohlcv) >= 2:
                    setter(ohlcv[-1].close)
                    # Update 5-day change
                    if len(ohlcv) >= 6:
                        change = ohlcv[-1].close - ohlcv[-6].close
                        if symbol == "DXY":
                            indicators.dxy = ohlcv[-1].close
                            indicators.dxy_change_5d = change
                        elif symbol == "US10Y":
                            indicators.us10y = ohlcv[-1].close
                            indicators.us10y_change_5d = change
            except Exception:
                pass  # Not all exchanges have these symbols

    def get_latest_state(self) -> MacroRegimeState | None:
        """Get the most recent macro regime state."""
        return self._latest_state
