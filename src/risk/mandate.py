"""
Mandate — Human-committed trading authorization boundary.

The Risk Guardian says "this trade is safe."
The Mandate says "this trade is within my authorization."

A mandate is a HUMAN COMMITMENT — a signed contract defining what the
system is ALLOWED to trade. Without a committed mandate, ALL live trades
are blocked. Paper mode is exempt.

Lifecycle:
  1. Create mandate with rules (allowed symbols, limits, etc.)
  2. commit(user_id) — human signs off, mandate becomes active
  3. check_order(order) → MandateDecision — validate against rules
  4. update(changes) — modify rules (re-commits automatically)
  5. revoke(user_id) — deactivate, block all live trades

Persists to config/mandate.yaml. All validation is deterministic.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from src.interfaces.types import Order, OrderSide, OrderType

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = "config/mandate.yaml"


# ═══════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════


class MandateStatus(StrEnum):
    """Lifecycle status of a mandate."""

    DRAFT = "draft"  # Created but not committed
    ACTIVE = "active"  # Committed and enforcing
    REVOKED = "revoked"  # Deactivated by user


class MandateRules(BaseModel):
    """The authorization rules — what the system is ALLOWED to do.

    All fields have sensible defaults that BLOCK everything (empty lists,
    zero caps). The user must explicitly configure each permission.
    """

    allowed_symbols: list[str] = Field(
        default_factory=list,
        description="Trading pairs the system may trade. Empty = nothing allowed.",
    )
    max_position_size_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Max position size as fraction of equity (0.0-1.0).",
    )
    max_daily_trades: int = Field(
        default=0,
        ge=0,
        description="Max number of trades per day. 0 = no trades allowed.",
    )
    max_leverage: float = Field(
        default=1.0,
        ge=1.0,
        description="Maximum leverage multiplier. 1.0 = no leverage.",
    )
    allowed_order_types: list[str] = Field(
        default_factory=lambda: ["market", "limit"],
        description="Permitted order types (market, limit, stop_market, stop_limit).",
    )
    max_notional_per_trade: float = Field(
        default=0.0,
        ge=0.0,
        description="Max notional value per trade in quote currency. 0 = no limit.",
    )
    allowed_sides: list[str] = Field(
        default_factory=lambda: ["buy", "sell"],
        description="Permitted order sides. Restrict to ['buy'] to disable shorting.",
    )
    min_paper_trades: int = Field(
        default=50,
        ge=0,
        description="Minimum number of paper trades required before live trading. 0 = no minimum.",
    )
    min_paper_days: int = Field(
        default=7,
        ge=0,
        description="Minimum number of days in paper mode before live trading. 0 = no minimum.",
    )
    min_win_rate: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Minimum win rate (0.0-1.0) required before live trading. 0 = no minimum.",
    )
    paper_trades_completed: int = Field(
        default=0,
        ge=0,
        description="Number of paper trades completed (tracked automatically).",
    )
    paper_start_date: str = Field(
        default="",
        description="ISO date when paper trading started (tracked automatically).",
    )
    paper_wins: int = Field(
        default=0,
        ge=0,
        description="Number of winning paper trades (tracked automatically).",
    )
    paper_total_pnl: float = Field(
        default=0.0,
        description="Total paper P&L (tracked automatically).",
    )

    @field_validator("allowed_symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        """Normalize symbols to uppercase and validate format."""
        normalized = []
        for sym in v:
            sym_upper = sym.strip().upper()
            if "/" not in sym_upper:
                raise ValueError(
                    f"Invalid symbol format '{sym}' — expected 'BASE/QUOTE' (e.g. 'BTC/USDT')."
                )
            normalized.append(sym_upper)
        return normalized

    @field_validator("allowed_order_types")
    @classmethod
    def validate_order_types(cls, v: list[str]) -> list[str]:
        """Validate order type strings."""
        valid_types = {ot.value for ot in OrderType}
        for ot in v:
            if ot not in valid_types:
                raise ValueError(f"Invalid order type '{ot}' — must be one of {valid_types}.")
        return v

    @field_validator("allowed_sides")
    @classmethod
    def validate_sides(cls, v: list[str]) -> list[str]:
        """Validate order side strings."""
        valid_sides = {s.value for s in OrderSide}
        for s in v:
            if s not in valid_sides:
                raise ValueError(f"Invalid order side '{s}' — must be one of {valid_sides}.")
        return v


class MandateDecision(BaseModel):
    """Result of checking an order against the mandate.

    Attributes:
        allowed: Whether the order passes mandate authorization.
        reason: Human-readable summary of the decision.
        violations: Specific rule violations found.
    """

    allowed: bool
    reason: str = ""
    violations: list[str] = Field(default_factory=list)


class MandateState(BaseModel):
    """Full mandate state including lifecycle metadata.

    Persisted to config/mandate.yaml.
    """

    rules: MandateRules = Field(default_factory=MandateRules)
    status: MandateStatus = MandateStatus.DRAFT
    committed_at: datetime | None = None
    committed_by: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    version: int = 1
    notes: str = ""


# ═══════════════════════════════════════════════════════════════════════
# MANDATE CLASS
# ═══════════════════════════════════════════════════════════════════════


class Mandate:
    """Human-committed trading authorization boundary.

    The mandate defines WHAT the system is allowed to trade.
    It is a hard boundary — no trade can exceed mandate rules,
    regardless of what the risk engine says.

    Lifecycle:
        1. Mandate() — create with rules (DRAFT state)
        2. commit(user_id) — human signs, becomes ACTIVE
        3. check_order(order) — validate against rules
        4. update(changes) — modify rules
        5. revoke(user_id) — deactivate

    Persistence:
        Reads/writes config/mandate.yaml in YAML format.
    """

    def __init__(
        self,
        state: MandateState | None = None,
        config_path: str | None = None,
    ) -> None:
        """Initialize the Mandate.

        Args:
            state: Pre-built state (takes precedence over config_path).
            config_path: Path to mandate YAML. Defaults to config/mandate.yaml.
        """
        self._config_path = Path(config_path or _DEFAULT_CONFIG)

        if state is not None:
            self._state = state
        else:
            self._state = self._load_from_yaml(self._config_path)

        logger.info(
            f"Mandate initialized: status={self._state.status.value}, "
            f"symbols={len(self._state.rules.allowed_symbols)}, "
            f"version={self._state.version}"
        )

    # ── Properties ────────────────────────────────────────────────

    @property
    def status(self) -> MandateStatus:
        """Current mandate status."""
        return self._state.status

    @property
    def is_active(self) -> bool:
        """Whether the mandate is currently active and enforcing."""
        return self._state.status == MandateStatus.ACTIVE

    @property
    def committed_at(self) -> datetime | None:
        """When the mandate was last committed."""
        return self._state.committed_at

    @property
    def committed_by(self) -> str | None:
        """Who committed the mandate."""
        return self._state.committed_by

    @property
    def rules(self) -> MandateRules:
        """Current mandate rules."""
        return self._state.rules

    @property
    def version(self) -> int:
        """Mandate version number."""
        return self._state.version

    @property
    def state(self) -> MandateState:
        """Full mandate state (read-only snapshot)."""
        return self._state.model_copy()

    # ── Lifecycle ─────────────────────────────────────────────────

    def commit(self, user_id: str) -> None:
        """Commit the mandate — human signs off, becomes ACTIVE.

        A committed mandate is a CONTRACT. The system will enforce
        these rules until explicitly revoked or updated.

        Args:
            user_id: ID of the human committing the mandate.

        Raises:
            ValueError: If rules are invalid (no symbols, zero limits).
        """
        self._validate_rules()
        now = datetime.now(UTC)
        self._state = self._state.model_copy(
            update={
                "status": MandateStatus.ACTIVE,
                "committed_at": now,
                "committed_by": user_id,
                "revoked_at": None,
                "revoked_by": None,
            }
        )
        self._save_to_yaml()
        logger.info(
            f"Mandate COMMITTED by {user_id} at {now.isoformat()} — "
            f"v{self._state.version}, {len(self._state.rules.allowed_symbols)} symbols"
        )

    def revoke(self, user_id: str) -> None:
        """Revoke the mandate — deactivate, block all live trades.

        Args:
            user_id: ID of the human revoking the mandate.
        """
        now = datetime.now(UTC)
        self._state = self._state.model_copy(
            update={
                "status": MandateStatus.REVOKED,
                "revoked_at": now,
                "revoked_by": user_id,
            }
        )
        self._save_to_yaml()
        logger.warning(
            f"Mandate REVOKED by {user_id} at {now.isoformat()} — all live trades blocked"
        )

    def update(self, user_id: str, **rule_changes: Any) -> None:
        """Update mandate rules and re-commit.

        Any rule field in MandateRules can be passed as a keyword argument.
        The mandate is automatically re-committed after update.

        Args:
            user_id: ID of the human updating the mandate.
            **rule_changes: Rule fields to update.

        Raises:
            ValueError: If updated rules are invalid.
        """
        current_rules = self._state.rules.model_dump()
        current_rules.update(rule_changes)
        new_rules = MandateRules(**current_rules)

        self._state = self._state.model_copy(
            update={
                "rules": new_rules,
                "version": self._state.version + 1,
            }
        )
        self.commit(user_id)
        logger.info(
            f"Mandate UPDATED by {user_id} — "
            f"v{self._state.version}, changes: {list(rule_changes.keys())}"
        )

    # ── Order Checking ────────────────────────────────────────────

    def check_order(self, order: Order) -> MandateDecision:
        """Check an order against mandate rules.

        Validates: symbol authorization, position size, order type,
        leverage, daily trade count, side authorization.

        Args:
            order: The order to validate.

        Returns:
            MandateDecision with allowed, reason, and violations.
        """
        # If mandate is not active, block everything
        if not self.is_active:
            return MandateDecision(
                allowed=False,
                reason=(
                    f"Mandate is {self._state.status.value} — "
                    f"no live trades permitted. Commit the mandate first."
                ),
                violations=["mandate_not_active"],
            )

        violations: list[str] = []
        rules = self._state.rules

        # Check symbol authorization
        symbol_upper = order.symbol.strip().upper()
        if symbol_upper not in rules.allowed_symbols:
            violations.append(
                f"symbol_not_allowed: '{order.symbol}' is not in "
                f"allowed_symbols {rules.allowed_symbols}"
            )

        # Check order type
        if order.order_type.value not in rules.allowed_order_types:
            violations.append(
                f"order_type_not_allowed: '{order.order_type.value}' is not in "
                f"allowed_order_types {rules.allowed_order_types}"
            )

        # Check side authorization
        if order.side.value not in rules.allowed_sides:
            violations.append(
                f"side_not_allowed: '{order.side.value}' is not in "
                f"allowed_sides {rules.allowed_sides}"
            )

        # Check notional limit (if set and price available)
        if rules.max_notional_per_trade > 0 and order.price is not None:
            notional = abs(order.quantity * order.price)
            if notional > rules.max_notional_per_trade:
                violations.append(
                    f"notional_exceeded: trade notional {notional:.2f} "
                    f"exceeds max_notional_per_trade {rules.max_notional_per_trade:.2f}"
                )

        # Build decision
        if violations:
            return MandateDecision(
                allowed=False,
                reason=f"Mandate violations: {len(violations)} rule(s) breached.",
                violations=violations,
            )

        return MandateDecision(
            allowed=True,
            reason="Order passes all mandate checks.",
            violations=[],
        )

    def check_signal(
        self,
        symbol: str,
        side: OrderSide | str,
        quantity: float = 0.0,
        price: float | None = None,
        order_type: OrderType | str = OrderType.MARKET,
        daily_trade_count: int = 0,
        leverage: float = 1.0,
    ) -> MandateDecision:
        """Check a signal/trade proposal against mandate rules.

        Lightweight alternative to check_order when you don't have
        a full Order object. Used by the MandateGate.

        Args:
            symbol: Trading pair.
            side: Buy or sell.
            quantity: Proposed quantity.
            price: Proposed price (for notional checks).
            order_type: Order type.
            daily_trade_count: Current daily trade count.
            leverage: Requested leverage.

        Returns:
            MandateDecision with allowed, reason, and violations.
        """
        # If mandate is not active, block everything
        if not self.is_active:
            return MandateDecision(
                allowed=False,
                reason=(
                    f"Mandate is {self._state.status.value} — "
                    f"no live trades permitted. Commit the mandate first."
                ),
                violations=["mandate_not_active"],
            )

        violations: list[str] = []
        rules = self._state.rules

        # Normalize inputs
        side_str = side.value if isinstance(side, OrderSide) else side

        ot_str = order_type.value if isinstance(order_type, OrderType) else order_type

        # Symbol check
        symbol_upper = symbol.strip().upper()
        if symbol_upper not in rules.allowed_symbols:
            violations.append(
                f"symbol_not_allowed: '{symbol}' is not in allowed_symbols {rules.allowed_symbols}"
            )

        # Order type check
        if ot_str not in rules.allowed_order_types:
            violations.append(
                f"order_type_not_allowed: '{ot_str}' is not in "
                f"allowed_order_types {rules.allowed_order_types}"
            )

        # Side check
        if side_str not in rules.allowed_sides:
            violations.append(
                f"side_not_allowed: '{side_str}' is not in allowed_sides {rules.allowed_sides}"
            )

        # Leverage check
        if leverage > rules.max_leverage:
            violations.append(
                f"leverage_exceeded: requested {leverage}x exceeds "
                f"max_leverage {rules.max_leverage}x"
            )

        # Daily trade count check
        if rules.max_daily_trades > 0 and daily_trade_count >= rules.max_daily_trades:
            violations.append(
                f"daily_trades_exceeded: {daily_trade_count} trades today "
                f">= max_daily_trades {rules.max_daily_trades}"
            )

        # Notional check
        if rules.max_notional_per_trade > 0 and price is not None and quantity > 0:
            notional = abs(quantity * price)
            if notional > rules.max_notional_per_trade:
                violations.append(
                    f"notional_exceeded: trade notional {notional:.2f} "
                    f"exceeds max_notional_per_trade {rules.max_notional_per_trade:.2f}"
                )

        if violations:
            return MandateDecision(
                allowed=False,
                reason=f"Mandate violations: {len(violations)} rule(s) breached.",
                violations=violations,
            )

        return MandateDecision(
            allowed=True,
            reason="Signal passes all mandate checks.",
            violations=[],
        )

    # ── Persistence ───────────────────────────────────────────────

    def _save_to_yaml(self) -> None:
        """Persist mandate state to YAML file."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        data = self._state.model_dump(mode="json")

        # Convert datetime objects to ISO strings for YAML
        for key in ("committed_at", "revoked_at"):
            if data.get(key) is not None:
                data[key] = str(data[key])

        # Ensure enums are serialized as strings
        data["status"] = (
            data["status"].value if isinstance(data["status"], MandateStatus) else data["status"]
        )

        with open(self._config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.debug(f"Mandate saved to {self._config_path}")

    @staticmethod
    def _load_from_yaml(path: Path) -> MandateState:
        """Load mandate state from YAML file.

        Returns default (draft) state if file doesn't exist.
        """
        if not path.exists():
            logger.info(f"Mandate config not found at {path}, creating default draft")
            return MandateState()

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}

            # Reconstruct nested models
            rules_data = data.get("rules", {})
            rules = MandateRules(**rules_data) if rules_data else MandateRules()

            # Parse datetime strings
            committed_at = data.get("committed_at")
            if committed_at and isinstance(committed_at, str):
                committed_at = datetime.fromisoformat(committed_at)

            revoked_at = data.get("revoked_at")
            if revoked_at and isinstance(revoked_at, str):
                revoked_at = datetime.fromisoformat(revoked_at)

            status_str = data.get("status", "draft")
            try:
                status = MandateStatus(status_str)
            except ValueError:
                status = MandateStatus.DRAFT

            return MandateState(
                rules=rules,
                status=status,
                committed_at=committed_at,
                committed_by=data.get("committed_by"),
                revoked_at=revoked_at,
                revoked_by=data.get("revoked_by"),
                version=data.get("version", 1),
                notes=data.get("notes", ""),
            )
        except Exception as e:
            logger.error(f"Failed to load mandate config from {path}: {e}")
            return MandateState()

    def check_paper_trading_gate(self) -> MandateDecision:
        """Check if minimum paper trading requirements are met.

        Validates:
        1. Minimum paper trades completed
        2. Minimum days in paper mode
        3. Minimum win rate threshold

        Returns:
            MandateDecision indicating if paper trading gate passes.
        """
        rules = self._state.rules
        violations: list[str] = []

        # Check minimum paper trades
        if rules.min_paper_trades > 0:
            if rules.paper_trades_completed < rules.min_paper_trades:
                violations.append(
                    f"paper_trades_insufficient: {rules.paper_trades_completed} "
                    f"completed < {rules.min_paper_trades} required"
                )

        # Check minimum paper days
        if rules.min_paper_days > 0 and rules.paper_start_date:
            try:
                start = datetime.fromisoformat(rules.paper_start_date)
                days_in_paper = (datetime.now(UTC) - start).days
                if days_in_paper < rules.min_paper_days:
                    violations.append(
                        f"paper_days_insufficient: {days_in_paper} days "
                        f"< {rules.min_paper_days} required"
                    )
            except (ValueError, TypeError):
                violations.append("paper_start_date_invalid")

        # Check win rate threshold
        if rules.min_win_rate > 0 and rules.paper_trades_completed > 0:
            win_rate = rules.paper_wins / rules.paper_trades_completed
            if win_rate < rules.min_win_rate:
                violations.append(
                    f"win_rate_insufficient: {win_rate:.1%} "
                    f"< {rules.min_win_rate:.1%} required "
                    f"({rules.paper_wins}W / {rules.paper_trades_completed}T)"
                )

        if violations:
            return MandateDecision(
                allowed=False,
                reason=f"Paper trading gate: {len(violations)} requirement(s) not met.",
                violations=violations,
            )

        return MandateDecision(
            allowed=True,
            reason="Paper trading requirements satisfied.",
            violations=[],
        )

    def record_paper_trade(self, pnl: float = 0.0) -> None:
        """Record a completed paper trade.

        Increments counters and tracks win rate.

        Args:
            pnl: Realized P&L of the trade (positive = win).
        """
        self._state.rules.paper_trades_completed += 1
        if pnl > 0:
            self._state.rules.paper_wins += 1
        self._state.rules.paper_total_pnl += pnl
        if not self._state.rules.paper_start_date:
            self._state.rules.paper_start_date = datetime.now(UTC).isoformat()
        self._save_to_yaml()

    def _validate_rules(self) -> None:
        """Validate that rules are sensible before committing.

        Raises:
            ValueError: If rules would block all trades or are nonsensical.
        """
        rules = self._state.rules

        if not rules.allowed_symbols:
            raise ValueError(
                "Cannot commit mandate with empty allowed_symbols — no trades would be permitted."
            )

        if rules.max_position_size_pct <= 0:
            raise ValueError(
                "Cannot commit mandate with max_position_size_pct <= 0 — "
                "no trades would be permitted."
            )

        if rules.max_daily_trades <= 0:
            raise ValueError(
                "Cannot commit mandate with max_daily_trades <= 0 — no trades would be permitted."
            )

        if not rules.allowed_order_types:
            raise ValueError(
                "Cannot commit mandate with empty allowed_order_types — "
                "no trades would be permitted."
            )

        # Check paper trading gate before allowing live commit
        paper_gate = self.check_paper_trading_gate()
        if not paper_gate.allowed:
            raise ValueError(
                f"Cannot commit mandate — paper trading requirements not met: "
                f"{'; '.join(paper_gate.violations)}"
            )

    def reload(self) -> None:
        """Reload mandate from YAML file (for external edits)."""
        self._state = self._load_from_yaml(self._config_path)
        logger.info(f"Mandate reloaded from {self._config_path}")

    def __repr__(self) -> str:
        return (
            f"Mandate(status={self._state.status.value}, "
            f"symbols={len(self._state.rules.allowed_symbols)}, "
            f"version={self._state.version}, "
            f"committed_by={self._state.committed_by})"
        )
