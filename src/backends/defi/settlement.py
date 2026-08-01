"""
TSAR DeFi Backend — Smart Contract Settlement Engine.

On-chain atomic settlement via escrow contracts across Ethereum, Polygon,
and Arbitrum. Manages the full transaction lifecycle: build → sign → submit
→ confirm → handle failures. Supports multi-sig for large trades and
includes dispute resolution hooks.

Architecture:
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │ Settlement   │────▶│ Transaction  │────▶│ Chain-Specific  │
  │ Request      │     │ Builder      │     │ Executor        │
  └─────────────┘     └──────────────┘     └─────────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │ Multi-Sig   │     │ Gas          │     │ Confirmation &  │
  │ Manager     │     │ Estimator    │     │ Verification    │
  └─────────────┘     └──────────────┘     └─────────────────┘

Usage:
    engine = SettlementEngine(config)
    result = await engine.create_escrow("ETH/USDT", 1.5, "0x...")
    verified = await engine.verify_settlement(result.tx_hash)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS & ENUMS
# ═══════════════════════════════════════════════════════════════════════

class Chain(Enum):
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"


class SettlementStatus(Enum):
    PENDING = "pending"
    BUILDING = "building"
    SIGNING = "signing"
    SUBMITTED = "submitted"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class DisputeReason(Enum):
    AMOUNT_MISMATCH = "amount_mismatch"
    TIMEOUT = "timeout"
    COUNTERPARTY_DEFAULT = "counterparty_default"
    SMART_CONTRACT_ERROR = "smart_contract_error"
    PRICE_SLIPPAGE = "price_slippage"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    OTHER = "other"


# Escrow contract addresses per chain (mainnet)
DEFAULT_ESCROW_ADDRESSES: dict[Chain, str] = {
    Chain.ETHEREUM: "0x0000000000000000000000000000000000000000",  # placeholder
    Chain.POLYGON: "0x0000000000000000000000000000000000000000",
    Chain.ARBITRUM: "0x0000000000000000000000000000000000000000",
    Chain.OPTIMISM: "0x0000000000000000000000000000000000000000",
    Chain.BASE: "0x0000000000000000000000000000000000000000",
}

# Minimum confirmations per chain
MIN_CONFIRMATIONS: dict[Chain, int] = {
    Chain.ETHEREUM: 12,
    Chain.POLYGON: 256,
    Chain.ARBITRUM: 1,
    Chain.OPTIMISM: 1,
    Chain.BASE: 1,
}

# Multi-sig threshold: trades above this USD value require multi-sig
MULTISIG_THRESHOLD_USD = 100_000.0


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SettlementConfig:
    """Configuration for the settlement engine."""
    chain: Chain = Chain.ARBITRUM
    escrow_address: str = ""
    rpc_url: str = ""
    private_key: str = ""  # stored encrypted in production
    multisig_wallet: str = ""
    multisig_threshold: int = 2
    multisig_signers: list[str] = field(default_factory=list)
    settlement_timeout_s: int = 3600  # 1 hour
    max_retries: int = 3
    gas_limit_buffer: float = 1.2  # 20% buffer on gas estimates
    confirmation_timeout_s: int = 600  # 10 min for confirmations


@dataclass
class EscrowTrade:
    """Represents a trade to be settled via escrow."""
    trade_id: str
    pair: str
    amount: float
    price: float
    counterparty: str
    chain: Chain
    status: SettlementStatus = SettlementStatus.PENDING
    tx_hash: str = ""
    escrow_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    confirmations: int = 0
    gas_used: int = 0
    gas_price: int = 0
    total_cost_wei: int = 0
    error_message: str = ""
    approval_count: int = 0
    required_approvals: int = 1
    dispute_reason: Optional[DisputeReason] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransactionRequest:
    """A built transaction ready for signing."""
    to: str
    value: int  # wei
    data: bytes
    gas_limit: int
    gas_price: int  # legacy; or max_fee_per_gas for EIP-1559
    max_priority_fee: int = 0
    nonce: int = 0
    chain_id: int = 0


@dataclass
class SettlementResult:
    """Result of a settlement operation."""
    success: bool
    trade_id: str
    tx_hash: str = ""
    status: SettlementStatus = SettlementStatus.PENDING
    confirmations: int = 0
    block_number: int = 0
    gas_used: int = 0
    total_cost_wei: int = 0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# CHAIN IDs
# ═══════════════════════════════════════════════════════════════════════

CHAIN_IDS: dict[Chain, int] = {
    Chain.ETHEREUM: 1,
    Chain.POLYGON: 137,
    Chain.ARBITRUM: 42161,
    Chain.OPTIMISM: 10,
    Chain.BASE: 8453,
}


# ═══════════════════════════════════════════════════════════════════════
# SETTLEMENT ENGINE
# ═══════════════════════════════════════════════════════════════════════

class SettlementEngine:
    """
    Smart contract settlement engine.

    Manages the full lifecycle of on-chain settlements via escrow contracts.
    Supports atomic settlement, multi-sig approvals, and dispute resolution.
    """

    def __init__(self, config: SettlementConfig | None = None):
        self.config = config or SettlementConfig()
        self._active_trades: dict[str, EscrowTrade] = {}
        self._nonce: int = 0
        self._escrow_abi = self._build_escrow_abi()
        logger.info(
            "SettlementEngine initialized",
            extra={"chain": self.config.chain.value},
        )

    # ───────────────────────────────────────────────────────────────────
    # Public API
    # ───────────────────────────────────────────────────────────────────

    async def create_escrow(
        self,
        pair: str,
        amount: float,
        counterparty: str,
        price: float = 0.0,
        chain: Chain | None = None,
        timeout_s: int | None = None,
    ) -> SettlementResult:
        """
        Create an escrow settlement for a trade.

        Args:
            pair: Trading pair (e.g. "ETH/USDT")
            amount: Trade amount
            counterparty: Counterparty address
            price: Execution price
            chain: Override chain (default: config chain)
            timeout_s: Settlement timeout override

        Returns:
            SettlementResult with trade_id and tx_hash on success
        """
        chain = chain or self.config.chain
        timeout_s = timeout_s or self.config.settlement_timeout_s
        trade_id = f"escrow_{uuid.uuid4().hex[:12]}"

        trade = EscrowTrade(
            trade_id=trade_id,
            pair=pair,
            amount=amount,
            price=price,
            counterparty=counterparty,
            chain=chain,
            status=SettlementStatus.BUILDING,
        )

        # Check if multi-sig is required
        usd_value = amount * price if price > 0 else 0
        if usd_value >= MULTISIG_THRESHOLD_USD:
            trade.required_approvals = self.config.multisig_threshold
            logger.info(
                "Trade requires multi-sig",
                extra={
                    "trade_id": trade_id,
                    "usd_value": usd_value,
                    "required_approvals": trade.required_approvals,
                },
            )

        self._active_trades[trade_id] = trade

        try:
            # Step 1: Build transaction
            tx_req = await self._build_transaction(trade, chain)
            trade.status = SettlementStatus.SIGNING

            # Step 2: Sign transaction
            signed_tx = await self._sign_transaction(tx_req)
            trade.status = SettlementStatus.SUBMITTED

            # Step 3: Submit to chain
            tx_hash = await self._submit_transaction(signed_tx, chain)
            trade.tx_hash = tx_hash
            trade.status = SettlementStatus.CONFIRMING

            # Step 4: Wait for confirmations (non-blocking in production)
            confirmations = MIN_CONFIRMATIONS.get(chain, 12)
            confirmed = await self._wait_confirmations(
                tx_hash, confirmations, chain, timeout_s
            )

            if confirmed:
                trade.status = SettlementStatus.CONFIRMED
                trade.confirmations = confirmations
                logger.info(
                    "Settlement confirmed",
                    extra={"trade_id": trade_id, "tx_hash": tx_hash},
                )
                return SettlementResult(
                    success=True,
                    trade_id=trade_id,
                    tx_hash=tx_hash,
                    status=SettlementStatus.CONFIRMED,
                    confirmations=confirmations,
                )
            else:
                trade.status = SettlementStatus.FAILED
                trade.error_message = "Confirmation timeout"
                return SettlementResult(
                    success=False,
                    trade_id=trade_id,
                    tx_hash=tx_hash,
                    status=SettlementStatus.FAILED,
                    error="Confirmation timeout",
                )

        except Exception as e:
            trade.status = SettlementStatus.FAILED
            trade.error_message = str(e)
            logger.error(
                "Settlement failed",
                extra={"trade_id": trade_id, "error": str(e)},
            )
            return SettlementResult(
                success=False,
                trade_id=trade_id,
                status=SettlementStatus.FAILED,
                error=str(e),
            )

    async def verify_settlement(self, tx_hash: str) -> SettlementResult:
        """
        Verify a settlement on-chain.

        Confirms the transaction was included in a block and the
        escrow state matches expectations.
        """
        # Find trade by tx_hash
        trade = None
        for t in self._active_trades.values():
            if t.tx_hash == tx_hash:
                trade = t
                break

        if not trade:
            # Verify directly from chain
            return await self._verify_raw_transaction(tx_hash)

        try:
            chain = trade.chain
            confirmations = await self._get_confirmation_count(tx_hash, chain)
            trade.confirmations = confirmations

            min_conf = MIN_CONFIRMATIONS.get(chain, 12)
            is_confirmed = confirmations >= min_conf

            if is_confirmed:
                trade.status = SettlementStatus.CONFIRMED

                # Verify escrow state
                escrow_valid = await self._verify_escrow_state(
                    trade.escrow_id, chain
                )

                return SettlementResult(
                    success=True,
                    trade_id=trade.trade_id,
                    tx_hash=tx_hash,
                    status=SettlementStatus.CONFIRMED,
                    confirmations=confirmations,
                    metadata={"escrow_valid": escrow_valid},
                )
            else:
                return SettlementResult(
                    success=False,
                    trade_id=trade.trade_id,
                    tx_hash=tx_hash,
                    status=SettlementStatus.CONFIRMING,
                    confirmations=confirmations,
                    error=f"Insufficient confirmations: {confirmations}/{min_conf}",
                )

        except Exception as e:
            logger.error(
                "Verification failed",
                extra={"tx_hash": tx_hash, "error": str(e)},
            )
            return SettlementResult(
                success=False,
                trade_id=trade.trade_id if trade else "",
                tx_hash=tx_hash,
                status=SettlementStatus.FAILED,
                error=str(e),
            )

    async def add_approval(self, trade_id: str, signer: str) -> bool:
        """
        Add a multi-sig approval for a trade.

        Returns True when the required threshold is reached.
        """
        trade = self._active_trades.get(trade_id)
        if not trade:
            raise ValueError(f"Unknown trade: {trade_id}")

        if signer not in self.config.multisig_signers:
            raise ValueError(f"Signer {signer} not in multi-sig wallet")

        trade.approval_count += 1
        trade.updated_at = time.time()

        logger.info(
            "Approval added",
            extra={
                "trade_id": trade_id,
                "signer": signer,
                "approvals": f"{trade.approval_count}/{trade.required_approvals}",
            },
        )

        if trade.approval_count >= trade.required_approvals:
            logger.info("Multi-sig threshold reached", extra={"trade_id": trade_id})
            return True
        return False

    async def raise_dispute(
        self, trade_id: str, reason: DisputeReason, details: str = ""
    ) -> bool:
        """
        Raise a dispute for a settlement.

        Flags the trade and triggers dispute resolution hooks.
        """
        trade = self._active_trades.get(trade_id)
        if not trade:
            raise ValueError(f"Unknown trade: {trade_id}")

        trade.status = SettlementStatus.DISPUTED
        trade.dispute_reason = reason
        trade.updated_at = time.time()
        trade.metadata["dispute_details"] = details
        trade.metadata["dispute_timestamp"] = time.time()

        logger.warning(
            "Settlement disputed",
            extra={
                "trade_id": trade_id,
                "reason": reason.value,
                "details": details,
            },
        )

        # In production: notify dispute resolution system, pause related
        # settlements, and trigger arbitration workflow
        await self._trigger_dispute_hooks(trade, reason, details)
        return True

    async def get_trade_status(self, trade_id: str) -> EscrowTrade | None:
        """Get the current status of a settlement trade."""
        return self._active_trades.get(trade_id)

    async def list_active_trades(self) -> list[EscrowTrade]:
        """List all active settlement trades."""
        return list(self._active_trades.values())

    async def cancel_trade(self, trade_id: str) -> bool:
        """Cancel a pending settlement (only if not yet submitted)."""
        trade = self._active_trades.get(trade_id)
        if not trade:
            raise ValueError(f"Unknown trade: {trade_id}")

        if trade.status in (
            SettlementStatus.SUBMITTED,
            SettlementStatus.CONFIRMING,
            SettlementStatus.CONFIRMED,
        ):
            raise ValueError(
                f"Cannot cancel trade in status {trade.status.value}"
            )

        trade.status = SettlementStatus.CANCELLED
        trade.updated_at = time.time()
        logger.info("Trade cancelled", extra={"trade_id": trade_id})
        return True

    # ───────────────────────────────────────────────────────────────────
    # Transaction Lifecycle (Internal)
    # ───────────────────────────────────────────────────────────────────

    async def _build_transaction(
        self, trade: EscrowTrade, chain: Chain
    ) -> TransactionRequest:
        """Build an escrow contract transaction."""
        escrow_addr = self.config.escrow_address or DEFAULT_ESCROW_ADDRESSES.get(
            chain, ""
        )
        if not escrow_addr:
            raise ValueError(f"No escrow address configured for {chain.value}")

        chain_id = CHAIN_IDS.get(chain, 1)

        # Encode escrow function call: createEscrow(counterparty, amount, pair, timeout)
        data = self._encode_escrow_create(trade)

        # Estimate gas
        gas_limit = await self._estimate_gas(
            to=escrow_addr,
            data=data,
            value=0,
            chain=chain,
        )

        # Apply buffer
        gas_limit = int(gas_limit * self.config.gas_limit_buffer)

        # Get current gas price
        gas_price = await self._get_gas_price(chain)

        tx = TransactionRequest(
            to=escrow_addr,
            value=0,
            data=data,
            gas_limit=gas_limit,
            gas_price=gas_price,
            chain_id=chain_id,
        )

        trade.gas_price = gas_price
        logger.debug(
            "Transaction built",
            extra={
                "trade_id": trade.trade_id,
                "gas_limit": gas_limit,
                "gas_price": gas_price,
            },
        )
        return tx

    async def _sign_transaction(self, tx: TransactionRequest) -> bytes:
        """Sign a transaction with the configured private key."""
        # In production: use proper signing library (eth_account, etc.)
        # This is the structural placeholder
        if not self.config.private_key:
            raise ValueError("No private key configured for signing")

        # Simulate signing
        raw = (
            tx.to.encode()
            + tx.data
            + tx.gas_limit.to_bytes(8, "big")
            + tx.gas_price.to_bytes(8, "big")
        )
        return hashlib.sha256(raw).digest()

    async def _submit_transaction(
        self, signed_tx: bytes, chain: Chain
    ) -> str:
        """Submit a signed transaction to the chain."""
        # In production: call eth_sendRawTransaction via RPC
        # Generate deterministic mock tx hash for development
        tx_hash = "0x" + hashlib.sha256(signed_tx + str(time.time()).encode()).hexdigest()

        logger.info(
            "Transaction submitted",
            extra={"chain": chain.value, "tx_hash": tx_hash},
        )
        return tx_hash

    async def _wait_confirmations(
        self,
        tx_hash: str,
        required: int,
        chain: Chain,
        timeout_s: int,
    ) -> bool:
        """Wait for transaction confirmations."""
        start = time.time()
        while time.time() - start < timeout_s:
            count = await self._get_confirmation_count(tx_hash, chain)
            if count >= required:
                return True
            await asyncio.sleep(min(2.0, timeout_s / 10))
        return False

    async def _get_confirmation_count(
        self, tx_hash: str, chain: Chain
    ) -> int:
        """Get the current confirmation count for a transaction."""
        # In production: query chain for tx receipt and current block
        # Return minimum required for dev/testing
        return MIN_CONFIRMATIONS.get(chain, 12)

    async def _verify_raw_transaction(self, tx_hash: str) -> SettlementResult:
        """Verify a transaction not tracked in our active trades."""
        # In production: query chain directly
        return SettlementResult(
            success=False,
            trade_id="",
            tx_hash=tx_hash,
            status=SettlementStatus.PENDING,
            error="Transaction not found in active trades",
        )

    async def _verify_escrow_state(
        self, escrow_id: str, chain: Chain
    ) -> bool:
        """Verify the on-chain escrow state matches expectations."""
        # In production: call escrow contract's view functions
        return True

    # ───────────────────────────────────────────────────────────────────
    # Gas & Chain Interaction (Internal)
    # ───────────────────────────────────────────────────────────────────

    async def _estimate_gas(
        self,
        to: str,
        data: bytes,
        value: int,
        chain: Chain,
    ) -> int:
        """Estimate gas for a transaction."""
        # In production: call eth_estimateGas via RPC
        # Base estimates by chain (L2s are cheaper)
        base_gas = {
            Chain.ETHEREUM: 150_000,
            Chain.POLYGON: 120_000,
            Chain.ARBITRUM: 80_000,
            Chain.OPTIMISM: 80_000,
            Chain.BASE: 80_000,
        }
        return base_gas.get(chain, 150_000)

    async def _get_gas_price(self, chain: Chain) -> int:
        """Get current gas price for a chain (wei)."""
        # In production: call eth_gasPrice or feeHistory
        base_prices = {
            Chain.ETHEREUM: 30_000_000_000,  # 30 gwei
            Chain.POLYGON: 50_000_000_000,    # 50 gwei
            Chain.ARBITRUM: 100_000_000,      # 0.1 gwei
            Chain.OPTIMISM: 100_000_000,      # 0.1 gwei
            Chain.BASE: 100_000_000,          # 0.1 gwei
        }
        return base_prices.get(chain, 30_000_000_000)

    # ───────────────────────────────────────────────────────────────────
    # ABI Encoding (Internal)
    # ───────────────────────────────────────────────────────────────────

    def _build_escrow_abi(self) -> dict[str, Any]:
        """Build the escrow contract ABI definition."""
        return {
            "createEscrow": {
                "inputs": [
                    {"name": "counterparty", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "pairHash", "type": "bytes32"},
                    {"name": "timeout", "type": "uint256"},
                ],
                "outputs": [{"name": "escrowId", "type": "bytes32"}],
            },
            "releaseEscrow": {
                "inputs": [{"name": "escrowId", "type": "bytes32"}],
                "outputs": [],
            },
            "refundEscrow": {
                "inputs": [{"name": "escrowId", "type": "bytes32"}],
                "outputs": [],
            },
            "getEscrowState": {
                "inputs": [{"name": "escrowId", "type": "bytes32"}],
                "outputs": [
                    {
                        "name": "",
                        "type": "tuple",
                        "components": [
                            {"name": "sender", "type": "address"},
                            {"name": "receiver", "type": "address"},
                            {"name": "amount", "type": "uint256"},
                            {"name": "state", "type": "uint8"},
                            {"name": "timeout", "type": "uint256"},
                        ],
                    }
                ],
            },
        }

    def _encode_escrow_create(self, trade: EscrowTrade) -> bytes:
        """Encode the createEscrow function call."""
        # Simplified ABI encoding — in production use eth_abi
        pair_hash = hashlib.sha256(trade.pair.encode()).digest()
        timeout = int(time.time()) + self.config.settlement_timeout_s

        # Keccak256 function selector for createEscrow(address,uint256,bytes32,uint256)
        selector = b"\x12\x34\x56\x78"  # placeholder

        # Encode params (simplified)
        counterparty_bytes = bytes.fromhex(
            trade.counterparty.replace("0x", "").zfill(40)
        )
        amount_bytes = int(trade.amount * 1e18).to_bytes(32, "big")
        timeout_bytes = timeout.to_bytes(32, "big")

        return selector + counterparty_bytes + amount_bytes + pair_hash + timeout_bytes

    # ───────────────────────────────────────────────────────────────────
    # Dispute Resolution Hooks
    # ───────────────────────────────────────────────────────────────────

    async def _trigger_dispute_hooks(
        self,
        trade: EscrowTrade,
        reason: DisputeReason,
        details: str,
    ) -> None:
        """Trigger dispute resolution workflow."""
        logger.info(
            "Triggering dispute hooks",
            extra={
                "trade_id": trade.trade_id,
                "reason": reason.value,
            },
        )
        # In production:
        # 1. Pause related settlements
        # 2. Notify counterparty
        # 3. Submit to arbitration contract
        # 4. Log to dispute resolution database
        # 5. Alert risk management system


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE FACTORY
# ═══════════════════════════════════════════════════════════════════════

def create_settlement_engine(
    chain: str = "arbitrum",
    rpc_url: str = "",
    escrow_address: str = "",
    private_key: str = "",
    multisig_wallet: str = "",
    multisig_threshold: int = 2,
    multisig_signers: list[str] | None = None,
) -> SettlementEngine:
    """Create a SettlementEngine from simple parameters."""
    chain_enum = Chain(chain.lower())
    config = SettlementConfig(
        chain=chain_enum,
        rpc_url=rpc_url,
        escrow_address=escrow_address,
        private_key=private_key,
        multisig_wallet=multisig_wallet,
        multisig_threshold=multisig_threshold,
        multisig_signers=multisig_signers or [],
    )
    return SettlementEngine(config)
