"""
TSAR — LLM News Verification Layer.

Verifies CRITICAL news items using the LLM router before they
trigger trading halts. This prevents false positives from
FUD, fake news, or misclassified articles.

Flow:
  1. NewsClassifier tags an item as CRITICAL
  2. LLMNewsVerifier.verify() is called before the veto takes effect
  3. LLM cross-references the claim, checks for corroboration
  4. Returns verification result with confidence score
  5. Results are cached to avoid redundant LLM calls

Uses the router's generate() with a dedicated task_type for
news verification. Falls back to allowing the news through
if LLM verification fails (fail-open for safety).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


class VerificationStatus(StrEnum):
    """Result of LLM verification."""

    VERIFIED = "verified"         # LLM confirms the news is credible
    UNVERIFIED = "unverified"     # LLM cannot confirm or deny
    DISPUTED = "disputed"         # LLM found contradicting information
    FALSE_POSITIVE = "false_positive"  # LLM believes this is false/FUD
    FAILED = "failed"             # LLM verification itself failed (error)


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying a news item.

    Attributes:
        status: Verification outcome.
        confidence: LLM's confidence in its assessment (0-1).
        reasoning: LLM's explanation.
        corroborating_sources: Sources that corroborate the claim.
        contradicting_sources: Sources that contradict the claim.
        verification_time_ms: How long verification took.
        cached: Whether this result was from cache.
    """

    status: VerificationStatus
    confidence: float
    reasoning: str
    corroborating_sources: tuple[str, ...] = ()
    contradicting_sources: tuple[str, ...] = ()
    verification_time_ms: float = 0.0
    cached: bool = False


# ═══════════════════════════════════════════════════════════════════════
# VERIFICATION PROMPTS
# ═══════════════════════════════════════════════════════════════════════

_VERIFICATION_SYSTEM_PROMPT = """You are a crypto news verification analyst. Your job is to assess whether a news item is credible, exaggerated, or false/FUD.

For each news item, you must:
1. Assess the plausibility of the claim based on your knowledge
2. Check if the source is known and credible
3. Identify any red flags (unrealistic amounts, unknown sources, suspicious timing)
4. Determine if this could be market manipulation or FUD

Respond in this exact JSON format:
{
  "status": "verified|unverified|disputed|false_positive",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of your assessment",
  "corroborating_factors": ["factor1", "factor2"],
  "contradicting_factors": ["factor1", "factor2"],
  "red_flags": ["flag1", "flag2"]
}"""

_VERIFICATION_PROMPT_TEMPLATE = """Verify this crypto news item:

Title: {title}
Source: {source}
Summary: {summary}
Published: {published_at}
Claimed Impact: {severity}

Context:
- This news was classified as {severity} severity
- It mentions: {affected_assets}
- Sentiment score: {sentiment}

Is this news credible? Could it be FUD, fake news, or market manipulation?
Assess based on your knowledge of the crypto space."""


# ═══════════════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════════════


class _VerificationCache:
    """In-memory cache for verification results with TTL."""

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 500) -> None:
        self._cache: dict[str, tuple[float, VerificationResult]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size

    def _make_key(self, title: str, source: str, summary: str) -> str:
        """Create a deterministic cache key from news content."""
        content = f"{title}|{source}|{summary}".lower().strip()
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get(self, title: str, source: str, summary: str) -> VerificationResult | None:
        """Get cached verification result."""
        key = self._make_key(title, source, summary)
        if key in self._cache:
            ts, result = self._cache[key]
            if time.time() - ts < self._ttl:
                # Return with cached=True flag
                return VerificationResult(
                    status=result.status,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    corroborating_sources=result.corroborating_sources,
                    contradicting_sources=result.contradicting_sources,
                    verification_time_ms=result.verification_time_ms,
                    cached=True,
                )
            del self._cache[key]
        return None

    def set(self, title: str, source: str, summary: str, result: VerificationResult) -> None:
        """Store verification result in cache."""
        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]

        key = self._make_key(title, source, summary)
        self._cache[key] = (time.time(), result)

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


# ═══════════════════════════════════════════════════════════════════════
# LLM NEWS VERIFIER
# ═══════════════════════════════════════════════════════════════════════


class LLMNewsVerifier:
    """Verifies CRITICAL news items using the LLM router.

    Integrates with the TSAR ModelRouter to use LLM-based verification
    for high-severity news before trading vetoes take effect.

    The verifier is fail-open: if LLM verification fails, the news
    is allowed through (better to trade on false news than miss a
    real exploit).

    Usage:
        verifier = LLMNewsVerifier(router=model_router)
        result = await verifier.verify(news_item)
        if result.status == "false_positive":
            print("FUD detected, ignoring")
    """

    description = (
        "LLM news verification: CRITICAL news cross-checking, "
        "FUD detection, source credibility assessment"
    )

    def __init__(
        self,
        router: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._router = router
        self._config = config or {}
        self._cache = _VerificationCache(
            ttl_seconds=self._config.get("verification_cache_ttl", 3600),
            max_size=self._config.get("verification_cache_max", 500),
        )

        # Task type for LLM verification (configurable)
        self._task_type = self._config.get(
            "verification_task_type",
            "t4_news_verification",
        )

        # Whether to fail-open or fail-closed
        self._fail_open = self._config.get("verification_fail_open", True)

    # ── Public API ───────────────────────────────────────────────────

    async def verify(
        self,
        title: str,
        source: str,
        summary: str = "",
        severity: str = "CRITICAL",
        affected_assets: tuple[str, ...] = (),
        sentiment: float = 0.0,
        published_at: str = "",
    ) -> VerificationResult:
        """Verify a news item using the LLM router.

        Args:
            title: News headline.
            source: News source name.
            summary: Article summary.
            severity: Classified severity level.
            affected_assets: Tokens/projects affected.
            sentiment: Article sentiment score.
            published_at: Publication timestamp string.

        Returns:
            VerificationResult with status and confidence.
        """
        start_time = time.monotonic()

        # Check cache first
        cached = self._cache.get(title, source, summary)
        if cached:
            return cached

        # If no router available, return unverified
        if self._router is None:
            logger.warning("No LLM router configured — returning unverified")
            return VerificationResult(
                status=VerificationStatus.UNVERIFIED,
                confidence=0.0,
                reasoning="LLM router not configured",
                verification_time_ms=0.0,
            )

        # Build verification prompt
        prompt = _VERIFICATION_PROMPT_TEMPLATE.format(
            title=title,
            source=source,
            summary=summary or "No summary available",
            published_at=published_at or "Unknown",
            severity=severity,
            affected_assets=", ".join(affected_assets) if affected_assets else "None specified",
            sentiment=f"{sentiment:.2f}",
        )

        try:
            # Call LLM router
            response = await self._router.generate(
                task_type=self._task_type,
                prompt=prompt,
                system_prompt=_VERIFICATION_SYSTEM_PROMPT,
                temperature=0.1,  # Low temperature for consistent verification
                max_tokens=500,
            )

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Parse LLM response
            result = self._parse_verification_response(
                response.content if hasattr(response, 'content') else str(response),
                elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error("LLM verification failed: %s", exc)

            if self._fail_open:
                # Fail-open: allow the news through
                result = VerificationResult(
                    status=VerificationStatus.UNVERIFIED,
                    confidence=0.0,
                    reasoning=f"Verification failed: {exc}. Failing open.",
                    verification_time_ms=elapsed_ms,
                )
            else:
                result = VerificationResult(
                    status=VerificationStatus.FAILED,
                    confidence=0.0,
                    reasoning=f"Verification failed: {exc}",
                    verification_time_ms=elapsed_ms,
                )

        # Cache the result
        self._cache.set(title, source, summary, result)
        return result

    async def verify_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[VerificationResult]:
        """Verify multiple news items.

        Args:
            items: List of dicts with keys matching verify() parameters.

        Returns:
            List of VerificationResult, one per input item.
        """
        import asyncio

        tasks = [
            self.verify(**item) for item in items
        ]

        return await asyncio.gather(*tasks, return_exceptions=False)

    def should_verify(self, severity: str, source: str = "") -> bool:
        """Determine if a news item needs LLM verification.

        Only CRITICAL items are verified to minimize LLM costs.

        Args:
            severity: News severity level.
            source: News source name.

        Returns:
            True if verification is needed.
        """
        # Only verify CRITICAL items
        if severity.upper() != "CRITICAL":
            return False

        # Skip verification for highly trusted sources
        trusted_sources = {"SEC", "CFTC", "Reuters", "Bloomberg"}
        if source in trusted_sources:
            return False

        return True

    # ── Response Parsing ─────────────────────────────────────────────

    def _parse_verification_response(
        self,
        response_text: str,
        elapsed_ms: float,
    ) -> VerificationResult:
        """Parse the LLM's verification response."""
        try:
            # Try to extract JSON from the response
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)

            # Map status string to enum
            status_str = data.get("status", "unverified").lower()
            status_map = {
                "verified": VerificationStatus.VERIFIED,
                "unverified": VerificationStatus.UNVERIFIED,
                "disputed": VerificationStatus.DISPUTED,
                "false_positive": VerificationStatus.FALSE_POSITIVE,
            }
            status = status_map.get(status_str, VerificationStatus.UNVERIFIED)

            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            reasoning = data.get("reasoning", "No reasoning provided")
            corroborating = tuple(data.get("corroborating_factors", []))
            contradicting = tuple(data.get("contradicting_factors", []))

            return VerificationResult(
                status=status,
                confidence=confidence,
                reasoning=reasoning,
                corroborating_sources=corroborating,
                contradicting_sources=contradicting,
                verification_time_ms=elapsed_ms,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to parse verification response: %s", exc)

            # Fallback: try to infer from raw text
            return self._fallback_parse(response_text, elapsed_ms)

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON object from text that may contain other content."""
        # Try direct parse first
        text = text.strip()
        if text.startswith("{"):
            return text

        # Find JSON block in markdown or surrounding text
        import re
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)

        return text

    @staticmethod
    def _fallback_parse(text: str, elapsed_ms: float) -> VerificationResult:
        """Fallback parsing when JSON extraction fails."""
        text_lower = text.lower()

        if "false" in text_lower and ("positive" in text_lower or "fud" in text_lower):
            status = VerificationStatus.FALSE_POSITIVE
        elif "verified" in text_lower or "credible" in text_lower or "confirmed" in text_lower:
            status = VerificationStatus.VERIFIED
        elif "disputed" in text_lower or "contradicting" in text_lower:
            status = VerificationStatus.DISPUTED
        else:
            status = VerificationStatus.UNVERIFIED

        return VerificationResult(
            status=status,
            confidence=0.3,  # Low confidence for fallback parsing
            reasoning=f"Fallback parse: {text[:300]}",
            verification_time_ms=elapsed_ms,
        )

    # ── Cache Management ─────────────────────────────────────────────

    def clear_cache(self) -> None:
        """Clear the verification cache."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Number of cached verification results."""
        return self._cache.size
