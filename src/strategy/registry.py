"""
Strategy Registry — Active strategy management with signal aggregation.

Maintains the set of active strategies and their configurations.
Strategies can be added, removed, paused, and retired.
Provides signal aggregation across all active strategies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Registry of active trading strategies with signal aggregation.

    Usage::

        registry = StrategyRegistry()
        registry.register(MeanReversionStrategy())
        registry.register(MomentumStrategy())

        # Generate signals from all active strategies
        aggregated = registry.generate_signals(market_data)

        # Or get signals from a specific strategy
        strategy = registry.get("mean_reversion")
    """

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}
        self._paused: set[str] = set()

    # ── Registration ─────────────────────────────────────────

    def register(self, strategy: BaseStrategy) -> None:
        """Register a strategy.

        Args:
            strategy: Strategy instance to register.
        """
        self._strategies[strategy.NAME] = strategy
        logger.info(f"Registered strategy: {strategy.NAME} v{strategy.VERSION}")

    def unregister(self, name: str) -> bool:
        """Remove a strategy from the registry.

        Args:
            name: Strategy name to remove.

        Returns:
            True if strategy was found and removed.
        """
        if name in self._strategies:
            del self._strategies[name]
            self._paused.discard(name)
            logger.info(f"Unregistered strategy: {name}")
            return True
        return False

    def get(self, name: str) -> BaseStrategy | None:
        """Get a strategy by name.

        Args:
            name: Strategy name.

        Returns:
            Strategy instance or None if not found.
        """
        return self._strategies.get(name)

    def list_active(self) -> list[str]:
        """List all registered (non-paused) strategy names."""
        return [name for name in self._strategies if name not in self._paused]

    def list_all(self) -> list[str]:
        """List all registered strategy names (including paused)."""
        return list(self._strategies.keys())

    def get_all(self) -> dict[str, BaseStrategy]:
        """Get all registered strategies."""
        return dict(self._strategies)

    # ── Pause / Resume ───────────────────────────────────────

    def pause(self, name: str) -> bool:
        """Pause a strategy (stops generating signals but stays registered).

        Args:
            name: Strategy name to pause.

        Returns:
            True if strategy was found and paused.
        """
        if name in self._strategies:
            self._paused.add(name)
            logger.info(f"Paused strategy: {name}")
            return True
        return False

    def resume(self, name: str) -> bool:
        """Resume a paused strategy.

        Args:
            name: Strategy name to resume.

        Returns:
            True if strategy was found and resumed.
        """
        if name in self._paused:
            self._paused.discard(name)
            logger.info(f"Resumed strategy: {name}")
            return True
        return False

    def is_paused(self, name: str) -> bool:
        """Check if a strategy is paused."""
        return name in self._paused

    # ── Signal Generation ────────────────────────────────────

    def generate_signals(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate entry signals from all active strategies.

        Runs check_entry() on each active (non-paused) strategy and
        collects all signals, tagged with strategy name.

        Args:
            data: Market data dict passed to each strategy.

        Returns:
            List of signal dicts, each with a 'strategy' key added.
            Sorted by score descending.
        """
        signals: list[dict[str, Any]] = []

        for name in self.list_active():
            strategy = self._strategies[name]
            try:
                signal = strategy.check_entry(data)
                if signal is not None:
                    # Tag with strategy name
                    signal_with_meta = {**signal, "strategy": name}
                    signals.append(signal_with_meta)
            except Exception as e:
                logger.error(f"Strategy {name} check_entry failed: {e}")

        # Sort by score descending
        signals.sort(key=lambda s: s.get("score", 0), reverse=True)
        return signals

    def check_exits(
        self,
        positions: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check exit conditions for open positions across all strategies.

        Args:
            positions: List of position dicts, each with a 'strategy' key.
            data: Current market data.

        Returns:
            List of exit signal dicts.
        """
        exits: list[dict[str, Any]] = []

        for position in positions:
            strategy_name = position.get("strategy", "")
            strategy = self._strategies.get(strategy_name)
            if strategy is None:
                continue
            try:
                exit_signal = strategy.check_exit(position, data)
                if exit_signal is not None:
                    exit_signal = {**exit_signal, "strategy": strategy_name, "position": position}
                    exits.append(exit_signal)
            except Exception as e:
                logger.error(f"Strategy {strategy_name} check_exit failed: {e}")

        return exits

    # ── Signal Aggregation ───────────────────────────────────

    def aggregate_signals(
        self,
        signals: list[dict[str, Any]],
        method: str = "score_weighted",
    ) -> dict[str, Any] | None:
        """Aggregate multiple signals into a single consensus signal.

        Args:
            signals: List of signal dicts from generate_signals().
            method: Aggregation method:
                - "score_weighted": Weight signals by their score
                - "vote": Simple majority vote on side
                - "best": Return highest-scoring signal

        Returns:
            Aggregated signal dict or None if no signals.
        """
        if not signals:
            return None

        if method == "best":
            return max(signals, key=lambda s: s.get("score", 0))

        if method == "vote":
            return self._aggregate_vote(signals)

        # Default: score_weighted
        return self._aggregate_score_weighted(signals)

    def _aggregate_vote(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate by majority vote on side."""
        buy_signals = [s for s in signals if s.get("side") == "buy"]
        sell_signals = [s for s in signals if s.get("side") == "sell"]

        if len(buy_signals) > len(sell_signals):
            winner_side = "buy"
            winners = buy_signals
        elif len(sell_signals) > len(buy_signals):
            winner_side = "sell"
            winners = sell_signals
        else:
            # Tie: pick highest score
            best = max(signals, key=lambda s: s.get("score", 0))
            return best

        # Average the winning signals
        avg_score = sum(s.get("score", 0) for s in winners) / len(winners)
        avg_entry = sum(s.get("entry_price", 0) for s in winners) / len(winners)
        avg_sl = sum(s.get("stop_loss", 0) for s in winners) / len(winners)
        avg_tp = sum(s.get("take_profit", 0) for s in winners) / len(winners)

        return {
            "side": winner_side,
            "score": round(avg_score, 4),
            "entry_price": round(avg_entry, 2),
            "stop_loss": round(avg_sl, 2),
            "take_profit": round(avg_tp, 2),
            "aggregation": "vote",
            "vote_count": len(winners),
            "total_signals": len(signals),
            "strategies": [s.get("strategy", "") for s in winners],
        }

    def _aggregate_score_weighted(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate by score-weighted average."""
        buy_signals = [s for s in signals if s.get("side") == "buy"]
        sell_signals = [s for s in signals if s.get("side") == "sell"]

        buy_score = sum(s.get("score", 0) for s in buy_signals)
        sell_score = sum(s.get("score", 0) for s in sell_signals)

        if buy_score > sell_score:
            winner_side = "buy"
            winners = buy_signals
            total_weight = buy_score
        elif sell_score > buy_score:
            winner_side = "sell"
            winners = sell_signals
            total_weight = sell_score
        else:
            best = max(signals, key=lambda s: s.get("score", 0))
            return best

        if total_weight == 0:
            return None

        # Weighted average
        weighted_entry = sum(s.get("entry_price", 0) * s.get("score", 0) for s in winners) / total_weight
        weighted_sl = sum(s.get("stop_loss", 0) * s.get("score", 0) for s in winners) / total_weight
        weighted_tp = sum(s.get("take_profit", 0) * s.get("score", 0) for s in winners) / total_weight
        weighted_score = total_weight / len(winners)

        return {
            "side": winner_side,
            "score": round(min(1.0, weighted_score), 4),
            "entry_price": round(weighted_entry, 2),
            "stop_loss": round(weighted_sl, 2),
            "take_profit": round(weighted_tp, 2),
            "aggregation": "score_weighted",
            "signal_count": len(winners),
            "total_signals": len(signals),
            "strategies": [s.get("strategy", "") for s in winners],
        }
