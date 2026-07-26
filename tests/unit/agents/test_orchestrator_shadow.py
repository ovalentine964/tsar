"""Tests for Orchestrator shadow extraction loop integration.

Verifies G1: ShadowExtractor lifecycle management, periodic triggering,
and the full extract → validate → mutate → publish pipeline.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.comms.events import (
    TSAR_SHADOW_EXTRACTED,
    TSAR_RULE_VALIDATED,
    TSAR_STRATEGY_PROPOSAL,
)
from src.knowledge.shadow_extractor import ExtractionResult, TradingRule
from src.knowledge.rule_validator import ValidatedRule
from src.knowledge.genome_mutator import MutationProposal


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _make_config(shadow_enabled: bool = True) -> dict:
    """Build minimal orchestrator config with shadow loop settings."""
    return {
        "agents": {
            "enabled": [],
            "heartbeat_interval_s": 10,
        },
        "shadow_extractor": {
            "enabled": shadow_enabled,
            "cycle_interval_hours": 24,
            "min_trades": 5,
            "min_win_rate": 0.55,
            "lookback_days": 90,
            "timeframe": "1h",
            "lookback_candles": 200,
            "min_confidence": 0.5,
            "min_sharpe": 0.3,
            "max_proposals": 3,
        },
        "database": {"db_path": ":memory:"},
    }


def _make_extraction_result(n_rules: int = 2) -> ExtractionResult:
    """Create a sample ExtractionResult with n rules."""
    rules = []
    for i in range(n_rules):
        rules.append(TradingRule(
            rule_id=f"rule-{i}",
            conditions=[{"type": "rsi_below", "value": 30}],
            action="buy",
            confidence=0.7 + i * 0.05,
            source_trade_ids=[f"trade-{j}" for j in range(5)],
            symbol="BTC/USDT",
            strategy_id="mean_reversion",
            description=f"Test rule {i}",
        ))
    return ExtractionResult(
        rules=rules,
        source_trade_count=20,
        winning_trade_count=12,
        losing_trade_count=8,
    )


def _make_validated_rule(rule_id: str = "vr-0", status: str = "passed") -> ValidatedRule:
    """Create a sample ValidatedRule."""
    return ValidatedRule(
        rule_id=rule_id,
        source_rule_id="rule-0",
        conditions=[{"type": "rsi_below", "value": 30}],
        action="buy",
        confidence=0.75,
        symbol="BTC/USDT",
        strategy_id="mean_reversion",
        sharpe=1.2,
        win_rate=0.6,
        profit_factor=1.5,
        max_drawdown=0.08,
        sample_size=30,
        total_trades=30,
        winning_trades=18,
        losing_trades=12,
        validation_status=status,
    )


def _make_mutation_proposal(proposal_id: str = "prop-0") -> MutationProposal:
    """Create a sample MutationProposal."""
    return MutationProposal(
        proposal_id=proposal_id,
        source_rule_id="rule-0",
        target_genome_id="genome-0",
        target_genome_name="test_genome",
        mutation_type="rule_addition",
        change_description="Add RSI oversold condition",
        confidence_score=0.8,
        expected_improvement=0.15,
    )


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Shadow Loop Initialization
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_shadow_loop_disabled():
    """When shadow_extractor.enabled=False, no components are initialized."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=False)
    orch = Orchestrator(config, trading_mode="paper")

    await orch._initialize_shadow_loop()

    assert orch._shadow_extractor is None
    assert orch._rule_validator is None
    assert orch._genome_mutator is None


@pytest.mark.asyncio
async def test_shadow_loop_enabled():
    """When shadow_extractor.enabled=True, all components are initialized."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    with (
        patch("src.interfaces.get_llm_provider") as mock_llm,
        patch("src.interfaces.get_exchange_gateway") as mock_gw,
    ):
        mock_llm.return_value = MagicMock()
        mock_gw.return_value = MagicMock()

        await orch._initialize_shadow_loop()

    assert orch._shadow_extractor is not None
    assert orch._rule_validator is not None
    assert orch._genome_mutator is not None


@pytest.mark.asyncio
async def test_shadow_loop_init_failure_graceful():
    """If initialization fails, all shadow components are set to None."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    with patch("src.interfaces.get_llm_provider", side_effect=RuntimeError("no LLM")):
        await orch._initialize_shadow_loop()

    assert orch._shadow_extractor is None
    assert orch._rule_validator is None
    assert orch._genome_mutator is None


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Periodic Trigger in run_cycle
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_run_cycle_triggers_shadow_extraction():
    """run_cycle should call _run_shadow_extraction when interval has elapsed."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    # Mock shadow components
    orch._shadow_extractor = MagicMock()
    orch._rule_validator = MagicMock()
    orch._genome_mutator = MagicMock()
    orch._last_shadow_extraction = 0  # Force trigger

    # Mock the extraction method
    orch._run_shadow_extraction = AsyncMock()

    # Force the interval to be elapsed
    with patch("time.monotonic", return_value=100000.0):
        await orch.run_cycle()

    orch._run_shadow_extraction.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_skips_shadow_when_not_elapsed():
    """run_cycle should NOT call _run_shadow_extraction when interval hasn't elapsed."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    orch._shadow_extractor = MagicMock()
    orch._last_shadow_extraction = time.monotonic()  # Just set

    orch._run_shadow_extraction = AsyncMock()

    await orch.run_cycle()

    orch._run_shadow_extraction.assert_not_called()


@pytest.mark.asyncio
async def test_run_cycle_skips_shadow_when_no_extractor():
    """run_cycle should NOT call _run_shadow_extraction when extractor is None."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=False)
    orch = Orchestrator(config, trading_mode="paper")
    orch._shadow_extractor = None

    orch._run_shadow_extraction = AsyncMock()

    await orch.run_cycle()

    orch._run_shadow_extraction.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Full Shadow Extraction Pipeline
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_run_shadow_extraction_full_pipeline():
    """Full pipeline: extract → validate → mutate → publish."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    # Mock shadow components
    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = _make_extraction_result(2)

    mock_validator = AsyncMock()
    mock_validator.validate_batch.return_value = [
        _make_validated_rule("vr-0", "passed"),
        _make_validated_rule("vr-1", "passed"),
    ]

    mock_mutator = AsyncMock()
    mock_mutator.propose_mutations.return_value = [
        _make_mutation_proposal("prop-0"),
        _make_mutation_proposal("prop-1"),
    ]

    orch._shadow_extractor = mock_extractor
    orch._rule_validator = mock_validator
    orch._genome_mutator = mock_mutator
    orch.publish_event = AsyncMock()

    await orch._run_shadow_extraction()

    # Verify extraction was called
    mock_extractor.extract.assert_called_once()

    # Verify validation was called with extracted rules
    mock_validator.validate_batch.assert_called_once()
    call_args = mock_validator.validate_batch.call_args
    assert len(call_args[0][0]) == 2  # 2 rules passed

    # Verify mutation was called with passed rules
    mock_mutator.propose_mutations.assert_called_once()

    # Verify events were published
    publish_calls = orch.publish_event.call_args_list
    event_types = [c[1]["event_type"] if "event_type" in c[1] else c[0][1] for c in publish_calls]

    # Should have: 1 extraction event + 2 validation events + 2 proposal events = 5
    assert len(publish_calls) == 5
    assert TSAR_SHADOW_EXTRACTED in event_types
    assert TSAR_RULE_VALIDATED in event_types
    assert TSAR_STRATEGY_PROPOSAL in event_types


@pytest.mark.asyncio
async def test_run_shadow_extraction_no_rules():
    """When extraction finds no rules, pipeline stops early."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = ExtractionResult(rules=[], source_trade_count=5)

    mock_validator = AsyncMock()
    mock_mutator = AsyncMock()

    orch._shadow_extractor = mock_extractor
    orch._rule_validator = mock_validator
    orch._genome_mutator = mock_mutator
    orch.publish_event = AsyncMock()

    await orch._run_shadow_extraction()

    mock_extractor.extract.assert_called_once()
    mock_validator.validate_batch.assert_not_called()
    mock_mutator.propose_mutations.assert_not_called()


@pytest.mark.asyncio
async def test_run_shadow_extraction_no_passed_rules():
    """When no rules pass validation, mutation step is skipped."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = _make_extraction_result(2)

    mock_validator = AsyncMock()
    mock_validator.validate_batch.return_value = [
        _make_validated_rule("vr-0", "failed"),
        _make_validated_rule("vr-1", "failed"),
    ]

    mock_mutator = AsyncMock()

    orch._shadow_extractor = mock_extractor
    orch._rule_validator = mock_validator
    orch._genome_mutator = mock_mutator
    orch.publish_event = AsyncMock()

    await orch._run_shadow_extraction()

    mock_validator.validate_batch.assert_called_once()
    mock_mutator.propose_mutations.assert_not_called()


@pytest.mark.asyncio
async def test_run_shadow_extraction_handles_exceptions():
    """Exceptions in the pipeline are caught and logged, not raised."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    mock_extractor = AsyncMock()
    mock_extractor.extract.side_effect = RuntimeError("LLM exploded")

    orch._shadow_extractor = mock_extractor
    orch._rule_validator = AsyncMock()
    orch._genome_mutator = AsyncMock()
    orch.publish_event = AsyncMock()

    # Should not raise
    await orch._run_shadow_extraction()

    mock_extractor.extract.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Proposal Publishing
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_proposals_published_to_strategy_proposals_stream():
    """Mutation proposals should be published to the 'strategy_proposals' stream."""
    from src.agents.orchestrator import Orchestrator

    config = _make_config(shadow_enabled=True)
    orch = Orchestrator(config, trading_mode="paper")

    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = _make_extraction_result(1)

    mock_validator = AsyncMock()
    mock_validator.validate_batch.return_value = [
        _make_validated_rule("vr-0", "passed"),
    ]

    mock_mutator = AsyncMock()
    mock_mutator.propose_mutations.return_value = [
        _make_mutation_proposal("prop-0"),
    ]

    orch._shadow_extractor = mock_extractor
    orch._rule_validator = mock_validator
    orch._genome_mutator = mock_mutator
    orch.publish_event = AsyncMock()

    await orch._run_shadow_extraction()

    # Find the proposal publish call
    proposal_calls = [
        c for c in orch.publish_event.call_args_list
        if c[1].get("event_type") == TSAR_STRATEGY_PROPOSAL
        or (len(c[0]) > 1 and c[0][1] == TSAR_STRATEGY_PROPOSAL)
    ]

    assert len(proposal_calls) == 1
    call = proposal_calls[0]
    # Verify it's on the strategy_proposals stream
    assert call[1].get("stream") == "strategy_proposals" or call[0][0] == "strategy_proposals"
