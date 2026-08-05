"""TSAR — Flywheel Health Monitoring Tool.

Reports real-time health metrics for the TSAR flywheel loop:
  TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → BETTER TRADE

This tool provides a unified interface for querying flywheel status
from any agent, API endpoint, or health check system.

Usage::

    from src.tools.flywheel_health import FlywheelHealthTool

    tool = FlywheelHealthTool(flywheel_orchestrator, db_path="data/tsar.db")
    status = tool.get_status()
    print(status)

    # Or query individual subsystems
    trades = tool.count_trades_processed()
    lessons = tool.count_lessons_extracted()
    rules = tool.count_rules_validated()
    proposals = tool.count_genome_proposals()
    cycles = tool.get_cycle_info()
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agents.flywheel_orchestrator import FlywheelOrchestrator


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FlywheelStatus:
    """Complete flywheel health snapshot.

    Aggregates metrics from all flywheel pipeline stages:
    - Trades processed (input)
    - Lessons extracted (EXTRACT stage)
    - Rules validated (VALIDATE stage)
    - Genome proposals (MUTATE stage)
    - Mutations applied (EVOLVE stage)
    - Cycle count and timing
    """

    # Pipeline throughput
    trades_processed: int = 0
    lessons_extracted: int = 0
    rules_extracted: int = 0
    rules_validated: int = 0
    rules_failed: int = 0
    genome_proposals: int = 0
    mutations_applied: int = 0

    # Cycle tracking
    flywheel_cycle_count: int = 0
    last_run_time: str | None = None
    last_run_duration_s: float | None = None
    last_run_outcome: str | None = None

    # Pipeline component readiness
    shadow_extractor_ready: bool = False
    rule_validator_ready: bool = False
    genome_mutator_ready: bool = False
    strategy_geneticist_ready: bool = False
    pipeline_ready: bool = False

    # Event bus health
    event_bus_type: str = "unknown"
    dlq_count: int = 0

    # Configuration
    batch_size: int = 10
    cooldown_seconds: int = 300
    trades_since_last_flywheel: int = 0

    # Timing
    checked_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @property
    def health_score(self) -> float:
        """Compute a 0-1 health score based on pipeline readiness and throughput.

        Score components:
        - Pipeline readiness (40%): all 4 components ready
        - Throughput (30%): non-zero cycle count
        - Freshness (30%): last run within 24 hours
        """
        readiness = (
            sum(
                [
                    self.shadow_extractor_ready,
                    self.rule_validator_ready,
                    self.genome_mutator_ready,
                    self.strategy_geneticist_ready,
                ]
            )
            / 4.0
        )

        throughput = (
            min(1.0, self.flywheel_cycle_count / 10.0) if self.flywheel_cycle_count > 0 else 0.0
        )

        if self.last_run_time:
            try:
                last_dt = datetime.fromisoformat(self.last_run_time.replace("Z", "+00:00"))
                now = datetime.now(UTC)
                hours_since = (now - last_dt).total_seconds() / 3600
                freshness = max(0.0, 1.0 - (hours_since / 24.0))
            except (ValueError, TypeError):
                freshness = 0.0
        else:
            freshness = 0.0

        return round(0.4 * readiness + 0.3 * throughput + 0.3 * freshness, 3)

    @property
    def is_healthy(self) -> bool:
        """Check if the flywheel is in a healthy state."""
        return self.pipeline_ready and self.health_score >= 0.5

    @property
    def conversion_rate(self) -> float:
        """Compute the rule-to-proposal conversion rate."""
        if self.rules_extracted == 0:
            return 0.0
        return round(self.mutations_applied / self.rules_extracted, 4)


# ═══════════════════════════════════════════════════════════════════════
# FLYWHEEL HEALTH TOOL
# ═══════════════════════════════════════════════════════════════════════


class FlywheelHealthTool:
    """Query and report flyloop health metrics.

    Aggregates data from:
    - FlywheelOrchestrator (in-memory counters)
    - SQLite database (persisted validated rules, mutations)
    - EventBus (DLQ count, bus type)

    Usage::

        tool = FlywheelHealthTool(flywheel_orchestrator, db_path="data/tsar.db")
        status = tool.get_status()
        print(f"Health score: {status.health_score}")
        print(f"Cycle count: {status.flywheel_cycle_count}")
    """

    def __init__(
        self,
        flywheel_orchestrator: FlywheelOrchestrator | None = None,
        db_path: str | None = None,
    ) -> None:
        self._flywheel = flywheel_orchestrator
        self._db_path = db_path

    def set_flywheel(self, flywheel: FlywheelOrchestrator) -> None:
        """Set or update the flywheel orchestrator reference."""
        self._flywheel = flywheel

    def get_status(self) -> FlywheelStatus:
        """Get comprehensive flywheel health status.

        Returns:
            FlywheelStatus with all metrics.
        """
        status = FlywheelStatus()

        # ── In-memory metrics from FlywheelOrchestrator ─────
        if self._flywheel:
            health = self._flywheel.get_health()
            fw = health.get("flywheel", {})

            status.trades_processed = fw.get("total_trades_processed", 0)
            status.rules_extracted = fw.get("total_rules_extracted", 0)
            status.rules_validated = fw.get("total_rules_validated", 0)
            status.genome_proposals = fw.get("total_mutations_proposed", 0)
            status.mutations_applied = fw.get("total_mutations_applied", 0)
            status.flywheel_cycle_count = fw.get("runs", 0)
            status.trades_since_last_flywheel = fw.get("trades_since_flywheel", 0)
            status.batch_size = fw.get("batch_size", 10)
            status.cooldown_seconds = fw.get("cooldown_s", 300)

            # Pipeline readiness
            status.shadow_extractor_ready = self._flywheel._shadow_extractor is not None
            status.rule_validator_ready = self._flywheel._rule_validator is not None
            status.genome_mutator_ready = self._flywheel._genome_mutator is not None
            status.strategy_geneticist_ready = self._flywheel._strategy_geneticist is not None
            status.pipeline_ready = fw.get("pipeline_ready", False)

        # ── Persisted metrics from SQLite ────────────────────
        if self._db_path:
            self._enrich_from_database(status)

        # ── EventBus metrics ─────────────────────────────────
        if self._flywheel and hasattr(self._flywheel, "_event_bus"):
            bus = self._flywheel._event_bus
            status.event_bus_type = type(bus).__name__
            status.dlq_count = bus.get_dlq_count()

        # ── Lessons extracted (from trade count heuristic) ───
        # Lessons are extracted as part of rules_extracted,
        # but loss lessons are a subset. We estimate from DB.
        status.lessons_extracted = status.rules_extracted  # 1:1 mapping for now

        return status

    def _enrich_from_database(self, status: FlywheelStatus) -> None:
        """Enrich status with persisted database metrics."""
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.row_factory = sqlite3.Row

            # Count validated rules by status
            try:
                row = conn.execute(
                    "SELECT validation_status, COUNT(*) as cnt "
                    "FROM validated_rules GROUP BY validation_status"
                ).fetchall()
                for r in row:
                    if r["validation_status"] == "passed":
                        status.rules_validated = max(status.rules_validated, r["cnt"])
                    elif r["validation_status"] == "failed":
                        status.rules_failed = r["cnt"]
            except sqlite3.OperationalError:
                pass  # Table may not exist yet

            # Count mutations
            try:
                row = conn.execute("SELECT COUNT(*) as cnt FROM strategy_mutations").fetchone()
                if row:
                    status.genome_proposals = max(status.genome_proposals, row["cnt"])
            except sqlite3.OperationalError:
                pass  # Table may not exist yet

            # Last run time from most recent mutation
            try:
                row = conn.execute(
                    "SELECT created_at FROM strategy_mutations ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if row:
                    status.last_run_time = row["created_at"]
            except sqlite3.OperationalError:
                pass

            conn.close()
        except Exception:
            pass  # Database may not exist yet

    # ── Individual metric queries ────────────────────────────

    def count_trades_processed(self) -> int:
        """Get the total number of trades processed by the flywheel."""
        if self._flywheel:
            return self._flywheel._trade_count
        return 0

    def count_lessons_extracted(self) -> int:
        """Get the number of lessons extracted (rules from losers + winners)."""
        if self._flywheel:
            return self._flywheel._total_rules_extracted
        return 0

    def count_rules_validated(self) -> int:
        """Get the number of rules that passed validation."""
        if self._flywheel:
            return self._flywheel._total_rules_validated
        return 0

    def count_genome_proposals(self) -> int:
        """Get the number of genome mutation proposals generated."""
        if self._flywheel:
            return self._flywheel._total_mutations_proposed
        return 0

    def get_cycle_info(self) -> dict[str, Any]:
        """Get flywheel cycle information.

        Returns:
            Dict with cycle count, last run time, and next run estimate.
        """
        status = self.get_status()
        next_run_estimate = None

        if self._flywheel and self._flywheel._last_flywheel_run > 0:
            elapsed = time.monotonic() - self._flywheel._last_flywheel_run
            remaining = max(0, self._flywheel.COOLDOWN_SECONDS - elapsed)
            if remaining > 0:
                next_run_estimate = f"{int(remaining)}s"
            elif self._flywheel._trades_since_flywheel < self._flywheel.BATCH_SIZE:
                trades_needed = self._flywheel.BATCH_SIZE - self._flywheel._trades_since_flywheel
                next_run_estimate = f"after {trades_needed} more trades"
            else:
                next_run_estimate = "ready"

        return {
            "cycle_count": status.flywheel_cycle_count,
            "last_run_time": status.last_run_time,
            "last_run_outcome": status.last_run_outcome,
            "next_run_estimate": next_run_estimate,
            "trades_since_last_flywheel": status.trades_since_last_flywheel,
            "batch_size": status.batch_size,
            "cooldown_seconds": status.cooldown_seconds,
        }

    def get_pipeline_status(self) -> dict[str, bool]:
        """Get the readiness status of each pipeline component.

        Returns:
            Dict mapping component name to readiness boolean.
        """
        status = self.get_status()
        return {
            "shadow_extractor": status.shadow_extractor_ready,
            "rule_validator": status.rule_validator_ready,
            "genome_mutator": status.genome_mutator_ready,
            "strategy_geneticist": status.strategy_geneticist_ready,
            "pipeline_ready": status.pipeline_ready,
        }

    def get_throughput_summary(self) -> dict[str, Any]:
        """Get a throughput summary of the flywheel pipeline.

        Returns:
            Dict with stage-by-stage counts and conversion rates.
        """
        status = self.get_status()
        return {
            "trades_processed": status.trades_processed,
            "rules_extracted": status.rules_extracted,
            "rules_validated": status.rules_validated,
            "rules_failed": status.rules_failed,
            "genome_proposals": status.genome_proposals,
            "mutations_applied": status.mutations_applied,
            "conversion_rate": status.conversion_rate,
            "health_score": status.health_score,
            "is_healthy": status.is_healthy,
        }

    def to_json(self) -> str:
        """Get the full status as a JSON string."""
        return self.get_status().to_json()


# ═══════════════════════════════════════════════════════════════════════
# STANDALONE QUERY (for CLI / API endpoints)
# ═══════════════════════════════════════════════════════════════════════


def get_flywheel_health_json(
    flywheel: FlywheelOrchestrator | None = None,
    db_path: str | None = None,
) -> str:
    """Get flywheel health as JSON (convenience function for API endpoints).

    Args:
        flywheel: Optional FlywheelOrchestrator instance.
        db_path: Optional path to SQLite database.

    Returns:
        JSON string with flywheel health status.
    """
    tool = FlywheelHealthTool(flywheel, db_path)
    return tool.to_json()
