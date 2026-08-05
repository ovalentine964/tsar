"""
Prompt templates for LLM tasks.

All prompts are defined here — not scattered across agent code.
Task types reference these templates by name via :func:`get_prompt`.

Three main categories:
- **Trade analysis** — signal narratives, trade summaries, deep trade analysis
- **Strategy synthesis** — strategy mutations, evaluations, performance reviews
- **Regime explanation** — market regime interpretation, risk explanations
"""

from __future__ import annotations

import re
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
# SECURITY (H-009): Prompt Injection Sanitization
# ═══════════════════════════════════════════════════════════════════════
# Market data (symbol names, headlines, trade details) may contain
# adversarial content injected via compromised data feeds. These
# functions sanitize all external data before it enters LLM prompts.

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(previous|all|above|prior)\s+(instructions|prompts|rules)",
    r"(?i)you\s+are\s+now\s+(a|an|the)",
    r"(?i)system\s*:\s*",
    r"(?i)assistant\s*:\s*",
    r"(?i)user\s*:\s*",
    r"(?i)\bact\s+as\b",
    r"(?i)\bpretend\s+(you|to)\s+(are|be)\b",
    r"(?i)\bnew\s+instructions?\b",
    r"(?i)\bforget\s+(everything|all|previous)\b",
    r"(?i)\bdisregard\b",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
]
_INJECTION_RE = [re.compile(p) for p in _INJECTION_PATTERNS]

# Max length for any single interpolated field (prevent token flooding)
_MAX_FIELD_LENGTH = 2000


def sanitize_field(value: Any) -> str:
    """Sanitize a single value before interpolation into an LLM prompt.

    - Converts to string
    - Truncates to safe length
    - Removes control characters
    - Escapes prompt-delimiter sequences
    - Detects and flags injection attempts

    Args:
        value: Any value to sanitize.

    Returns:
        Sanitized string safe for prompt interpolation.
    """
    if value is None:
        return ""

    s = str(value)

    # Truncate to prevent token flooding
    if len(s) > _MAX_FIELD_LENGTH:
        s = s[:_MAX_FIELD_LENGTH] + "...[truncated]"

    # Remove control characters (except newline/tab)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)

    # Check for injection patterns and neutralize them
    for pattern in _INJECTION_RE:
        if pattern.search(s):
            # Replace matched injection text with [SANITIZED] marker
            s = pattern.sub("[SANITIZED]", s)

    # Escape common prompt delimiter spoofing
    s = s.replace("```", "'")
    s = s.replace("---", "–")  # em-dash to en-dash

    return s


def sanitize_dict(data: dict[str, Any]) -> dict[str, str]:
    """Sanitize all values in a dict for prompt interpolation.

    Args:
        data: Dict with string keys and arbitrary values.

    Returns:
        Dict with all values sanitized.
    """
    return {k: sanitize_field(v) for k, v in data.items()}


def validate_llm_output(text: str) -> str:
    """Validate LLM-generated output for signs of injection success.

    Checks if the LLM output contains patterns suggesting the model
    was manipulated (e.g., repeating injected instructions).

    Args:
        text: Raw LLM output.

    Returns:
        The original text if valid, or a safe fallback message.
    """
    if not text:
        return "[No output generated]"

    # Check for signs the model was hijacked
    suspicious = [
        r"(?i)^I\s+am\s+now\s+",
        r"(?i)^my\s+new\s+instructions",
        r"(?i)^system\s*:.*override",
        r"(?i)I\s+will\s+ignore\s+",
        r"(?i)as\s+an\s+unrestricted\s+AI",
    ]
    for pattern in suspicious:
        if re.search(pattern, text):
            return "[Output rejected: suspicious content detected]"

    # Truncate excessively long outputs (possible token stuffing)
    if len(text) > 5000:
        text = text[:5000] + "...[truncated]"

    return text


# ═══════════════════════════════════════════════════════════════════════
# TRADE ANALYSIS PROMPTS
# ═══════════════════════════════════════════════════════════════════════

TRADE_ANALYSIS_SYSTEM = (
    "Quant trading analyst. Be precise, factual, concise. "
    "Focus on actionable data insights. No financial advice."
)

SIGNAL_NARRATIVE = """Explain this trading signal concisely.

Signal:
- Symbol: {symbol}
- Side: {side}
- Score: {score:.2f}
- Entry: {entry_price}
- Stop Loss: {stop_loss}
- Take Profit: {take_profit}
- RSI: {rsi:.1f}
- Volume Ratio: {volume_ratio:.2f}

Provide a 2-3 sentence explanation of why this setup is interesting.
Focus on the key factors that contributed to the score."""

TRADE_SUMMARY = """Summarize this completed trade in 2-3 sentences.

Trade:
- Symbol: {symbol}
- Side: {side}
- Entry: {entry_price}
- Exit: {exit_price}
- P&L: {pnl:.2f} ({pnl_pct:.2f}%)
- Duration: {duration}
- Strategy: {strategy}
- Signal Score: {score:.2f}

Be factual. Note whether the trade was successful and any notable aspects."""

TRADE_NARRATIVE = """Analyze this completed trade deeply.

Trade:
- Symbol: {symbol}
- Side: {side}
- Entry: {entry_price}
- Exit: {exit_price}
- P&L: {pnl:.2f} ({pnl_pct:.2f}%)
- Duration: {duration}
- Strategy: {strategy}
- Signal Score: {score:.2f}
- Regime at Entry: {regime}
- Max Favorable Excursion: {mfe}
- Max Adverse Excursion: {mae}

Answer:
1. What went right?
2. What went wrong?
3. What would I do differently?
4. What lesson should be extracted?
5. Error category: timing | sizing | regime | execution | none"""

RISK_EXPLANATION = """Explain this risk management decision in 2-3 sentences.

Decision:
- Symbol: {symbol}
- Side: {side}
- Approved: {approved}
- Reason: {reason}
- Position Size: {position_size}
- Risk Amount: {risk_amount}
- Daily P&L: {daily_pnl}

Be concise and factual."""

NEWS_SENTIMENT = """Score this news for crypto trading sentiment.

Headline: {headline}
Source: {source}
Date: {date}

Respond with a JSON object:
{{"sentiment": "bullish|bearish|neutral", "score": 0.0-1.0, "reasoning": "brief explanation"}}"""

DAILY_SUMMARY = """Generate an end-of-day trading summary.

Date: {date}
Trades: {trade_count}
Win Rate: {win_rate:.1f}%
Total P&L: {total_pnl:.2f}
Best Trade: {best_trade}
Worst Trade: {worst_trade}
Active Positions: {active_positions}

Provide a 3-5 sentence summary highlighting key outcomes and observations."""


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY SYNTHESIS PROMPTS
# ═══════════════════════════════════════════════════════════════════════

STRATEGY_SYNTHESIS_SYSTEM = (
    "Quant strategy researcher. Propose specific, testable strategy modifications "
    "based on performance data. Every suggestion must be concrete and measurable."
)

STRATEGY_SYNTHESIS = """Propose a mutation to improve this trading strategy.

Current Strategy: {strategy_name}
Thesis: {thesis}
Entry Rules: {entry_rules}
Exit Rules: {exit_rules}
Performance: {performance_summary}
Known Weaknesses: {weaknesses}

Propose ONE specific, testable modification. Explain:
1. What to change
2. Why it should improve performance
3. How to test it"""

STRATEGY_EVALUATION = """Evaluate this trading strategy's performance.

Strategy: {strategy_name}
Period: {period}
Total Trades: {total_trades}
Win Rate: {win_rate:.1f}%
Sharpe Ratio: {sharpe:.2f}
Max Drawdown: {max_drawdown:.2f}%
Total P&L: {total_pnl:.2f}

Regime Performance:
{regime_performance}

Assess: Is this strategy performing well? Should it be modified, paused, or retired?"""

BIAS_DETECTION = """Analyze these recent trades for behavioral biases.

Recent Trades:
{trade_history}

Look for patterns indicating:
1. Revenge trading (increasing size after losses)
2. FOMO (entering low-quality setups)
3. Overconfidence (increasing size after wins)
4. Anchoring (holding losers too long)
5. Disposition effect (selling winners too early)

Report any detected biases with evidence."""


# ═══════════════════════════════════════════════════════════════════════
# REGIME EXPLANATION PROMPTS
# ═══════════════════════════════════════════════════════════════════════

REGIME_EXPLANATION_SYSTEM = (
    "Market regime analyst. Explain what the current environment means "
    "for position sizing, strategy selection, and risk parameters. Be specific."
)

REGIME_EXPLANATION = """Explain the current market regime in 2-3 sentences.

Regime: {regime}
Confidence: {confidence:.2f}
Indicators: {indicators}

Focus on what this means for trading decisions."""

ANOMALY_EXPLANATION = """Explain this market anomaly and its trading implications.

Anomaly Type: {anomaly_type}
Symbol: {symbol}
Details: {details}
Severity: {severity}

What does this anomaly mean? Should trading behavior change?"""

RISK_SCENARIO = """Analyze this risk scenario for the portfolio.

Scenario: {scenario}
Current Exposure: {current_exposure}
Correlation Matrix:
{correlation_matrix}

Assess:
1. Potential worst-case loss
2. Probability estimate
3. Recommended hedging actions"""


# ═══════════════════════════════════════════════════════════════════════
# PROMPT REGISTRY
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# SHADOW ACCOUNT — RULE EXTRACTION PROMPTS
# ═══════════════════════════════════════════════════════════════════════

SHADOW_RULE_EXTRACTION_SYSTEM = (
    "Quant rule analyst. Extract implicit if-then rules from completed trades "
    "that distinguish winners from losers. Rules must be specific, testable, "
    "data-backed. Never invent rules without evidence."
)

SHADOW_RULE_EXTRACTION = """Analyze these winning trades and extract implicit trading rules.

Trade Group: {group_key}

Trade Data:
{trade_data}

Your task:
1. Identify 3-5 IF-THEN rules that explain WHY the winning trades won.
2. Each rule must have specific, measurable conditions (price levels, indicators, volumes).
3. Compare winners to losers — what's DIFFERENT about the winners?
4. Rate each rule's confidence based on how many trades support it.

Respond with a JSON object:
{{
  "rules": [
    {{
      "conditions": [
        {{"type": "rsi_below", "value": 30}},
        {{"type": "volume_above_avg", "multiplier": 1.5}}
      ],
      "action": "buy",
      "confidence": 0.75,
      "regime": "oversold_reversal",
      "description": "Buy when RSI is oversold with above-average volume",
      "rationale": "7 of 10 winning trades had RSI < 30 with volume spike"
    }}
  ]
}}

Supported condition types:
- rsi_below / rsi_above (value: float)
- price_above_ma / price_below_ma (period: int)
- volume_above_avg (multiplier: float)
- close_above_high / close_below_low (lookback: int)
- price_change_above (pct: float)

Be precise. Vague rules will be rejected."""


PROMPT_TEMPLATES: dict[str, str] = {
    # Trade analysis
    "t2_signal_narrative": SIGNAL_NARRATIVE,
    "t2_trade_summary": TRADE_SUMMARY,
    "t2_risk_explanation": RISK_EXPLANATION,
    "t2_news_sentiment": NEWS_SENTIMENT,
    "t2_daily_summary": DAILY_SUMMARY,
    "t2_anomaly_explanation": ANOMALY_EXPLANATION,
    "t3_trade_narrative": TRADE_NARRATIVE,
    # Strategy synthesis
    "t3_strategy_synthesis": STRATEGY_SYNTHESIS,
    "t3_strategy_evaluation": STRATEGY_EVALUATION,
    "t3_bias_detection": BIAS_DETECTION,
    # Regime explanation
    "t2_regime_explanation": REGIME_EXPLANATION,
    "t3_risk_scenario": RISK_SCENARIO,
    # Shadow account
    "t3_shadow_rule_extraction": SHADOW_RULE_EXTRACTION,
}

# Maps task types to their system prompt category
SYSTEM_PROMPTS: dict[str, str] = {
    "t2_signal_narrative": TRADE_ANALYSIS_SYSTEM,
    "t2_trade_summary": TRADE_ANALYSIS_SYSTEM,
    "t2_risk_explanation": TRADE_ANALYSIS_SYSTEM,
    "t2_news_sentiment": TRADE_ANALYSIS_SYSTEM,
    "t2_daily_summary": TRADE_ANALYSIS_SYSTEM,
    "t2_anomaly_explanation": REGIME_EXPLANATION_SYSTEM,
    "t3_trade_narrative": TRADE_ANALYSIS_SYSTEM,
    "t3_strategy_synthesis": STRATEGY_SYNTHESIS_SYSTEM,
    "t3_strategy_evaluation": STRATEGY_SYNTHESIS_SYSTEM,
    "t3_bias_detection": TRADE_ANALYSIS_SYSTEM,
    "t2_regime_explanation": REGIME_EXPLANATION_SYSTEM,
    "t3_risk_scenario": REGIME_EXPLANATION_SYSTEM,
    "t3_shadow_rule_extraction": SHADOW_RULE_EXTRACTION_SYSTEM,
}


# Max output tokens per task type — tuned for each use case
MAX_TOKENS: dict[str, int] = {
    # T2 tasks: short, fast responses
    "t2_signal_narrative": 150,
    "t2_trade_summary": 150,
    "t2_risk_explanation": 150,
    "t2_news_sentiment": 100,
    "t2_daily_summary": 250,
    "t2_anomaly_explanation": 200,
    "t2_regime_explanation": 150,
    # T3 tasks: deeper analysis
    "t3_trade_narrative": 500,
    "t3_strategy_synthesis": 400,
    "t3_strategy_evaluation": 400,
    "t3_bias_detection": 300,
    "t3_risk_scenario": 400,
    # T3 shadow: structured JSON output
    "t3_shadow_rule_extraction": 800,
}


def get_max_tokens(task_type: str) -> int:
    """Get recommended max_tokens for a task type.

    Args:
        task_type: Task type key.

    Returns:
        Max tokens for output (default 256 if unknown).
    """
    return MAX_TOKENS.get(task_type, 256)


def get_prompt(task_type: str, **kwargs: Any) -> str:
    """Get a formatted prompt for a task type.

    SECURITY (H-009): All template variables are sanitized before
    interpolation to prevent prompt injection via market data.

    Args:
        task_type: Task type key (e.g. ``"t2_signal_narrative"``).
        **kwargs: Template variables to interpolate.

    Returns:
        Formatted prompt string.

    Raises:
        ValueError: Unknown task_type or missing template variables.
    """
    template = PROMPT_TEMPLATES.get(task_type)
    if template is None:
        raise ValueError(f"Unknown task_type: {task_type}")
    if not template:
        # Dynamic prompts (empty template) expect a 'prompt' kwarg
        return sanitize_field(kwargs.get("prompt", ""))
    try:
        # SECURITY: Sanitize all kwargs before interpolation
        safe_kwargs = sanitize_dict(kwargs)
        return template.format(**safe_kwargs)
    except KeyError as exc:
        raise ValueError(f"Missing template variable for {task_type}: {exc}") from exc


def get_system_prompt(task_type: str) -> str:
    """Get the system prompt for a task type.

    Args:
        task_type: Task type key.

    Returns:
        System prompt string, or empty string if none defined.
    """
    return SYSTEM_PROMPTS.get(task_type, "")
