# TradingAgents Debate Pattern → TSAR Integration

**Council:** TradingAgents Debate Implementation Council
**Date:** 2026-07-30
**Status:** Implementation Spec + Code
**Source:** `council_reviews/integration/repos/TradingAgents/`

---

## 1. Extracted Pattern: TradingAgents Debate Architecture

TradingAgents implements a **two-stage adversarial debate** pipeline:

```
Analysts (market, sentiment, news, fundamentals)
    ↓ reports
Bull Researcher ←→ Bear Researcher  (InvestDebateState, N rounds)
    ↓ debate history
Research Manager  (judge → investment_plan)
    ↓
Trader  (→ trader_investment_plan)
    ↓
Aggressive ←→ Conservative ←→ Neutral  (RiskDebateState, N rounds)
    ↓ debate history
Portfolio Manager  (judge → final_trade_decision)
```

### 1.1 InvestDebateState (Bull/Bear Signal Validation)

**Source:** `tradingagents/agents/utils/agent_states.py`

```python
class InvestDebateState(TypedDict):
    bull_history: str          # Bull's cumulative arguments
    bear_history: str          # Bear's cumulative arguments
    history: str               # Combined debate transcript
    current_response: str      # Latest argument (used as opponent's context)
    judge_decision: str        # Research Manager's final verdict
    count: int                 # Turn counter (terminates at 2 * max_debate_rounds)
```

**Routing Logic** (`conditional_logic.py`):
- `count >= 2 * max_debate_rounds` → Research Manager (judge)
- Last speaker was Bull → next is Bear
- Last speaker was Bear → next is Bull

**Key Design:** Each researcher gets ALL analyst reports + the debate history + opponent's last argument. The debate is turn-based, not parallel.

### 1.2 RiskDebateState (Three-Way Risk Assessment)

**Source:** `tradingagents/agents/utils/agent_states.py`

```python
class RiskDebateState(TypedDict):
    aggressive_history: str    # Aggressive analyst's cumulative arguments
    conservative_history: str  # Conservative analyst's cumulative arguments
    neutral_history: str       # Neutral analyst's cumulative arguments
    history: str               # Combined transcript
    latest_speaker: str        # Who spoke last (drives routing)
    current_aggressive_response: str
    current_conservative_response: str
    current_neutral_response: str
    judge_decision: str        # Portfolio Manager's final verdict
    count: int                 # Terminates at 3 * max_risk_discuss_rounds
```

**Routing Logic:**
- `count >= 3 * max_risk_discuss_rounds` → Portfolio Manager (judge)
- Last was Aggressive → next is Conservative
- Last was Conservative → next is Neutral
- Last is Neutral → next is Aggressive

**Key Design:** Three-way round-robin. Each debator sees the trader's proposal + both opponents' last arguments + all analyst reports.

### 1.3 Reflector (Post-Trade Learning)

**Source:** `tradingagents/graph/reflection.py`

```python
class Reflector:
    def reflect_on_final_decision(self, final_decision, raw_return, alpha_return, benchmark_name):
        # Produces 2-4 sentences: directional call accuracy, thesis hold/fail, one lesson
```

**Source:** `tradingagents/agents/utils/memory.py` — `TradingMemoryLog`
- Phase A: `store_decision()` — append pending entry at decision time
- Phase B: `update_with_outcome()` — replace pending tag with returns + reflection
- `get_past_context()` — inject same-ticker + cross-ticker lessons into future prompts

---

## 2. TSAR Integration Design

### 2.1 Architecture Mapping

| TradingAgents | TSAR Target | Integration Method |
|---|---|---|
| `InvestDebateState` | `trade_philosopher.py` | Add `SignalDebate` mixin |
| `RiskDebateState` | `risk_guardian.py` | Add `RiskDebateEngine` component |
| `Reflector` | `lesson_archive.py` | Add `DebateReflector` class |
| `TradingMemoryLog` | `trade_memory.py` | Extend with debate transcript storage |
| Bull/Bear researchers | Inline LLM calls in `trade_philosopher` | Debate runs as pre-trade validation |
| Risk debators | Inline LLM calls in `risk_guardian` | Debate runs as risk augmentation |
| Research Manager / Portfolio Manager | Judge functions | Structured output synthesis |

### 2.2 Key Design Decisions

1. **No LangGraph dependency.** TSAR uses async agents with CloudEvents, not LangGraph state machines. Debates are implemented as async iteration loops.
2. **Debate is optional.** The `risk_guardian` remains deterministic by default. Debate is an opt-in LLM augmentation layer that produces advisory signals, not vetoes.
3. **Debates store transcripts.** Full debate history is persisted in `trade_memory` for post-trade reflection and pattern matching.
4. **Structured output.** Debate judges produce typed Pydantic models (not free text) for downstream consumption.

---

## 3. Implementation

### 3.1 New Module: `src/agents/debate_engine.py`

Core debate engine shared by both `trade_philosopher` and `risk_guardian`:

```python
"""
Debate Engine — Multi-perspective adversarial validation.

Extracted from TradingAgents' InvestDebateState / RiskDebateState pattern.
Provides turn-based debate with configurable round counts and judge synthesis.

This is a pure utility module — no agent lifecycle, no CloudEvents.
Agents compose it into their own run_cycle() methods.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DEBATE STATE
# ═══════════════════════════════════════════════════════════════════════

class DebateVerdict(str, Enum):
    """Judge's directional verdict after debate."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class DebateTurn:
    """A single turn in a debate."""
    speaker: str
    argument: str
    turn_number: int


@dataclass
class DebateTranscript:
    """Complete record of a debate session."""
    debate_id: str
    debate_type: str  # "signal_validation" | "risk_assessment"
    turns: list[DebateTurn] = field(default_factory=list)
    judge_verdict: str = ""
    judge_rationale: str = ""
    verdict_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "debate_type": self.debate_type,
            "turns": [{"speaker": t.speaker, "argument": t.argument, "turn": t.turn_number}
                      for t in self.turns],
            "judge_verdict": self.judge_verdict,
            "judge_rationale": self.judge_rationale,
            "verdict_confidence": self.verdict_confidence,
        }

    def get_speaker_history(self, speaker: str) -> str:
        """Get cumulative arguments for a specific speaker."""
        return "\n\n".join(
            f"{t.speaker}: {t.argument}"
            for t in self.turns if t.speaker == speaker
        )

    def get_full_history(self) -> str:
        """Get full debate transcript."""
        return "\n\n".join(
            f"{t.speaker} (turn {t.turn_number}): {t.argument}"
            for t in self.turns
        )


# ═══════════════════════════════════════════════════════════════════════
# DEBATABLE AGENT PROTOCOL
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DebaterConfig:
    """Configuration for a single debate participant."""
    name: str
    role_description: str  # System prompt preamble
    focus_areas: list[str]  # Key points this debater emphasizes


@dataclass
class JudgeConfig:
    """Configuration for the debate judge."""
    name: str
    role_description: str
    verdict_schema: type  # Pydantic model for structured output


# Type aliases
LLMCallFn = Callable[[str], Awaitable[str]]  # prompt → response


# ═══════════════════════════════════════════════════════════════════════
# DEBATE ENGINE
# ═══════════════════════════════════════════════════════════════════════

class DebateEngine:
    """Runs a turn-based adversarial debate between N debaters, then
    synthesizes a judge verdict.

    Usage::

        engine = DebateEngine(
            debaters=[
                DebaterConfig("Bull Analyst", "Advocate for the trade...", ["growth", "momentum"]),
                DebaterConfig("Bear Analyst", "Advocate against the trade...", ["risks", "weaknesses"]),
            ],
            judge=JudgeConfig("Research Manager", "Synthesize the debate...", ResearchPlan),
            max_rounds=2,
            llm_call=my_llm_fn,
        )
        transcript = await engine.run_debate(context="Market report: ...")
    """

    def __init__(
        self,
        debaters: list[DebaterConfig],
        judge: JudgeConfig,
        max_rounds: int,
        llm_call: LLMCallFn,
        debate_type: str = "signal_validation",
    ):
        if len(debaters) < 2:
            raise ValueError("Debate requires at least 2 debaters")
        self.debaters = debaters
        self.judge = judge
        self.max_rounds = max_rounds
        self.llm_call = llm_call
        self.debate_type = debate_type

    async def run_debate(self, context: str, extra_kwargs: dict[str, str] | None = None) -> DebateTranscript:
        """Run the full debate: N debaters × max_rounds, then judge.

        Args:
            context: Shared context injected into every prompt (reports, data, etc.)
            extra_kwargs: Additional key-value pairs available in prompts.

        Returns:
            DebateTranscript with all turns and the judge's verdict.
        """
        import uuid
        transcript = DebateTranscript(
            debate_id=uuid.uuid4().hex[:12],
            debate_type=self.debate_type,
        )
        extra = extra_kwargs or {}

        total_turns = len(self.debaters) * self.max_rounds
        for turn_num in range(total_turns):
            debater = self.debaters[turn_num % len(self.debaters)]
            prompt = self._build_debater_prompt(debater, context, transcript, extra)
            argument = await self.llm_call(prompt)
            transcript.turns.append(DebateTurn(
                speaker=debater.name,
                argument=argument,
                turn_number=turn_num + 1,
            ))
            logger.info(
                "Debate %s: turn %d/%d by %s (%d chars)",
                transcript.debate_id, turn_num + 1, total_turns,
                debater.name, len(argument),
            )

        # Judge phase
        judge_prompt = self._build_judge_prompt(context, transcript, extra)
        judge_response = await self.llm_call(judge_prompt)
        verdict = self._parse_judge_verdict(judge_response)
        transcript.judge_verdict = verdict.get("verdict", "hold")
        transcript.judge_rationale = verdict.get("rationale", judge_response)
        transcript.verdict_confidence = verdict.get("confidence", 0.5)

        logger.info(
            "Debate %s: judge verdict=%s confidence=%.2f",
            transcript.debate_id, transcript.judge_verdict, transcript.verdict_confidence,
        )
        return transcript

    def _build_debater_prompt(
        self,
        debater: DebaterConfig,
        context: str,
        transcript: DebateTranscript,
        extra: dict[str, str],
    ) -> str:
        """Build the prompt for a debater's turn."""
        history = transcript.get_full_history()
        opponents_last = self._get_opponents_last_arguments(debater.name, transcript)

        focus_points = "\n".join(f"- {f}" for f in debater.focus_areas)
        opponents_section = ""
        if opponents_last:
            opponents_section = "\n\nOpponents' latest arguments:\n" + opponents_last

        extra_section = ""
        if extra:
            extra_section = "\n\n" + "\n".join(f"{k}: {v}" for k, v in extra.items())

        return f"""{debater.role_description}

Key areas to focus on:
{focus_points}

---CONTEXT---
{context}{extra_section}

---DEBATE HISTORY---
{history if history else "(No arguments yet — this is the opening statement.)"}{opponents_section}

Present your argument conversationally. Address your opponents' points directly. Be specific and evidence-based. Do not use markdown formatting."""

    def _get_opponents_last_arguments(self, current_speaker: str, transcript: DebateTranscript) -> str:
        """Get the most recent argument from each opponent."""
        seen: dict[str, str] = {}
        for turn in reversed(transcript.turns):
            if turn.speaker != current_speaker and turn.speaker not in seen:
                seen[turn.speaker] = f"{turn.speaker}: {turn.argument}"
        return "\n\n".join(seen.values())

    def _build_judge_prompt(
        self, context: str, transcript: DebateTranscript, extra: dict[str, str],
    ) -> str:
        """Build the prompt for the judge's synthesis."""
        history = transcript.get_full_history()
        debater_names = ", ".join(d.name for d in self.debaters)
        focus_summary = "\n".join(
            f"- {d.name}: {', '.join(d.focus_areas)}" for d in self.debaters
        )

        extra_section = ""
        if extra:
            extra_section = "\n\n" + "\n".join(f"{k}: {v}" for k, v in extra.items())

        return f"""{self.judge.role_description}

You are judging a debate between: {debater_names}

Each debater's focus areas:
{focus_summary}

---CONTEXT---
{context}{extra_section}

---FULL DEBATE TRANSCRIPT---
{history}

---

Synthesize the debate into a clear verdict. You MUST respond with a valid JSON object:
{{
  "verdict": "<one of: strong_buy, buy, hold, sell, strong_sell>",
  "rationale": "<2-4 sentences explaining which arguments carried and why>",
  "confidence": <0.0 to 1.0>,
  "key_bull_points": ["<strongest bull argument>"],
  "key_bear_points": ["<strongest bear argument>"]
}}

Do NOT include any text outside the JSON object."""

    @staticmethod
    def _parse_judge_verdict(response: str) -> dict[str, Any]:
        """Parse the judge's JSON verdict from LLM output."""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r"```(?:json)?\s*({.*?})\s*```", response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            # Fallback: extract verdict from prose
            response_lower = response.lower()
            for verdict in ("strong_buy", "strong_sell", "buy", "sell", "hold"):
                if verdict in response_lower:
                    return {"verdict": verdict, "rationale": response[:500], "confidence": 0.3}
            return {"verdict": "hold", "rationale": response[:500], "confidence": 0.2}
```

### 3.2 Integration into `trade_philosopher.py` — Signal Validation Debate

The TradePhilosopher gains a **pre-trade debate** capability. When a signal arrives, before reflecting on outcomes, it can run a Bull/Bear debate to validate the signal's thesis.

**Additions to `trade_philosopher.py`:**

```python
# ── Add to imports ──────────────────────────────────────────────
from src.agents.debate_engine import (
    DebateEngine,
    DebateTranscript,
    DebaterConfig,
    JudgeConfig,
)
import uuid

# ── Add new method to TradePhilosopher class ────────────────────

    async def run_signal_debate(
        self,
        signal_data: dict[str, Any],
        analyst_reports: dict[str, str],
    ) -> DebateTranscript:
        """Run a Bull/Bear debate to validate a trading signal.

        This is the TSAR equivalent of TradingAgents' InvestDebateState flow.
        Called before trade execution to stress-test the signal thesis.

        Args:
            signal_data: The signal being debated (symbol, side, score, reasoning).
            analyst_reports: Dict of report_name → report_text (market, sentiment, news, fundamentals).

        Returns:
            DebateTranscript with bull/bear arguments and judge verdict.
        """
        if self.llm_provider is None:
            logger.warning("Signal debate requires LLM provider, skipping")
            return DebateTranscript(
                debate_id="skipped",
                debate_type="signal_validation",
                judge_verdict="hold",
                judge_rationale="No LLM provider available",
            )

        symbol = signal_data.get("symbol", "UNKNOWN")
        side = signal_data.get("side", "buy")
        reasoning = signal_data.get("reasoning", "")

        context = f"""Signal under evaluation:
Symbol: {symbol}
Direction: {side}
Score: {signal_data.get('score', 0)}
Entry: {signal_data.get('entry_price', 0)}
Stop-Loss: {signal_data.get('stop_loss', 0)}
Take-Profit: {signal_data.get('take_profit', 0)}
Strategy: {signal_data.get('strategy', 'unknown')}
Signal Reasoning: {reasoning}

---ANALYST REPORTS---
"""
        for name, report in analyst_reports.items():
            context += f"\n{name.upper()} REPORT:\n{report}\n"

        # Wire LLM call through TSAR's provider
        async def llm_call(prompt: str) -> str:
            response = await self.llm_provider.generate(
                prompt=prompt,
                temperature=0.7,
                max_tokens=2000,
            )
            return response.text if response else ""

        engine = DebateEngine(
            debaters=[
                DebaterConfig(
                    name="Bull Analyst",
                    role_description=(
                        f"You are a Bull Analyst advocating FOR the {side} trade on {symbol}. "
                        "Build a strong evidence-based case emphasizing growth potential, "
                        "competitive advantages, and positive market indicators. "
                        "Directly counter the bear's arguments with specific data."
                    ),
                    focus_areas=[
                        "Growth potential and momentum",
                        "Technical setup strength",
                        "Positive sentiment indicators",
                        "Refutation of bear concerns",
                    ],
                ),
                DebaterConfig(
                    name="Bear Analyst",
                    role_description=(
                        f"You are a Bear Analyst arguing AGAINST the {side} trade on {symbol}. "
                        "Present risks, challenges, and negative indicators. "
                        "Directly counter the bull's arguments with specific data."
                    ),
                    focus_areas=[
                        "Risk factors and downside scenarios",
                        "Technical weakness signals",
                        "Negative sentiment or macro headwinds",
                        "Refutation of bull optimism",
                    ],
                ),
            ],
            judge=JudgeConfig(
                name="Signal Judge",
                role_description=(
                    "You are the Signal Judge. Synthesize the bull/bear debate into a "
                    "clear verdict on whether this signal should proceed to risk evaluation. "
                    "Be decisive — commit to a stance unless the evidence is genuinely balanced."
                ),
                verdict_schema=None,  # Uses JSON output, not Pydantic binding
            ),
            max_rounds=2,  # 2 rounds = 4 total turns (2 per side)
            llm_call=llm_call,
            debate_type="signal_validation",
        )

        transcript = await engine.run_debate(context=context)

        # Persist debate transcript in trade memory if available
        if self.trade_memory:
            try:
                # Store as journal entry linked to the signal
                from src.knowledge.trade_memory import TradeJournalEntry
                entry = TradeJournalEntry(
                    trade_id=signal_data.get("signal_id", ""),
                    entry_type="signal_debate",
                    content=json.dumps(transcript.to_dict(), default=str),
                    mood=transcript.judge_verdict,
                )
                self.trade_memory.insert_journal_entry(entry)
            except Exception:
                logger.debug("Failed to persist debate transcript", exc_info=True)

        # Extract lessons from debate for the lesson archive
        if self.lesson_archive and transcript.verdict_confidence > 0.6:
            try:
                from src.knowledge.lesson_archive import Lesson
                lesson = Lesson(
                    title=f"Signal debate: {symbol} {side} → {transcript.judge_verdict}",
                    lesson_type="DEBATE_INSIGHT",
                    category="signal_validation",
                    severity="insight" if transcript.judge_verdict in ("buy", "strong_buy") else "moderate",
                    description=transcript.judge_rationale,
                    content=json.dumps(transcript.to_dict(), default=str),
                    confidence=transcript.verdict_confidence,
                    tags=",".join([
                        "signal_debate",
                        symbol.lower(),
                        side,
                        transcript.judge_verdict,
                    ]),
                    discovered_by="trade_philosopher:signal_debate",
                )
                self.lesson_archive.insert_lesson(lesson)
            except Exception:
                logger.debug("Failed to persist debate lesson", exc_info=True)

        return transcript
```

### 3.3 Integration into `risk_guardian.py` — Three-Way Risk Debate

The RiskGuardian gains an **optional LLM risk debate** that runs after the deterministic checks pass. It does NOT replace the deterministic gate — it augments it with advisory intelligence.

**Additions to `risk_guardian.py`:**

```python
# ── Add to imports ──────────────────────────────────────────────
from src.agents.debate_engine import (
    DebateEngine,
    DebateTranscript,
    DebaterConfig,
    JudgeConfig,
)

# ── Add new attributes to RiskGuardian.__init__ ─────────────────

        # Risk debate (optional LLM augmentation)
        debate_config = config.get("risk", {}).get("debate", {})
        self._debate_enabled = debate_config.get("enabled", False)
        self._debate_max_rounds = debate_config.get("max_rounds", 1)
        self._llm_provider = None  # Lazy-initialized

# ── Add new method to RiskGuardian class ────────────────────────

    async def run_risk_debate(
        self,
        signal_data: dict[str, Any],
        analyst_reports: dict[str, str],
        trader_proposal: str,
    ) -> DebateTranscript:
        """Run a three-way risk debate (Aggressive / Conservative / Neutral).

        This is the TSAR equivalent of TradingAgents' RiskDebateState flow.
        Runs AFTER deterministic risk checks pass — produces advisory output
        that can influence position sizing and risk parameters.

        Args:
            signal_data: The signal being risk-assessed.
            analyst_reports: Dict of analyst report texts.
            trader_proposal: The trader's proposed action and sizing.

        Returns:
            DebateTranscript with three-way arguments and judge verdict.
        """
        if not self._debate_enabled:
            return DebateTranscript(
                debate_id="disabled",
                debate_type="risk_assessment",
                judge_verdict="hold",
                judge_rationale="Risk debate disabled in config",
            )

        if self._llm_provider is None:
            try:
                from src.llm.provider import get_llm_provider
                self._llm_provider = get_llm_provider()
            except Exception:
                logger.warning("Risk debate: LLM provider unavailable")
                return DebateTranscript(
                    debate_id="no_llm",
                    debate_type="risk_assessment",
                    judge_verdict="hold",
                    judge_rationale="LLM provider unavailable",
                )

        symbol = signal_data.get("symbol", "UNKNOWN")
        side = signal_data.get("side", "buy")

        context = f"""Trade proposal under risk evaluation:
Symbol: {symbol} | Direction: {side}
Entry: {signal_data.get('entry_price', 0)} | SL: {signal_data.get('stop_loss', 0)} | TP: {signal_data.get('take_profit', 0)}
Score: {signal_data.get('score', 0)} | Strategy: {signal_data.get('strategy', 'unknown')}

TRADER'S PROPOSAL:
{trader_proposal}

---ANALYST REPORTS---
"""
        for name, report in analyst_reports.items():
            context += f"\n{name.upper()} REPORT:\n{report}\n"

        async def llm_call(prompt: str) -> str:
            response = await self._llm_provider.generate(
                prompt=prompt,
                temperature=0.7,
                max_tokens=2000,
            )
            return response.text if response else ""

        engine = DebateEngine(
            debaters=[
                DebaterConfig(
                    name="Aggressive Analyst",
                    role_description=(
                        "You are the Aggressive Risk Analyst. Champion high-reward, high-risk "
                        "opportunities. Emphasize bold strategies, competitive advantages, and "
                        "growth potential. Challenge the other analysts' caution with data-driven "
                        "rebuttals. Focus on why the trader's proposal deserves full conviction."
                    ),
                    focus_areas=[
                        "Upside potential and growth trajectory",
                        "Competitive moats and catalysts",
                        "Why caution misses opportunity",
                        "Refutation of conservative fears",
                    ],
                ),
                DebaterConfig(
                    name="Conservative Analyst",
                    role_description=(
                        "You are the Conservative Risk Analyst. Protect assets, minimize "
                        "volatility, ensure steady growth. Critically examine high-risk elements "
                        "of the proposal. Point out threats the others overlook. Advocate for "
                        "reduced sizing or tighter stops."
                    ),
                    focus_areas=[
                        "Downside risks and tail scenarios",
                        "Position sizing concerns",
                        "Market regime fragility",
                        "Refutation of aggressive optimism",
                    ],
                ),
                DebaterConfig(
                    name="Neutral Analyst",
                    role_description=(
                        "You are the Neutral Risk Analyst. Provide a balanced perspective. "
                        "Weigh both sides, factor in broader trends and diversification. "
                        "Challenge both extremes. Advocate for a moderate, sustainable approach."
                    ),
                    focus_areas=[
                        "Risk-adjusted return optimization",
                        "Diversification and correlation",
                        "Balanced position sizing",
                        "Exposing blind spots on both sides",
                    ],
                ),
            ],
            judge=JudgeConfig(
                name="Risk Judge",
                role_description=(
                    "You are the Risk Judge. Synthesize the three-way risk debate into a "
                    "final risk assessment. Consider the deterministic risk checks already "
                    "passed. Your verdict adjusts position sizing and risk parameters — "
                    "it does NOT override the hard veto gate."
                ),
                verdict_schema=None,
            ),
            max_rounds=self._debate_max_rounds,
            llm_call=llm_call,
            debate_type="risk_assessment",
        )

        transcript = await engine.run_debate(
            context=context,
            extra_kwargs={"trader_proposal": trader_proposal},
        )

        return transcript

    def _apply_debate_to_decision(
        self,
        decision: RiskDecision,
        debate_transcript: DebateTranscript,
    ) -> RiskDecision:
        """Apply risk debate verdict to adjust position sizing.

        This does NOT change approval/veto status — it only adjusts
        the position_size multiplier based on debate consensus.
        """
        if not decision.approved or debate_transcript.debate_id in ("disabled", "no_llm", "skipped"):
            return decision

        verdict = debate_transcript.judge_verdict
        confidence = debate_transcript.verdict_confidence

        # Map verdict to position size multiplier
        multiplier_map = {
            "strong_buy": 1.2,    # Increase size
            "buy": 1.0,           # No change
            "hold": 0.75,         # Reduce size
            "sell": 0.5,          # Significantly reduce
            "strong_sell": 0.25,  # Minimal position
        }
        multiplier = multiplier_map.get(verdict, 1.0)

        # Blend with confidence: low confidence → stay closer to 1.0
        blended = 1.0 + (multiplier - 1.0) * confidence

        # Apply to position size
        adjusted_size = decision.position_size * blended

        logger.info(
            "Risk debate adjustment: verdict=%s confidence=%.2f "
            "multiplier=%.2f blended=%.2f original_size=%.6f adjusted=%.6f",
            verdict, confidence, multiplier, blended,
            decision.position_size, adjusted_size,
        )

        # Return new decision with adjusted size and debate context in warnings
        from src.interfaces.types import RiskDecision, VetoLevel
        return RiskDecision(
            signal_id=decision.signal_id,
            approved=decision.approved,
            position_size=adjusted_size,
            rejection_reasons=decision.rejection_reasons,
            warnings=decision.warnings + (
                f"RISK_DEBATE: {verdict} (confidence={confidence:.2f}, "
                f"size_multiplier={blended:.2f})",
            ),
            veto_level=decision.veto_level,
            timestamp=decision.timestamp,
        )
```

### 3.4 Integration into `lesson_archive.py` — Debate Reflection System

Add debate-specific reflection capabilities to the lesson archive:

```python
# ── Add to lesson_archive.py ────────────────────────────────────

    def record_debate_outcome(
        self,
        debate_id: str,
        debate_type: str,
        symbol: str,
        verdict: str,
        confidence: float,
        trade_outcome: str | None = None,
        pnl_impact: float | None = None,
        correct_direction: bool | None = None,
    ) -> str:
        """Record a debate outcome for post-trade reflection.

        Links debate verdicts to actual trade outcomes to measure
        debate accuracy over time.

        Args:
            debate_id: Unique debate session ID.
            debate_type: "signal_validation" or "risk_assessment".
            symbol: Trading symbol.
            verdict: Judge's verdict (buy/sell/hold/etc).
            confidence: Judge's confidence (0-1).
            trade_outcome: "win", "loss", "breakeven" (filled after trade closes).
            pnl_impact: Realized P&L if known.
            correct_direction: Whether the debate verdict matched actual outcome.

        Returns:
            Lesson ID of the created lesson.
        """
        # Determine lesson severity based on correctness
        if correct_direction is None:
            severity = "insight"  # Pending outcome
        elif correct_direction:
            severity = "insight"  # Debate was correct
        else:
            severity = "high" if abs(pnl_impact or 0) > 3 else "moderate"

        content = (
            f"Debate {debate_id} ({debate_type}) on {symbol}: "
            f"verdict={verdict}, confidence={confidence:.2f}"
        )
        if trade_outcome:
            content += f", outcome={trade_outcome}"
        if pnl_impact is not None:
            content += f", P&L={pnl_impact:+.2f}%"
        if correct_direction is not None:
            content += f", direction_correct={correct_direction}"

        lesson = Lesson(
            title=f"Debate {debate_type}: {symbol} → {verdict}",
            lesson_type="DEBATE_OUTCOME",
            category=debate_type,
            severity=severity,
            description=content,
            content=json.dumps({
                "debate_id": debate_id,
                "debate_type": debate_type,
                "symbol": symbol,
                "verdict": verdict,
                "confidence": confidence,
                "trade_outcome": trade_outcome,
                "pnl_impact": pnl_impact,
                "correct_direction": correct_direction,
            }),
            confidence=confidence,
            tags=",".join(["debate_outcome", debate_type, symbol.lower(), verdict]),
            discovered_by="lesson_archive:debate_reflection",
        )

        lesson_id = self.insert_lesson(lesson)
        return lesson_id

    def get_debate_accuracy(self, debate_type: str | None = None, since: str | None = None) -> dict[str, Any]:
        """Compute debate accuracy statistics.

        Returns:
            Dict with total_debates, correct, incorrect, pending, accuracy_rate,
            avg_confidence_correct, avg_confidence_incorrect.
        """
        clause_type = "AND category = ?" if debate_type else ""
        clause_since = "AND created_at >= ?" if since else ""
        sql = f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN content LIKE '%direction_correct=True%' THEN 1 ELSE 0 END) AS correct,
                SUM(CASE WHEN content LIKE '%direction_correct=False%' THEN 1 ELSE 0 END) AS incorrect,
                SUM(CASE WHEN content LIKE '%direction_correct=None%'
                         OR content NOT LIKE '%direction_correct=%' THEN 1 ELSE 0 END) AS pending,
                AVG(confidence) AS avg_confidence
            FROM lessons
            WHERE lesson_type = 'DEBATE_OUTCOME' AND is_archived = 0
            {clause_type} {clause_since}
        """
        params: list[Any] = []
        if debate_type:
            params.append(debate_type)
        if since:
            params.append(since)
        with self._conn() as conn:
            row = conn.execute(sql, params).fetchone()

        if not row or row["total"] == 0:
            return {"total_debates": 0, "accuracy_rate": 0.0}

        resolved = (row["correct"] or 0) + (row["incorrect"] or 0)
        accuracy = (row["correct"] or 0) / resolved if resolved > 0 else 0.0

        return {
            "total_debates": row["total"],
            "correct": row["correct"] or 0,
            "incorrect": row["incorrect"] or 0,
            "pending": row["pending"] or 0,
            "accuracy_rate": accuracy,
            "avg_confidence": row["avg_confidence"] or 0.0,
        }

    def get_best_debate_insights(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get debate lessons with highest confidence that were directionally correct.

        Useful for injecting proven debate patterns into future debates.
        """
        sql = """
            SELECT * FROM lessons
            WHERE lesson_type IN ('DEBATE_OUTCOME', 'DEBATE_INSIGHT')
                AND content LIKE '%direction_correct=True%'
                AND is_archived = 0
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]
```

### 3.5 Wiring: Past Context Injection (Reflection → Debates)

TradingAgents injects past reflections into future agent prompts via `TradingMemoryLog.get_past_context()`. TSAR achieves this through the existing `lesson_archive` + `trade_memory`:

```python
# ── Add to trade_philosopher.py ─────────────────────────────────

    async def _get_debate_context(self, symbol: str) -> str:
        """Retrieve past debate insights for prompt injection.

        Equivalent to TradingAgents' TradingMemoryLog.get_past_context().
        Returns formatted string of relevant past debates and lessons.
        """
        parts = []

        # Same-symbol debate history
        if self.lesson_archive:
            try:
                symbol_lessons = self.lesson_archive.get_lessons_for_symbol(symbol)
                debate_lessons = [l for l in symbol_lessons if "debate" in (l.category or "")]
                if debate_lessons:
                    parts.append(f"Past debate insights for {symbol}:")
                    for lesson in debate_lessons[:5]:
                        parts.append(
                            f"  [{lesson.severity}] {lesson.title}: {lesson.description}"
                        )
            except Exception:
                pass

            # Cross-symbol debate accuracy
            try:
                accuracy = self.lesson_archive.get_debate_accuracy()
                if accuracy.get("total_debates", 0) > 0:
                    parts.append(
                        f"\nDebate system accuracy: {accuracy['accuracy_rate']:.1%} "
                        f"({accuracy['correct']}/{accuracy['correct'] + accuracy['incorrect']} resolved)"
                    )
            except Exception:
                pass

        # Cross-ticker reflections from trade memory
        if self.trade_memory:
            try:
                recent_reflections = self.trade_memory.list_trades(
                    status="CLOSED", limit=10,
                )
                cross_lessons = [
                    t for t in recent_reflections
                    if t.symbol != symbol and t.reflection
                ]
                if cross_lessons:
                    parts.append("\nRecent cross-ticker lessons:")
                    for trade in cross_lessons[:3]:
                        parts.append(
                            f"  {trade.symbol} ({trade.strategy_id}): {trade.reflection[:200]}"
                        )
            except Exception:
                pass

        return "\n".join(parts) if parts else ""
```

---

## 4. Configuration Schema

Add to `config/default.yaml`:

```yaml
# ── Debate Engine Configuration ──────────────────────────────
debate:
  signal_validation:
    enabled: true
    max_rounds: 2          # 2 rounds × 2 debaters = 4 turns
    temperature: 0.7
    max_tokens_per_turn: 2000
    persist_transcripts: true
    inject_past_context: true

  risk_assessment:
    enabled: false          # Disabled by default — deterministic risk first
    max_rounds: 1           # 1 round × 3 debaters = 3 turns
    temperature: 0.7
    max_tokens_per_turn: 2000
    persist_transcripts: true
    position_size_impact: true  # Whether debate adjusts sizing

# ── Risk Guardian debate settings ────────────────────────────
risk:
  debate:
    enabled: false
    max_rounds: 1
```

---

## 5. Data Flow

### 5.1 Signal Validation Flow (TradePhilosopher)

```
Signal detected
    ↓
TradePhilosopher.run_signal_debate(signal, reports)
    ↓
DebateEngine: Bull(1) → Bear(1) → Bull(2) → Bear(2) → Judge
    ↓
DebateTranscript {verdict, rationale, confidence}
    ↓
├─ Persist transcript → trade_memory (journal entry)
├─ Extract lesson → lesson_archive (DEBATE_INSIGHT)
└─ Return verdict for orchestrator decision
```

### 5.2 Risk Assessment Flow (RiskGuardian)

```
Signal passes deterministic checks (approved)
    ↓
RiskGuardian.run_risk_debate(signal, reports, trader_proposal)
    ↓
DebateEngine: Aggressive → Conservative → Neutral → Judge
    ↓
DebateTranscript {verdict, confidence}
    ↓
RiskGuardian._apply_debate_to_decision(original_decision, transcript)
    ↓
Adjusted RiskDecision (warnings include debate verdict)
    ↓
Publish to risk_decisions stream
```

### 5.3 Post-Trade Reflection Flow (LessonArchive)

```
Trade closes (outcome known)
    ↓
TradePhilosopher reflects on trade
    ↓
If debate transcript exists for this trade:
    ↓
LessonArchive.record_debate_outcome(
    debate_id, verdict, confidence,
    trade_outcome, pnl, correct_direction
)
    ↓
Debate accuracy metrics updated
    ↓
Future debates inject past accuracy context
```

---

## 6. Key Differences from TradingAgents

| Aspect | TradingAgents | TSAR |
|---|---|---|
| **Orchestration** | LangGraph StateGraph | Async method calls + CloudEvents |
| **Debate is mandatory** | Yes, always runs | No, opt-in via config |
| **Risk debate → veto** | Portfolio Manager can change final decision | Advisory only — adjusts sizing, never overrides deterministic veto |
| **State management** | TypedDict in LangGraph state | DebateTranscript dataclass |
| **LLM binding** | LangChain LLM wrappers | TSAR LLMProvider interface |
| **Persistence** | Markdown memory log | SQLite (trade_memory + lesson_archive) |
| **Structured output** | Pydantic via LangChain with_structured_output | JSON parsing with validation |
| **Reflection timing** | Phase B (deferred, after outcome known) | Same — debate outcomes recorded post-trade |
| **Debater count** | Fixed: 2 (invest) or 3 (risk) | Configurable via DebaterConfig list |

---

## 7. Testing Strategy

### Unit Tests

```python
# tests/test_debate_engine.py

import pytest
from src.agents.debate_engine import (
    DebateEngine, DebateTranscript, DebaterConfig, JudgeConfig,
)

@pytest.fixture
def mock_llm():
    """LLM that returns predictable responses."""
    responses = {
        "Bull": "Strong growth indicators support this trade.",
        "Bear": "Significant downside risks present.",
        "Aggressive": "Full conviction, maximize position.",
        "Conservative": "Reduce sizing, protect capital.",
        "Neutral": "Balanced approach recommended.",
    }
    async def call(prompt: str) -> str:
        for key, resp in responses.items():
            if key in prompt:
                return resp
        return '{"verdict": "buy", "rationale": "Test", "confidence": 0.8}'
    return call

@pytest.mark.asyncio
async def test_two_way_debate(mock_llm):
    engine = DebateEngine(
        debaters=[
            DebaterConfig("Bull", "Advocate for", ["growth"]),
            DebaterConfig("Bear", "Advocate against", ["risks"]),
        ],
        judge=JudgeConfig("Judge", "Synthesize", None),
        max_rounds=1,
        llm_call=mock_llm,
    )
    transcript = await engine.run_debate(context="Test context")
    assert len(transcript.turns) == 2
    assert transcript.judge_verdict in ("buy", "sell", "hold")

@pytest.mark.asyncio
async def test_three_way_debate(mock_llm):
    engine = DebateEngine(
        debaters=[
            DebaterConfig("Aggressive", "Champion risk", ["upside"]),
            DebaterConfig("Conservative", "Protect capital", ["downside"]),
            DebaterConfig("Neutral", "Balance both", ["balance"]),
        ],
        judge=JudgeConfig("Judge", "Synthesize", None),
        max_rounds=1,
        llm_call=mock_llm,
    )
    transcript = await engine.run_debate(context="Test context")
    assert len(transcript.turns) == 3
    assert transcript.debate_type == "signal_validation"

@pytest.mark.asyncio
async def test_debate_transcript_serialization(mock_llm):
    engine = DebateEngine(
        debaters=[
            DebaterConfig("Bull", "Advocate for", ["growth"]),
            DebaterConfig("Bear", "Advocate against", ["risks"]),
        ],
        judge=JudgeConfig("Judge", "Synthesize", None),
        max_rounds=1,
        llm_call=mock_llm,
    )
    transcript = await engine.run_debate(context="Test")
    d = transcript.to_dict()
    assert "debate_id" in d
    assert "turns" in d
    assert len(d["turns"]) == 2

@pytest.mark.asyncio
async def test_judge_verdict_parsing():
    from src.agents.debate_engine import DebateEngine
    result = DebateEngine._parse_judge_verdict(
        '{"verdict": "strong_buy", "rationale": "Test", "confidence": 0.9}'
    )
    assert result["verdict"] == "strong_buy"
    assert result["confidence"] == 0.9

def test_debate_requires_minimum_debaters():
    with pytest.raises(ValueError, match="at least 2"):
        DebateEngine(
            debaters=[DebaterConfig("Solo", "Only one", ["test"])],
            judge=JudgeConfig("Judge", "Synthesize", None),
            max_rounds=1,
            llm_call=AsyncMock(),
        )
```

---

## 8. Summary

This integration extracts three core patterns from TradingAgents:

1. **Bull/Bear Debate (InvestDebateState)** → `DebateEngine` used by `TradePhilosopher.run_signal_debate()` for pre-trade signal validation
2. **Three-Way Risk Debate (RiskDebateState)** → `DebateEngine` used by `RiskGuardian.run_risk_debate()` for post-approval risk augmentation
3. **Reflection System (Reflector + TradingMemoryLog)** → `LessonArchive.record_debate_outcome()` + `get_debate_accuracy()` for measuring and learning from debate performance

The `DebateEngine` is a standalone, reusable component that:
- Requires no LangGraph or framework dependency
- Supports any number of debaters (not just 2 or 3)
- Persists full transcripts for post-trade analysis
- Injects historical debate accuracy into future debates
- Integrates with TSAR's existing `trade_memory` and `lesson_archive` stores
- Respects TSAR's deterministic-first architecture (debates are advisory, never override vetoes)
