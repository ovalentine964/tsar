# RISK GOVERNOR — COMPLETE ARCHITECTURE

**Version:** 1.0.0
**Date:** 2026-07-24
**Classification:** CRITICAL — This is the most important component of the Trading Super Agent
**Principle:** 100% deterministic. Zero LLM involvement in any risk decision path.

---

## TABLE OF CONTENTS

1. [Architecture Overview](#1-architecture-overview)
2. [Position Sizing Engine](#2-position-sizing-engine)
3. [Drawdown Circuit Breakers](#3-drawdown-circuit-breakers)
4. [Anti-Behavioral Guards](#4-anti-behavioral-guards)
5. [Correlation Monitor](#5-correlation-monitor)
6. [Time-Based Risk Rules](#6-time-based-risk-rules)
7. [Kill Switch](#7-kill-switch)
8. [Veto Protocol](#8-veto-protocol)
9. [Check Cadence & Execution Order](#9-check-cadence--execution-order)
10. [Redis State Schema](#10-redis-state-schema)
11. [Python Implementation](#11-python-implementation)

---

## 1. ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────┐
│                    TRADING SUPER AGENT                       │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Strategy  │  │ Strategy  │  │ Strategy  │  │ Strategy  │  │
│  │ Engine    │  │ Engine    │  │ Engine    │  │ Engine    │  │
│  │ (LLM OK) │  │ (LLM OK) │  │ (LLM OK) │  │ (LLM OK) │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │          │
│       ▼              ▼              ▼              ▼          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              TRADE PROPOSAL (symbol, side, qty,     │    │
│  │              entry, stop, target, conviction)        │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │          ★ RISK GOVERNOR (DETERMINISTIC) ★           │    │
│  │                                                     │    │
│  │  ┌─────────────────────────────────────────────┐    │    │
│  │  │  CHECK 1: Position Sizing Validation        │    │    │
│  │  ├─────────────────────────────────────────────┤    │    │
│  │  │  CHECK 2: Drawdown Circuit Breakers         │    │    │
│  │  ├─────────────────────────────────────────────┤    │    │
│  │  │  CHECK 3: Anti-Behavioral Guards            │    │    │
│  │  ├─────────────────────────────────────────────┤    │    │
│  │  │  CHECK 4: Correlation Limits                │    │    │
│  │  ├─────────────────────────────────────────────┤    │    │
│  │  │  CHECK 5: Time-Based Rules                  │    │    │
│  │  ├─────────────────────────────────────────────┤    │    │
│  │  │  CHECK 6: Kill Switch Status                │    │    │
│  │  ├─────────────────────────────────────────────┤    │    │
│  │  │  CHECK 7: Veto Protocol (Final Gate)        │    │    │
│  │  └─────────────────────────────────────────────┘    │    │
│  │                                                     │    │
│  │  OUTPUT: APPROVE / REJECT / MODIFY                  │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              EXECUTION ENGINE                        │    │
│  │  (Only runs if Risk Governor approves)               │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              POST-TRADE RISK CHECK                   │    │
│  │  (Update state, recalculate all limits)              │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              PERIODIC MONITOR (Background)                    │
│  Runs every 60 seconds:                                      │
│  - Re-check all open positions                               │
│  - Update correlation matrix                                 │
│  - Check drawdown limits                                     │
│  - Monitor for regime changes                                │
│  - Check time-based rules                                    │
│  - Emergency flatten if limits breached                      │
└─────────────────────────────────────────────────────────────┘
```

### Core Invariants

1. **No order reaches the exchange without passing through the Risk Governor**
2. **The Risk Governor is pure deterministic code** — no API calls to LLMs, no "interpretation"
3. **The Risk Governor can only REDUCE position size or REJECT trades** — it can never increase
4. **The Kill Switch works even if the main process is corrupted** — it's a separate lightweight process
5. **All state is persisted in Redis** — survives process crashes
6. **Every decision is logged** — full audit trail with timestamps and reasons

---

## 2. POSITION SIZING ENGINE

### 2.1 Half-Kelly Criterion

**Why Half-Kelly:** Full Kelly maximizes long-term growth but has devastating drawdowns (50% drawdown probability). Half-Kelly sacrifices ~25% of growth for dramatically reduced drawdown risk. This is what Renaissance Technologies and most institutional quant funds use.

```python
import math

def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Calculate Half-Kelly fraction.

    Kelly formula: f* = (p * b - q) / b
    Where:
        p = probability of winning
        q = probability of losing = 1 - p
        b = ratio of average win to average loss (odds)

    Half-Kelly: f*/2

    Returns: fraction of capital to risk (0.0 to 1.0)
    """
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0

    p = win_rate
    q = 1.0 - p
    b = abs(avg_win / avg_loss)

    kelly = (p * b - q) / b

    # Negative Kelly = negative edge = don't trade
    if kelly <= 0:
        return 0.0

    # Half-Kelly for safety
    half_kelly = kelly / 2.0

    # Hard cap: never risk more than 2% of capital per trade
    return min(half_kelly, 0.02)


def calculate_position_size(
    portfolio_value: float,
    entry_price: float,
    stop_loss_price: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    atr: float,
    correlation_penalty: float,  # 0.0 to 1.0, from correlation monitor
) -> dict:
    """
    Calculate final position size incorporating all risk factors.

    Returns dict with:
        - risk_amount: dollar amount at risk
        - position_size_units: number of units/shares/contracts
        - position_value: total value of position
        - risk_pct: actual risk as % of portfolio
        - sizing_method: which method was the binding constraint
    """

    # --- Step 1: Base size from Kelly ---
    kelly_frac = kelly_fraction(win_rate, avg_win, avg_loss)
    kelly_risk_amount = portfolio_value * kelly_frac

    # --- Step 2: Fixed fractional (hard cap) ---
    MAX_RISK_PER_TRADE_PCT = 0.02  # 2%
    fixed_risk_amount = portfolio_value * MAX_RISK_PER_TRADE_PCT

    # --- Step 3: ATR-adjusted sizing ---
    # Stop distance in price terms, but at least 1.5x ATR
    stop_distance = abs(entry_price - stop_loss_price)
    min_stop_distance = 1.5 * atr
    effective_stop_distance = max(stop_distance, min_stop_distance)

    # If stop is too tight relative to ATR, we need fewer units
    # (tight stop = more units for same dollar risk, which is backwards)
    atr_risk_per_unit = effective_stop_distance

    # --- Step 4: Take the MINIMUM of all sizing methods ---
    risk_amounts = {
        'kelly': kelly_risk_amount,
        'fixed_fractional': fixed_risk_amount,
    }

    # The binding constraint is the smallest risk amount
    binding_method = min(risk_amounts, key=risk_amounts.get)
    base_risk_amount = risk_amounts[binding_method]

    # --- Step 5: Apply correlation penalty ---
    # If we have correlated positions, reduce size proportionally
    # correlation_penalty ranges from 0 (no correlation) to 1 (perfect correlation)
    correlation_factor = 1.0 - (correlation_penalty * 0.5)  # Max 50% reduction
    adjusted_risk_amount = base_risk_amount * correlation_factor

    # --- Step 6: Convert to position size ---
    if atr_risk_per_unit <= 0:
        return {
            'risk_amount': 0,
            'position_size_units': 0,
            'position_value': 0,
            'risk_pct': 0,
            'sizing_method': 'invalid_stop',
        }

    position_size_units = adjusted_risk_amount / atr_risk_per_unit
    position_value = position_size_units * entry_price
    risk_pct = adjusted_risk_amount / portfolio_value

    return {
        'risk_amount': round(adjusted_risk_amount, 2),
        'position_size_units': math.floor(position_size_units),  # Round DOWN
        'position_value': round(position_value, 2),
        'risk_pct': round(risk_pct, 6),
        'sizing_method': binding_method,
        'kelly_fraction': round(kelly_frac, 6),
        'correlation_factor': round(correlation_factor, 4),
        'effective_stop_distance': round(effective_stop_distance, 6),
    }
```

### 2.2 Position Size Limits

| Limit | Threshold | Action |
|-------|-----------|--------|
| Max risk per trade | 2% of portfolio | Hard cap, never exceeded |
| Max position value | 10% of portfolio | Single asset concentration limit |
| Max total exposure | 150% of portfolio (gross) | Sum of all absolute position values |
| Max net exposure | 100% of portfolio | Long - Short (directional bias limit) |
| Max positions | 20 open positions | Prevents over-diversification / death by 1000 cuts |
| Max same-sector exposure | 25% of portfolio | Sector concentration limit |
| Min conviction for trade | 0.6 (60%) | Below this, no trade regardless of other factors |

```python
# Position limits configuration (all values are fractions of portfolio)
POSITION_LIMITS = {
    'max_risk_per_trade_pct': 0.02,        # 2%
    'max_position_value_pct': 0.10,        # 10%
    'max_gross_exposure_pct': 1.50,        # 150%
    'max_net_exposure_pct': 1.00,          # 100%
    'max_open_positions': 20,              # Count
    'max_sector_exposure_pct': 0.25,       # 25%
    'min_conviction': 0.60,                # 60%
    'max_single_asset_pct': 0.10,          # 10% in one asset
    'max_correlated_exposure_pct': 0.30,   # 30% in correlated group
}


def check_position_limits(proposal: dict, portfolio_state: dict) -> tuple[bool, str]:
    """
    Validate a trade proposal against all position limits.

    Args:
        proposal: {symbol, side, qty, entry_price, stop_loss, conviction}
        portfolio_state: current portfolio state from Redis

    Returns:
        (approved: bool, reason: str)
    """
    pval = portfolio_state['portfolio_value']
    limits = POSITION_LIMITS

    # Check conviction
    if proposal['conviction'] < limits['min_conviction']:
        return False, f"Conviction {proposal['conviction']:.0%} below minimum {limits['min_conviction']:.0%}"

    # Check position value limit
    position_value = proposal['qty'] * proposal['entry_price']
    if position_value > pval * limits['max_position_value_pct']:
        return False, f"Position value ${position_value:,.0f} exceeds {limits['max_position_value_pct']:.0%} limit (${pval * limits['max_position_value_pct']:,.0f})"

    # Check risk per trade
    risk_per_unit = abs(proposal['entry_price'] - proposal['stop_loss'])
    total_risk = risk_per_unit * proposal['qty']
    if total_risk > pval * limits['max_risk_per_trade_pct']:
        return False, f"Trade risk ${total_risk:,.0f} exceeds {limits['max_risk_per_trade_pct']:.0%} limit"

    # Check gross exposure
    current_gross = portfolio_state['gross_exposure']
    new_gross = current_gross + position_value
    if new_gross > pval * limits['max_gross_exposure_pct']:
        return False, f"Gross exposure ${new_gross:,.0f} would exceed {limits['max_gross_exposure_pct']:.0%} limit"

    # Check net exposure
    direction = 1 if proposal['side'] == 'LONG' else -1
    current_net = portfolio_state['net_exposure']
    new_net = current_net + (position_value * direction)
    if abs(new_net) > pval * limits['max_net_exposure_pct']:
        return False, f"Net exposure ${abs(new_net):,.0f} would exceed {limits['max_net_exposure_pct']:.0%} limit"

    # Check max open positions
    if portfolio_state['open_position_count'] >= limits['max_open_positions']:
        return False, f"Already at max {limits['max_open_positions']} open positions"

    # Check single asset concentration
    existing_in_asset = portfolio_state['positions_by_asset'].get(proposal['symbol'], 0)
    total_in_asset = existing_in_asset + position_value
    if total_in_asset > pval * limits['max_single_asset_pct']:
        return False, f"Total exposure to {proposal['symbol']} would be ${total_in_asset:,.0f}, exceeding {limits['max_single_asset_pct']:.0%} limit"

    # Check sector exposure
    sector = proposal.get('sector', 'unknown')
    existing_sector = portfolio_state['positions_by_sector'].get(sector, 0)
    new_sector = existing_sector + position_value
    if new_sector > pval * limits['max_sector_exposure_pct']:
        return False, f"Sector '{sector}' exposure would be ${new_sector:,.0f}, exceeding {limits['max_sector_exposure_pct']:.0%} limit"

    return True, "All position limits passed"
```

---

## 3. DRAWDOWN CIRCUIT BREAKERS

### 3.1 Drawdown Thresholds & Actions

```
DRAWDOWN LEVELS:

Level 0: GREEN (Normal)
  - Daily P&L: > -1.5%
  - Weekly P&L: > -3%
  - Monthly P&L: > -6%
  - Total drawdown from peak: > -10%
  → Full trading allowed

Level 1: YELLOW (Caution)
  - Daily P&L: -1.5% to -2.5%
  - Weekly P&L: -3% to -5%
  - Monthly P&L: -6% to -10%
  - Total drawdown from peak: -10% to -15%
  → Reduce position sizes by 50%
  → No new high-risk trades
  → Alert sent to operator

Level 2: ORANGE (Danger)
  - Daily P&L: -2.5% to -4%
  - Weekly P&L: -5% to -8%
  - Monthly P&L: -10% to -15%
  - Total drawdown from peak: -15% to -20%
  → Halt all new trades
  → Reduce existing positions by 50%
  → Alert sent with urgency flag
  → Manual review required to resume

Level 3: RED (Emergency)
  - Daily P&L: < -4%
  - Weekly P&L: < -8%
  - Monthly P&L: < -15%
  - Total drawdown from peak: > -20%
  → FLATTEN ALL POSITIONS immediately
  → Kill switch activated
  → Trading halted until manual reset
  → Full incident report generated
```

```python
from enum import IntEnum
from dataclasses import dataclass
from datetime import datetime, timedelta

class RiskLevel(IntEnum):
    GREEN = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3

@dataclass
class DrawdownThresholds:
    daily_loss_warn: float = -0.015     # -1.5%
    daily_loss_halt: float = -0.025     # -2.5%
    daily_loss_kill: float = -0.04      # -4.0%

    weekly_loss_warn: float = -0.03     # -3.0%
    weekly_loss_halt: float = -0.05     # -5.0%
    weekly_loss_kill: float = -0.08     # -8.0%

    monthly_loss_warn: float = -0.06    # -6.0%
    monthly_loss_halt: float = -0.10    # -10.0%
    monthly_loss_kill: float = -0.15    # -15.0%

    total_drawdown_warn: float = -0.10  # -10%
    total_drawdown_halt: float = -0.15  # -15%
    total_drawdown_kill: float = -0.20  # -20%


class DrawdownCircuitBreaker:
    """
    Monitors drawdown across multiple timeframes and triggers
    progressive risk reduction / halts.
    """

    def __init__(self, redis_client, thresholds: DrawdownThresholds = None):
        self.redis = redis_client
        self.thresholds = thresholds or DrawdownThresholds()

    def get_current_state(self) -> dict:
        """Read all drawdown metrics from Redis."""
        now = datetime.utcnow()
        state = self.redis.hgetall('risk:drawdown_state')
        return {
            'daily_pnl_pct': float(state.get('daily_pnl_pct', 0)),
            'weekly_pnl_pct': float(state.get('weekly_pnl_pct', 0)),
            'monthly_pnl_pct': float(state.get('monthly_pnl_pct', 0)),
            'peak_equity': float(state.get('peak_equity', 0)),
            'current_equity': float(state.get('current_equity', 0)),
            'total_drawdown_pct': float(state.get('total_drawdown_pct', 0)),
            'risk_level': RiskLevel(int(state.get('risk_level', 0))),
            'last_updated': state.get('last_updated', ''),
        }

    def evaluate(self) -> tuple[RiskLevel, list[str]]:
        """
        Evaluate all drawdown metrics and return the highest triggered level.

        Returns:
            (risk_level, list of triggered reasons)
        """
        state = self.get_current_state()
        t = self.thresholds
        reasons = []
        max_level = RiskLevel.GREEN

        # --- Check daily P&L ---
        daily = state['daily_pnl_pct']
        if daily <= t.daily_loss_kill:
            max_level = max(max_level, RiskLevel.RED)
            reasons.append(f"DAILY LOSS {daily:.2%} <= {t.daily_loss_kill:.2%} [RED]")
        elif daily <= t.daily_loss_halt:
            max_level = max(max_level, RiskLevel.ORANGE)
            reasons.append(f"Daily loss {daily:.2%} <= {t.daily_loss_halt:.2%} [ORANGE]")
        elif daily <= t.daily_loss_warn:
            max_level = max(max_level, RiskLevel.YELLOW)
            reasons.append(f"Daily loss {daily:.2%} <= {t.daily_loss_warn:.2%} [YELLOW]")

        # --- Check weekly P&L ---
        weekly = state['weekly_pnl_pct']
        if weekly <= t.weekly_loss_kill:
            max_level = max(max_level, RiskLevel.RED)
            reasons.append(f"WEEKLY LOSS {weekly:.2%} <= {t.weekly_loss_kill:.2%} [RED]")
        elif weekly <= t.weekly_loss_halt:
            max_level = max(max_level, RiskLevel.ORANGE)
            reasons.append(f"Weekly loss {weekly:.2%} <= {t.weekly_loss_halt:.2%} [ORANGE]")
        elif weekly <= t.weekly_loss_warn:
            max_level = max(max_level, RiskLevel.YELLOW)
            reasons.append(f"Weekly loss {weekly:.2%} <= {t.weekly_loss_warn:.2%} [YELLOW]")

        # --- Check monthly P&L ---
        monthly = state['monthly_pnl_pct']
        if monthly <= t.monthly_loss_kill:
            max_level = max(max_level, RiskLevel.RED)
            reasons.append(f"MONTHLY LOSS {monthly:.2%} <= {t.monthly_loss_kill:.2%} [RED]")
        elif monthly <= t.monthly_loss_halt:
            max_level = max(max_level, RiskLevel.ORANGE)
            reasons.append(f"Monthly loss {monthly:.2%} <= {t.monthly_loss_halt:.2%} [ORANGE]")
        elif monthly <= t.monthly_loss_warn:
            max_level = max(max_level, RiskLevel.YELLOW)
            reasons.append(f"Monthly loss {monthly:.2%} <= {t.monthly_loss_warn:.2%} [YELLOW]")

        # --- Check total drawdown from peak ---
        dd = state['total_drawdown_pct']
        if dd <= t.total_drawdown_kill:
            max_level = max(max_level, RiskLevel.RED)
            reasons.append(f"TOTAL DRAWDOWN {dd:.2%} <= {t.total_drawdown_kill:.2%} [RED]")
        elif dd <= t.total_drawdown_halt:
            max_level = max(max_level, RiskLevel.ORANGE)
            reasons.append(f"Total drawdown {dd:.2%} <= {t.total_drawdown_halt:.2%} [ORANGE]")
        elif dd <= t.total_drawdown_warn:
            max_level = max(max_level, RiskLevel.YELLOW)
            reasons.append(f"Total drawdown {dd:.2%} <= {t.total_drawdown_warn:.2%} [YELLOW]")

        return max_level, reasons

    def apply_risk_level(self, level: RiskLevel) -> dict:
        """
        Return the action to take based on the risk level.

        Returns:
            {
                'action': 'full_trading' | 'reduced' | 'halt' | 'flatten',
                'size_multiplier': float,  # 1.0 = normal, 0.5 = half, 0 = none
                'allow_new_trades': bool,
                'reduce_existing': float,  # fraction to reduce by (0 = don't reduce)
                'alert_level': str,
            }
        """
        actions = {
            RiskLevel.GREEN: {
                'action': 'full_trading',
                'size_multiplier': 1.0,
                'allow_new_trades': True,
                'reduce_existing': 0.0,
                'alert_level': 'info',
            },
            RiskLevel.YELLOW: {
                'action': 'reduced',
                'size_multiplier': 0.5,
                'allow_new_trades': True,  # But only low-risk setups
                'reduce_existing': 0.0,
                'alert_level': 'warning',
            },
            RiskLevel.ORANGE: {
                'action': 'halt',
                'size_multiplier': 0.0,
                'allow_new_trades': False,
                'reduce_existing': 0.5,  # Reduce existing by 50%
                'alert_level': 'critical',
            },
            RiskLevel.RED: {
                'action': 'flatten',
                'size_multiplier': 0.0,
                'allow_new_trades': False,
                'reduce_existing': 1.0,  # Flatten everything
                'alert_level': 'emergency',
            },
        }
        return actions[level]
```

### 3.2 Recovery Rules

```python
class RecoveryProtocol:
    """
    Rules for resuming trading after a drawdown event.
    """

    RECOVERY_RULES = {
        RiskLevel.YELLOW: {
            'cooldown_minutes': 30,
            'requirement': 'Wait 30 minutes, then resume with 50% sizing for 24 hours',
            'auto_resume': True,
            'resume_size_multiplier': 0.5,
            'resume_duration_hours': 24,
        },
        RiskLevel.ORANGE: {
            'cooldown_minutes': 0,  # No auto-resume
            'requirement': 'Manual review required. Operator must approve resume.',
            'auto_resume': False,
            'resume_size_multiplier': 0.25,  # Resume at 25% size
            'resume_duration_hours': 72,     # 3 days of reduced sizing
        },
        RiskLevel.RED: {
            'cooldown_minutes': 0,  # No auto-resume
            'requirement': 'Full incident report + operator approval + strategy review',
            'auto_resume': False,
            'resume_size_multiplier': 0.10,  # Resume at 10% size
            'resume_duration_hours': 168,    # 7 days of minimal sizing
        },
    }

    def can_resume(self, risk_level: RiskLevel, redis_client) -> tuple[bool, str]:
        """Check if trading can resume after a drawdown event."""
        if risk_level == RiskLevel.GREEN:
            return True, "Normal operation"

        rules = self.RECOVERY_RULES[risk_level]
        halt_time = redis_client.get('risk:halt_timestamp')

        if not halt_time:
            return False, "No halt timestamp found"

        halt_dt = datetime.fromisoformat(halt_time)
        elapsed = (datetime.utcnow() - halt_dt).total_seconds() / 60

        if rules['auto_resume']:
            if elapsed >= rules['cooldown_minutes']:
                return True, f"Cooldown expired ({elapsed:.0f}m >= {rules['cooldown_minutes']}m)"
            return False, f"Cooldown active ({elapsed:.0f}m / {rules['cooldown_minutes']}m)"

        # Manual resume required
        manual_approved = redis_client.get('risk:manual_resume_approved')
        if not manual_approved:
            return False, f"Manual operator approval required for {risk_level.name}"

        return True, f"Manual resume approved. Sizing at {rules['resume_size_multiplier']:.0%} for {rules['resume_duration_hours']}h"
```

---

## 4. ANTI-BEHAVIORAL GUARDS

These protect against the classic psychological traps that destroy traders.

### 4.1 Anti-Revenge (Cooldown After Consecutive Losses)

```python
class AntiRevengeGuard:
    """
    After N consecutive losses, force a cooldown period.
    Prevents the "I need to make it back" spiral.
    """

    # Thresholds
    CONSECUTIVE_LOSSES_TRIGGER = 3      # 3 losses in a row
    COOLDOWN_MINUTES = 60               # 1 hour forced break
    EXTENDED_LOSSES_TRIGGER = 5         # 5 losses in a row
    EXTENDED_COOLDOWN_MINUTES = 240     # 4 hours forced break
    MAX_DAILY_LOSSES = 6                # 6 total losing trades in a day
    DAILY_LOSS_HALT_REST = 480          # 8 hours after 6 daily losses

    def check(self, trade_history: list[dict]) -> tuple[bool, str]:
        """
        Check if revenge trading guard should activate.

        Args:
            trade_history: list of recent trades with 'pnl' field

        Returns:
            (blocked: bool, reason: str)
        """
        if not trade_history:
            return False, ""

        # Check consecutive losses
        consecutive_losses = 0
        for trade in reversed(trade_history):
            if trade['pnl'] < 0:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= self.EXTENDED_LOSSES_TRIGGER:
            return True, (
                f"REVENGE GUARD: {consecutive_losses} consecutive losses. "
                f"Forced cooldown: {self.EXTENDED_COOLDOWN_MINUTES} minutes. "
                f"Step away from the screen."
            )

        if consecutive_losses >= self.CONSECUTIVE_LOSSES_TRIGGER:
            return True, (
                f"REVENGE GUARD: {consecutive_losses} consecutive losses. "
                f"Forced cooldown: {self.COOLDOWN_MINUTES} minutes."
            )

        # Check daily loss count
        today = datetime.utcnow().date()
        daily_losses = sum(
            1 for t in trade_history
            if t['pnl'] < 0 and datetime.fromisoformat(t['closed_at']).date() == today
        )

        if daily_losses >= self.MAX_DAILY_LOSSES:
            return True, (
                f"REVENGE GUARD: {daily_losses} losing trades today (max {self.MAX_DAILY_LOSSES}). "
                f"Trading halted for {self.DAILY_LOSS_HALT_REST} minutes."
            )

        return False, ""
```

### 4.2 Anti-Greed (Deflate After Win Streaks)

```python
class AntiGreedGuard:
    """
    After win streaks, reduce position sizes.
    Win streaks breed overconfidence and oversized positions.
    """

    WIN_STREAK_THRESHOLD = 5            # 5 wins in a row
    SIZE_REDUCTION_FACTOR = 0.7         # Reduce to 70% of normal size
    EXTENDED_WIN_STREAK = 8             # 8 wins in a row
    EXTENDED_REDUCTION_FACTOR = 0.5     # Reduce to 50%
    STREAK_RESET_HOURS = 48             # Streak "expires" after 48h

    def get_size_multiplier(self, trade_history: list[dict]) -> float:
        """
        Returns a multiplier (0.5 to 1.0) for position sizing
        based on recent win streaks.
        """
        if not trade_history:
            return 1.0

        # Count consecutive wins
        consecutive_wins = 0
        for trade in reversed(trade_history):
            if trade['pnl'] > 0:
                consecutive_wins += 1
            else:
                break

        # Also check if wins are recent (within streak window)
        if consecutive_wins > 0:
            last_win_time = datetime.fromisoformat(trade_history[-1]['closed_at'])
            if (datetime.utcnow() - last_win_time).total_seconds() > self.STREAK_RESET_HOURS * 3600:
                return 1.0  # Streak expired

        if consecutive_wins >= self.EXTENDED_WIN_STREAK:
            return self.EXTENDED_REDUCTION_FACTOR

        if consecutive_wins >= self.WIN_STREAK_THRESHOLD:
            return self.SIZE_REDUCTION_FACTOR

        return 1.0
```

### 4.3 Anti-Overconfidence (Conviction Cap)

```python
class AntiOverconfidenceGuard:
    """
    Cap conviction-based sizing to prevent "I'm sure about this one" disasters.
    No single trade should ever be sized based on pure conviction.
    """

    MAX_CONVICTION_SIZE_MULTIPLIER = 1.5   # Even 100% conviction = 1.5x max
    CONVICTION_DECAY_HOURS = 24            # Conviction decays over 24h
    MAX_CONVICTION_POSITIONS = 3           # Max 3 high-conviction positions at once

    def adjust_size_for_conviction(
        self,
        base_size: float,
        conviction: float,
        high_conviction_count: int,
    ) -> tuple[float, str]:
        """
        Adjust position size based on conviction level.

        Args:
            base_size: calculated position size
            conviction: 0.0 to 1.0 (from strategy engine)
            high_conviction_count: number of existing high-conviction positions

        Returns:
            (adjusted_size, reason)
        """
        # Cap conviction at reasonable level
        effective_conviction = min(conviction, 1.0)

        # Map conviction to multiplier: 0.6 → 1.0, 1.0 → 1.5
        # Linear interpolation
        multiplier = 1.0 + (effective_conviction - 0.6) * (self.MAX_CONVICTION_SIZE_MULTIPLIER - 1.0) / 0.4
        multiplier = max(1.0, min(multiplier, self.MAX_CONVICTION_SIZE_MULTIPLIER))

        # Check if we already have too many high-conviction positions
        if conviction >= 0.8 and high_conviction_count >= self.MAX_CONVICTION_POSITIONS:
            multiplier = 1.0  # Cap at base size
            return base_size * multiplier, (
                f"Conviction capped: already {high_conviction_count} high-conviction positions "
                f"(max {self.MAX_CONVICTION_POSITIONS}). Size not boosted."
            )

        adjusted = base_size * multiplier
        reason = f"Conviction {conviction:.0%} → multiplier {multiplier:.2f}x"

        return adjusted, reason
```

### 4.4 Anti-FOMO (Only Trade Registered Setups)

```python
class AntiFOMOGuard:
    """
    Only allow trades that match pre-registered setup types.
    Prevents "oh look, something's moving, I should jump in."
    """

    # Registered setup types (configured at system startup)
    REGISTERED_SETUPS = {
        'momentum_breakout': {
            'description': 'Price breaks above resistance with volume confirmation',
            'required_signals': ['price_breakout', 'volume_surge', 'trend_alignment'],
            'max_trades_per_day': 3,
        },
        'mean_reversion': {
            'description': 'Price deviates >2 std from mean, expecting reversion',
            'required_signals': ['std_deviation', 'support_level', 'rsi_oversold_overbought'],
            'max_trades_per_day': 4,
        },
        'trend_continuation': {
            'description': 'Pullback in established trend with confirmation',
            'required_signals': ['trend_direction', 'pullback_level', 'momentum_resume'],
            'max_trades_per_day': 3,
        },
        'news_reaction': {
            'description': 'Delayed reaction to significant news event',
            'required_signals': ['news_event', 'price_reaction', 'volume_confirmation'],
            'max_trades_per_day': 2,
        },
        'volatility_compression': {
            'description': 'Low volatility regime breakout',
            'required_signals': ['volatility_percentile', 'range_contraction', 'directional_bias'],
            'max_trades_per_day': 2,
        },
    }

    def validate_setup(self, proposal: dict, todays_trades: list[dict]) -> tuple[bool, str]:
        """
        Validate that a trade proposal matches a registered setup.

        Args:
            proposal: {setup_type, signals_present: list[str], ...}
            todays_trades: list of trades taken today

        Returns:
            (approved: bool, reason: str)
        """
        setup_type = proposal.get('setup_type')

        if setup_type not in self.REGISTERED_SETUPS:
            return False, (
                f"FOMO GUARD: Setup type '{setup_type}' is not registered. "
                f"Registered setups: {list(self.REGISTERED_SETUPS.keys())}"
            )

        setup = self.REGISTERED_SETUPS[setup_type]

        # Check all required signals are present
        present = set(proposal.get('signals_present', []))
        required = set(setup['required_signals'])
        missing = required - present

        if missing:
            return False, (
                f"FOMO GUARD: Setup '{setup_type}' missing signals: {missing}. "
                f"Required: {required}"
            )

        # Check daily limit for this setup type
        setup_count_today = sum(
            1 for t in todays_trades
            if t.get('setup_type') == setup_type
        )

        if setup_count_today >= setup['max_trades_per_day']:
            return False, (
                f"FOMO GUARD: Already taken {setup_count_today} '{setup_type}' trades today "
                f"(max {setup['max_trades_per_day']})"
            )

        return True, f"Setup '{setup_type}' validated with all {len(required)} signals present"
```

---

## 5. CORRELATION MONITOR

### 5.1 Real-Time Correlation Tracking

```python
import numpy as np
from collections import defaultdict

class CorrelationMonitor:
    """
    Monitor real-time correlation between active positions.
    Prevents concentrated risk from correlated bets.
    """

    # Configuration
    CORRELATION_WINDOW = 60             # Rolling window in periods (e.g., 60 1-min bars)
    HIGH_CORRELATION_THRESHOLD = 0.7    # Correlation above this = "correlated"
    REGIME_CHANGE_THRESHOLD = 0.85      # Correlation spike = potential regime change
    MAX_CORRELATED_EXPOSURE_PCT = 0.30  # 30% max in correlated group
    CORRELATION_UPDATE_INTERVAL = 300   # Update every 5 minutes

    # Asset correlation groups (static baseline, updated dynamically)
    KNOWN_CORRELATION_GROUPS = {
        'crypto_majors': ['BTC', 'ETH', 'SOL', 'BNB'],
        'tech_mega': ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META'],
        'semiconductors': ['NVDA', 'AMD', 'INTC', 'TSM', 'AVGO'],
        'defi': ['UNI', 'AAVE', 'MKR', 'COMP'],
        'meme_coins': ['DOGE', 'SHIB', 'PEPE'],
    }

    def __init__(self, redis_client):
        self.redis = redis_client

    def calculate_correlation_matrix(self, returns_data: dict[str, list[float]]) -> np.ndarray:
        """
        Calculate correlation matrix from returns data.

        Args:
            returns_data: {symbol: [returns...]} for each active position

        Returns:
            correlation_matrix (numpy array)
        """
        symbols = sorted(returns_data.keys())
        n = len(symbols)
        matrix = np.zeros((n, n))

        for i, sym_i in enumerate(symbols):
            for j, sym_j in enumerate(symbols):
                if i == j:
                    matrix[i][j] = 1.0
                elif i < j:
                    corr = np.corrcoef(returns_data[sym_i], returns_data[sym_j])[0][1]
                    matrix[i][j] = corr
                    matrix[j][i] = corr

        return matrix, symbols

    def get_correlated_groups(
        self,
        positions: dict[str, float],  # symbol -> position_value
        returns_data: dict[str, list[float]],
    ) -> list[dict]:
        """
        Identify groups of correlated positions and their total exposure.

        Returns list of:
        {
            'symbols': [list of correlated symbols],
            'avg_correlation': float,
            'total_exposure': float,
            'exposure_pct': float,  # as % of portfolio
            'risk_level': 'normal' | 'warning' | 'critical'
        }
        """
        if len(positions) < 2:
            return []

        matrix, symbols = self.calculate_correlation_matrix(returns_data)
        groups = []
        visited = set()

        for i, sym_i in enumerate(symbols):
            if sym_i in visited:
                continue

            group = [sym_i]
            group_corrs = []

            for j, sym_j in enumerate(symbols):
                if i != j and sym_j not in visited:
                    corr = abs(matrix[i][j])
                    if corr >= self.HIGH_CORRELATION_THRESHOLD:
                        group.append(sym_j)
                        group_corrs.append(corr)

            if len(group) > 1:
                total_exposure = sum(abs(positions.get(s, 0)) for s in group)
                avg_corr = np.mean(group_corrs) if group_corrs else 0

                risk_level = 'normal'
                if avg_corr >= self.REGIME_CHANGE_THRESHOLD:
                    risk_level = 'critical'
                elif avg_corr >= self.HIGH_CORRELATION_THRESHOLD:
                    risk_level = 'warning'

                groups.append({
                    'symbols': group,
                    'avg_correlation': round(avg_corr, 4),
                    'total_exposure': round(total_exposure, 2),
                    'risk_level': risk_level,
                })

                visited.update(group)

        return groups

    def get_correlation_penalty(
        self,
        new_symbol: str,
        existing_positions: dict[str, float],
        returns_data: dict[str, list[float]],
    ) -> float:
        """
        Calculate correlation penalty for a new trade.

        Returns penalty from 0.0 (no correlation) to 1.0 (perfect correlation).
        This is fed into the position sizing engine.
        """
        if not existing_positions or not returns_data:
            return 0.0

        if new_symbol not in returns_data:
            return 0.0

        max_corr = 0.0
        total_weighted_corr = 0.0
        total_exposure = sum(abs(v) for v in existing_positions.values())

        for symbol, exposure in existing_positions.items():
            if symbol in returns_data:
                corr = abs(np.corrcoef(
                    returns_data[new_symbol],
                    returns_data[symbol]
                )[0][1])

                # Weight by exposure size
                weight = abs(exposure) / total_exposure if total_exposure > 0 else 0
                total_weighted_corr += corr * weight
                max_corr = max(max_corr, corr)

        # Blend of max correlation and weighted average
        penalty = 0.6 * max_corr + 0.4 * total_weighted_corr
        return min(penalty, 1.0)

    def check_regime_change(self, returns_data: dict[str, list[float]]) -> tuple[bool, str]:
        """
        Detect if correlation spike indicates a regime change.
        During crises, all correlations go to 1.0 — this is dangerous.
        """
        if len(returns_data) < 3:
            return False, ""

        matrix, symbols = self.calculate_correlation_matrix(returns_data)

        # Calculate average pairwise correlation
        n = len(symbols)
        total_corr = 0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                total_corr += abs(matrix[i][j])
                count += 1

        avg_corr = total_corr / count if count > 0 else 0

        # Load historical average for comparison
        hist_avg = float(self.redis.get('risk:historical_avg_correlation') or 0.3)

        if avg_corr > hist_avg * 2.0 and avg_corr > 0.7:
            return True, (
                f"REGIME CHANGE DETECTED: Average correlation {avg_corr:.2f} "
                f"is {avg_corr/hist_avg:.1f}x the historical average ({hist_avg:.2f}). "
                f"Likely risk-off event. Reducing all exposure."
            )

        return False, ""
```

---

## 6. TIME-BASED RISK RULES

### 6.1 Economic Calendar Blackout

```python
class TimeBasedRiskRules:
    """
    Time-based trading restrictions.
    """

    # High-impact events that require blackout
    # Format: (event_name, pre_blackout_minutes, post_blackout_minutes)
    HIGH_IMPACT_EVENTS = [
        ('NFP', 30, 30),              # Non-Farm Payrolls
        ('CPI', 30, 30),              # Consumer Price Index
        ('FOMC_RATE', 60, 60),        # Fed Rate Decision
        ('FOMC_MINUTES', 30, 30),     # Fed Minutes Release
        ('ECB_RATE', 30, 30),         # ECB Rate Decision
        ('BOJ_RATE', 30, 30),         # BOJ Rate Decision
        ('GDP', 15, 15),              # GDP Release
        ('UNEMPLOYMENT', 15, 15),     # Unemployment Rate
        ('PPI', 15, 15),              # Producer Price Index
        ('RETAIL_SALES', 15, 15),     # Retail Sales
    ]

    # Weekend rules
    WEEKEND_CLOSE_HOUR_UTC = 20       # Close positions by Friday 20:00 UTC
    WEEKEND_REDUCE_HOUR_UTC = 16      # Start reducing by Friday 16:00 UTC
    WEEKEND_REDUCTION_FACTOR = 0.5    # Reduce to 50% by Friday 20:00

    # Session rules
    NO_NEW_POSITIONS_LAST_HOURS = 1   # No new positions in last hour of session
    ASIAN_SESSION_LOW_LIQUIDITY = True  # Reduce size during Asian session

    # Funding rate (crypto specific)
    FUNDING_RATE_THRESHOLD = 0.01     # 1% funding rate = expensive
    FUNDING_RATE_REDUCE_AT = 0.005    # Start reducing at 0.5%

    def check_event_blackout(self, current_time: datetime, events: list[dict]) -> tuple[bool, str]:
        """
        Check if we're in a blackout period around a high-impact event.

        Args:
            current_time: current UTC time
            events: list of upcoming events with {name, datetime, impact}

        Returns:
            (blocked: bool, reason: str)
        """
        for event in events:
            if event.get('impact') != 'high':
                continue

            event_time = datetime.fromisoformat(event['datetime'])
            minutes_until = (event_time - current_time).total_seconds() / 60

            for event_name, pre_min, post_min in self.HIGH_IMPACT_EVENTS:
                if event_name in event.get('name', '').upper():
                    if -post_min <= minutes_until <= pre_min:
                        return True, (
                            f"BLACKOUT: {event_name} in {minutes_until:.0f} minutes. "
                            f"Blackout window: {pre_min}min before / {post_min}min after."
                        )

        return False, ""

    def check_weekend_rules(self, current_time: datetime) -> tuple[bool, float, str]:
        """
        Check weekend exposure rules.

        Returns:
            (apply_reduction: bool, size_multiplier: float, reason: str)
        """
        # Friday checks
        if current_time.weekday() == 4:  # Friday
            hour = current_time.hour

            if hour >= self.WEEKEND_CLOSE_HOUR_UTC:
                return True, 0.0, (
                    f"WEEKEND RULE: It's Friday {hour}:00 UTC. "
                    f"All positions should be closed by {self.WEEKEND_CLOSE_HOUR_UTC}:00 UTC."
                )
            elif hour >= self.WEEKEND_REDUCE_HOUR_UTC:
                return True, self.WEEKEND_REDUCTION_FACTOR, (
                    f"WEEKEND RULE: It's Friday {hour}:00 UTC. "
                    f"Reducing exposure to {self.WEEKEND_REDUCTION_FACTOR:.0%} before weekend."
                )

        # Saturday/Sunday - no trading
        if current_time.weekday() in (5, 6):
            return True, 0.0, "WEEKEND RULE: No trading on weekends."

        return False, 1.0, ""

    def check_session_rules(self, current_time: datetime) -> tuple[bool, str]:
        """
        Check session-based trading restrictions.
        """
        hour = current_time.hour

        # Late session check (assuming we track session end times)
        # This is market-specific and should be configured per market

        # Low liquidity periods
        if self.ASIAN_SESSION_LOW_LIQUIDITY and 0 <= hour <= 6:
            return False, "ADVISORY: Asian session low liquidity. Reduce position sizes by 25%."

        return False, ""

    def check_funding_rate(self, symbol: str, funding_rate: float, side: str) -> tuple[bool, float, str]:
        """
        Check if funding rate makes the trade expensive.

        For perpetual futures: positive funding = longs pay shorts
        """
        if abs(funding_rate) < self.FUNDING_RATE_REDUCE_AT:
            return False, 1.0, ""

        # If funding is positive and we're long, we pay
        # If funding is negative and we're short, we pay
        paying_funding = (
            (funding_rate > 0 and side == 'LONG') or
            (funding_rate < 0 and side == 'SHORT')
        )

        if paying_funding:
            if abs(funding_rate) >= self.FUNDING_RATE_THRESHOLD:
                return True, 0.5, (
                    f"FUNDING RATE WARNING: {symbol} funding rate {funding_rate:.4%} is expensive "
                    f"for {side} position. Reducing size by 50%."
                )
            else:
                return True, 0.75, (
                    f"FUNDING RATE: {symbol} funding rate {funding_rate:.4%} is elevated "
                    f"for {side}. Reducing size by 25%."
                )

        return False, 1.0, ""
```

### 6.2 Event Calendar Integration

```python
class EconomicCalendar:
    """
    Integration with economic calendar data.
    Events are fetched and cached in Redis.
    """

    REDIS_KEY = 'risk:economic_calendar'
    CACHE_TTL = 3600  # Refresh every hour

    def get_upcoming_events(self, redis_client, hours_ahead: int = 48) -> list[dict]:
        """Get upcoming high-impact events from Redis cache."""
        import json
        cached = redis_client.get(self.REDIS_KEY)
        if cached:
            events = json.loads(cached)
            cutoff = datetime.utcnow() + timedelta(hours=hours_ahead)
            return [
                e for e in events
                if datetime.fromisoformat(e['datetime']) <= cutoff
            ]
        return []

    def is_blackout_active(self, redis_client) -> tuple[bool, str]:
        """Quick check if any blackout is currently active."""
        events = self.get_upcoming_events(redis_client, hours_ahead=4)
        time_rules = TimeBasedRiskRules()
        return time_rules.check_event_blackout(datetime.utcnow(), events)
```

---

## 7. KILL SWITCH

### 7.1 Kill Switch Architecture

The Kill Switch is the nuclear option. It must work even if the main trading process is compromised.

```
┌─────────────────────────────────────────────────────────┐
│                    KILL SWITCH SYSTEM                     │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────┐           │
│  │  TRIGGER          │    │  TRIGGER          │          │
│  │  DETECTOR         │    │  MANUAL           │          │
│  │  (Automatic)      │    │  (Human)          │          │
│  └────────┬─────────┘    └────────┬─────────┘          │
│           │                       │                      │
│           ▼                       ▼                      │
│  ┌──────────────────────────────────────────────┐       │
│  │           REDIS KILL SWITCH FLAG              │       │
│  │           risk:kill_switch = ACTIVE           │       │
│  │           (atomic set, survives crashes)       │       │
│  └──────────────────────┬───────────────────────┘       │
│                         │                                │
│           ┌─────────────┼─────────────┐                  │
│           ▼             ▼             ▼                  │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────┐        │
│  │ Main Process  │ │ Monitor  │ │ Exchange API │        │
│  │ Checks flag   │ │ Process  │ │ Direct       │        │
│  │ before every  │ │ Checks   │ │ Cancel All   │        │
│  │ order         │ │ every 5s │ │ Orders       │        │
│  └──────────────┘ └──────────┘ └──────────────┘        │
│                                                          │
│  ALL PATHS converge on: CANCEL ALL ORDERS + FLATTEN      │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Kill Switch Implementation

```python
import json
import time
from datetime import datetime
from enum import Enum

class KillSwitchTrigger(Enum):
    DRAWDOWN_RED = "drawdown_red"
    DAILY_LOSS = "daily_loss_4pct"
    CONSECUTIVE_LOSES = "consecutive_losses_5"
    CORRELATION_SPIKE = "correlation_regime_change"
    MANUAL = "manual_operator"
    EXCHANGE_ERROR = "exchange_connectivity"
    DATA_FEED_LOSS = "data_feed_loss"
    UNEXPECTED_ERROR = "unexpected_exception"
    POSITION_LIMIT_BREACH = "position_limit_breach"
    RAPID_MARKET_MOVE = "rapid_adverse_move"


class KillSwitch:
    """
    Emergency kill switch. Flattens all positions and halts trading.
    Operates independently of the main trading loop.
    """

    REDIS_KEY = 'risk:kill_switch'
    REDIS_REASON_KEY = 'risk:kill_switch_reason'
    REDIS_TIMESTAMP_KEY = 'risk:kill_switch_timestamp'
    REDIS_LOG_KEY = 'risk:kill_switch_log'

    # Auto-triggers
    RAPID_MOVE_THRESHOLD_PCT = 0.05     # 5% adverse move in 5 minutes
    MAX_CONSECUTIVE_ERRORS = 3          # 3 exchange errors in a row
    DATA_FEED_TIMEOUT_SECONDS = 30      # No data for 30 seconds

    def __init__(self, redis_client, exchange_client=None, notifier=None):
        self.redis = redis_client
        self.exchange = exchange_client
        self.notifier = notifier

    def is_active(self) -> bool:
        """Check if kill switch is active."""
        return self.redis.get(self.REDIS_KEY) == 'ACTIVE'

    def activate(self, trigger: KillSwitchTrigger, details: str = "") -> dict:
        """
        ACTIVATE THE KILL SWITCH.
        This is the most critical function in the entire system.
        """
        timestamp = datetime.utcnow().isoformat()
        reason = f"{trigger.value}: {details}"

        # 1. Set the flag atomically
        pipe = self.redis.pipeline()
        pipe.set(self.REDIS_KEY, 'ACTIVE')
        pipe.set(self.REDIS_REASON_KEY, reason)
        pipe.set(self.REDIS_TIMESTAMP_KEY, timestamp)
        pipe.lpush(self.REDIS_LOG_KEY, json.dumps({
            'timestamp': timestamp,
            'trigger': trigger.value,
            'details': details,
            'action': 'ACTIVATED',
        }))
        pipe.execute()

        # 2. Cancel all open orders on exchange
        cancel_result = self._cancel_all_orders()

        # 3. Flatten all positions
        flatten_result = self._flatten_all_positions()

        # 4. Send emergency notification
        notification = (
            f"🚨🚨🚨 KILL SWITCH ACTIVATED 🚨🚨🚨\n"
            f"Trigger: {trigger.value}\n"
            f"Details: {details}\n"
            f"Time: {timestamp}\n"
            f"Orders cancelled: {cancel_result}\n"
            f"Positions flattened: {flatten_result}\n"
            f"\nTrading is HALTED. Manual reset required."
        )

        if self.notifier:
            self.notifier.send_emergency(notification)

        return {
            'status': 'ACTIVE',
            'trigger': trigger.value,
            'reason': reason,
            'timestamp': timestamp,
            'orders_cancelled': cancel_result,
            'positions_flattened': flatten_result,
        }

    def _cancel_all_orders(self) -> dict:
        """Cancel all open orders across all exchanges."""
        if not self.exchange:
            return {'error': 'No exchange client configured'}

        results = {}
        try:
            open_orders = self.exchange.get_open_orders()
            for order in open_orders:
                try:
                    self.exchange.cancel_order(order['id'], order['symbol'])
                    results[order['id']] = 'cancelled'
                except Exception as e:
                    results[order['id']] = f'error: {str(e)}'
        except Exception as e:
            results['global_error'] = str(e)

        return results

    def _flatten_all_positions(self) -> dict:
        """Close all open positions at market."""
        if not self.exchange:
            return {'error': 'No exchange client configured'}

        results = {}
        try:
            positions = self.exchange.get_positions()
            for pos in positions:
                if abs(pos['size']) > 0:
                    try:
                        # Market order to close
                        side = 'SELL' if pos['side'] == 'LONG' else 'BUY'
                        order = self.exchange.create_market_order(
                            symbol=pos['symbol'],
                            side=side,
                            size=abs(pos['size']),
                            reduce_only=True,
                        )
                        results[pos['symbol']] = {
                            'status': 'closed',
                            'order_id': order['id'],
                        }
                    except Exception as e:
                        results[pos['symbol']] = {
                            'status': 'error',
                            'error': str(e),
                        }
        except Exception as e:
            results['global_error'] = str(e)

        return results

    def deactivate(self, operator_id: str, reason: str) -> bool:
        """
        Deactivate the kill switch. REQUIRES HUMAN AUTHORIZATION.
        """
        # Log the deactivation
        timestamp = datetime.utcnow().isoformat()
        self.redis.lpush(self.REDIS_LOG_KEY, json.dumps({
            'timestamp': timestamp,
            'operator': operator_id,
            'reason': reason,
            'action': 'DEACTIVATED',
        }))

        # Clear the flags
        pipe = self.redis.pipeline()
        pipe.delete(self.REDIS_KEY)
        pipe.delete(self.REDIS_REASON_KEY)
        pipe.set('risk:resume_timestamp', timestamp)
        pipe.set('risk:resume_operator', operator_id)
        pipe.execute()

        return True


class AutoKillDetector:
    """
    Runs as a separate lightweight process.
    Monitors for conditions that should trigger the kill switch.
    """

    def __init__(self, redis_client, exchange_client, kill_switch: KillSwitch):
        self.redis = redis_client
        self.exchange = exchange_client
        self.kill_switch = kill_switch

    def run_check(self) -> None:
        """Run all auto-kill checks. Call every 5 seconds."""

        if self.kill_switch.is_active():
            return  # Already killed

        # Check 1: Drawdown level RED
        risk_level = int(self.redis.get('risk:current_level') or 0)
        if risk_level >= 3:  # RED
            self.kill_switch.activate(
                KillSwitchTrigger.DRAWDOWN_RED,
                f"Risk level reached RED ({risk_level})"
            )
            return

        # Check 2: Exchange connectivity
        try:
            self.exchange.ping()
            self.redis.set('risk:last_exchange_ping', time.time())
        except Exception:
            last_ping = float(self.redis.get('risk:last_exchange_ping') or 0)
            if time.time() - last_ping > 30:
                self.kill_switch.activate(
                    KillSwitchTrigger.EXCHANGE_ERROR,
                    f"Exchange unreachable for {time.time() - last_ping:.0f}s"
                )
                return

        # Check 3: Data feed staleness
        last_price_update = float(self.redis.get('risk:last_price_update') or 0)
        if time.time() - last_price_update > self.kill_switch.DATA_FEED_TIMEOUT_SECONDS:
            self.kill_switch.activate(
                KillSwitchTrigger.DATA_FEED_LOSS,
                f"No price data for {time.time() - last_price_update:.0f}s"
            )
            return

        # Check 4: Rapid adverse market move
        positions = self.exchange.get_positions()
        for pos in positions:
            entry = pos.get('entry_price', 0)
            current = pos.get('mark_price', 0)
            if entry > 0:
                pnl_pct = (current - entry) / entry
                if pos['side'] == 'SHORT':
                    pnl_pct = -pnl_pct

                if pnl_pct < -self.kill_switch.RAPID_MOVE_THRESHOLD_PCT:
                    self.kill_switch.activate(
                        KillSwitchTrigger.RAPID_MARKET_MOVE,
                        f"{pos['symbol']} moved {pnl_pct:.2%} against position"
                    )
                    return

    def start_monitoring(self, interval_seconds: int = 5):
        """Start the monitoring loop (run as separate process/thread)."""
        while True:
            try:
                self.run_check()
            except Exception as e:
                # The monitor itself should never crash
                self.redis.lpush('risk:monitor_errors', json.dumps({
                    'timestamp': datetime.utcnow().isoformat(),
                    'error': str(e),
                }))
            time.sleep(interval_seconds)
```

---

## 8. VETO PROTOCOL

### 8.1 Pre-Trade Veto Flow

```python
@dataclass
class TradeProposal:
    """Trade proposal from strategy engine."""
    symbol: str
    side: str            # 'LONG' or 'SHORT'
    entry_price: float
    stop_loss: float
    take_profit: float
    conviction: float    # 0.0 to 1.0
    setup_type: str      # Must match registered setup
    signals_present: list[str]
    strategy_id: str
    sector: str
    asset_class: str     # 'crypto', 'equity', 'forex', 'commodity'
    timeframe: str
    risk_reward_ratio: float
    metadata: dict       # Additional strategy-specific data


@dataclass
class VetoResult:
    """Result of the veto protocol evaluation."""
    approved: bool
    modified_qty: int | None  # If approved with modified size
    checks_passed: list[str]
    checks_failed: list[str]
    warnings: list[str]
    final_risk_pct: float
    timestamp: str
    decision_id: str


class VetoProtocol:
    """
    The final gate before any trade is executed.
    Runs ALL risk checks in order and produces a go/no-go decision.
    """

    def __init__(self, redis_client, config: dict = None):
        self.redis = redis_client
        self.config = config or {}

        # Initialize all guard components
        self.drawdown_breaker = DrawdownCircuitBreaker(redis_client)
        self.anti_revenge = AntiRevengeGuard()
        self.anti_greed = AntiGreedGuard()
        self.anti_overconfidence = AntiOverconfidenceGuard()
        self.anti_fomo = AntiFOMOGuard()
        self.correlation_monitor = CorrelationMonitor(redis_client)
        self.time_rules = TimeBasedRiskRules()
        self.kill_switch = KillSwitch(redis_client)
        self.calendar = EconomicCalendar()

    def evaluate(self, proposal: TradeProposal) -> VetoResult:
        """
        Run the complete veto protocol on a trade proposal.

        This is THE function that determines if a trade happens.
        Every check is deterministic. No LLM involvement.

        Execution order matters — cheapest checks first, most critical last.
        """
        checks_passed = []
        checks_failed = []
        warnings = []
        modified_qty = None

        # ============================================================
        # GATE 0: Kill Switch (instant reject if active)
        # ============================================================
        if self.kill_switch.is_active():
            return VetoResult(
                approved=False,
                modified_qty=None,
                checks_passed=[],
                checks_failed=['KILL_SWITCH_ACTIVE: Trading is halted by kill switch'],
                warnings=[],
                final_risk_pct=0.0,
                timestamp=datetime.utcnow().isoformat(),
                decision_id=self._generate_id(),
            )

        # ============================================================
        # GATE 1: Basic Validation
        # ============================================================
        if proposal.entry_price <= 0 or proposal.stop_loss <= 0:
            checks_failed.append(f"INVALID_PRICES: entry={proposal.entry_price}, stop={proposal.stop_loss}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        if proposal.side not in ('LONG', 'SHORT'):
            checks_failed.append(f"INVALID_SIDE: {proposal.side}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        # Validate stop is on correct side
        if proposal.side == 'LONG' and proposal.stop_loss >= proposal.entry_price:
            checks_failed.append("INVALID_STOP: Long stop must be below entry")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        if proposal.side == 'SHORT' and proposal.stop_loss <= proposal.entry_price:
            checks_failed.append("INVALID_STOP: Short stop must be above entry")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        checks_passed.append("basic_validation")

        # ============================================================
        # GATE 2: Anti-FOMO (setup validation)
        # ============================================================
        portfolio_state = self._get_portfolio_state()
        trade_history = self._get_trade_history()
        todays_trades = self._get_todays_trades()

        fomo_ok, fomo_reason = self.anti_fomo.validate_setup(
            {'setup_type': proposal.setup_type, 'signals_present': proposal.signals_present},
            todays_trades,
        )
        if not fomo_ok:
            checks_failed.append(fomo_reason)
            return self._build_result(False, None, checks_passed, checks_failed, warnings)
        checks_passed.append("anti_fomo")

        # ============================================================
        # GATE 3: Time-Based Rules
        # ============================================================
        now = datetime.utcnow()

        # Weekend check
        weekend_reduced, weekend_mult, weekend_reason = self.time_rules.check_weekend_rules(now)
        if weekend_mult == 0.0:
            checks_failed.append(f"WEEKEND_HALT: {weekend_reason}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)
        if weekend_reduced:
            warnings.append(weekend_reason)

        # Event blackout
        events = self.calendar.get_upcoming_events(self.redis)
        blackout, blackout_reason = self.time_rules.check_event_blackout(now, events)
        if blackout:
            checks_failed.append(f"EVENT_BLACKOUT: {blackout_reason}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)
        checks_passed.append("time_rules")

        # ============================================================
        # GATE 4: Anti-Behavioral Guards
        # ============================================================

        # Anti-revenge
        revenge_blocked, revenge_reason = self.anti_revenge.check(trade_history)
        if revenge_blocked:
            checks_failed.append(f"ANTI_REVENGE: {revenge_reason}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)
        checks_passed.append("anti_revenge")

        # Anti-greed sizing multiplier
        greed_mult = self.anti_greed.get_size_multiplier(trade_history)
        if greed_mult < 1.0:
            warnings.append(f"ANTI_GREED: Win streak detected, sizing at {greed_mult:.0%}")

        checks_passed.append("anti_greed")

        # ============================================================
        # GATE 5: Drawdown Circuit Breakers
        # ============================================================
        risk_level, dd_reasons = self.drawdown_breaker.evaluate()
        action = self.drawdown_breaker.apply_risk_level(risk_level)

        if not action['allow_new_trades']:
            checks_failed.append(f"DRAWDOWN_{risk_level.name}: {'; '.join(dd_reasons)}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        if risk_level > RiskLevel.GREEN:
            warnings.append(f"DRAWDOWN_{risk_level.name}: Sizing at {action['size_multiplier']:.0%}")

        checks_passed.append(f"drawdown_{risk_level.name.lower()}")

        # ============================================================
        # GATE 6: Position Limits
        # ============================================================
        limits_ok, limits_reason = check_position_limits(
            {
                'symbol': proposal.symbol,
                'side': proposal.side,
                'qty': 0,  # Will be calculated
                'entry_price': proposal.entry_price,
                'stop_loss': proposal.stop_loss,
                'conviction': proposal.conviction,
                'sector': proposal.sector,
            },
            portfolio_state,
        )
        if not limits_ok:
            checks_failed.append(f"POSITION_LIMITS: {limits_reason}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)
        checks_passed.append("position_limits")

        # ============================================================
        # GATE 7: Correlation Check
        # ============================================================
        returns_data = self._get_returns_data()
        correlation_penalty = self.correlation_monitor.get_correlation_penalty(
            proposal.symbol,
            portfolio_state['positions_by_asset'],
            returns_data,
        )

        regime_change, regime_reason = self.correlation_monitor.check_regime_change(returns_data)
        if regime_change:
            checks_failed.append(f"REGIME_CHANGE: {regime_reason}")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        if correlation_penalty > 0.5:
            warnings.append(f"HIGH_CORRELATION: Penalty {correlation_penalty:.2f} for {proposal.symbol}")

        checks_passed.append("correlation_check")

        # ============================================================
        # GATE 8: Position Sizing (final calculation)
        # ============================================================

        # Get sizing components
        win_rate = float(self.redis.get('strategy:win_rate') or 0.5)
        avg_win = float(self.redis.get('strategy:avg_win') or 1.5)
        avg_loss = float(self.redis.get('strategy:avg_loss') or 1.0)
        atr = float(self.redis.get(f'market:{proposal.symbol}:atr') or 0)

        sizing = calculate_position_size(
            portfolio_value=portfolio_state['portfolio_value'],
            entry_price=proposal.entry_price,
            stop_loss_price=proposal.stop_loss,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            atr=atr,
            correlation_penalty=correlation_penalty,
        )

        # Apply all multipliers
        final_mult = (
            action['size_multiplier']      # Drawdown reducer
            * greed_mult                    # Anti-greed
            * weekend_mult                  # Weekend reduction
        )

        # Apply overconfidence cap
        high_conv_count = sum(
            1 for t in todays_trades
            if t.get('conviction', 0) >= 0.8
        )
        _, oc_reason = self.anti_overconfidence.adjust_size_for_conviction(
            sizing['position_value'],
            proposal.conviction,
            high_conv_count,
        )
        if oc_reason:
            warnings.append(f"OVERCONFIDENCE: {oc_reason}")

        # Final position size
        final_qty = int(sizing['position_size_units'] * final_mult)

        if final_qty <= 0:
            checks_failed.append("ZERO_SIZE: All risk multipliers reduce size to zero")
            return self._build_result(False, None, checks_passed, checks_failed, warnings)

        # Verify final position still within limits
        final_value = final_qty * proposal.entry_price
        final_risk_pct = (abs(proposal.entry_price - proposal.stop_loss) * final_qty) / portfolio_state['portfolio_value']

        if final_risk_pct > 0.02:
            # Hard cap: reduce to fit
            final_qty = int((0.02 * portfolio_state['portfolio_value']) / abs(proposal.entry_price - proposal.stop_loss))
            warnings.append(f"HARD_CAP: Reduced qty to {final_qty} to maintain 2% risk limit")

        checks_passed.append("position_sizing")

        # ============================================================
        # GATE 9: Risk-Reward Minimum
        # ============================================================
        if proposal.risk_reward_ratio < 1.5:
            checks_failed.append(
                f"RISK_REWARD: Ratio {proposal.risk_reward_ratio:.2f} below minimum 1.5"
            )
            return self._build_result(False, None, checks_passed, checks_failed, warnings)
        checks_passed.append("risk_reward")

        # ============================================================
        # ALL CHECKS PASSED — APPROVE
        # ============================================================
        return VetoResult(
            approved=True,
            modified_qty=final_qty,
            checks_passed=checks_passed,
            checks_failed=[],
            warnings=warnings,
            final_risk_pct=round(final_risk_pct, 6),
            timestamp=datetime.utcnow().isoformat(),
            decision_id=self._generate_id(),
        )

    def _get_portfolio_state(self) -> dict:
        """Get current portfolio state from Redis."""
        state = self.redis.hgetall('portfolio:state')
        return {
            'portfolio_value': float(state.get('portfolio_value', 100000)),
            'gross_exposure': float(state.get('gross_exposure', 0)),
            'net_exposure': float(state.get('net_exposure', 0)),
            'open_position_count': int(state.get('open_position_count', 0)),
            'positions_by_asset': json.loads(state.get('positions_by_asset', '{}')),
            'positions_by_sector': json.loads(state.get('positions_by_sector', '{}')),
        }

    def _get_trade_history(self) -> list[dict]:
        """Get recent trade history."""
        raw = self.redis.lrange('trades:history', 0, 99)
        return [json.loads(t) for t in raw]

    def _get_todays_trades(self) -> list[dict]:
        """Get today's trades."""
        today = datetime.utcnow().date().isoformat()
        raw = self.redis.lrange(f'trades:{today}', 0, -1)
        return [json.loads(t) for t in raw]

    def _get_returns_data(self) -> dict[str, list[float]]:
        """Get returns data for correlation calculation."""
        symbols = self.redis.smembers('portfolio:active_symbols')
        data = {}
        for sym in symbols:
            raw = self.redis.lrange(f'market:{sym}:returns', 0, 59)
            if raw:
                data[sym] = [float(r) for r in raw]
        return data

    def _generate_id(self) -> str:
        """Generate unique decision ID."""
        import uuid
        return f"VETO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    def _build_result(
        self,
        approved: bool,
        modified_qty: int | None,
        passed: list[str],
        failed: list[str],
        warnings: list[str],
    ) -> VetoResult:
        return VetoResult(
            approved=approved,
            modified_qty=modified_qty,
            checks_passed=passed,
            checks_failed=failed,
            warnings=warnings,
            final_risk_pct=0.0,
            timestamp=datetime.utcnow().isoformat(),
            decision_id=self._generate_id(),
        )
```

### 8.2 Veto Message Format

```python
def format_veto_message(result: VetoResult, proposal: TradeProposal) -> str:
    """
    Format the veto result into a human-readable message.
    Used for logging and operator notifications.
    """
    status = "✅ APPROVED" if result.approved else "❌ REJECTED"

    msg = f"""
═══════════════════════════════════════════
  TRADE DECISION: {status}
  Decision ID: {result.decision_id}
  Timestamp: {result.timestamp}
═══════════════════════════════════════════

  PROPOSAL:
  ─────────
  Symbol:       {proposal.symbol}
  Side:         {proposal.side}
  Entry:        {proposal.entry_price}
  Stop Loss:    {proposal.stop_loss}
  Take Profit:  {proposal.take_profit}
  Conviction:   {proposal.conviction:.0%}
  Setup:        {proposal.setup_type}
  R:R Ratio:    {proposal.risk_reward_ratio:.2f}

  DECISION:
  ─────────
  Approved:     {result.approved}
  Final Qty:    {result.modified_qty or 'N/A'}
  Final Risk:   {result.final_risk_pct:.2%}

  CHECKS PASSED ({len(result.checks_passed)}):
  ─────────
"""
    for check in result.checks_passed:
        msg += f"  ✅ {check}\n"

    if result.checks_failed:
        msg += f"\n  CHECKS FAILED ({len(result.checks_failed)}):\n"
        msg += "  ─────────\n"
        for check in result.checks_failed:
            msg += f"  ❌ {check}\n"

    if result.warnings:
        msg += f"\n  WARNINGS ({len(result.warnings)}):\n"
        msg += "  ─────────\n"
        for warn in result.warnings:
            msg += f"  ⚠️  {warn}\n"

    msg += "═══════════════════════════════════════════\n"
    return msg
```

---

## 9. CHECK CADENCE & EXECUTION ORDER

### 9.1 Check Types and Frequency

```
┌─────────────────────────────────────────────────────────────────┐
│                    CHECK CADENCE                                  │
├─────────────────────┬───────────────┬─────────────────────────────┤
│ Check Type          │ Frequency     │ Trigger                     │
├─────────────────────┼───────────────┼─────────────────────────────┤
│ PRE-TRADE           │ Per trade     │ Before every order          │
│ POST-TRADE          │ Per trade     │ After every fill            │
│ PERIODIC            │ 60 seconds    │ Timer (background thread)   │
│ EMERGENCY           │ 5 seconds     │ Kill switch monitor         │
│ DAILY RESET         │ 00:00 UTC     │ Cron / timer                │
│ WEEKLY RESET        │ Monday 00:00  │ Cron / timer                │
│ MONTHLY RESET       │ 1st 00:00     │ Cron / timer                │
└─────────────────────┴───────────────┴─────────────────────────────┘
```

### 9.2 Pre-Trade Check Sequence

```
PRE-TRADE CHECK ORDER (cheapest first, most critical last):

 1. Kill switch status           → Redis GET (microseconds)
 2. Basic validation             → Pure computation (microseconds)
 3. Anti-FOMO setup check        → Redis lookup + comparison (milliseconds)
 4. Time-based rules             → Redis + datetime checks (milliseconds)
 5. Anti-revenge guard           → Redis list scan (milliseconds)
 6. Anti-greed multiplier        → Redis list scan (milliseconds)
 7. Drawdown circuit breaker     → Redis hash read + comparison (milliseconds)
 8. Position limits              → Redis hash read + arithmetic (milliseconds)
 9. Correlation check            → Returns data + numpy (10-100ms)
10. Position sizing calculation  → Full Kelly + adjustments (milliseconds)
11. Risk-reward validation       → Arithmetic (microseconds)

TOTAL: Should complete in < 100ms. If > 500ms, something is wrong.
```

### 9.3 Post-Trade Check

```python
def post_trade_check(fill: dict, redis_client) -> None:
    """
    Run after every order fill.
    Updates all risk state.
    """
    # 1. Update portfolio state
    update_portfolio_state(fill, redis_client)

    # 2. Update drawdown metrics
    update_drawdown_metrics(redis_client)

    # 3. Update trade history
    record_trade(fill, redis_client)

    # 4. Update correlation data
    update_correlation_returns(fill['symbol'], redis_client)

    # 5. Re-check all circuit breakers
    breaker = DrawdownCircuitBreaker(redis_client)
    level, reasons = breaker.evaluate()
    redis_client.set('risk:current_level', int(level))

    if level >= RiskLevel.RED:
        # This should trigger the kill switch
        kill_switch = KillSwitch(redis_client)
        kill_switch.activate(
            KillSwitchTrigger.DRAWDOWN_RED,
            f"Post-trade check: {reasons}"
        )
```

### 9.4 Periodic Check (Every 60 Seconds)

```python
def periodic_risk_check(redis_client, exchange_client) -> None:
    """
    Runs every 60 seconds in background.
    """
    # 1. Update mark-to-market on all positions
    positions = exchange_client.get_positions()
    update_mark_to_market(positions, redis_client)

    # 2. Recalculate drawdown
    update_drawdown_metrics(redis_client)

    # 3. Update correlation matrix
    returns_data = get_returns_data(redis_client)
    monitor = CorrelationMonitor(redis_client)
    regime_change, reason = monitor.check_regime_change(returns_data)

    if regime_change:
        # Reduce all positions
        reduce_all_positions(0.5, exchange_client, redis_client)
        send_alert('REGIME_CHANGE', reason)

    # 4. Check time-based rules (weekend, events)
    now = datetime.utcnow()
    rules = TimeBasedRiskRules()
    weekend_reduced, mult, msg = rules.check_weekend_rules(now)
    if weekend_reduced and mult < 1.0:
        reduce_all_positions(mult, exchange_client, redis_client)

    # 5. Check for stale positions (positions held too long)
    check_position_staleness(positions, redis_client)

    # 6. Update peak equity
    current_equity = calculate_equity(positions, redis_client)
    peak = float(redis_client.get('risk:peak_equity') or 0)
    if current_equity > peak:
        redis_client.set('risk:peak_equity', current_equity)
```

### 9.5 Daily / Weekly / Monthly Reset

```python
def daily_reset(redis_client) -> None:
    """Run at 00:00 UTC daily."""
    pipe = redis_client.pipeline()

    # Reset daily P&L tracking
    pipe.set('risk:daily_pnl', 0)
    pipe.set('risk:daily_pnl_pct', 0)
    pipe.set('risk:daily_trade_count', 0)
    pipe.set('risk:daily_loss_count', 0)

    # Archive yesterday's data
    yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    daily_summary = {
        'date': yesterday,
        'pnl': redis_client.get('risk:daily_pnl'),
        'trade_count': redis_client.get('risk:daily_trade_count'),
        'max_drawdown': redis_client.get('risk:daily_max_drawdown'),
    }
    pipe.lpush('risk:daily_history', json.dumps(daily_summary))

    # Clear anti-revenge cooldown if it's a new day
    pipe.delete('risk:revenge_cooldown_until')

    pipe.execute()


def weekly_reset(redis_client) -> None:
    """Run at Monday 00:00 UTC."""
    pipe = redis_client.pipeline()
    pipe.set('risk:weekly_pnl', 0)
    pipe.set('risk:weekly_pnl_pct', 0)
    pipe.execute()


def monthly_reset(redis_client) -> None:
    """Run at 1st of month 00:00 UTC."""
    pipe = redis_client.pipeline()
    pipe.set('risk:monthly_pnl', 0)
    pipe.set('risk:monthly_pnl_pct', 0)
    pipe.execute()
```

---

## 10. REDIS STATE SCHEMA

```
┌─────────────────────────────────────────────────────────────────┐
│                    REDIS KEYS (Risk Governor)                    │
├─────────────────────────────────────┬───────────┬───────────────┤
│ Key                                 │ Type      │ Description   │
├─────────────────────────────────────┼───────────┼───────────────┤
│                                     │           │               │
│ === KILL SWITCH ===                 │           │               │
│ risk:kill_switch                    │ STRING    │ 'ACTIVE'/None │
│ risk:kill_switch_reason             │ STRING    │ Why it fired  │
│ risk:kill_switch_timestamp          │ STRING    │ ISO timestamp │
│ risk:kill_switch_log                │ LIST      │ Full history  │
│                                     │           │               │
│ === DRAWDOWN ===                    │           │               │
│ risk:drawdown_state                 │ HASH      │ All DD metrics│
│   ├── daily_pnl_pct                │ FLOAT     │               │
│   ├── weekly_pnl_pct               │ FLOAT     │               │
│   ├── monthly_pnl_pct              │ FLOAT     │               │
│   ├── peak_equity                   │ FLOAT     │               │
│   ├── current_equity                │ FLOAT     │               │
│   ├── total_drawdown_pct           │ FLOAT     │               │
│   └── risk_level                    │ INT       │ 0-3           │
│ risk:current_level                  │ STRING    │ '0'-'3'       │
│ risk:halt_timestamp                 │ STRING    │ When halt occ │
│ risk:resume_timestamp               │ STRING    │ When resumed  │
│ risk:resume_operator                │ STRING    │ Who approved  │
│ risk:daily_pnl                      │ STRING    │ Today's P&L   │
│ risk:daily_pnl_pct                  │ STRING    │ Today's P&L % │
│ risk:weekly_pnl                     │ STRING    │ This week     │
│ risk:monthly_pnl                    │ STRING    │ This month    │
│ risk:peak_equity                    │ STRING    │ All-time peak │
│ risk:daily_max_drawdown             │ STRING    │ Today's max DD│
│ risk:daily_history                  │ LIST      │ Historical dly│
│                                     │           │               │
│ === PORTFOLIO ===                   │           │               │
│ portfolio:state                     │ HASH      │ Portfolio data│
│   ├── portfolio_value              │ FLOAT     │               │
│   ├── gross_exposure               │ FLOAT     │               │
│   ├── net_exposure                  │ FLOAT     │               │
│   ├── open_position_count          │ INT       │               │
│   ├── positions_by_asset           │ JSON      │ {sym: value}  │
│   └── positions_by_sector          │ JSON      │ {sec: value}  │
│ portfolio:active_symbols            │ SET       │ Active syms   │
│                                     │           │               │
│ === TRADES ===                      │           │               │
│ trades:history                      │ LIST      │ Last 100      │
│ trades:YYYY-MM-DD                   │ LIST      │ Today's trades│
│ trades:consecutive_losses           │ STRING    │ Count         │
│ trades:consecutive_wins             │ STRING    │ Count         │
│                                     │           │               │
│ === MARKET DATA ===                 │           │               │
│ market:{sym}:price                  │ STRING    │ Last price    │
│ market:{sym}:atr                    │ STRING    │ ATR value     │
│ market:{sym}:returns                │ LIST      │ Last 60 rets  │
│ market:{sym}:funding_rate           │ STRING    │ Current fund  │
│ risk:last_price_update              │ STRING    │ Unix timestamp│
│ risk:last_exchange_ping             │ STRING    │ Unix timestamp│
│                                     │           │               │
│ === STRATEGY ===                    │           │               │
│ strategy:win_rate                   │ STRING    │ Rolling WR    │
│ strategy:avg_win                    │ STRING    │ Rolling avg   │
│ strategy:avg_loss                   │ STRING    │ Rolling avg   │
│                                     │           │               │
│ === CORRELATION ===                 │           │               │
│ risk:correlation_matrix             │ STRING    │ Serialized    │
│ risk:historical_avg_correlation     │ STRING    │ Baseline avg  │
│ risk:regime_change_active           │ STRING    │ 'true'/None   │
│                                     │           │               │
│ === EVENTS ===                      │           │               │
│ risk:economic_calendar              │ STRING    │ JSON, cached  │
│                                     │           │               │
│ === ANTI-BEHAVIORAL ===             │           │               │
│ risk:revenge_cooldown_until         │ STRING    │ ISO timestamp │
│ risk:manual_resume_approved         │ STRING    │ 'true'/None   │
│                                     │           │               │
│ === MONITOR ===                     │           │               │
│ risk:monitor_errors                 │ LIST      │ Monitor errors│
└─────────────────────────────────────┴───────────┴───────────────┘
```

---

## 11. PYTHON IMPLEMENTATION

### 11.1 Module Structure

```
trading-super-agent/
├── risk_governor/
│   ├── __init__.py
│   ├── config.py                    # All thresholds and limits
│   ├── governor.py                  # Main RiskGovernor class
│   ├── position_sizing.py           # Kelly + sizing engine
│   ├── drawdown.py                  # Circuit breakers
│   ├── anti_behavioral.py           # Revenge, greed, FOMO guards
│   ├── correlation.py               # Correlation monitor
│   ├── time_rules.py                # Time-based rules
│   ├── kill_switch.py               # Kill switch system
│   ├── veto_protocol.py             # Final gate
│   ├── state.py                     # Redis state management
│   ├── periodic.py                  # Periodic checks
│   ├── notifications.py             # Alert system
│   └── logging_config.py            # Structured logging
├── tests/
│   ├── test_position_sizing.py
│   ├── test_drawdown.py
│   ├── test_anti_behavioral.py
│   ├── test_correlation.py
│   ├── test_time_rules.py
│   ├── test_kill_switch.py
│   ├── test_veto_protocol.py
│   └── test_integration.py
└── monitor/
    ├── __init__.py
    ├── kill_monitor.py              # Separate process for kill detection
    └── health_check.py              # System health monitoring
```

### 11.2 Configuration File

```python
# risk_governor/config.py

from dataclasses import dataclass, field

@dataclass(frozen=True)
class RiskConfig:
    """
    Immutable risk configuration.
    Loaded once at startup. Changes require restart.
    """

    # === POSITION SIZING ===
    max_risk_per_trade_pct: float = 0.02         # 2%
    max_position_value_pct: float = 0.10         # 10%
    max_gross_exposure_pct: float = 1.50         # 150%
    max_net_exposure_pct: float = 1.00           # 100%
    max_open_positions: int = 20
    max_sector_exposure_pct: float = 0.25        # 25%
    min_conviction: float = 0.60                 # 60%
    min_risk_reward_ratio: float = 1.5           # 1.5:1

    # === DRAWDOWN ===
    daily_loss_warn: float = -0.015              # -1.5%
    daily_loss_halt: float = -0.025              # -2.5%
    daily_loss_kill: float = -0.04               # -4.0%
    weekly_loss_warn: float = -0.03              # -3.0%
    weekly_loss_halt: float = -0.05              # -5.0%
    weekly_loss_kill: float = -0.08              # -8.0%
    monthly_loss_warn: float = -0.06             # -6.0%
    monthly_loss_halt: float = -0.10             # -10.0%
    monthly_loss_kill: float = -0.15             # -15.0%
    total_drawdown_warn: float = -0.10           # -10%
    total_drawdown_halt: float = -0.15           # -15%
    total_drawdown_kill: float = -0.20           # -20%

    # === ANTI-BEHAVIORAL ===
    consecutive_losses_cooldown: int = 3         # 3 losses
    consecutive_losses_cooldown_minutes: int = 60
    extended_losses_threshold: int = 5
    extended_cooldown_minutes: int = 240
    max_daily_losses: int = 6
    win_streak_threshold: int = 5
    win_streak_reduction: float = 0.7
    extended_win_streak: int = 8
    extended_win_reduction: float = 0.5
    max_conviction_multiplier: float = 1.5
    max_high_conviction_positions: int = 3

    # === CORRELATION ===
    high_correlation_threshold: float = 0.7
    regime_change_threshold: float = 0.85
    max_correlated_exposure_pct: float = 0.30
    correlation_window: int = 60

    # === TIME RULES ===
    weekend_close_hour_utc: int = 20
    weekend_reduce_hour_utc: int = 16
    weekend_reduction_factor: float = 0.5
    funding_rate_threshold: float = 0.01
    funding_rate_reduce_at: float = 0.005

    # === KILL SWITCH ===
    rapid_move_threshold_pct: float = 0.05       # 5%
    max_consecutive_errors: int = 3
    data_feed_timeout_seconds: int = 30

    # === PERFORMANCE ===
    max_decision_latency_ms: int = 500
    periodic_check_interval_seconds: int = 60
    kill_monitor_interval_seconds: int = 5
```

### 11.3 Main Governor Class

```python
# risk_governor/governor.py

import json
import logging
import uuid
from datetime import datetime
from dataclasses import dataclass

import redis

from .config import RiskConfig
from .veto_protocol import VetoProtocol, TradeProposal, VetoResult
from .kill_switch import KillSwitch, AutoKillDetector
from .state import RiskStateManager
from .periodic import PeriodicRiskChecker

logger = logging.getLogger('risk_governor')


class RiskGovernor:
    """
    THE Risk Governor. Deterministic. No LLM.

    This is the single point of control for all risk decisions.
    Every trade must pass through here.
    """

    def __init__(self, redis_url: str, config: RiskConfig = None, exchange_client=None, notifier=None):
        self.config = config or RiskConfig()
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.state_manager = RiskStateManager(self.redis)
        self.veto = VetoProtocol(self.redis, self.config)
        self.kill_switch = KillSwitch(self.redis, exchange_client, notifier)
        self.periodic = PeriodicRiskChecker(self.redis, exchange_client, self.config)
        self.notifier = notifier

        # Performance tracking
        self._decision_count = 0
        self._rejection_count = 0

        logger.info("Risk Governor initialized with config: %s", self.config)

    def evaluate_trade(self, proposal: TradeProposal) -> VetoResult:
        """
        PRIMARY ENTRY POINT: Evaluate a trade proposal.

        This is deterministic. No LLM calls. No external API calls (except Redis).
        """
        start_time = datetime.utcnow()

        # Run the veto protocol
        result = self.veto.evaluate(proposal)

        # Track metrics
        self._decision_count += 1
        if not result.approved:
            self._rejection_count += 1

        # Log the decision
        self._log_decision(proposal, result)

        # Check latency
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        if latency_ms > self.config.max_decision_latency_ms:
            logger.warning(
                "Risk decision took %.0fms (limit: %dms)",
                latency_ms, self.config.max_decision_latency_ms
            )

        # Notify if rejected
        if not result.approved and self.notifier:
            self.notifier.send_warning(
                f"Trade REJECTED: {proposal.symbol} {proposal.side}\n"
                f"Reasons: {'; '.join(result.checks_failed)}"
            )

        return result

    def force_kill(self, reason: str) -> dict:
        """Manual kill switch activation."""
        return self.kill_switch.activate(
            KillSwitchTrigger.MANUAL,
            f"Manual kill by operator: {reason}"
        )

    def resume_trading(self, operator_id: str, reason: str) -> bool:
        """Resume trading after kill switch."""
        return self.kill_switch.deactivate(operator_id, reason)

    def get_status(self) -> dict:
        """Get current risk status."""
        return {
            'kill_switch': self.kill_switch.is_active(),
            'risk_level': int(self.redis.get('risk:current_level') or 0),
            'portfolio_value': float(self.redis.get('portfolio:state:portfolio_value') or 0),
            'daily_pnl_pct': float(self.redis.get('risk:daily_pnl_pct') or 0),
            'weekly_pnl_pct': float(self.redis.get('risk:weekly_pnl_pct') or 0),
            'total_drawdown_pct': float(self.redis.get('risk:drawdown_state:total_drawdown_pct') or 0),
            'open_positions': int(self.redis.get('portfolio:state:open_position_count') or 0),
            'decisions_today': self._decision_count,
            'rejections_today': self._rejection_count,
            'rejection_rate': self._rejection_count / max(self._decision_count, 1),
        }

    def _log_decision(self, proposal: TradeProposal, result: VetoResult):
        """Log every decision for audit trail."""
        log_entry = {
            'timestamp': result.timestamp,
            'decision_id': result.decision_id,
            'symbol': proposal.symbol,
            'side': proposal.side,
            'entry': proposal.entry_price,
            'stop': proposal.stop_loss,
            'conviction': proposal.conviction,
            'setup': proposal.setup_type,
            'approved': result.approved,
            'final_qty': result.modified_qty,
            'final_risk_pct': result.final_risk_pct,
            'checks_passed': result.checks_passed,
            'checks_failed': result.checks_failed,
            'warnings': result.warnings,
        }

        self.redis.lpush('risk:decision_log', json.dumps(log_entry))
        self.redis.ltrim('risk:decision_log', 0, 9999)  # Keep last 10k

        if result.approved:
            logger.info(
                "APPROVED: %s %s qty=%s risk=%.2f%% id=%s",
                proposal.side, proposal.symbol,
                result.modified_qty, result.final_risk_pct * 100,
                result.decision_id,
            )
        else:
            logger.info(
                "REJECTED: %s %s reasons=%s id=%s",
                proposal.side, proposal.symbol,
                result.checks_failed, result.decision_id,
            )
```

---

## SUMMARY: THRESHOLD TABLE

| Category | Parameter | Value | Action |
|----------|-----------|-------|--------|
| **Sizing** | Max risk/trade | 2% | Hard cap |
| **Sizing** | Max position value | 10% | Single asset limit |
| **Sizing** | Max gross exposure | 150% | Total exposure |
| **Sizing** | Max net exposure | 100% | Directional limit |
| **Sizing** | Max positions | 20 | Count limit |
| **Sizing** | Min conviction | 60% | Below = no trade |
| **Sizing** | Min R:R ratio | 1.5:1 | Below = no trade |
| **Drawdown** | Daily warn | -1.5% | Reduce sizing 50% |
| **Drawdown** | Daily halt | -2.5% | No new trades |
| **Drawdown** | Daily kill | -4.0% | Flatten all |
| **Drawdown** | Weekly warn | -3.0% | Reduce sizing 50% |
| **Drawdown** | Weekly halt | -5.0% | No new trades |
| **Drawdown** | Weekly kill | -8.0% | Flatten all |
| **Drawdown** | Monthly warn | -6.0% | Reduce sizing 50% |
| **Drawdown** | Monthly halt | -10.0% | No new trades |
| **Drawdown** | Monthly kill | -15.0% | Flatten all |
| **Drawdown** | Total DD warn | -10% | Reduce sizing 50% |
| **Drawdown** | Total DD halt | -15% | No new trades |
| **Drawdown** | Total DD kill | -20% | Flatten all |
| **Anti-Revenge** | Consecutive losses | 3 | 60-min cooldown |
| **Anti-Revenge** | Extended losses | 5 | 4-hour cooldown |
| **Anti-Revenge** | Daily losses | 6 | 8-hour halt |
| **Anti-Greed** | Win streak | 5 | 70% sizing |
| **Anti-Greed** | Extended streak | 8 | 50% sizing |
| **Anti-FOMO** | Unregistered setup | — | Reject |
| **Anti-FOMO** | Missing signals | — | Reject |
| **Correlation** | High threshold | 0.7 | Warn + reduce |
| **Correlation** | Regime change | 0.85 | Halt + reduce all |
| **Correlation** | Max correlated | 30% | Reject new |
| **Time** | Weekend reduce | Fri 16:00 UTC | 50% sizing |
| **Time** | Weekend close | Fri 20:00 UTC | Flatten |
| **Time** | Event blackout | 30-60 min | No trading |
| **Time** | Funding rate | >0.5% | Reduce 25-50% |
| **Kill** | Rapid move | 5% in 5 min | Auto-kill |
| **Kill** | Data feed loss | 30 sec | Auto-kill |
| **Kill** | Exchange down | 30 sec | Auto-kill |
| **Kill** | Exchange errors | 3 consecutive | Auto-kill |

---

## KEY DESIGN DECISIONS

1. **Half-Kelly, not Full-Kelly**: Full Kelly has ~50% drawdown probability. Half-Kelly sacrifices 25% growth for dramatically lower drawdown risk.

2. **Progressive circuit breakers**: Not binary halt/no-halt. Four levels (Green/Yellow/Orange/Red) with proportional responses.

3. **Anti-behavioral guards are psychology, not math**: These protect against the human tendency to revenge-trade, over-leverage after wins, and FOMO into positions. Even with an automated system, these patterns can emerge from strategy design.

4. **Correlation monitoring prevents "diversification illusion"**: Holding 20 crypto positions isn't diversification — it's one bet with extra steps. The correlation monitor catches this.

5. **Kill switch is a separate process**: The main trading loop could have bugs, memory leaks, or corrupted state. The kill switch runs independently and checks Redis directly.

6. **Every decision is logged**: Full audit trail. Every approved trade, every rejection, every warning. This is non-negotiable for debugging and accountability.

7. **Configuration is immutable at runtime**: Risk parameters are set at startup. Changing them requires a deliberate restart with new config. No "just tweak this one number" during live trading.

8. **The veto protocol is the single point of control**: No code path can bypass it. The exchange execution layer only receives orders that have been approved by the veto protocol.
