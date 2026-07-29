"""TSAR — Genome Mutator.

Phase 1B: Shadow Account Loop — Propose StrategyGenome mutations from
validated trading rules. The mutator proposes but does not apply — the
Strategy Geneticist decides whether to evolve the genome.

The flywheel step: TRADE → OBSERVE → REFLECT → EXTRACT → **ADAPT** → BETTER TRADE
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.knowledge.strategy_genomes import (
    StrategyGenome,
    StrategyGenomes,
    StrategyMutation,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.knowledge.rule_validator import ValidatedRule

logger = get_logger(__name__)


def _ulid() -> str:
    return uuid.uuid4().hex


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class MutationProposal:
    """A proposed genome mutation derived from a validated rule.

    This is the output of GenomeMutator — a concrete proposal
    that the Strategy Geneticist can accept or reject.
    """
    proposal_id: str = field(default_factory=_ulid)
    source_rule_id: str = ""
    target_genome_id: str | None = None
    target_genome_name: str | None = None
    mutation_type: str = "rule_addition"  # rule_addition | param_tweak | rule_modification
    change_description: str = ""
    proposed_entry_rules: str | None = None
    proposed_exit_rules: str | None = None
    proposed_risk_params: str | None = None
    confidence_score: float = 0.0
    expected_improvement: float = 0.0
    rationale: str = ""
    status: str = "pending_validation"  # pending_validation | accepted | rejected | applied
    validated_rule_snapshot: str | None = None  # JSON snapshot of the source ValidatedRule
    created_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MutatorConfig:
    """Configuration for the GenomeMutator."""
    min_confidence: float = 0.6
    min_sharpe: float = 0.5
    min_win_rate: float = 0.45
    min_profit_factor: float = 1.1
    max_proposals_per_run: int = 5
    allow_new_genomes: bool = False  # If True, create new genomes; else only mutate existing


# ═══════════════════════════════════════════════════════════════════════
# GENOME MUTATOR
# ═══════════════════════════════════════════════════════════════════════


class GenomeMutator:
    """Propose StrategyGenome mutations from validated trading rules.

    Takes ValidatedRules from RuleValidator, finds matching genomes,
    and proposes specific mutations. Proposals are marked as
    "pending_validation" — the Strategy Geneticist decides whether
    to apply them.

    Usage::

        mutator = GenomeMutator(strategy_genomes, config=MutatorConfig())
        proposals = await mutator.propose_mutations(validated_rules)
        for p in proposals:
            print(p.change_description, p.confidence_score)
    """

    def __init__(
        self,
        strategy_genomes: StrategyGenomes,
        config: MutatorConfig | None = None,
    ) -> None:
        self._genomes = strategy_genomes
        self._config = config or MutatorConfig()

    async def propose_mutations(
        self,
        validated_rules: list[ValidatedRule],
    ) -> list[MutationProposal]:
        """Propose genome mutations from validated rules.

        Filters rules by quality thresholds, finds matching genomes,
        and creates mutation proposals.

        Args:
            validated_rules: ValidatedRules from RuleValidator.

        Returns:
            List of MutationProposals (up to max_proposals_per_run).
        """
        # Filter to only passed, high-confidence rules
        candidates = [
            r for r in validated_rules
            if r.validation_status == "passed"
            and r.confidence >= self._config.min_confidence
            and r.sharpe >= self._config.min_sharpe
            and r.win_rate >= self._config.min_win_rate
            and r.profit_factor >= self._config.min_profit_factor
        ]

        if not candidates:
            logger.info("genome_mutator_no_candidates", total_rules=len(validated_rules))
            return []

        # Sort by expectancy (best rules first)
        candidates.sort(key=lambda r: r.expectancy, reverse=True)

        proposals: list[MutationProposal] = []
        for rule in candidates[: self._config.max_proposals_per_run]:
            try:
                proposal = await self._propose_for_rule(rule)
                if proposal:
                    proposals.append(proposal)
            except Exception as e:
                logger.error(
                    "genome_mutator_propose_error",
                    rule_id=rule.rule_id,
                    error=str(e),
                )

        logger.info(
            "genome_mutations_proposed",
            proposed=len(proposals),
            candidates=len(candidates),
        )
        return proposals

    async def _propose_for_rule(
        self, rule: ValidatedRule
    ) -> MutationProposal | None:
        """Create a mutation proposal for a single validated rule."""
        # Find the best matching genome
        genome = self._find_matching_genome(rule)

        if genome:
            return self._propose_genome_mutation(rule, genome)
        elif self._config.allow_new_genomes:
            return self._propose_new_genome(rule)
        else:
            logger.debug(
                "genome_mutator_no_matching_genome",
                rule_id=rule.rule_id,
                strategy_id=rule.strategy_id,
            )
            return None

    def _find_matching_genome(self, rule: ValidatedRule) -> StrategyGenome | None:
        """Find the best matching genome for a rule.

        Priority:
        1. Exact strategy_id match
        2. Same symbol + active status
        3. Best-performing active genome
        """
        # Try exact strategy match
        if rule.strategy_id:
            genome = self._genomes.get_genome(rule.strategy_id)
            if genome:
                return genome

        # Try by name
        if rule.strategy_id:
            genome = self._genomes.get_genome_by_name(rule.strategy_id)
            if genome:
                return genome

        # Fall back to best active genome
        active = self._genomes.get_active_strategies()
        if active:
            return active[0]  # Already sorted by sharpe_ratio DESC

        # Try candidates
        candidates = self._genomes.list_genomes(status="candidate", limit=1)
        if candidates:
            return candidates[0]

        return None

    def _propose_genome_mutation(
        self, rule: ValidatedRule, genome: StrategyGenome
    ) -> MutationProposal:
        """Propose a mutation to an existing genome."""
        # Build the mutation description
        change_desc = self._build_change_description(rule, genome)
        mutation_type = self._classify_mutation(rule, genome)

        # Compute confidence score from validation metrics
        confidence = self._compute_confidence_score(rule)

        # Estimate expected improvement
        expected_improvement = self._estimate_improvement(rule, genome)

        # Build proposed rule changes
        proposed_entry = self._merge_entry_rules(genome.entry_rules, rule)
        proposed_exit = self._merge_exit_rules(genome.exit_rules, rule)

        proposal = MutationProposal(
            source_rule_id=rule.rule_id,
            target_genome_id=genome.strategy_id,
            target_genome_name=genome.name,
            mutation_type=mutation_type,
            change_description=change_desc,
            proposed_entry_rules=proposed_entry,
            proposed_exit_rules=proposed_exit,
            confidence_score=confidence,
            expected_improvement=expected_improvement,
            rationale=rule.rationale,
            status="pending_validation",
            validated_rule_snapshot=json.dumps(rule.to_dict(), default=str),
        )

        # Record the mutation in the StrategyGenomes store
        mutation = StrategyMutation(
            strategy_name=genome.name,
            parent_id=genome.strategy_id,
            mutation_type=mutation_type,
            change_description=change_desc,
            mutation_detail=json.dumps(proposal.to_dict(), default=str),
            rationale=rule.rationale,
            outcome="pending",
        )
        self._genomes.record_mutation(mutation)

        logger.info(
            "genome_mutation_proposed",
            proposal_id=proposal.proposal_id,
            genome_id=genome.strategy_id,
            mutation_type=mutation_type,
            confidence=confidence,
        )
        return proposal

    def _propose_new_genome(self, rule: ValidatedRule) -> MutationProposal:
        """Propose creating a new genome from a validated rule."""
        confidence = self._compute_confidence_score(rule)

        proposal = MutationProposal(
            source_rule_id=rule.rule_id,
            target_genome_name=f"shadow_{rule.symbol}_{rule.action}" if rule.symbol else f"shadow_{rule.action}",
            mutation_type="new_genome",
            change_description=f"New genome from shadow rule: {rule.description}",
            proposed_entry_rules=json.dumps(rule.conditions),
            confidence_score=confidence,
            expected_improvement=rule.expectancy,
            rationale=rule.rationale,
            status="pending_validation",
            validated_rule_snapshot=json.dumps(rule.to_dict(), default=str),
        )

        logger.info(
            "new_genome_proposed",
            proposal_id=proposal.proposal_id,
            confidence=confidence,
        )
        return proposal

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _build_change_description(rule: ValidatedRule, genome: StrategyGenome) -> str:
        """Build a human-readable mutation description."""
        parts = [
            f"Shadow rule [{rule.rule_id[:8]}] suggests:",
            f"{rule.description}",
            f"Action: {rule.action} | Win rate: {rule.win_rate:.1%} | "
            f"Sharpe: {rule.sharpe:.2f} | PF: {rule.profit_factor:.2f}",
            f"Based on {rule.sample_size} backtested trades.",
        ]
        return " | ".join(parts)

    @staticmethod
    def _classify_mutation(rule: ValidatedRule, genome: StrategyGenome) -> str:
        """Classify the type of mutation."""
        existing_rules = genome.entry_rules or ""
        if not existing_rules:
            return "rule_addition"
        # If the rule's conditions overlap with existing rules, it's a modification
        return "rule_addition"

    @staticmethod
    def _compute_confidence_score(rule: ValidatedRule) -> float:
        """Compute a confidence score [0, 1] from validation metrics.

        Combines statistical significance, sample size, and performance.
        """
        # p-value component (0 to 1, where p=0 → 1.0, p=0.05 → 0.0)
        p_score = max(0.0, 1.0 - (rule.p_value / 0.05)) if rule.p_value < 0.05 else 0.0

        # Sample size component (logarithmic scaling, 20 trades → 0.5, 100 → 0.85)
        n_score = min(1.0, math.log(max(rule.sample_size, 1)) / math.log(200))

        # Sharpe component (0.5 → 0.5, 2.0 → 1.0)
        sharpe_score = min(1.0, rule.sharpe / 2.0)

        # Weighted combination
        confidence = (
            0.35 * p_score
            + 0.25 * n_score
            + 0.25 * sharpe_score
            + 0.15 * min(1.0, rule.win_rate / 0.6)
        )
        return round(min(1.0, max(0.0, confidence)), 4)

    @staticmethod
    def _estimate_improvement(rule: ValidatedRule, genome: StrategyGenome) -> float:
        """Estimate the expected improvement to the genome's Sharpe.

        Returns a conservative estimate based on the rule's contribution
        to overall portfolio performance.
        """
        # Conservative: blend rule's Sharpe with genome's, weighted by sample size
        weight = min(0.3, rule.sample_size / 200)  # Max 30% weight
        improvement = (rule.sharpe - genome.sharpe_ratio) * weight
        return round(max(0.0, improvement), 4)

    @staticmethod
    def _merge_entry_rules(existing: str | None, rule: ValidatedRule) -> str:
        """Merge validated rule conditions into existing entry rules."""
        new_conditions = rule.conditions
        if existing:
            try:
                current = json.loads(existing)
                if isinstance(current, list):
                    current.extend(new_conditions)
                else:
                    current = [current] + new_conditions
                return json.dumps(current, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass
        return json.dumps(new_conditions, indent=2)

    @staticmethod
    def _merge_exit_rules(existing: str | None, rule: ValidatedRule) -> str | None:
        """Merge validated rule into exit rules (only for sell actions)."""
        if rule.action != "sell":
            return existing
        return GenomeMutator._merge_entry_rules(existing, rule)

