"""
Regime Detector — Classify market regime using ADX, ATR, Bollinger Bands.

Role: ANALYSIS (Level 3+)
Model Tier: T0 (indicator math) + T1 (classification)

Regime states: STRONG_TREND_UP, STRONG_TREND_DOWN, RANGING, HIGH_VOLATILITY, UNCERTAIN

Subscribes to: tsar:stream:cartography
Publishes to: tsar:stream:regime
"""

import logging
from typing import Any

import pandas as pd
import pandas_ta as ta

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class RegimeDetector(BaseAgent):
    """Classify market regime using statistical models."""

    AGENT_NAME = "regime_detector"
    ROLE = "ANALYSIS"

    REGIMES = ["STRONG_TREND_UP", "STRONG_TREND_DOWN", "RANGING", "HIGH_VOLATILITY", "UNCERTAIN"]

    def __init__(self, config: dict[str, Any], trading_mode: str = "paper") -> None:
        super().__init__(config, trading_mode)
        self.symbols = config.get("exchange", {}).get("symbols", ["BTC/USDT", "ETH/USDT"])
        self.pricing_engine = None
        self.regime_state = None

    async def run_cycle(self) -> None:
        """Classify market regime using ADX, ATR, Bollinger Bands."""
        if self.pricing_engine is None or self.regime_state is None:
            logger.debug("RegimeDetector: pricing_engine or regime_state not set, skipping")
            return

        for symbol in self.symbols:
            try:
                ohlcv = await self.pricing_engine.get_ohlcv(symbol, "1h", limit=100)
                if ohlcv is None or len(ohlcv) < 50:
                    continue

                df = pd.DataFrame(ohlcv)

                # ADX for trend strength
                adx = ta.adx(df["high"], df["low"], df["close"], length=14)
                adx_val = adx["ADX_14"].iloc[-1] if adx is not None else 0
                plus_di = adx["DMP_14"].iloc[-1] if adx is not None else 0
                minus_di = adx["DMN_14"].iloc[-1] if adx is not None else 0

                # ATR for volatility
                atr = ta.atr(df["high"], df["low"], df["close"], length=14)
                atr_pct = (atr.iloc[-1] / df["close"].iloc[-1]) * 100 if atr is not None else 0

                # Bollinger Bands for range
                bb = ta.bbands(df["close"], length=20, std=2)
                if bb is not None:
                    bb_upper = bb["BBU_20_2.0"].iloc[-1]
                    bb_lower = bb["BBL_20_2.0"].iloc[-1]
                    price = df["close"].iloc[-1]
                    in_range = bb_lower <= price <= bb_upper
                else:
                    in_range = False

                # EMA slope for direction
                ema = ta.ema(df["close"], length=21)
                ema_slope = (ema.iloc[-1] - ema.iloc[-5]) / ema.iloc[-5] * 100 if ema is not None else 0

                # Classify regime
                if atr_pct > 3.0:
                    regime = "HIGH_VOLATILITY"
                elif adx_val > 25 and plus_di > minus_di:
                    regime = "STRONG_TREND_UP"
                elif adx_val > 25 and minus_di > plus_di:
                    regime = "STRONG_TREND_DOWN"
                elif in_range and adx_val <= 25:
                    regime = "RANGING"
                else:
                    regime = "UNCERTAIN"

                confidence = min(adx_val / 50.0, 1.0)

                # Store in regime state
                from src.knowledge.regime_state import RegimeState
                state = RegimeState(
                    dominant_regime=regime,
                    confidence=confidence,
                    indicators={"adx": adx_val, "atr_pct": atr_pct, "ema_slope": ema_slope},
                )
                self.regime_state.update_asset_regime(symbol, state)

                logger.info(f"Regime: {symbol} = {regime} (conf={confidence:.2f})")

            except Exception as e:
                logger.error(f"Regime detection failed for {symbol}: {e}")

        return self.regime_state.snapshot_to_dict() if self.regime_state else {}
