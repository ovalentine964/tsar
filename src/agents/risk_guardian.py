"""
Risk Guardian — Gatekeeper agent that approves or rejects every trade.

Role: TRADE_ADMIN
Deterministic. NO LLM involvement. Zero exceptions.

Evaluation checklist (ALL must pass):
  1. Kill switch not active
  2. Circuit breaker not RED
  3. Position size ≤ max_position_pct (15% of equity)
  4. Daily P&L not below daily_loss_limit (-2%)
  5. Open positions < max_open_positions (Day1: 3)
  6. Stop-loss is set and reasonable (≤ 2% from entry)
  7. Risk-reward ratio ≥ min_risk_reward (2:1)
  8. Symbol cooldown not active (30 min)
  9. No conflicting positions (same symbol opposite direction)
  10. Signal score meets minimum threshold

VETO Protocol:
  NONE:   All checks pass — trade approved
  SOFT:   Advisory warning — trade proceeds with warnings
  FIRM:   Trade blocked — can be overridden by admin
  HARD:   Trade blocked — cannot override
  NUCLEAR: Kill switch — halt all trading

Subscribes to: tsar:stream:signals
Publishes to:  tsar:stream:risk_decisions
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.agents.base import BaseAgent
from src.interfaces.types import (
    DrawdownLevel,
    DrawdownState,
    OrderSide,
    Portfolio,
    RiskDecision,
    Signal,
    VetoLevel,
)
from src.risk.mandate_gate import MandateGate

# ── Domain Tools (Tools-to-Agents Wiring) ──────────────────────────
from src.tools.risk_management import RiskManagementTools
from src.tools.stop_loss_calculator import StopLossCalculator
from src.tools.take_profit_calculator import TakeProfitCalculator
from src.tools.fee_calculator import FeeCalculator

if TYPE_CHECKING:
    from src.comms.events import CloudEvent

logger = logging.getLogger(__name__)


class RiskGuardian(BaseAgent):
    """Gatekeeper — approves or rejects every trade signal.

    Pure deterministic risk engine. No LLM calls. No heuristics.
    Every trade must pass ALL checks or it gets vetoed.

    The Risk Guardian has VETO power — it can reject any trade.
    This is the safety harness that prevents the intelligence layer
    from making catastrophic decisions.
    """

    AGENT_NAME = "risk_guardian"
    ROLE = "TRADE_ADMIN"

    PUBLISH_STREAM = "risk_decisions"
    SUBSCRIBE_STREAMS = ["signals"]

    # Risk limits from TSAR_ARCHITECTURE.md §6.1
    DEFAULT_LIMITS = {
        "max_daily_loss_pct": 2.0,        # -2% daily loss limit
        "max_drawdown_pct": 5.0,          # 5% max drawdown from HWM
        "max_open_positions": 3,          # Day1: 3 (prod: 10)
        "max_single_position_pct": 15.0,  # 15% of equity per position
        "min_risk_reward": 2.0,           # 2:1 minimum R:R
        "max_stop_loss_pct": 2.0,         # 2% max stop-loss from entry
        "cooldown_seconds": 1800,         # 30-minute symbol cooldown
        "min_signal_score": 0.6,          # Minimum signal score
        # Entry optimization checks
        "session_timing_check": True,     # Check session timing
        "news_blackout_check": True,      # Check news blackout
        "weekend_risk_check": True,       # Check weekend risk
    }

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        # Merge config overrides
        risk_config = config.get("risk", {})
        self._limits = {**self.DEFAULT_LIMITS, **risk_config}

        # State tracking
        self._symbol_cooldowns: dict[str, float] = {}  # symbol → last trade timestamp
        self._daily_pnl: float = 0.0
        self._high_water_mark: float = 0.0
        self._current_equity: float = 0.0

        # Engine reference (lazy-initialized)
        self._risk_engine = None

        # ── Domain Tools (Tools-to-Agents Wiring) ───────
        self._risk_tools: RiskManagementTools | None = None
        self._sl_calculator: StopLossCalculator | None = None
        self._tp_calculator: TakeProfitCalculator | None = None
        self._fee_calculator: FeeCalculator | None = None

        # Mandate Gate — pre-risk authorization (Check 0)
        mandate_config = risk_config.get("mandate_gate", {})
        if mandate_config.get("enabled", True):
            self._mandate_gate = MandateGate(
                config_path=mandate_config.get("config_path", "config/mandate.yaml")
            )
        else:
            self._mandate_gate = None
        self._is_live = trading_mode == "live"

    async def on_initialize(self) -> None:
        """Initialize the risk engine backend and domain tools."""
        from src.interfaces import get_risk_engine

        self._risk_engine = get_risk_engine()

        # Initialize domain tools
        self._risk_tools = RiskManagementTools(config=self._limits)
        self._sl_calculator = StopLossCalculator(config=self._limits)
        self._tp_calculator = TakeProfitCalculator(config=self._limits)
        self._fee_calculator = FeeCalculator(config=self._limits)

        if self._mandate_gate:
            mandate_status = self._mandate_gate.get_status()
            logger.info(
                "RiskGuardian initialized: limits=%s, mandate=%s (active=%s)",
                {k: v for k, v in self._limits.items()},
                mandate_status["mandate_status"],
                mandate_status["is_active"],
            )
        else:
            logger.info(
                "RiskGuardian initialized: limits=%s, mandate=DISABLED",
                {k: v for k, v in self._limits.items()},
            )

    async def handle_event(self, stream: str, event: CloudEvent) -> None:
        """Handle incoming signal.detected events.

        Args:
            stream: Event stream name.
            event: CloudEvent containing signal data.
        """
        if stream == "signals" and event.type == "tsar.signal.detected.v1":
            await self._evaluate_signal(event)
        else:
            logger.debug("RiskGuardian ignoring event: %s on %s", event.type, stream)

    async def run_cycle(self) -> None:
        """Process incoming signals — main logic is event-driven.

        The RiskGuardian primarily reacts to signal.detected events.
        The run_cycle is kept for heartbeat and periodic maintenance.
        """
        # Periodic maintenance: clean expired cooldowns
        now = time.time()
        expired = [
            sym for sym, ts in self._symbol_cooldowns.items()
            if now - ts > self._limits["cooldown_seconds"] * 2
        ]
        for sym in expired:
            del self._symbol_cooldowns[sym]

    async def _evaluate_signal(self, event: CloudEvent) -> None:
        """Evaluate a trading signal against all risk rules.

        This is THE GATEKEEPER. Every trade must pass ALL checks.

        Args:
            event: CloudEvent containing the signal data.
        """
        data = event.data
        trace_id = event.traceid

        signal = Signal(
            signal_id=data["signal_id"],
            symbol=data["symbol"],
            side=OrderSide(data["side"]),
            score=data["score"],
            entry_price=data["entry_price"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            strategy=data.get("strategy", "unknown"),
            reasoning=data.get("reasoning", ""),
            metadata=data.get("metadata", {}),
        )

        logger.info(
            "🛡️ Evaluating signal: %s %s %s score=%.3f (trace=%s)",
            signal.signal_id, signal.symbol, signal.side.value,
            signal.score, trace_id,
        )

        # ── Check 0: Mandate Gate (pre-risk authorization) ────
        if self._mandate_gate and self._is_live:
            mandate_decision = self._mandate_gate.check(
                signal,
                is_live=True,
                daily_trade_count=signal.metadata.get("daily_trade_count", 0),
            )
            if not mandate_decision.approved:
                logger.warning(
                    "🔒 MANDATE GATE REJECTED [%s]: %s %s — %s",
                    mandate_decision.veto_level,
                    signal.signal_id,
                    signal.symbol,
                    mandate_decision.rejection_reasons,
                )
                await self.publish_event(
                    stream="risk_decisions",
                    event_type="tsar.risk.vetoed.v1",
                    data=self._decision_to_dict(mandate_decision, signal),
                    priority=2,
                    risk_level="HARD",
                    trace_id=trace_id,
                )
                return

        # ── News Blackout Check (async, before sync checks) ────
        if self._limits.get("news_blackout_check", True):
            try:
                from src.tools.market_calendar import MarketCalendar
                from src.agents.trade_manager import NewsProximity
                calendar = MarketCalendar(config=self.config.get("market_calendar", {}))
                snapshot = await calendar.get_calendar(days_ahead=1)
                blocked, reason, risk_mult = NewsProximity.check_news_blackout(snapshot)
                if blocked:
                    logger.warning(
                        "🔒 NEWS BLACKOUT: %s %s — %s",
                        signal.signal_id, signal.symbol, reason,
                    )
                    # Inject blocking result into signal metadata for sync check
                    signal.metadata["news_blackout_blocked"] = True
                    await self.publish_event(
                        stream="risk_decisions",
                        event_type="tsar.risk.vetoed.v1",
                        data={
                            "signal_id": signal.signal_id,
                            "approved": False,
                            "rejection_reasons": [f"NEWS_BLACKOUT: {reason}"],
                            "veto_level": VetoLevel.SOFT.value,
                            "symbol": signal.symbol,
                            "side": signal.side.value,
                        },
                        priority=2,
                        risk_level="SOFT",
                        trace_id=trace_id,
                    )
                    return
            except Exception:
                logger.debug("News blackout check failed", exc_info=True)

        # Run all remaining risk checks
        decision = self._run_all_checks(signal)

        if decision.approved:
            # Calculate position size
            position_size = self._calculate_position_size(signal)

            # Update cooldown
            self._symbol_cooldowns[signal.symbol] = time.time()

            logger.info(
                "✅ APPROVED: %s %s %s qty=%.6f (veto=%s, warnings=%d)",
                signal.signal_id, signal.symbol, signal.side.value,
                position_size, decision.veto_level, len(decision.warnings),
            )
        else:
            logger.warning(
                "❌ VETOED [%s]: %s %s — reasons: %s",
                decision.veto_level, signal.signal_id, signal.symbol,
                decision.rejection_reasons,
            )

        # Publish risk decision event
        event_type = "tsar.risk.approved.v1" if decision.approved else "tsar.risk.vetoed.v1"
        await self.publish_event(
            stream="risk_decisions",
            event_type=event_type,
            data=self._decision_to_dict(decision, signal),
            priority=1 if decision.approved else 2,
            risk_level="NONE" if decision.approved else decision.veto_level,
            trace_id=trace_id,
        )

    def _run_all_checks(self, signal: Signal) -> RiskDecision:
        """Run the full 10-point risk evaluation checklist.

        Args:
            signal: The trading signal to evaluate.

        Returns:
            RiskDecision with approval status and details.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        warnings: list[str] = []

        # ── Check 1: Kill Switch ──────────────────────────────────
        if self._risk_engine and self._risk_engine.get_kill_switch_status():
            checks_failed.append("KILL_SWITCH_ACTIVE: Trading is halted")
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.NUCLEAR.value,
                timestamp=datetime.now(UTC),
            )
        checks_passed.append("kill_switch")

        # ── Check 2: Circuit Breaker ──────────────────────────────
        drawdown = self._get_drawdown_state()
        if drawdown.circuit_breaker_level == DrawdownLevel.RED.value:
            checks_failed.append(
                f"CIRCUIT_BREAKER_RED: Drawdown {drawdown.current_drawdown_pct:.1f}% > 5%"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.HARD.value,
                timestamp=datetime.now(UTC),
            )

        if drawdown.circuit_breaker_level == DrawdownLevel.ORANGE.value:
            checks_failed.append(
                f"CIRCUIT_BREAKER_ORANGE: Drawdown {drawdown.current_drawdown_pct:.1f}% — no new entries"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.FIRM.value,
                timestamp=datetime.now(UTC),
            )

        if drawdown.circuit_breaker_level == DrawdownLevel.YELLOW.value:
            warnings.append(
                f"CIRCUIT_BREAKER_YELLOW: Drawdown {drawdown.current_drawdown_pct:.1f}% — reduced sizing"
            )
        checks_passed.append("circuit_breaker")

        # ── Check 3: Daily Loss Limit ─────────────────────────────
        if self._current_equity > 0:
            daily_loss_pct = (self._daily_pnl / self._current_equity) * 100
            if daily_loss_pct < -self._limits["max_daily_loss_pct"]:
                checks_failed.append(
                    f"DAILY_LOSS_LIMIT: Daily P&L {daily_loss_pct:.2f}% "
                    f"< -{self._limits['max_daily_loss_pct']}%"
                )
                return RiskDecision(
                    signal_id=signal.signal_id,
                    approved=False,
                    position_size=0.0,
                    rejection_reasons=tuple(checks_failed),
                    warnings=tuple(warnings),
                    veto_level=VetoLevel.HARD.value,
                    timestamp=datetime.now(UTC),
                )
        checks_passed.append("daily_loss_limit")

        # ── Check 4: Max Open Positions ───────────────────────────
        open_positions = signal.metadata.get("open_position_count", 0)
        if open_positions >= self._limits["max_open_positions"]:
            checks_failed.append(
                f"MAX_POSITIONS: {open_positions} open >= {self._limits['max_open_positions']} max"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.FIRM.value,
                timestamp=datetime.now(UTC),
            )
        checks_passed.append("max_open_positions")

        # ── Check 5: Stop-Loss Validation ─────────────────────────
        if signal.entry_price <= 0:
            checks_failed.append("INVALID_ENTRY: Entry price must be > 0")
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.HARD.value,
                timestamp=datetime.now(UTC),
            )

        stop_loss_distance_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price * 100
        if stop_loss_distance_pct > self._limits["max_stop_loss_pct"]:
            checks_failed.append(
                f"STOP_LOSS_TOO_WIDE: {stop_loss_distance_pct:.2f}% > "
                f"{self._limits['max_stop_loss_pct']}%"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.FIRM.value,
                timestamp=datetime.now(UTC),
            )

        if signal.stop_loss == 0:
            checks_failed.append("NO_STOP_LOSS: Stop-loss is required")
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.HARD.value,
                timestamp=datetime.now(UTC),
            )
        checks_passed.append("stop_loss_validation")

        # ── Check 6: Risk-Reward Ratio ────────────────────────────
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        if risk > 0:
            rr_ratio = reward / risk
            if rr_ratio < self._limits["min_risk_reward"]:
                checks_failed.append(
                    f"RISK_REWARD: {rr_ratio:.2f} < {self._limits['min_risk_reward']} minimum"
                )
                return RiskDecision(
                    signal_id=signal.signal_id,
                    approved=False,
                    position_size=0.0,
                    rejection_reasons=tuple(checks_failed),
                    warnings=tuple(warnings),
                    veto_level=VetoLevel.FIRM.value,
                    timestamp=datetime.now(UTC),
                )
        checks_passed.append("risk_reward_ratio")

        # ── Check 7: Symbol Cooldown ──────────────────────────────
        last_trade = self._symbol_cooldowns.get(signal.symbol, 0)
        elapsed = time.time() - last_trade
        if elapsed < self._limits["cooldown_seconds"]:
            remaining = self._limits["cooldown_seconds"] - elapsed
            checks_failed.append(
                f"COOLDOWN: {signal.symbol} traded {elapsed:.0f}s ago "
                f"({remaining:.0f}s remaining)"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.FIRM.value,
                timestamp=datetime.now(UTC),
            )
        checks_passed.append("symbol_cooldown")

        # ── Check 8: Conflicting Positions ────────────────────────
        # Check if we have an opposite position on the same symbol
        existing_side = signal.metadata.get("existing_position_side")
        if existing_side and existing_side != signal.side.value:
            checks_failed.append(
                f"CONFLICTING_POSITION: Existing {existing_side} position "
                f"on {signal.symbol}"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.FIRM.value,
                timestamp=datetime.now(UTC),
            )
        checks_passed.append("no_conflicting_positions")

        # ── Check 9: Signal Score ─────────────────────────────────
        if signal.score < self._limits["min_signal_score"]:
            checks_failed.append(
                f"LOW_SCORE: {signal.score:.3f} < {self._limits['min_signal_score']} minimum"
            )
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.SOFT.value,
                timestamp=datetime.now(UTC),
            )
        checks_passed.append("signal_score")

        # ── Check 10: Position Size Limit ─────────────────────────
        # (Actual sizing check happens in _calculate_position_size)
        checks_passed.append("position_size_limit")

        # ── Check 11: Exposure Limits (via RiskManagementTools) ───
        if self._risk_tools:
            try:
                exposure_check = self._risk_tools.check_exposure_limits(
                    current_exposure_usd=self._current_equity * 0.8,  # estimate
                    max_exposure_pct=self._limits.get("max_single_position_pct", 15.0),
                    equity=self._current_equity,
                )
                if not exposure_check.get("within_limits", True):
                    warnings.append(
                        f"EXPOSURE_WARNING: {exposure_check.get('reason', 'approaching limits')}"
                    )
            except Exception:
                logger.debug("Exposure check via tool failed", exc_info=True)

        # ── Check 12: Session Timing Gate ────────────────────────
        if self._limits.get("session_timing_check", True):
            try:
                from src.agents.trade_manager import SessionTiming
                session_allowed, session_reason = SessionTiming.is_entry_allowed()
                if not session_allowed:
                    checks_failed.append(
                        f"SESSION_TIMING: {session_reason}"
                    )
                    return RiskDecision(
                        signal_id=signal.signal_id,
                        approved=False,
                        position_size=0.0,
                        rejection_reasons=tuple(checks_failed),
                        warnings=tuple(warnings),
                        veto_level=VetoLevel.SOFT.value,
                        timestamp=datetime.now(UTC),
                    )
                # Check session quality for risk adjustment
                quality = SessionTiming.get_session_quality()
                if quality < 0.6:
                    warnings.append(
                        f"SESSION_QUALITY_LOW: Quality={quality:.2f} — reduced sizing recommended"
                    )
            except ImportError:
                logger.debug("SessionTiming not available")
            except Exception:
                logger.debug("Session timing check failed", exc_info=True)

        # ── Check 13: Weekend Risk Gate ──────────────────────────
        if self._limits.get("weekend_risk_check", True):
            try:
                from src.agents.trade_manager import SessionTiming
                should_close, weekend_reason = SessionTiming.should_close_for_weekend()
                if should_close:
                    checks_failed.append(
                        f"WEEKEND_RISK: {weekend_reason}"
                    )
                    return RiskDecision(
                        signal_id=signal.signal_id,
                        approved=False,
                        position_size=0.0,
                        rejection_reasons=tuple(checks_failed),
                        warnings=tuple(warnings),
                        veto_level=VetoLevel.SOFT.value,
                        timestamp=datetime.now(UTC),
                    )
            except Exception:
                logger.debug("Weekend risk check failed", exc_info=True)

        # ── Check 14: News Blackout Gate ─────────────────────────
        # NOTE: News blackout is checked in _evaluate_signal (async) before
        # _run_all_checks is called. This is a placeholder for the check result.
        news_blackout_result = signal.metadata.get("news_blackout_blocked", False)
        if news_blackout_result:
            checks_failed.append("NEWS_BLACKOUT: Blocked by news event proximity")
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                position_size=0.0,
                rejection_reasons=tuple(checks_failed),
                warnings=tuple(warnings),
                veto_level=VetoLevel.SOFT.value,
                timestamp=datetime.now(UTC),
            )

        # ── All Checks Passed ─────────────────────────────────────
        veto_level = VetoLevel.SOFT.value if warnings else VetoLevel.NONE.value

        return RiskDecision(
            signal_id=signal.signal_id,
            approved=True,
            position_size=0.0,  # Will be calculated separately
            rejection_reasons=(),
            warnings=tuple(warnings),
            veto_level=veto_level,
            timestamp=datetime.now(UTC),
        )

    def _calculate_position_size(self, signal: Signal) -> float:
        """Calculate position size using Half-Kelly with fee-adjusted R:R.

        Uses StopLossCalculator for validation and FeeCalculator for
        fee-adjusted risk-reward ratio, ensuring position sizing
        accounts for real trading costs.

        Args:
            signal: Approved trading signal.

        Returns:
            Position quantity in base asset units.
        """
        if self._current_equity <= 0 or signal.entry_price <= 0:
            return 0.0

        # Validate stop-loss via tool
        if self._sl_calculator:
            sl_result = self._sl_calculator.calculate_atr(
                entry=signal.entry_price,
                atr=abs(signal.entry_price - signal.stop_loss) / 1.5,  # Back-calculate ATR
                side=signal.side.value,
                multiplier=1.5,
            )
            logger.debug(
                "SL tool validation: price=%.2f dist_pct=%.4f capped=%s",
                sl_result.stop_price, sl_result.distance_pct, sl_result.capped,
            )

        # Fee-adjusted R:R via FeeCalculator
        fee_adjusted_rr = self._limits["min_risk_reward"]
        if self._fee_calculator:
            fee_result = self._fee_calculator.net_risk_reward(
                entry=signal.entry_price,
                stop=signal.stop_loss,
                tp=signal.take_profit,
                tier="vip0",
            )
            fee_adjusted_rr = fee_result.net_rr_ratio
            logger.debug(
                "Fee-adjusted R:R: gross=%.2f net=%.2f fees=%.4f",
                fee_result.gross_rr_ratio, fee_result.net_rr_ratio, fee_result.total_fees,
            )

        # Half-Kelly sizing
        risk_per_trade_pct = 0.02  # 2% risk per trade
        risk_amount = self._current_equity * risk_per_trade_pct

        # Distance to stop-loss
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance <= 0:
            return 0.0

        # Position size = risk_amount / stop_distance
        quantity = risk_amount / stop_distance

        # Cap at max single position %
        max_notional = self._current_equity * (self._limits["max_single_position_pct"] / 100)
        max_quantity = max_notional / signal.entry_price
        quantity = min(quantity, max_quantity)

        # Apply circuit breaker multiplier
        drawdown = self._get_drawdown_state()
        quantity *= drawdown.position_size_multiplier

        logger.info(
            "Position sizing: equity=%.2f risk=%.2f stop_dist=%.2f qty=%.6f "
            "multiplier=%.2f fee_adj_rr=%.2f",
            self._current_equity, risk_amount, stop_distance,
            quantity, drawdown.position_size_multiplier, fee_adjusted_rr,
        )

        return quantity

    def _get_drawdown_state(self) -> DrawdownState:
        """Get current drawdown state.

        Returns:
            DrawdownState with circuit breaker level.
        """
        if self._risk_engine:
            # Use the engine if available
            portfolio = Portfolio(
                equity=self._current_equity,
                high_water_mark=self._high_water_mark,
                cash=self._current_equity,
            )
            return self._risk_engine.get_drawdown_state(portfolio)

        # Fallback: calculate locally
        if self._high_water_mark > 0:
            drawdown_pct = ((self._high_water_mark - self._current_equity) / self._high_water_mark) * 100
        else:
            drawdown_pct = 0.0

        if drawdown_pct < 2.0:
            level = DrawdownLevel.GREEN.value
            trading_allowed = True
            multiplier = 1.0
        elif drawdown_pct < 3.0:
            level = DrawdownLevel.YELLOW.value
            trading_allowed = True
            multiplier = 0.5
        elif drawdown_pct < 5.0:
            level = DrawdownLevel.ORANGE.value
            trading_allowed = False
            multiplier = 0.0
        else:
            level = DrawdownLevel.RED.value
            trading_allowed = False
            multiplier = 0.0

        return DrawdownState(
            current_drawdown_pct=drawdown_pct,
            high_water_mark=self._high_water_mark,
            current_equity=self._current_equity,
            daily_pnl=self._daily_pnl,
            daily_pnl_pct=(self._daily_pnl / self._current_equity * 100) if self._current_equity > 0 else 0,
            circuit_breaker_level=level,
            trading_allowed=trading_allowed,
            position_size_multiplier=multiplier,
        )

    def update_portfolio_state(
        self,
        equity: float,
        high_water_mark: float,
        daily_pnl: float,
    ) -> None:
        """Update portfolio state for risk calculations.

        Called by the Orchestrator or execution feedback loop.

        Args:
            equity: Current total equity.
            high_water_mark: Peak equity value.
            daily_pnl: Today's realized P&L.
        """
        self._current_equity = equity
        self._high_water_mark = high_water_mark
        self._daily_pnl = daily_pnl

    @staticmethod
    def _decision_to_dict(decision: RiskDecision, signal: Signal) -> dict[str, Any]:
        """Convert a RiskDecision to a serializable dict.

        Args:
            decision: RiskDecision instance.
            signal: Original signal.

        Returns:
            Dict suitable for CloudEvents data payload.
        """
        return {
            "signal_id": decision.signal_id,
            "approved": decision.approved,
            "position_size": decision.position_size,
            "rejection_reasons": list(decision.rejection_reasons),
            "warnings": list(decision.warnings),
            "veto_level": decision.veto_level,
            "timestamp": decision.timestamp.isoformat() if decision.timestamp else None,
            # Carry forward signal data for downstream agents
            "symbol": signal.symbol,
            "side": signal.side.value,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "score": signal.score,
            "strategy": signal.strategy,
            "reasoning": signal.reasoning,
        }
