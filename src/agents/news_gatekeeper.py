"""TSAR — News Gatekeeper Agent.

THE news veto authority. Decides whether news conditions allow trading.

Authority:
  - Can veto ANY trade regardless of technicals, sentiment, or on-chain signals.
  - CRITICAL news = NUCLEAR veto. No override except admin manual ack.
  - HIGH news = HARD veto on new entries.
  - Vetoes decay automatically after configured durations.

Architecture:
  NewsMonitor → [NewsGatekeeper] → RiskGuardian → ExecutionSniper

Subscribes to: tsar:stream:news
Publishes to:  tsar:stream:signals (veto events)
               tsar:stream:news_classified (enriched news for SQF)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.agents.base import BaseAgent
from src.tools.news_classifier import (
    ClassificationResult,
    NewsCategory,
    NewsClassifier,
    NewsSeverity,
    apply_time_decay,
)
from src.tools.news_velocity import (
    NewsVelocityDetector,
    VelocityConfig,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


class VetoLevel(StrEnum):
    """News-triggered veto levels."""

    EMERGENCY = "emergency"  # CRITICAL news → Kill switch, all symbols
    SYMBOL_BLOCK = "symbol_block"  # HIGH news → Block specific symbol
    ENTRY_BLOCK = "entry_block"  # MEDIUM-HIGH → Block new entries only
    ALERT = "alert"  # MEDIUM → Warning, reduce size
    CLEAR = "clear"  # Veto expired or lifted


@dataclass
class VetoRecord:
    """An active veto with expiry tracking."""

    veto_id: str
    symbol: str
    level: VetoLevel
    reason: str
    category: NewsCategory
    severity: NewsSeverity
    issued_at: float  # time.time()
    expires_at: float  # time.time()
    source_articles: list[str] = field(default_factory=list)
    override_requested: bool = False
    override_approved: bool = False

    @property
    def is_active(self) -> bool:
        """Check if veto is still active (not expired, not overridden)."""
        if self.override_approved:
            return False
        return time.time() < self.expires_at

    @property
    def remaining_seconds(self) -> float:
        """Seconds until veto expires."""
        return max(0.0, self.expires_at - time.time())


@dataclass
class GatekeeperDecision:
    """Decision output from the NewsGatekeeper."""

    symbol: str
    allowed: bool
    veto_level: VetoLevel
    reason: str
    active_vetoes: list[VetoRecord]
    news_sentiment: float  # -1.0 to +1.0 (time-decayed)
    news_confidence: float  # 0.0 to 1.0
    highest_severity: NewsSeverity
    velocity_action: str  # "NORMAL", "ALERT", "VETO", "AMPLIFY"
    timestamp: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
# DEFAULT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

_DEFAULT_VETO_DURATIONS: dict[VetoLevel, int] = {
    VetoLevel.EMERGENCY: 3600,  # 1 hour minimum for CRITICAL
    VetoLevel.SYMBOL_BLOCK: 1800,  # 30 min for HIGH
    VetoLevel.ENTRY_BLOCK: 900,  # 15 min for MEDIUM-HIGH
    VetoLevel.ALERT: 300,  # 5 min advisory
}

_SEVERITY_VETO_MAP: dict[NewsSeverity, VetoLevel] = {
    NewsSeverity.CRITICAL: VetoLevel.EMERGENCY,
    NewsSeverity.HIGH: VetoLevel.SYMBOL_BLOCK,
    NewsSeverity.MEDIUM: VetoLevel.ALERT,
    NewsSeverity.LOW: VetoLevel.CLEAR,
}


# ═══════════════════════════════════════════════════════════════════════
# NEWS GATEKEEPER AGENT
# ═══════════════════════════════════════════════════════════════════════


class NewsGatekeeper(BaseAgent):
    """News gatekeeper — THE veto authority for news-driven risk.

    Evaluates classified news and velocity signals to decide
    whether trading is safe. Issues, tracks, and expires vetoes.

    Authority:
      - CRITICAL news → EMERGENCY veto (all symbols, NUCLEAR level)
      - HIGH news → SYMBOL_BLOCK or ENTRY_BLOCK
      - Velocity avalanche (bearish) → EMERGENCY veto
      - Vetoes decay automatically

    Subscribes to: tsar:stream:news
    Publishes to:  tsar:stream:signals (veto events)
                   tsar:stream:news_classified (enriched sentiment for SQF)
    """

    AGENT_NAME = "news_gatekeeper"
    ROLE = "TRADE_ADMIN"

    PUBLISH_STREAM = "signals"
    SUBSCRIBE_STREAMS = ["news"]

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        **kwargs: Any,
    ) -> None:
        super().__init__(config, trading_mode, **kwargs)

        gk_config = config.get("news_gatekeeper", {})

        # Sub-components
        self._classifier = NewsClassifier(config=gk_config)
        velocity_config = VelocityConfig(
            avalanche_threshold=gk_config.get("velocity", {}).get("avalanche_threshold", 5),
            avalanche_window_minutes=gk_config.get("velocity", {}).get(
                "avalanche_window_minutes", 60
            ),
            silence_threshold_hours=gk_config.get("velocity", {}).get(
                "silence_threshold_hours", 24
            ),
            shift_threshold=gk_config.get("velocity", {}).get("sentiment_shift_threshold", 0.3),
        )
        self._velocity_detector = NewsVelocityDetector(config=velocity_config)

        # Veto durations (configurable)
        self._veto_durations: dict[VetoLevel, int] = {
            **_DEFAULT_VETO_DURATIONS,
            **{VetoLevel(k): v for k, v in gk_config.get("veto_durations", {}).items()},
        }

        # State
        self._active_vetoes: dict[str, VetoRecord] = {}  # veto_id → VetoRecord
        self._symbol_vetoes: dict[str, list[str]] = {}  # symbol → [veto_ids]
        self._global_vetoes: list[str] = []  # veto_ids for all-symbol vetoes
        self._last_classifications: list[ClassificationResult] = []
        self._last_velocity_report = None

        # Stats
        self._total_vetoes_issued = 0
        self._total_vetoes_expired = 0
        self._total_signals_blocked = 0

        logger.info("NewsGatekeeper initialized")

    async def on_initialize(self) -> None:
        logger.info("NewsGatekeeper ready — monitoring news stream")

    async def on_shutdown(self) -> None:
        logger.info(
            "NewsGatekeeper shutting down: %d active vetoes, %d total issued, %d total expired",
            len(self._active_vetoes),
            self._total_vetoes_issued,
            self._total_vetoes_expired,
        )

    # ── Event Handling ───────────────────────────────────────────────

    async def handle_event(self, stream: str, event: Any) -> None:
        """Handle incoming news events from the news stream."""
        if stream != "news":
            return

        data = event.data if hasattr(event, "data") else event
        await self._evaluate_news(data)

    async def run_cycle(self) -> None:
        """Periodic maintenance: expire old vetoes, log status."""
        self._expire_vetoes()

        if self._active_vetoes:
            logger.info(
                "NewsGatekeeper: %d active vetoes (%d global, %d symbol-specific)",
                len(self._active_vetoes),
                len(self._global_vetoes),
                sum(len(v) for v in self._symbol_vetoes.values()),
            )

    # ── Core Evaluation ──────────────────────────────────────────────

    async def _evaluate_news(self, news_data: dict[str, Any]) -> None:
        """Core evaluation: classify news, detect velocity, issue vetoes.

        This is the main decision path. Every news update flows through here.
        """
        raw_items = news_data.get("items", [])

        # Step 1: Classify all items
        classifications = self._classifier.classify_batch(raw_items)
        self._last_classifications = classifications

        # Step 2: Run velocity analysis
        velocity_items = [
            {
                "sentiment": c.sentiment,
                "source": raw_items[i].get("source", "Unknown")
                if i < len(raw_items)
                else "Unknown",
                "age_minutes": raw_items[i].get("age_minutes", 0) if i < len(raw_items) else 0,
                "published_at": raw_items[i].get("published_at") if i < len(raw_items) else None,
            }
            for i, c in enumerate(classifications)
        ]
        velocity_report = self._velocity_detector.analyze(velocity_items)
        self._last_velocity_report = velocity_report

        # Step 3: Process CRITICAL items
        critical_items = [
            (c, raw_items[i] if i < len(raw_items) else {})
            for i, c in enumerate(classifications)
            if c.severity == NewsSeverity.CRITICAL
        ]

        for classification, raw in critical_items:
            # Verify CRITICAL (multi-source check)
            sources = [r.get("source", "Unknown") for r in raw_items]
            verification = self._classifier.verify_critical(
                classification,
                classifications,
                sources,
            )

            if verification.verified:
                await self._issue_veto(
                    symbol=raw.get("symbol", "ALL"),
                    level=VetoLevel.EMERGENCY,
                    reason=f"CRITICAL: {classification.category.value}",
                    category=classification.category,
                    severity=classification.severity,
                    articles=[raw.get("title", "")],
                )
            else:
                # Downgrade to HIGH if unverified
                logger.warning(
                    "CRITICAL news downgraded to HIGH (unverified): %s flags=%s",
                    raw.get("title", ""),
                    verification.flags,
                )
                await self._issue_veto(
                    symbol=raw.get("symbol", "ALL"),
                    level=VetoLevel.SYMBOL_BLOCK,
                    reason=f"HIGH (downgraded from CRITICAL): {classification.category.value}",
                    category=classification.category,
                    severity=NewsSeverity.HIGH,
                    articles=[raw.get("title", "")],
                )

        # Step 4: Process HIGH items
        high_items = [
            (c, raw_items[i] if i < len(raw_items) else {})
            for i, c in enumerate(classifications)
            if c.severity == NewsSeverity.HIGH
        ]

        for classification, raw in high_items:
            await self._issue_veto(
                symbol=raw.get("symbol", "ALL"),
                level=VetoLevel.SYMBOL_BLOCK,
                reason=f"HIGH: {classification.category.value}",
                category=classification.category,
                severity=classification.severity,
                articles=[raw.get("title", "")],
            )

        # Step 5: Process velocity signals
        if velocity_report.avalanche.detected:
            if velocity_report.avalanche.severity == "emergency":
                await self._issue_veto(
                    symbol=news_data.get("symbol", "ALL"),
                    level=VetoLevel.EMERGENCY,
                    reason=f"VELOCITY: {velocity_report.avalanche.description}",
                    category=NewsCategory.MARKET_ANALYSIS,
                    severity=NewsSeverity.CRITICAL,
                    articles=[],
                )

        # Step 6: Publish enriched news for downstream (SQF)
        await self._publish_classified_news(classifications, velocity_report)

    # ── Veto Management ──────────────────────────────────────────────

    async def _issue_veto(
        self,
        symbol: str,
        level: VetoLevel,
        reason: str,
        category: NewsCategory,
        severity: NewsSeverity,
        articles: list[str],
    ) -> None:
        """Issue a new veto. Deduplicates against existing active vetoes."""
        # Dedup: don't issue duplicate vetoes for same category+symbol
        existing = self._find_active_veto(symbol, category)
        if existing:
            logger.debug(
                "Veto already active for %s/%s, extending if needed",
                symbol,
                category.value,
            )
            # Extend if new veto has longer duration
            duration = self._veto_durations.get(level, 300)
            new_expiry = time.time() + duration
            if new_expiry > existing.expires_at:
                existing.expires_at = new_expiry
                logger.info("Extended veto %s to %ds", existing.veto_id, duration)
            return

        # Create new veto
        veto_id = f"veto_{int(time.time())}_{category.value}"
        duration = self._veto_durations.get(level, 300)

        veto = VetoRecord(
            veto_id=veto_id,
            symbol=symbol,
            level=level,
            reason=reason,
            category=category,
            severity=severity,
            issued_at=time.time(),
            expires_at=time.time() + duration,
            source_articles=articles,
        )

        self._active_vetoes[veto_id] = veto
        self._total_vetoes_issued += 1

        # Index by symbol
        if symbol == "ALL":
            self._global_vetoes.append(veto_id)
        else:
            if symbol not in self._symbol_vetoes:
                self._symbol_vetoes[symbol] = []
            self._symbol_vetoes[symbol].append(veto_id)

        logger.warning(
            "🚨 VETO ISSUED [%s]: %s — %s (expires in %ds)",
            level.value,
            symbol,
            reason,
            duration,
        )

        # Publish veto event
        await self.publish_event(
            stream="signals",
            event_type="tsar.news.veto.v1",
            data={
                "veto_id": veto_id,
                "symbol": symbol,
                "level": level.value,
                "reason": reason,
                "category": category.value,
                "severity": severity.value,
                "expires_in_seconds": duration,
                "articles": articles[:5],
            },
            priority=0 if level == VetoLevel.EMERGENCY else 1,
            risk_level="NUCLEAR" if level == VetoLevel.EMERGENCY else "HARD",
        )

    def _expire_vetoes(self) -> None:
        """Remove expired vetoes."""
        time.time()
        expired_ids = [vid for vid, veto in self._active_vetoes.items() if not veto.is_active]

        for vid in expired_ids:
            veto = self._active_vetoes.pop(vid)
            self._total_vetoes_expired += 1

            # Remove from indexes
            if vid in self._global_vetoes:
                self._global_vetoes.remove(vid)
            for sym_vids in self._symbol_vetoes.values():
                if vid in sym_vids:
                    sym_vids.remove(vid)

            logger.info(
                "Veto expired: %s — %s (%s)",
                vid,
                veto.reason,
                veto.symbol,
            )

    def _find_active_veto(
        self,
        symbol: str,
        category: NewsCategory,
    ) -> VetoRecord | None:
        """Find an active veto for the given symbol and category."""
        for veto in self._active_vetoes.values():
            if (
                veto.is_active
                and veto.category == category
                and (veto.symbol == symbol or veto.symbol == "ALL")
            ):
                return veto
        return None

    # ── Public API (for RiskGuardian integration) ────────────────────

    def check_trade_allowed(
        self,
        symbol: str,
        side: str = "buy",
    ) -> GatekeeperDecision:
        """Check if a trade is allowed given current news conditions.

        Called by RiskGuardian before executing any trade.

        Args:
            symbol: Asset symbol (e.g. "BTC/USDT").
            side: Trade direction ("buy" or "sell").

        Returns:
            GatekeeperDecision with allow/deny and reasoning.
        """
        base_symbol = symbol.split("/")[0].upper()

        # Check global vetoes (all symbols)
        active_global = [
            self._active_vetoes[vid]
            for vid in self._global_vetoes
            if vid in self._active_vetoes and self._active_vetoes[vid].is_active
        ]

        # Check symbol-specific vetoes
        symbol_vids = self._symbol_vetoes.get(base_symbol, [])
        active_symbol = [
            self._active_vetoes[vid]
            for vid in symbol_vids
            if vid in self._active_vetoes and self._active_vetoes[vid].is_active
        ]

        all_active = active_global + active_symbol

        if not all_active:
            return GatekeeperDecision(
                symbol=base_symbol,
                allowed=True,
                veto_level=VetoLevel.CLEAR,
                reason="No active news vetoes",
                active_vetoes=[],
                news_sentiment=self._compute_decayed_sentiment(),
                news_confidence=self._compute_confidence(),
                highest_severity=NewsSeverity.LOW,
                velocity_action=getattr(self._last_velocity_report, "recommended_action", "NORMAL"),
                timestamp=datetime.now(UTC),
            )

        # Find highest severity active veto
        highest = max(all_active, key=lambda v: _severity_rank(v.severity))

        return GatekeeperDecision(
            symbol=base_symbol,
            allowed=False,
            veto_level=highest.level,
            reason=highest.reason,
            active_vetoes=all_active,
            news_sentiment=self._compute_decayed_sentiment(),
            news_confidence=self._compute_confidence(),
            highest_severity=highest.severity,
            velocity_action=getattr(self._last_velocity_report, "recommended_action", "NORMAL"),
            timestamp=datetime.now(UTC),
        )

    def get_active_vetoes(self) -> list[VetoRecord]:
        """Get all currently active vetoes."""
        self._expire_vetoes()
        return [v for v in self._active_vetoes.values() if v.is_active]

    def get_news_sentiment_for_symbol(self, symbol: str) -> float:
        """Get time-decayed news sentiment for SQF integration."""
        return self._compute_decayed_sentiment()

    def override_veto(self, veto_id: str, admin_reason: str) -> bool:
        """Admin override for a specific veto. Returns True if successful."""
        veto = self._active_vetoes.get(veto_id)
        if not veto:
            return False

        if veto.level == VetoLevel.EMERGENCY:
            logger.warning(
                "⚠️ ADMIN OVERRIDE of EMERGENCY veto: %s — %s (reason: %s)",
                veto_id,
                veto.reason,
                admin_reason,
            )

        veto.override_approved = True
        veto.override_requested = True
        return True

    # ── Sentiment Computation (for SQF) ──────────────────────────────

    def _compute_decayed_sentiment(self) -> float:
        """Compute time-decayed weighted sentiment from recent classifications."""
        if not self._last_classifications:
            return 0.0

        time.time()
        weighted_sum = 0.0
        total_weight = 0.0

        for c in self._last_classifications:
            # Apply time decay
            age_minutes = 0  # Would need actual age from raw items
            decayed = apply_time_decay(
                c.sentiment,
                age_minutes,
                c.decay_rate_minutes,
            )

            # Weight by severity and source reliability
            severity_weight = {
                NewsSeverity.CRITICAL: 10.0,
                NewsSeverity.HIGH: 3.0,
                NewsSeverity.MEDIUM: 1.0,
                NewsSeverity.LOW: 0.1,
            }.get(c.severity, 0.1)

            weight = severity_weight * c.source_reliability * c.confidence
            weighted_sum += decayed * weight
            total_weight += weight

        if total_weight > 0:
            return max(-1.0, min(1.0, weighted_sum / total_weight))
        return 0.0

    def _compute_confidence(self) -> float:
        """Compute aggregate confidence from recent classifications."""
        if not self._last_classifications:
            return 0.0
        return sum(c.confidence for c in self._last_classifications) / len(
            self._last_classifications
        )

    # ── Publishing ───────────────────────────────────────────────────

    async def _publish_classified_news(
        self,
        classifications: list[ClassificationResult],
        velocity_report: Any,
    ) -> None:
        """Publish enriched news data for downstream consumers (SQF)."""
        # Compute aggregate sentiment
        sentiment = self._compute_decayed_sentiment()
        confidence = self._compute_confidence()

        # Highest severity in batch
        highest = max(
            (c.severity for c in classifications),
            key=_severity_rank,
            default=NewsSeverity.LOW,
        )

        await self.publish_event(
            stream="news_classified",
            event_type="tsar.news.classified.v1",
            data={
                "item_count": len(classifications),
                "overall_sentiment": round(sentiment, 4),
                "confidence": round(confidence, 4),
                "highest_severity": highest.value,
                "severity_breakdown": {
                    s.value: sum(1 for c in classifications if c.severity == s)
                    for s in NewsSeverity
                },
                "velocity": {
                    "action": velocity_report.recommended_action,
                    "is_unusual": velocity_report.is_unusual,
                    "avalanche_detected": velocity_report.avalanche.detected,
                    "silence_detected": velocity_report.silence.detected,
                },
                "active_veto_count": len(self._active_vetoes),
                "timestamp": datetime.now(UTC).isoformat(),
            },
            priority=2,
            risk_level="NONE",
        )


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _severity_rank(severity: NewsSeverity) -> int:
    """Numeric rank for severity comparison (higher = more severe)."""
    return {
        NewsSeverity.LOW: 0,
        NewsSeverity.MEDIUM: 1,
        NewsSeverity.HIGH: 2,
        NewsSeverity.CRITICAL: 3,
    }.get(severity, 0)
