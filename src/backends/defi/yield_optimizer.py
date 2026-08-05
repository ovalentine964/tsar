"""
TSAR — DeFi Yield Optimization Engine.

Scans yield opportunities across DeFi protocols, computes risk-adjusted
scores, recommends rebalancing, and optimises liquid staking strategies.

Protocols covered:
  - Lending: Aave (v2/v3), Compound (v2/v3)
  - Liquid Staking: Lido (stETH), Rocket Pool (rETH), Frax (sfrxETH)
  - DEX LP: Uniswap (v2/v3), Curve, Balancer
  - Yield Aggregators: Yearn, Convex, Beefy

All data sourced from DeFiLlama (free) with optional premium enrichment.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import httpx

from .analytics_providers import (
    DeFiLlamaClient,
    FallbackChain,
    YieldPool,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RiskScore:
    """Composite risk assessment for a DeFi protocol or pool.

    Attributes:
        protocol_risk: Smart contract / protocol risk (0-1, lower = safer).
        tvl_risk: TVL stability risk (0-1).
        il_risk: Impermanent loss risk (0-1).
        audit_risk: Audit coverage risk (0-1, lower = better audited).
        composite: Weighted composite risk score (0-1).
        risk_grade: Letter grade (A+ to F).
        risk_factors: List of human-readable risk factors.
    """

    protocol_risk: float = 0.0
    tvl_risk: float = 0.0
    il_risk: float = 0.0
    audit_risk: float = 0.0
    composite: float = 0.0
    risk_grade: str = "C"
    risk_factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class YieldOpportunity:
    """A yield opportunity with risk-adjusted scoring.

    Attributes:
        protocol: Protocol name.
        chain: Blockchain.
        pool_id: Pool identifier.
        symbol: Token/pair symbol.
        apy: Annual Percentage Yield (%).
        apy_base: Base APY from lending/trading fees.
        apy_reward: Reward APY from token incentives.
        tvl_usd: Total Value Locked in USD.
        risk_score: Risk assessment.
        risk_adjusted_apy: APY adjusted for risk.
        il_risk: Impermanent loss risk level.
        stable_pool: Whether this is a stablecoin pool.
        strategy_type: "lending", "staking", "lp", "vault", "farming".
        recommendation: "strong_buy", "buy", "hold", "caution", "avoid".
        reasoning: Why this recommendation was made.
    """

    protocol: str
    chain: str
    pool_id: str
    symbol: str
    apy: float = 0.0
    apy_base: float = 0.0
    apy_reward: float = 0.0
    tvl_usd: float = 0.0
    risk_score: RiskScore = field(default_factory=RiskScore)
    risk_adjusted_apy: float = 0.0
    il_risk: str = "none"
    stable_pool: bool = False
    strategy_type: str = "lending"
    recommendation: str = "hold"
    reasoning: str = ""


@dataclass(frozen=True)
class RebalanceRecommendation:
    """A rebalancing recommendation for DeFi positions.

    Attributes:
        action: "enter", "exit", "increase", "decrease", "rotate".
        protocol_from: Source protocol (for rotate/exit).
        protocol_to: Target protocol (for rotate/enter).
        pool_from: Source pool.
        pool_to: Target pool.
        symbol: Asset symbol.
        amount_pct: Percentage of position to move.
        current_apy: Current APY.
        target_apy: Expected APY after rebalance.
        risk_change: Change in risk score (negative = safer).
        reasoning: Why this rebalance is recommended.
    """

    action: str
    protocol_from: str = ""
    protocol_to: str = ""
    pool_from: str = ""
    pool_to: str = ""
    symbol: str = ""
    amount_pct: float = 100.0
    current_apy: float = 0.0
    target_apy: float = 0.0
    risk_change: float = 0.0
    reasoning: str = ""


@dataclass(frozen=True)
class LiquidStakingOption:
    """A liquid staking option with comparison data.

    Attributes:
        protocol: Staking protocol name.
        token: Liquid staking token (stETH, rETH, etc.).
        chain: Blockchain.
        apy: Staking APY (%).
        tvl_usd: Total staked value.
        fee_pct: Protocol fee (% of rewards).
        liquidity_score: How liquid the LST token is (0-1).
        peg_stability: How stable the peg to ETH is (0-1).
        risk_score: Risk assessment.
        composite_score: Overall attractiveness score (0-1).
        recommendation: "best", "good", "acceptable", "avoid".
    """

    protocol: str
    token: str
    chain: str
    apy: float = 0.0
    tvl_usd: float = 0.0
    fee_pct: float = 10.0
    liquidity_score: float = 0.0
    peg_stability: float = 0.0
    risk_score: RiskScore = field(default_factory=RiskScore)
    composite_score: float = 0.0
    recommendation: str = "acceptable"


# ═══════════════════════════════════════════════════════════════════════
# PROTOCOL RISK PROFILES
# ═══════════════════════════════════════════════════════════════════════

# Pre-computed risk profiles for major protocols
# Based on: audit history, time in production, TVL stability, incident history
_PROTOCOL_RISK_PROFILES: dict[str, dict[str, Any]] = {
    # ── Lending ──────────────────────────────────────────────────────
    "aave-v3": {
        "protocol_risk": 0.08,
        "audit_score": 0.05,
        "audits": 12,
        "years_live": 4,
        "incidents": 0,
        "risk_factors": [],
        "category": "lending",
    },
    "aave-v2": {
        "protocol_risk": 0.10,
        "audit_score": 0.05,
        "audits": 10,
        "years_live": 5,
        "incidents": 0,
        "risk_factors": ["legacy_version"],
        "category": "lending",
    },
    "compound-v3": {
        "protocol_risk": 0.10,
        "audit_score": 0.08,
        "audits": 8,
        "years_live": 2,
        "incidents": 0,
        "risk_factors": [],
        "category": "lending",
    },
    "compound-v2": {
        "protocol_risk": 0.12,
        "audit_score": 0.08,
        "audits": 6,
        "years_live": 5,
        "incidents": 1,
        "risk_factors": ["legacy_version"],
        "category": "lending",
    },
    "morpho": {
        "protocol_risk": 0.15,
        "audit_score": 0.12,
        "audits": 5,
        "years_live": 2,
        "incidents": 0,
        "risk_factors": ["newer_protocol"],
        "category": "lending",
    },
    "spark": {
        "protocol_risk": 0.12,
        "audit_score": 0.10,
        "audits": 6,
        "years_live": 2,
        "incidents": 0,
        "risk_factors": ["maker_ecosystem_dependency"],
        "category": "lending",
    },
    # ── Liquid Staking ──────────────────────────────────────────────
    "lido": {
        "protocol_risk": 0.05,
        "audit_score": 0.03,
        "audits": 15,
        "years_live": 4,
        "incidents": 0,
        "risk_factors": ["validator_centrality"],
        "category": "staking",
    },
    "rocket-pool": {
        "protocol_risk": 0.08,
        "audit_score": 0.05,
        "audits": 8,
        "years_live": 3,
        "incidents": 0,
        "risk_factors": [],
        "category": "staking",
    },
    "frax-ether": {
        "protocol_risk": 0.15,
        "audit_score": 0.12,
        "audits": 4,
        "years_live": 2,
        "incidents": 0,
        "risk_factors": ["newer_protocol", "algo_stablecoin_risk"],
        "category": "staking",
    },
    "coinbase-wrapped-staked-eth": {
        "protocol_risk": 0.10,
        "audit_score": 0.08,
        "audits": 5,
        "years_live": 2,
        "incidents": 0,
        "risk_factors": ["centralized_custody"],
        "category": "staking",
    },
    # ── DEX / LP ────────────────────────────────────────────────────
    "uniswap-v3": {
        "protocol_risk": 0.08,
        "audit_score": 0.05,
        "audits": 10,
        "years_live": 4,
        "incidents": 0,
        "risk_factors": ["concentrated_liq_il"],
        "category": "dex",
    },
    "uniswap-v2": {
        "protocol_risk": 0.06,
        "audit_score": 0.05,
        "audits": 8,
        "years_live": 5,
        "incidents": 0,
        "risk_factors": ["legacy_version"],
        "category": "dex",
    },
    "curve-dex": {
        "protocol_risk": 0.10,
        "audit_score": 0.08,
        "audits": 7,
        "years_live": 5,
        "incidents": 1,
        "risk_factors": ["complex_math"],
        "category": "dex",
    },
    "balancer-v2": {
        "protocol_risk": 0.12,
        "audit_score": 0.10,
        "audits": 6,
        "years_live": 3,
        "incidents": 0,
        "risk_factors": ["complex_pools"],
        "category": "dex",
    },
    # ── Yield Aggregators ───────────────────────────────────────────
    "yearn-finance": {
        "protocol_risk": 0.15,
        "audit_score": 0.10,
        "audits": 8,
        "years_live": 4,
        "incidents": 1,
        "risk_factors": ["strategy_complexity"],
        "category": "vault",
    },
    "convex-finance": {
        "protocol_risk": 0.12,
        "audit_score": 0.10,
        "audits": 5,
        "years_live": 3,
        "incidents": 0,
        "risk_factors": ["curve_dependency"],
        "category": "vault",
    },
    "beefy": {
        "protocol_risk": 0.18,
        "audit_score": 0.15,
        "audits": 4,
        "years_live": 3,
        "incidents": 0,
        "risk_factors": ["multi_chain_complexity"],
        "category": "vault",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# AUDIT DATABASE (simplified — production would use DeFiSafety scores)
# ═══════════════════════════════════════════════════════════════════════

_KNOWN_AUDIT_FIRMS: dict[str, float] = {
    "trail_of_bits": 0.95,
    "openzeppelin": 0.95,
    "consensys_diligence": 0.90,
    "chainsecurity": 0.90,
    "certora": 0.88,
    "peckshield": 0.80,
    "quantstamp": 0.80,
    "slowmist": 0.75,
    "hacken": 0.75,
    "mixbytes": 0.70,
}


# ═══════════════════════════════════════════════════════════════════════
# YIELD OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════


class YieldOptimizer:
    """DeFi yield optimization engine.

    Scans yield opportunities across protocols, computes risk-adjusted
    scores, generates rebalancing recommendations, and optimises
    liquid staking strategies.

    Uses DeFiLlama (free) for yield data and protocol risk profiles
    for risk scoring. Optionally enriches with Glassnode/CryptoQuant
    data via FallbackChain.

    Usage:
        optimizer = YieldOptimizer()
        opportunities = await optimizer.scan_yields(chain="Ethereum", min_tvl=1_000_000)
        risk = await optimizer.assess_protocol_risk("aave-v3")
        il = optimizer.calculate_impermanent_loss("ETH/USDC", 10000, 30)
        staking = await optimizer.compare_liquid_staking()
        rebalance = await optimizer.recommend_rebalance(positions)
    """

    def __init__(
        self,
        analytics: FallbackChain | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._analytics = analytics
        self._config = config or {}
        self._defillama: DeFiLlamaClient | None = None
        self._http_client: httpx.AsyncClient | None = None

    async def _get_defillama(self) -> DeFiLlamaClient:
        """Get DeFiLlama client from analytics chain or create standalone."""
        if self._defillama:
            return self._defillama

        if self._analytics:
            dl = self._analytics.get_defillama()
            if dl:
                self._defillama = dl
                return dl

        self._defillama = DeFiLlamaClient(config=self._config)
        return self._defillama

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=15.0)
        return self._http_client

    async def close(self) -> None:
        """Close all clients."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ═══════════════════════════════════════════════════════════════════
    # YIELD SCANNING
    # ═══════════════════════════════════════════════════════════════════

    async def scan_yields(
        self,
        chain: str | None = None,
        min_tvl: float = 1_000_000,
        min_apy: float = 1.0,
        max_apy: float = 200.0,
        stable_only: bool = False,
        strategy_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[YieldOpportunity]:
        """Scan DeFi yield opportunities with risk scoring.

        Args:
            chain: Filter by chain (e.g. "Ethereum", "Arbitrum", "Base").
            min_tvl: Minimum TVL in USD.
            min_apy: Minimum APY (%).
            max_apy: Maximum APY (%) — filters suspiciously high yields.
            stable_only: Only stablecoin pools.
            strategy_types: Filter by type ("lending", "staking", "lp", "vault").
            limit: Maximum results.

        Returns:
            List of YieldOpportunity sorted by risk-adjusted APY descending.
        """
        dl = await self._get_defillama()
        pools = await dl.get_yield_pools(
            chain=chain,
            min_tvl=min_tvl,
            min_apy=min_apy,
            max_apy=max_apy,
            stable_only=stable_only,
        )

        # Classify strategy types
        opportunities: list[YieldOpportunity] = []

        for pool in pools[:200]:  # Process top 200 pools
            strategy = self._classify_strategy(pool)

            if strategy_types and strategy not in strategy_types:
                continue

            # Compute risk
            risk = await self._compute_pool_risk(pool)

            # Risk-adjusted APY: APY × (1 - risk_composite)
            risk_adj = pool.apy * (1.0 - risk.composite * 0.5)

            # Generate recommendation
            rec, reasoning = self._generate_recommendation(pool, risk, risk_adj)

            opportunities.append(
                YieldOpportunity(
                    protocol=pool.protocol,
                    chain=pool.chain,
                    pool_id=pool.pool_id,
                    symbol=pool.symbol,
                    apy=pool.apy,
                    apy_base=pool.apy_base,
                    apy_reward=pool.apy_reward,
                    tvl_usd=pool.tvl_usd,
                    risk_score=risk,
                    risk_adjusted_apy=round(risk_adj, 2),
                    il_risk=pool.il_risk,
                    stable_pool=pool.stable_pool,
                    strategy_type=strategy,
                    recommendation=rec,
                    reasoning=reasoning,
                )
            )

        # Sort by risk-adjusted APY
        opportunities.sort(key=lambda x: x.risk_adjusted_apy, reverse=True)
        return opportunities[:limit]

    # ═══════════════════════════════════════════════════════════════════
    # PROTOCOL RISK ASSESSMENT
    # ═══════════════════════════════════════════════════════════════════

    async def assess_protocol_risk(self, protocol: str) -> RiskScore:
        """Assess the risk of a DeFi protocol.

        Evaluates: smart contract risk, TVL stability, audit coverage,
        incident history, and time in production.

        Args:
            protocol: Protocol slug (e.g. "aave-v3", "lido", "uniswap-v3").

        Returns:
            RiskScore with component scores and composite grade.
        """
        dl = await self._get_defillama()

        # Get protocol profile
        profile = _PROTOCOL_RISK_PROFILES.get(protocol.lower(), {})

        # Get TVL data for stability assessment
        tvl_data = await dl.get_protocol_tvl(protocol)

        # Component scores
        protocol_risk = profile.get("protocol_risk", 0.5)  # Default: medium risk
        audit_risk = profile.get("audit_score", 0.5)

        # TVL risk: based on TVL size and stability
        tvl_risk = 0.5
        if tvl_data:
            tvl = tvl_data.tvl_usd
            if tvl > 10_000_000_000:  # >$10B
                tvl_risk = 0.05
            elif tvl > 1_000_000_000:  # >$1B
                tvl_risk = 0.10
            elif tvl > 100_000_000:  # >$100M
                tvl_risk = 0.20
            elif tvl > 10_000_000:  # >$10M
                tvl_risk = 0.35
            else:
                tvl_risk = 0.60

            # Penalize rapid TVL decline
            if tvl_data.tvl_change_7d < -20:
                tvl_risk = min(1.0, tvl_risk + 0.3)
            elif tvl_data.tvl_change_7d < -10:
                tvl_risk = min(1.0, tvl_risk + 0.15)

        # IL risk (for LP protocols)
        il_risk = 0.0
        if profile.get("category") == "dex":
            il_risk = 0.3  # Base IL risk for DEX pools

        # Composite: weighted average
        weights = {"protocol": 0.30, "tvl": 0.25, "audit": 0.25, "il": 0.20}
        composite = (
            protocol_risk * weights["protocol"]
            + tvl_risk * weights["tvl"]
            + audit_risk * weights["audit"]
            + il_risk * weights["il"]
        )

        # Letter grade
        grade = self._risk_grade(composite)

        # Risk factors
        factors = list(profile.get("risk_factors", []))
        if tvl_data and tvl_data.tvl_change_7d < -10:
            factors.append("tvl_declining")
        if tvl_data and tvl_data.tvl_usd < 10_000_000:
            factors.append("low_tvl")
        if not profile:
            factors.append("unverified_protocol")

        return RiskScore(
            protocol_risk=round(protocol_risk, 4),
            tvl_risk=round(tvl_risk, 4),
            il_risk=round(il_risk, 4),
            audit_risk=round(audit_risk, 4),
            composite=round(composite, 4),
            risk_grade=grade,
            risk_factors=tuple(factors),
        )

    # ═══════════════════════════════════════════════════════════════════
    # IMPERMANENT LOSS CALCULATOR
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def calculate_impermanent_loss(
        pair: str,
        amount_usd: float,
        duration_days: int,
        price_change_pct: float = 0.0,
        volatility: float = 0.5,
    ) -> dict[str, Any]:
        """Calculate expected impermanent loss for a liquidity position.

        Uses the standard IL formula for constant-product AMMs:
          IL = 2 * sqrt(price_ratio) / (1 + price_ratio) - 1

        Also factors in time-weighted expected IL based on volatility.

        Args:
            pair: Trading pair (e.g. "ETH/USDC", "WBTC/ETH").
            amount_usd: Position size in USD.
            duration_days: Expected holding period in days.
            price_change_pct: Expected price change (%) of volatile asset.
            volatility: Annualized volatility of the volatile asset (default 0.5 = 50%).

        Returns:
            Dict with IL analysis including expected_loss_usd, il_pct,
            break_even_apy, and risk assessment.
        """
        # Parse pair to determine if it's volatile/volatile or volatile/stable
        parts = pair.upper().split("/")
        stablecoins = {"USDC", "USDT", "DAI", "FRAX", "TUSD", "BUSD", "LUSD", "GUSD"}
        is_stable_pair = all(p in stablecoins for p in parts)

        if is_stable_pair:
            # Stable pairs have negligible IL
            return {
                "pair": pair,
                "amount_usd": amount_usd,
                "duration_days": duration_days,
                "il_pct": 0.0,
                "il_usd": 0.0,
                "expected_il_pct": 0.0,
                "expected_il_usd": 0.0,
                "break_even_apy": 0.0,
                "il_risk": "none",
                "note": "Stablecoin pair — minimal impermanent loss risk",
            }

        # Calculate IL for given price change
        if price_change_pct == 0:
            # Use volatility-based expected IL
            # Expected IL ≈ volatility * sqrt(time_years) * 0.5 (approximation)
            time_years = duration_days / 365.0
            expected_price_ratio = math.exp(volatility * math.sqrt(time_years) * 0.5)
        else:
            expected_price_ratio = 1.0 + (price_change_pct / 100.0)

        # Standard IL formula
        # IL = 2*sqrt(r)/(1+r) - 1, where r = price ratio
        r = expected_price_ratio
        il_pct = (2 * math.sqrt(r) / (1 + r)) - 1.0
        il_pct = abs(il_pct) * 100  # Convert to percentage

        # Also calculate worst-case IL (±2x expected move)
        r_worst = expected_price_ratio**2
        il_worst_pct = abs((2 * math.sqrt(r_worst) / (1 + r_worst)) - 1.0) * 100

        il_usd = amount_usd * (il_pct / 100)
        il_worst_usd = amount_usd * (il_worst_pct / 100)

        # Break-even APY: minimum yield needed to compensate for IL
        break_even_apy = (il_pct / duration_days) * 365 if duration_days > 0 else 0

        # Risk level
        if il_pct < 0.5:
            il_risk = "none"
        elif il_pct < 2:
            il_risk = "low"
        elif il_pct < 5:
            il_risk = "medium"
        else:
            il_risk = "high"

        return {
            "pair": pair,
            "amount_usd": amount_usd,
            "duration_days": duration_days,
            "price_change_pct": price_change_pct,
            "volatility": volatility,
            "il_pct": round(il_pct, 4),
            "il_usd": round(il_usd, 2),
            "il_worst_case_pct": round(il_worst_pct, 4),
            "il_worst_case_usd": round(il_worst_usd, 2),
            "expected_il_pct": round(il_pct, 4),
            "expected_il_usd": round(il_usd, 2),
            "break_even_apy": round(break_even_apy, 2),
            "il_risk": il_risk,
            "note": (
                f"With {volatility * 100:.0f}% annualized volatility over {duration_days} days, "
                f"expected IL is ~{il_pct:.2f}% (${il_usd:,.0f}). "
                f"Need >{break_even_apy:.1f}% APY to break even."
            ),
        }

    # ═══════════════════════════════════════════════════════════════════
    # LIQUID STAKING COMPARISON
    # ═══════════════════════════════════════════════════════════════════

    async def compare_liquid_staking(
        self,
        chain: str = "Ethereum",
        amount_usd: float = 0,
    ) -> list[LiquidStakingOption]:
        """Compare liquid staking options across protocols.

        Evaluates: APY, TVL, liquidity, peg stability, fees, and risk.

        Args:
            chain: Blockchain (default Ethereum).
            amount_usd: Optional position size for liquidity assessment.

        Returns:
            List of LiquidStakingOption sorted by composite score.
        """
        dl = await self._get_defillama()

        # Known liquid staking protocols
        ls_protocols = {
            "lido": {"token": "stETH", "fee": 10.0},
            "rocket-pool": {"token": "rETH", "fee": 14.0},
            "frax-ether": {"token": "sfrxETH", "fee": 10.0},
            "coinbase-wrapped-staked-eth": {"token": "cbETH", "fee": 25.0},
            "ether-fi": {"token": "eETH", "fee": 10.0},
            "mantle-staked-ether": {"token": "mETH", "fee": 10.0},
        }

        options: list[LiquidStakingOption] = []

        for protocol, meta in ls_protocols.items():
            # Get yield pool data
            pools = await dl.get_yield_pools(chain=chain, min_tvl=1_000_000)
            matching = [
                p
                for p in pools
                if protocol in p.protocol.lower() or meta["token"].lower() in p.symbol.lower()
            ]

            if not matching:
                continue

            pool = matching[0]

            # Get TVL data
            tvl_data = await dl.get_protocol_tvl(protocol)

            # Risk assessment
            risk = await self.assess_protocol_risk(protocol)

            # Liquidity score based on TVL
            tvl = tvl_data.tvl_usd if tvl_data else pool.tvl_usd
            if tvl > 10_000_000_000:
                liquidity = 0.95
            elif tvl > 1_000_000_000:
                liquidity = 0.80
            elif tvl > 100_000_000:
                liquidity = 0.60
            else:
                liquidity = 0.40

            # Peg stability (hardcoded knowledge — production would track on-chain)
            peg_scores = {
                "stETH": 0.90,
                "rETH": 0.95,
                "sfrxETH": 0.80,
                "cbETH": 0.85,
                "eETH": 0.75,
                "mETH": 0.70,
            }
            peg = peg_scores.get(meta["token"], 0.70)

            # Composite score: weighted combination
            composite = (
                pool.apy / 100 * 0.30  # APY contribution (normalized)
                + liquidity * 0.25
                + peg * 0.20
                + (1.0 - risk.composite) * 0.15
                + (1.0 - meta["fee"] / 100) * 0.10  # Lower fee = better
            )

            # Recommendation
            if composite > 0.75:
                rec = "best"
            elif composite > 0.60:
                rec = "good"
            elif composite > 0.45:
                rec = "acceptable"
            else:
                rec = "avoid"

            options.append(
                LiquidStakingOption(
                    protocol=protocol,
                    token=meta["token"],
                    chain=chain,
                    apy=pool.apy,
                    tvl_usd=tvl,
                    fee_pct=meta["fee"],
                    liquidity_score=round(liquidity, 2),
                    peg_stability=round(peg, 2),
                    risk_score=risk,
                    composite_score=round(composite, 4),
                    recommendation=rec,
                )
            )

        options.sort(key=lambda x: x.composite_score, reverse=True)
        return options

    # ═══════════════════════════════════════════════════════════════════
    # YIELD FARMING STRATEGY BUILDER
    # ═══════════════════════════════════════════════════════════════════

    async def build_farming_strategy(
        self,
        capital_usd: float,
        risk_tolerance: str = "medium",
        chains: list[str] | None = None,
        prefer_stable: bool = False,
        min_apy: float = 3.0,
    ) -> dict[str, Any]:
        """Build a yield farming strategy given capital and risk tolerance.

        Allocates capital across multiple protocols and chains to
        maximize risk-adjusted yield while maintaining diversification.

        Args:
            capital_usd: Total capital to deploy in USD.
            risk_tolerance: "low", "medium", "high".
            chains: Preferred chains (None = all).
            prefer_stable: Prefer stablecoin yields.
            min_apy: Minimum acceptable APY.

        Returns:
            Dict with allocations, expected yield, risk metrics, and rationale.
        """
        # Risk tolerance parameters
        risk_params = {
            "low": {"max_apy": 20, "max_single_pct": 30, "min_protocols": 3, "stable_bias": 0.7},
            "medium": {"max_apy": 50, "max_single_pct": 40, "min_protocols": 2, "stable_bias": 0.4},
            "high": {"max_apy": 200, "max_single_pct": 50, "min_protocols": 1, "stable_bias": 0.2},
        }
        params = risk_params.get(risk_tolerance, risk_params["medium"])

        # Scan yields across chains
        all_opportunities: list[YieldOpportunity] = []
        target_chains = chains or ["Ethereum", "Arbitrum", "Base", "Optimism", "Polygon"]

        for chain in target_chains:
            opps = await self.scan_yields(
                chain=chain,
                min_tvl=5_000_000,
                min_apy=min_apy,
                max_apy=params["max_apy"],
                stable_only=prefer_stable,
                limit=20,
            )
            all_opportunities.extend(opps)

        if not all_opportunities:
            return {
                "capital_usd": capital_usd,
                "allocations": [],
                "expected_annual_yield_usd": 0,
                "weighted_apy": 0,
                "risk_tolerance": risk_tolerance,
                "error": "No suitable yield opportunities found",
            }

        # Filter by risk tolerance
        if risk_tolerance == "low":
            viable = [o for o in all_opportunities if o.risk_score.composite < 0.25]
        elif risk_tolerance == "medium":
            viable = [o for o in all_opportunities if o.risk_score.composite < 0.45]
        else:
            viable = all_opportunities

        if not viable:
            viable = all_opportunities[:5]  # Take best available

        # Diversify: max allocation per protocol
        max_single = params["max_single_pct"] / 100
        allocations: list[dict[str, Any]] = []
        remaining = capital_usd
        used_protocols: set[str] = set()

        # Prioritize by risk-adjusted APY, diversify across protocols
        for opp in viable:
            if remaining < 100:  # Min $100 per position
                break
            if opp.protocol in used_protocols and len(used_protocols) < params["min_protocols"]:
                continue

            alloc_pct = min(max_single, remaining / capital_usd)
            alloc_usd = capital_usd * alloc_pct

            allocations.append(
                {
                    "protocol": opp.protocol,
                    "chain": opp.chain,
                    "symbol": opp.symbol,
                    "pool_id": opp.pool_id,
                    "strategy_type": opp.strategy_type,
                    "allocation_pct": round(alloc_pct * 100, 1),
                    "allocation_usd": round(alloc_usd, 2),
                    "apy": opp.apy,
                    "risk_adjusted_apy": opp.risk_adjusted_apy,
                    "risk_grade": opp.risk_score.risk_grade,
                    "il_risk": opp.il_risk,
                    "recommendation": opp.recommendation,
                }
            )

            remaining -= alloc_usd
            used_protocols.add(opp.protocol)

        # Calculate expected yield
        total_yield = sum(a["allocation_usd"] * a["apy"] / 100 for a in allocations)
        weighted_apy = (total_yield / capital_usd * 100) if capital_usd > 0 else 0

        # Risk summary
        risk_grades = [a["risk_grade"] for a in allocations]
        avg_risk = (
            sum(
                {"A+": 1, "A": 2, "B+": 3, "B": 4, "C+": 5, "C": 6, "D": 7, "F": 8}.get(g, 5)
                for g in risk_grades
            )
            / len(risk_grades)
            if risk_grades
            else 5
        )

        return {
            "capital_usd": capital_usd,
            "allocations": allocations,
            "expected_annual_yield_usd": round(total_yield, 2),
            "weighted_apy": round(weighted_apy, 2),
            "risk_tolerance": risk_tolerance,
            "protocol_count": len(used_protocols),
            "chain_count": len({a["chain"] for a in allocations}),
            "avg_risk_grade": self._risk_grade(avg_risk / 8),
            "diversification_score": min(1.0, len(used_protocols) / 5),
            "rationale": self._build_rationale(allocations, risk_tolerance),
        }

    # ═══════════════════════════════════════════════════════════════════
    # AUTO-REBALANCING
    # ═══════════════════════════════════════════════════════════════════

    async def recommend_rebalance(
        self,
        current_positions: list[dict[str, Any]],
    ) -> list[RebalanceRecommendation]:
        """Generate rebalancing recommendations for current DeFi positions.

        Compares current positions against available opportunities and
        suggests rotations for better risk-adjusted yield.

        Args:
            current_positions: List of dicts with keys:
                protocol, pool_id, symbol, chain, amount_usd, current_apy.

        Returns:
            List of RebalanceRecommendation sorted by priority.
        """
        if not current_positions:
            return []

        recommendations: list[RebalanceRecommendation] = []

        for pos in current_positions:
            protocol = pos.get("protocol", "")
            current_apy = pos.get("current_apy", 0)
            chain = pos.get("chain", "Ethereum")
            symbol = pos.get("symbol", "")
            pos.get("amount_usd", 0)

            # Find better opportunities for same chain
            better = await self.scan_yields(
                chain=chain,
                min_tvl=5_000_000,
                min_apy=current_apy * 0.8,  # Look for at least 80% of current
                limit=10,
            )

            # Filter to strictly better options
            better = [
                o
                for o in better
                if o.protocol != protocol
                and o.risk_adjusted_apy > current_apy * 1.1  # At least 10% better
            ]

            if not better:
                continue

            best = better[0]
            apy_delta = best.risk_adjusted_apy - current_apy

            # Determine action
            if current_apy < 2:
                action = "rotate"
                reasoning = (
                    f"Current yield ({current_apy:.1f}%) is below inflation. "
                    f"Rotate to {best.protocol} ({best.symbol}) for {best.apy:.1f}% APY "
                    f"with {best.risk_score.risk_grade} risk grade."
                )
            elif apy_delta > 5:
                action = "rotate"
                reasoning = (
                    f"Significant yield improvement available: {current_apy:.1f}% → {best.apy:.1f}% "
                    f"({apy_delta:+.1f}% improvement). {best.protocol} has comparable risk."
                )
            elif apy_delta > 2:
                action = "decrease"
                reasoning = (
                    f"Consider partial rotation: move 50% to {best.protocol} "
                    f"for {best.apy:.1f}% APY while maintaining some position."
                )
            else:
                continue  # Not worth the gas cost

            recommendations.append(
                RebalanceRecommendation(
                    action=action,
                    protocol_from=protocol,
                    protocol_to=best.protocol,
                    pool_from=pos.get("pool_id", ""),
                    pool_to=best.pool_id,
                    symbol=symbol,
                    amount_pct=100.0 if action == "rotate" else 50.0,
                    current_apy=current_apy,
                    target_apy=best.apy,
                    risk_change=round(best.risk_score.composite - 0.3, 4),  # Estimate
                    reasoning=reasoning,
                )
            )

        # Sort by yield improvement
        recommendations.sort(key=lambda r: r.target_apy - r.current_apy, reverse=True)
        return recommendations

    # ═══════════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _classify_strategy(pool: YieldPool) -> str:
        """Classify a yield pool into a strategy type."""
        protocol_lower = pool.protocol.lower()
        symbol_lower = pool.symbol.lower()

        # Liquid staking
        if any(
            kw in protocol_lower
            for kw in ["lido", "rocket-pool", "frax-ether", "ether-fi", "mantle-staked"]
        ):
            return "staking"
        if any(kw in symbol_lower for kw in ["steth", "reth", "sfrxeth", "cbeth", "eeth"]):
            return "staking"

        # Lending
        if any(kw in protocol_lower for kw in ["aave", "compound", "morpho", "spark", "venus"]):
            return "lending"

        # Vaults
        if any(kw in protocol_lower for kw in ["yearn", "convex", "beefy", "autofarm"]):
            return "vault"

        # Default to LP for DEX pools
        if pool.exposure == "multi" or "/" in pool.symbol:
            return "lp"

        return "lending"

    async def _compute_pool_risk(self, pool: YieldPool) -> RiskScore:
        """Compute risk score for a yield pool."""
        protocol_key = pool.protocol.lower().replace(" ", "-")

        # Check if we have a profile
        profile = _PROTOCOL_RISK_PROFILES.get(protocol_key, {})

        protocol_risk = profile.get("protocol_risk", 0.4)
        audit_risk = profile.get("audit_score", 0.4)

        # TVL risk
        if pool.tvl_usd > 1_000_000_000:
            tvl_risk = 0.05
        elif pool.tvl_usd > 100_000_000:
            tvl_risk = 0.15
        elif pool.tvl_usd > 10_000_000:
            tvl_risk = 0.30
        else:
            tvl_risk = 0.50

        # IL risk from pool metadata
        il_risk_map = {"none": 0.0, "low": 0.15, "medium": 0.35, "high": 0.60}
        il_risk = il_risk_map.get(pool.il_risk, 0.0)

        # APY anomaly risk: suspiciously high APY = higher risk
        if pool.apy > 100:
            apy_penalty = 0.3
        elif pool.apy > 50:
            apy_penalty = 0.15
        else:
            apy_penalty = 0.0

        # Composite
        composite = (
            protocol_risk * 0.30
            + tvl_risk * 0.20
            + audit_risk * 0.20
            + il_risk * 0.15
            + apy_penalty * 0.15
        )

        factors: list[str] = []
        if not profile:
            factors.append("unverified_protocol")
        if pool.tvl_usd < 10_000_000:
            factors.append("low_tvl")
        if pool.apy > 50:
            factors.append("high_apy_risk")
        if pool.il_risk in ("medium", "high"):
            factors.append(f"il_risk_{pool.il_risk}")
        if pool.exposure == "multi" and not pool.stable_pool:
            factors.append("multi_asset_exposure")

        return RiskScore(
            protocol_risk=round(protocol_risk, 4),
            tvl_risk=round(tvl_risk, 4),
            il_risk=round(il_risk, 4),
            audit_risk=round(audit_risk, 4),
            composite=round(composite, 4),
            risk_grade=YieldOptimizer._risk_grade(composite),
            risk_factors=tuple(factors),
        )

    @staticmethod
    def _risk_grade(score: float) -> str:
        """Convert numeric risk score to letter grade."""
        if score < 0.08:
            return "A+"
        elif score < 0.15:
            return "A"
        elif score < 0.22:
            return "B+"
        elif score < 0.30:
            return "B"
        elif score < 0.40:
            return "C+"
        elif score < 0.50:
            return "C"
        elif score < 0.65:
            return "D"
        else:
            return "F"

    @staticmethod
    def _generate_recommendation(
        pool: YieldPool, risk: RiskScore, risk_adj_apy: float
    ) -> tuple[str, str]:
        """Generate a buy/hold/avoid recommendation."""
        if risk.composite > 0.50:
            return "avoid", f"High risk ({risk.risk_grade}) — protocol risk too high for yield"

        if pool.apy > 50 and risk.composite > 0.30:
            return (
                "caution",
                f"High APY ({pool.apy:.1f}%) with moderate risk — possible unsustainability",
            )

        if risk_adj_apy > 10 and risk.composite < 0.20:
            return (
                "strong_buy",
                f"Excellent risk-adjusted yield ({risk_adj_apy:.1f}%) with low risk ({risk.risk_grade})",
            )

        if risk_adj_apy > 5 and risk.composite < 0.30:
            return (
                "buy",
                f"Good risk-adjusted yield ({risk_adj_apy:.1f}%) with acceptable risk ({risk.risk_grade})",
            )

        if risk_adj_apy > 3:
            return "hold", f"Moderate yield ({risk_adj_apy:.1f}%) — acceptable for diversification"

        return "caution", f"Low risk-adjusted yield ({risk_adj_apy:.1f}%) — consider alternatives"

    @staticmethod
    def _build_rationale(allocations: list[dict], risk_tolerance: str) -> str:
        """Build human-readable rationale for a strategy."""
        if not allocations:
            return "No suitable allocations found."

        chains = {a["chain"] for a in allocations}
        protos = {a["protocol"] for a in allocations}
        avg_apy = sum(a["apy"] for a in allocations) / len(allocations)

        return (
            f"Diversified across {len(protos)} protocols on {len(chains)} chains "
            f"for {risk_tolerance}-risk tolerance. "
            f"Average APY: {avg_apy:.1f}%. "
            f"Total expected annual yield: ${sum(a['allocation_usd'] * a['apy'] / 100 for a in allocations):,.0f}."
        )
