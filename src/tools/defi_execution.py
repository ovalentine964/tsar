"""
TSAR Domain Tools — DeFi Execution Tools.

What the agent DOES on-chain. Covers DEX swaps, token approvals,
balance queries, and gas estimation across EVM chains and Solana.

Tools:
  1. swap()              — Execute a token swap on a DEX
  2. get_quote()         — Fetch a swap quote without executing
  3. get_token_balance() — Query token balances across chains
  4. approve_token()     — Approve token spending for DEX router
  5. get_gas_estimate()  — Estimate gas costs for a chain

All tools are async and delegate to WalletManager + DexExecutor.
Results use shared types from this module.

Usage:
    tools = DeFiExecutionTools(config)
    quote = await tools.get_quote("ethereum", "USDC", "WETH", 1000)
    result = await tools.swap("trading_wallet", "ethereum", "USDC", "WETH", 1000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.backends.defi.dex_executor import (
    DexExecutor,
    SwapStatus,
)
from src.backends.defi.wallet_manager import WalletInfo, WalletManager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class QuoteResult:
    """User-facing quote result.

    Attributes:
        from_token: Source token symbol.
        to_token: Destination token symbol.
        from_amount: Input amount.
        to_amount: Estimated output amount.
        effective_price: Effective exchange rate.
        price_impact: Price impact percentage.
        gas_cost_native: Estimated gas cost in native token.
        gas_cost_usd: Estimated gas cost in USD.
        route: DEX routing path.
        slippage: Slippage tolerance (%).
        chain: Chain identifier.
        valid_for_seconds: How long the quote is valid.
    """

    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    effective_price: float
    price_impact: float
    gas_cost_native: float
    gas_cost_usd: float
    route: str
    slippage: float
    chain: str
    valid_for_seconds: float = 30.0


@dataclass(frozen=True)
class SwapToolResult:
    """User-facing swap result.

    Attributes:
        success: Whether the swap succeeded.
        tx_hash: Transaction hash.
        from_token: Source token.
        to_token: Destination token.
        from_amount: Amount sent.
        to_amount: Amount received.
        gas_used: Gas consumed.
        gas_cost_native: Gas cost in native token.
        price_impact: Price impact.
        status: Swap status string.
        error: Error message if failed.
        chain: Chain identifier.
        timestamp: Execution time.
    """

    success: bool
    tx_hash: str
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float = 0.0
    gas_used: int = 0
    gas_cost_native: float = 0.0
    price_impact: float = 0.0
    status: str = ""
    error: str = ""
    chain: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class BalanceResult:
    """User-facing balance result.

    Attributes:
        wallet_name: Wallet label.
        address: Wallet address.
        chain: Chain identifier.
        native_symbol: Native token symbol.
        native_balance: Native token balance.
        tokens: List of token balances (symbol, balance, contract).
        timestamp: Snapshot time.
    """

    wallet_name: str
    address: str
    chain: str
    native_symbol: str
    native_balance: float
    tokens: tuple[dict[str, Any], ...] = ()
    timestamp: str = ""


@dataclass(frozen=True)
class ApprovalResult:
    """User-facing token approval result.

    Attributes:
        success: Whether the approval succeeded.
        tx_hash: Approval transaction hash.
        token: Token address.
        chain: Chain identifier.
        error: Error message if failed.
    """

    success: bool
    tx_hash: str
    token: str
    chain: str
    error: str = ""


@dataclass(frozen=True)
class GasResult:
    """User-facing gas estimate result.

    Attributes:
        chain: Chain identifier.
        gas_limit: Estimated gas units.
        gas_price_gwei: Gas price in gwei.
        gas_cost_native: Total cost in native token.
        gas_cost_usd: Estimated USD cost.
        base_fee_gwei: EIP-1559 base fee in gwei.
        priority_fee_gwei: Priority fee in gwei.
    """

    chain: str
    gas_limit: int
    gas_price_gwei: float
    gas_cost_native: float
    gas_cost_usd: float
    base_fee_gwei: float = 0.0
    priority_fee_gwei: float = 0.0


# ═══════════════════════════════════════════════════════════════════════
# DEFI EXECUTION TOOLS
# ═══════════════════════════════════════════════════════════════════════


class DeFiExecutionTools:
    """DeFi execution tools for on-chain trading.

    Provides the complete DeFi toolkit that TSAR agents use to
    interact with decentralized exchanges: getting quotes, executing
    swaps, managing approvals, checking balances, and estimating gas.

    All operations delegate to WalletManager for key management
    and DexExecutor for on-chain interaction.

    Attributes:
        wallet_manager: WalletManager instance.
        dex_executor: DexExecutor instance.
    """

    description = (
        "DeFi execution tools: DEX swaps, token approvals, "
        "balance queries, gas estimation across EVM chains and Solana"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize DeFi execution tools.

        Args:
            config: Configuration dict, typically from config/default.yaml.
        """
        self._config = config or {}
        self.wallet_manager = WalletManager(config)
        self.dex_executor = DexExecutor(config, self.wallet_manager)

        logger.info("DeFiExecutionTools initialized")

    # ── 1. Swap ─────────────────────────────────────────────────────

    async def swap(
        self,
        wallet_name: str,
        chain: str,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float | None = None,
    ) -> SwapToolResult:
        """Execute a token swap on a DEX.

        Full lifecycle: quote → approve → sign → submit → confirm.

        Args:
            wallet_name: Wallet label (must exist in WalletManager).
            chain: Chain identifier (ethereum, polygon, arbitrum, base, solana).
            from_token: Source token symbol (e.g. "USDC") or contract address.
            to_token: Destination token symbol or contract address.
            amount: Amount of source token to swap.
            slippage: Slippage tolerance in % (None = use config default).

        Returns:
            SwapToolResult with transaction details.

        Example:
            result = await tools.swap("main", "ethereum", "USDC", "WETH", 1000)
            if result.success:
                print(f"Swapped {result.from_amount} {result.from_token} → "
                      f"{result.to_amount} {result.to_token}")
                print(f"TX: {result.tx_hash}")
        """
        result = await self.dex_executor.swap(
            wallet_name=wallet_name,
            chain=chain,
            from_token=from_token,
            to_token=to_token,
            amount=amount,
            slippage=slippage,
        )

        return SwapToolResult(
            success=result.status == SwapStatus.CONFIRMED,
            tx_hash=result.tx_hash,
            from_token=result.from_token,
            to_token=result.to_token,
            from_amount=result.from_amount,
            to_amount=result.to_amount,
            gas_used=result.gas_used,
            gas_cost_native=result.gas_cost_native,
            price_impact=result.price_impact,
            status=result.status.value,
            error=result.error,
            chain=result.chain,
            timestamp=result.timestamp,
        )

    # ── 2. Get Quote ────────────────────────────────────────────────

    async def get_quote(
        self,
        chain: str,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float | None = None,
    ) -> QuoteResult:
        """Fetch a swap quote without executing.

        Gets the best available rate from 1inch (EVM) or Jupiter (Solana).
        Use this to preview swap outcomes before committing.

        Args:
            chain: Chain identifier.
            from_token: Source token symbol or address.
            to_token: Destination token symbol or address.
            amount: Amount of source token.
            slippage: Slippage tolerance override (%).

        Returns:
            QuoteResult with estimated output and costs.

        Example:
            quote = await tools.get_quote("ethereum", "USDC", "WETH", 1000)
            print(f"1000 USDC → {quote.to_amount:.6f} WETH")
            print(f"Price impact: {quote.price_impact:.2f}%")
            print(f"Gas cost: ${quote.gas_cost_usd:.2f}")
        """
        raw = await self.dex_executor.get_quote(
            chain=chain,
            from_token=from_token,
            to_token=to_token,
            amount=amount,
            slippage=slippage,
        )

        effective_price = raw.to_amount / raw.from_amount if raw.from_amount > 0 else 0.0

        return QuoteResult(
            from_token=raw.from_token,
            to_token=raw.to_token,
            from_amount=raw.from_amount,
            to_amount=raw.to_amount,
            effective_price=effective_price,
            price_impact=raw.price_impact,
            gas_cost_native=raw.gas_estimate / 1e18
            if raw.chain != "solana"
            else raw.gas_estimate / 1e9,
            gas_cost_usd=raw.gas_cost_usd,
            route=raw.route,
            slippage=raw.slippage,
            chain=raw.chain,
            valid_for_seconds=max(0, raw.valid_until - __import__("time").time()),
        )

    # ── 3. Get Token Balance ────────────────────────────────────────

    async def get_token_balance(
        self,
        wallet_name: str,
        chain: str,
        token_address: str | None = None,
    ) -> BalanceResult:
        """Query token balances for a wallet.

        Returns native token balance and optionally ERC-20/SPL
        token balances.

        Args:
            wallet_name: Wallet label.
            chain: Chain identifier.
            token_address: Specific token contract address (None = native only).

        Returns:
            BalanceResult with balance information.

        Example:
            bal = await tools.get_token_balance("main", "ethereum")
            print(f"ETH balance: {bal.native_balance}")

            bal = await tools.get_token_balance(
                "main", "ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
            )
            print(f"USDC balance: {bal.tokens[0]['balance']}")
        """
        wallet_bal = await self.wallet_manager.get_balance(
            name=wallet_name,
            chain=chain,
            token_address=token_address,
        )

        tokens = []
        for tb in wallet_bal.token_balances:
            tokens.append(
                {
                    "symbol": tb.symbol,
                    "balance": tb.balance_float,
                    "balance_raw": tb.balance,
                    "decimals": tb.decimals,
                    "contract": tb.contract,
                }
            )

        from src.backends.defi.wallet_manager import NATIVE_TOKEN

        return BalanceResult(
            wallet_name=wallet_name,
            address=wallet_bal.address,
            chain=wallet_bal.chain,
            native_symbol=NATIVE_TOKEN.get(chain, "???"),
            native_balance=wallet_bal.native_balance.balance_float,
            tokens=tuple(tokens),
            timestamp=wallet_bal.timestamp,
        )

    # ── 4. Approve Token ────────────────────────────────────────────

    async def approve_token(
        self,
        wallet_name: str,
        chain: str,
        token_address: str,
        amount: int | None = None,
        spender: str | None = None,
    ) -> ApprovalResult:
        """Approve a token for spending by the DEX router.

        Required before swapping ERC-20 tokens on EVM chains.
        Native tokens (ETH, MATIC, SOL) don't need approval.

        Args:
            wallet_name: Wallet label.
            chain: Chain identifier.
            token_address: Token contract address to approve.
            amount: Amount to approve in wei (None = unlimited).
            spender: Spender address (None = 1inch router).

        Returns:
            ApprovalResult with transaction hash.

        Example:
            # Approve USDC for unlimited spending
            result = await tools.approve_token(
                "main", "ethereum",
                "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
            )
            print(f"Approval TX: {result.tx_hash}")
        """
        try:
            tx_hash = await self.dex_executor.approve_token(
                wallet_name=wallet_name,
                chain=chain,
                token_address=token_address,
                amount=amount,
                spender=spender,
            )
            return ApprovalResult(
                success=True,
                tx_hash=tx_hash,
                token=token_address,
                chain=chain,
            )
        except Exception as exc:
            logger.error("Token approval failed: %s", exc)
            return ApprovalResult(
                success=False,
                tx_hash="",
                token=token_address,
                chain=chain,
                error=str(exc),
            )

    # ── 5. Get Gas Estimate ─────────────────────────────────────────

    async def get_gas_estimate(self, chain: str) -> GasResult:
        """Estimate current gas costs for a chain.

        Use before executing transactions to check if gas is reasonable.

        Args:
            chain: Chain identifier.

        Returns:
            GasResult with gas price and cost estimates.

        Example:
            gas = await tools.get_gas_estimate("ethereum")
            print(f"Gas price: {gas.gas_price_gwei:.1f} gwei")
            print(f"Estimated cost: ${gas.gas_cost_usd:.2f}")
        """
        raw = await self.dex_executor.get_gas_estimate(chain)

        return GasResult(
            chain=chain,
            gas_limit=raw.gas_limit,
            gas_price_gwei=raw.gas_price / 1e9 if raw.gas_price > 0 else 0,
            gas_cost_native=raw.gas_cost_native,
            gas_cost_usd=raw.gas_cost_usd,
            base_fee_gwei=raw.base_fee / 1e9 if raw.base_fee > 0 else 0,
            priority_fee_gwei=raw.priority_fee / 1e9 if raw.priority_fee > 0 else 0,
        )

    # ── Wallet Management (pass-through) ────────────────────────────

    def create_wallet(self, name: str, chain: str, private_key: str | None = None) -> WalletInfo:
        """Create or import a wallet.

        Args:
            name: Wallet label.
            chain: Chain identifier.
            private_key: Private key to import (None = generate new).

        Returns:
            WalletInfo with public address.
        """
        return self.wallet_manager.create_wallet(name, chain, private_key)

    def list_wallets(self) -> list[WalletInfo]:
        """List all stored wallets.

        Returns:
            List of WalletInfo objects (public data only).
        """
        return self.wallet_manager.list_wallets()

    def get_address(self, name: str, chain: str) -> str:
        """Get wallet address.

        Args:
            name: Wallet label.
            chain: Chain identifier.

        Returns:
            Blockchain address.
        """
        return self.wallet_manager.get_address(name, chain)

    def get_supported_chains(self) -> list[str]:
        """Get supported blockchain networks.

        Returns:
            List of chain identifiers.
        """
        return self.wallet_manager.get_supported_chains()

    def switch_network(self, chain: str, rpc_url: str, chain_id: int | None = None) -> None:
        """Switch a chain to a different RPC endpoint.

        Args:
            chain: Chain identifier.
            rpc_url: New RPC endpoint.
            chain_id: New chain ID (optional).
        """
        self.wallet_manager.switch_network(chain, rpc_url, chain_id)
