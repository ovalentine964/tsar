"""TSAR — Blueprint Selector.

Recommends the optimal strategy blueprint based on:
  - Account size
  - Risk tolerance
  - Market regime
  - Trading experience
  - Time availability

Loads blueprints from config/blueprints/ and scores each against
the trader's profile.

Usage::

    from src.llm.blueprint_selector import BlueprintSelector, TraderProfile

    selector = BlueprintSelector("/path/to/config/blueprints")
    profile = TraderProfile(
        account_size_usd=10000,
        risk_tolerance="medium",
        experience="intermediate",
        preferred_time_horizon="days_to_weeks",
        market_regime="strong_trend_up",
    )
    recommendations = selector.recommend(profile)
    best = recommendations[0]
    print(f"Best blueprint: {best.name} (score: {best.score})")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TraderProfile:
    """Trader's profile for blueprint matching."""

    account_size_usd: float = 10000.0
    risk_tolerance: str = "medium"  # low, medium, high
    experience: str = "intermediate"  # beginner, intermediate, advanced, expert
    preferred_time_horizon: str = "days_to_weeks"  # minutes_to_hours, hours_to_days, days_to_weeks, weeks_to_months
    market_regime: str | None = None  # strong_trend_up, strong_trend_down, ranging, high_volatility
    max_drawdown_tolerance_pct: float | None = None  # Override risk_tolerance
    trading_style: str | None = None  # scalp, day, swing, position
    time_commitment: str | None = None  # low, medium, high, very_high
    leverage_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_size_usd": self.account_size_usd,
            "risk_tolerance": self.risk_tolerance,
            "experience": self.experience,
            "preferred_time_horizon": self.preferred_time_horizon,
            "market_regime": self.market_regime,
            "max_drawdown_tolerance_pct": self.max_drawdown_tolerance_pct,
            "trading_style": self.trading_style,
            "time_commitment": self.time_commitment,
            "leverage_allowed": self.leverage_allowed,
        }


@dataclass
class BlueprintRecommendation:
    """A blueprint recommendation with scoring details."""

    name: str
    display_name: str
    description: str
    score: float  # 0.0 - 1.0
    config: dict[str, Any]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adjustments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "warnings": self.warnings,
            "adjustments": self.adjustments,
        }


# Score weights for each matching dimension
_SCORE_WEIGHTS = {
    "experience": 0.25,
    "risk_tolerance": 0.25,
    "time_horizon": 0.20,
    "account_size": 0.15,
    "market_regime": 0.10,
    "style_match": 0.05,
}

# Experience level ordering
_EXPERIENCE_LEVELS = {"beginner": 0, "intermediate": 1, "advanced": 2, "expert": 3}

# Risk tolerance ordering
_RISK_LEVELS = {"low": 0, "medium": 1, "high": 2}

# Time horizon to time commitment mapping
_TIME_HORIZON_COMMITMENT = {
    "minutes_to_hours": "very_high",
    "hours_to_days": "high",
    "days_to_weeks": "medium",
    "weeks_to_months": "low",
}

# Time horizon compatibility (blueprint_horizon → trader_horizon compatibility)
_TIME_COMPAT = {
    "minutes_to_hours": {"minutes_to_hours": 1.0, "hours_to_days": 0.3},
    "hours_to_days": {"hours_to_days": 1.0, "minutes_to_hours": 0.5, "days_to_weeks": 0.5},
    "days_to_weeks": {"days_to_weeks": 1.0, "hours_to_days": 0.5, "weeks_to_months": 0.5},
    "weeks_to_months": {"weeks_to_months": 1.0, "days_to_weeks": 0.5},
}


class BlueprintSelector:
    """Recommend strategy blueprints based on trader profile.

    Args:
        blueprints_dir: Path to the blueprints directory.
    """

    def __init__(self, blueprints_dir: str | None = None) -> None:
        if blueprints_dir is None:
            blueprints_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "blueprints"
            )
        self._blueprints_dir = Path(blueprints_dir)
        self._blueprints: dict[str, dict[str, Any]] = {}
        self._load_blueprints()

    def _load_blueprints(self) -> None:
        """Load all blueprint YAML files from the directory."""
        if not self._blueprints_dir.exists():
            logger.warning("blueprints_dir_not_found", path=str(self._blueprints_dir))
            return

        for yaml_file in self._blueprints_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if data and "blueprint" in data:
                    bp = data["blueprint"]
                    name = bp.get("name", yaml_file.stem)
                    self._blueprints[name] = data
                    logger.debug("blueprint_loaded", name=name, file=yaml_file.name)
            except Exception as exc:
                logger.error("blueprint_load_failed", file=yaml_file.name, error=str(exc))

        logger.info("blueprints_loaded", count=len(self._blueprints))

    def reload(self) -> None:
        """Reload blueprints from disk."""
        self._blueprints.clear()
        self._load_blueprints()

    @property
    def available_blueprints(self) -> list[str]:
        """List available blueprint names."""
        return list(self._blueprints.keys())

    def recommend(
        self,
        profile: TraderProfile,
        top_n: int = 3,
        regime: str | None = None,
    ) -> list[BlueprintRecommendation]:
        """Recommend blueprints for the given trader profile.

        Args:
            profile: Trader's profile.
            top_n: Number of top recommendations to return.
            regime: Optional market regime override.

        Returns:
            List of BlueprintRecommendation sorted by score (best first).
        """
        if not self._blueprints:
            logger.warning("no_blueprints_available")
            return []

        effective_regime = regime or profile.market_regime
        recommendations: list[BlueprintRecommendation] = []

        for name, bp_data in self._blueprints.items():
            try:
                rec = self._score_blueprint(bp_data, profile, effective_regime)
                recommendations.append(rec)
            except Exception as exc:
                logger.error("blueprint_scoring_failed", name=name, error=str(exc))

        # Sort by score descending
        recommendations.sort(key=lambda r: r.score, reverse=True)

        # Apply regime-based adjustments
        if effective_regime:
            recommendations = self._apply_regime_adjustments(recommendations, effective_regime)

        return recommendations[:top_n]

    def get_blueprint(self, name: str) -> dict[str, Any] | None:
        """Get a specific blueprint config by name.

        Args:
            name: Blueprint name (e.g. 'conservative', 'balanced').

        Returns:
            Blueprint config dict, or None if not found.
        """
        return self._blueprints.get(name)

    def get_blueprint_for_regime(self, regime: str) -> str:
        """Get the recommended blueprint name for a market regime.

        Args:
            regime: Market regime string.

        Returns:
            Blueprint name recommendation.
        """
        regime_map = {
            "strong_trend_up": "aggressive",
            "strong_trend_down": "conservative",
            "ranging": "balanced",
            "high_volatility": "conservative",
            "low_volatility": "balanced",
            "breakout": "swing",
            "accumulation": "swing",
            "distribution": "conservative",
        }
        return regime_map.get(regime, "balanced")

    def apply_blueprint(self, name: str, base_config: dict[str, Any]) -> dict[str, Any]:
        """Apply blueprint overrides to a base strategy config.

        Args:
            name: Blueprint name.
            base_config: Base strategy configuration to merge into.

        Returns:
            Merged configuration dict.
        """
        bp = self._blueprints.get(name)
        if not bp:
            logger.warning("blueprint_not_found", name=name)
            return base_config

        bp_config = bp.get("blueprint", {})
        merged = dict(base_config)

        # Merge risk parameters
        risk = bp_config.get("risk", {})
        for key, value in risk.items():
            merged[key] = value

        # Merge sizing
        sizing = bp_config.get("sizing", {})
        for key, value in sizing.items():
            merged[f"sizing_{key}"] = value

        # Merge exit rules
        exit_rules = bp_config.get("exit_rules", {})
        for key, value in exit_rules.items():
            merged[f"exit_{key}"] = value

        # Merge strategy overrides
        strategies = bp_config.get("strategies", {})
        for role in ["primary", "secondary", "tertiary"]:
            strat = strategies.get(role, {})
            if strat and "overrides" in strat:
                strat_name = strat.get("name", "")
                for key, value in strat["overrides"].items():
                    merged[f"strategy_{strat_name}_{key}"] = value

        logger.info("blueprint_applied", name=name)
        return merged

    # ── Scoring internals ────────────────────────────────────

    def _score_blueprint(
        self,
        bp_data: dict[str, Any],
        profile: TraderProfile,
        regime: str | None,
    ) -> BlueprintRecommendation:
        """Score a single blueprint against the trader profile."""
        bp = bp_data.get("blueprint", {})
        audience = bp.get("target_audience", {})
        risk = bp.get("risk", {})

        name = bp.get("name", "unknown")
        display_name = bp.get("display_name", name)
        description = bp.get("description", "")

        reasons: list[str] = []
        warnings: list[str] = []
        adjustments: dict[str, Any] = {}
        scores: dict[str, float] = {}

        # 1. Experience match
        bp_experiences = audience.get("experience", [])
        if profile.experience in bp_experiences:
            scores["experience"] = 1.0
            reasons.append(f"Designed for {profile.experience} traders")
        else:
            profile_level = _EXPERIENCE_LEVELS.get(profile.experience, 1)
            bp_levels = [_EXPERIENCE_LEVELS.get(e, 1) for e in bp_experiences]
            if bp_levels:
                min_diff = min(abs(profile_level - l) for l in bp_levels)
                scores["experience"] = max(0.0, 1.0 - min_diff * 0.35)
                if min_diff > 0:
                    warnings.append(f"Blueprint targets {bp_experiences}, you're {profile.experience}")
            else:
                scores["experience"] = 0.5

        # 2. Risk tolerance match
        bp_risk = audience.get("risk_tolerance", "medium")
        profile_risk = profile.risk_tolerance
        if profile.max_drawdown_tolerance_pct:
            # Override with explicit drawdown tolerance
            max_dd = risk.get("max_drawdown_flatten", 0.10)
            if max_dd <= profile.max_drawdown_tolerance_pct:
                scores["risk_tolerance"] = 1.0
                reasons.append(f"Max drawdown {max_dd:.0%} within your {profile.max_drawdown_tolerance_pct:.0%} tolerance")
            else:
                scores["risk_tolerance"] = max(0.0, 1.0 - (max_dd - profile.max_drawdown_tolerance_pct) * 5)
                warnings.append(f"Max drawdown {max_dd:.0%} exceeds your {profile.max_drawdown_tolerance_pct:.0%} tolerance")
        else:
            risk_diff = abs(_RISK_LEVELS.get(profile_risk, 1) - _RISK_LEVELS.get(bp_risk, 1))
            scores["risk_tolerance"] = max(0.0, 1.0 - risk_diff * 0.4)
            if risk_diff > 0:
                warnings.append(f"Blueprint risk level: {bp_risk}, yours: {profile_risk}")

        # 3. Time horizon match
        bp_horizon = audience.get("time_horizon", "days_to_weeks")
        trader_horizon = profile.preferred_time_horizon
        horizon_compat = _TIME_COMPAT.get(bp_horizon, {})
        scores["time_horizon"] = horizon_compat.get(trader_horizon, 0.2)
        if scores["time_horizon"] >= 0.8:
            reasons.append(f"Time horizon matches ({trader_horizon})")
        elif scores["time_horizon"] < 0.5:
            # Check explicit style match
            if profile.trading_style:
                style_horizon_map = {
                    "scalp": "minutes_to_hours",
                    "day": "hours_to_days",
                    "swing": "days_to_weeks",
                    "position": "weeks_to_months",
                }
                expected = style_horizon_map.get(profile.trading_style)
                if expected == bp_horizon:
                    scores["time_horizon"] = 1.0
                    reasons.append(f"Matches your {profile.trading_style} trading style")

        # 4. Account size match
        size_range = audience.get("account_size_range_usd", [0, float("inf")])
        min_size, max_size = size_range[0], size_range[1]
        if min_size <= profile.account_size_usd <= max_size:
            scores["account_size"] = 1.0
            reasons.append(f"Account size ${profile.account_size_usd:,.0f} in target range")
        elif profile.account_size_usd < min_size:
            ratio = profile.account_size_usd / min_size if min_size > 0 else 0
            scores["account_size"] = max(0.0, ratio)
            warnings.append(f"Blueprint targets ${min_size:,.0f}+ accounts")
        else:
            scores["account_size"] = 0.8  # Above max is less of an issue
            reasons.append("Account above target range (fine, just less optimal)")

        # 5. Market regime compatibility
        if regime:
            regime_score = self._score_regime_compatibility(bp_data, regime)
            scores["market_regime"] = regime_score
            if regime_score >= 0.7:
                reasons.append(f"Good fit for {regime} regime")
            elif regime_score < 0.4:
                warnings.append(f"Suboptimal for {regime} regime")
        else:
            scores["market_regime"] = 0.5  # Neutral if no regime

        # 6. Style match bonus
        if profile.trading_style:
            bp_name = bp.get("name", "")
            style_to_blueprint = {
                "scalp": "scalp",
                "day": "balanced",
                "swing": "swing",
                "position": "conservative",
            }
            if style_to_blueprint.get(profile.trading_style) == bp_name:
                scores["style_match"] = 1.0
                reasons.append(f"Exact match for {profile.trading_style} style")
            else:
                scores["style_match"] = 0.3

        # Calculate weighted final score
        total_score = 0.0
        total_weight = 0.0
        for dimension, weight in _SCORE_WEIGHTS.items():
            if dimension in scores:
                total_score += scores[dimension] * weight
                total_weight += weight

        final_score = total_score / total_weight if total_weight > 0 else 0.0

        # Generate adjustments for mismatched dimensions
        if scores.get("risk_tolerance", 1.0) < 0.6:
            adjustments["reduce_position_size"] = True
            adjustments["recommended_max_risk_pct"] = max(0.005, risk.get("max_risk_per_trade_pct", 0.02) * 0.7)
        if scores.get("experience", 1.0) < 0.6:
            adjustments["enable_extra_validation"] = True
            adjustments["recommended_signal_threshold"] = 0.75

        return BlueprintRecommendation(
            name=name,
            display_name=display_name,
            description=description,
            score=final_score,
            config=bp_data,
            reasons=reasons,
            warnings=warnings,
            adjustments=adjustments,
        )

    def _score_regime_compatibility(self, bp_data: dict[str, Any], regime: str) -> float:
        """Score how compatible a blueprint is with a market regime."""
        bp = bp_data.get("blueprint", {})
        name = bp.get("name", "")
        strategies = bp.get("strategies", {})

        # Regime → preferred blueprint mapping
        regime_preferences = {
            "strong_trend_up": {
                "aggressive": 0.9,
                "swing": 0.8,
                "balanced": 0.7,
                "scalp": 0.5,
                "conservative": 0.3,
            },
            "strong_trend_down": {
                "conservative": 0.9,
                "balanced": 0.6,
                "swing": 0.5,
                "scalp": 0.4,
                "aggressive": 0.2,
            },
            "ranging": {
                "balanced": 0.8,
                "scalp": 0.7,
                "conservative": 0.6,
                "swing": 0.4,
                "aggressive": 0.3,
            },
            "high_volatility": {
                "conservative": 0.8,
                "balanced": 0.5,
                "scalp": 0.6,
                "swing": 0.3,
                "aggressive": 0.4,
            },
            "low_volatility": {
                "balanced": 0.7,
                "swing": 0.8,
                "conservative": 0.6,
                "scalp": 0.3,
                "aggressive": 0.4,
            },
            "breakout": {
                "swing": 0.9,
                "aggressive": 0.8,
                "balanced": 0.7,
                "scalp": 0.6,
                "conservative": 0.3,
            },
        }

        preferences = regime_preferences.get(regime, {})
        base_score = preferences.get(name, 0.5)

        # Bonus: check if blueprint's primary strategy fits the regime
        primary_strat = strategies.get("primary", {}).get("name", "")
        regime_strategy_bonus = {
            "strong_trend_up": {"momentum_funding": 0.1, "tsar": 0.05},
            "strong_trend_down": {"mean_reversion": 0.1, "tsar": 0.05},
            "ranging": {"mean_reversion": 0.15, "tsar": 0.05},
            "high_volatility": {"mean_reversion": 0.1, "tsar": 0.05},
        }
        bonus = regime_strategy_bonus.get(regime, {}).get(primary_strat, 0.0)

        return min(1.0, base_score + bonus)

    def _apply_regime_adjustments(
        self,
        recommendations: list[BlueprintRecommendation],
        regime: str,
    ) -> list[BlueprintRecommendation]:
        """Apply regime-specific adjustments to recommendations."""
        # Regime-specific parameter adjustments
        regime_adjustments = {
            "high_volatility": {
                "reduce_position_size": True,
                "recommended_max_risk_pct_multiplier": 0.7,
                "widen_stops": True,
                "recommended_stop_atr_multiplier": 1.3,
            },
            "strong_trend_down": {
                "reduce_long_exposure": True,
                "prefer_short_bias": True,
            },
            "ranging": {
                "prefer_mean_reversion": True,
                "reduce_trend_following": True,
            },
        }

        adjustments = regime_adjustments.get(regime, {})
        if adjustments:
            for rec in recommendations:
                rec.adjustments.update(adjustments)

        return recommendations

    def format_recommendation(self, rec: BlueprintRecommendation) -> str:
        """Format a recommendation as a human-readable string."""
        lines = [
            f"## {rec.display_name} (Score: {rec.score:.0%})",
            "",
            rec.description.strip(),
            "",
        ]

        if rec.reasons:
            lines.append("**Why it fits:**")
            for reason in rec.reasons:
                lines.append(f"  ✅ {reason}")
            lines.append("")

        if rec.warnings:
            lines.append("**Considerations:**")
            for warning in rec.warnings:
                lines.append(f"  ⚠️ {warning}")
            lines.append("")

        if rec.adjustments:
            lines.append("**Recommended adjustments:**")
            for key, value in rec.adjustments.items():
                lines.append(f"  → {key}: {value}")

        return "\n".join(lines)
