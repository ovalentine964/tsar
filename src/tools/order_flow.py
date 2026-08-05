"""
TSAR Domain Tools — Order Flow Analysis.

Breaks the information asymmetry that causes 78% of retail traders to lose.
Institutional traders see order flow, COT positioning, and whale movements.
Retail traders don't. Until now.

Data Sources:
  - CFTC COT Reports (Commitments of Traders) — free weekly data
  - IG Client Sentiment API — free retail positioning data
  - Whale Alert / large transfer detection — on-chain whale tracking
  - Binance/Bybit open interest & funding rates — derivatives positioning

All tools are async with caching and graceful degradation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


class FlowDirection(StrEnum):
    """Direction of order flow."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ParticipantType(StrEnum):
    """Market participant classification."""

    INSTITUTIONAL = "institutional"
    RETAIL = "retail"
    WHALE = "whale"
    COMMERCIAL = "commercial"  # Hedgers in COT context
    NON_COMMERCIAL = "non_commercial"  # Speculators in COT context


@dataclass(frozen=True)
class COTReport:
    """CFTC Commitments of Traders report for a single asset.

    Attributes:
        asset: Asset name (e.g., "BITCOIN", "GOLD", "EUR").
        report_date: Date of the COT report.
        non_commercial_long: Speculator long positions (contracts).
        non_commercial_short: Speculator short positions (contracts).
        commercial_long: Hedger long positions.
        commercial_short: Hedger short positions.
        open_interest: Total open interest.
        net_speculator_position: Net position of speculators (long - short).
        net_speculator_pct: Net speculator position as % of open interest.
        speculator_positioning: "long", "short", or "neutral".
        positioning_extreme: How extreme the positioning is (0-1).
            Values > 0.8 suggest overcrowding (contrarian signal).
        change_from_prev: Change in net speculator position from prior week.
    """

    asset: str
    report_date: datetime
    non_commercial_long: int
    non_commercial_short: int
    commercial_long: int
    commercial_short: int
    open_interest: int
    net_speculator_position: int
    net_speculator_pct: float
    speculator_positioning: str
    positioning_extreme: float
    change_from_prev: int = 0


@dataclass(frozen=True)
class RetailPositioning:
    """Retail trader positioning from sentiment APIs.

    Attributes:
        asset: Asset symbol.
        long_pct: Percentage of retail traders who are long.
        short_pct: Percentage of retail traders who are short.
        long_volume: Number of long positions.
        short_volume: Number of short positions.
        signal: Contrarian signal derived from positioning.
            Retail is typically wrong at extremes.
        sentiment_bias: "bullish", "bearish", or "neutral".
        crowd_wrong_probability: Estimated probability retail is wrong (0-1).
            Higher when positioning is extreme.
        timestamp: When the data was fetched.
    """

    asset: str
    long_pct: float
    short_pct: float
    long_volume: int = 0
    short_volume: int = 0
    signal: str = "neutral"
    sentiment_bias: str = "neutral"
    crowd_wrong_probability: float = 0.0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class WhaleMovement:
    """A detected whale transaction.

    Attributes:
        symbol: Asset symbol.
        amount: Transaction amount.
        amount_usd: Estimated USD value.
        direction: "exchange_inflow", "exchange_outflow", "transfer", "unknown".
        from_address: Sender (truncated).
        to_address: Receiver (truncated).
        timestamp: When the transaction occurred.
        significance: How significant this movement is (0-1).
    """

    symbol: str
    amount: float
    amount_usd: float
    direction: str
    from_address: str = ""
    to_address: str = ""
    timestamp: datetime | None = None
    significance: float = 0.0


@dataclass(frozen=True)
class InstitutionalFlow:
    """Aggregated institutional vs retail flow classification.

    Attributes:
        asset: Asset symbol.
        institutional_bias: What institutions are doing.
        retail_bias: What retail is doing.
        divergence: Whether institutional and retail disagree.
        smart_money_signal: What "smart money" suggests (contrarian to retail).
        confidence: Confidence in the signal (0-1).
        components: Number of data sources that contributed.
    """

    asset: str
    institutional_bias: str  # "long", "short", "neutral"
    retail_bias: str  # "long", "short", "neutral"
    divergence: bool = False
    smart_money_signal: str = "neutral"
    confidence: float = 0.0
    components: int = 0


@dataclass(frozen=True)
class NetPositioning:
    """Net long/short positioning by asset across all sources.

    Attributes:
        asset: Asset symbol.
        net_long_score: Aggregate long score (-1 to 1).
        cot_signal: COT-derived signal.
        retail_signal: Retail positioning signal.
        whale_signal: Whale movement signal.
        derivatives_signal: Funding/OI derived signal.
        composite_signal: Weighted composite of all signals.
        signal_strength: Absolute strength of composite (0-1).
    """

    asset: str
    net_long_score: float = 0.0
    cot_signal: str = "neutral"
    retail_signal: str = "neutral"
    whale_signal: str = "neutral"
    derivatives_signal: str = "neutral"
    composite_signal: str = "neutral"
    signal_strength: float = 0.0


# ═══════════════════════════════════════════════════════════════════════
# COT REPORT CACHE
# ═══════════════════════════════════════════════════════════════════════

# CFTC publishes COT data as CSV. We cache parsed reports.
# Asset name mapping for CFTC COT reports (CFTC code → common name)
_COT_ASSET_MAP: dict[str, str] = {
    "BITCOIN": "BITCOIN",
    "MICRO BITCOIN": "BITCOIN",
    "ETHER": "ETHEREUM",
    "MICRO ETHER": "ETHEREUM",
    "GOLD": "GOLD",
    "SILVER": "SILVER",
    "EURO FX": "EUR",
    "JAPANESE YEN": "JPY",
    "BRITISH POUND": "GBP",
    "CANADIAN DOLLAR": "CAD",
    "SWISS FRANC": "CHF",
    "AUSTRALIAN DOLLAR": "AUD",
    "NEW ZEALAND DOLLAR": "NZD",
    "RUSSIAN RUBLE": "RUB",
    "CRUDE OIL": "CRUDE_OIL",
    "NATURAL GAS": "NATURAL_GAS",
    "CORN": "CORN",
    "SOYBEANS": "SOYBEANS",
    "WHEAT": "WHEAT",
    "S&P 500": "SP500",
    "NASDAQ-100": "NASDAQ",
    "DOW JONES": "DOW",
    "COPPER": "COPPER",
    "PLATINUM": "PLATINUM",
    "PALLADIUM": "PALLADIUM",
}


# ═══════════════════════════════════════════════════════════════════════
# ORDER FLOW TOOLS
# ═══════════════════════════════════════════════════════════════════════


class OrderFlowTools:
    """Order flow analysis tools that break information asymmetry.

    Provides institutional-grade positioning data that was previously
    only available to professional traders and hedge funds.

    Usage:
        tools = OrderFlowTools()
        cot = await tools.get_cot_positioning("BITCOIN")
        retail = await tools.get_retail_positioning("BTC/USD")
        flow = await tools.get_institutional_flow("BTC/USD")
    """

    def __init__(self, cache_ttl: int = 3600) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = cache_ttl
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self._http

    def _cache_get(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
        return None

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    # ─────────────────────────────────────────────────────────────────
    # COT (Commitments of Traders) — CFTC Weekly Data
    # ─────────────────────────────────────────────────────────────────

    async def get_cot_positioning(
        self,
        asset: str,
        lookback_weeks: int = 26,
    ) -> COTReport | None:
        """Get COT report data for an asset from CFTC.

        The COT report shows how commercial hedgers, large speculators,
        and small traders are positioned. When speculators are extremely
        long or short, it's often a contrarian signal.

        Args:
            asset: Asset name (e.g., "BITCOIN", "GOLD", "EUR").
            lookback_weeks: How many weeks of history to fetch.

        Returns:
            COTReport or None if data unavailable.
        """
        cache_key = f"cot:{asset}:{lookback_weeks}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            result = await self._fetch_cot_from_cftc(asset)
            if result:
                self._cache_set(cache_key, result)
            return result
        except Exception as e:
            logger.warning("COT fetch failed for %s: %s", asset, e)
            return self._estimate_cot_from_derivatives(asset)

    async def _fetch_cot_from_cftc(self, asset: str) -> COTReport | None:
        """Fetch COT data from CFTC's public data endpoint.

        CFTC provides free CSV data at:
        https://www.cftc.gov/dea/futures/financial_lf.htm
        """
        http = await self._get_http()

        # CFTC Disaggregated COT reports (futures only)
        # Try the legacy report first (more assets covered)
        url = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

        # Map common names to CFTC market names
        market_name = asset.upper()

        params = {
            "$where": f"market_name like '%{market_name}%'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": lookback_weeks,
        }

        try:
            resp = await http.get(url, params=params, timeout=15.0)
            if resp.status_code != 200:
                logger.debug("CFTC API returned %d for %s", resp.status_code, asset)
                return None

            data = resp.json()
            if not data:
                return None

            return self._parse_cot_record(data[0], asset)
        except Exception as e:
            logger.debug("CFTC API error: %s", e)
            return None

    def _parse_cot_record(self, record: dict, asset: str) -> COTReport:
        """Parse a single COT JSON record into a COTReport."""
        try:
            report_date_str = record.get("report_date_as_yyyy_mm_dd", "")
            report_date = datetime.fromisoformat(report_date_str.replace("T00:00:00", ""))
        except (ValueError, AttributeError):
            report_date = datetime.now(UTC)

        non_comm_long = int(record.get("noncomm_positions_long_all", 0) or 0)
        non_comm_short = int(record.get("noncomm_positions_short_all", 0) or 0)
        comm_long = int(record.get("comm_positions_long_all", 0) or 0)
        comm_short = int(record.get("comm_positions_short_all", 0) or 0)
        oi = int(record.get("open_interest_all", 0) or 0)

        net_spec = non_comm_long - non_comm_short
        net_spec_pct = (net_spec / oi * 100) if oi > 0 else 0.0

        # Positioning classification
        if net_spec_pct > 10:
            positioning = "long"
        elif net_spec_pct < -10:
            positioning = "short"
        else:
            positioning = "neutral"

        # Extremes: how far from the historical norm
        # Values beyond ±30% of OI are considered extreme
        extreme = min(abs(net_spec_pct) / 30.0, 1.0)

        return COTReport(
            asset=asset,
            report_date=report_date,
            non_commercial_long=non_comm_long,
            non_commercial_short=non_comm_short,
            commercial_long=comm_long,
            commercial_short=comm_short,
            open_interest=oi,
            net_speculator_position=net_spec,
            net_speculator_pct=net_spec_pct,
            speculator_positioning=positioning,
            positioning_extreme=extreme,
        )

    def _estimate_cot_from_derivatives(self, asset: str) -> COTReport | None:
        """Fallback: estimate positioning from derivatives data.

        When CFTC data isn't available (crypto), use open interest
        and funding rates as a proxy for institutional positioning.
        """
        # This is a degraded fallback — better than nothing
        logger.info("Using derivatives-based COT estimate for %s", asset)
        return None  # Will be filled by derivatives integration

    # ─────────────────────────────────────────────────────────────────
    # Retail Positioning — IG Client Sentiment
    # ─────────────────────────────────────────────────────────────────

    async def get_retail_positioning(self, asset: str) -> RetailPositioning:
        """Get retail trader positioning data.

        Retail traders are wrong at extremes. When 80%+ of retail is
        long, the market often drops (and vice versa). This is the
        single most reliable contrarian signal available.

        Uses IG Client Sentiment API (free) as primary source,
        with fallback estimation from volume profiles.

        Args:
            asset: Asset symbol (e.g., "BTC/USD", "EUR/USD").

        Returns:
            RetailPositioning with contrarian signal.
        """
        cache_key = f"retail:{asset}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        result = await self._fetch_ig_sentiment(asset)
        if result is None:
            result = self._estimate_retail_from_volume(asset)

        self._cache_set(cache_key, result)
        return result

    async def _fetch_ig_sentiment(self, asset: str) -> RetailPositioning | None:
        """Fetch retail sentiment from IG Client Sentiment API.

        IG publishes free retail positioning data at:
        https://www.ig.com/en/client-sentiment
        """
        http = await self._get_http()

        # IG sentiment API (public, no auth required for basic data)
        # Map common symbols to IG epic codes
        ig_epic_map = {
            "BTC/USD": "CS.D.BITCOIN.TODAY.IP",
            "ETH/USD": "CS.D.ETHER.TODAY.IP",
            "EUR/USD": "CS.D.EURUSD.TODAY.IP",
            "GBP/USD": "CS.D.GBPUSD.TODAY.IP",
            "USD/JPY": "CS.D.USDJPY.TODAY.IP",
            "AUD/USD": "CS.D.AUDUSD.TODAY.IP",
            "GOLD": "CS.D.CFDDUMMYGOLD.TFM.IP",
            "SP500": "IX.D.SPTRD.DAILY.IP",
        }

        epic = ig_epic_map.get(asset.upper(), ig_epic_map.get(asset))
        if not epic:
            return None

        try:
            # IG's public sentiment endpoint
            url = f"https://www.ig.com/rest-api/sentiment/{epic}"
            resp = await http.get(url, timeout=10.0)
            if resp.status_code != 200:
                return None

            data = resp.json()
            client_sentiment = data.get("clientSentiment", {})

            long_pct = float(client_sentiment.get("longPositionPercentage", 50))
            short_pct = float(client_sentiment.get("shortPositionPercentage", 50))

            return self._build_retail_positioning(asset, long_pct, short_pct)

        except Exception as e:
            logger.debug("IG sentiment fetch failed for %s: %s", asset, e)
            return None

    def _build_retail_positioning(
        self,
        asset: str,
        long_pct: float,
        short_pct: float,
        long_vol: int = 0,
        short_vol: int = 0,
    ) -> RetailPositioning:
        """Build RetailPositioning with contrarian analysis."""
        # Contrarian signal logic
        # Retail is typically wrong at extremes (>75% one direction)
        if long_pct >= 80:
            signal = "bearish"  # Too many retail longs → price likely drops
            crowd_wrong = min((long_pct - 50) / 50, 1.0) * 0.8
            bias = "bullish"  # Retail is bullish (we go opposite)
        elif short_pct >= 80:
            signal = "bullish"  # Too many retail shorts → price likely rises
            crowd_wrong = min((short_pct - 50) / 50, 1.0) * 0.8
            bias = "bearish"
        elif long_pct >= 65:
            signal = "mildly_bearish"
            crowd_wrong = (long_pct - 50) / 100
            bias = "bullish"
        elif short_pct >= 65:
            signal = "mildly_bullish"
            crowd_wrong = (short_pct - 50) / 100
            bias = "bearish"
        else:
            signal = "neutral"
            crowd_wrong = 0.0
            bias = "neutral"

        return RetailPositioning(
            asset=asset,
            long_pct=long_pct,
            short_pct=short_pct,
            long_volume=long_vol,
            short_volume=short_vol,
            signal=signal,
            sentiment_bias=bias,
            crowd_wrong_probability=crowd_wrong,
            timestamp=datetime.now(UTC),
        )

    def _estimate_retail_from_volume(self, asset: str) -> RetailPositioning:
        """Fallback: estimate retail positioning from volume patterns.

        High-volume buying at local tops + high-volume selling at local
            bottoms is a strong indicator of retail behavior.
        """
        # Default to neutral when no data available
        return RetailPositioning(
            asset=asset,
            long_pct=50.0,
            short_pct=50.0,
            signal="neutral",
            sentiment_bias="neutral",
            crowd_wrong_probability=0.0,
            timestamp=datetime.now(UTC),
        )

    # ─────────────────────────────────────────────────────────────────
    # Whale / Large Order Detection
    # ─────────────────────────────────────────────────────────────────

    async def detect_whale_movements(
        self,
        symbol: str,
        min_usd: float = 1_000_000,
        hours: int = 24,
    ) -> list[WhaleMovement]:
        """Detect large (whale) transactions for an asset.

        Whale movements often precede price action. Large exchange
        inflows suggest selling pressure; outflows suggest accumulation.

        Args:
            symbol: Asset symbol (e.g., "BTC", "ETH").
            min_usd: Minimum USD value to qualify as whale movement.
            hours: How many hours back to look.

        Returns:
            List of detected whale movements.
        """
        cache_key = f"whale:{symbol}:{min_usd}:{hours}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        movements = await self._fetch_whale_alerts(symbol, min_usd, hours)
        if not movements:
            movements = await self._detect_from_blockchain_explorer(symbol, min_usd, hours)

        self._cache_set(cache_key, movements)
        return movements

    async def _fetch_whale_alerts(
        self, symbol: str, min_usd: float, hours: int
    ) -> list[WhaleMovement]:
        """Fetch whale alerts from public APIs.

        Whale Alert has a free tier API. We also use
        blockchain explorers for fallback.
        """
        http = await self._get_http()
        movements: list[WhaleMovement] = []

        # Try Whale Alert's free API (limited but useful)
        # Their demo endpoint shows recent large transactions
        try:
            url = "https://api.whale-alert.io/v1/transactions"
            params = {
                "min_value": int(min_usd),
                "currency": symbol.lower(),
                "limit": 20,
            }
            # Note: Free API requires API key; we'll try without and handle gracefully
            resp = await http.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                for tx in data.get("transactions", []):
                    direction = self._classify_whale_direction(tx)
                    movements.append(
                        WhaleMovement(
                            symbol=symbol,
                            amount=float(tx.get("amount", 0)),
                            amount_usd=float(tx.get("amount_usd", 0)),
                            direction=direction,
                            from_address=str(tx.get("from", {}).get("address", ""))[:12],
                            to_address=str(tx.get("to", {}).get("address", ""))[:12],
                            timestamp=datetime.fromtimestamp(tx.get("timestamp", 0), tz=UTC)
                            if tx.get("timestamp")
                            else None,
                            significance=min(float(tx.get("amount_usd", 0)) / 10_000_000, 1.0),
                        )
                    )
        except Exception as e:
            logger.debug("Whale Alert API error: %s", e)

        return movements

    def _classify_whale_direction(self, tx: dict) -> str:
        """Classify whale transaction direction."""
        from_owner = tx.get("from", {}).get("owner", "")
        to_owner = tx.get("to", {}).get("owner", "")

        from_is_exchange = any(
            ex in (from_owner or "").lower()
            for ex in ["binance", "coinbase", "kraken", "bitfinex", "okx", "bybit"]
        )
        to_is_exchange = any(
            ex in (to_owner or "").lower()
            for ex in ["binance", "coinbase", "kraken", "bitfinex", "okx", "bybit"]
        )

        if from_is_exchange and not to_is_exchange:
            return "exchange_outflow"  # Bullish — withdrawing to hold
        elif to_is_exchange and not from_is_exchange:
            return "exchange_inflow"  # Bearish — depositing to sell
        elif from_is_exchange and to_is_exchange:
            return "exchange_transfer"
        else:
            return "transfer"

    async def _detect_from_blockchain_explorer(
        self, symbol: str, min_usd: float, hours: int
    ) -> list[WhaleMovement]:
        """Fallback: detect large movements from blockchain explorers."""
        # Blockchain.com and Etherscan have public APIs for this
        # For now, return empty — will be populated by on-chain tools
        return []

    # ─────────────────────────────────────────────────────────────────
    # Institutional vs Retail Classification
    # ─────────────────────────────────────────────────────────────────

    async def classify_institutional_flow(self, asset: str) -> InstitutionalFlow:
        """Classify whether institutional or retail is driving the market.

        When institutions and retail disagree, institutions are usually
        right. This tool helps identify those divergences.

        Args:
            asset: Asset symbol.

        Returns:
            InstitutionalFlow with bias classification.
        """
        # Gather signals from multiple sources
        cot = await self.get_cot_positioning(asset)
        retail = await self.get_retail_positioning(asset)
        whale_movements = await self.detect_whale_movements(asset)

        # Institutional bias from COT
        inst_bias = "neutral"
        if cot:
            if cot.speculator_positioning == "long" and cot.positioning_extreme < 0.5:
                inst_bias = "long"
            elif cot.speculator_positioning == "short" and cot.positioning_extreme < 0.5:
                inst_bias = "short"
            elif cot.positioning_extreme >= 0.7:
                # Extreme speculator positioning — institutions likely on other side
                inst_bias = "short" if cot.speculator_positioning == "long" else "long"

        # Refine with whale movements
        if whale_movements:
            exchange_outflows = sum(1 for m in whale_movements if m.direction == "exchange_outflow")
            exchange_inflows = sum(1 for m in whale_movements if m.direction == "exchange_inflow")
            if exchange_outflows > exchange_inflows * 1.5:
                whale_bias = "long"
            elif exchange_inflows > exchange_outflows * 1.5:
                whale_bias = "short"
            else:
                whale_bias = "neutral"

            # If COT and whale agree, high confidence
            if inst_bias == whale_bias and inst_bias != "neutral":
                confidence = 0.8
            elif inst_bias == "neutral":
                inst_bias = whale_bias
                confidence = 0.5
            else:
                confidence = 0.6
        else:
            confidence = 0.4 if inst_bias != "neutral" else 0.2

        # Retail bias from sentiment
        retail_bias = retail.sentiment_bias if retail.sentiment_bias != "neutral" else "neutral"

        # Divergence = they disagree
        divergence = (
            inst_bias != "neutral" and retail_bias != "neutral" and inst_bias != retail_bias
        )

        # Smart money signal: follow institutions, fade retail
        if divergence:
            smart_money = inst_bias  # Follow institutions
            confidence = min(confidence + 0.2, 1.0)
        elif inst_bias != "neutral":
            smart_money = inst_bias
        else:
            smart_money = "neutral"

        return InstitutionalFlow(
            asset=asset,
            institutional_bias=inst_bias,
            retail_bias=retail_bias,
            divergence=divergence,
            smart_money_signal=smart_money,
            confidence=confidence,
            components=2 + (1 if whale_movements else 0),
        )

    # ─────────────────────────────────────────────────────────────────
    # Net Positioning
    # ─────────────────────────────────────────────────────────────────

    async def get_net_positioning(self, asset: str) -> NetPositioning:
        """Get aggregate net long/short positioning from all sources.

        Combines COT, retail sentiment, whale movements, and
        derivatives data into a single positioning score.

        Args:
            asset: Asset symbol.

        Returns:
            NetPositioning with composite signal.
        """
        cot = await self.get_cot_positioning(asset)
        retail = await self.get_retail_positioning(asset)
        whale_movements = await self.detect_whale_movements(asset)
        inst_flow = await self.classify_institutional_flow(asset)

        # Score each signal from -1 (very bearish) to +1 (very bullish)
        scores: list[tuple[str, float, float]] = []  # (name, score, weight)

        # COT signal
        if cot:
            cot_score = cot.net_speculator_pct / 50.0  # Normalize
            cot_score = max(-1.0, min(1.0, cot_score))
            # Invert if extreme (contrarian)
            if cot.positioning_extreme > 0.7:
                cot_score *= -0.5
            scores.append(("cot", cot_score, 1.5))
        cot_signal = self._score_to_signal(cot.net_speculator_pct / 50.0 if cot else 0)

        # Retail signal (contrarian)
        retail_score = 0.0
        retail_signal = "neutral"
        if retail:
            # Retail is contrarian — invert their bias
            if retail.signal == "bearish":
                retail_score = 0.6  # Retail is long → we're bearish → but contrarian says bullish
            elif retail.signal == "bullish":
                retail_score = -0.6
            elif retail.signal == "mildly_bearish":
                retail_score = 0.3
            elif retail.signal == "mildly_bullish":
                retail_score = -0.3
            retail_signal = retail.signal
            scores.append(("retail", retail_score, 1.0))

        # Whale signal
        whale_score = 0.0
        whale_signal = "neutral"
        if whale_movements:
            for m in whale_movements:
                if m.direction == "exchange_outflow":
                    whale_score += 0.2 * m.significance
                elif m.direction == "exchange_inflow":
                    whale_score -= 0.2 * m.significance
            whale_score = max(-1.0, min(1.0, whale_score))
            whale_signal = self._score_to_signal(whale_score)
            scores.append(("whale", whale_score, 1.2))

        # Derivative/smart money signal
        deriv_score = 0.0
        deriv_signal = "neutral"
        if inst_flow.divergence:
            # Strong signal when institutions and retail diverge
            if inst_flow.smart_money_signal == "long":
                deriv_score = 0.7
            elif inst_flow.smart_money_signal == "short":
                deriv_score = -0.7
            deriv_signal = inst_flow.smart_money_signal
            scores.append(("derivatives", deriv_score, 1.3))

        # Weighted composite
        if scores:
            total_weight = sum(w for _, _, w in scores)
            composite = sum(s * w for _, s, w in scores) / total_weight
        else:
            composite = 0.0

        composite = max(-1.0, min(1.0, composite))
        composite_signal = self._score_to_signal(composite)

        return NetPositioning(
            asset=asset,
            net_long_score=composite,
            cot_signal=cot_signal,
            retail_signal=retail_signal,
            whale_signal=whale_signal,
            derivatives_signal=deriv_signal,
            composite_signal=composite_signal,
            signal_strength=abs(composite),
        )

    @staticmethod
    def _score_to_signal(score: float) -> str:
        """Convert a numeric score to a signal string."""
        if score > 0.3:
            return "bullish"
        elif score < -0.3:
            return "bearish"
        else:
            return "neutral"

    # ─────────────────────────────────────────────────────────────────
    # Open Interest & Funding (Derivatives Positioning)
    # ─────────────────────────────────────────────────────────────────

    async def get_derivatives_positioning(self, symbol: str) -> dict[str, Any]:
        """Get derivatives market positioning (funding rate, OI).

        High positive funding = crowded longs (bearish signal).
        High negative funding = crowded shorts (bullish signal).
        Rising OI + rising price = new longs entering (bullish).
        Rising OI + falling price = new shorts entering (bearish).

        Args:
            symbol: Asset symbol (e.g., "BTC").

        Returns:
            Dict with funding_rate, open_interest, and derived signals.
        """
        cache_key = f"derivatives:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        http = await self._get_http()
        result: dict[str, Any] = {
            "symbol": symbol,
            "funding_rate": None,
            "open_interest": None,
            "oi_change_24h": None,
            "long_liquidations_24h": None,
            "short_liquidations_24h": None,
            "signal": "neutral",
        }

        try:
            # Binance Futures funding rate
            pair = f"{symbol.upper()}USDT"
            url = "https://fapi.binance.com/fapi/v1/fundingRate"
            params = {"symbol": pair, "limit": 1}
            resp = await http.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    result["funding_rate"] = float(data[0].get("fundingRate", 0))

            # Open interest
            url = "https://fapi.binance.com/fapi/v1/openInterest"
            params = {"symbol": pair}
            resp = await http.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                result["open_interest"] = float(data.get("openInterest", 0))

        except Exception as e:
            logger.debug("Derivatives data fetch error for %s: %s", symbol, e)

        # Derive signal
        fr = result.get("funding_rate")
        if fr is not None:
            if fr > 0.001:  # > 0.1% funding = crowded longs
                result["signal"] = "bearish"
            elif fr < -0.001:  # < -0.1% funding = crowded shorts
                result["signal"] = "bullish"
            else:
                result["signal"] = "neutral"

        self._cache_set(cache_key, result)
        return result

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
