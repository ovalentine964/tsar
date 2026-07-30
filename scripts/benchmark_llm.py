#!/usr/bin/env python3
"""
TSAR LLM Benchmark — Compare DeepSeek-R1 vs Opus on trading tasks.

Benchmarks LLM providers on key trading-related tasks:
1. Signal narrative generation (explain a trading signal)
2. Risk scenario analysis (evaluate a risk scenario)
3. Strategy synthesis (design a strategy from market observations)
4. Trade sentiment analysis (analyze news sentiment)
5. Regime classification (classify market regime from data)

Usage:
    python scripts/benchmark_llm.py [--providers deepseek,ollama] [--runs 3]

Generates a markdown report with latency, token usage, and quality scores.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# BENCHMARK TASKS
# ═══════════════════════════════════════════════════════════════════════

BENCHMARK_TASKS = [
    {
        "name": "Signal Narrative",
        "task_type": "t2_signal_narrative",
        "prompt": (
            "Explain this trading signal in 2-3 sentences for a portfolio manager:\n"
            "Symbol: BTC/USDT\n"
            "Side: BUY\n"
            "RSI(14): 28.5 (oversold)\n"
            "Price near support at $62,400\n"
            "MACD histogram turning positive\n"
            "Volume: 1.8x 20-period average\n"
            "Score: 0.78\n"
            "Stop-loss: $61,200 | Take-profit: $65,800"
        ),
        "system_prompt": "You are a concise trading signal analyst. Be direct and factual.",
        "max_tokens": 256,
        "quality_checks": [
            ("mentions_rsi", "RSI" in "{}" or "oversold" in "{}"),
            ("mentions_support", "support" in "{}" or "$62,400" in "{}"),
            ("mentions_risk_reward", "stop" in "{}" or "risk" in "{}"),
            ("concise", len("{}".split()) < 150),
        ],
    },
    {
        "name": "Risk Scenario Analysis",
        "task_type": "t3_risk_scenario",
        "prompt": (
            "Analyze this risk scenario for a crypto portfolio:\n\n"
            "Portfolio: $10,000\n"
            "Positions:\n"
            "- BTC/USDT LONG 0.05 BTC @ $63,000 (unrealized PnL: +$150)\n"
            "- ETH/USDT LONG 1.5 ETH @ $3,400 (unrealized PnL: -$90)\n\n"
            "Market conditions:\n"
            "- BTC dominance rising (58% → 62%)\n"
            "- US 10Y yield spiking (+15bps today)\n"
            "- Fear & Greed Index: 25 (Extreme Fear)\n"
            "- Funding rates negative on major exchanges\n\n"
            "What is the primary risk and recommended action?"
        ),
        "system_prompt": "You are a risk analyst. Be specific about risks and actions.",
        "max_tokens": 512,
        "quality_checks": [
            ("mentions_btc_dominance", "dominance" in "{}" or "BTC" in "{}"),
            ("mentions_fear", "fear" in "{}" or "sentiment" in "{}"),
            ("actionable", any(w in "{}".lower() for w in ["reduce", "hedge", "close", "stop", "sell", "trim"])),
        ],
    },
    {
        "name": "Strategy Synthesis",
        "task_type": "t3_strategy_synthesis",
        "prompt": (
            "Given these market observations, suggest a trading strategy:\n\n"
            "1. BTC has been range-bound between $60,000-$65,000 for 14 days\n"
            "2. Bollinger Bands are squeezing (width at 3-month low)\n"
            "3. RSI oscillating between 35-55 (neutral)\n"
            "4. Volume declining (bearish divergence)\n"
            "5. 200-day MA at $58,500 acting as strong support\n\n"
            "Propose: strategy type, entry/exit rules, and risk parameters."
        ),
        "system_prompt": "You are a quantitative strategy designer. Be specific with numbers.",
        "max_tokens": 512,
        "quality_checks": [
            ("mentions_range", "range" in "{}" or "bound" in "{}" or "mean reversion" in "{}".lower()),
            ("has_entry_rules", any(w in "{}".lower() for w in ["entry", "buy", "sell", "enter", "when"])),
            ("has_risk_params", any(w in "{}".lower() for w in ["stop", "loss", "risk", "position size"])),
        ],
    },
    {
        "name": "Trade Sentiment",
        "task_type": "t2_news_sentiment",
        "prompt": (
            "Classify the sentiment of this news headline for BTC trading:\n\n"
            "Headline: 'BlackRock's Bitcoin ETF sees record $1.2B daily inflow "
            "as institutional demand surges'\n\n"
            "Provide: sentiment (bullish/bearish/neutral), confidence (0-1), "
            "and brief reasoning."
        ),
        "system_prompt": "You are a financial sentiment analyst. Be precise.",
        "max_tokens": 128,
        "quality_checks": [
            ("says_bullish", "bullish" in "{}".lower()),
            ("has_confidence", any(c in "{}" for c in ["0.", "1.", "%", "confidence"])),
        ],
    },
    {
        "name": "Regime Classification",
        "task_type": "t2_regime_explanation",
        "prompt": (
            "Classify the current market regime based on these indicators:\n\n"
            "- BTC 30-day realized volatility: 42% (high)\n"
            "- ADX(14): 18 (no trend)\n"
            "- Bollinger Band width: 8.2% (narrowing)\n"
            "- Correlation BTC-ETH: 0.92 (high)\n"
            "- Open Interest change: -12% (declining)\n\n"
            "What regime is this? (trending/ranging/volatile/crisis)"
        ),
        "system_prompt": "You are a market regime analyst. Be definitive.",
        "max_tokens": 128,
        "quality_checks": [
            ("identifies_regime", any(w in "{}".lower() for w in ["ranging", "range", "volatile", "consolidation", "choppy"])),
            ("mentions_volatility", "volatil" in "{}".lower()),
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class TaskResult:
    """Result for a single benchmark task run."""

    task_name: str
    provider: str
    model: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    content: str
    quality_score: float
    quality_details: dict[str, bool]
    error: str | None = None


@dataclass
class ProviderBenchmark:
    """Aggregated benchmark results for a provider."""

    provider: str
    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        valid = [t for t in self.tasks if t.error is None]
        return statistics.mean([t.latency_ms for t in valid]) if valid else 0

    @property
    def median_latency_ms(self) -> float:
        valid = [t for t in self.tasks if t.error is None]
        return statistics.median([t.latency_ms for t in valid]) if valid else 0

    @property
    def avg_quality(self) -> float:
        valid = [t for t in self.tasks if t.error is None]
        return statistics.mean([t.quality_score for t in valid]) if valid else 0

    @property
    def total_tokens(self) -> int:
        return sum(t.total_tokens for t in self.tasks if t.error is None)

    @property
    def error_count(self) -> int:
        return sum(1 for t in self.tasks if t.error is not None)

    @property
    def success_rate(self) -> float:
        if not self.tasks:
            return 0
        return (len(self.tasks) - self.error_count) / len(self.tasks)


# ═══════════════════════════════════════════════════════════════════════
# BENCHMARK RUNNER
# ═══════════════════════════════════════════════════════════════════════


async def run_benchmark(
    providers: list[str],
    runs_per_task: int = 3,
) -> list[ProviderBenchmark]:
    """Run the benchmark suite against specified providers.

    Args:
        providers: List of provider names to benchmark.
        runs_per_task: Number of runs per task per provider.

    Returns:
        List of ProviderBenchmark results.
    """
    from src.llm.router import ModelRouter

    router = ModelRouter()
    await router.initialize_all()

    results: list[ProviderBenchmark] = []

    for provider_name in providers:
        benchmark = ProviderBenchmark(provider=provider_name)
        logger.info("Benchmarking provider: %s", provider_name)

        for task in BENCHMARK_TASKS:
            for run_idx in range(runs_per_task):
                try:
                    result = await _run_single_task(
                        router, provider_name, task, run_idx
                    )
                    benchmark.tasks.append(result)

                    logger.info(
                        "  %s [run %d]: %.0fms, %d tokens, quality=%.2f%s",
                        task["name"],
                        run_idx + 1,
                        result.latency_ms,
                        result.total_tokens,
                        result.quality_score,
                        f" ERROR: {result.error}" if result.error else "",
                    )

                except Exception as exc:
                    benchmark.tasks.append(TaskResult(
                        task_name=task["name"],
                        provider=provider_name,
                        model="unknown",
                        latency_ms=0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        content="",
                        quality_score=0,
                        quality_details={},
                        error=str(exc),
                    ))

                # Brief pause between runs to avoid rate limiting
                await asyncio.sleep(0.5)

        results.append(benchmark)

    await router.shutdown_all()
    return results


async def _run_single_task(
    router: Any,
    provider_name: str,
    task: dict[str, Any],
    run_idx: int,
) -> TaskResult:
    """Run a single benchmark task against a provider.

    Routes through the model router using the task's task_type,
    but forces the specific provider/model path.
    """
    # Build the model path for this provider
    model_map = {
        "deepseek": "deepseek/deepseek-reasoner",
        "ollama": "ollama/qwen2.5:7b",
        "openai": "openai/gpt-4o-mini",
        "nvidia_nim": "nvidia_nim/deepseek-ai/deepseek-r1",
    }

    model_path = model_map.get(provider_name, f"{provider_name}/default")
    provider_obj, model_name = router._get_provider_and_model(model_path)

    start = time.monotonic()
    try:
        response = await provider_obj.generate(
            task["prompt"],
            system=task.get("system_prompt", ""),
            model=model_name,
            max_tokens=task.get("max_tokens", 256),
            temperature=0.3,
        )
        latency_ms = (time.monotonic() - start) * 1000

        content = response.content

        # Run quality checks
        quality_details = {}
        passed = 0
        for check_name, check_fn in task["quality_checks"]:
            # Replace {} with the actual content in the check
            check_str = str(check_fn).replace("{}", content)
            try:
                result = eval(check_fn) if callable(check_fn) else eval(check_str)
            except Exception:
                # Try string-based check
                try:
                    result = eval(f'"""{content}""".lower().__contains__("{check_name.split("_")[1]}")')
                except Exception:
                    result = False
            quality_details[check_name] = result
            if result:
                passed += 1

        quality_score = passed / len(task["quality_checks"]) if task["quality_checks"] else 1.0

        return TaskResult(
            task_name=task["name"],
            provider=provider_name,
            model=model_name,
            latency_ms=round(latency_ms, 1),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            content=content[:500],  # Truncate for storage
            quality_score=round(quality_score, 3),
            quality_details=quality_details,
        )

    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return TaskResult(
            task_name=task["name"],
            provider=provider_name,
            model=model_path,
            latency_ms=round(latency_ms, 1),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            content="",
            quality_score=0,
            quality_details={},
            error=str(exc),
        )


# ═══════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════


def generate_report(results: list[ProviderBenchmark]) -> str:
    """Generate a markdown benchmark report.

    Args:
        results: List of provider benchmark results.

    Returns:
        Markdown string with the full benchmark report.
    """
    lines = [
        "# TSAR LLM Benchmark Report",
        "",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        f"**Providers tested:** {len(results)}",
        f"**Tasks per provider:** {len(BENCHMARK_TASKS)}",
        "",
        "## Summary",
        "",
        "| Provider | Avg Latency | Median Latency | Avg Quality | Tokens | Success Rate |",
        "|----------|-------------|----------------|-------------|--------|-------------|",
    ]

    for bench in results:
        lines.append(
            f"| {bench.provider} "
            f"| {bench.avg_latency_ms:.0f}ms "
            f"| {bench.median_latency_ms:.0f}ms "
            f"| {bench.avg_quality:.0%} "
            f"| {bench.total_tokens:,} "
            f"| {bench.success_rate:.0%} |"
        )

    lines.append("")

    # Per-task breakdown
    lines.append("## Per-Task Results")
    lines.append("")

    for task in BENCHMARK_TASKS:
        lines.append(f"### {task['name']}")
        lines.append("")
        lines.append("| Provider | Latency | Quality | Tokens | Error |")
        lines.append("|----------|---------|---------|--------|-------|")

        for bench in results:
            task_results = [t for t in bench.tasks if t.task_name == task["name"]]
            if task_results:
                avg_latency = statistics.mean([t.latency_ms for t in task_results])
                avg_quality = statistics.mean([t.quality_score for t in task_results])
                avg_tokens = statistics.mean([t.total_tokens for t in task_results])
                errors = sum(1 for t in task_results if t.error)
                error_str = f"{errors} errors" if errors else "—"
                lines.append(
                    f"| {bench.provider} "
                    f"| {avg_latency:.0f}ms "
                    f"| {avg_quality:.0%} "
                    f"| {avg_tokens:.0f} "
                    f"| {error_str} |"
                )

        lines.append("")

        # Quality details for first successful run
        for bench in results:
            successful = [t for t in bench.tasks if t.task_name == task["name"] and t.error is None]
            if successful:
                t = successful[0]
                if t.quality_details:
                    checks = ", ".join(
                        f"{'✅' if v else '❌'} {k}" for k, v in t.quality_details.items()
                    )
                    lines.append(f"  **{bench.provider} quality checks:** {checks}")
        lines.append("")

    # Key findings
    lines.append("## Key Findings")
    lines.append("")

    if len(results) >= 2:
        fastest = min(results, key=lambda b: b.avg_latency_ms)
        best_quality = max(results, key=lambda b: b.avg_quality)
        most_reliable = max(results, key=lambda b: b.success_rate)

        lines.append(f"- **Fastest provider:** {fastest.provider} ({fastest.avg_latency_ms:.0f}ms avg)")
        lines.append(f"- **Best quality:** {best_quality.provider} ({best_quality.avg_quality:.0%} avg quality)")
        lines.append(f"- **Most reliable:** {most_reliable.provider} ({most_reliable.success_rate:.0%} success rate)")

        # Recommendation
        lines.append("")
        lines.append("### Recommendation")
        lines.append("")
        lines.append("For TSAR's trading tasks:")
        lines.append("- **Tier 2 (routine):** Use local Ollama (zero cost, fast)")
        lines.append("- **Tier 3 (complex reasoning):** Use cloud providers with Ollama fallback")
        lines.append("- **Always:** Maintain Ollama as the final fallback in the routing chain")

    lines.append("")
    lines.append("---")
    lines.append("*Report generated by TSAR LLM Benchmark Suite*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════


async def main():
    """Run the benchmark suite."""
    parser = argparse.ArgumentParser(description="TSAR LLM Benchmark")
    parser.add_argument(
        "--providers",
        default="ollama,deepseek",
        help="Comma-separated list of providers to benchmark",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Number of runs per task per provider",
    )
    parser.add_argument(
        "--output",
        default="scripts/benchmark_results.md",
        help="Output file for the benchmark report",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    providers = [p.strip() for p in args.providers.split(",")]
    logger.info("Starting benchmark: providers=%s, runs=%d", providers, args.runs)

    results = await run_benchmark(providers, runs_per_task=args.runs)

    report = generate_report(results)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)

    logger.info("Benchmark report written to %s", output_path)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
