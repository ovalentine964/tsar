"""
TSAR Domain Tools — Fundamental Analysis Tools.

What the agent RESEARCHES. Provides project fundamentals (GitHub,
TVL, developer activity) and market structure analysis (tokenomics,
supply dynamics, valuation metrics).

Sub-tools are split into dedicated modules for maintainability:
  - src.tools.on_chain      — On-chain analytics
  - src.tools.sentiment     — Social sentiment
  - src.tools.news          — News aggregation
  - src.tools.economic_calendar — Economic calendar

This module handles:
  1. Project Fundamentals (GitHub, TVL, developer score, community)
  2. Market Structure (market cap, supply, tokenomics, valuation)

All tools fetch from free/public APIs with caching and rate limiting.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# COINGECKO ID MAPPING
# ═══════════════════════════════════════════════════════════════════════

_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
    "APT": "aptos",
    "SUI": "sui",
    "FIL": "filecoin",
    "LTC": "litecoin",
    "AAVE": "aave",
    "MKR": "maker",
    "CRV": "curve-dao-token",
    "LDO": "lido-dao",
    "RPL": "rocket-pool",
}

# GitHub repositories for major projects
_GITHUB_REPOS: dict[str, str] = {
    "BTC": "bitcoin/bitcoin",
    "ETH": "ethereum/go-ethereum",
    "SOL": "solana-labs/solana",
    "ADA": "input-output-hk/cardano-node",
    "DOT": "paritytech/polkadot-sdk",
    "AVAX": "ava-labs/avalanchego",
    "MATIC": "maticnetwork/bor",
    "LINK": "smartcontractkit/chainlink",
    "UNI": "Uniswap/v3-core",
    "ATOM": "cosmos/cosmos-sdk",
    "NEAR": "near/nearcore",
    "ARB": "OffchainLabs/nitro",
    "OP": "ethereum-optimism/optimism",
    "FIL": "filecoin-project/lotus",
    "LTC": "litecoin-project/litecoin",
    "AAVE": "aave/aave-v3-core",
    "MKR": "makerdao/dss",
    "CRV": "curvefi/curve-contract",
}


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class GitHubActivity:
    """GitHub repository activity metrics.

    Attributes:
        repo: Repository path (e.g. "bitcoin/bitcoin").
        stars: Number of GitHub stars.
        forks: Number of forks.
        open_issues: Number of open issues.
        commits_30d: Commits in the last 30 days.
        commits_90d: Commits in the last 90 days.
        contributors: Number of contributors.
        pull_requests_open: Open pull requests.
        pull_requests_merged_30d: Merged PRs in last 30 days.
        last_commit_days_ago: Days since last commit.
        code_frequency: Estimated code churn (additions/deletions per week).
        activity_score: Overall activity score (0-1).
            Based on commits, PRs, and contributor count.
        health_score: Repository health score (0-1).
            Based on issue resolution, PR merge rate, activity trend.
    """

    repo: str
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    commits_30d: int = 0
    commits_90d: int = 0
    contributors: int = 0
    pull_requests_open: int = 0
    pull_requests_merged_30d: int = 0
    last_commit_days_ago: int = 0
    code_frequency: float = 0.0
    activity_score: float = 0.0
    health_score: float = 0.0


@dataclass(frozen=True)
class TVLData:
    """Total Value Locked data for DeFi protocols.

    Attributes:
        protocol: Protocol name.
        chain: Primary blockchain.
        tvl: Current TVL in USD.
        tvl_change_1d: 1-day TVL change (%).
        tvl_change_7d: 7-day TVL change (%).
        tvl_change_30d: 30-day TVL change (%).
        tvl_peak: All-time high TVL.
        tvl_dominance: TVL as % of category total.
        mcap_to_tvl: Market cap / TVL ratio.
            Low ratio (<1) = potentially undervalued.
            High ratio (>5) = potentially overvalued.
        chains: Chains the protocol is deployed on.
    """

    protocol: str
    chain: str = ""
    tvl: float = 0.0
    tvl_change_1d: float = 0.0
    tvl_change_7d: float = 0.0
    tvl_change_30d: float = 0.0
    tvl_peak: float = 0.0
    tvl_dominance: float = 0.0
    mcap_to_tvl: float = 0.0
    chains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tokenomics:
    """Tokenomics analysis.

    Attributes:
        symbol: Asset symbol.
        circulating_supply: Current circulating supply.
        total_supply: Total supply (may be > circulating if locked).
        max_supply: Maximum supply (None if uncapped).
        circulating_pct: Circulating as % of total supply.
        inflation_rate: Estimated annual inflation rate (%).
            Based on supply emission schedule.
        vesting_schedule: Description of vesting/unlock schedule.
        concentration_top10: % of supply held by top 10 wallets.
        concentration_top100: % of supply held by top 100 wallets.
        burn_rate: Token burn rate (if applicable).
        staking_ratio: % of supply staked (if applicable).
        tokenomics_score: Overall tokenomics quality score (0-1).
            Higher = healthier supply dynamics.
    """

    symbol: str
    circulating_supply: float = 0.0
    total_supply: float = 0.0
    max_supply: float | None = None
    circulating_pct: float = 0.0
    inflation_rate: float = 0.0
    vesting_schedule: str = ""
    concentration_top10: float = 0.0
    concentration_top100: float = 0.0
    burn_rate: float = 0.0
    staking_ratio: float = 0.0
    tokenomics_score: float = 0.0


@dataclass(frozen=True)
class MarketStructure:
    """Market structure and valuation metrics.

    Attributes:
        symbol: Asset symbol.
        market_cap: Market capitalization in USD.
        fully_diluted_valuation: FDV in USD.
        volume_24h: 24-hour trading volume.
        volume_to_mcap: Volume / market cap ratio.
            High ratio (>0.1) = high interest/liquidity.
            Low ratio (<0.01) = low interest.
        price: Current price in USD.
        price_change_24h: 24-hour price change (%).
        price_change_7d: 7-day price change (%).
        price_change_30d: 30-day price change (%).
        ath: All-time high price.
        ath_change_pct: Distance from ATH (%).
        atl: All-time low price.
        rank: Market cap rank.
        dominance: Market dominance (% of total crypto market cap).
        category: Asset category ("layer1", "defi", "meme", etc.).
        tokenomics: Tokenomics data.
        valuation_signal: Derived valuation signal.
            "undervalued", "fair", "overvalued", or "uncertain".
    """

    symbol: str
    market_cap: float = 0.0
    fully_diluted_valuation: float = 0.0
    volume_24h: float = 0.0
    volume_to_mcap: float = 0.0
    price: float = 0.0
    price_change_24h: float = 0.0
    price_change_7d: float = 0.0
    price_change_30d: float = 0.0
    ath: float = 0.0
    ath_change_pct: float = 0.0
    atl: float = 0.0
    rank: int = 0
    dominance: float = 0.0
    category: str = ""
    tokenomics: Tokenomics | None = None
    valuation_signal: str = "uncertain"


@dataclass(frozen=True)
class ProjectFundamentals:
    """Comprehensive project fundamental data.

    Combines market data, developer activity, TVL, community metrics,
    and tokenomics into a single snapshot.

    Attributes:
        symbol: Asset symbol.
        name: Project name.
        description: Brief project description.
        market_structure: Market structure and valuation data.
        github: GitHub activity metrics.
        tvl: Total Value Locked (for DeFi protocols).
        developer_score: Developer activity score (0-1).
        community_score: Community engagement score (0-1).
        fundamental_score: Aggregate fundamental score (0-1).
        timestamp: When the data was fetched.
    """

    symbol: str
    name: str = ""
    description: str = ""
    market_structure: MarketStructure | None = None
    github: GitHubActivity | None = None
    tvl: TVLData | None = None
    developer_score: float = 0.0
    community_score: float = 0.0
    fundamental_score: float = 0.0
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# FUNDAMENTAL ANALYSIS TOOLS
# ═══════════════════════════════════════════════════════════════════════


class FundamentalAnalysisTools:
    """Fundamental analysis tools for crypto markets.

    Provides project fundamentals (GitHub, TVL, community) and
    market structure analysis (tokenomics, valuation, supply dynamics).
    """

    description = (
        "Fundamental analysis: GitHub activity, TVL, tokenomics, "
        "market structure, valuation, community metrics"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._client: httpx.AsyncClient | None = None

        # Caches
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 300)

        # API keys
        self._coingecko_key = self._config.get("coingecko_api_key", "")
        self._github_token = self._config.get("github_token", "")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cached(self, key: str) -> Any | None:
        """Get from cache if not expired."""
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        """Store in cache."""
        self._cache[key] = (time.time(), value)

    # ── GitHub Activity ──────────────────────────────────────────────

    async def get_github_activity(self, symbol: str) -> GitHubActivity:
        """Get GitHub development activity for a project.

        Fetches repository stats, commit history, and contributor
        data from the GitHub API. Computes activity and health scores.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            GitHubActivity with repository metrics and scores.
        """
        cache_key = f"github:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()
        repo = _GITHUB_REPOS.get(base_symbol)

        if not repo:
            return GitHubActivity(repo="")

        client = await self._get_client()

        try:
            headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
            if self._github_token:
                headers["Authorization"] = f"token {self._github_token}"

            # Fetch repo info
            repo_resp = await client.get(
                f"https://api.github.com/repos/{repo}",
                headers=headers,
                timeout=10,
            )
            repo_resp.raise_for_status()
            repo_data = repo_resp.json()

            stars = repo_data.get("stargazers_count", 0)
            forks = repo_data.get("forks_count", 0)
            open_issues = repo_data.get("open_issues_count", 0)

            # Fetch commit activity (last year, weekly)
            commit_resp = await client.get(
                f"https://api.github.com/repos/{repo}/stats/commit_activity",
                headers=headers,
                timeout=10,
            )

            commits_30d = 0
            commits_90d = 0
            if commit_resp.status_code == 200:
                commit_data = commit_resp.json()
                if isinstance(commit_data, list):
                    # Last 4 weeks = 30 days, last 13 weeks = ~90 days
                    commits_30d = sum(w.get("total", 0) for w in commit_data[-4:])
                    commits_90d = sum(w.get("total", 0) for w in commit_data[-13:])

            # Fetch contributors count
            contrib_resp = await client.get(
                f"https://api.github.com/repos/{repo}/contributors",
                headers=headers,
                params={"per_page": 1, "anon": "true"},
                timeout=10,
            )

            # GitHub returns contributors in Link header with page count
            contributors = 0
            if contrib_resp.status_code == 200:
                link_header = contrib_resp.headers.get("Link", "")
                if 'rel="last"' in link_header:
                    # Parse last page number from Link header
                    import re
                    match = re.search(r'page=(\d+)>; rel="last"', link_header)
                    if match:
                        contributors = int(match.group(1))
                else:
                    contributors = len(contrib_resp.json()) if isinstance(contrib_resp.json(), list) else 0

            # Fetch recent commits for last_commit calculation
            recent_commits_resp = await client.get(
                f"https://api.github.com/repos/{repo}/commits",
                headers=headers,
                params={"per_page": 1},
                timeout=10,
            )

            last_commit_days = 0
            if recent_commits_resp.status_code == 200:
                commits_list = recent_commits_resp.json()
                if commits_list:
                    commit_date = commits_list[0].get("commit", {}).get("committer", {}).get("date", "")
                    if commit_date:
                        try:
                            last_dt = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
                            last_commit_days = (datetime.now(UTC) - last_dt).days
                        except (ValueError, TypeError):
                            pass

            # Compute scores
            activity_score = self._compute_activity_score(
                commits_30d, contributors, stars, forks
            )
            health_score = self._compute_health_score(
                commits_30d, last_commit_days, open_issues
            )

            result = GitHubActivity(
                repo=repo,
                stars=stars,
                forks=forks,
                open_issues=open_issues,
                commits_30d=commits_30d,
                commits_90d=commits_90d,
                contributors=contributors,
                last_commit_days_ago=last_commit_days,
                activity_score=round(activity_score, 4),
                health_score=round(health_score, 4),
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("GitHub activity fetch failed for %s: %s", symbol, exc)
            return GitHubActivity(repo=repo)

    @staticmethod
    def _compute_activity_score(
        commits_30d: int,
        contributors: int,
        stars: int,
        forks: int,
    ) -> float:
        """Compute developer activity score (0-1).

        Weights:
          - Commits (40%): More commits = more active development
          - Contributors (30%): More contributors = healthier project
          - Stars (15%): Community interest indicator
          - Forks (15%): Developer adoption indicator
        """
        # Normalize each metric to 0-1
        commit_score = min(1.0, commits_30d / 200)  # 200 commits/month = max
        contrib_score = min(1.0, contributors / 500)  # 500 contributors = max
        star_score = min(1.0, stars / 50_000)  # 50k stars = max
        fork_score = min(1.0, forks / 10_000)  # 10k forks = max

        return (
            commit_score * 0.40
            + contrib_score * 0.30
            + star_score * 0.15
            + fork_score * 0.15
        )

    @staticmethod
    def _compute_health_score(
        commits_30d: int,
        last_commit_days: int,
        open_issues: int,
    ) -> float:
        """Compute repository health score (0-1).

        Weights:
          - Recent activity (50%): Regular commits = healthy
          - Responsiveness (30%): Quick commits = maintained
          - Issue management (20%): Low open issues relative to activity
        """
        # Recent activity: regular commits
        activity = min(1.0, commits_30d / 50)  # 50 commits/month = max

        # Responsiveness: days since last commit
        if last_commit_days <= 1:
            responsiveness = 1.0
        elif last_commit_days <= 7:
            responsiveness = 0.8
        elif last_commit_days <= 30:
            responsiveness = 0.5
        else:
            responsiveness = max(0.0, 1.0 - last_commit_days / 365)

        # Issue management: lower is better (relative to activity)
        if commits_30d > 0:
            issue_ratio = min(1.0, open_issues / (commits_30d * 2))
            issue_score = 1.0 - issue_ratio
        else:
            issue_score = 0.3

        return activity * 0.50 + responsiveness * 0.30 + issue_score * 0.20

    # ── TVL (Total Value Locked) ─────────────────────────────────────

    async def get_tvl(self, symbol: str) -> TVLData:
        """Get Total Value Locked for a DeFi protocol.

        TVL measures the total assets deposited in a DeFi protocol.
        It's a key indicator of protocol adoption and trust.

        Uses DeFi Llama API (free, no auth required).

        Args:
            symbol: Asset symbol (e.g. "UNI", "AAVE", "MKR").

        Returns:
            TVLData with current TVL, changes, and mcap/TVL ratio.
        """
        cache_key = f"tvl:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()
        client = await self._get_client()

        try:
            # DeFi Llama protocol lookup
            protocol_name = self._symbol_to_defi_protocol(base_symbol)
            if not protocol_name:
                return TVLData(protocol=base_symbol)

            resp = await client.get(
                f"https://api.llama.fi/protocol/{protocol_name}",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            tvl_current = float(data.get("tvl", 0) or 0)
            chain = data.get("chain", "Multi-chain")
            chains = tuple(data.get("chains", []))

            # TVL changes from historical data
            tvl_history = data.get("tvl", [])
            if isinstance(tvl_history, list) and len(tvl_history) > 1:
                tvl_current = float(tvl_history[-1].get("totalLiquidityUSD", 0))

                # 1-day change
                if len(tvl_history) >= 2:
                    tvl_1d = float(tvl_history[-2].get("totalLiquidityUSD", tvl_current))
                    change_1d = ((tvl_current - tvl_1d) / tvl_1d * 100) if tvl_1d > 0 else 0
                else:
                    change_1d = 0

                # 7-day change
                if len(tvl_history) >= 8:
                    tvl_7d = float(tvl_history[-8].get("totalLiquidityUSD", tvl_current))
                    change_7d = ((tvl_current - tvl_7d) / tvl_7d * 100) if tvl_7d > 0 else 0
                else:
                    change_7d = 0

                # 30-day change
                if len(tvl_history) >= 31:
                    tvl_30d = float(tvl_history[-31].get("totalLiquidityUSD", tvl_current))
                    change_30d = ((tvl_current - tvl_30d) / tvl_30d * 100) if tvl_30d > 0 else 0
                else:
                    change_30d = 0

                # Peak TVL
                peak = max(float(h.get("totalLiquidityUSD", 0)) for h in tvl_history)
            else:
                change_1d = change_7d = change_30d = 0
                peak = tvl_current

            # Market cap / TVL ratio
            mcap = await self._get_market_cap(client, base_symbol)
            mcap_tvl = mcap / tvl_current if tvl_current > 0 else 0

            result = TVLData(
                protocol=protocol_name,
                chain=chain,
                tvl=round(tvl_current, 2),
                tvl_change_1d=round(change_1d, 2),
                tvl_change_7d=round(change_7d, 2),
                tvl_change_30d=round(change_30d, 2),
                tvl_peak=round(peak, 2),
                mcap_to_tvl=round(mcap_tvl, 4),
                chains=chains,
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("TVL fetch failed for %s: %s", symbol, exc)
            return TVLData(protocol=base_symbol)

    @staticmethod
    def _symbol_to_defi_protocol(symbol: str) -> str | None:
        """Convert symbol to DeFi Llama protocol name."""
        mapping = {
            "UNI": "uniswap",
            "AAVE": "aave",
            "MKR": "makerdao",
            "CRV": "curve-dex",
            "LDO": "lido",
            "RPL": "rocket-pool",
            "COMP": "compound",
            "SNX": "synthetix",
            "SUSHI": "sushiswap",
            "DYDX": "dydx",
            "GMX": "gmx",
            "PENDLE": "pendle",
            "JUP": "jupiter",
            "RAY": "raydium",
        }
        return mapping.get(symbol.upper())

    # ── Market Structure ─────────────────────────────────────────────

    async def get_market_structure(self, symbol: str) -> MarketStructure:
        """Get market structure and valuation metrics.

        Provides market cap, supply dynamics, volume analysis,
        and a derived valuation signal.

        Uses CoinGecko API (free tier).

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            MarketStructure with valuation and supply metrics.
        """
        cache_key = f"market_structure:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()
        client = await self._get_client()

        try:
            coin_id = _COINGECKO_IDS.get(base_symbol)
            if not coin_id:
                return MarketStructure(symbol=base_symbol)

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "community_data": "false",
                    "developer_data": "false",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            market = data.get("market_data", {})

            market_cap = float(market.get("market_cap", {}).get("usd", 0))
            fdv = float(market.get("fully_diluted_valuation", {}).get("usd", 0))
            volume = float(market.get("total_volume", {}).get("usd", 0))
            price = float(market.get("current_price", {}).get("usd", 0))
            circ_supply = float(market.get("circulating_supply", 0) or 0)
            total_supply = float(market.get("total_supply", 0) or 0)
            max_supply_val = market.get("max_supply")
            max_supply = float(max_supply_val) if max_supply_val else None

            # Price changes
            change_24h = float(market.get("price_change_percentage_24h", 0) or 0)
            change_7d = float(market.get("price_change_percentage_7d", 0) or 0)
            change_30d = float(market.get("price_change_percentage_30d", 0) or 0)

            # ATH/ATL
            ath = float(market.get("ath", {}).get("usd", 0) or 0)
            ath_change = float(market.get("ath_change_percentage", {}).get("usd", 0) or 0)
            atl = float(market.get("atl", {}).get("usd", 0) or 0)

            # Rank and category
            rank = int(data.get("market_cap_rank", 0) or 0)
            categories = data.get("categories", [])
            category = self._classify_category(categories)

            # Volume/mcap ratio
            vol_mcap = volume / market_cap if market_cap > 0 else 0

            # Tokenomics
            tokenomics = self._analyze_tokenomics(
                base_symbol, circ_supply, total_supply, max_supply
            )

            # Valuation signal
            valuation = self._compute_valuation_signal(
                market_cap, fdv, vol_mcap, ath_change, tokenomics
            )

            # Market dominance (approximate)
            dominance = 0.0
            if base_symbol == "BTC":
                # BTC dominance ~50% (would need global market cap API for precision)
                dominance = 50.0
            elif base_symbol == "ETH":
                dominance = 17.0

            result = MarketStructure(
                symbol=base_symbol,
                market_cap=round(market_cap, 2),
                fully_diluted_valuation=round(fdv, 2),
                volume_24h=round(volume, 2),
                volume_to_mcap=round(vol_mcap, 6),
                price=round(price, 8),
                price_change_24h=round(change_24h, 2),
                price_change_7d=round(change_7d, 2),
                price_change_30d=round(change_30d, 2),
                ath=round(ath, 8),
                ath_change_pct=round(ath_change, 2),
                atl=round(atl, 8),
                rank=rank,
                dominance=round(dominance, 2),
                category=category,
                tokenomics=tokenomics,
                valuation_signal=valuation,
            )

            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("Market structure fetch failed for %s: %s", symbol, exc)
            return MarketStructure(symbol=base_symbol)

    @staticmethod
    def _analyze_tokenomics(
        symbol: str,
        circulating: float,
        total: float,
        max_supply: float | None,
    ) -> Tokenomics:
        """Analyze tokenomics from supply data."""
        circulating_pct = (circulating / total * 100) if total > 0 else 0

        # Estimate inflation rate based on supply dynamics
        inflation = 0.0
        if max_supply and total > 0:
            # Remaining tokens to be emitted
            remaining = max_supply - circulating
            if remaining > 0:
                # Rough estimate: assume 4-year emission schedule for remaining
                annual_emission = remaining / 4
                inflation = (annual_emission / circulating * 100) if circulating > 0 else 0

        # Known staking ratios
        staking_ratios = {
            "ETH": 0.27,  # ~27% staked
            "SOL": 0.65,  # ~65% staked
            "ADA": 0.60,  # ~60% staked
            "DOT": 0.50,  # ~50% staked
            "ATOM": 0.60,  # ~60% staked
            "AVAX": 0.50,  # ~50% staked
        }
        staking = staking_ratios.get(symbol, 0.0)

        # Known burn mechanisms
        burn_rates = {
            "ETH": 0.005,  # EIP-1559 burn
            "BNB": 0.01,   # Quarterly burn
            "SOL": 0.005,  # Fee burn
        }
        burn = burn_rates.get(symbol, 0.0)

        # Tokenomics score
        score = 0.0

        # Circulating supply health (higher = better)
        if circulating_pct > 80:
            score += 0.3
        elif circulating_pct > 50:
            score += 0.2
        else:
            score += 0.1

        # Capped supply is healthier
        if max_supply:
            score += 0.2

        # Deflationary mechanisms
        if burn > 0:
            score += 0.15

        # Staking reduces circulating supply
        if staking > 0.2:
            score += 0.15

        # Low inflation
        if inflation < 5:
            score += 0.2
        elif inflation < 15:
            score += 0.1

        return Tokenomics(
            symbol=symbol,
            circulating_supply=circulating,
            total_supply=total,
            max_supply=max_supply,
            circulating_pct=round(circulating_pct, 2),
            inflation_rate=round(inflation, 2),
            burn_rate=round(burn, 4),
            staking_ratio=round(staking, 4),
            tokenomics_score=round(min(1.0, score), 4),
        )

    @staticmethod
    def _compute_valuation_signal(
        market_cap: float,
        fdv: float,
        vol_mcap: float,
        ath_change: float,
        tokenomics: Tokenomics,
    ) -> str:
        """Compute a valuation signal from market metrics."""
        score = 0  # -2 to +2 scale

        # FDV premium: large gap between mcap and FDV = dilution risk
        if fdv > 0 and market_cap > 0:
            fdv_ratio = fdv / market_cap
            if fdv_ratio > 3:
                score -= 1  # Overvalued (heavy dilution ahead)
            elif fdv_ratio < 1.5:
                score += 1  # Fairly valued

        # Volume/mcap: high interest is positive
        if vol_mcap > 0.1:
            score += 1
        elif vol_mcap < 0.01:
            score -= 1

        # Distance from ATH: far from ATH could mean undervalued
        if ath_change > -50:
            pass  # Near ATH
        elif ath_change < -80:
            score += 1  # Very far from ATH, potential value

        # Tokenomics quality
        if tokenomics.tokenomics_score > 0.7:
            score += 1
        elif tokenomics.tokenomics_score < 0.3:
            score -= 1

        if score >= 2:
            return "undervalued"
        elif score >= 0:
            return "fair"
        elif score >= -1:
            return "overvalued"
        else:
            return "overvalued"

    @staticmethod
    def _classify_category(categories: list[str]) -> str:
        """Classify asset into a primary category."""
        cats_lower = [c.lower() for c in categories if c]

        if any("layer 1" in c or "smart contract" in c for c in cats_lower):
            return "layer1"
        elif any("defi" in c or "decentralized" in c for c in cats_lower):
            return "defi"
        elif any("meme" in c for c in cats_lower):
            return "meme"
        elif any("layer 2" in c for c in cats_lower):
            return "layer2"
        elif any("stablecoin" in c for c in cats_lower):
            return "stablecoin"
        elif any("gaming" in c or "metaverse" in c for c in cats_lower):
            return "gaming"
        elif any("exchange" in c for c in cats_lower):
            return "exchange"
        else:
            return "other"

    # ── Comprehensive Project Fundamentals ───────────────────────────

    async def get_project_fundamentals(self, symbol: str) -> ProjectFundamentals:
        """Get comprehensive project fundamentals.

        Combines market structure, GitHub activity, TVL, and community
        data into a single snapshot with an aggregate fundamental score.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH").

        Returns:
            ProjectFundamentals with all sub-metrics and composite score.
        """
        cache_key = f"fundamentals:{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base_symbol = symbol.split("/")[0].upper()

        # Fetch all sub-metrics in parallel
        results = await asyncio.gather(
            self.get_market_structure(symbol),
            self.get_github_activity(symbol),
            self.get_tvl(symbol),
            return_exceptions=True,
        )

        market_struct = results[0] if not isinstance(results[0], Exception) else None
        github = results[1] if not isinstance(results[1], Exception) else None
        tvl = results[2] if not isinstance(results[2], Exception) else None

        # Developer score from GitHub
        dev_score = github.activity_score if github else 0.0

        # Community score from market data
        community_score = 0.0
        if market_struct:
            # Based on volume, rank, and market cap
            rank_score = max(0, 1.0 - market_struct.rank / 100)
            vol_score = min(1.0, market_struct.volume_24h / 1_000_000_000)
            community_score = (rank_score * 0.5 + vol_score * 0.5)

        # Fundamental score (weighted combination)
        scores: list[tuple[float, float]] = []
        if market_struct:
            scores.append((0.4, market_struct.tokenomics.tokenomics_score if market_struct.tokenomics else 0.5))
        if github:
            scores.append((0.3, github.activity_score))
        if tvl and tvl.tvl > 0:
            scores.append((0.2, min(1.0, tvl.tvl / 10_000_000_000)))
        scores.append((0.1, community_score))

        total_weight = sum(w for w, _ in scores)
        fundamental = sum(w * s for w, s in scores) / total_weight if total_weight > 0 else 0.5

        # Project name and description
        name = base_symbol
        descriptions = {
            "BTC": "Bitcoin — decentralized digital currency",
            "ETH": "Ethereum — smart contract platform",
            "SOL": "Solana — high-performance blockchain",
            "BNB": "BNB Chain — Binance ecosystem",
        }
        description = descriptions.get(base_symbol, f"{base_symbol} cryptocurrency")

        result = ProjectFundamentals(
            symbol=base_symbol,
            name=name,
            description=description,
            market_structure=market_struct,
            github=github,
            tvl=tvl,
            developer_score=round(dev_score, 4),
            community_score=round(community_score, 4),
            fundamental_score=round(fundamental, 4),
            timestamp=datetime.now(UTC),
        )

        self._set_cached(cache_key, result)
        return result

    # ── Helper Methods ───────────────────────────────────────────────

    async def _get_market_cap(
        self,
        client: httpx.AsyncClient,
        symbol: str,
    ) -> float:
        """Get market cap from CoinGecko."""
        try:
            coin_id = _COINGECKO_IDS.get(symbol)
            if not coin_id:
                return 0.0

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_market_cap": "true",
                },
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get(coin_id, {}).get("usd_market_cap", 0))
        except Exception:
            return 0.0
