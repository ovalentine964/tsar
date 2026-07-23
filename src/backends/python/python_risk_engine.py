"""
PythonRiskEngine — Deterministic risk rules in pure Python.

Day1 implementation of RiskEngine. All rules are rule-based.
NO LLM involvement. Level 2: Rust accelerated. Level 5: GPU Monte Carlo.
"""

import logging
from typing import Any

from src.interfaces.risk_engine import RiskEngine
from src.interfaces.types import (
    DrawdownLevel,
    DrawdownState,
    Position,
    PositionSizeResult,
    RiskCheckResult,
    VetoLevel,
)

logger = logging.getLogger(__name__)


class PythonRiskEngine(RiskEngine):
    """Deterministic risk engine — pure rule-based, no LLM."""

    # Canonical limits from TSAR_ARCHITECTURE.md §6
    MAX_POSITION_PCT = 0.15
    MAX_RISK_PER_TRADE_PCT = 0.02
    DAILY_LOSS_LIMIT_PCT = 0.02
    MAX_DRAWDOWN_PCT = 0.05
    MAX_OPEN_POSITIONS = 3  # Day1
    MIN_RISK_REWARD = 2.0
    MAX_DAILY_TRADES = 30
    KELLY_FRACTION = 0.25
    SYMBOL_COOLDOWN_S = 1800

    def __init__(self, **kwargs: Any) -> None:
        self._daily_trades: dict[str, int] = {}  # symbol -> count today
        self._last_trade_time: dict[str, float] = {}  # symbol -> timestamp

    def check_risk(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        signal_score: float,
        current_equity: float,
        open_positions: list[Position],
        daily_pnl: float,
        **kwargs: Any,
    ) -> RiskCheckResult:
        """Run all risk checks on a proposed trade."""
        checks_passed: list[str] = []
        checks_failed: list[str] = []

        # 1. Stop-loss required
        if stop_loss <= 0:
            checks_failed.append("stop_loss_missing")
        else:
            checks_passed.append("stop_loss_set")

        # 2. Risk-reward ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        if risk > 0 and reward / risk < self.MIN_RISK_REWARD:
            checks_failed.append(f"risk_reward_too_low ({reward/risk:.2f} < {self.MIN_RISK_REWARD})")
        else:
            checks_passed.append("risk_reward_ok")

        # 3. Max open positions
        if len(open_positions) >= self.MAX_OPEN_POSITIONS:
            checks_failed.append(f"max_positions ({len(open_positions)} >= {self.MAX_OPEN_POSITIONS})")
        else:
            checks_passed.append("positions_ok")

        # 4. Daily loss limit
        daily_loss_pct = abs(daily_pnl / current_equity * 100) if current_equity > 0 else 0
        if daily_pnl < 0 and daily_loss_pct >= self.DAILY_LOSS_LIMIT_PCT * 100:
            checks_failed.append(f"daily_loss_limit ({daily_loss_pct:.2f}%)")
        else:
            checks_passed.append("daily_loss_ok")

        # 5. Position size check (preliminary)
        risk_amount = current_equity * self.MAX_RISK_PER_TRADE_PCT
        position_value = entry_price * (risk_amount / risk if risk > 0 else 0)
        if position_value > current_equity * self.MAX_POSITION_PCT:
            checks_failed.append("position_size_too_large")
        else:
            checks_passed.append("position_size_ok")

        # 6. Signal score minimum
        if signal_score < 0.6:
            checks_failed.append(f"signal_score_too_low ({signal_score:.2f} < 0.6)")
        else:
            checks_passed.append("signal_score_ok")

        approved = len(checks_failed) == 0
        veto_level = None if approved else VetoLevel.FIRM

        return RiskCheckResult(
            approved=approved,
            veto_level=veto_level,
            reason="All checks passed" if approved else f"Failed: {', '.join(checks_failed)}",
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )

    def calculate_position_size(
        self,
        equity: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
        method: str = "half_kelly",
        **kwargs: Any,
    ) -> PositionSizeResult:
        """Calculate position size using half-Kelly or fixed fraction."""
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return PositionSizeResult(
                quantity=0, notional_value=0, risk_amount=0,
                risk_pct=0, method=method, capped=True, cap_reason="zero_risk_per_unit"
            )

        risk_amount = equity * risk_pct

        if method == "half_kelly":
            fraction = self.KELLY_FRACTION
        elif method == "fixed":
            fraction = risk_pct
        else:
            fraction = self.KELLY_FRACTION

        quantity = (equity * fraction) / entry_price
        notional = quantity * entry_price
        capped = False
        cap_reason = ""

        # Cap at max position size
        max_notional = equity * self.MAX_POSITION_PCT
        if notional > max_notional:
            quantity = max_notional / entry_price
            notional = max_notional
            capped = True
            cap_reason = f"capped_at_{self.MAX_POSITION_PCT*100:.0f}pct"

        return PositionSizeResult(
            quantity=quantity,
            notional_value=notional,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
            method=method,
            capped=capped,
            cap_reason=cap_reason,
        )

    def get_drawdown_state(
        self,
        current_equity: float,
        high_water_mark: float,
        daily_pnl: float,
        daily_loss_limit_pct: float = 2.0,
        max_drawdown_pct: float = 5.0,
    ) -> DrawdownState:
        """Determine current drawdown level and circuit breaker state."""
        if high_water_mark <= 0:
            drawdown_pct = 0.0
        else:
            drawdown_pct = (high_water_mark - current_equity) / high_water_mark * 100

        daily_pnl_pct = (daily_pnl / current_equity * 100) if current_equity > 0 else 0

        # Determine level
        if drawdown_pct >= max_drawdown_pct:
            level = DrawdownLevel.RED
        elif drawdown_pct >= max_drawdown_pct * 0.6:  # 3%
            level = DrawdownLevel.ORANGE
        elif drawdown_pct >= max_drawdown_pct * 0.4:  # 2%
            level = DrawdownLevel.YELLOW
        else:
            level = DrawdownLevel.GREEN

        return DrawdownState(
            current_drawdown_pct=drawdown_pct,
            high_water_mark=high_water_mark,
            current_equity=current_equity,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            level=level,
            is_kill_switch_active=(level == DrawdownLevel.RED),
        )
