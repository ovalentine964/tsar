"""
TSAR Domain Tools — DeFi Yield Optimization.

Scans yield opportunities across DeFi protocols, assesses protocol risk,
calculates impermanent loss, compares staking rewards, and tracks DeFi
positions across wallets and protocols.

Data Sources:
  - DeFiLlama (free) — yield pools, TVL, protocol revenue
  - Glassnode (optional) — on-chain fundamentals
  - CoinGecko (free) — market data fallback

All tools are async with caching and graceful degradation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from ..backends.defi.analytics_providers import (
    FallbackChain,
)
from ..backends.defi.yield_optimizer import (
    RiskScore,
    YieldOptimizer,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DeFiPosition:
    """A DeFi position held in a wallet.

    Attributes:
        protocol: Protocol name.
        chain: Blockchain.
        position_type: "lending", "borrowing", "staking", "lp", "vault".
        symbol: Asset/pair symbol.
        balance: Token balance.
        balance_usd: USD value.
        apy: Current APY.
        rewards_pending: Pending reward tokens (USD value).
        health_factor: Health factor for borrow positions.
        pool_id: Pool/vault identifier.
    """

    protocol: str
    chain: str
    position_type: str
    symbol: str
    balance: float = 0.0
    balance_usd: float = 0.0
    apy: float = 0.0
    rewards_pending: float = 0.0
    health_factor: float = 0.0
    pool_id: str = ""


@dataclass(frozen=True)
class StakingReward:
    """Staking reward comparison for a token.

    Attributes:
        protocol: Staking protocol.
        token: Staking token (e.g. stETH, rETH).
        chain: Blockchain.
        apy: Annual Percentage Yield.
        tvl_usd: Total staked value.
        fee_pct: Protocol fee (%).
        min_stake: Minimum stake amount.
        lock_period: Lock period description.
        liquidity: How liquid the staked position is.
        risk_grade: Risk assessment grade.
    """

    protocol: str
    token: str
    chain: str
    apy: float = 0.0
    tvl_usd: float = 0.0
    fee_pct: float = 0.0
    min_stake: float = 0.0
    lock_period: str = "none"
    liquidity: str = "high"
    risk_grade: str = "B"


# ═══════════════════════════════════════════════════════════════════════
# TOOL CLASS
# ═══════════════════════════════════════════════════════════════════════


class DeFiYieldTools:
    """DeFi yield optimization tools for TSAR.

    Provides yield scanning, protocol risk assessment, impermanent loss
    calculation, staking reward comparison, and DeFi position tracking.

    Uses DeFiLlama (free) as primary data source with optional enrichment
    from Glassnode, CryptoQuant, and Nansen via FallbackChain.

    All methods are async with caching and graceful degradation.
    """

    description = (
        "DeFi yield optimization: yield scanning, protocol risk, "
        "impermanent loss, staking rewards, DeFi positions"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 300)

        # Build analytics chain
        self._analytics = FallbackChain.from_config(self._config)

        # Build yield optimizer
        self._optimizer = YieldOptimizer(
            analytics=self._analytics,
            config=self._config,
        )

        # HTTP client for wallet queries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        """Close all clients."""
        await self._optimizer.close()
        await self._analytics.close()
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    # ═══════════════════════════════════════════════════════════════════
    # SCAN YIELDS
    # ═══════════════════════════════════════════════════════════════════

    async def scan_yields(
        self,
        chain: str | None = None,
        min_tvl: float = 1_000_000,
        min_apy: float = 1.0,
        max_apy: float = 200.0,
        stable_only: bool = False,
        strategy_types: list[str] | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Find best DeFi yield opportunities.

        Scans across protocols and chains, computes risk-adjusted scores,
        and returns ranked opportunities with recommendations.

        Args:
            chain: Filter by chain (e.g. "Ethereum", "Arbitrum", "Base").
            min_tvl: Minimum TVL in USD (default $1M).
            min_apy: Minimum APY (%).
            max_apy: Maximum APY (%) — filters suspiciously high yields.
            stable_only: Only return stablecoin pools.
            strategy_types: Filter by type ("lending", "staking", "lp", "vault").
            limit: Maximum results.

        Returns:
            Dict with opportunities, summary stats, and metadata.
        """
        cache_key = f"scan:{chain}:{min_tvl}:{stable_only}:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            opportunities = await self._optimizer.scan_yields(
                chain=chain,
                min_tvl=min_tvl,
                min_apy=min_apy,
                max_apy=max_apy,
                stable_only=stable_only,
                strategy_types=strategy_types,
                limit=limit,
            )

            # Build summary
            if opportunities:
                avg_apy = sum(o.apy for o in opportunities) / len(opportunities)
                avg_risk_apy = sum(o.risk_adjusted_apy for o in opportunities) / len(opportunities)
                chains_seen = {o.chain for o in opportunities}
                protocols_seen = {o.protocol for o in opportunities}
                buy_count = sum(
                    1 for o in opportunities if o.recommendation in ("strong_buy", "buy")
                )
            else:
                avg_apy = avg_risk_apy = 0.0
                chains_seen = protocols_seen = set()
                buy_count = 0

            result = {
                "opportunities": [
                    {
                        "protocol": o.protocol,
                        "chain": o.chain,
                        "symbol": o.symbol,
                        "apy": o.apy,
                        "apy_base": o.apy_base,
                        "apy_reward": o.apy_reward,
                        "tvl_usd": o.tvl_usd,
                        "risk_adjusted_apy": o.risk_adjusted_apy,
                        "risk_grade": o.risk_score.risk_grade,
                        "il_risk": o.il_risk,
                        "stable_pool": o.stable_pool,
                        "strategy_type": o.strategy_type,
                        "recommendation": o.recommendation,
                        "reasoning": o.reasoning,
                    }
                    for o in opportunities
                ],
                "summary": {
                    "total_opportunities": len(opportunities),
                    "avg_apy": round(avg_apy, 2),
                    "avg_risk_adjusted_apy": round(avg_risk_apy, 2),
                    "chains_covered": sorted(chains_seen),
                    "protocols_covered": sorted(protocols_seen),
                    "buy_recommendations": buy_count,
                },
                "filters": {
                    "chain": chain,
                    "min_tvl": min_tvl,
                    "min_apy": min_apy,
                    "max_apy": max_apy,
                    "stable_only": stable_only,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.error("Yield scan failed: %s", exc)
            return {
                "opportunities": [],
                "summary": {"error": str(exc)},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    # ═══════════════════════════════════════════════════════════════════
    # ASSESS PROTOCOL RISK
    # ═══════════════════════════════════════════════════════════════════

    async def assess_protocol_risk(self, protocol: str) -> dict[str, Any]:
        """Assess the risk of a DeFi protocol.

        Evaluates smart contract audit status, TVL history, incident
        record, and time in production to produce a composite risk grade.

        Args:
            protocol: Protocol slug (e.g. "aave-v3", "lido", "uniswap-v3").

        Returns:
            Dict with risk scores, grade, factors, and TVL data.
        """
        cache_key = f"risk:{protocol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            risk = await self._optimizer.assess_protocol_risk(protocol)

            # Get TVL data
            dl = self._analytics.get_defillama()
            tvl_data = await dl.get_protocol_tvl(protocol) if dl else None

            result = {
                "protocol": protocol,
                "risk_score": {
                    "protocol_risk": risk.protocol_risk,
                    "tvl_risk": risk.tvl_risk,
                    "il_risk": risk.il_risk,
                    "audit_risk": risk.audit_risk,
                    "composite": risk.composite,
                },
                "risk_grade": risk.risk_grade,
                "risk_factors": list(risk.risk_factors),
                "tvl": {
                    "current_usd": tvl_data.tvl_usd if tvl_data else 0,
                    "change_1d": tvl_data.tvl_change_1d if tvl_data else 0,
                    "change_7d": tvl_data.tvl_change_7d if tvl_data else 0,
                    "change_30d": tvl_data.tvl_change_30d if tvl_data else 0,
                    "mcap_tvl_ratio": tvl_data.mcap_tvl_ratio if tvl_data else 0,
                }
                if tvl_data
                else None,
                "interpretation": self._interpret_risk(risk),
                "timestamp": datetime.now(UTC).isoformat(),
            }

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.error("Protocol risk assessment failed for %s: %s", protocol, exc)
            return {
                "protocol": protocol,
                "error": str(exc),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    # ═══════════════════════════════════════════════════════════════════
    # CALCULATE IMPERMANENT LOSS
    # ═══════════════════════════════════════════════════════════════════

    def calculate_impermanent_loss(
        self,
        pair: str,
        amount: float,
        duration_days: int,
        price_change_pct: float = 0.0,
        volatility: float = 0.5,
    ) -> dict[str, Any]:
        """Calculate expected impermanent loss for a liquidity position.

        Uses the standard constant-product AMM IL formula and factors
        in time-weighted expected IL based on volatility.

        Args:
            pair: Trading pair (e.g. "ETH/USDC", "WBTC/ETH").
            amount: Position size in USD.
            duration_days: Expected holding period in days.
            price_change_pct: Expected price change (%) of volatile asset.
            volatility: Annualized volatility (default 0.5 = 50%).

        Returns:
            Dict with IL analysis, break-even APY, and risk assessment.
        """
        result = YieldOptimizer.calculate_impermanent_loss(
            pair=pair,
            amount_usd=amount,
            duration_days=duration_days,
            price_change_pct=price_change_pct,
            volatility=volatility,
        )

        # Add actionable context
        result["actionable"] = {
            "should_provide_liquidity": result["il_risk"] in ("none", "low"),
            "min_yield_to_compensate": result["break_even_apy"],
            "suggested_strategy": self._suggest_il_strategy(result),
        }

        return result

    # ═══════════════════════════════════════════════════════════════════
    # GET STAKING REWARDS
    # ═══════════════════════════════════════════════════════════════════

    async def get_staking_rewards(self, token: str) -> dict[str, Any]:
        """Compare staking rewards across protocols for a given token.

        Covers liquid staking (ETH), native staking (SOL, DOT, ATOM),
        and stablecoin yields.

        Args:
            token: Token to stake (e.g. "ETH", "SOL", "USDC").

        Returns:
            Dict with staking options, best recommendation, and comparison.
        """
        cache_key = f"staking:{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        token_upper = token.upper()

        try:
            # ETH liquid staking
            if token_upper == "ETH":
                options = await self._optimizer.compare_liquid_staking(chain="Ethereum")
                result = {
                    "token": token_upper,
                    "options": [
                        {
                            "protocol": o.protocol,
                            "token": o.token,
                            "apy": o.apy,
                            "tvl_usd": o.tvl_usd,
                            "fee_pct": o.fee_pct,
                            "liquidity_score": o.liquidity_score,
                            "peg_stability": o.peg_stability,
                            "risk_grade": o.risk_score.risk_grade,
                            "composite_score": o.composite_score,
                            "recommendation": o.recommendation,
                        }
                        for o in options
                    ],
                    "best_option": {
                        "protocol": options[0].protocol,
                        "token": options[0].token,
                        "apy": options[0].apy,
                        "reasoning": f"Highest composite score ({options[0].composite_score:.2f}) with {options[0].recommendation} rating",
                    }
                    if options
                    else None,
                    "comparison_count": len(options),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            else:
                # For non-ETH tokens, scan staking yields from DeFiLlama
                result = await self._scan_token_staking(token_upper)

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.error("Staking rewards lookup failed for %s: %s", token, exc)
            return {
                "token": token_upper,
                "error": str(exc),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    async def _scan_token_staking(self, token: str) -> dict[str, Any]:
        """Scan staking options for non-ETH tokens."""
        dl = self._analytics.get_defillama()
        if not dl:
            return {"token": token, "options": [], "error": "DeFiLlama unavailable"}

        # Search for staking pools with this token
        pools = await dl.get_yield_pools(min_tvl=1_000_000, min_apy=0.5)

        matching = [
            p
            for p in pools
            if token.lower() in p.symbol.lower()
            and p.protocol.lower()
            in [
                "lido",
                "rocket-pool",
                "jito",
                "marinade",
                "stride",
                "pstake",
                "ankr",
                "stader",
                "binance-staking",
                "native-staking",
                "cosmos-staking",
            ]
        ]

        # Also include lending protocols (they offer "staking-like" yields)
        lending = [
            p
            for p in pools
            if token.lower() in p.symbol.lower()
            and p.protocol.lower() in ["aave-v3", "compound-v3", "morpho", "spark"]
        ]

        all_options = matching + lending[:5]  # Limit lending options

        # Sort by APY
        all_options.sort(key=lambda p: p.apy, reverse=True)

        return {
            "token": token,
            "options": [
                {
                    "protocol": p.protocol,
                    "chain": p.chain,
                    "symbol": p.symbol,
                    "apy": p.apy,
                    "apy_base": p.apy_base,
                    "apy_reward": p.apy_reward,
                    "tvl_usd": p.tvl_usd,
                    "il_risk": p.il_risk,
                    "stable_pool": p.stable_pool,
                }
                for p in all_options[:15]
            ],
            "best_option": {
                "protocol": all_options[0].protocol,
                "chain": all_options[0].chain,
                "apy": all_options[0].apy,
            }
            if all_options
            else None,
            "comparison_count": len(all_options),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ═══════════════════════════════════════════════════════════════════
    # GET DEFI POSITIONS
    # ═══════════════════════════════════════════════════════════════════

    async def get_defi_positions(self, wallet: str) -> dict[str, Any]:
        """Get current DeFi positions for a wallet across protocols.

        Queries DeFiLlama's portfolio endpoint for position data across
        lending, borrowing, staking, LP, and vault positions.

        Args:
            wallet: Wallet address (EVM or Solana).

        Returns:
            Dict with positions, total value, yield summary, and health.
        """
        cache_key = f"positions:{wallet.lower()}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            client = await self._get_client()

            # Use DeFiLlama's portfolio endpoint
            resp = await client.get(
                f"https://api.llama.fi/portfolio/{wallet}",
                timeout=20,
            )

            if resp.status_code != 200:
                # Try alternative: return empty with guidance
                return {
                    "wallet": wallet,
                    "positions": [],
                    "total_value_usd": 0,
                    "error": f"Portfolio API returned {resp.status_code}. Ensure address is correct.",
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            data = resp.json()

            positions: list[dict[str, Any]] = []
            total_value = 0.0
            total_rewards = 0.0
            health_factors: list[float] = []

            for protocol_data in data.get("protocols", []):
                protocol = protocol_data.get("protocol", "unknown")
                chain = protocol_data.get("chain", "unknown")

                for pos in protocol_data.get("positions", []):
                    balance_usd = float(pos.get("value", 0) or 0)
                    total_value += balance_usd

                    health = float(pos.get("healthFactor", 0) or 0)
                    if health > 0:
                        health_factors.append(health)

                    rewards = float(pos.get("rewardUsd", 0) or 0)
                    total_rewards += rewards

                    positions.append(
                        {
                            "protocol": protocol,
                            "chain": chain,
                            "position_type": pos.get("type", "unknown"),
                            "symbol": pos.get("symbol", ""),
                            "balance": float(pos.get("balance", 0) or 0),
                            "balance_usd": balance_usd,
                            "apy": float(pos.get("apy", 0) or 0),
                            "rewards_pending": rewards,
                            "health_factor": health,
                            "pool_id": pos.get("pool", ""),
                        }
                    )

            # Sort by value
            positions.sort(key=lambda p: p["balance_usd"], reverse=True)

            result = {
                "wallet": wallet,
                "positions": positions,
                "total_value_usd": round(total_value, 2),
                "total_rewards_pending_usd": round(total_rewards, 2),
                "position_count": len(positions),
                "protocol_count": len({p["protocol"] for p in positions}),
                "chain_count": len({p["chain"] for p in positions}),
                "health": {
                    "min_health_factor": min(health_factors) if health_factors else 0,
                    "avg_health_factor": round(sum(health_factors) / len(health_factors), 2)
                    if health_factors
                    else 0,
                    "at_risk": any(h < 1.5 for h in health_factors),
                },
                "yield_summary": {
                    "weighted_apy": round(
                        sum(p["balance_usd"] * p["apy"] / 100 for p in positions)
                        / total_value
                        * 100,
                        2,
                    )
                    if total_value > 0
                    else 0,
                    "total_annual_yield_usd": round(
                        sum(p["balance_usd"] * p["apy"] / 100 for p in positions), 2
                    ),
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.error("DeFi positions lookup failed for %s: %s", wallet, exc)
            return {
                "wallet": wallet,
                "positions": [],
                "total_value_usd": 0,
                "error": str(exc),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    # ═══════════════════════════════════════════════════════════════════
    # BONUS: FARMING STRATEGY & REBALANCE
    # ═══════════════════════════════════════════════════════════════════

    async def build_farming_strategy(
        self,
        capital_usd: float,
        risk_tolerance: str = "medium",
        chains: list[str] | None = None,
        prefer_stable: bool = False,
    ) -> dict[str, Any]:
        """Build a yield farming strategy given capital and risk tolerance.

        Allocates capital across multiple protocols and chains to
        maximize risk-adjusted yield while maintaining diversification.

        Args:
            capital_usd: Total capital to deploy.
            risk_tolerance: "low", "medium", "high".
            chains: Preferred chains (None = all).
            prefer_stable: Prefer stablecoin yields.

        Returns:
            Dict with allocations, expected yield, and rationale.
        """
        return await self._optimizer.build_farming_strategy(
            capital_usd=capital_usd,
            risk_tolerance=risk_tolerance,
            chains=chains,
            prefer_stable=prefer_stable,
        )

    async def recommend_rebalance(
        self,
        current_positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate rebalancing recommendations for current DeFi positions.

        Args:
            current_positions: List of dicts with protocol, pool_id, symbol,
                chain, amount_usd, current_apy.

        Returns:
            Dict with rebalance recommendations and summary.
        """
        try:
            recs = await self._optimizer.recommend_rebalance(current_positions)

            return {
                "recommendations": [
                    {
                        "action": r.action,
                        "protocol_from": r.protocol_from,
                        "protocol_to": r.protocol_to,
                        "symbol": r.symbol,
                        "amount_pct": r.amount_pct,
                        "current_apy": r.current_apy,
                        "target_apy": r.target_apy,
                        "apy_improvement": round(r.target_apy - r.current_apy, 2),
                        "reasoning": r.reasoning,
                    }
                    for r in recs
                ],
                "total_positions_reviewed": len(current_positions),
                "positions_with_better_options": len(recs),
                "timestamp": datetime.now(UTC).isoformat(),
            }

        except Exception as exc:
            logger.error("Rebalance recommendation failed: %s", exc)
            return {
                "recommendations": [],
                "error": str(exc),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    # ═══════════════════════════════════════════════════════════════════
    # ANALYTICS ENRICHMENT
    # ═══════════════════════════════════════════════════════════════════

    async def get_onchain_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Get on-chain fundamentals (SOPR, MVRV, NVT) via analytics chain.

        Tries Glassnode → CoinGecko fallback.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            Dict with fundamental metrics and source attribution.
        """
        fundamentals = await self._analytics.get_fundamentals(symbol)
        smart_money = await self._analytics.get_smart_money(symbol)

        return {
            "symbol": symbol.upper(),
            "fundamentals": {
                "sopr": fundamentals.sopr,
                "mvrv": fundamentals.mvrv,
                "nvt_ratio": fundamentals.nvt_ratio,
                "nvt_signal": fundamentals.nvt_signal,
                "realized_cap": fundamentals.realized_cap,
                "market_cap": fundamentals.market_cap,
                "active_addresses": fundamentals.active_addresses,
                "tx_count_24h": fundamentals.tx_count_24h,
                "tx_volume_usd": fundamentals.tx_volume_usd,
            },
            "smart_money": {
                "direction": smart_money.smart_money_direction,
                "whale_balance_change_24h": smart_money.whale_balance_change_24h,
                "top_holder_concentration": smart_money.top_holder_concentration,
                "exchange_whale_ratio": smart_money.exchange_whale_ratio,
            },
            "sources": {
                "fundamentals": fundamentals.source or "unavailable",
                "smart_money": smart_money.source or "unavailable",
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def get_exchange_flow_pro(self, symbol: str) -> dict[str, Any]:
        """Get professional exchange flow data via analytics chain.

        Tries Glassnode → CryptoQuant → CoinGecko fallback.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            Dict with exchange flow data and source attribution.
        """
        flows = await self._analytics.get_exchange_flows(symbol)

        signal = "neutral"
        if flows.net_flow_24h < -1_000_000:
            signal = "bullish"
        elif flows.net_flow_24h > 1_000_000:
            signal = "bearish"

        return {
            "symbol": symbol.upper(),
            "exchange_flows": {
                "inflow_24h": flows.inflow_24h,
                "outflow_24h": flows.outflow_24h,
                "net_flow_24h": flows.net_flow_24h,
                "exchange_reserves": flows.exchange_reserves,
                "reserve_change_pct": flows.reserve_change_pct,
                "funding_rate": flows.funding_rate,
                "whale_inflow_count": flows.whale_inflow_count,
                "whale_outflow_count": flows.whale_outflow_count,
            },
            "signal": signal,
            "source": flows.source or "unavailable",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ═══════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _interpret_risk(risk: RiskScore) -> str:
        """Generate human-readable risk interpretation."""
        grade = risk.risk_grade
        factors = risk.risk_factors

        if grade in ("A+", "A"):
            base = "Low risk — well-established protocol with strong security"
        elif grade in ("B+", "B"):
            base = "Moderate risk — reputable protocol with minor concerns"
        elif grade in ("C+", "C"):
            base = "Elevated risk — exercise caution, monitor closely"
        elif grade == "D":
            base = "High risk — significant concerns, not recommended for large positions"
        else:
            base = "Very high risk — avoid unless you understand the risks"

        if factors:
            base += f". Concerns: {', '.join(factors)}"

        return base

    @staticmethod
    def _suggest_il_strategy(il_result: dict) -> str:
        """Suggest a strategy based on IL analysis."""
        il_risk = il_result.get("il_risk", "none")
        break_even = il_result.get("break_even_apy", 0)

        if il_risk == "none":
            return "Safe to provide liquidity — negligible IL expected"
        elif il_risk == "low":
            return f"Acceptable IL risk. Ensure pool APY > {break_even:.1f}% to compensate"
        elif il_risk == "medium":
            return (
                f"Moderate IL risk. Consider: (1) Stable pairs, (2) Single-sided staking, "
                f"(3) Concentrated liquidity with tight ranges. Need >{break_even:.1f}% APY"
            )
        else:
            return (
                f"High IL risk! Consider alternatives: (1) Lending (Aave/Compound), "
                f"(2) Liquid staking (Lido), (3) Single-sided yield vaults. "
                f"Would need >{break_even:.1f}% APY to break even"
            )
