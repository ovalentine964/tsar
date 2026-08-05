"""
TSAR — News Classification Engine.

Classifies crypto news into severity tiers and derives sentiment scores.
This is the intelligence layer that sits between raw news ingestion
and the NewsGatekeeper decision engine.

Classification Tiers:
  CRITICAL — Exchange hack, regulatory ban, stablecoin depeg, major exploit
  HIGH     — ETF decision, major partnership, protocol upgrade, whale movement
  MEDIUM   — Market analysis, price prediction, minor partnership
  LOW      — Opinion pieces, educational content, minor updates

Design Principle:
  False negatives (missing a hack) are catastrophic.
  False positives (pausing on FUD) are recoverable.
  The system is biased toward caution.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# ENUMS & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════


class NewsSeverity(StrEnum):
    CRITICAL = "critical"  # VETO: Halt all trading immediately
    HIGH = "high"  # BLOCK: Reject new entries, warn on existing
    MEDIUM = "medium"  # ALERT: Include in SQF scoring, reduce size
    LOW = "low"  # TRACK: Log only, no trading impact


class NewsCategory(StrEnum):
    EXCHANGE_COMPROMISE = "exchange_compromise"
    REGULATORY_BAN = "regulatory_ban"
    STABLECOIN_DEPEG = "stablecoin_depeg"
    MAJOR_EXPLOIT = "major_exploit"
    PROTOCOL_DEATH = "protocol_death"
    ETF_DECISION = "etf_decision"
    MAJOR_PARTNERSHIP = "major_partnership"
    PROTOCOL_UPGRADE = "protocol_upgrade"
    WHALE_MOVEMENT = "whale_movement"
    MAJOR_LAWSUIT = "major_lawsuit"
    MARKET_ANALYSIS = "market_analysis"
    MINOR_PARTNERSHIP = "minor_partnership"
    PRICE_PREDICTION = "price_prediction"
    EDUCATIONAL = "educational"
    OPINION = "opinion"
    MINOR_UPDATE = "minor_update"
    UNKNOWN = "unknown"


# Source reliability scores (0-1)
SOURCE_RELIABILITY: dict[str, float] = {
    # Tier 1: Primary financial/crypto news
    "Bloomberg": 0.95,
    "Reuters": 0.95,
    "Bloomberg Crypto": 0.95,
    "CoinDesk": 0.90,
    "The Block": 0.90,
    "Financial Times": 0.90,
    "Wall Street Journal": 0.90,
    # Tier 2: Crypto-native
    "CoinTelegraph": 0.85,
    "Decrypt": 0.85,
    "The Defiant": 0.75,
    "Blockworks": 0.80,
    "DL News": 0.75,
    # Tier 3: Aggregators
    "CryptoPanic": 0.70,
    # Tier 4: Social / Low reliability
    "Twitter": 0.40,
    "Twitter/X": 0.40,
    "Reddit": 0.35,
    "Telegram": 0.25,
    "Unknown": 0.20,
}

# Sentiment derivation map: category → (sentiment, confidence)
CATEGORY_SENTIMENT: dict[NewsCategory, tuple[float, float]] = {
    NewsCategory.EXCHANGE_COMPROMISE: (-1.0, 0.95),
    NewsCategory.REGULATORY_BAN: (-1.0, 0.90),
    NewsCategory.STABLECOIN_DEPEG: (-0.9, 0.90),
    NewsCategory.MAJOR_EXPLOIT: (-0.9, 0.85),
    NewsCategory.PROTOCOL_DEATH: (-1.0, 0.95),
    NewsCategory.MAJOR_LAWSUIT: (-0.8, 0.85),
    NewsCategory.WHALE_MOVEMENT: (-0.5, 0.60),
    NewsCategory.ETF_DECISION: (0.0, 0.80),  # Could be + or -
    NewsCategory.MAJOR_PARTNERSHIP: (0.6, 0.75),
    NewsCategory.PROTOCOL_UPGRADE: (0.5, 0.70),
    NewsCategory.MARKET_ANALYSIS: (0.0, 0.40),
    NewsCategory.MINOR_PARTNERSHIP: (0.3, 0.50),
    NewsCategory.PRICE_PREDICTION: (0.0, 0.30),
    NewsCategory.EDUCATIONAL: (0.0, 0.20),
    NewsCategory.OPINION: (0.0, 0.20),
    NewsCategory.MINOR_UPDATE: (0.0, 0.15),
    NewsCategory.UNKNOWN: (0.0, 0.10),
}


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ClassificationResult:
    """Result of classifying a single news item."""

    severity: NewsSeverity
    category: NewsCategory
    sentiment: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0
    relevance: float  # 0.0 to 1.0
    source_reliability: float  # 0.0 to 1.0
    is_breaking: bool
    flags: tuple[str, ...] = ()  # Verification flags (e.g., "UNVERIFIED_CRITICAL")
    matched_keywords: tuple[str, ...] = ()
    decay_rate_minutes: int = 0  # Half-life for time decay


@dataclass(frozen=True)
class VerificationCheck:
    """A single verification check result."""

    name: str
    passed: bool
    required: bool  # If True and failed, item should be downgraded/suppressed
    flag: str = ""
    action: str = ""


@dataclass(frozen=True)
class VerificationResult:
    """Aggregate verification result."""

    verified: bool
    confidence: float
    flags: tuple[str, ...]
    checks: tuple[VerificationCheck, ...]


# ═══════════════════════════════════════════════════════════════════════
# KEYWORD TAXONOMY
# ═══════════════════════════════════════════════════════════════════════

_CRYPTO_CONTEXT = frozenset(
    {
        "crypto",
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "blockchain",
        "defi",
        "token",
        "coin",
        "exchange",
        "binance",
        "coinbase",
        "kraken",
        "okx",
        "bybit",
        "stablecoin",
        "usdt",
        "usdc",
        "dai",
        "web3",
        "nft",
        "altcoin",
        "mining",
        "staking",
        "wallet",
    }
)

# Patterns: list of (compiled_regex, context_required: bool)
_CRITICAL_PATTERNS: dict[NewsCategory, list[tuple[re.Pattern, bool]]] = {
    NewsCategory.EXCHANGE_COMPROMISE: [
        (re.compile(r"hack(?:ed|ing)?", re.I), True),
        (re.compile(r"exploit(?:ed|s)?", re.I), True),
        (re.compile(r"drained?", re.I), True),
        (re.compile(r"stolen", re.I), True),
        (re.compile(r"breach(?:ed)?", re.I), True),
        (re.compile(r"compromised?", re.I), True),
        (re.compile(r"hot\s*wallet.*(?:drain|hack|stolen)", re.I), False),
        (
            re.compile(
                r"(?:binance|coinbase|kraken|okx|bybit|ftx).*"
                r"(?:hack|exploit|breach|drain)",
                re.I,
            ),
            False,
        ),
        (re.compile(r"security\s+(?:incident|breach|vulnerability)", re.I), True),
    ],
    NewsCategory.REGULATORY_BAN: [
        (re.compile(r"(?:ban|bans|banned|prohibit(?:ed|s)?|outlaw(?:ed|s)?)", re.I), True),
        (re.compile(r"emergency\s+(?:order|action|measure)", re.I), True),
        (re.compile(r"SEC.*(?:sue|sues|sued|lawsuit|charges?|enforcement|action)", re.I), False),
        (re.compile(r"CFTC.*(?:sue|sues|sued|lawsuit|charges?|enforcement)", re.I), False),
        (
            re.compile(
                r"(?:china|india|russia|nigeria).*"
                r"(?:ban|bans|banned|prohibit).*"
                r"(?:crypto|bitcoin|mining|trading)",
                re.I,
            ),
            False,
        ),
        (re.compile(r"(?:crack\s*down|crackdown).*(?:crypto|bitcoin|exchange)", re.I), True),
    ],
    NewsCategory.STABLECOIN_DEPEG: [
        (
            re.compile(
                r"(?:USDT|USDC|DAI|BUSD|TUSD|FRAX).*(?:de-?peg|break|below\s+\$0\.\d+)", re.I
            ),
            False,
        ),
        (re.compile(r"stablecoin.*(?:crisis|fail|collapse|de-?peg|break)", re.I), False),
        (
            re.compile(
                r"(?:tether|circle).*(?:insolvency|bankruptcy|reserve.*fail|audit.*fail)", re.I
            ),
            False,
        ),
        (re.compile(r"(?:USDT|USDC).*\$(?:0\.[0-8]\d|0\.9[0-4])", re.I), False),
    ],
    NewsCategory.MAJOR_EXPLOIT: [
        (
            re.compile(
                r"(?:bridge|protocol|smart\s*contract|vault|pool).*(?:exploit|hack|drain|stolen)",
                re.I,
            ),
            False,
        ),
        (re.compile(r"\$[\d,]+\.?\d*[MBK]?.*(?:stolen|drained|exploited|hack|lost)", re.I), True),
        (
            re.compile(
                r"(?:flash\s*loan|reentrancy|oracle\s*manipulation|rug\s*pull).*(?:attack|exploit)",
                re.I,
            ),
            False,
        ),
        (re.compile(r"(?:multisig|governance).*(?:attack|compromise|takeover)", re.I), True),
        (re.compile(r"(?:infinite\s*approval|approval.*exploit)", re.I), True),
    ],
    NewsCategory.PROTOCOL_DEATH: [
        (
            re.compile(
                r"(?:collaps|fail|bankrupt|insolv|deceased|dead).*(?:protocol|project|token|coin)",
                re.I,
            ),
            True,
        ),
        (
            re.compile(
                r"(?:luna|terra|ftx|celsius|voyager|3ac|blockfi).*(?:collaps|fail|bankrupt)", re.I
            ),
            False,
        ),
        (re.compile(r"bankruptcy\s+(?:fil|protection|chapter)", re.I), True),
        (re.compile(r"(?:ponzi|fraud|scam).*(?:scheme|alleg|charge)", re.I), True),
    ],
}

_HIGH_PATTERNS: dict[NewsCategory, list[tuple[re.Pattern, bool]]] = {
    NewsCategory.ETF_DECISION: [
        (re.compile(r"ETF.*(?:approv|deni|reject|delay|ruling|decision|filing)", re.I), False),
        (re.compile(r"SEC.*ETF.*(?:approv|deni|pending|review)", re.I), False),
        (re.compile(r"(?:bitcoin|ethereum|crypto)\s+ETF", re.I), False),
        (re.compile(r"(?:spot|futures)\s+(?:bitcoin|ethereum|crypto)\s+ETF", re.I), False),
    ],
    NewsCategory.MAJOR_PARTNERSHIP: [
        (
            re.compile(
                r"(?:blackrock|fidelity|jpmorgan|goldman|sachs|visa|mastercard|paypal|"
                r"google|apple|microsoft|amazon|tesla).*(?:crypto|bitcoin|blockchain|web3)",
                re.I,
            ),
            False,
        ),
        (
            re.compile(
                r"(?:institutional|wall\s*street|fortune\s*500|s&p\s*500)."
                r"*(?:adopt|partner|invest|buy|acquire)",
                re.I,
            ),
            True,
        ),
        (
            re.compile(
                r"(?:sovereign\s+wealth|pension\s+fund|endowment).*(?:invest|buy|allocat)", re.I
            ),
            True,
        ),
    ],
    NewsCategory.PROTOCOL_UPGRADE: [
        (
            re.compile(r"(?:upgrade|hard\s*fork|soft\s*fork|merge|shanghai|cancun|pectra)", re.I),
            True,
        ),
        (re.compile(r"(?:EIP|BIP|SIP)-\d+.*(?:implement|activ|live|launch)", re.I), False),
        (re.compile(r"(?:mainnet|testnet).*(?:launch|deploy|go\s*live)", re.I), True),
        (re.compile(r"(?:layer\s*2|L2|rollup).*(?:launch|mainnet|upgrade)", re.I), True),
    ],
    NewsCategory.WHALE_MOVEMENT: [
        (re.compile(r"whale.*(?:mov|transfer|deposit|withdraw|send)", re.I), True),
        (
            re.compile(r"(?:satoshi|nakamoto|vitalik).*wallet.*(?:active|mov|transfer|wake)", re.I),
            False,
        ),
        (
            re.compile(
                r"(?:\d[\d,]*\.?\d*\s*(?:BTC|ETH|BTC)).*(?:exchange|binance|coinbase|deposit)", re.I
            ),
            False,
        ),
        (re.compile(r"(?:large|massive|巨鲸).*(?:transfer|mov|deposit).*(?:exchange)", re.I), True),
    ],
    NewsCategory.MAJOR_LAWSUIT: [
        (
            re.compile(
                r"(?:SEC|CFTC|DOJ|FBI).*(?:sue|sues|sued|lawsuit|charges?|indict|criminal)", re.I
            ),
            False,
        ),
        (re.compile(r"(?:class\s*action|lawsuit|litigation|legal\s+action)", re.I), True),
        (re.compile(r"(?:settl|verdict|ruling|judgment).*(?:\$\d|million|billion)", re.I), True),
    ],
}

_MEDIUM_PATTERNS: dict[NewsCategory, list[tuple[re.Pattern, bool]]] = {
    NewsCategory.MARKET_ANALYSIS: [
        (
            re.compile(
                r"(?:head\s*(?:and|&)\s*shoulders|double\s*(?:top|bottom)|cup\s*(?:and|&)\s*handle)",
                re.I,
            ),
            False,
        ),
        (re.compile(r"(?:support|resistance|breakout|breakdown|consolidat)", re.I), True),
        (re.compile(r"(?:bullish|bearish).*(?:pattern|signal|setup|outlook)", re.I), True),
        (re.compile(r"(?:undervalu|overvalu|fair\s*value|intrinsic)", re.I), True),
    ],
    NewsCategory.MINOR_PARTNERSHIP: [
        (re.compile(r"(?:partner|integrat|collaborat|alliance)", re.I), True),
        (re.compile(r"(?:list(?:ed|ing)?|launch(?:ed|ing)?).*(?:token|pair|market)", re.I), True),
    ],
    NewsCategory.PRICE_PREDICTION: [
        (re.compile(r"(?:predict|forecast|target|expect).*(?:\$\d|price)", re.I), True),
        (re.compile(r"(?:analyst|trader|expert).*(?:predict|forecast|see|expect)", re.I), True),
        (re.compile(r"(?:\d+x|\d+X).*(?:potential|return|gain)", re.I), True),
    ],
}

# Hype/P&D keywords
_HYPE_KEYWORDS = frozenset(
    {
        "100x",
        "10x",
        "1000x",
        "moon",
        "gem",
        "next bitcoin",
        "guaranteed",
        "risk-free",
        "easy money",
        "get rich",
        "pump",
        "to the moon",
        "send it",
        "ape",
        "yolo",
    }
)


# ═══════════════════════════════════════════════════════════════════════
# CLASSIFIER ENGINE
# ═══════════════════════════════════════════════════════════════════════


class NewsClassifier:
    """Classify crypto news into severity tiers with sentiment scoring.

    Two-pass classification:
      Pass 1: Keyword regex matching (instant, deterministic)
      Pass 2: LLM verification for CRITICAL items (prevents false vetoes)

    All methods are stateless — safe for concurrent use.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._source_reliability = {
            **SOURCE_RELIABILITY,
            **self._config.get("source_reliability", {}),
        }
        # Minimum sources required for CRITICAL to be acted upon
        self._min_sources_critical = self._config.get("min_sources_critical", 2)
        self._min_sources_high = self._config.get("min_sources_high", 1)

    def classify(
        self,
        title: str,
        content: str = "",
        source: str = "Unknown",
        published_at: datetime | None = None,
    ) -> ClassificationResult:
        """Classify a single news item.

        Args:
            title: News headline.
            content: Article body/summary (optional).
            source: News source name.
            published_at: Publication timestamp.

        Returns:
            ClassificationResult with severity, category, sentiment.
        """
        text = f"{title} {content}".strip()
        text_lower = text.lower()

        # Pass 1: Keyword classification
        category, severity, matched = self._keyword_classify(text, title)

        # Derive sentiment from category
        base_sentiment, base_confidence = CATEGORY_SENTIMENT.get(category, (0.0, 0.1))

        # Adjust sentiment for directional keywords
        sentiment = self._adjust_sentiment(base_sentiment, text_lower)

        # Source reliability
        reliability = self._source_reliability.get(source, 0.20)

        # Adjust confidence by source reliability
        confidence = base_confidence * reliability

        # Relevance to crypto
        relevance = self._compute_relevance(text_lower)

        # Is breaking (CRITICAL or HIGH with high confidence)
        is_breaking = severity in (NewsSeverity.CRITICAL, NewsSeverity.HIGH) and confidence > 0.6

        # Decay rate by severity
        decay_rates = {
            NewsSeverity.CRITICAL: 1440,  # 24h half-life
            NewsSeverity.HIGH: 360,  # 6h
            NewsSeverity.MEDIUM: 120,  # 2h
            NewsSeverity.LOW: 30,  # 30min
        }

        # Flags
        flags: list[str] = []
        if severity == NewsSeverity.CRITICAL and reliability < 0.5:
            flags.append("LOW_RELIABILITY_SOURCE")
        if any(w in text_lower for w in _HYPE_KEYWORDS):
            flags.append("HYPE_DETECTED")

        return ClassificationResult(
            severity=severity,
            category=category,
            sentiment=round(sentiment, 4),
            confidence=round(confidence, 4),
            relevance=round(relevance, 4),
            source_reliability=round(reliability, 4),
            is_breaking=is_breaking,
            flags=tuple(flags),
            matched_keywords=tuple(matched),
            decay_rate_minutes=decay_rates.get(severity, 60),
        )

    def classify_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[ClassificationResult]:
        """Classify a batch of news items.

        Args:
            items: List of dicts with keys: title, content, source, published_at.

        Returns:
            List of ClassificationResult, same order as input.
        """
        return [
            self.classify(
                title=item.get("title", ""),
                content=item.get("content", "") or item.get("summary", ""),
                source=item.get("source", "Unknown"),
                published_at=item.get("published_at"),
            )
            for item in items
        ]

    def verify_critical(
        self,
        classification: ClassificationResult,
        all_items: list[ClassificationResult],
        all_sources: list[str],
    ) -> VerificationResult:
        """Verify a CRITICAL classification.

        Multi-source verification: CRITICAL claims from a single
        low-reliability source are downgraded to HIGH until confirmed.

        Args:
            classification: The classification to verify.
            all_items: All classified items in the current window.
            all_sources: Sources that reported the same event.

        Returns:
            VerificationResult with verification status and flags.
        """
        checks: list[VerificationCheck] = []

        # Check 1: Multi-source (required for CRITICAL)
        if classification.severity == NewsSeverity.CRITICAL:
            reliable_sources = [
                s for s in all_sources if self._source_reliability.get(s, 0.2) >= 0.70
            ]
            multi_source = len(set(reliable_sources)) >= self._min_sources_critical
            checks.append(
                VerificationCheck(
                    name="multi_source",
                    passed=multi_source,
                    required=True,
                    flag="" if multi_source else "UNVERIFIED_CRITICAL",
                    action="" if multi_source else "DOWNGRADE_TO_HIGH",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    name="multi_source",
                    passed=True,
                    required=False,
                )
            )

        # Check 2: Source reliability (any Tier 1 source)
        has_tier1 = any(self._source_reliability.get(s, 0) >= 0.85 for s in all_sources)
        checks.append(
            VerificationCheck(
                name="tier1_source",
                passed=has_tier1,
                required=False,
                flag="" if has_tier1 else "NO_TIER1_COVERAGE",
            )
        )

        # Check 3: Coordinated FUD detection
        is_fud = self._detect_coordinated_fud(all_items)
        checks.append(
            VerificationCheck(
                name="coordinated_fud",
                passed=not is_fud,
                required=True,
                flag="" if not is_fud else "COORDINATED_FUD",
                action="" if not is_fud else "SUPPRESS",
            )
        )

        # Check 4: Hype/P&D detection
        has_hype = any("HYPE_DETECTED" in c.flags for c in all_items)
        if has_hype and not has_tier1:
            checks.append(
                VerificationCheck(
                    name="pump_and_dump",
                    passed=False,
                    required=False,
                    flag="PUMP_AND_DUMP_SIGNAL",
                    action="SUPPRESS",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    name="pump_and_dump",
                    passed=True,
                    required=False,
                )
            )

        # Aggregate
        required_checks = [c for c in checks if c.required]
        all_required_passed = all(c.passed for c in required_checks)
        flags = tuple(c.flag for c in checks if c.flag and not c.passed)
        confidence = sum(1.0 for c in checks if c.passed) / len(checks) if checks else 0.0

        return VerificationResult(
            verified=all_required_passed,
            confidence=round(confidence, 4),
            flags=flags,
            checks=tuple(checks),
        )

    # ── Private Methods ──────────────────────────────────────────────

    def _keyword_classify(
        self,
        text: str,
        title: str,
    ) -> tuple[NewsCategory, NewsSeverity, list[str]]:
        """Pass 1: Keyword-based classification."""
        matched: list[str] = []

        # Check CRITICAL patterns first
        for category, patterns in _CRITICAL_PATTERNS.items():
            for pattern, need_context in patterns:
                if pattern.search(text):
                    if need_context:
                        # Require crypto context words nearby
                        if not any(kw in text.lower() for kw in _CRYPTO_CONTEXT):
                            continue
                    matched.append(pattern.pattern)
                    return category, NewsSeverity.CRITICAL, matched

        # Check HIGH patterns
        for category, patterns in _HIGH_PATTERNS.items():
            for pattern, need_context in patterns:
                if pattern.search(text):
                    if need_context and not any(kw in text.lower() for kw in _CRYPTO_CONTEXT):
                        continue
                    matched.append(pattern.pattern)
                    return category, NewsSeverity.HIGH, matched

        # Check MEDIUM patterns
        for category, patterns in _MEDIUM_PATTERNS.items():
            for pattern, need_context in patterns:
                if pattern.search(text):
                    if need_context and not any(kw in text.lower() for kw in _CRYPTO_CONTEXT):
                        continue
                    matched.append(pattern.pattern)
                    return category, NewsSeverity.MEDIUM, matched

        # Default: LOW / UNKNOWN
        return NewsCategory.UNKNOWN, NewsSeverity.LOW, []

    @staticmethod
    def _adjust_sentiment(base_sentiment: float, text_lower: str) -> float:
        """Adjust sentiment based on directional keywords in text."""
        bullish_words = {
            "surge",
            "rally",
            "bullish",
            "rise",
            "gain",
            "jump",
            "soar",
            "breakout",
            "record",
            "high",
            "adoption",
            "approval",
            "approve",
            "approved",
            "approves",
            "launch",
            "upgrade",
            "milestone",
            "growth",
            "positive",
        }
        bearish_words = {
            "crash",
            "drop",
            "fall",
            "bearish",
            "plunge",
            "decline",
            "hack",
            "exploit",
            "ban",
            "regulation",
            "lawsuit",
            "fraud",
            "bankruptcy",
            "sell-off",
            "dump",
            "fear",
            "concern",
            "negative",
        }

        words = set(re.findall(r"\b\w+\b", text_lower))
        bullish_hits = len(words & bullish_words)
        bearish_hits = len(words & bearish_words)

        if bullish_hits + bearish_hits == 0:
            return base_sentiment

        keyword_sentiment = (bullish_hits - bearish_hits) / (bullish_hits + bearish_hits)

        # Blend: 70% category-derived, 30% keyword
        blended = base_sentiment * 0.7 + keyword_sentiment * 0.3
        return max(-1.0, min(1.0, blended))

    @staticmethod
    def _compute_relevance(text_lower: str) -> float:
        """Compute relevance to crypto markets (0-1)."""
        crypto_hits = sum(1 for kw in _CRYPTO_CONTEXT if kw in text_lower)
        if crypto_hits >= 3:
            return 1.0
        elif crypto_hits >= 2:
            return 0.8
        elif crypto_hits >= 1:
            return 0.6
        else:
            return 0.2

    @staticmethod
    def _detect_coordinated_fud(items: list[ClassificationResult]) -> bool:
        """Detect coordinated FUD campaigns.

        Signals:
        - 3+ items with LOW reliability sources
        - All negative sentiment
        - No items with source_reliability >= 0.85
        """
        if len(items) < 3:
            return False

        negative_low = [i for i in items if i.sentiment < -0.3 and i.source_reliability < 0.50]
        tier1 = [i for i in items if i.source_reliability >= 0.85]

        return len(negative_low) >= 3 and len(tier1) == 0


# ═══════════════════════════════════════════════════════════════════════
# TIME DECAY UTILITY
# ═══════════════════════════════════════════════════════════════════════


def apply_time_decay(
    sentiment: float,
    age_minutes: int,
    half_life_minutes: int,
) -> float:
    """Apply exponential time decay to a sentiment score.

    Args:
        sentiment: Original sentiment (-1 to +1).
        age_minutes: How old the news is in minutes.
        half_life_minutes: Half-life for the decay curve.

    Returns:
        Decayed sentiment (magnitude reduced by age).
    """
    if half_life_minutes <= 0:
        return sentiment
    decay_factor = 0.5 ** (age_minutes / half_life_minutes)
    return sentiment * decay_factor
