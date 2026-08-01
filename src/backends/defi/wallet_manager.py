"""
TSAR DeFi Backend — Wallet Manager.

Encrypted wallet storage with multi-chain address management.
Supports EVM chains (ETH, Polygon, Arbitrum, Base) via web3.py
and Solana via solana-py.

Security:
  - All private keys encrypted at rest with Fernet symmetric encryption
  - Master key derived from environment variable or config passphrase
  - No plaintext keys in memory longer than needed
  - Testnet mode by default (Ethereum Sepolia, Solana devnet)

Usage:
    wm = WalletManager(config)
    wm.create_wallet("trading_wallet", chain="ethereum")
    addr = wm.get_address("trading_wallet", chain="ethereum")
    balance = await wm.get_balance("trading_wallet", chain="ethereum")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS & ENUMS
# ═══════════════════════════════════════════════════════════════════════


class Chain(StrEnum):
    """Supported blockchain networks."""

    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    BASE = "base"
    SOLANA = "solana"
    BITCOIN = "bitcoin"


# Default RPC endpoints (testnet where available)
DEFAULT_RPC: dict[str, str] = {
    Chain.ETHEREUM: "https://rpc.sepolia.org",
    Chain.POLYGON: "https://rpc-amoy.polygon.technology",
    Chain.ARBITRUM: "https://sepolia-rollup.arbitrum.io/rpc",
    Chain.BASE: "https://sepolia.base.org",
    Chain.SOLANA: "https://api.devnet.solana.com",
    Chain.BITCOIN: "",  # Bitcoin uses a different paradigm
}

# Chain IDs for EVM networks
CHAIN_IDS: dict[str, int] = {
    Chain.ETHEREUM: 11155111,   # Sepolia
    Chain.POLYGON: 80002,       # Amoy
    Chain.ARBITRUM: 421614,     # Arbitrum Sepolia
    Chain.BASE: 84532,          # Base Sepolia
}

# Native token symbols
NATIVE_TOKEN: dict[str, str] = {
    Chain.ETHEREUM: "ETH",
    Chain.POLYGON: "POL",
    Chain.ARBITRUM: "ETH",
    Chain.BASE: "ETH",
    Chain.SOLANA: "SOL",
    Chain.BITCOIN: "BTC",
}

# Well-known wrapped native tokens for DEX swaps
WRAPPED_NATIVE: dict[str, str] = {
    Chain.ETHEREUM: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH
    Chain.POLYGON: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",     # WMATIC
    Chain.ARBITRUM: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",    # WETH
    Chain.BASE: "0x4200000000000000000000000000000000000006",         # WETH
}


# ═══════════════════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class WalletInfo:
    """Public wallet information (no secrets).

    Attributes:
        name: Wallet label.
        address: Blockchain address.
        chain: Chain identifier.
        created_at: Wallet creation timestamp.
    """

    name: str
    address: str
    chain: str
    created_at: str


@dataclass(frozen=True)
class TokenBalance:
    """Token balance for a single asset.

    Attributes:
        symbol: Token symbol (e.g. "ETH", "USDC").
        balance: Raw balance as string (preserves precision).
        decimals: Token decimals.
        balance_float: Human-readable balance (balance / 10^decimals).
        contract: Token contract address (empty for native token).
    """

    symbol: str
    balance: str
    decimals: int
    balance_float: float
    contract: str = ""


@dataclass(frozen=True)
class WalletBalance:
    """Full wallet balance snapshot.

    Attributes:
        address: Wallet address.
        chain: Chain identifier.
        native_balance: Native token balance.
        token_balances: List of ERC-20/SPL token balances.
        timestamp: Snapshot time (UTC ISO).
    """

    address: str
    chain: str
    native_balance: TokenBalance
    token_balances: tuple[TokenBalance, ...] = ()
    timestamp: str = ""


# ERC-20 ABI fragment for balanceOf
_ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# WALLET MANAGER
# ═══════════════════════════════════════════════════════════════════════


class WalletManager:
    """Encrypted wallet storage with multi-chain address management.

    Manages wallet creation, key encryption, address resolution,
    and balance tracking across EVM chains and Solana.

    Private keys are encrypted with Fernet symmetric encryption.
    The master key is derived from:
      1. Environment variable TSAR_WALLET_MASTER_KEY (preferred)
      2. Config passphrase (fallback, less secure)

    All wallet data is stored in a single JSON file encrypted at rest.

    Attributes:
        testnet: Whether to use testnet RPC endpoints.
        wallet_path: Path to encrypted wallet storage file.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize wallet manager.

        Args:
            config: Configuration dict, typically from config/default.yaml.
                Expected keys under "defi" section:
                  - wallet_path: Path to wallet file (default: "data/wallets.enc")
                  - testnet: Use testnet mode (default: True)
                  - rpc_endpoints: Per-chain RPC URL overrides
                  - master_key_env: Env var name for master key
        """
        cfg = (config or {}).get("defi", config or {})

        self.testnet: bool = cfg.get("testnet", True)
        self.wallet_path: Path = Path(cfg.get("wallet_path", "data/wallets.enc"))

        # RPC endpoints — merge defaults with config overrides
        self._rpc_endpoints: dict[str, str] = dict(DEFAULT_RPC)
        for chain, url in cfg.get("rpc_endpoints", {}).items():
            if url:
                self._rpc_endpoints[chain] = url

        # Initialize Fernet encryption
        self._fernet = self._init_fernet(cfg)

        # In-memory wallet cache: name -> {chain -> {address, private_key}}
        self._wallets: dict[str, dict[str, dict[str, str]]] = {}

        # Load existing wallets if file exists
        self._load_wallets()

        # Lazy web3 connections (chain -> Web3 instance)
        self._w3: dict[str, Any] = {}

        logger.info(
            "WalletManager initialized (testnet=%s, wallet_path=%s, chains=%d)",
            self.testnet,
            self.wallet_path,
            len(self._rpc_endpoints),
        )

    # ── Encryption ──────────────────────────────────────────────────

    def _init_fernet(self, cfg: dict[str, Any]) -> Fernet:
        """Initialize Fernet encryption from master key.

        Args:
            cfg: Configuration dict.

        Returns:
            Initialized Fernet instance.

        Raises:
            RuntimeError: If no master key is available.
        """
        env_var = cfg.get("master_key_env", "TSAR_WALLET_MASTER_KEY")
        master_key = os.environ.get(env_var, "")

        if not master_key:
            # Generate a new key and warn
            master_key = Fernet.generate_key().decode()
            logger.warning(
                "No master key found in %s. Generated ephemeral key. "
                "Set %s in environment for persistent encryption.",
                env_var,
                env_var,
            )

        # If it looks like a raw passphrase, derive a Fernet key
        if not master_key.endswith("=") or len(master_key) < 32:
            import base64
            import hashlib

            derived = hashlib.sha256(master_key.encode()).digest()
            master_key = base64.urlsafe_b64encode(derived).decode()

        return Fernet(master_key.encode() if isinstance(master_key, str) else master_key)

    def _encrypt(self, data: str) -> str:
        """Encrypt a string and return base64-encoded ciphertext."""
        return self._fernet.encrypt(data.encode()).decode()

    def _decrypt(self, token: str) -> str:
        """Decrypt a base64-encoded ciphertext."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            raise ValueError("Failed to decrypt wallet data — wrong master key?")

    # ── Wallet Storage ──────────────────────────────────────────────

    def _load_wallets(self) -> None:
        """Load and decrypt wallet data from disk."""
        if not self.wallet_path.exists():
            logger.info("No existing wallet file found at %s", self.wallet_path)
            return

        try:
            encrypted = self.wallet_path.read_text(encoding="utf-8")
            plaintext = self._decrypt(encrypted)
            self._wallets = json.loads(plaintext)
            logger.info("Loaded %d wallets from disk", len(self._wallets))
        except Exception as exc:
            logger.error("Failed to load wallets: %s", exc)
            self._wallets = {}

    def _save_wallets(self) -> None:
        """Encrypt and save wallet data to disk."""
        self.wallet_path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(self._wallets, indent=2)
        encrypted = self._encrypt(plaintext)
        self.wallet_path.write_text(encrypted, encoding="utf-8")
        logger.debug("Saved %d wallets to disk", len(self._wallets))

    # ── Wallet Creation ─────────────────────────────────────────────

    def create_wallet(self, name: str, chain: str, private_key: str | None = None) -> WalletInfo:
        """Create or import a wallet.

        If private_key is provided, imports the wallet. Otherwise,
        generates a new keypair for the specified chain.

        Args:
            name: Wallet label (must be unique).
            chain: Chain identifier (see Chain enum).
            private_key: Hex private key to import (EVM: 0x-prefixed 64 hex chars,
                         Solana: base58-encoded). None to generate new.

        Returns:
            WalletInfo with the public address.

        Raises:
            ValueError: If chain is unsupported or wallet name exists.
        """
        chain = chain.lower()
        if chain not in [c.value for c in Chain]:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {[c.value for c in Chain]}")

        if name in self._wallets and chain in self._wallets[name]:
            raise ValueError(f"Wallet '{name}' already exists for chain '{chain}'")

        if private_key:
            address = self._derive_address(chain, private_key)
        else:
            address, private_key = self._generate_keypair(chain)

        # Store encrypted
        if name not in self._wallets:
            self._wallets[name] = {}

        self._wallets[name][chain] = {
            "address": address,
            "private_key": self._encrypt(private_key),
            "created_at": datetime.now(UTC).isoformat(),
        }

        self._save_wallets()

        logger.info("Created wallet '%s' on %s: %s", name, chain, address[:10] + "...")
        return WalletInfo(
            name=name,
            address=address,
            chain=chain,
            created_at=self._wallets[name][chain]["created_at"],
        )

    def _generate_keypair(self, chain: str) -> tuple[str, str]:
        """Generate a new keypair for the given chain.

        Returns:
            Tuple of (address, private_key_hex_or_base58).
        """
        if chain == Chain.SOLANA:
            return self._generate_solana_keypair()
        elif chain == Chain.BITCOIN:
            return self._generate_bitcoin_keypair()
        else:
            return self._generate_evm_keypair()

    def _generate_evm_keypair(self) -> tuple[str, str]:
        """Generate an EVM keypair using eth_account."""
        from eth_account import Account

        acct = Account.create()
        return acct.address, acct.key.hex()

    def _generate_solana_keypair(self) -> tuple[str, str]:
        """Generate a Solana keypair using solders."""
        from solders.keypair import Keypair

        kp = Keypair()
        return str(kp.pubkey()), kp.to_base58_string()

    def _generate_bitcoin_keypair(self) -> tuple[str, str]:
        """Generate a Bitcoin keypair.

        Uses a simplified approach — in production, use a proper
        Bitcoin library like bitcoinlib or bit.
        """
        import hashlib
        import os

        # Generate random private key
        privkey_bytes = os.urandom(32)
        privkey_hex = privkey_bytes.hex()

        # Simple address derivation (P2PKH testnet placeholder)
        # In production, use proper Bitcoin address derivation
        address_hash = hashlib.sha256(privkey_bytes).hexdigest()[:40]
        address = f"tb1q{address_hash[:38]}"

        return address, privkey_hex

    def _derive_address(self, chain: str, private_key: str) -> str:
        """Derive a public address from a private key.

        Args:
            chain: Chain identifier.
            private_key: Private key (hex for EVM, base58 for Solana).

        Returns:
            Blockchain address string.
        """
        if chain == Chain.SOLANA:
            from solders.keypair import Keypair
            kp = Keypair.from_base58_string(private_key)
            return str(kp.pubkey())
        elif chain == Chain.BITCOIN:
            import hashlib
            privkey_bytes = bytes.fromhex(private_key)
            address_hash = hashlib.sha256(privkey_bytes).hexdigest()[:40]
            return f"tb1q{address_hash[:38]}"
        else:
            from eth_account import Account
            acct = Account.from_key(private_key)
            return acct.address

    # ── Wallet Retrieval ────────────────────────────────────────────

    def get_address(self, name: str, chain: str) -> str:
        """Get the public address for a wallet.

        Args:
            name: Wallet label.
            chain: Chain identifier.

        Returns:
            Blockchain address.

        Raises:
            KeyError: If wallet not found.
        """
        chain = chain.lower()
        if name not in self._wallets or chain not in self._wallets[name]:
            raise KeyError(f"Wallet '{name}' not found for chain '{chain}'")
        return self._wallets[name][chain]["address"]

    def get_private_key(self, name: str, chain: str) -> str:
        """Get the decrypted private key for a wallet.

        ⚠️ SECURITY: Use sparingly. Clear references after signing.

        Args:
            name: Wallet label.
            chain: Chain identifier.

        Returns:
            Decrypted private key.

        Raises:
            KeyError: If wallet not found.
        """
        chain = chain.lower()
        if name not in self._wallets or chain not in self._wallets[name]:
            raise KeyError(f"Wallet '{name}' not found for chain '{chain}'")
        return self._decrypt(self._wallets[name][chain]["private_key"])

    def list_wallets(self) -> list[WalletInfo]:
        """List all stored wallets (public info only).

        Returns:
            List of WalletInfo objects.
        """
        result = []
        for name, chains in self._wallets.items():
            for chain, data in chains.items():
                result.append(WalletInfo(
                    name=name,
                    address=data["address"],
                    chain=chain,
                    created_at=data.get("created_at", ""),
                ))
        return result

    def delete_wallet(self, name: str, chain: str | None = None) -> bool:
        """Delete a wallet.

        Args:
            name: Wallet label.
            chain: Specific chain to delete (None = delete all chains for this name).

        Returns:
            True if wallet was deleted.
        """
        if name not in self._wallets:
            return False

        if chain:
            chain = chain.lower()
            if chain in self._wallets[name]:
                del self._wallets[name][chain]
                if not self._wallets[name]:
                    del self._wallets[name]
            else:
                return False
        else:
            del self._wallets[name]

        self._save_wallets()
        return True

    # ── Web3 Connections ────────────────────────────────────────────

    def _get_web3(self, chain: str) -> Any:
        """Get or create a Web3 connection for an EVM chain.

        Args:
            chain: Chain identifier.

        Returns:
            Web3 instance.

        Raises:
            ValueError: If chain is not EVM-compatible.
        """
        if chain == Chain.SOLANA:
            raise ValueError("Use get_solana_client() for Solana")
        if chain == Chain.BITCOIN:
            raise ValueError("Bitcoin does not use Web3")

        if chain not in self._w3:
            from web3 import Web3

            rpc_url = self._rpc_endpoints.get(chain, "")
            if not rpc_url:
                raise ValueError(f"No RPC endpoint configured for chain '{chain}'")

            w3 = Web3(Web3.HTTPProvider(rpc_url))

            if not w3.is_connected():
                logger.warning("Failed to connect to %s RPC: %s", chain, rpc_url)
            else:
                logger.info("Connected to %s RPC (chain_id=%s)", chain, w3.eth.chain_id)

            self._w3[chain] = w3

        return self._w3[chain]

    def get_solana_client(self) -> Any:
        """Get a Solana RPC client.

        Returns:
            AsyncClient for Solana RPC.
        """
        from solana.rpc.async_api import AsyncClient

        rpc_url = self._rpc_endpoints.get(Chain.SOLANA, DEFAULT_RPC[Chain.SOLANA])
        return AsyncClient(rpc_url)

    # ── Balance Tracking ────────────────────────────────────────────

    async def get_balance(
        self,
        name: str,
        chain: str,
        token_address: str | None = None,
    ) -> WalletBalance:
        """Get wallet balance for native and optionally a specific token.

        Args:
            name: Wallet label.
            chain: Chain identifier.
            token_address: ERC-20/SPL token contract address (None = all known tokens).

        Returns:
            WalletBalance snapshot.

        Raises:
            KeyError: If wallet not found.
        """
        chain = chain.lower()
        address = self.get_address(name, chain)

        if chain == Chain.SOLANA:
            return await self._get_solana_balance(address)
        elif chain == Chain.BITCOIN:
            return self._get_bitcoin_balance(address, chain)
        else:
            return await self._get_evm_balance(address, chain, token_address)

    async def _get_evm_balance(
        self,
        address: str,
        chain: str,
        token_address: str | None = None,
    ) -> WalletBalance:
        """Get EVM chain balance (native + ERC-20)."""
        w3 = self._get_web3(chain)

        # Native balance
        native_wei = w3.eth.get_balance(address)
        native_symbol = NATIVE_TOKEN.get(chain, "ETH")
        native_decimals = 18
        native_float = native_wei / (10 ** native_decimals)

        native = TokenBalance(
            symbol=native_symbol,
            balance=str(native_wei),
            decimals=native_decimals,
            balance_float=native_float,
        )

        # ERC-20 token balances (if requested)
        tokens: list[TokenBalance] = []
        if token_address:
            try:
                contract = w3.eth.contract(
                    address=w3.to_checksum_address(token_address),
                    abi=_ERC20_BALANCE_ABI,
                )
                raw_balance = contract.functions.balanceOf(address).call()
                decimals = contract.functions.decimals().call()
                symbol = contract.functions.symbol().call()
                tokens.append(TokenBalance(
                    symbol=symbol,
                    balance=str(raw_balance),
                    decimals=decimals,
                    balance_float=raw_balance / (10 ** decimals),
                    contract=token_address,
                ))
            except Exception as exc:
                logger.warning("Failed to get token balance for %s: %s", token_address, exc)

        return WalletBalance(
            address=address,
            chain=chain,
            native_balance=native,
            token_balances=tuple(tokens),
            timestamp=datetime.now(UTC).isoformat(),
        )

    async def _get_solana_balance(self, address: str) -> WalletBalance:
        """Get Solana balance (native SOL)."""
        from solders.pubkey import Pubkey

        client = self.get_solana_client()
        try:
            pubkey = Pubkey.from_string(address)
            resp = await client.get_balance(pubkey)
            lamports = resp.value
            sol_float = lamports / 1e9  # 1 SOL = 10^9 lamports

            native = TokenBalance(
                symbol="SOL",
                balance=str(lamports),
                decimals=9,
                balance_float=sol_float,
            )

            return WalletBalance(
                address=address,
                chain=Chain.SOLANA,
                native_balance=native,
                timestamp=datetime.now(UTC).isoformat(),
            )
        finally:
            await client.close()

    def _get_bitcoin_balance(self, address: str, chain: str) -> WalletBalance:
        """Get Bitcoin balance (placeholder — needs a Bitcoin node or API)."""
        native = TokenBalance(
            symbol="BTC",
            balance="0",
            decimals=8,
            balance_float=0.0,
        )
        return WalletBalance(
            address=address,
            chain=chain,
            native_balance=native,
            timestamp=datetime.now(UTC).isoformat(),
        )

    # ── Transaction Signing ─────────────────────────────────────────

    def sign_transaction(self, name: str, chain: str, tx_dict: dict[str, Any]) -> Any:
        """Sign an EVM transaction.

        Args:
            name: Wallet label.
            chain: Chain identifier.
            tx_dict: Transaction dict (to, value, data, gas, etc.).

        Returns:
            Signed transaction bytes.

        Raises:
            KeyError: If wallet not found.
            ValueError: If chain is not EVM-compatible.
        """
        chain = chain.lower()
        if chain == Chain.SOLANA:
            raise ValueError("Use sign_solana_transaction() for Solana")

        w3 = self._get_web3(chain)
        private_key = self.get_private_key(name, chain)

        try:
            # Ensure required fields
            if "nonce" not in tx_dict:
                tx_dict["nonce"] = w3.eth.get_transaction_count(
                    self.get_address(name, chain)
                )
            if "chainId" not in tx_dict:
                tx_dict["chainId"] = CHAIN_IDS.get(chain, 1)

            signed = w3.eth.account.sign_transaction(tx_dict, private_key)
            return signed
        finally:
            # Clear private key from memory
            del private_key

    def sign_solana_transaction(self, name: str, transaction: Any) -> Any:
        """Sign a Solana transaction.

        Args:
            name: Wallet label.
            transaction: Solana Transaction object.

        Returns:
            Signed transaction.
        """
        from solders.keypair import Keypair

        private_key = self.get_private_key(name, Chain.SOLANA)
        try:
            kp = Keypair.from_base58_string(private_key)
            transaction.sign([kp])
            return transaction
        finally:
            del private_key

    # ── Utility ─────────────────────────────────────────────────────

    def get_chain_id(self, chain: str) -> int:
        """Get the chain ID for an EVM network.

        Args:
            chain: Chain identifier.

        Returns:
            Chain ID integer.

        Raises:
            ValueError: If chain is not EVM.
        """
        chain = chain.lower()
        if chain not in CHAIN_IDS:
            raise ValueError(f"No chain ID for '{chain}' (not EVM)")
        return CHAIN_IDS[chain]

    def get_rpc_url(self, chain: str) -> str:
        """Get the RPC URL for a chain.

        Args:
            chain: Chain identifier.

        Returns:
            RPC endpoint URL.
        """
        return self._rpc_endpoints.get(chain.lower(), "")

    def switch_network(self, chain: str, rpc_url: str, chain_id: int | None = None) -> None:
        """Switch a chain to a different RPC endpoint.

        Useful for toggling between testnet and mainnet.

        Args:
            chain: Chain identifier.
            rpc_url: New RPC endpoint URL.
            chain_id: New chain ID (updates CHAIN_IDS if provided).
        """
        chain = chain.lower()
        self._rpc_endpoints[chain] = rpc_url

        if chain_id is not None:
            CHAIN_IDS[chain] = chain_id

        # Clear cached connection
        if chain in self._w3:
            del self._w3[chain]

        logger.info("Switched %s to RPC: %s (chain_id=%s)", chain, rpc_url, chain_id)

    def get_supported_chains(self) -> list[str]:
        """Get list of supported chain identifiers.

        Returns:
            List of chain name strings.
        """
        return [c.value for c in Chain]
