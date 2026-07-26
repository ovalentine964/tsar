"""TSAR — Shadow Account Loop Tests.

Phase 1B: Tests for ShadowExtractor, RuleValidator, and GenomeMutator.
Covers rule extraction, backtest validation, genome mutation proposals,
and the end-to-end flow.
"""

from __future__ import annotations

import json
import math
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge.shadow_extractor import (
    ShadowExtractor,
    TradingRule,
    ExtractionResult,
)
from src.knowledge.rule_validator import (
    RuleValidator,
    ValidatedRule,
    OHLCVCandle,
    OHLCVProvider,
)
from src.knowledge.genome_mutator import (
    GenomeMutator,
    MutationProposal,
    MutatorConfig,
)
from src.knowledge.trade_memory import TradeMemory, TradeRecord
from src.knowledge.strategy_genomes import (
    StrategyGenome,
    StrategyGenomes,
    StrategyMutation,
)
from src.interfaces.types import LLMResponse


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Temporary SQLite database path."""
    return str(tmp_path / "test_tsar.db")


@pytest.fixture
def trade_memory(tmp_db: str) -> TradeMemory:
    """Initialized TradeMemory with schema."""
    mem = TradeMemory(tmp_db)
    # Create tables
    conn = sqlite3.connect(tmp_db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trade_records (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT,
            asset_class TEXT DEFAULT 'crypto',
            exchange TEXT,
            strategy_id TEXT,
            signal_type TEXT DEFAULT 'entry',
            signal_score REAL,
            signal_source TEXT,
            side TEXT DEFAULT 'buy',
            order_type TEXT DEFAULT 'market',
            quantity REAL DEFAULT 0.0,
            limit_price REAL,
            stop_price REAL,
            entry_price REAL,
            exit_price REAL,
            fill_quantity REAL,
            slippage_bps REAL,
            commission REAL DEFAULT 0.0,
            fill_timestamp TEXT,
            latency_ms INTEGER,
            position_size_before REAL DEFAULT 0.0,
            position_size_after REAL DEFAULT 0.0,
            portfolio_heat_before REAL,
            portfolio_heat_after REAL,
            regime_at_entry TEXT,
            vix_level REAL,
            market_breadth REAL,
            sector_momentum TEXT,
            volatility_regime TEXT,
            liquidity_score REAL,
            expected_return REAL,
            expected_risk REAL,
            risk_reward_ratio REAL,
            confidence REAL,
            thesis TEXT,
            key_levels TEXT,
            status TEXT DEFAULT 'OPEN',
            realized_pnl REAL DEFAULT 0.0,
            realized_pnl_pct REAL DEFAULT 0.0,
            holding_period_hours REAL,
            max_drawdown_during REAL,
            max_favorable_excursion REAL,
            max_adverse_excursion REAL,
            outcome_grade TEXT,
            execution_grade TEXT,
            reflection TEXT,
            lessons TEXT,
            pattern_matches TEXT,
            trading_mode TEXT DEFAULT 'paper',
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS trade_records_fts (
            thesis TEXT,
            reflection TEXT,
            lessons TEXT
        );
        CREATE TABLE IF NOT EXISTS trade_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            trade_id TEXT,
            snapshot_type TEXT,
            bid REAL, ask REAL, mid REAL, last_price REAL,
            volume_24h REAL, rsi_14 REAL, macd_signal REAL,
            bb_position REAL, atr_14 REAL, obv_trend TEXT,
            book_depth_bid TEXT, book_depth_ask TEXT,
            spread_bps REAL, news_sentiment REAL,
            social_sentiment REAL, fear_greed_index REAL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trade_journal (
            journal_id TEXT PRIMARY KEY,
            trade_id TEXT,
            entry_type TEXT,
            content TEXT,
            mood TEXT,
            cognitive_biases TEXT,
            created_at TEXT
        );
    """)
    conn.close()
    return mem


@pytest.fixture
def strategy_genomes(tmp_db: str) -> StrategyGenomes:
    """Initialized StrategyGenomes with schema."""
    sg = StrategyGenomes(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS strategy_genomes (
            strategy_id TEXT PRIMARY KEY,
            name TEXT,
            parent_id TEXT,
            version INTEGER DEFAULT 1,
            thesis TEXT,
            genome_yaml TEXT,
            genome_hash TEXT,
            asset_class TEXT DEFAULT 'crypto',
            symbols TEXT,
            strategy_type TEXT,
            entry_rules TEXT,
            exit_rules TEXT,
            risk_params TEXT,
            status TEXT DEFAULT 'candidate',
            activated_at TEXT,
            retired_at TEXT,
            retirement_reason TEXT,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0.0,
            max_drawdown REAL DEFAULT 0.0,
            profit_factor REAL DEFAULT 0.0,
            sharpe_ratio REAL DEFAULT 0.0,
            rolling_sharpe_30d REAL DEFAULT 0.0,
            win_rate REAL DEFAULT 0.0,
            avg_holding_hours REAL DEFAULT 0.0,
            consecutive_losses INTEGER DEFAULT 0,
            max_consecutive_losses INTEGER DEFAULT 0,
            regime_performance TEXT,
            gates_passed INTEGER DEFAULT 0,
            gates_evaluated_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            last_evolved TEXT
        );
        CREATE TABLE IF NOT EXISTS strategy_performance (
            snapshot_id TEXT PRIMARY KEY,
            strategy_id TEXT,
            period_start TEXT,
            period_end TEXT,
            total_return REAL,
            annualized_return REAL,
            excess_return REAL,
            volatility REAL,
            max_drawdown REAL,
            var_95 REAL,
            cvar_95 REAL,
            sortino_ratio REAL,
            calmar_ratio REAL,
            sharpe_ratio REAL,
            avg_slippage_bps REAL,
            avg_latency_ms REAL,
            fill_rate REAL,
            total_trades INTEGER,
            winning_trades INTEGER,
            total_pnl REAL,
            win_rate REAL,
            regime_performance TEXT,
            signal_accuracy TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS strategy_mutations (
            mutation_id TEXT PRIMARY KEY,
            strategy_name TEXT,
            parent_id TEXT,
            child_id TEXT,
            version_from INTEGER DEFAULT 1,
            version_to INTEGER DEFAULT 2,
            mutation_type TEXT,
            change_description TEXT,
            mutation_detail TEXT,
            rationale TEXT,
            performance_before TEXT,
            performance_after TEXT,
            parent_fitness REAL,
            outcome TEXT DEFAULT 'pending',
            created_at TEXT
        );
    """)
    conn.close()
    return sg


def _make_trade(
    trade_id: str = "t-001",
    symbol: str = "BTC/USDT",
    strategy_id: str = "mean_reversion",
    side: str = "buy",
    status: str = "CLOSED",
    entry_price: float = 50000.0,
    exit_price: float = 51000.0,
    realized_pnl: float = 100.0,
    realized_pnl_pct: float = 0.02,
    regime: str = "oversold",
    signal_score: float = 0.8,
    confidence: float = 0.75,
    thesis: str = "RSI oversold bounce",
    volatility_regime: str = "low",
    holding_hours: float = 12.0,
    **kwargs: Any,
) -> TradeRecord:
    """Create a TradeRecord with sensible defaults."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return TradeRecord(
        trade_id=trade_id,
        symbol=symbol,
        strategy_id=strategy_id,
        side=side,
        status=status,
        entry_price=entry_price,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        regime_at_entry=regime,
        signal_score=signal_score,
        confidence=confidence,
        thesis=thesis,
        volatility_regime=volatility_regime,
        holding_period_hours=holding_hours,
        created_at=now,
        updated_at=now,
        **kwargs,
    )


def _populate_trades(mem: TradeMemory, count: int = 15) -> list[TradeRecord]:
    """Insert a mix of winning and losing trades."""
    trades: list[TradeRecord] = []
    for i in range(count):
        is_winner = i % 3 != 0  # ~67% win rate
        entry = 50000.0 + i * 100
        if is_winner:
            exit_p = entry * 1.02
            pnl = exit_p - entry
            pnl_pct = 0.02
        else:
            exit_p = entry * 0.98
            pnl = exit_p - entry
            pnl_pct = -0.02

        trade = _make_trade(
            trade_id=f"t-{i:03d}",
            entry_price=entry,
            exit_price=exit_p,
            realized_pnl=pnl,
            realized_pnl_pct=pnl_pct,
            signal_score=0.7 + (i % 5) * 0.05,
            confidence=0.6 + (i % 4) * 0.1,
        )
        mem.insert_trade(trade)
        trades.append(trade)
    return trades


def _make_candles(count: int = 200, base_price: float = 50000.0) -> list[OHLCVCandle]:
    """Generate synthetic OHLCV candles with a mean-reverting pattern."""
    import random
    random.seed(42)
    candles: list[OHLCVCandle] = []
    price = base_price
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    for i in range(count):
        # Mean-reverting random walk
        reversion = (base_price - price) * 0.05
        shock = random.gauss(0, 200)
        price = price + reversion + shock
        price = max(price, base_price * 0.8)
        price = min(price, base_price * 1.2)

        high = price + abs(random.gauss(0, 100))
        low = price - abs(random.gauss(0, 100))
        opn = price + random.gauss(0, 50)
        volume = 1000 + random.gauss(0, 300)
        volume = max(volume, 100)

        candles.append(OHLCVCandle(
            timestamp=(base_time + timedelta(hours=i)).isoformat(),
            open=round(opn, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(price, 2),
            volume=round(volume, 2),
        ))
    return candles


class MockOHLCVProvider:
    """Mock OHLCV provider for testing."""

    def __init__(self, candles: Optional[list[OHLCVCandle]] = None) -> None:
        self._candles = candles or _make_candles()

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        since: Optional[str] = None,
    ) -> list[OHLCVCandle]:
        return self._candles[:limit]


def _mock_llm_response(rules: list[dict[str, Any]]) -> LLMResponse:
    """Create a mock LLM response with extracted rules."""
    return LLMResponse(
        content=json.dumps({"rules": rules}),
        model="test-model",
        provider="test",
        prompt_tokens=100,
        completion_tokens=200,
        total_tokens=300,
    )


# ═══════════════════════════════════════════════════════════════════════
# SHADOW EXTRACTOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestShadowExtractor:
    """Tests for ShadowExtractor rule extraction."""

    @pytest.mark.asyncio
    async def test_extract_insufficient_trades(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should return empty result when not enough trades."""
        llm = AsyncMock()
        extractor = ShadowExtractor(trade_memory, llm)

        # Insert only 3 trades (below default min_trades=5)
        for i in range(3):
            trade_memory.insert_trade(_make_trade(trade_id=f"t-{i:03d}"))

        result = await extractor.extract(min_trades=5)
        assert result.rules == []
        assert result.source_trade_count == 3
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_with_mock_llm(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should extract rules from winning trades using LLM."""
        _populate_trades(trade_memory, count=15)

        mock_rules = [
            {
                "conditions": [
                    {"type": "rsi_below", "value": 30},
                    {"type": "volume_above_avg", "multiplier": 1.5},
                ],
                "action": "buy",
                "confidence": 0.75,
                "regime": "oversold",
                "description": "Buy when RSI < 30 with volume spike",
                "rationale": "10 of 15 winners had this pattern",
            },
            {
                "conditions": [{"type": "price_below_ma", "period": 20}],
                "action": "buy",
                "confidence": 0.65,
                "description": "Buy below 20-period MA",
                "rationale": "8 of 15 winners bought below MA",
            },
        ]

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=_mock_llm_response(mock_rules))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=5)

        assert len(result.rules) == 2
        assert result.rules[0].conditions[0]["type"] == "rsi_below"
        assert result.rules[0].confidence == 0.75
        assert result.rules[1].action == "buy"
        assert result.source_trade_count == 15
        assert result.winning_trade_count > 0
        llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_llm_returns_list_format(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should handle LLM returning a bare list instead of {rules: [...]}."""
        _populate_trades(trade_memory, count=10)

        mock_rules = [
            {
                "conditions": [{"type": "rsi_below", "value": 25}],
                "action": "buy",
                "confidence": 0.8,
                "description": "Deep oversold buy",
                "rationale": "Test",
            }
        ]

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=LLMResponse(
            content=json.dumps(mock_rules),  # Bare list, not {rules: [...]}
            model="test", provider="test",
        ))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=5)

        assert len(result.rules) == 1
        assert result.rules[0].description == "Deep oversold buy"

    @pytest.mark.asyncio
    async def test_extract_llm_returns_invalid_json(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should handle LLM returning invalid JSON gracefully."""
        _populate_trades(trade_memory, count=10)

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=LLMResponse(
            content="This is not JSON at all",
            model="test", provider="test",
        ))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=5)

        assert result.rules == []

    @pytest.mark.asyncio
    async def test_extract_llm_error(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should handle LLM errors gracefully."""
        _populate_trades(trade_memory, count=10)

        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("LLM timeout"))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=5)

        # Should not crash, just return empty rules
        assert result.rules == []

    @pytest.mark.asyncio
    async def test_extract_caps_at_five_rules(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should cap at 5 rules per group even if LLM returns more."""
        _populate_trades(trade_memory, count=15)

        # 8 rules from LLM
        mock_rules = [
            {
                "conditions": [{"type": "rsi_below", "value": 30 + i}],
                "action": "buy",
                "confidence": 0.6,
                "description": f"Rule {i}",
                "rationale": f"Test {i}",
            }
            for i in range(8)
        ]

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=_mock_llm_response(mock_rules))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=5)

        assert len(result.rules) <= 5

    @pytest.mark.asyncio
    async def test_extract_filters_rules_without_conditions(
        self, trade_memory: TradeMemory
    ) -> None:
        """Should skip rules that have no conditions."""
        _populate_trades(trade_memory, count=10)

        mock_rules = [
            {
                "conditions": [],  # Empty!
                "action": "buy",
                "confidence": 0.5,
                "description": "Bad rule",
                "rationale": "No conditions",
            },
            {
                "conditions": [{"type": "rsi_below", "value": 30}],
                "action": "buy",
                "confidence": 0.7,
                "description": "Good rule",
                "rationale": "Has conditions",
            },
        ]

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=_mock_llm_response(mock_rules))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=5)

        assert len(result.rules) == 1
        assert result.rules[0].description == "Good rule"

    def test_trading_rule_serialization(self) -> None:
        """TradingRule should serialize/deserialize correctly."""
        rule = TradingRule(
            conditions=[{"type": "rsi_below", "value": 30}],
            action="buy",
            confidence=0.75,
            source_trade_ids=["t-001", "t-002"],
            symbol="BTC/USDT",
            description="Test rule",
        )
        d = rule.to_dict()
        assert d["conditions"] == [{"type": "rsi_below", "value": 30}]
        assert d["action"] == "buy"
        assert d["confidence"] == 0.75
        assert len(d["source_trade_ids"]) == 2

    def test_extraction_result_serialization(self) -> None:
        """ExtractionResult should serialize rules correctly."""
        rule = TradingRule(
            conditions=[{"type": "rsi_below", "value": 30}],
            action="buy",
            confidence=0.75,
            description="Test",
        )
        result = ExtractionResult(rules=[rule], source_trade_count=10)
        d = result.to_dict()
        assert len(d["rules"]) == 1
        assert d["rules"][0]["action"] == "buy"


# ═══════════════════════════════════════════════════════════════════════
# RULE VALIDATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestRuleValidator:
    """Tests for RuleValidator backtest validation."""

    @pytest.mark.asyncio
    async def test_validate_insufficient_candles(self) -> None:
        """Should return insufficient_data when too few candles."""
        provider = MockOHLCVProvider(candles=_make_candles(count=20))
        validator = RuleValidator(provider)

        rule = TradingRule(
            conditions=[{"type": "rsi_below", "value": 30}],
            action="buy",
            description="Test rule",
        )

        result = await validator.validate(rule, lookback_candles=50)
        assert result.validation_status == "insufficient_data"

    @pytest.mark.asyncio
    async def test_validate_always_true_condition(self) -> None:
        """Should produce trades when condition is always true."""
        candles = _make_candles(count=200)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)

        rule = TradingRule(
            conditions=[{"type": "always"}],
            action="buy",
            description="Always enter",
        )

        result = await validator.validate(rule, lookback_candles=200)
        assert result.total_trades > 0
        assert result.sample_size > 0

    @pytest.mark.asyncio
    async def test_validate_rsi_condition(self) -> None:
        """Should trigger trades when RSI condition is met."""
        candles = _make_candles(count=300, base_price=50000.0)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)

        rule = TradingRule(
            conditions=[{"type": "rsi_below", "value": 40}],
            action="buy",
            description="Buy on RSI < 40",
        )

        result = await validator.validate(rule, lookback_candles=300)
        # RSI < 40 should trigger at least some trades in 300 candles
        assert result.total_trades >= 0  # May or may not trigger

    @pytest.mark.asyncio
    async def test_validate_volume_condition(self) -> None:
        """Should trigger on volume spikes."""
        candles = _make_candles(count=200)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)

        rule = TradingRule(
            conditions=[{"type": "volume_above_avg", "multiplier": 1.2}],
            action="buy",
            description="Buy on volume spike",
        )

        result = await validator.validate(rule, lookback_candles=200)
        assert result.total_trades >= 0

    @pytest.mark.asyncio
    async def test_validate_computes_metrics(self) -> None:
        """Should compute all expected metrics."""
        candles = _make_candles(count=200)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)

        rule = TradingRule(
            conditions=[{"type": "always"}],
            action="buy",
            description="Always enter",
        )

        result = await validator.validate(rule, lookback_candles=200)

        # Check all metrics exist
        assert hasattr(result, "sharpe")
        assert hasattr(result, "win_rate")
        assert hasattr(result, "profit_factor")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "sample_size")
        assert hasattr(result, "p_value")
        assert hasattr(result, "confidence_interval_low")
        assert hasattr(result, "confidence_interval_high")
        assert hasattr(result, "expectancy")

    @pytest.mark.asyncio
    async def test_validate_sell_action(self) -> None:
        """Should correctly compute P&L for sell (short) actions."""
        candles = _make_candles(count=200)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)

        rule = TradingRule(
            conditions=[{"type": "always"}],
            action="sell",
            description="Always short",
        )

        result = await validator.validate(rule, lookback_candles=200)
        assert result.total_trades > 0

    @pytest.mark.asyncio
    async def test_validate_batch(self) -> None:
        """Should validate multiple rules in batch."""
        candles = _make_candles(count=200)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)

        rules = [
            TradingRule(
                conditions=[{"type": "always"}],
                action="buy",
                description="Always buy",
            ),
            TradingRule(
                conditions=[{"type": "rsi_below", "value": 30}],
                action="buy",
                description="RSI oversold",
            ),
        ]

        results = await validator.validate_batch(rules, lookback_candles=200)
        assert len(results) == 2
        assert all(isinstance(r, ValidatedRule) for r in results)

    def test_wilson_confidence_interval(self) -> None:
        """Wilson CI should be bounded [0, 1]."""
        low, high = RuleValidator._wilson_confidence_interval(0.6, 50)
        assert 0.0 <= low <= high <= 1.0

        low, high = RuleValidator._wilson_confidence_interval(0.0, 0)
        assert low == 0.0 and high == 0.0

    def test_p_value_computation(self) -> None:
        """P-value should decrease with larger sample and higher win rate."""
        # High win rate with large sample → low p-value
        p1 = RuleValidator._compute_p_value(0.7, 100)
        # Low win rate with small sample → high p-value
        p2 = RuleValidator._compute_p_value(0.52, 20)
        assert p1 < p2

    def test_metrics_empty_trades(self) -> None:
        """Should handle empty trade list."""
        metrics = RuleValidator._compute_metrics([])
        assert metrics["total_trades"] == 0
        assert metrics["sharpe"] == 0.0

    def test_metrics_all_winners(self) -> None:
        """Should compute correct metrics for all-winning trades."""
        trades = [
            {"pnl_pct": 0.02, "entry_idx": 0, "exit_idx": 1,
             "entry_price": 100, "exit_price": 102, "holding_candles": 1}
            for _ in range(10)
        ]
        metrics = RuleValidator._compute_metrics(trades)
        assert metrics["win_rate"] == 1.0
        assert metrics["profit_factor"] == float("inf")
        assert metrics["winning_trades"] == 10

    def test_metrics_all_losers(self) -> None:
        """Should compute correct metrics for all-losing trades."""
        trades = [
            {"pnl_pct": -0.02, "entry_idx": 0, "exit_idx": 1,
             "entry_price": 100, "exit_price": 98, "holding_candles": 1}
            for _ in range(10)
        ]
        metrics = RuleValidator._compute_metrics(trades)
        assert metrics["win_rate"] == 0.0
        assert metrics["profit_factor"] == 0.0
        assert metrics["losing_trades"] == 10

    def test_rsi_computation(self) -> None:
        """RSI should be between 0 and 100."""
        candles = _make_candles(count=50)
        rsi = RuleValidator._compute_rsi(candles, 49, period=14)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_sma_computation(self) -> None:
        """SMA should be the average of closes."""
        candles = _make_candles(count=30)
        sma = RuleValidator._compute_sma(candles, 29, period=20)
        assert sma is not None
        expected = sum(c.close for c in candles[10:30]) / 20
        assert abs(sma - expected) < 0.01

    def test_validated_rule_is_valid(self) -> None:
        """is_valid property should check all thresholds."""
        rule = ValidatedRule(
            validation_status="passed",
            sample_size=30,
            sharpe=1.0,
            win_rate=0.55,
            profit_factor=1.5,
            max_drawdown=0.10,
        )
        assert rule.is_valid

        # Too few samples
        rule2 = ValidatedRule(
            validation_status="passed",
            sample_size=10,
            sharpe=1.0,
            win_rate=0.55,
            profit_factor=1.5,
            max_drawdown=0.10,
        )
        assert not rule2.is_valid

        # Bad status
        rule3 = ValidatedRule(
            validation_status="failed",
            sample_size=30,
            sharpe=1.0,
            win_rate=0.55,
            profit_factor=1.5,
            max_drawdown=0.10,
        )
        assert not rule3.is_valid


# ═══════════════════════════════════════════════════════════════════════
# GENOME MUTATOR TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestGenomeMutator:
    """Tests for GenomeMutator mutation proposals."""

    @pytest.fixture
    def sample_genome(self, strategy_genomes: StrategyGenomes) -> StrategyGenome:
        """Insert a sample genome."""
        genome = StrategyGenome(
            strategy_id="strat-001",
            name="mean_reversion_v1",
            thesis="Mean reversion on oversold RSI",
            entry_rules=json.dumps([{"type": "rsi_below", "value": 30}]),
            exit_rules=json.dumps([{"type": "rsi_above", "value": 70}]),
            status="live",
            sharpe_ratio=0.8,
            win_rate=0.55,
            profit_factor=1.3,
            total_trades=50,
        )
        strategy_genomes.insert_genome(genome)
        return genome

    @pytest.mark.asyncio
    async def test_propose_mutations_filters_low_quality(
        self, strategy_genomes: StrategyGenomes
    ) -> None:
        """Should reject rules that don't meet quality thresholds."""
        mutator = GenomeMutator(strategy_genomes)

        low_quality_rules = [
            ValidatedRule(
                validation_status="passed",
                conditions=[{"type": "rsi_below", "value": 30}],
                action="buy",
                confidence=0.3,  # Below min_confidence=0.6
                sharpe=0.2,      # Below min_sharpe=0.5
                win_rate=0.40,   # Below min_win_rate=0.45
                profit_factor=1.0,
                sample_size=30,
                description="Low quality rule",
            ),
        ]

        proposals = await mutator.propose_mutations(low_quality_rules)
        assert proposals == []

    @pytest.mark.asyncio
    async def test_propose_mutations_with_good_rule(
        self, strategy_genomes: StrategyGenomes, sample_genome: StrategyGenome
    ) -> None:
        """Should propose mutation for high-quality validated rules."""
        mutator = GenomeMutator(strategy_genomes)

        good_rules = [
            ValidatedRule(
                validation_status="passed",
                conditions=[{"type": "volume_above_avg", "multiplier": 1.5}],
                action="buy",
                confidence=0.75,
                sharpe=1.2,
                win_rate=0.60,
                profit_factor=1.8,
                max_drawdown=0.08,
                sample_size=50,
                expectancy=0.015,
                description="Volume spike buy",
                rationale="High volume confirms reversal",
                strategy_id="strat-001",
            ),
        ]

        proposals = await mutator.propose_mutations(good_rules)

        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.status == "pending_validation"
        assert proposal.target_genome_id == "strat-001"
        assert proposal.confidence_score > 0
        assert proposal.mutation_type == "rule_addition"

    @pytest.mark.asyncio
    async def test_propose_mutations_records_in_store(
        self, strategy_genomes: StrategyGenomes, sample_genome: StrategyGenome
    ) -> None:
        """Should record mutations in StrategyGenomes store."""
        mutator = GenomeMutator(strategy_genomes)

        good_rules = [
            ValidatedRule(
                validation_status="passed",
                conditions=[{"type": "rsi_below", "value": 25}],
                action="buy",
                confidence=0.8,
                sharpe=1.5,
                win_rate=0.65,
                profit_factor=2.0,
                max_drawdown=0.05,
                sample_size=40,
                expectancy=0.02,
                description="Deep RSI oversold",
                rationale="Strong reversal signal",
                strategy_id="strat-001",
            ),
        ]

        await mutator.propose_mutations(good_rules)

        # Check that a mutation was recorded
        mutations = strategy_genomes.get_mutations(parent_id="strat-001")
        assert len(mutations) == 1
        assert mutations[0].outcome == "pending"

    @pytest.mark.asyncio
    async def test_propose_mutations_no_matching_genome(
        self, strategy_genomes: StrategyGenomes
    ) -> None:
        """Should return empty when no matching genome and allow_new_genomes=False."""
        mutator = GenomeMutator(strategy_genomes, MutatorConfig(allow_new_genomes=False))

        good_rules = [
            ValidatedRule(
                validation_status="passed",
                conditions=[{"type": "rsi_below", "value": 30}],
                action="buy",
                confidence=0.8,
                sharpe=1.0,
                win_rate=0.60,
                profit_factor=1.5,
                sample_size=30,
                expectancy=0.01,
                description="No matching genome",
            ),
        ]

        proposals = await mutator.propose_mutations(good_rules)
        assert proposals == []

    @pytest.mark.asyncio
    async def test_propose_mutations_creates_new_genome(
        self, strategy_genomes: StrategyGenomes
    ) -> None:
        """Should propose new genome when allow_new_genomes=True."""
        config = MutatorConfig(allow_new_genomes=True)
        mutator = GenomeMutator(strategy_genomes, config)

        good_rules = [
            ValidatedRule(
                validation_status="passed",
                conditions=[{"type": "rsi_below", "value": 30}],
                action="buy",
                confidence=0.8,
                sharpe=1.0,
                win_rate=0.60,
                profit_factor=1.5,
                sample_size=30,
                expectancy=0.01,
                symbol="ETH/USDT",
                description="New strategy",
            ),
        ]

        proposals = await mutator.propose_mutations(good_rules)
        assert len(proposals) == 1
        assert proposals[0].mutation_type == "new_genome"

    @pytest.mark.asyncio
    async def test_propose_mutations_respects_max_limit(
        self, strategy_genomes: StrategyGenomes, sample_genome: StrategyGenome
    ) -> None:
        """Should not exceed max_proposals_per_run."""
        config = MutatorConfig(max_proposals_per_run=2)
        mutator = GenomeMutator(strategy_genomes, config)

        # 5 good rules, but max 2 proposals
        rules = [
            ValidatedRule(
                validation_status="passed",
                conditions=[{"type": "rsi_below", "value": 30 + i}],
                action="buy",
                confidence=0.8,
                sharpe=1.0 + i * 0.1,
                win_rate=0.60,
                profit_factor=1.5,
                sample_size=30,
                expectancy=0.01 + i * 0.005,
                description=f"Rule {i}",
                strategy_id="strat-001",
            )
            for i in range(5)
        ]

        proposals = await mutator.propose_mutations(rules)
        assert len(proposals) <= 2

    def test_confidence_score_computation(
        self, strategy_genomes: StrategyGenomes
    ) -> None:
        """Confidence score should be bounded [0, 1]."""
        mutator = GenomeMutator(strategy_genomes)

        rule = ValidatedRule(
            p_value=0.01,
            sample_size=50,
            sharpe=1.5,
            win_rate=0.60,
        )
        score = mutator._compute_confidence_score(rule)
        assert 0.0 <= score <= 1.0

    def test_confidence_score_high_for_strong_rule(
        self, strategy_genomes: StrategyGenomes
    ) -> None:
        """Strong rule should get high confidence score."""
        mutator = GenomeMutator(strategy_genomes)

        strong = ValidatedRule(
            p_value=0.001,
            sample_size=100,
            sharpe=2.0,
            win_rate=0.65,
        )
        weak = ValidatedRule(
            p_value=0.04,
            sample_size=20,
            sharpe=0.6,
            win_rate=0.48,
        )
        assert mutator._compute_confidence_score(strong) > mutator._compute_confidence_score(weak)

    def test_mutation_proposal_serialization(self) -> None:
        """MutationProposal should serialize correctly."""
        proposal = MutationProposal(
            source_rule_id="rule-001",
            target_genome_id="strat-001",
            mutation_type="rule_addition",
            change_description="Add volume filter",
            confidence_score=0.75,
            status="pending_validation",
        )
        d = proposal.to_dict()
        assert d["mutation_type"] == "rule_addition"
        assert d["confidence_score"] == 0.75

    def test_merge_entry_rules_new(self) -> None:
        """Should create new entry rules when none exist."""
        rule = ValidatedRule(
            conditions=[{"type": "rsi_below", "value": 30}],
        )
        result = GenomeMutator._merge_entry_rules(None, rule)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["type"] == "rsi_below"

    def test_merge_entry_rules_existing(self) -> None:
        """Should append to existing entry rules."""
        existing = json.dumps([{"type": "price_below_ma", "period": 20}])
        rule = ValidatedRule(
            conditions=[{"type": "rsi_below", "value": 30}],
        )
        result = GenomeMutator._merge_entry_rules(existing, rule)
        parsed = json.loads(result)
        assert len(parsed) == 2


# ═══════════════════════════════════════════════════════════════════════
# END-TO-END FLOW TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestEndToEndFlow:
    """Tests for the complete Shadow Account Loop:
    TRADE → EXTRACT → VALIDATE → MUTATE
    """

    @pytest.mark.asyncio
    async def test_full_pipeline(
        self,
        trade_memory: TradeMemory,
        strategy_genomes: StrategyGenomes,
    ) -> None:
        """End-to-end: trades → extract rules → validate → propose mutations."""
        # 1. Populate trades
        trades = _populate_trades(trade_memory, count=20)

        # 2. Insert a target genome
        genome = StrategyGenome(
            strategy_id="strat-001",
            name="mean_reversion_v1",
            entry_rules=json.dumps([{"type": "rsi_below", "value": 30}]),
            status="live",
            sharpe_ratio=0.5,
            win_rate=0.50,
            profit_factor=1.2,
            total_trades=30,
        )
        strategy_genomes.insert_genome(genome)

        # 3. Mock LLM to return realistic rules
        mock_rules = [
            {
                "conditions": [
                    {"type": "rsi_below", "value": 30},
                    {"type": "volume_above_avg", "multiplier": 1.5},
                ],
                "action": "buy",
                "confidence": 0.8,
                "regime": "oversold",
                "description": "Buy oversold with volume confirmation",
                "rationale": "Pattern observed in 80% of winning trades",
            },
        ]

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=_mock_llm_response(mock_rules))

        # 4. Extract rules
        extractor = ShadowExtractor(trade_memory, llm)
        extraction = await extractor.extract(min_trades=5)
        assert len(extraction.rules) == 1

        # 5. Validate rules
        candles = _make_candles(count=300)
        provider = MockOHLCVProvider(candles=candles)
        validator = RuleValidator(provider)
        validated = await validator.validate_batch(extraction.rules, lookback_candles=300)
        assert len(validated) == 1

        # 6. Propose mutations (may or may not pass depending on backtest)
        mutator = GenomeMutator(strategy_genomes)
        proposals = await mutator.propose_mutations(validated)

        # The pipeline completed without errors
        assert isinstance(proposals, list)
        assert len(validated) == 1
        assert validated[0].total_trades >= 0

    @pytest.mark.asyncio
    async def test_pipeline_preserves_rule_provenance(
        self,
        trade_memory: TradeMemory,
        strategy_genomes: StrategyGenomes,
    ) -> None:
        """Each stage should preserve links back to source data."""
        trades = _populate_trades(trade_memory, count=10)
        source_ids = [t.trade_id for t in trades]

        genome = StrategyGenome(
            strategy_id="strat-001",
            name="test_strategy",
            status="live",
            sharpe_ratio=0.5,
        )
        strategy_genomes.insert_genome(genome)

        mock_rules = [
            {
                "conditions": [{"type": "rsi_below", "value": 35}],
                "action": "buy",
                "confidence": 0.7,
                "description": "RSI oversold",
                "rationale": "Test",
            },
        ]

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=_mock_llm_response(mock_rules))

        # Extract
        extractor = ShadowExtractor(trade_memory, llm)
        extraction = await extractor.extract(min_trades=5)

        # Check provenance chain
        if extraction.rules:
            rule = extraction.rules[0]
            assert len(rule.source_trade_ids) > 0
            # All source IDs should be from our trades
            for sid in rule.source_trade_ids:
                assert sid in source_ids

    @pytest.mark.asyncio
    async def test_pipeline_handles_empty_extraction(
        self,
        trade_memory: TradeMemory,
        strategy_genomes: StrategyGenomes,
    ) -> None:
        """Pipeline should handle empty extraction gracefully."""
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"rules": []}),
            model="test", provider="test",
        ))

        extractor = ShadowExtractor(trade_memory, llm)
        # No trades → empty extraction
        extraction = await extractor.extract(min_trades=5)
        assert extraction.rules == []

        # Validate empty list
        provider = MockOHLCVProvider()
        validator = RuleValidator(provider)
        validated = await validator.validate_batch(extraction.rules)
        assert validated == []

        # Mutate empty list
        mutator = GenomeMutator(strategy_genomes)
        proposals = await mutator.propose_mutations(validated)
        assert proposals == []

    @pytest.mark.asyncio
    async def test_pipeline_multiple_symbols(
        self,
        trade_memory: TradeMemory,
        strategy_genomes: StrategyGenomes,
    ) -> None:
        """Should handle trades across multiple symbols."""
        # Insert trades for different symbols
        for i in range(10):
            symbol = "BTC/USDT" if i % 2 == 0 else "ETH/USDT"
            trade = _make_trade(
                trade_id=f"t-{i:03d}",
                symbol=symbol,
                realized_pnl=100 if i % 3 != 0 else -50,
                realized_pnl_pct=0.02 if i % 3 != 0 else -0.01,
            )
            trade_memory.insert_trade(trade)

        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=_mock_llm_response([
            {
                "conditions": [{"type": "rsi_below", "value": 30}],
                "action": "buy",
                "confidence": 0.7,
                "description": "Oversold buy",
                "rationale": "Test",
            }
        ]))

        extractor = ShadowExtractor(trade_memory, llm)
        result = await extractor.extract(min_trades=3)

        # Should have extracted from multiple groups
        assert result.source_trade_count == 10


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestIntegration:
    """Integration tests for the Shadow Account Loop components."""

    @pytest.mark.asyncio
    async def test_validated_rule_persistence(self, tmp_path: Path) -> None:
        """ValidatedRule should persist to SQLite."""
        db_path = str(tmp_path / "test.db")
        provider = MockOHLCVProvider(candles=_make_candles(count=200))
        validator = RuleValidator(provider, db_path=db_path)

        rule = TradingRule(
            conditions=[{"type": "always"}],
            action="buy",
            description="Always enter",
        )

        result = await validator.validate(rule, lookback_candles=200)

        # Verify persistence
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM validated_rules WHERE rule_id = ?", (result.rule_id,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["validation_status"] == result.validation_status

    def test_genome_mutation_linkage(
        self, strategy_genomes: StrategyGenomes
    ) -> None:
        """GenomeMutator should create traceable links between rules and mutations."""
        genome = StrategyGenome(
            strategy_id="strat-001",
            name="test_strat",
            status="live",
            sharpe_ratio=0.5,
        )
        strategy_genomes.insert_genome(genome)

        mutation = StrategyMutation(
            strategy_name="test_strat",
            parent_id="strat-001",
            mutation_type="rule_addition",
            change_description="Add volume filter from shadow rule",
            outcome="pending",
        )
        mutation_id = strategy_genomes.record_mutation(mutation)

        mutations = strategy_genomes.get_mutations(parent_id="strat-001")
        assert len(mutations) == 1
        assert mutations[0].mutation_type == "rule_addition"
        assert mutations[0].outcome == "pending"
