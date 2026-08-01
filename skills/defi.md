---
name: defi
description: DeFi operations — DEX trading, yield farming, cross-chain bridging, MEV protection
tools: [defi_execution, dex_executor, intent_executor, cross_chain, mev_protection, settlement, defi_yield]
requires_governance: true
---

# DeFi Operations Skill

## Purpose
Execute on-chain operations across EVM chains (ETH, Polygon, Arbitrum, Base) and Solana.
Covers DEX swaps, intent-based trading, cross-chain bridging, yield optimization, and MEV protection.

## Instructions

### DEX Execution
When executing on-chain swaps:
1. Check liquidity depth on target DEX
2. Calculate price impact (reject if > 1% for large orders)
3. Estimate gas costs and include in P&L calculation
4. Use 1inch aggregator (EVM) or Jupiter (Solana) for best routes
5. Set appropriate slippage tolerance (0.5% default, 1% for volatile pairs)
6. Monitor transaction confirmation

### Intent-Based Trading
For large orders or complex routes:
1. Use CoW Protocol for batched settlement (lower MEV exposure)
2. Use UniswapX for limit orders on Uniswap
3. Use 1inch Fusion for gasless swaps
4. Compare intent quotes across providers

### Cross-Chain Bridging
When moving assets between chains:
1. Compare bridge routes (Wormhole, LayerZero, Axelar)
2. Check bridge security (TVL, audit status, incident history)
3. Estimate bridge time and fees
4. Verify destination chain gas for subsequent operations
5. Monitor bridge transaction status

### Yield Optimization
For idle capital:
1. Scan lending protocols (Aave, Compound, Morpho)
2. Check LP opportunities (Uniswap V3 concentrated liquidity)
3. Evaluate yield farming rewards (beware impermanent loss)
4. Monitor health factors on leveraged positions
5. Auto-compound rewards when gas-efficient

### MEV Protection
Protect against sandwich attacks and front-running:
1. Use private mempools (Flashbots Protect) for EVM
2. Set appropriate slippage (not too high, not too low)
3. Use Flashbots Bundle for multi-tx operations
4. Monitor for suspicious pending transactions
5. Use Jito bundles on Solana

## Risk Constraints
- Maximum single DEX trade: $10,000
- Maximum price impact: 1%
- Minimum liquidity: $100K in pool
- Bridge only through audited protocols
- Health factor > 1.5 for leveraged positions
- No unaudited contract interactions

## Supported Chains
| Chain | DEX | Bridge | Gas Token |
|-------|-----|--------|-----------|
| Ethereum | Uniswap, 1inch | Wormhole, LayerZero | ETH |
| Polygon | QuickSwap, 1inch | Wormhole, Axelar | MATIC |
| Arbitrum | Uniswap, 1inch | Wormhole, LayerZero | ETH |
| Base | Uniswap, 1inch | Wormhole, LayerZero | ETH |
| Solana | Jupiter, Raydium | Wormhole | SOL |

## Tool Usage
```
defi_execution  → General DeFi operation executor
dex_executor    → Direct DEX swap execution
intent_executor → Intent-based trading (CoW, UniswapX, Fusion)
cross_chain     → Cross-chain bridging
mev_protection  → MEV detection and protection
settlement      → Smart contract escrow settlement
defi_yield      → Yield optimization and farming
```
