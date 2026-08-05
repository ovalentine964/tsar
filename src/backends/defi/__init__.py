"""
TSAR DeFi Backend — On-chain execution, settlement, and L2 optimization.

Provides decentralized exchange (DEX) execution across EVM chains
(ETH, Polygon, Arbitrum, Base) via 1inch Aggregation API and
Solana via Jupiter API, plus smart contract settlement and L2 gas optimization.

Components:
  - WalletManager: Encrypted wallet storage, multi-chain address management
  - DexExecutor: DEX swap execution with slippage protection and gas estimation
  - MEVProtection: Flashbots/Jito MEV protection, sandwich detection
  - OracleClient: Chainlink/Pyth price feeds, TWAP, deviation alerts
  - SettlementEngine: Smart contract escrow settlement with multi-sig support
  - L2Optimizer: L2 gas optimization, chain comparison, and batch transactions
  - BridgeClient: Cross-chain bridging (Wormhole, LayerZero, Axelar)
  - IntentExecutor: Intent-based execution (CoW Protocol, UniswapX, 1inch Fusion)
  - YieldOptimizer: DeFi yield scanning, risk-adjusted scoring, rebalancing
  - GlassnodeClient: SOPR, MVRV, exchange flows, whale clustering
  - NansenClient: Smart money tracking, token god mode, whale wallets
  - CryptoQuantClient: Exchange reserves, miner flows, funding rates

All private keys are encrypted at rest using Fernet symmetric encryption.
Testnet mode is enabled by default (Ethereum Sepolia, Solana devnet).

Usage:
    from src.backends.defi import (
        WalletManager, DexExecutor, MEVProtection, OracleClient,
        SettlementEngine, L2Optimizer, BridgeClient, IntentExecutor,
        YieldOptimizer, GlassnodeClient, NansenClient, CryptoQuantClient,
    )

    wm = WalletManager(config)
    executor = DexExecutor(config, wm)
    mev = MEVProtection(rpc_url="...")
    oracle = OracleClient(rpc_url="...")
    settlement = SettlementEngine()
    optimizer = L2Optimizer()
    bridge = BridgeClient(config)
    intent = IntentExecutor(config)
    yield_opt = YieldOptimizer()
    glassnode = GlassnodeClient(api_key="...")
"""

from __future__ import annotations

from src.backends.defi.analytics_providers import (
    CryptoQuantClient,
    DeFiLlamaClient,
    FallbackChain,
    GlassnodeClient,
    NansenClient,
)
from src.backends.defi.bridge_client import BridgeClient
from src.backends.defi.dex_executor import DexExecutor
from src.backends.defi.intent_executor import IntentExecutor
from src.backends.defi.l2_optimizer import L2Optimizer
from src.backends.defi.mev_protection import MEVProtection
from src.backends.defi.oracle_client import OracleClient
from src.backends.defi.settlement import SettlementEngine
from src.backends.defi.wallet_manager import WalletManager
from src.backends.defi.yield_optimizer import YieldOptimizer

__all__ = [
    "WalletManager",
    "DexExecutor",
    "MEVProtection",
    "OracleClient",
    "SettlementEngine",
    "L2Optimizer",
    "BridgeClient",
    "IntentExecutor",
    "YieldOptimizer",
    "GlassnodeClient",
    "NansenClient",
    "CryptoQuantClient",
    "DeFiLlamaClient",
    "FallbackChain",
]
