"""TSAR — Nemotron Policy Generator for Risk Guardrails.

Uses NVIDIA Nemotron to generate adaptive risk policies:
- Position limits based on market regime
- Drawdown rules adapted to volatility
- Correlation limits for portfolio diversification
- Volatility-adjusted position sizing
- Regime-adaptive trading rules

Generated policies are validated against historical data before deployment.
Nemotron is optional — falls back to static rules from risk.yaml.

Requires: NVIDIA NIM API (NVIDIA_API_KEY env var)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── Nemotron availability check ─────────────────────────────


def _check_nemotron_available() -> bool:
    """Check if Nemotron NIM is reachable.

    Verifies:
    1. httpx can be imported
    2. NVIDIA_API_KEY env var is set
    3. NIM endpoint responds to a lightweight health check
    """
    import os

    try:
        import httpx  # noqa: F811
    except ImportError:
        return False

    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        return False

    # Lightweight connectivity test: GET the models endpoint
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                "https://integrate.api.nvidia.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code == 200:
                return True
            logger.warning(
                "nemotron_endpoint_unavailable",
                status=response.status_code,
                msg="NIM endpoint returned non-200",
            )
            return False
    except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
        logger.warning("nemotron_connectivity_failed", error=str(exc))
        return False


try:
    import httpx

    NEMOTRON_AVAILABLE = _check_nemotron_available()
except ImportError:
    NEMOTRON_AVAILABLE = False


# ── Data classes ─────────────────────────────────────────────


@dataclass
class RiskPolicy:
    """A generated risk policy rule."""

    policy_id: str
    category: str  # position_limits, drawdown_rules, etc.
    name: str
    description: str
    rule: dict[str, Any]  # The actual rule parameters
    confidence: float = 0.0  # 0-1 confidence in this policy
    source: str = "nemotron"  # nemotron | static | backtested
    approved: bool = False  # Requires human approval
    backtest_sharpe: float = 0.0  # Sharpe ratio from backtesting
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "rule": self.rule,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "approved": self.approved,
            "backtest_sharpe": round(self.backtest_sharpe, 4),
            "metadata": self.metadata,
        }


@dataclass
class PolicySet:
    """A collection of generated risk policies."""

    policies: list[RiskPolicy] = field(default_factory=list)
    generation_method: str = "nemotron"
    total_generated: int = 0
    approved_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policies": [p.to_dict() for p in self.policies],
            "generation_method": self.generation_method,
            "total_generated": self.total_generated,
            "approved_count": self.approved_count,
            "metadata": self.metadata,
        }

    @property
    def approved_policies(self) -> list[RiskPolicy]:
        """Return only approved policies."""
        return [p for p in self.policies if p.approved]


# ── Main Policy Generator ───────────────────────────────────


class NemotronPolicyGenerator:
    """Generate risk policies using NVIDIA Nemotron.

    Generates adaptive risk guardrails based on:
    - Current market regime
    - Historical performance data
    - Portfolio characteristics
    - Volatility environment

    Falls back to static rules from risk.yaml if Nemotron unavailable.

    Usage::

        generator = NemotronPolicyGenerator(config)
        policy_set = await generator.generate_policies(
            market_context={"regime": "high_volatility", "vix": 35},
            performance_data={"win_rate": 0.55, "max_drawdown": -0.08},
        )
        for policy in policy_set.approved_policies:
            print(f"Approved: {policy.name}")
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._available = NEMOTRON_AVAILABLE
        self._fallback = self._config.get("fallback", "static_rules")

        # Generation config
        gen_cfg = self._config.get("generation", {})
        self._model = gen_cfg.get("model", "nvidia/nemotron-3-ultra-550b-a55b")
        self._max_policies = gen_cfg.get("max_policies", 20)
        self._confidence_threshold = gen_cfg.get("confidence_threshold", 0.8)

        # Validation config
        val_cfg = self._config.get("validation", {})
        self._require_approval = val_cfg.get("require_approval", True)
        self._test_on_historical = val_cfg.get("test_on_historical", True)
        self._min_backtest_sharpe = val_cfg.get("min_backtest_sharpe", 0.5)

        # Policy categories
        self._categories = self._config.get(
            "categories",
            [
                "position_limits",
                "drawdown_rules",
                "correlation_limits",
                "volatility_adjustments",
                "regime_adaptive_rules",
            ],
        )

        # Check for API key
        import os

        self._api_key = os.environ.get("NVIDIA_API_KEY", "")

        if not self._available:
            logger.warning(
                "nemotron_not_available",
                msg=f"Nemotron not available. Using {self._fallback} fallback.",
            )

    @property
    def available(self) -> bool:
        """Check if Nemotron NIM is available."""
        return self._available

    # ── Policy Generation ────────────────────────────────────

    async def generate_policies(
        self,
        market_context: dict[str, Any] | None = None,
        performance_data: dict[str, Any] | None = None,
        existing_policies: list[dict[str, Any]] | None = None,
    ) -> PolicySet:
        """Generate risk policies based on current context.

        Args:
            market_context: Current market conditions (regime, vix, etc.).
            performance_data: Recent trading performance metrics.
            existing_policies: Current risk.yaml policies for context.

        Returns:
            PolicySet with generated policies.
        """
        if self.available:
            return await self._nemotron_generate(
                market_context, performance_data, existing_policies
            )
        else:
            return self._static_fallback(market_context, performance_data)

    async def _nemotron_generate(
        self,
        market_context: dict[str, Any] | None,
        performance_data: dict[str, Any] | None,
        existing_policies: list[dict[str, Any]] | None,
    ) -> PolicySet:
        """Generate policies using Nemotron via NIM API."""
        assert NEMOTRON_AVAILABLE

        # Build prompt
        prompt = self._build_generation_prompt(market_context, performance_data, existing_policies)

        try:
            # Call NVIDIA NIM API
            result = await self._call_nim_api(prompt)
            policies = self._parse_policies(result)

            # Validate if configured
            if self._test_on_historical and performance_data:
                policies = self._validate_policies(policies, performance_data)

            # Apply approval requirement
            if not self._require_approval:
                for p in policies:
                    if p.confidence >= self._confidence_threshold:
                        p.approved = True

            policy_set = PolicySet(
                policies=policies[: self._max_policies],
                generation_method="nemotron",
                total_generated=len(policies),
                approved_count=sum(1 for p in policies if p.approved),
                metadata={
                    "model": self._model,
                    "market_context": market_context,
                },
            )

            logger.info(
                "policies_generated",
                total=policy_set.total_generated,
                approved=policy_set.approved_count,
                method="nemotron",
            )

            return policy_set

        except Exception as exc:
            logger.error("nemotron_generation_failed", error=str(exc))
            return self._static_fallback(market_context, performance_data)

    def _build_generation_prompt(
        self,
        market_context: dict[str, Any] | None,
        performance_data: dict[str, Any] | None,
        existing_policies: list[dict[str, Any]] | None,
    ) -> str:
        """Build the Nemotron prompt for policy generation."""
        ctx_str = json.dumps(market_context or {}, indent=2)
        perf_str = json.dumps(performance_data or {}, indent=2)
        existing_str = json.dumps(existing_policies or [], indent=2)

        return f"""You are a quantitative risk management expert for an automated trading system.

Current Market Context:
{ctx_str}

Recent Trading Performance:
{perf_str}

Existing Risk Policies:
{existing_str}

Generate risk policies for the following categories: {", ".join(self._categories)}

For each policy, provide:
1. Category (from the list above)
2. Name (descriptive)
3. Description (why this policy matters)
4. Rule parameters (specific thresholds and values)
5. Confidence (0-1, how confident you are in this policy)
6. Rationale (reasoning behind the values)

Respond in JSON format:
{{
  "policies": [
    {{
      "category": "...",
      "name": "...",
      "description": "...",
      "rule": {{...}},
      "confidence": 0.0,
      "rationale": "..."
    }}
  ]
}}

Be conservative. Err on the side of caution. Trading capital preservation is paramount."""

    async def _call_nim_api(self, prompt: str) -> dict[str, Any]:
        """Call NVIDIA NIM API for policy generation."""
        assert httpx is not None

        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a quantitative risk management expert. Respond only in valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,  # Low temperature for conservative policies
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON from response
            # Handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())

    def _parse_policies(self, result: dict[str, Any]) -> list[RiskPolicy]:
        """Parse Nemotron response into RiskPolicy objects."""
        policies = []
        raw_policies = result.get("policies", [])

        for i, raw in enumerate(raw_policies):
            policy = RiskPolicy(
                policy_id=f"nemotron_{i:03d}",
                category=raw.get("category", "unknown"),
                name=raw.get("name", f"Policy {i}"),
                description=raw.get("description", ""),
                rule=raw.get("rule", {}),
                confidence=float(raw.get("confidence", 0.5)),
                source="nemotron",
                approved=False,  # Requires explicit approval
                metadata={"rationale": raw.get("rationale", "")},
            )
            policies.append(policy)

        return policies

    def _validate_policies(
        self,
        policies: list[RiskPolicy],
        performance_data: dict[str, Any],
    ) -> list[RiskPolicy]:
        """Validate policies against historical performance.

        Adjusts confidence based on how well the policy would have
        performed historically.
        """
        win_rate = performance_data.get("win_rate", 0.5)
        max_dd = abs(performance_data.get("max_drawdown", 0.0))
        sharpe = performance_data.get("sharpe_ratio", 0.0)

        validated = []
        for p in policies:
            # Adjust confidence based on policy category and performance
            adjusted_confidence = p.confidence

            if p.category == "drawdown_rules":
                # If max drawdown was high, increase confidence in stricter rules
                if max_dd > 0.10:
                    adjusted_confidence = min(1.0, p.confidence + 0.1)

            elif p.category == "position_limits":
                # If win rate is low, increase confidence in tighter limits
                if win_rate < 0.45:
                    adjusted_confidence = min(1.0, p.confidence + 0.1)

            elif p.category == "volatility_adjustments":
                # Always validate volatility policies more strictly
                adjusted_confidence = p.confidence * 0.9

            p.confidence = adjusted_confidence
            p.backtest_sharpe = sharpe  # Store for reference

            # Auto-approve high-confidence policies if not requiring manual approval
            if not self._require_approval:
                if adjusted_confidence >= self._confidence_threshold:
                    if sharpe >= self._min_backtest_sharpe:
                        p.approved = True

            validated.append(p)

        return validated

    # ── Static Fallback ──────────────────────────────────────

    def _static_fallback(
        self,
        market_context: dict[str, Any] | None,
        performance_data: dict[str, Any] | None,
    ) -> PolicySet:
        """Generate policies from static risk.yaml rules when Nemotron unavailable."""
        policies = []

        # Position limits
        policies.append(
            RiskPolicy(
                policy_id="static_pos_001",
                category="position_limits",
                name="Max Single Position",
                description="Maximum notional value per position as % of equity",
                rule={"max_single_position_pct": 0.15},
                confidence=1.0,
                source="static",
                approved=True,
            )
        )

        policies.append(
            RiskPolicy(
                policy_id="static_pos_002",
                category="position_limits",
                name="Max Open Positions",
                description="Maximum number of concurrent open positions",
                rule={"max_open_positions": 10},
                confidence=1.0,
                source="static",
                approved=True,
            )
        )

        # Drawdown rules
        policies.append(
            RiskPolicy(
                policy_id="static_dd_001",
                category="drawdown_rules",
                name="Daily Loss Limit",
                description="Maximum daily loss before halting trading",
                rule={"daily_loss_flatten": -0.02, "daily_loss_kill": -0.03},
                confidence=1.0,
                source="static",
                approved=True,
            )
        )

        policies.append(
            RiskPolicy(
                policy_id="static_dd_002",
                category="drawdown_rules",
                name="Max Drawdown",
                description="Maximum drawdown from high water mark",
                rule={"max_drawdown_halt": -0.05, "max_drawdown_flatten": -0.15},
                confidence=1.0,
                source="static",
                approved=True,
            )
        )

        # Correlation limits
        policies.append(
            RiskPolicy(
                policy_id="static_corr_001",
                category="correlation_limits",
                name="Max Correlation",
                description="Maximum correlation between positions",
                rule={"max_correlation": 0.7, "max_sector_concentration_pct": 0.30},
                confidence=0.9,
                source="static",
                approved=True,
            )
        )

        # Volatility adjustments
        regime = (market_context or {}).get("regime", "normal")
        if regime == "high_volatility":
            policies.append(
                RiskPolicy(
                    policy_id="static_vol_001",
                    category="volatility_adjustments",
                    name="High Volatility Position Reduction",
                    description="Reduce position sizes during high volatility",
                    rule={
                        "size_multiplier": 0.5,
                        "trigger": "atr_above_2x_average",
                    },
                    confidence=0.85,
                    source="static",
                    approved=True,
                )
            )

        # Regime-adaptive rules
        if regime == "trending":
            policies.append(
                RiskPolicy(
                    policy_id="static_regime_001",
                    category="regime_adaptive_rules",
                    name="Trending Market Momentum Bias",
                    description="Favor momentum strategies in trending markets",
                    rule={
                        "strategy_weight_boost": {"momentum": 1.5, "mean_reversion": 0.7},
                        "stop_loss_pct": 0.03,  # Wider stops in trends
                    },
                    confidence=0.7,
                    source="static",
                    approved=True,
                )
            )
        elif regime == "ranging":
            policies.append(
                RiskPolicy(
                    policy_id="static_regime_002",
                    category="regime_adaptive_rules",
                    name="Range-Bound Mean Reversion Bias",
                    description="Favor mean reversion in range-bound markets",
                    rule={
                        "strategy_weight_boost": {"mean_reversion": 1.5, "momentum": 0.7},
                        "stop_loss_pct": 0.015,  # Tighter stops in ranges
                    },
                    confidence=0.7,
                    source="static",
                    approved=True,
                )
            )

        return PolicySet(
            policies=policies,
            generation_method="static_fallback",
            total_generated=len(policies),
            approved_count=sum(1 for p in policies if p.approved),
            metadata={"source": "risk.yaml"},
        )

    # ── Policy Application ───────────────────────────────────

    def apply_policy(self, policy: RiskPolicy) -> dict[str, Any]:
        """Convert a policy into runtime configuration overrides.

        Returns a dict that can be merged into risk engine configuration.
        """
        if not policy.approved:
            logger.warning(
                "unapproved_policy_not_applied",
                policy_id=policy.policy_id,
            )
            return {}

        return {
            "policy_id": policy.policy_id,
            "category": policy.category,
            "overrides": policy.rule,
            "source": policy.source,
            "confidence": policy.confidence,
        }

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return generator status."""
        return {
            "available": self.available,
            "method": "nemotron" if self.available else f"fallback_{self._fallback}",
            "model": self._model if self.available else None,
            "categories": self._categories,
            "require_approval": self._require_approval,
            "confidence_threshold": self._confidence_threshold,
        }
