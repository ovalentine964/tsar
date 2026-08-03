"""
TSAR DeFi Backend — DEX Executor.

DEX swap execution via aggregator APIs:
  - 1inch Aggregation API: EVM chains (ETH, Polygon, Arbitrum, Base)
  - Jupiter API: Solana

Features:
  - Quote fetching with price impact calculation
  - Slippage protection (configurable tolerance)
  - Transaction submission with receipt confirmation
  - Gas estimation before every transaction
  - Token approval management

All operations are testnet-safe by default.

Usage:
    executor = DexExecutor(config, wallet_manager)
    quote = await executor.get_quote("ethereum", "USDC", "WETH", 1000)
    result = await executor.swap("trading_wallet", "ethereum", "USDC", "WETH", 1000)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

from src.backends.defi.wallet_manager import CHAIN_IDS, NATIVE_TOKEN, WalletManager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# 1inch Aggregation API v6 base URLs
_ONEINCH_BASE = "https://api.1inch.dev"

# Jupiter API v6
_JUPITER_BASE = "https://quote-api.jup.ag/v6"

# Well-known token addresses (EVM mainnet — testnet uses different addresses)
_TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "ethereum": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "polygon": {
        "MATIC": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    },
    "arbitrum": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "WBTC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
    },
    "base": {
        "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    },
}

# Solana token mints (mainnet)
_SOLANA_TOKENS: dict[str, str] = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "BONk": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
}

# Max gas limits for different operations
_DEFAULT_GAS_LIMIT = 300_000
_APPROVAL_GAS_LIMIT = 100_000

# Transaction receipt polling
_RECEIPT_POLL_INTERVAL_S = 2.0
_RECEIPT_TIMEOUT_S = 120.0


# ═══════════════════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════════════════


class SwapStatus(StrEnum):
    """Status of a swap operation."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class SwapQuote:
    """A DEX swap quote.

    Attributes:
        from_token: Source token symbol.
        to_token: Destination token symbol.
        from_amount: Amount of source token (human-readable).
        to_amount: Estimated amount of destination token.
        price_impact: Price impact as percentage.
        gas_estimate: Estimated gas cost in native token.
        gas_cost_usd: Estimated gas cost in USD.
        route: DEX routing path description.
        slippage: Configured slippage tolerance (%).
        valid_until: Quote expiration timestamp (Unix seconds).
        chain: Chain identifier.
        raw_response: Full API response for debugging.
    """

    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    price_impact: float
    gas_estimate: float
    gas_cost_usd: float
    route: str
    slippage: float
    valid_until: float
    chain: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SwapResult:
    """Result of executing a swap.

    Attributes:
        status: Swap status.
        tx_hash: Transaction hash.
        from_token: Source token.
        to_token: Destination token.
        from_amount: Amount sent.
        to_amount: Amount received (0 until confirmed).
        gas_used: Actual gas used.
        gas_cost_native: Gas cost in native token.
        block_number: Block number of confirmation.
        price_impact: Actual price impact.
        slippage_bps: Slippage in basis points.
        error: Error message if failed.
        chain: Chain identifier.
        timestamp: Execution timestamp (UTC ISO).
    """

    status: SwapStatus
    tx_hash: str
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float = 0.0
    gas_used: int = 0
    gas_cost_native: float = 0.0
    block_number: int = 0
    price_impact: float = 0.0
    slippage_bps: float = 0.0
    error: str = ""
    chain: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class GasEstimate:
    """Gas estimation for a transaction.

    Attributes:
        gas_limit: Estimated gas units.
        gas_price: Gas price in wei (EVM) or lamports (Solana).
        gas_cost_native: Total gas cost in native token.
        gas_cost_usd: Estimated USD cost.
        base_fee: EIP-1559 base fee (EVM only).
        priority_fee: EIP-1559 priority fee (EVM only).
    """

    gas_limit: int
    gas_price: int
    gas_cost_native: float
    gas_cost_usd: float
    base_fee: int = 0
    priority_fee: int = 0


# ═══════════════════════════════════════════════════════════════════════
# DEX EXECUTOR
# ═══════════════════════════════════════════════════════════════════════


class DexExecutor:
    """DEX swap execution via aggregator APIs.

    Supports:
      - 1inch Aggregation API for EVM chains (ETH, Polygon, Arbitrum, Base)
      - Jupiter API for Solana

    All operations include gas estimation, slippage protection,
    and transaction receipt confirmation with timeout.

    Attributes:
        testnet: Whether using testnet mode.
        slippage: Default slippage tolerance (percentage).
        wallet_manager: WalletManager instance for signing.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        wallet_manager: WalletManager | None = None,
    ) -> None:
        """Initialize DEX executor.

        Args:
            config: Configuration dict (defi section).
            wallet_manager: WalletManager instance for key access.
        """
        cfg = (config or {}).get("defi", config or {})

        self.testnet: bool = cfg.get("testnet", True)
        self.slippage: float = cfg.get("slippage_tolerance", 1.0)
        self.confirmation_timeout: float = cfg.get("confirmation_timeout_s", 120.0)

        self._wallet_manager = wallet_manager or WalletManager(config)
        self._http: httpx.AsyncClient | None = None
        self._oneinch_api_key: str = cfg.get("oneinch_api_key", "")

        logger.info(
            "DexExecutor initialized (testnet=%s, slippage=%.2f%%)",
            self.testnet,
            self.slippage,
        )

    async def _get_http(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ── Token Resolution ────────────────────────────────────────────

    def _resolve_token(self, chain: str, symbol: str) -> str:
        """Resolve a token symbol to its contract address.

        Args:
            chain: Chain identifier.
            symbol: Token symbol (e.g. "USDC") or address.

        Returns:
            Token contract address.
        """
        # If it looks like an address, return as-is
        if symbol.startswith("0x") and len(symbol) >= 40:
            return symbol

        chain = chain.lower()
        if chain == "solana":
            mint = _SOLANA_TOKENS.get(symbol.upper())
            if not mint:
                raise ValueError(f"Unknown Solana token: {symbol}")
            return mint

        chain_tokens = _TOKEN_ADDRESSES.get(chain, {})
        addr = chain_tokens.get(symbol.upper())
        if not addr:
            raise ValueError(f"Unknown token '{symbol}' on chain '{chain}'")
        return addr

    def _token_symbol(self, chain: str, address: str) -> str:
        """Get the symbol for a token address (best-effort).

        Args:
            chain: Chain identifier.
            address: Token contract address.

        Returns:
            Token symbol or shortened address.
        """
        chain = chain.lower()
        if chain == "solana":
            for sym, addr in _SOLANA_TOKENS.items():
                if addr == address:
                    return sym
        else:
            chain_tokens = _TOKEN_ADDRESSES.get(chain, {})
            for sym, addr in chain_tokens.items():
                if addr.lower() == address.lower():
                    return sym
        return address[:8] + "..."

    # ── Quote Fetching ──────────────────────────────────────────────

    async def get_quote(
        self,
        chain: str,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float | None = None,
    ) -> SwapQuote:
        """Fetch a swap quote from the appropriate aggregator.

        Routes to 1inch for EVM chains, Jupiter for Solana.

        Args:
            chain: Chain identifier.
            from_token: Source token symbol or address.
            to_token: Destination token symbol or address.
            amount: Amount of source token (human-readable).
            slippage: Slippage tolerance override (%).

        Returns:
            SwapQuote with estimated output and gas.
        """
        chain = chain.lower()
        slippage = slippage or self.slippage

        if chain == "solana":
            return await self._jupiter_quote(from_token, to_token, amount, slippage)
        else:
            return await self._oneinch_quote(chain, from_token, to_token, amount, slippage)

    async def _oneinch_quote(
        self,
        chain: str,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float,
    ) -> SwapQuote:
        """Fetch quote from 1inch Aggregation API."""
        http = await self._get_http()

        from_addr = self._resolve_token(chain, from_token)
        to_addr = self._resolve_token(chain, to_token)
        chain_id = CHAIN_IDS.get(chain)
        if not chain_id:
            raise ValueError(f"No chain ID for '{chain}'")

        # Get token decimals for amount conversion
        from_decimals = self._get_token_decimals(chain, from_addr)
        amount_wei = int(amount * (10 ** from_decimals))

        url = f"{_ONEINCH_BASE}/swap/v6.0/{chain_id}/quote"
        params = {
            "src": from_addr,
            "dst": to_addr,
            "amount": str(amount_wei),
            "includeGas": "true",
        }

        headers = {}
        if self._oneinch_api_key:
            headers["Authorization"] = f"Bearer {self._oneinch_api_key}"

        resp = await http.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        to_decimals = self._get_token_decimals(chain, to_addr)
        to_amount = int(data.get("dstAmount", 0)) / (10 ** to_decimals)
        gas_estimate = int(data.get("gas", _DEFAULT_GAS_LIMIT))

        # Estimate gas cost
        gas_info = await self._estimate_gas_cost(chain, gas_estimate)

        # Build route description
        protocols = data.get("protocols", [])
        route_parts = []
        for step in protocols:
            if isinstance(step, list) and step:
                for sub in step:
                    if isinstance(sub, dict):
                        route_parts.append(sub.get("name", "unknown"))
        route = " → ".join(route_parts[:5]) if route_parts else "direct"

        return SwapQuote(
            from_token=from_token,
            to_token=to_token,
            from_amount=amount,
            to_amount=to_amount,
            price_impact=float(data.get("priceImpact", 0)),
            gas_estimate=gas_estimate,
            gas_cost_usd=gas_info.gas_cost_usd,
            route=route,
            slippage=slippage,
            valid_until=time.time() + 30,  # 1inch quotes are ephemeral
            chain=chain,
            raw_response=data,
        )

    async def _jupiter_quote(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float,
    ) -> SwapQuote:
        """Fetch quote from Jupiter API."""
        http = await self._get_http()

        from_mint = self._resolve_token("solana", from_token)
        to_mint = self._resolve_token("solana", to_token)

        # SOL has 9 decimals, USDC has 6, etc.
        from_decimals = 9 if from_token.upper() == "SOL" else 6
        amount_lamports = int(amount * (10 ** from_decimals))

        url = f"{_JUPITER_BASE}/quote"
        params = {
            "inputMint": from_mint,
            "outputMint": to_mint,
            "amount": str(amount_lamports),
            "slippageBps": int(slippage * 100),  # Jupiter uses bps
        }

        resp = await http.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        to_decimals = 9 if to_token.upper() == "SOL" else 6
        to_amount = int(data.get("outAmount", 0)) / (10 ** to_decimals)

        # Jupiter doesn't return gas directly, estimate ~5000 lamports
        gas_lamports = 5000
        gas_sol = gas_lamports / 1e9

        # Route info
        route_plan = data.get("routePlan", [])
        route_parts = [step.get("swapInfo", {}).get("label", "unknown") for step in route_plan]
        route = " → ".join(route_parts[:5]) if route_parts else "direct"

        return SwapQuote(
            from_token=from_token,
            to_token=to_token,
            from_amount=amount,
            to_amount=to_amount,
            price_impact=float(data.get("priceImpactPct", 0)),
            gas_estimate=gas_lamports,
            gas_cost_usd=gas_sol * 150,  # Rough SOL price estimate
            route=route,
            slippage=slippage,
            valid_until=time.time() + 30,
            chain="solana",
            raw_response=data,
        )

    def _get_token_decimals(self, chain: str, token_address: str) -> int:
        """Get token decimals (defaults to 18 for EVM)."""
        # Native tokens
        native_addr = {
            "ethereum": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            "polygon": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            "arbitrum": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            "base": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        }

        if token_address == native_addr.get(chain):
            return 18

        # Stablecoins are typically 6 decimals
        stablecoins = {
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC eth
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT eth
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC polygon
            "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",  # USDT polygon
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC arbitrum
            "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",  # USDT arbitrum
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC base
        }
        if token_address in stablecoins:
            return 6

        # WBTC is 8
        wbtc_addrs = {
            "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
            "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
        }
        if token_address in wbtc_addrs:
            return 8

        return 18  # Default ERC-20

    # ── Swap Execution ──────────────────────────────────────────────

    async def swap(
        self,
        wallet_name: str,
        chain: str,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float | None = None,
    ) -> SwapResult:
        """Execute a token swap on a DEX.

        Full flow: fetch quote → check approval → sign → submit → confirm.

        Args:
            wallet_name: Wallet label.
            chain: Chain identifier.
            from_token: Source token symbol or address.
            to_token: Destination token symbol or address.
            amount: Amount of source token.
            slippage: Slippage tolerance override (%).

        Returns:
            SwapResult with transaction details.
        """
        chain = chain.lower()
        slippage = slippage or self.slippage

        logger.info(
            "Starting swap: %s %.6f %s → %s on %s",
            wallet_name, amount, from_token, to_token, chain,
        )

        try:
            # 1. Get quote
            quote = await self.get_quote(chain, from_token, to_token, amount, slippage)

            # 2. Gas pre-check
            gas_info = await self.get_gas_estimate(chain)
            logger.info("Gas estimate: %.6f %s ($%.2f)", gas_info.gas_cost_native, NATIVE_TOKEN.get(chain, "ETH"), gas_info.gas_cost_usd)

            # 3. Check/token approval (EVM only) — exact amount only, never unlimited
            if chain != "solana":
                from_addr = self._resolve_token(chain, from_token)
                native_symbol = NATIVE_TOKEN.get(chain, "ETH")
                if from_token.upper() != native_symbol and from_addr != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE":
                    # Approve exact trade amount +5% buffer for slippage (not unlimited)
                    approval_amount = int(amount * 1.05 * (10 ** quote.get("from_decimals", 18)))
                    await self.approve_token(wallet_name, chain, from_addr, amount=approval_amount)

            # 4. Build and sign transaction
            if chain == "solana":
                return await self._execute_solana_swap(wallet_name, quote, slippage)
            else:
                return await self._execute_evm_swap(wallet_name, chain, quote, slippage)

        except Exception as exc:
            logger.error("Swap failed: %s", exc)
            return SwapResult(
                status=SwapStatus.FAILED,
                tx_hash="",
                from_token=from_token,
                to_token=to_token,
                from_amount=amount,
                error=str(exc),
                chain=chain,
                timestamp=datetime.now(UTC).isoformat(),
            )

    async def _execute_evm_swap(
        self,
        wallet_name: str,
        chain: str,
        quote: SwapQuote,
        slippage: float,
    ) -> SwapResult:
        """Execute an EVM swap via 1inch."""
        http = await self._get_http()
        w3 = self._wallet_manager._get_web3(chain)
        address = self._wallet_manager.get_address(wallet_name, chain)

        from_addr = self._resolve_token(chain, quote.from_token)
        to_addr = self._resolve_token(chain, quote.to_token)
        chain_id = CHAIN_IDS.get(chain)
        from_decimals = self._get_token_decimals(chain, from_addr)
        amount_wei = int(quote.from_amount * (10 ** from_decimals))

        # Get swap transaction from 1inch
        url = f"{_ONEINCH_BASE}/swap/v6.0/{chain_id}/swap"
        params = {
            "src": from_addr,
            "dst": to_addr,
            "amount": str(amount_wei),
            "from": address,
            "slippage": str(slippage),
            "disableEstimate": "false",
        }

        headers = {}
        if self._oneinch_api_key:
            headers["Authorization"] = f"Bearer {self._oneinch_api_key}"

        resp = await http.get(url, params=params, headers=headers)
        resp.raise_for_status()
        swap_data = resp.json()

        tx = swap_data.get("tx", {})

        # Build transaction dict
        tx_dict = {
            "from": address,
            "to": w3.to_checksum_address(tx.get("to", "")),
            "data": tx.get("data", ""),
            "value": int(tx.get("value", 0)),
            "gas": int(tx.get("gas", _DEFAULT_GAS_LIMIT)),
            "chainId": chain_id,
        }

        # Estimate gas if not provided
        if tx_dict["gas"] == _DEFAULT_GAS_LIMIT:
            try:
                tx_dict["gas"] = w3.eth.estimate_gas(tx_dict)
            except Exception:
                pass  # Use default

        # Get gas price (EIP-1559)
        try:
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", 0)
            max_priority = w3.eth.max_priority_fee
            tx_dict["maxFeePerGas"] = base_fee * 2 + max_priority
            tx_dict["maxPriorityFeePerGas"] = max_priority
            tx_dict["type"] = 2  # EIP-1559
        except Exception:
            # Fallback to legacy gas price
            tx_dict["gasPrice"] = w3.eth.gas_price

        # Sign
        signed = self._wallet_manager.sign_transaction(wallet_name, chain, tx_dict)

        # Submit
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash_hex = tx_hash.hex()

        logger.info("Transaction submitted: %s", tx_hash_hex)

        # Wait for confirmation
        receipt = await self._wait_for_receipt(w3, tx_hash_hex)

        if receipt and receipt.get("status") == 1:
            gas_used = receipt.get("gasUsed", 0)
            effective_gas = receipt.get("effectiveGasPrice", tx_dict.get("gasPrice", 0))
            gas_cost = (gas_used * effective_gas) / 1e18

            return SwapResult(
                status=SwapStatus.CONFIRMED,
                tx_hash=tx_hash_hex,
                from_token=quote.from_token,
                to_token=quote.to_token,
                from_amount=quote.from_amount,
                to_amount=quote.to_amount,
                gas_used=gas_used,
                gas_cost_native=gas_cost,
                block_number=receipt.get("blockNumber", 0),
                price_impact=quote.price_impact,
                chain=chain,
                timestamp=datetime.now(UTC).isoformat(),
            )
        else:
            return SwapResult(
                status=SwapStatus.FAILED,
                tx_hash=tx_hash_hex,
                from_token=quote.from_token,
                to_token=quote.to_token,
                from_amount=quote.from_amount,
                error="Transaction reverted",
                chain=chain,
                timestamp=datetime.now(UTC).isoformat(),
            )

    async def _execute_solana_swap(
        self,
        wallet_name: str,
        quote: SwapQuote,
        slippage: float,
    ) -> SwapResult:
        """Execute a Solana swap via Jupiter."""
        http = await self._get_http()

        from_mint = self._resolve_token("solana", quote.from_token)
        to_mint = self._resolve_token("solana", quote.to_token)
        from_decimals = 9 if quote.from_token.upper() == "SOL" else 6
        amount_lamports = int(quote.from_amount * (10 ** from_decimals))

        address = self._wallet_manager.get_address(wallet_name, "solana")

        # Get swap transaction from Jupiter
        url = f"{_JUPITER_BASE}/swap"
        payload = {
            "quoteResponse": quote.raw_response,
            "userPublicKey": address,
            "wrapAndUnwrapSol": True,
            "slippageBps": int(slippage * 100),
        }

        resp = await http.post(url, json=payload)
        resp.raise_for_status()
        swap_data = resp.json()

        swap_tx_b64 = swap_data.get("swapTransaction", "")
        if not swap_tx_b64:
            return SwapResult(
                status=SwapStatus.FAILED,
                tx_hash="",
                from_token=quote.from_token,
                to_token=quote.to_token,
                from_amount=quote.from_amount,
                error="No swap transaction returned",
                chain="solana",
                timestamp=datetime.now(UTC).isoformat(),
            )

        # Decode and sign
        import base64
        from solders.transaction import VersionedTransaction

        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)

        signed_tx = self._wallet_manager.sign_solana_transaction(wallet_name, tx)

        # Submit
        client = self._wallet_manager.get_solana_client()
        try:
            resp = await client.send_raw_transaction(bytes(signed_tx))
            tx_hash = str(resp.value)
            logger.info("Solana transaction submitted: %s", tx_hash)

            # Confirm
            from solders.signature import Signature
            sig = Signature.from_string(tx_hash)
            confirmation = await client.confirm_transaction(sig)

            return SwapResult(
                status=SwapStatus.CONFIRMED,
                tx_hash=tx_hash,
                from_token=quote.from_token,
                to_token=quote.to_token,
                from_amount=quote.from_amount,
                to_amount=quote.to_amount,
                chain="solana",
                timestamp=datetime.now(UTC).isoformat(),
            )
        except Exception as exc:
            return SwapResult(
                status=SwapStatus.FAILED,
                tx_hash="",
                from_token=quote.from_token,
                to_token=quote.to_token,
                from_amount=quote.from_amount,
                error=str(exc),
                chain="solana",
                timestamp=datetime.now(UTC).isoformat(),
            )
        finally:
            await client.close()

    # ── Token Approval ──────────────────────────────────────────────

    async def approve_token(
        self,
        wallet_name: str,
        chain: str,
        token_address: str,
        amount: int,
        spender: str | None = None,
    ) -> str:
        """Approve a token for spending by the DEX router.

        SECURITY: Always approve exact amounts, never unlimited.
        Callers must provide the exact amount needed for the trade.

        Args:
            wallet_name: Wallet label.
            chain: Chain identifier.
            token_address: Token contract address.
            amount: Exact amount to approve (in wei). REQUIRED — no unlimited approvals.
            spender: Spender address (None = 1inch router).

        Returns:
            Transaction hash of the approval.
        """
        chain = chain.lower()

        # Security: reject unlimited or excessively large approvals
        _MAX_REASONABLE_APPROVAL = 2**128  # ~3.4e38 — still huge, but not 2^256
        if amount <= 0:
            raise ValueError(f"Approval amount must be positive, got {amount}")
        if amount > _MAX_REASONABLE_APPROVAL:
            raise ValueError(
                f"Approval amount {amount} exceeds maximum reasonable value {_MAX_REASONABLE_APPROVAL}. "
                f"Use exact trade amounts, not unlimited approvals."
            )

        w3 = self._wallet_manager._get_web3(chain)
        address = self._wallet_manager.get_address(wallet_name, chain)

        # ERC-20 approve ABI
        approve_abi = [
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"},
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ]

        # Default spender: 1inch router
        if spender is None:
            # 1inch v6 router addresses by chain
            routers = {
                "ethereum": "0x111111125421cA6dc452d289314280a0f8842A65",
                "polygon": "0x111111125421cA6dc452d289314280a0f8842A65",
                "arbitrum": "0x111111125421cA6dc452d289314280a0f8842A65",
                "base": "0x111111125421cA6dc452d289314280a0f8842A65",
            }
            spender = routers.get(chain, routers["ethereum"])

        logger.info(
            "Approving %s wei of %s for spender %s on %s",
            amount, token_address, spender, chain,
        )

        contract = w3.eth.contract(
            address=w3.to_checksum_address(token_address),
            abi=approve_abi,
        )

        tx = contract.functions.approve(
            w3.to_checksum_address(spender),
            amount,
        ).build_transaction({
            "from": address,
            "nonce": w3.eth.get_transaction_count(address),
            "chainId": CHAIN_IDS.get(chain, 1),
        })

        # Estimate gas
        try:
            tx["gas"] = w3.eth.estimate_gas(tx)
        except Exception:
            tx["gas"] = _APPROVAL_GAS_LIMIT

        # Gas pricing
        try:
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", 0)
            max_priority = w3.eth.max_priority_fee
            tx["maxFeePerGas"] = base_fee * 2 + max_priority
            tx["maxPriorityFeePerGas"] = max_priority
            tx["type"] = 2
        except Exception:
            tx["gasPrice"] = w3.eth.gas_price

        signed = self._wallet_manager.sign_transaction(wallet_name, chain, tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash_hex = tx_hash.hex()

        logger.info("Token approval submitted: %s", tx_hash_hex)

        # Wait for confirmation
        receipt = await self._wait_for_receipt(w3, tx_hash_hex)
        if receipt and receipt.get("status") == 1:
            logger.info("Token approval confirmed: %s", tx_hash_hex)
        else:
            logger.warning("Token approval may have failed: %s", tx_hash_hex)

        return tx_hash_hex

    # ── Gas Estimation ──────────────────────────────────────────────

    async def get_gas_estimate(self, chain: str) -> GasEstimate:
        """Estimate current gas costs for a chain.

        Args:
            chain: Chain identifier.

        Returns:
            GasEstimate with current gas prices.
        """
        chain = chain.lower()

        if chain == "solana":
            return GasEstimate(
                gas_limit=200_000,  # Compute units
                gas_price=5000,      # Lamports per CU
                gas_cost_native=5000 / 1e9 * 200_000,
                gas_cost_usd=0.001,  # Very cheap
            )

        w3 = self._wallet_manager._get_web3(chain)

        try:
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", w3.eth.gas_price)

            try:
                priority_fee = w3.eth.max_priority_fee
            except Exception:
                priority_fee = base_fee // 10

            gas_price = base_fee * 2 + priority_fee
            gas_limit = _DEFAULT_GAS_LIMIT
            gas_cost_wei = gas_price * gas_limit
            gas_cost_native = gas_cost_wei / 1e18

            # Rough USD estimate (assumes ~$3000/ETH, ~$0.50/MATIC)
            eth_prices = {
                "ethereum": 3000,
                "polygon": 0.50,
                "arbitrum": 3000,
                "base": 3000,
            }
            gas_cost_usd = gas_cost_native * eth_prices.get(chain, 3000)

            return GasEstimate(
                gas_limit=gas_limit,
                gas_price=gas_price,
                gas_cost_native=gas_cost_native,
                gas_cost_usd=gas_cost_usd,
                base_fee=base_fee,
                priority_fee=priority_fee,
            )
        except Exception as exc:
            logger.warning("Gas estimation failed: %s", exc)
            return GasEstimate(
                gas_limit=_DEFAULT_GAS_LIMIT,
                gas_price=0,
                gas_cost_native=0,
                gas_cost_usd=0,
            )

    # ── Transaction Receipt ─────────────────────────────────────────

    async def _wait_for_receipt(
        self,
        w3: Any,
        tx_hash: str,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Wait for a transaction receipt with timeout.

        Args:
            w3: Web3 instance.
            tx_hash: Transaction hash (0x-prefixed hex).
            timeout: Max wait time in seconds.

        Returns:
            Receipt dict or None if timed out.
        """
        timeout = timeout or self.confirmation_timeout
        start = time.time()

        while time.time() - start < timeout:
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    return dict(receipt)
            except Exception:
                pass

            await asyncio.sleep(_RECEIPT_POLL_INTERVAL_S)

        logger.warning("Transaction receipt timeout after %.0fs: %s", timeout, tx_hash)
        return None
