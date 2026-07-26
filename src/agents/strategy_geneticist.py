"""
Strategy Geneticist — Evolve strategies, run backtests, retire underperformers.

Role: ANALYSIS (Level 3+)
Model Tier: T0 (backtesting math) + T2 (strategy_evaluation) + T3 (strategy_synthesis)

Strategy retirement gates:
  - Rolling Sharpe < 0.5 for 30 days → RETIRE
  - Drawdown > 15% → PAUSE, > 20% → RETIRE
  - Win rate < 40% over 50 trades → RETIRE

Subscribes to: tsar:stream:analytics, tsar:stream:regime, tsar:stream:fills,
               tsar:stream:strategy_proposals
Publishes to: tsar:stream:strategy_mutations

Integration (G6–G9):
  G6: BacktestEngine — backtest mutation proposals before accepting
  G7: WalkForwardValidator — detect overfitting after backtest passes
  G8: MonteCarloSimulator — compute confidence intervals after walk-forward
  G9: FactorBenchmarker — periodic IC/IR benchmarks on factor library
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.agents.base import BaseAgent
from src.strategy.backtest_engine import BacktestConfig, BacktestEngine, BacktestResult
from src.strategy.factor_bench import FactorBenchmarker, FactorBenchmarkResult
from src.strategy.factor_library import FactorLibrary
from src.strategy.monte_carlo import MonteCarloConfig, MonteCarloResult, MonteCarloSimulator
from src.strategy.walk_forward import WalkForwardConfig, WalkForwardResult, WalkForwardValidator

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# EVALUATION RESULT
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class StrategyEvaluation:
    """Full evaluation result for a strategy or mutation proposal."""

    strategy_name: str
    backtest_result: BacktestResult | None = None
    walk_forward_result: WalkForwardResult | None = None
    monte_carlo_result: MonteCarloResult | None = None
    accepted: bool = False
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        """Compact summary for logging/events."""
        d: dict[str, Any] = {
            "strategy": self.strategy_name,
            "accepted": self.accepted,
            "rejection_reasons": self.rejection_reasons,
        }
        if self.backtest_result:
            m = self.backtest_result.metrics
            d["backtest"] = {
                "sharpe": m.sharpe_ratio,
                "win_rate": m.win_rate,
                "max_drawdown": m.max_drawdown,
                "total_trades": m.total_trades,
                "profit_factor": m.profit_factor,
            }
        if self.walk_forward_result:
            wf = self.walk_forward_result
            d["walk_forward"] = {
                "overfitting_score": wf.overfitting_score,
                "is_overfit": wf.is_overfit,
                "consistency_score": wf.consistency_score,
            }
        if self.monte_carlo_result:
            mc = self.monte_carlo_result
            d["monte_carlo"] = {
                "probability_of_profit": mc.probability_of_profit,
                "probability_of_ruin": mc.probability_of_ruin,
                "sharpe_ci": mc.confidence_intervals.get("sharpe_ratio", {}),
            }
        return d


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY GENETICIST AGENT
# ═══════════════════════════════════════════════════════════════════════


class StrategyGeneticist(BaseAgent):
    """Evolve and retire trading strategies based on performance.

    Full pipeline per evaluation:
      1. BacktestEngine — run strategy against historical data (G6)
      2. WalkForwardValidator — detect overfitting via rolling windows (G7)
      3. MonteCarloSimulator — compute confidence intervals (G8)
      4. FactorBenchmarker — periodic IC/IR benchmarks (G9)
    """

    AGENT_NAME = "strategy_geneticist"
    ROLE = "ANALYSIS"

    PUBLISH_STREAM = "strategy_mutations"
    SUBSCRIBE_STREAMS = ["analytics", "regime", "fills", "strategy_proposals"]

    def __init__(
        self,
        config: dict[str, Any],
        trading_mode: str = "paper",
        *,
        # Injectable dependencies for testing
        backtest_engine: BacktestEngine | None = None,
        walk_forward: WalkForwardValidator | None = None,
        monte_carlo: MonteCarloSimulator | None = None,
        factor_library: FactorLibrary | None = None,
        factor_benchmarker: FactorBenchmarker | None = None,
        strategy_factory: Any = None,
        ohlcv_provider: Any = None,
    ) -> None:
        super().__init__(config, trading_mode)
        self._config = config

        # Backtest config
        bt_cfg = config.get("backtest", {})
        self._backtest_config = BacktestConfig(
            initial_capital=bt_cfg.get("initial_capital", 100_000.0),
            position_size_pct=bt_cfg.get("position_size_pct", 0.10),
            commission_bps=bt_cfg.get("commission_bps", 10.0),
            slippage_bps=bt_cfg.get("slippage_bps", 5.0),
            risk_free_rate=bt_cfg.get("risk_free_rate", 0.04),
        )

        # Walk-forward config
        wf_cfg = config.get("walk_forward", {})
        self._walk_forward_config = WalkForwardConfig(
            n_windows=wf_cfg.get("n_windows", 5),
            train_ratio=wf_cfg.get("train_ratio", 0.70),
            overfit_threshold=wf_cfg.get("overfit_threshold", 3.0),
            backtest_config=self._backtest_config,
        )

        # Monte Carlo config
        mc_cfg = config.get("monte_carlo", {})
        self._monte_carlo_config = MonteCarloConfig(
            n_simulations=mc_cfg.get("n_simulations", 1000),
            confidence_levels=tuple(mc_cfg.get("confidence_levels", [5.0, 25.0, 50.0, 75.0, 95.0])),
        )

        # Accept injected dependencies or create later in on_initialize
        self._backtest_engine = backtest_engine
        self._walk_forward = walk_forward
        self._monte_carlo = monte_carlo or MonteCarloSimulator(self._monte_carlo_config)
        self._factor_library = factor_library
        self._factor_benchmarker = factor_benchmarker
        self._strategy_factory = strategy_factory
        self._ohlcv_provider = ohlcv_provider

        # Benchmark scheduling (G9)
        factor_cfg = config.get("factor_library", {})
        self._benchmark_interval_s: float = factor_cfg.get(
            "benchmark_interval_hours", 168
        ) * 3600
        self._last_benchmark_time: float = 0.0

        # Genome store reference (lazy)
        self._genomes: Any = None

    async def on_initialize(self) -> None:
        """Initialize backtest and analysis components."""
        # Factor library (G9)
        if self._factor_library is None:
            factor_cfg = self._config.get("factor_library", {})
            self._factor_library = FactorLibrary(
                db_path=factor_cfg.get("db_path", ":memory:")
            )
        if self._factor_benchmarker is None:
            self._factor_benchmarker = FactorBenchmarker(self._factor_library)

        # Genome store
        try:
            from src.knowledge.strategy_genomes import StrategyGenomes

            db_path = self._config.get("database", {}).get("db_path", "data/tsar.db")
            self._genomes = StrategyGenomes(db_path)
        except ImportError:
            logger.warning("StrategyGenomes not available — genome features disabled")

        # Strategy factory (for walk-forward)
        if self._strategy_factory is None:
            try:
                from src.strategy.mean_reversion import MeanReversionStrategy

                self._strategy_factory = MeanReversionStrategy
            except ImportError:
                logger.warning("MeanReversionStrategy not available")

        logger.info(
            "Strategy Geneticist initialized: factors=%s, benchmark_interval=%dh",
            len(self._factor_library.list_factors()) if self._factor_library else 0,
            int(self._benchmark_interval_s / 3600),
        )

    # ═══════════════════════════════════════════════════════════════
    # EVENT HANDLING
    # ═══════════════════════════════════════════════════════════════

    async def handle_event(self, stream: str, event: Any) -> None:
        """Handle incoming events from subscribed streams."""
        if stream == "strategy_proposals" and event.type == "tsar.strategy.proposal.v1":
            await self._evaluate_proposal(event.data)

        elif stream == "analytics" and event.type == "tsar.factor.benchmark.v1":
            logger.info("Received factor benchmark update")

    # ═══════════════════════════════════════════════════════════════
    # MAIN CYCLE
    # ═══════════════════════════════════════════════════════════════

    async def run_cycle(self) -> None:
        """Periodic strategy evaluation cycle.

        1. Run factor benchmarks if interval elapsed (G9)
        2. Evaluate active strategies via full pipeline
        """
        # G9: Periodic factor benchmarking
        now = time.monotonic()
        if now - self._last_benchmark_time >= self._benchmark_interval_s:
            self._last_benchmark_time = now
            await self._run_factor_benchmark()

        # Evaluate active strategies
        if self._genomes:
            try:
                active = self._genomes.get_active_strategies()
                for genome in active:
                    await self._evaluate_strategy(genome)
            except Exception:
                logger.exception("Error evaluating strategies")

    # ═══════════════════════════════════════════════════════════════
    # G6 + G7 + G8: FULL EVALUATION PIPELINE
    # ═══════════════════════════════════════════════════════════════

    async def evaluate_strategy(
        self,
        strategy_name: str,
        ohlcv_data: list[Any],
    ) -> StrategyEvaluation:
        """Run the full evaluation pipeline on a strategy.

        Pipeline:
          1. Backtest (G6)
          2. Walk-forward validation (G7)
          3. Monte Carlo simulation (G8)

        Args:
            strategy_name: Name/label for the strategy.
            ohlcv_data: Historical OHLCV bars for backtesting.

        Returns:
            StrategyEvaluation with all results and accept/reject decision.
        """
        eval_result = StrategyEvaluation(strategy_name=strategy_name)
        reasons = eval_result.rejection_reasons

        # Need a strategy factory for walk-forward
        if self._strategy_factory is None:
            reasons.append("No strategy factory available")
            return eval_result

        # ── Step 1: Backtest (G6) ──────────────────────────────
        logger.info("[%s] Running backtest...", strategy_name)
        try:
            strategy = self._strategy_factory()
            engine = BacktestEngine(strategy, self._backtest_config)
            bt_result = engine.run(ohlcv_data)
            eval_result.backtest_result = bt_result

            m = bt_result.metrics
            logger.info(
                "[%s] Backtest: sharpe=%.2f win_rate=%.2f max_dd=%.2f trades=%d pf=%.2f",
                strategy_name, m.sharpe_ratio, m.win_rate,
                m.max_drawdown, m.total_trades, m.profit_factor,
            )

            # Gate: minimum quality thresholds
            if m.total_trades < 5:
                reasons.append(f"Too few trades: {m.total_trades} < 5")
            if m.sharpe_ratio < 0.0:
                reasons.append(f"Negative Sharpe: {m.sharpe_ratio:.2f}")
            if m.max_drawdown > 0.30:
                reasons.append(f"Max drawdown too high: {m.max_drawdown:.1%}")

            if reasons:
                logger.info("[%s] Rejected at backtest stage: %s", strategy_name, reasons)
                return eval_result

        except Exception:
            logger.exception("[%s] Backtest failed", strategy_name)
            reasons.append("Backtest execution failed")
            return eval_result

        # ── Step 2: Walk-forward validation (G7) ───────────────
        logger.info("[%s] Running walk-forward validation...", strategy_name)
        try:
            wf_validator = WalkForwardValidator(
                strategy_factory=self._strategy_factory,
                config=self._walk_forward_config,
            )
            wf_result = wf_validator.run(ohlcv_data)
            eval_result.walk_forward_result = wf_result

            logger.info(
                "[%s] Walk-forward: overfit_score=%.2f is_overfit=%s consistency=%.2f",
                strategy_name, wf_result.overfitting_score,
                wf_result.is_overfit, wf_result.consistency_score,
            )

            if wf_result.is_overfit:
                reasons.append(
                    f"Overfitting detected: train/test Sharpe ratio = "
                    f"{wf_result.overfitting_score:.2f} > {self._walk_forward_config.overfit_threshold}"
                )
            if wf_result.consistency_score < 0.4:
                reasons.append(
                    f"Low consistency: only {wf_result.consistency_score:.0%} of windows profitable"
                )

            if reasons:
                logger.info("[%s] Rejected at walk-forward stage: %s", strategy_name, reasons)
                return eval_result

        except Exception:
            logger.exception("[%s] Walk-forward failed", strategy_name)
            reasons.append("Walk-forward validation failed")
            return eval_result

        # ── Step 3: Monte Carlo simulation (G8) ────────────────
        logger.info("[%s] Running Monte Carlo simulation...", strategy_name)
        try:
            mc_simulator = MonteCarloSimulator(self._monte_carlo_config)
            mc_result = mc_simulator.run(bt_result)
            eval_result.monte_carlo_result = mc_result

            logger.info(
                "[%s] Monte Carlo: P(profit)=%.2f P(ruin)=%.2f",
                strategy_name, mc_result.probability_of_profit,
                mc_result.probability_of_ruin,
            )

            if mc_result.probability_of_ruin > 0.10:
                reasons.append(
                    f"High ruin probability: {mc_result.probability_of_ruin:.1%} > 10%"
                )
            if mc_result.probability_of_profit < 0.50:
                reasons.append(
                    f"Low profit probability: {mc_result.probability_of_profit:.1%} < 50%"
                )

            if reasons:
                logger.info("[%s] Rejected at Monte Carlo stage: %s", strategy_name, reasons)
                return eval_result

        except Exception:
            logger.exception("[%s] Monte Carlo failed", strategy_name)
            reasons.append("Monte Carlo simulation failed")
            return eval_result

        # ── All gates passed → Accept ──────────────────────────
        eval_result.accepted = True
        logger.info("✅ [%s] Strategy PASSED all evaluation gates", strategy_name)
        return eval_result

    # ═══════════════════════════════════════════════════════════════
    # PROPOSAL EVALUATION
    # ═══════════════════════════════════════════════════════════════

    async def _evaluate_proposal(self, proposal_data: dict[str, Any]) -> None:
        """Evaluate a mutation proposal from GenomeMutator.

        Backtests the proposed changes before accepting.
        """
        proposal_id = proposal_data.get("proposal_id", "unknown")
        genome_id = proposal_data.get("target_genome_id", "unknown")
        confidence = proposal_data.get("confidence_score", 0.0)

        logger.info(
            "Evaluating mutation proposal: %s (genome=%s, confidence=%.2f)",
            proposal_id, genome_id, confidence,
        )

        # Quick confidence gate
        if confidence < 0.5:
            logger.info("Proposal %s rejected: low confidence (%.2f)", proposal_id, confidence)
            return

        # If we have OHLCV data and strategy factory, run full evaluation
        if self._ohlcv_provider and self._strategy_factory:
            try:
                ohlcv_data = await self._get_ohlcv_for_evaluation(proposal_data)
                if ohlcv_data:
                    eval_result = await self.evaluate_strategy(
                        strategy_name=f"proposal:{proposal_id}",
                        ohlcv_data=ohlcv_data,
                    )
                    if not eval_result.accepted:
                        logger.info(
                            "Proposal %s rejected by evaluation: %s",
                            proposal_id, eval_result.rejection_reasons,
                        )
                        return
            except Exception:
                logger.exception("Evaluation failed for proposal %s", proposal_id)
                return

        # Accept: update genome
        if self._genomes:
            try:
                self._genomes.update_genome(
                    genome_id,
                    entry_rules=proposal_data.get("proposed_entry_rules"),
                    exit_rules=proposal_data.get("proposed_exit_rules"),
                )
                logger.info("Proposal %s accepted → genome %s updated", proposal_id, genome_id)
            except Exception:
                logger.exception("Failed to update genome %s", genome_id)

        # Publish accepted mutation
        await self.publish_event(
            stream="strategy_mutations",
            event_type="tsar.strategy.mutated.v1",
            data={
                "genome_id": genome_id,
                "proposal_id": proposal_id,
                "confidence": confidence,
                "accepted": True,
            },
            priority=2,
        )

    # ═══════════════════════════════════════════════════════════════
    # STRATEGY EVALUATION (genome-based)
    # ═══════════════════════════════════════════════════════════════

    async def _evaluate_strategy(self, genome: Any) -> None:
        """Evaluate an active strategy genome.

        If performance degrades past retirement gates, retire the strategy.
        """
        strategy_id = getattr(genome, "strategy_id", getattr(genome, "id", "unknown"))
        name = getattr(genome, "name", strategy_id)

        logger.debug("Evaluating strategy: %s", name)

        # Check retirement gates from genome stats
        stats = getattr(genome, "stats", None) or getattr(genome, "performance", {})
        if not stats:
            return

        # Rolling Sharpe gate
        rolling_sharpe = getattr(stats, "rolling_sharpe", None) or stats.get("rolling_sharpe")
        if rolling_sharpe is not None and rolling_sharpe < 0.5:
            logger.warning(
                "⚠️ Strategy %s: rolling Sharpe %.2f < 0.5 — consider retirement",
                name, rolling_sharpe,
            )

        # Drawdown gate
        max_dd = getattr(stats, "max_drawdown", None) or stats.get("max_drawdown")
        if max_dd is not None:
            if max_dd > 0.20:
                logger.warning(
                    "🚨 Strategy %s: max drawdown %.1f%% > 20%% → RETIRE",
                    name, max_dd * 100,
                )
                if self._genomes:
                    try:
                        self._genomes.update_status(strategy_id, "retired")
                    except Exception:
                        logger.exception("Failed to retire strategy %s", strategy_id)
            elif max_dd > 0.15:
                logger.warning(
                    "⚠️ Strategy %s: max drawdown %.1f%% > 15%% → PAUSE",
                    name, max_dd * 100,
                )
                if self._genomes:
                    try:
                        self._genomes.update_status(strategy_id, "paused")
                    except Exception:
                        logger.exception("Failed to pause strategy %s", strategy_id)

    # ═══════════════════════════════════════════════════════════════
    # G9: FACTOR BENCHMARKING
    # ═══════════════════════════════════════════════════════════════

    async def _run_factor_benchmark(self) -> None:
        """Run IC/IR benchmarks on factor library (G9).

        Publishes results as tsar.factor.benchmark.v1 event.
        """
        if not self._factor_benchmarker or not self._ohlcv_provider:
            logger.debug("Factor benchmark skipped: no benchmarker or data provider")
            return

        logger.info("Running periodic factor benchmark...")
        try:
            ohlcv_data = await self._get_benchmark_data()
            if ohlcv_data is None or len(ohlcv_data) < 50:
                logger.info("Insufficient data for factor benchmark")
                return

            import pandas as pd

            ohlcv_df = pd.DataFrame([
                {"open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume}
                for b in ohlcv_data
            ])

            result = self._factor_benchmarker.run(
                ohlcv_df,
                forward_periods=[1, 5, 10],
                rolling_window=50,
            )

            logger.info(
                "Factor benchmark complete: %d factors, top=%s (IR=%.4f)",
                result.n_factors,
                result.rankings[0].factor_name if result.rankings else "none",
                result.rankings[0].ir if result.rankings else 0.0,
            )

            # Publish benchmark results
            await self.publish_event(
                stream="analytics",
                event_type="tsar.factor.benchmark.v1",
                data={
                    "n_factors": result.n_factors,
                    "n_observations": result.n_observations,
                    "forward_period": result.forward_period,
                    "rankings": [
                        {
                            "factor": s.factor_name,
                            "category": s.category,
                            "ic_mean": s.ic_mean,
                            "ir": s.ir,
                            "ic_positive_ratio": s.ic_positive_ratio,
                        }
                        for s in result.rankings[:10]  # Top 10
                    ],
                },
                priority=3,
            )

        except Exception:
            logger.exception("Factor benchmark failed")

    async def _get_benchmark_data(self) -> list[Any] | None:
        """Get OHLCV data for factor benchmarking."""
        if self._ohlcv_provider is None:
            return None
        try:
            # Try calling with default symbol/timeframe
            if hasattr(self._ohlcv_provider, "get_ohlcv"):
                return await self._ohlcv_provider.get_ohlcv("BTC/USDT", "1h", limit=500)
            elif callable(self._ohlcv_provider):
                return await self._ohlcv_provider()
        except Exception:
            logger.exception("Failed to get benchmark data")
        return None

    async def _get_ohlcv_for_evaluation(self, proposal_data: dict[str, Any]) -> list[Any] | None:
        """Get OHLCV data for evaluating a mutation proposal."""
        symbol = proposal_data.get("symbol", "BTC/USDT")
        try:
            if hasattr(self._ohlcv_provider, "get_ohlcv"):
                return await self._ohlcv_provider.get_ohlcv(symbol, "1h", limit=500)
        except Exception:
            logger.exception("Failed to get OHLCV for evaluation")
        return None
