"""
Agent Loop — OpenHarness streaming tool-call cycle adapted for TSAR.

Adapts OpenHarness's core agent loop pattern:
  1. Stream LLM response with tool calls
  2. Execute tool calls (parallel where safe)
  3. Feed results back to LLM
  4. Repeat until done or max iterations

TSAR-specific additions:
  - API retry with exponential backoff
  - Parallel tool execution for independent calls
  - Token counting and cost tracking per turn
  - Real-time data priority (market data tools get fast-lane)
  - Async execution for non-blocking trading operations
  - Integration with RiskGovernor pre-trade hooks

Architecture:
  ┌─────────────────────────────────────────────────┐
  │                 Agent Loop                       │
  │                                                  │
  │  ┌──────────┐    ┌──────────┐    ┌──────────┐   │
  │  │  LLM     │───▶│  Tool    │───▶│  Result  │   │
  │  │  Stream   │    │  Execute │    │  Merge   │   │
  │  └──────────┘    └──────────┘    └──────────┘   │
  │       ▲                               │          │
  │       └───────────────────────────────┘          │
  │                                                  │
  │  ┌──────────┐    ┌──────────┐    ┌──────────┐   │
  │  │  Retry   │    │  Token   │    │  Cost    │   │
  │  │  w/Backoff│    │  Counter │    │  Tracker │   │
  │  └──────────┘    └──────────┘    └──────────┘   │
  └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.llm.token_counter import count_tokens

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════


class ToolPriority(Enum):
    """Tool execution priority for parallel scheduling."""
    CRITICAL = 0    # Risk checks, kill switch — run first, block others
    HIGH = 1        # Market data, order execution — time-sensitive
    NORMAL = 2      # Analysis, sentiment — can wait
    LOW = 3         # Logging, metrics — background


@dataclass(frozen=True)
class AgentLoopConfig:
    """Configuration for the agent loop."""

    # LLM settings
    model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.1

    # Loop control
    max_iterations: int = 15
    max_tool_calls_per_turn: int = 5
    timeout_seconds: float = 120.0

    # Retry with exponential backoff
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_multiplier: float = 2.0

    # Parallel execution
    max_parallel_tools: int = 4
    parallel_enabled: bool = True

    # Token/cost tracking
    input_cost_per_1k: float = 0.0002   # $/1K tokens (DeepSeek)
    output_cost_per_1k: float = 0.001   # $/1K tokens (DeepSeek)
    max_context_tokens: int = 128000
    compression_threshold: int = 100000  # Compress when context exceeds this

    # TSAR-specific
    trading_mode: str = "paper"
    enable_risk_hooks: bool = True
    market_data_priority: ToolPriority = ToolPriority.HIGH


@dataclass
class ToolCall:
    """Represents a single tool invocation."""
    id: str
    name: str
    arguments: dict[str, Any]
    priority: ToolPriority = ToolPriority.NORMAL
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    tokens_used: int = 0


@dataclass
class TurnMetrics:
    """Metrics for a single agent loop turn."""
    turn_number: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls_count: int = 0
    tool_duration_ms: float = 0.0
    llm_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    cost_usd: float = 0.0
    retries: int = 0


@dataclass
class LoopMetrics:
    """Aggregate metrics for an entire agent loop session."""
    turns: list[TurnMetrics] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    iterations: int = 0
    max_iterations_reached: bool = False
    errors: list[str] = field(default_factory=list)

    def add_turn(self, turn: TurnMetrics) -> None:
        self.turns.append(turn)
        self.total_input_tokens += turn.input_tokens
        self.total_output_tokens += turn.output_tokens
        self.total_cost_usd += turn.cost_usd
        self.total_tool_calls += turn.tool_calls_count

    def summary(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tool_calls": self.total_tool_calls,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "avg_turn_duration_ms": (
                round(self.total_duration_ms / max(len(self.turns), 1), 2)
            ),
            "errors": len(self.errors),
        }


# ═══════════════════════════════════════════════════════════════
# Agent Loop
# ═══════════════════════════════════════════════════════════════


class AgentLoop:
    """
    OpenHarness-style streaming tool-call agent loop adapted for TSAR.

    Core cycle:
      1. Send messages to LLM (streaming)
      2. Collect tool calls from LLM response
      3. Execute tools (parallel for independent calls)
      4. Append tool results to conversation
      5. Repeat until LLM stops calling tools or max iterations

    TSAR-specific:
      - Pre-trade risk hooks via Governance integration
      - Market data tools get priority execution
      - Token counting for cost awareness
      - Context compression for long trading sessions
    """

    def __init__(
        self,
        config: AgentLoopConfig | None = None,
        llm_provider: Any = None,
        tool_registry: Any = None,
        governance: Any = None,
        memory: Any = None,
    ) -> None:
        self._config = config or AgentLoopConfig()
        self._llm = llm_provider
        self._tools = tool_registry
        self._governance = governance
        self._memory = memory

        # Runtime state
        self._messages: list[dict[str, Any]] = []
        self._metrics = LoopMetrics()
        self._abort = False

    # ── Main Entry Point ──────────────────────────────────────────

    async def run(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str = "",
    ) -> tuple[str, LoopMetrics]:
        """Run the agent loop to completion.

        Args:
            messages: Initial conversation messages.
            system_prompt: System prompt to prepend.

        Returns:
            Tuple of (final_response_text, metrics).
        """
        start_time = time.monotonic()
        self._messages = list(messages)
        self._metrics = LoopMetrics()
        self._abort = False

        # Prepend system prompt
        if system_prompt:
            self._messages.insert(0, {"role": "system", "content": system_prompt})

        # Inject memory context if available
        if self._memory:
            context = await self._memory.get_context()
            if context:
                self._messages.insert(1, {
                    "role": "system",
                    "content": f"[Memory Context]\n{context}",
                })

        # Check context size and compress if needed
        await self._maybe_compress_context()

        # ── Main Loop ────────────────────────────────────────────
        final_response = ""
        for iteration in range(self._config.max_iterations):
            if self._abort:
                break

            self._metrics.iterations = iteration + 1
            turn = TurnMetrics(turn_number=iteration + 1)
            turn_start = time.monotonic()

            # Step 1: Call LLM with retry
            llm_start = time.monotonic()
            response, retries = await self._call_llm_with_retry()
            turn.retries = retries
            turn.llm_duration_ms = (time.monotonic() - llm_start) * 1000

            if response is None:
                self._metrics.errors.append(f"LLM call failed after {retries} retries")
                break

            # Step 2: Extract content and tool calls
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            # Count tokens
            turn.input_tokens = self._count_message_tokens()
            turn.output_tokens = count_tokens(content, model=self._config.model)
            turn.cost_usd = self._calculate_cost(turn.input_tokens, turn.output_tokens)

            # Step 3: If no tool calls, we're done
            if not tool_calls:
                final_response = content
                if content:
                    self._messages.append({"role": "assistant", "content": content})
                turn.tool_calls_count = 0
                turn.total_duration_ms = (time.monotonic() - turn_start) * 1000
                self._metrics.add_turn(turn)
                break

            # Step 4: Execute tool calls
            if content:
                self._messages.append({"role": "assistant", "content": content})

            tool_results, tool_duration = await self._execute_tool_calls(tool_calls)
            turn.tool_calls_count = len(tool_calls)
            turn.tool_duration_ms = tool_duration

            # Step 5: Append tool results to messages
            for tc, result in zip(tool_calls, tool_results):
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": self._serialize_tool_result(result),
                })

            turn.total_duration_ms = (time.monotonic() - turn_start) * 1000
            self._metrics.add_turn(turn)

            # Step 6: Compress context if approaching limit
            await self._maybe_compress_context()

        self._metrics.total_duration_ms = (time.monotonic() - start_time) * 1000

        if not final_response and self._messages:
            # Extract last assistant message
            for msg in reversed(self._messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    final_response = msg["content"]
                    break

        return final_response, self._metrics

    async def abort(self) -> None:
        """Signal the loop to stop after the current iteration."""
        self._abort = True

    # ── LLM Call with Retry ───────────────────────────────────────

    async def _call_llm_with_retry(
        self,
    ) -> tuple[dict[str, Any] | None, int]:
        """Call the LLM with exponential backoff retry.

        Returns:
            Tuple of (response_dict, retry_count).
        """
        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await self._call_llm()
                return response, attempt
            except Exception as e:
                last_error = e
                if attempt < self._config.max_retries:
                    delay = min(
                        self._config.base_delay_seconds
                        * (self._config.backoff_multiplier ** attempt),
                        self._config.max_delay_seconds,
                    )
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, self._config.max_retries + 1, e, delay,
                    )
                    await asyncio.sleep(delay)

        logger.error(
            "LLM call failed after %d attempts: %s",
            self._config.max_retries + 1, last_error,
        )
        return None, self._config.max_retries + 1

    async def _call_llm(self) -> dict[str, Any]:
        """Make a single LLM API call.

        Adapts OpenHarness's streaming pattern — collects tool calls
        from a streamed response.
        """
        if self._llm is None:
            raise RuntimeError("No LLM provider configured")

        # Build tool definitions for the LLM
        tools_def = []
        if self._tools:
            tools_def = self._tools.get_tool_definitions()

        # Call LLM (streaming)
        response = await self._llm.chat(
            messages=self._messages,
            tools=tools_def if tools_def else None,
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            stream=True,
        )

        return response

    # ── Tool Execution ────────────────────────────────────────────

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> tuple[list[Any], float]:
        """Execute tool calls, parallelizing independent ones.

        Strategy:
          - CRITICAL tools (risk checks) execute first, blocking
          - Independent tools of same priority run in parallel
          - Dependent tools wait for prerequisites

        Returns:
            Tuple of (results_list, total_duration_ms).
        """
        start = time.monotonic()
        parsed_calls = self._parse_tool_calls(tool_calls)

        # Pre-trade risk hook: if any tool is a trade execution,
        # run governance check first
        if self._config.enable_risk_hooks and self._governance:
            trade_calls = [tc for tc in parsed_calls if self._is_trade_tool(tc.name)]
            if trade_calls:
                approved = await self._governance.pre_trade_check(trade_calls)
                if not approved:
                    return [
                        {"error": "Trade blocked by governance/risk hooks"}
                        for _ in parsed_calls
                    ], (time.monotonic() - start) * 1000

        if not self._config.parallel_enabled or len(parsed_calls) <= 1:
            # Sequential execution
            results = []
            for tc in parsed_calls:
                result = await self._execute_single_tool(tc)
                results.append(result)
        else:
            # Parallel execution grouped by priority
            results = await self._execute_parallel(parsed_calls)

        # Post-trade hook
        if self._config.enable_risk_hooks and self._governance:
            await self._governance.post_trade_hook(parsed_calls, results)

        duration_ms = (time.monotonic() - start) * 1000
        return results, duration_ms

    async def _execute_parallel(
        self,
        tool_calls: list[ToolCall],
    ) -> list[Any]:
        """Execute tool calls in parallel, respecting priority and limits.

        Groups by priority, runs each group concurrently up to max_parallel_tools.
        """
        # Sort by priority
        sorted_calls = sorted(tool_calls, key=lambda tc: tc.priority.value)

        results: dict[str, Any] = {}
        current_group: list[ToolCall] = []
        current_priority = None

        async def flush_group(group: list[ToolCall]) -> None:
            """Execute a group of tools concurrently."""
            if not group:
                return
            semaphore = asyncio.Semaphore(self._config.max_parallel_tools)

            async def _run(tc: ToolCall) -> None:
                async with semaphore:
                    results[tc.id] = await self._execute_single_tool(tc)

            await asyncio.gather(*[_run(tc) for tc in group])

        for tc in sorted_calls:
            if tc.priority != current_priority and current_group:
                await flush_group(current_group)
                current_group = []
            current_priority = tc.priority
            current_group.append(tc)

        if current_group:
            await flush_group(current_group)

        # Return results in original order
        return [results.get(tc.id) for tc in tool_calls]

    async def _execute_single_tool(self, tc: ToolCall) -> Any:
        """Execute a single tool call with timing and error handling."""
        start = time.monotonic()
        try:
            if self._tools is None:
                raise RuntimeError("No tool registry configured")

            result = await self._tools.execute(tc.name, tc.arguments)
            tc.result = result
            tc.duration_ms = (time.monotonic() - start) * 1000

            logger.debug(
                "Tool %s executed in %.1fms", tc.name, tc.duration_ms,
            )
            return result

        except Exception as e:
            tc.error = str(e)
            tc.duration_ms = (time.monotonic() - start) * 1000
            logger.error("Tool %s failed: %s", tc.name, e)
            return {"error": str(e)}

    # ── Token Counting & Cost ─────────────────────────────────────

    def _count_message_tokens(self) -> int:
        """Count total tokens in current message history."""
        total = 0
        for msg in self._messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += count_tokens(content, model=self._config.model)
        return total

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for this turn."""
        input_cost = (input_tokens / 1000) * self._config.input_cost_per_1k
        output_cost = (output_tokens / 1000) * self._config.output_cost_per_1k
        return input_cost + output_cost

    # ── Context Compression ───────────────────────────────────────

    async def _maybe_compress_context(self) -> None:
        """Compress context if approaching token limit.

        Strategy: Summarize older tool results, keep recent messages intact.
        """
        if self._memory is None:
            return

        total_tokens = self._count_message_tokens()
        if total_tokens < self._config.compression_threshold:
            return

        logger.info(
            "Context compression triggered: %d tokens > %d threshold",
            total_tokens, self._config.compression_threshold,
        )

        # Compress via memory system
        compressed = await self._memory.compress_messages(self._messages)
        if compressed:
            self._messages = compressed
            new_tokens = self._count_message_tokens()
            logger.info(
                "Context compressed: %d → %d tokens (%.0f%% reduction)",
                total_tokens, new_tokens,
                (1 - new_tokens / max(total_tokens, 1)) * 100,
            )

    # ── Helpers ───────────────────────────────────────────────────

    def _parse_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse raw tool calls into ToolCall objects with priority."""
        parsed = []
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", tc.get("name", ""))
            args = tc.get("function", {}).get("arguments", tc.get("arguments", {}))
            if isinstance(args, str):
                import json
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}

            priority = self._get_tool_priority(name)
            parsed.append(ToolCall(
                id=tc.get("id", f"tc_{id(tc)}"),
                name=name,
                arguments=args,
                priority=priority,
            ))
        return parsed

    def _get_tool_priority(self, tool_name: str) -> ToolPriority:
        """Determine tool priority for execution scheduling.

        Maps TSAR tools to priorities:
          CRITICAL: Risk checks, kill switch
          HIGH: Market data, order execution
          NORMAL: Analysis, sentiment, news
          LOW: Logging, metrics, backtesting
        """
        critical_tools = {
            "risk_check", "kill_switch", "mandate_gate",
            "risk_management", "drawdown_check",
        }
        high_tools = {
            "market_data", "order_router", "execution",
            "order_flow", "position_sizer",
        }
        low_tools = {
            "monitoring", "metrics", "backtesting",
            "pnl_tracker", "flywheel_health",
        }

        if tool_name in critical_tools:
            return ToolPriority.CRITICAL
        if tool_name in high_tools:
            return ToolPriority.HIGH
        if tool_name in low_tools:
            return ToolPriority.LOW
        return ToolPriority.NORMAL

    def _is_trade_tool(self, tool_name: str) -> bool:
        """Check if a tool is a trade execution tool."""
        return tool_name in {
            "execution", "order_router", "defi_execution",
            "dex_executor", "intent_executor", "cross_chain",
        }

    def _serialize_tool_result(self, result: Any) -> str:
        """Serialize a tool result to string for the LLM."""
        if result is None:
            return "Tool returned no result."
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            import json
            return json.dumps(result, indent=2, default=str)
        return str(result)

    def get_metrics(self) -> dict[str, Any]:
        """Get current session metrics."""
        return self._metrics.summary()
