"""
Mean Reversion Strategy — Day1 strategy.

Thesis: BTC mean-reverts after RSI extremes. Buy oversold at support,
sell overbought at resistance.

Entry rules:
  - RSI(14) < 30 (oversold) at support proximity → BUY
  - RSI(14) > 70 (overbought) at resistance proximity → SELL
  - Volume > 1.5x 20-period average
  - Signal score ≥ 0.6

Exit rules:
  - Take profit: RSI > 70 OR +2% from entry
  - Stop loss: -1% from entry (hard)
  - Time stop: Close after 4 hours if neither TP nor SL hit
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """Day1 mean reversion strategy for BTC/USDT.

    Uses RSI extremes combined with support/resistance proximity
    to identify high-probability mean reversion setups.
    """

    NAME = "mean_reversion"
    VERSION = "1.0.0"

    # ── Entry ────────────────────────────────────────────────

    def check_entry(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Check mean reversion entry conditions.

        Args:
            data: Market data dict expected to contain:
                - rsi (float): RSI(14) value
                - close (float): Current close price
                - volume_ratio (float): Volume / 20-period avg volume
                - support_levels (list[dict]): Support levels with 'price' and 'strength'
                - resistance_levels (list[dict]): Resistance levels with 'price' and 'strength'
                - fear_greed_index (float, optional): Fear & Greed Index
                - macro_alignment (float, optional): Macro regime alignment score
                - onchain_metrics (float, optional): On-chain metrics score
                - order_flow (float, optional): Order flow score
                - seasonality (float, optional): Seasonal pattern score
                - cross_asset (float, optional): Cross-asset alignment score

        Returns:
            Signal dict with score, entry_price, stop_loss, take_profit, reasoning, or None.
        """
        rsi = data.get("rsi", 50.0)
        price = data.get("close", 0.0)
        volume_ratio = data.get("volume_ratio", 1.0)
        support_levels = data.get("support_levels", [])
        resistance_levels = data.get("resistance_levels", [])

        if price <= 0:
            return None

        # ── LONG: RSI oversold at support ──
        long_signal = self._check_long_entry(
            rsi=rsi,
            price=price,
            volume_ratio=volume_ratio,
            support_levels=support_levels,
            data=data,
        )
        if long_signal is not None:
            return long_signal

        # ── SHORT: RSI overbought at resistance ──
        short_signal = self._check_short_entry(
            rsi=rsi,
            price=price,
            volume_ratio=volume_ratio,
            resistance_levels=resistance_levels,
            data=data,
        )
        if short_signal is not None:
            return short_signal

        return None

    def _check_long_entry(
        self,
        rsi: float,
        price: float,
        volume_ratio: float,
        support_levels: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check long entry: RSI < 30 at support level."""
        rsi_oversold = 30
        support_proximity_pct = 2.0

        if rsi >= rsi_oversold:
            return None

        # Check support proximity
        near_support, support_price, support_strength = self._near_level(
            price, support_levels, support_proximity_pct
        )

        # Build weighted score
        score, components = self._compute_long_score(
            rsi=rsi,
            near_support=near_support,
            support_strength=support_strength,
            volume_ratio=volume_ratio,
            data=data,
        )

        min_score = 0.6
        if score < min_score:
            return None

        entry_price = price
        stop_loss = price * 0.99  # -1%
        take_profit = price * 1.02  # +2%

        reasoning_parts = [f"RSI={rsi:.1f}"]
        if near_support:
            reasoning_parts.append(f"near_support={support_price:.2f}")
        reasoning_parts.append(f"vol_ratio={volume_ratio:.2f}")
        reasoning_parts.append(f"score={score:.2f}")

        return {
            "side": "buy",
            "score": score,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reasoning": ", ".join(reasoning_parts),
            "components": components,
        }

    def _check_short_entry(
        self,
        rsi: float,
        price: float,
        volume_ratio: float,
        resistance_levels: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check short entry: RSI > 70 at resistance level."""
        rsi_overbought = 70
        resistance_proximity_pct = 2.0

        if rsi <= rsi_overbought:
            return None

        # Check resistance proximity
        near_resistance, resistance_price, resistance_strength = self._near_level(
            price, resistance_levels, resistance_proximity_pct
        )

        # Build weighted score
        score, components = self._compute_short_score(
            rsi=rsi,
            near_resistance=near_resistance,
            resistance_strength=resistance_strength,
            volume_ratio=volume_ratio,
            data=data,
        )

        min_score = 0.6
        if score < min_score:
            return None

        entry_price = price
        stop_loss = price * 1.01  # +1% (short stop)
        take_profit = price * 0.98  # -2% (short TP)

        reasoning_parts = [f"RSI={rsi:.1f}"]
        if near_resistance:
            reasoning_parts.append(f"near_resistance={resistance_price:.2f}")
        reasoning_parts.append(f"vol_ratio={volume_ratio:.2f}")
        reasoning_parts.append(f"score={score:.2f}")

        return {
            "side": "sell",
            "score": score,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reasoning": ", ".join(reasoning_parts),
            "components": components,
        }

    # ── Scoring ──────────────────────────────────────────────

    def _compute_long_score(
        self,
        rsi: float,
        near_support: bool,
        support_strength: float,
        volume_ratio: float,
        data: dict[str, Any],
    ) -> tuple[float, dict[str, float]]:
        """Compute weighted signal score for long entry.

        Weights from YAML genome:
          rsi: 0.25, support_proximity: 0.20, volume: 0.10,
          fear_greed: 0.15, macro: 0.10, onchain: 0.05,
          order_flow: 0.05, seasonality: 0.05, cross_asset: 0.05
        """
        components: dict[str, float] = {}

        # RSI score: 0 at rsi=30, 1.0 at rsi=15 or below
        rsi_score = max(0.0, min(1.0, (30 - rsi) / 15))
        components["rsi"] = rsi_score

        # Support proximity score
        support_score = support_strength if near_support else 0.0
        components["support_proximity"] = support_score

        # Volume score: 0 at ratio=1.0, 1.0 at ratio=2.5+
        volume_score = max(0.0, min(1.0, (volume_ratio - 1.0) / 1.5))
        components["volume_ratio"] = volume_score

        # Optional signals
        fear_greed = data.get("fear_greed_index", 50)
        fg_score = max(0.0, min(1.0, (50 - fear_greed) / 30))
        components["fear_greed"] = fg_score

        macro = data.get("macro_alignment", 0.5)
        components["macro_alignment"] = max(0.0, min(1.0, macro))

        onchain = data.get("onchain_metrics", 0.5)
        components["onchain_metrics"] = max(0.0, min(1.0, onchain))

        order_flow = data.get("order_flow", 0.5)
        components["order_flow"] = max(0.0, min(1.0, order_flow))

        seasonality = data.get("seasonality", 0.5)
        components["seasonality"] = max(0.0, min(1.0, seasonality))

        cross_asset = data.get("cross_asset", 0.5)
        components["cross_asset"] = max(0.0, min(1.0, cross_asset))

        # Weighted sum
        weights = {
            "rsi": 0.25,
            "support_proximity": 0.20,
            "volume_ratio": 0.10,
            "fear_greed": 0.15,
            "macro_alignment": 0.10,
            "onchain_metrics": 0.05,
            "order_flow": 0.05,
            "seasonality": 0.05,
            "cross_asset": 0.05,
        }
        score = sum(components[k] * weights[k] for k in weights)
        return round(score, 4), components

    def _compute_short_score(
        self,
        rsi: float,
        near_resistance: bool,
        resistance_strength: float,
        volume_ratio: float,
        data: dict[str, Any],
    ) -> tuple[float, dict[str, float]]:
        """Compute weighted signal score for short entry (mirror of long)."""
        components: dict[str, float] = {}

        # RSI score: 0 at rsi=70, 1.0 at rsi=85+
        rsi_score = max(0.0, min(1.0, (rsi - 70) / 15))
        components["rsi"] = rsi_score

        # Resistance proximity score
        resistance_score = resistance_strength if near_resistance else 0.0
        components["resistance_proximity"] = resistance_score

        # Volume score
        volume_score = max(0.0, min(1.0, (volume_ratio - 1.0) / 1.5))
        components["volume_ratio"] = volume_score

        # Optional signals (inverted for short)
        fear_greed = data.get("fear_greed_index", 50)
        fg_score = max(0.0, min(1.0, (fear_greed - 50) / 30))
        components["fear_greed"] = fg_score

        macro = data.get("macro_alignment", 0.5)
        components["macro_alignment"] = max(0.0, min(1.0, 1.0 - macro))

        onchain = data.get("onchain_metrics", 0.5)
        components["onchain_metrics"] = max(0.0, min(1.0, 1.0 - onchain))

        order_flow = data.get("order_flow", 0.5)
        components["order_flow"] = max(0.0, min(1.0, 1.0 - order_flow))

        seasonality = data.get("seasonality", 0.5)
        components["seasonality"] = max(0.0, min(1.0, 1.0 - seasonality))

        cross_asset = data.get("cross_asset", 0.5)
        components["cross_asset"] = max(0.0, min(1.0, 1.0 - cross_asset))

        weights = {
            "rsi": 0.25,
            "resistance_proximity": 0.20,
            "volume_ratio": 0.10,
            "fear_greed": 0.15,
            "macro_alignment": 0.10,
            "onchain_metrics": 0.05,
            "order_flow": 0.05,
            "seasonality": 0.05,
            "cross_asset": 0.05,
        }
        score = sum(components[k] * weights[k] for k in weights)
        return round(score, 4), components

    # ── Support/Resistance helpers ───────────────────────────

    @staticmethod
    def _near_level(
        price: float,
        levels: list[dict[str, Any]],
        threshold_pct: float,
    ) -> tuple[bool, float, float]:
        """Check if price is within threshold_pct of any level.

        Returns:
            (is_near, nearest_level_price, nearest_level_strength)
        """
        if not levels:
            return False, 0.0, 0.0

        best_dist = float("inf")
        best_price = 0.0
        best_strength = 0.0

        for level in levels:
            level_price = level.get("price", 0.0)
            if level_price <= 0:
                continue
            dist_pct = abs(price - level_price) / level_price * 100
            if dist_pct < best_dist:
                best_dist = dist_pct
                best_price = level_price
                best_strength = level.get("strength", 0.5)

        if best_dist <= threshold_pct:
            return True, best_price, best_strength
        return False, best_price, 0.0

    # ── Exit ─────────────────────────────────────────────────

    def check_exit(self, position: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        """Check mean reversion exit conditions.

        Args:
            position: Current position with entry_price, side, entry_time
            data: Current market data with rsi, close

        Returns:
            Exit signal dict or None.
        """
        rsi = data.get("rsi", 50.0)
        entry_price = position.get("entry_price", 0.0)
        current_price = data.get("close", 0.0)
        side = position.get("side", "buy")

        if entry_price <= 0:
            return None

        # ── Long exits ──
        if side == "buy":
            # Take profit: RSI overbought
            if rsi > 70:
                return {"reason": "rsi_overbought", "action": "close", "rsi": rsi}

            # Take profit: +2% from entry
            if current_price >= entry_price * 1.02:
                return {"reason": "take_profit_hit", "action": "close", "pnl_pct": 2.0}

            # Stop loss: -1% from entry
            if current_price <= entry_price * 0.99:
                return {"reason": "stop_loss_hit", "action": "close", "pnl_pct": -1.0}

        # ── Short exits ──
        if side == "sell":
            # Take profit: RSI oversold
            if rsi < 30:
                return {"reason": "rsi_oversold", "action": "close", "rsi": rsi}

            # Take profit: -2% from entry
            if current_price <= entry_price * 0.98:
                return {"reason": "take_profit_hit", "action": "close", "pnl_pct": 2.0}

            # Stop loss: +1% from entry
            if current_price >= entry_price * 1.01:
                return {"reason": "stop_loss_hit", "action": "close", "pnl_pct": -1.0}

        # ── Time stop: 4 hours ──
        entry_time = position.get("entry_time")
        if entry_time is not None:
            from datetime import datetime
            now = datetime.now(UTC)
            if isinstance(entry_time, str):
                entry_time = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            hours_held = (now - entry_time).total_seconds() / 3600
            if hours_held >= 4:
                return {"reason": "time_stop", "action": "close", "hours_held": hours_held}

        return None

    # ── Risk params ──────────────────────────────────────────

    def get_risk_params(self) -> dict[str, Any]:
        """Return risk parameters for this strategy."""
        return {
            "stop_loss_pct": 0.015,       # 1.5% (ATR-adaptive)
            "take_profit_pct": 0.03,      # 3% (2:1 R:R minimum)
            "max_hold_hours": 4,          # Time stop
            "min_score": 0.6,             # Min signal score
            "max_position_pct": 0.15,     # Max 15% of portfolio
            "risk_per_trade_pct": 0.02,   # 2% risk per trade
            "method": "half_kelly",
            # Entry optimization
            "use_limit_orders": True,
            "limit_order_offset_pct": 0.001,
            "require_pullback": True,
            "require_volume_confirmation": True,
            "volume_confirmation_candles": 2,
            # Exit optimization
            "trailing_stop_enabled": True,
            "trailing_trigger_rr": 1.5,
            "partial_exit_enabled": True,
            "partial_exit_schedule": [0.4, 0.3, 0.3],
            "partial_exit_rr_levels": [1.0, 2.0, 3.0],
            "breakeven_trigger_rr": 1.0,
        }
