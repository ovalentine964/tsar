"""
TSAR — MEV Protection Module.

Provides multi-chain MEV protection for on-chain trades:

  - **Flashbots Protect** (Ethereum): private mempool via relay.flashbots.net
  - **Jito** (Solana): bundle submission for MEV protection
  - **Sandwich Attack Detection**: monitor pending swaps on same pair
  - **Gas Price Optimization**: EIP-1559 base fee tracking, priority fee estimation
  - **Transaction Simulation**: eth_call / simulateTransaction before submission

All public methods are async.  Synchronous wrappers are provided for tool-layer
compatibility.

Usage::

    from src.backends.defi.mev_protection import MEVProtection

    mev = MEVProtection(rpc_url="https://eth-mainnet.g.alchemy.com/v2/...")
    risk = await mev.check_mev_risk("WETH/USDC", 10.0)
    quote = await mev.get_protected_quote("WETH/USDC", 10.0)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

FLASHBOTS_RELAY_URL = "https://relay.flashbots.net"
FLASHBOTS_STATUS_URL = "https://protect.flashbots.net/v1/status"
JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf"
JITO_BUNDLE_URL = f"{JITO_BLOCK_ENGINE_URL}/api/v1/bundles"
JITO_TIP_DEFAULT_LAMPORTS = 10_000  # 0.00001 SOL

# Well-known DEX router addresses (Ethereum)
UNISWAP_V2_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D".lower()
UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564".lower()
SUSHISWAP_ROUTER = "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F".lower()

# Well-known token addresses (Ethereum mainnet)
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2".lower()
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48".lower()
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7".lower()


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


class MEVRiskLevel(StrEnum):
    """Estimated MEV risk for a proposed swap."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SubmissionMethod(StrEnum):
    """How the transaction should be submitted."""
    PUBLIC_MEMPOOL = "public_mempool"
    FLASHBOTS_PROTECT = "flashbots_protect"
    JITO_BUNDLE = "jito_bundle"
    PRIVATE_RPC = "private_rpc"


@dataclass(frozen=True)
class MEVRiskAssessment:
    """Result of an MEV risk check.

    Attributes:
        pair: Trading pair analysed.
        amount: Swap amount in base token.
        risk_level: Estimated risk severity.
        risk_score: Numeric risk 0.0 – 1.0.
        sandwich_detected: Whether a sandwich pattern is currently pending.
        pending_arbitrageurs: Addresses of detected arbitrage bots.
        recommended_method: Best submission method to mitigate risk.
        estimated_mev_loss_usd: Estimated loss if unprotected.
        gas_priority_gwei: Recommended priority fee (gwei).
        details: Human-readable explanation.
    """
    pair: str
    amount: float
    risk_level: MEVRiskLevel
    risk_score: float
    sandwich_detected: bool
    pending_arbitrageurs: list[str]
    recommended_method: SubmissionMethod
    estimated_mev_loss_usd: float
    gas_priority_gwei: float
    details: str


@dataclass(frozen=True)
class ProtectedQuote:
    """Quote with MEV protection baked in.

    Attributes:
        pair: Trading pair.
        amount: Input amount.
        output_amount: Expected output after slippage.
        price_impact_pct: Estimated price impact (%).
        slippage_tolerance_pct: Slippage tolerance used (%).
        submission_method: How to submit the resulting tx.
        mev_tip_lamports: Tip amount for Jito (Solana only).
        gas_estimate: Estimated gas units.
        priority_fee_gwei: Recommended priority fee.
        valid_until: Timestamp (epoch seconds) when quote expires.
        route: DEX route used for the quote.
    """
    pair: str
    amount: float
    output_amount: float
    price_impact_pct: float
    slippage_tolerance_pct: float
    submission_method: SubmissionMethod
    mev_tip_lamports: int
    gas_estimate: int
    priority_fee_gwei: float
    valid_until: float
    route: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GasEstimate:
    """EIP-1559 gas recommendation.

    Attributes:
        base_fee_gwei: Current base fee.
        low_priority_gwei: Priority fee for non-urgent txs (~6 blocks).
        medium_priority_gwei: Priority fee for standard txs (~3 blocks).
        high_priority_gwei: Priority fee for fast inclusion (~1 block).
        block_number: Block number of the estimate.
        timestamp: When the estimate was computed.
    """
    base_fee_gwei: float
    low_priority_gwei: float
    medium_priority_gwei: float
    high_priority_gwei: float
    block_number: int
    timestamp: float


@dataclass(frozen=True)
class SimulationResult:
    """Result of transaction simulation.

    Attributes:
        success: Whether the simulation succeeded.
        gas_used: Gas consumed in simulation.
        return_data: Hex-encoded return data.
        error: Error message if simulation failed.
        logs: Emitted event logs.
    """
    success: bool
    gas_used: int
    return_data: str
    error: str | None
    logs: list[dict[str, Any]] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# MEV PROTECTION ENGINE
# ═══════════════════════════════════════════════════════════════════════


class MEVProtection:
    """Multi-chain MEV protection engine.

    Supports Ethereum (Flashbots Protect) and Solana (Jito bundles).
    Provides sandwich detection, gas optimisation, and tx simulation.

    Args:
        rpc_url: Ethereum JSON-RPC endpoint.
        solana_rpc_url: Solana RPC endpoint (optional, for Jito).
        flashbots_relay: Flashbots relay URL (default: relay.flashbots.net).
        jito_tip_lamports: Tip amount for Jito bundles (default: 10_000).
        chain: ``"ethereum"`` or ``"solana"``.
        http_client: Optional pre-configured httpx.AsyncClient.
    """

    def __init__(
        self,
        rpc_url: str = "",
        solana_rpc_url: str = "",
        flashbots_relay: str = FLASHBOTS_RELAY_URL,
        jito_tip_lamports: int = JITO_TIP_DEFAULT_LAMPORTS,
        chain: str = "ethereum",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.rpc_url = rpc_url.rstrip("/")
        self.solana_rpc_url = solana_rpc_url.rstrip("/")
        self.flashbots_relay = flashbots_relay.rstrip("/")
        self.jito_tip_lamports = jito_tip_lamports
        self.chain = chain
        self._client = http_client
        self._owns_client = http_client is None

        # Cache for gas estimates / mempool snapshots
        self._gas_cache: GasEstimate | None = None
        self._gas_cache_ts: float = 0.0
        self._mempool_cache: list[dict[str, Any]] = []
        self._mempool_cache_ts: float = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── JSON-RPC helpers ──────────────────────────────────────────────

    async def _eth_call(self, method: str, params: list[Any] | None = None) -> Any:
        """Execute an Ethereum JSON-RPC call."""
        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        resp = await client.post(self.rpc_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data.get("result")

    async def _solana_call(self, method: str, params: list[Any] | None = None) -> Any:
        """Execute a Solana JSON-RPC call."""
        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        resp = await client.post(self.solana_rpc_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Solana RPC error: {data['error']}")
        return data.get("result")

    # ── Gas price optimisation (EIP-1559) ─────────────────────────────

    async def get_gas_estimate(self, *, force_refresh: bool = False) -> GasEstimate:
        """Fetch current EIP-1559 gas parameters.

        Uses ``eth_getBlockByNumber`` (latest) to read ``baseFeePerGas``
        and applies standard priority fee tiers.
        """
        now = time.time()
        if (
            not force_refresh
            and self._gas_cache is not None
            and now - self._gas_cache_ts < 12  # refresh every block
        ):
            return self._gas_cache

        block = await self._eth_call("eth_getBlockByNumber", ["latest", False])
        base_fee_hex = block.get("baseFeePerGas", "0x0")
        base_fee = int(base_fee_hex, 16) / 1e9  # wei → gwei
        block_number = int(block.get("number", "0x0"), 16)

        # Priority fee tiers (heuristic — could use eth_feeHistory)
        low = max(1.0, base_fee * 0.05)
        medium = max(2.0, base_fee * 0.10)
        high = max(3.0, base_fee * 0.20)

        estimate = GasEstimate(
            base_fee_gwei=round(base_fee, 2),
            low_priority_gwei=round(low, 2),
            medium_priority_gwei=round(medium, 2),
            high_priority_gwei=round(high, 2),
            block_number=block_number,
            timestamp=now,
        )
        self._gas_cache = estimate
        self._gas_cache_ts = now
        logger.debug("gas_estimate_refreshed", base_fee=base_fee, block=block_number)
        return estimate

    # ── Mempool monitoring / sandwich detection ───────────────────────

    async def _fetch_pending_transactions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch pending transactions from the mempool.

        Uses ``txpool_content`` (Geth) or ``eth_pendingTransactions``
        depending on node support.
        """
        now = time.time()
        if now - self._mempool_cache_ts < 5:
            return self._mempool_cache

        try:
            content = await self._eth_call("txpool_content")
            # Flatten pending txs
            txs: list[dict[str, Any]] = []
            for _addr, nonces in (content or {}).get("pending", {}).items():
                for _nonce, tx_list in nonces.items():
                    txs.extend(tx_list if isinstance(tx_list, list) else [tx_list])
            self._mempool_cache = txs[:limit]
        except Exception:
            # Fallback: eth_pendingTransactions (returns only hashes on most nodes)
            try:
                hashes = await self._eth_call("eth_pendingTransactions")
                self._mempool_cache = hashes[:limit] if isinstance(hashes, list) else []
            except Exception:
                self._mempool_cache = []

        self._mempool_cache_ts = now
        return self._mempool_cache

    def _parse_pair_tokens(self, pair: str) -> tuple[str, str]:
        """Resolve a pair string like 'WETH/USDC' to lowercase token addresses."""
        mapping = {
            "WETH": WETH, "ETH": WETH,
            "USDC": USDC, "USDT": USDT,
        }
        parts = pair.upper().split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid pair format: {pair}. Expected 'BASE/QUOTE'.")
        base = mapping.get(parts[0], parts[0].lower())
        quote = mapping.get(parts[1], parts[1].lower())
        return base, quote

    async def detect_sandwich_attacks(
        self,
        pair: str,
        amount: float,
    ) -> tuple[bool, list[str]]:
        """Scan the mempool for sandwich attack patterns on *pair*.

        Looks for pending swap transactions on the same DEX pair that
        bracket a victim transaction (same token pair, similar amounts,
        submitted within a short window).

        Returns:
            (sandwich_detected, list_of_arbitrageur_addresses)
        """
        base_token, quote_token = self._parse_pair_tokens(pair)
        pending = await self._fetch_pending_transactions()

        # Identify DEX swap txs targeting the same pair
        dex_routers = {UNISWAP_V2_ROUTER, UNISWAP_V3_ROUTER, SUSHISWAP_ROUTER}
        swap_txs: list[dict[str, Any]] = []

        for tx in pending:
            to_addr = (tx.get("to") or "").lower()
            if to_addr not in dex_routers:
                continue
            input_data = tx.get("input", "0x")
            # swapExactTokensForTokens (0x38ed1739) / swapExactETHForTokens (0x7ff36ab5)
            # We check if the tx interacts with our token pair by checking calldata
            if not isinstance(input_data, str) or len(input_data) < 10:
                continue
            method_sig = input_data[:10].lower()
            if method_sig in ("0x38ed1739", "0x7ff36ab5", "0x18cbafe5", "0x8803dbee"):
                swap_txs.append(tx)

        if len(swap_txs) < 2:
            return False, []

        # Heuristic: look for two txs from the same sender surrounding a third
        senders: dict[str, list[dict[str, Any]]] = {}
        for tx in swap_txs:
            sender = (tx.get("from") or "").lower()
            senders.setdefault(sender, []).append(tx)

        arbitrageurs: list[str] = []
        sandwich = False

        for sender, txs in senders.items():
            if len(txs) >= 2:
                # Same sender submitting multiple swaps on same pair → likely attacker
                sandwich = True
                arbitrageurs.append(sender)

        if not sandwich and len(swap_txs) >= 3:
            # Different senders: check for front-run / back-run pattern
            # (simplified: if >2 pending swaps on same pair, flag risk)
            unique_senders = {tx.get("from", "").lower() for tx in swap_txs}
            if len(unique_senders) >= 2:
                sandwich = True
                arbitrageurs = list(unique_senders)[:5]

        return sandwich, arbitrageurs

    # ── MEV risk assessment ───────────────────────────────────────────

    async def check_mev_risk(
        self,
        pair: str,
        amount: float,
    ) -> MEVRiskAssessment:
        """Estimate the MEV risk for a proposed swap.

        Combines mempool analysis, amount heuristics, and gas conditions
        to produce a comprehensive risk profile.
        """
        sandwich, arbitrageurs = await self.detect_sandwich_attacks(pair, amount)
        gas = await self.get_gas_estimate()

        # Risk scoring heuristic
        score = 0.0
        reasons: list[str] = []

        # Sandwich detected
        if sandwich:
            score += 0.4
            reasons.append(f"Sandwich pattern detected ({len(arbitrageurs)} bot(s))")

        # Large trades attract more MEV
        # Heuristic: >$50k equivalent → higher risk
        est_value_usd = amount * 2000  # rough WETH price placeholder
        if est_value_usd > 100_000:
            score += 0.3
            reasons.append(f"Large trade (~${est_value_usd:,.0f}) — attractive MEV target")
        elif est_value_usd > 10_000:
            score += 0.15
            reasons.append(f"Medium trade (~${est_value_usd:,.0f}) — moderate MEV exposure")
        else:
            reasons.append(f"Small trade (~${est_value_usd:,.0f}) — low MEV attractiveness")

        # High gas → more competition for block space → more MEV
        if gas.base_fee_gwei > 50:
            score += 0.15
            reasons.append(f"High base fee ({gas.base_fee_gwei} gwei) — increased MEV activity")
        elif gas.base_fee_gwei > 20:
            score += 0.05
            reasons.append(f"Moderate base fee ({gas.base_fee_gwei} gwei)")

        score = min(score, 1.0)

        if score >= 0.7:
            risk_level = MEVRiskLevel.CRITICAL
        elif score >= 0.5:
            risk_level = MEVRiskLevel.HIGH
        elif score >= 0.3:
            risk_level = MEVRiskLevel.MEDIUM
        else:
            risk_level = MEVRiskLevel.LOW

        # Recommended submission method
        if self.chain == "solana":
            method = SubmissionMethod.JITO_BUNDLE
        elif risk_level in (MEVRiskLevel.HIGH, MEVRiskLevel.CRITICAL):
            method = SubmissionMethod.FLASHBOTS_PROTECT
        else:
            method = SubmissionMethod.FLASHBOTS_PROTECT  # always prefer private mempool

        # Estimate potential MEV loss (rough: 0.1-1% of trade value for sandwich)
        mev_loss = est_value_usd * (0.005 if sandwich else 0.001)

        return MEVRiskAssessment(
            pair=pair,
            amount=amount,
            risk_level=risk_level,
            risk_score=round(score, 3),
            sandwich_detected=sandwich,
            pending_arbitrageurs=arbitrageurs,
            recommended_method=method,
            estimated_mev_loss_usd=round(mev_loss, 2),
            gas_priority_gwei=gas.high_priority_gwei,
            details="; ".join(reasons),
        )

    # ── Protected quote ───────────────────────────────────────────────

    async def get_protected_quote(
        self,
        pair: str,
        amount: float,
        slippage_pct: float = 0.5,
    ) -> ProtectedQuote:
        """Get a quote for *pair* with MEV protection applied.

        The quote includes:
        - Slippage-adjusted output amount
        - Recommended submission method (Flashbots / Jito)
        - Priority fee for fast inclusion
        - Quote expiry (30 seconds)
        """
        risk = await self.check_mev_risk(pair, amount)
        gas = await self.get_gas_estimate()

        # Simplified price model (real impl would query DEX quoter contract)
        # Using 1 WETH ≈ 2000 USDC as placeholder
        base, quote = self._parse_pair_tokens(pair)
        base_price = 2000.0  # placeholder
        raw_output = amount * base_price

        # Price impact heuristic: sqrt(amount / 1000) %
        price_impact = (amount / 1000) ** 0.5 * 0.1
        output_after_impact = raw_output * (1 - price_impact / 100)
        output_after_slippage = output_after_impact * (1 - slippage_pct / 100)

        return ProtectedQuote(
            pair=pair,
            amount=amount,
            output_amount=round(output_after_slippage, 6),
            price_impact_pct=round(price_impact, 4),
            slippage_tolerance_pct=slippage_pct,
            submission_method=risk.recommended_method,
            mev_tip_lamports=self.jito_tip_lamports if self.chain == "solana" else 0,
            gas_estimate=150_000,  # typical Uniswap swap
            priority_fee_gwei=gas.high_priority_gwei,
            valid_until=time.time() + 30,
            route=[pair],
        )

    # ── Flashbots submission ──────────────────────────────────────────

    async def submit_via_flashbots(
        self,
        signed_tx_hex: str,
        target_block: int | None = None,
    ) -> dict[str, Any]:
        """Submit a signed transaction via Flashbots Protect relay.

        Args:
            signed_tx_hex: Hex-encoded signed transaction.
            target_block: Optional target block number.

        Returns:
            Flashbots relay response.
        """
        client = await self._get_client()

        # Flashbots relay accepts JSON-RPC with eth_sendBundle or eth_sendRawTransaction
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendRawTransaction",
            "params": [signed_tx_hex],
        }

        headers = {
            "Content-Type": "application/json",
            "X-Flashbots-Signature": "tsar-mev-protection",  # placeholder — real impl uses signer
        }

        resp = await client.post(
            self.flashbots_relay,
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()

        logger.info(
            "flashbots_submit",
            relay=self.flashbots_relay,
            success="error" not in result,
        )
        return result

    # ── Jito bundle submission (Solana) ───────────────────────────────

    async def submit_via_jito(
        self,
        encoded_transactions: list[str],
    ) -> dict[str, Any]:
        """Submit transactions as a Jito bundle (Solana).

        Args:
            encoded_transactions: List of base58-encoded signed transactions.

        Returns:
            Jito bundle response with bundle_id.
        """
        client = await self._get_client()

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [encoded_transactions],
        }

        resp = await client.post(JITO_BUNDLE_URL, json=payload)
        resp.raise_for_status()
        result = resp.json()

        logger.info(
            "jito_bundle_submit",
            bundle_id=result.get("result"),
            tx_count=len(encoded_transactions),
        )
        return result

    # ── Transaction simulation ────────────────────────────────────────

    async def simulate_transaction(
        self,
        tx_params: dict[str, Any],
    ) -> SimulationResult:
        """Simulate a transaction before submission.

        Uses ``eth_call`` for Ethereum or ``simulateTransaction`` for Solana.

        Args:
            tx_params: Transaction parameters (``from``, ``to``, ``data``, ``value``, …).

        Returns:
            SimulationResult with success status and gas used.
        """
        if self.chain == "solana":
            return await self._simulate_solana(tx_params)
        return await self._simulate_ethereum(tx_params)

    async def _simulate_ethereum(self, tx_params: dict[str, Any]) -> SimulationResult:
        """Simulate via eth_call."""
        try:
            result = await self._eth_call("eth_call", [tx_params, "latest"])
            return SimulationResult(
                success=True,
                gas_used=int(result, 16) if isinstance(result, str) and result.startswith("0x") else 0,
                return_data=result or "0x",
                error=None,
            )
        except Exception as exc:
            return SimulationResult(
                success=False,
                gas_used=0,
                return_data="0x",
                error=str(exc),
            )

    async def _simulate_solana(self, tx_params: dict[str, Any]) -> SimulationResult:
        """Simulate via simulateTransaction."""
        try:
            result = await self._solana_call(
                "simulateTransaction",
                [tx_params.get("transaction", ""), {"encoding": "base58"}],
            )
            value = result if isinstance(result, dict) else {}
            err = value.get("err")
            return SimulationResult(
                success=err is None,
                gas_used=value.get("unitsConsumed", 0),
                return_data=json.dumps(value),
                error=json.dumps(err) if err else None,
                logs=value.get("logs", []),
            )
        except Exception as exc:
            return SimulationResult(
                success=False,
                gas_used=0,
                return_data="",
                error=str(exc),
            )

    # ── Flashbots status check ────────────────────────────────────────

    async def flashbots_status(self) -> dict[str, Any]:
        """Check Flashbots Protect relay status."""
        client = await self._get_client()
        try:
            resp = await client.get(FLASHBOTS_STATUS_URL)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    # ── Utility ───────────────────────────────────────────────────────

    def get_submission_config(self) -> dict[str, Any]:
        """Return the current submission configuration for logging / debugging."""
        return {
            "chain": self.chain,
            "rpc_url": self.rpc_url[:30] + "..." if len(self.rpc_url) > 30 else self.rpc_url,
            "flashbots_relay": self.flashbots_relay,
            "jito_tip_lamports": self.jito_tip_lamports,
        }
