# AI Enhancement Team — Fix Summary

**Team:** AI Enhancement
**Date:** 2026-07-30
**Issues Addressed:** C-017, H-006, H-011, H-012, M-011, M-012, M-014

---

## C-017: Hallucination Mitigation for Trading Signals ✅

**File:** `src/agents/signal_scout.py`

**Changes:**
- Added `_validate_signal()` method — a deterministic validation layer that runs on every signal before publishing
- Validates **8 statistical bounds**:
  1. Score in [0, 1]
  2. RSI in [0, 100]
  3. Entry price > 0
  4. Stop-loss on correct side of entry (BUY: below, SELL: above)
  5. Take-profit on correct side of entry
  6. Risk:Reward ratio ≥ 1.0
  7. Stop-loss/take-profit not unreasonably far (SL ≤ 20%, TP ≤ 50% of price)
  8. Entry price within 3σ of 20-bar mean (catches hallucinated price levels)
  9. ATR ≤ 15% of price (catches unreasonable volatility)
- Signals failing validation are rejected with logged reasons — never published
- Added `numpy` import for statistical computations

**Impact:** Any signal with impossible/improbable values is now caught before reaching RiskGuardian. This is the primary defense against LLM hallucinations corrupting the trading pipeline.

---

## H-006: LLM Output Evaluation Framework ✅

**File:** `src/llm/evaluation.py` (new)

**Components:**
- `LLMEvaluator` — Pulls closed trades from TradeMemory and computes quality metrics
- **Signal Accuracy Metrics:** Win rate, avg score for winners vs losers, score calibration (do higher scores predict wins?)
- **Prediction Quality Metrics:** Directional accuracy, confidence-outcome alignment (Pearson correlation)
- **Lesson Relevance Metrics:** Lessons extracted/applied, win rate improvement over time, avg rule confidence
- `EvaluationReport` with composite score (weighted: signal accuracy 50%, prediction quality 30%, lesson relevance 20%)
- Self-contained — no external dependencies beyond TradeMemory
- Exported via `src/llm/__init__.py`

**Usage:**
```python
evaluator = LLMEvaluator(trade_memory)
report = evaluator.evaluate(lookback_days=30)
# report.overall_score → 0-1 composite quality
```

---

## H-011: Sentiment Pipeline ✅

**File:** `src/agents/sentiment_agent.py` (new)

**Data Sources (all free):**
1. **CryptoPanic API** — Crypto news sentiment via vote aggregation (free tier: 20 req/min)
2. **Fear & Greed Index** — `api.alternative.me/fng/` (free, no auth)
3. **Binance Funding Rates** — `fapi.binance.com/fapi/v1/fundingRate` (free, public)

**Architecture:**
- Extends `BaseAgent` — runs on configurable timer (default 15min)
- Fetches all 3 sources concurrently via `asyncio.create_task()`
- 5-minute TTL cache to avoid API rate limits
- Composite sentiment score: Fear&Greed (40%) + News (35%) + Funding (25%)
- Funding rate inverted: high positive funding = crowded longs = contrarian bearish signal
- Publishes `tsar.sentiment.update.v1` CloudEvents on `sentiment` stream

**Composite Score Range:** -1.0 (extreme bearish) to +1.0 (extreme bullish)

**Config (in `agents.sentiment_agent`):**
- `cryptopanic_api_key`: Optional API key for higher rate limits
- `symbols`: Which crypto to track (default: ["BTC"])
- `funding_symbols`: Binance futures symbols (default: ["BTCUSDT"])
- `cache_ttl_s`: Cache TTL (default: 300s)

---

## H-012: ML/RL Signal Scoring ✅

**File:** `src/strategy/ml_scorer.py` (new)

**Model:** XGBoost (primary), LightGBM (optional), LogisticRegression (fallback)

**Features (11 total):**
- RSI, MACD histogram, Bollinger Band position, ATR %, volume ratio
- Rule-based signal score, EMA alignment, S/R proximity
- Side (buy/sell), hour of day, day of week

**Training:**
- Trains on closed trade history from TradeMemory
- Binary classification: profitable (1) vs loss (0)
- 5-fold cross-validation for accuracy estimation
- Feature importance tracking for interpretability
- Auto-retrains every 24 hours (configurable)
- Minimum 30 samples required
- Model persisted to disk via pickle

**Integration:**
- `MLScorer.score_signal(signal_metadata)` — score a SignalScout signal
- `MLScorer.predict(features)` — returns (probability, feature_contributions)
- Can be used as a signal validation layer alongside C-017

**Dependencies:** numpy (already present), scikit-learn (fallback), xgboost or lightgbm (optional)

---

## M-011: Accurate Token Counting ✅

**Files Modified:**
- `src/llm/token_counter.py` (new) — shared tiktoken-based counter
- `src/backends/python/deepseek_provider.py` — updated `count_tokens()`
- `src/backends/python/ollama_provider.py` — updated `count_tokens()`
- `src/backends/python/openai_provider.py` — updated `count_tokens()`
- `pyproject.toml` — added `tiktoken>=0.7` dependency

**Changes:**
- All three providers now use `src.llm.token_counter.count_tokens()` instead of `len(text) // 4`
- Token counter uses tiktoken with model-specific encoding selection:
  - OpenAI models → `o200k_base` or `cl100k_base`
  - DeepSeek → `cl100k_base`
  - Ollama/Qwen/Llama → `cl100k_base` (best approximation)
- Graceful fallback: if tiktoken not installed, falls back to `len(text) // 4` heuristic
- LRU cache on encoder instances for performance
- Exported via `src/llm/__init__.py`

---

## M-012: Prompt Optimization ✅

**File:** `src/llm/prompts.py`

**System Prompt Compression (3x → 1x):**
| Prompt | Before | After | Reduction |
|--------|--------|-------|-----------|
| TRADE_ANALYSIS_SYSTEM | 199 chars | 95 chars | 52% |
| STRATEGY_SYNTHESIS_SYSTEM | 181 chars | 121 chars | 33% |
| REGIME_EXPLANATION_SYSTEM | 175 chars | 105 chars | 40% |
| SHADOW_RULE_EXTRACTION_SYSTEM | 193 chars | 119 chars | 38% |

**Max Tokens Configuration (new):**
Added `MAX_TOKENS` dict and `get_max_tokens(task_type)` function with per-task limits:
- T2 tasks (short): 100-250 tokens
- T3 tasks (analysis): 300-500 tokens
- Shadow extraction (structured JSON): 800 tokens

**Impact:** ~40% reduction in system prompt token usage. Per-task max_tokens prevents wasting tokens on verbose outputs for simple tasks.

---

## M-014: LLM Post-Training Readiness ✅

**File:** `src/knowledge/shadow_extractor.py`

**Approach Documented:** LLM Rule-Extraction Pipeline (chosen over direct fine-tuning)

**Documentation covers:**
1. **Extract** — ShadowExtractor analyzes trades via LLM → discovers if-then rules
2. **Validate** — RuleValidator applies statistical significance tests
3. **Store** — Valid rules persisted with confidence scores and regime tags
4. **Apply** — Rules feed back into SignalScout as scoring factors
5. **Fine-Tune (Future)** — Structured (trade → rule) pairs as training data for model distillation

**Rationale for rule-extraction over direct fine-tuning:**
- Rules are interpretable and auditable
- Rules can be backtested before deployment
- Rules compose (multiple rules combine)
- Rules degrade gracefully (partial match still useful)
- Direct fine-tuning risks overfitting to noise

**Current limitations documented** to track path from 3/10 → 7/10.

---

## New Files Summary

| File | Issue | Purpose |
|------|-------|---------|
| `src/llm/evaluation.py` | H-006 | LLM output evaluation framework |
| `src/llm/token_counter.py` | M-011 | Shared tiktoken-based token counter |
| `src/agents/sentiment_agent.py` | H-011 | Sentiment pipeline (CryptoPanic + Fear&Greed + Funding) |
| `src/strategy/ml_scorer.py` | H-012 | XGBoost/LightGBM signal scoring |

## Modified Files Summary

| File | Issue | Change |
|------|-------|--------|
| `src/agents/signal_scout.py` | C-017 | Added `_validate_signal()` — 8-point deterministic validation |
| `src/llm/prompts.py` | M-012 | Compressed system prompts 40%, added `MAX_TOKENS` config |
| `src/llm/__init__.py` | M-011 | Export new modules |
| `src/backends/python/deepseek_provider.py` | M-011 | Use tiktoken for `count_tokens()` |
| `src/backends/python/ollama_provider.py` | M-011 | Use tiktoken for `count_tokens()` |
| `src/backends/python/openai_provider.py` | M-011 | Use tiktoken for `count_tokens()` |
| `src/knowledge/shadow_extractor.py` | M-014 | Documented rule-extraction approach |
| `src/agents/__init__.py` | H-011 | Export SentimentAgent |
| `src/strategy/__init__.py` | H-012 | Export MLScorer |
| `pyproject.toml` | M-011 | Added tiktoken dependency |

## Dependencies Added

- `tiktoken>=0.7` — Accurate token counting (optional at runtime, graceful fallback)

## Dependencies Required (not added — user choice)

- `xgboost` or `lightgbm` — For ML scorer (falls back to sklearn LogisticRegression)
- `scikit-learn` — For cross-validation and fallback model
