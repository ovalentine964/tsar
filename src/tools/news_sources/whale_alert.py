"""
TSAR — Whale Alert Large Transaction Monitor.

Detects large on-chain transactions via the Whale Alert API.
Large transfers to exchanges often precede sell pressure;
large withdrawals may signal accumulation.

Free tier: 10 requests/min, last 100 transactions.
Paid tier: historical data, webhooks, custom thresholds.

API Docs: https://docs.whale-alert.io/
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


class WhaleTxType(StrEnum):
    """Transaction classification."""

    TRANSFER = "transfer"
    EXCHANGE_DEPOSIT = "exchange_deposit"   # → bearish signal
    EXCHANGE_WITHDRAWAL = "exchange_withdrawal"  # → bullish signal
    WHALE_TO_WHALE = "whale_to_whale"
    BURN = "burn"
    MINT = "mint"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WhaleTransaction:
    """A single large on-chain transaction.

    Attributes:
        blockchain: Chain name (e.g. "bitcoin", "ethereum").
        symbol: Token symbol (e.g. "BTC", "USDT").
        amount: Raw token amount transferred.
        amount_usd: USD value of the transfer.
        from_owner: Sender identity (exchange name, whale label, or "unknown").
        to_owner: Receiver identity.
        tx_type: Classification of the transaction.
        timestamp: Unix timestamp of the transaction.
        hash: Transaction hash.
        sentiment_impact: Derived sentiment (-1 to +1).
    """

    blockchain: str
    symbol: str
    amount: float
    amount_usd: float
    from_owner: str = "unknown"
    to_owner: str = "unknown"
    tx_type: WhaleTxType = WhaleTxType.UNKNOWN
    timestamp: float = 0.0
    hash: str = ""
    sentiment_impact: float = 0.0


@dataclass
class WhaleAlertSummary:
    """Aggregated whale activity summary.

    Attributes:
        symbol: Asset symbol queried.
        transactions: All detected whale transactions.
        total_volume_usd: Total USD volume of whale transactions.
        net_exchange_flow: Net flow to exchanges (positive = deposits, negative = withdrawals).
        deposit_count: Number of exchange deposits.
        withdrawal_count: Number of exchange withdrawals.
        sentiment: Aggregate sentiment from whale activity (-1 to +1).
        alert_level: "critical" if single tx > $50M, "high" if > $10M.
    """

    symbol: str
    transactions: list[WhaleTransaction] = field(default_factory=list)
    total_volume_usd: float = 0.0
    net_exchange_flow: float = 0.0
    deposit_count: int = 0
    withdrawal_count: int = 0
    sentiment: float = 0.0
    alert_level: str = "low"


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

_BASE_URL = "https://api.whale-alert.io/v1"

# Minimum USD value to consider a "whale" transaction
_DEFAULT_MIN_VALUE_USD = 500_000  # $500K

# Alert thresholds
_CRITICAL_USD = 50_000_000   # $50M
_HIGH_USD = 10_000_000       # $10M

# Known exchange owners in Whale Alert
_EXCHANGE_LABELS = frozenset({
    "binance", "coinbase", "kraken", "bitfinex", "okx", "bybit",
    "huobi", "kucoin", "gate.io", "gemini", "ftx", "crypto.com",
    "bitstamp", "bittrex", "poloniex", "hotbit",
})


# ═══════════════════════════════════════════════════════════════════════
# WHALE ALERT CLIENT
# ═══════════════════════════════════════════════════════════════════════


class WhaleAlertClient:
    """Whale Alert API client for large transaction detection.

    Fetches recent large transactions, classifies them by type
    (exchange deposit/withdrawal, whale-to-whale, etc.), and
    computes aggregate sentiment.

    Usage:
        client = WhaleAlertClient(api_key="your_key")
        summary = await client.get_whale_activity("BTC")
        print(summary.sentiment, summary.alert_level)
    """

    description = (
        "Whale Alert: large on-chain transaction monitoring, "
        "exchange flow analysis, whale movement detection"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._api_key = self._config.get("whale_alert_api_key", "")
        self._min_value_usd = self._config.get("min_value_usd", _DEFAULT_MIN_VALUE_USD)
        self._client: httpx.AsyncClient | None = None

        # Cache
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = self._config.get("cache_ttl_s", 120)  # 2 min

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
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

    # ── Public API ───────────────────────────────────────────────────

    async def get_whale_activity(
        self,
        symbol: str,
        limit: int = 50,
        min_value_usd: float | None = None,
    ) -> WhaleAlertSummary:
        """Get recent whale activity for a symbol.

        Args:
            symbol: Asset symbol (e.g. "BTC", "ETH", "USDT").
            limit: Max number of transactions to fetch.
            min_value_usd: Override minimum USD threshold.

        Returns:
            WhaleAlertSummary with classified transactions and sentiment.
        """
        base_symbol = symbol.split("/")[0].upper()
        min_val = min_value_usd or self._min_value_usd

        cache_key = f"whale:{base_symbol}:{limit}:{min_val}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        transactions = await self._fetch_transactions(base_symbol, limit, min_val)
        summary = self._build_summary(base_symbol, transactions)

        self._set_cached(cache_key, summary)
        return summary

    async def get_large_transactions(
        self,
        symbol: str,
        min_usd: float = 1_000_000,
        limit: int = 20,
    ) -> list[WhaleTransaction]:
        """Get transactions above a USD threshold.

        Args:
            symbol: Asset symbol.
            min_usd: Minimum USD value.
            limit: Max transactions.

        Returns:
            List of WhaleTransaction objects.
        """
        base_symbol = symbol.split("/")[0].upper()
        return await self._fetch_transactions(base_symbol, limit, min_usd)

    # ── API Fetch ────────────────────────────────────────────────────

    async def _fetch_transactions(
        self,
        symbol: str,
        limit: int,
        min_value_usd: float,
    ) -> list[WhaleTransaction]:
        """Fetch transactions from Whale Alert API."""
        client = await self._get_client()
        params: dict[str, Any] = {
            "min_value": int(min_value_usd),
            "limit": min(limit, 100),
        }

        # Add API key if available
        if self._api_key:
            params["api_key"] = self._api_key

        # Filter by currency if supported
        if symbol:
            params["currency"] = symbol.lower()

        try:
            resp = await client.get(
                f"{_BASE_URL}/transactions",
                params=params,
                timeout=10,
            )

            # Handle rate limiting gracefully
            if resp.status_code == 429:
                logger.warning("Whale Alert rate limited")
                return []

            resp.raise_for_status()
            data = resp.json()

            transactions: list[WhaleTransaction] = []
            for tx in data.get("transactions", []):
                parsed = self._parse_transaction(tx)
                if parsed:
                    transactions.append(parsed)

            return transactions

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.debug("Whale Alert: API key required for this endpoint")
            else:
                logger.debug("Whale Alert HTTP error: %s", exc)
            return []
        except Exception as exc:
            logger.debug("Whale Alert fetch failed: %s", exc)
            return []

    def _parse_transaction(self, raw: dict[str, Any]) -> WhaleTransaction | None:
        """Parse a raw Whale Alert transaction."""
        try:
            blockchain = raw.get("blockchain", "")
            symbol = raw.get("symbol", "").upper()
            amount = float(raw.get("amount", 0))
            amount_usd = float(raw.get("amount_usd", 0))
            timestamp = float(raw.get("timestamp", 0))
            tx_hash = raw.get("hash", "")

            # Parse owner info
            from_info = raw.get("from", {})
            to_info = raw.get("to", {})
            from_owner = from_info.get("owner", "unknown") or "unknown"
            to_owner = to_info.get("owner", "unknown") or "unknown"

            # Classify transaction type
            tx_type = self._classify_transaction(from_owner, to_owner)

            # Compute sentiment impact
            sentiment = self._compute_sentiment(tx_type, amount_usd)

            return WhaleTransaction(
                blockchain=blockchain,
                symbol=symbol,
                amount=amount,
                amount_usd=amount_usd,
                from_owner=from_owner,
                to_owner=to_owner,
                tx_type=tx_type,
                timestamp=timestamp,
                hash=tx_hash,
                sentiment_impact=round(sentiment, 4),
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Failed to parse whale tx: %s", exc)
            return None

    @staticmethod
    def _classify_transaction(from_owner: str, to_owner: str) -> WhaleTxType:
        """Classify a transaction by sender/receiver."""
        from_lower = from_owner.lower()
        to_lower = to_owner.lower()

        from_is_exchange = any(ex in from_lower for ex in _EXCHANGE_LABELS)
        to_is_exchange = any(ex in to_lower for ex in _EXCHANGE_LABELS)

        if from_is_exchange and not to_is_exchange:
            return WhaleTxType.EXCHANGE_WITHDRAWAL
        elif not from_is_exchange and to_is_exchange:
            return WhaleTxType.EXCHANGE_DEPOSIT
        elif not from_is_exchange and not to_is_exchange:
            return WhaleTxType.WHALE_TO_WHALE
        else:
            return WhaleTxType.TRANSFER

    @staticmethod
    def _compute_sentiment(tx_type: WhaleTxType, amount_usd: float) -> float:
        """Compute sentiment impact of a whale transaction.

        Exchange deposits → bearish (whale preparing to sell)
        Exchange withdrawals → bullish (whale accumulating)
        Size amplifies the signal.
        """
        # Base signal by type
        if tx_type == WhaleTxType.EXCHANGE_DEPOSIT:
            base = -0.3
        elif tx_type == WhaleTxType.EXCHANGE_WITHDRAWAL:
            base = 0.3
        elif tx_type == WhaleTxType.BURN:
            base = 0.2
        elif tx_type == WhaleTxType.MINT:
            base = -0.1
        else:
            base = 0.0

        # Scale by size (log scale to prevent extreme values)
        import math
        if amount_usd > 0:
            size_multiplier = min(2.0, math.log10(amount_usd / 1_000_000) + 1.0)
        else:
            size_multiplier = 1.0

        return max(-1.0, min(1.0, base * size_multiplier))

    def _build_summary(
        self,
        symbol: str,
        transactions: list[WhaleTransaction],
    ) -> WhaleAlertSummary:
        """Build an aggregate summary from transactions."""
        total_volume = sum(tx.amount_usd for tx in transactions)

        # Net exchange flow
        deposits = sum(tx.amount_usd for tx in transactions if tx.tx_type == WhaleTxType.EXCHANGE_DEPOSIT)
        withdrawals = sum(tx.amount_usd for tx in transactions if tx.tx_type == WhaleTxType.EXCHANGE_WITHDRAWAL)
        net_flow = deposits - withdrawals  # positive = more deposits (bearish)

        deposit_count = sum(1 for tx in transactions if tx.tx_type == WhaleTxType.EXCHANGE_DEPOSIT)
        withdrawal_count = sum(1 for tx in transactions if tx.tx_type == WhaleTxType.EXCHANGE_WITHDRAWAL)

        # Aggregate sentiment
        if transactions:
            sentiment = sum(tx.sentiment_impact for tx in transactions) / len(transactions)
        else:
            sentiment = 0.0

        # Alert level based on largest single transaction
        max_usd = max((tx.amount_usd for tx in transactions), default=0)
        if max_usd >= _CRITICAL_USD:
            alert_level = "critical"
        elif max_usd >= _HIGH_USD:
            alert_level = "high"
        elif transactions:
            alert_level = "medium"
        else:
            alert_level = "low"

        return WhaleAlertSummary(
            symbol=symbol,
            transactions=transactions,
            total_volume_usd=total_volume,
            net_exchange_flow=net_flow,
            deposit_count=deposit_count,
            withdrawal_count=withdrawal_count,
            sentiment=round(sentiment, 4),
            alert_level=alert_level,
        )
