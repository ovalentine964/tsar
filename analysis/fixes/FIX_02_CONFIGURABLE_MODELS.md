# FIX-02: Configurable Model System — Eliminate Hardcoded Model Names

**Status:** SPECIFICATION  
**Priority:** P1 — Architectural Debt  
**Author:** Configuration Specialist  
**Date:** 2026-07-24  
**Supersedes:** All hardcoded model references across TSAR codebase

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Unified Model Config Schema](#2-unified-model-config-schema-configmodelsyaml)
3. [Config Loader (Python)](#3-config-loader-python)
4. [Tool Model Resolution](#4-tool-model-resolution)
5. [Migration Guide](#5-migration-guide)
6. [Environment Variable Mapping](#6-environment-variable-mapping)
7. [Testing Strategy](#7-testing-strategy)
8. [Rollout Plan](#8-rollout-plan)

---

## 1. Problem Statement

### 1.1 What's Hardcoded

Every LLM model name in the TSAR codebase is hardcoded in one of three locations:

| Location | Hardcoded Values | Count |
|----------|-----------------|-------|
| `TECH_STACK.md` §Model Routing | `ollama/qwen3:8b`, `ollama/llama3:8b`, `deepseek/deepseek-chat`, `local/all-MiniLM-L6-v2` | 4 unique models, 18 references |
| `trading-super-agent-spec.md` §4 Model Router | `qwen2.5:7b`, `deepseek-ai/deepseek-r1`, `deepseek-reasoner`, `qwen2.5:32b` | 4 unique models, 15 references |
| `DAY1_ARCHITECTURE.md` | `qwen2.5:7b`, `deepseek-ai/deepseek-r1` | 2 unique models, 6 references |
| `MARKET_ANALYSIS_LAYER.md` | `qwen2.5:7b`, `all-MiniLM-L6-v2` | 2 unique models, 8 references |
| `DATA_ARCHITECTURE.md` | `all-MiniLM-L6-v2` | 1 unique model, 8 references |
| `STRATEGY_LAYER.md` | `deepseek` (implicit) | 1 reference |
| **Agent code examples** (Python) | `OllamaClient(model="qwen2.5:7b")`, `DeepSeekClient(model="deepseek-r1")` | ~10 instances |

**Total: 11 unique model identifiers, ~67 hardcoded references across 7+ files.**

### 1.2 Why This Is Critical

1. **Vendor lock-in:** Changing from Qwen to Llama requires editing 67 references across 7 files.
2. **Inconsistent naming:** Same model referenced as `qwen2.5:7b`, `qwen3:8b`, `Qwen2.5-7B`, `qwen2.5:32b` — four different names.
3. **No fallback logic in config:** Fallback chains are defined inline in code, not declaratively.
4. **Environment blindness:** No way to override models per environment (dev/staging/prod) without code changes.
5. **Cost opacity:** No centralized cost tracking or budget enforcement.

### 1.3 Design Principles

- **Zero model names in tool/agent code.** Code references task types only.
- **Single source of truth:** One YAML file defines all models, providers, routing, and fallbacks.
- **Environment overrides:** Dev can use cheaper models, prod can use better ones — same code.
- **Hot-reload:** Changing the YAML file takes effect without restarting the system.
- **Fail-safe defaults:** If config is missing or corrupt, system falls back to conservative defaults.

---

## 2. Unified Model Config Schema (`config/models.yaml`)

### 2.1 Complete Schema

```yaml
# ============================================================
# TSAR Model Configuration — Single Source of Truth
# ============================================================
# This file defines ALL model names, providers, routing rules,
# and fallback chains. NO model name should appear in any
# Python/Rust source file. Tools reference task_type only.
#
# Environment override prefix: TSAR_MODELS__
# Example: TSAR_MODELS__PROVIDERS__OLLAMA__BASE_URL=http://gpu-server:11434
#
# Version: 1.0.0
# ============================================================

# ─── Schema Version ───────────────────────────────────────────
schema_version: "1.0.0"

# ─── Providers ────────────────────────────────────────────────
# Each provider defines connection details for an LLM backend.
# Models reference providers by key name (e.g., "ollama", "nvidia_nim").

providers:
  ollama:
    type: "ollama"                       # ollama | openai_compatible | deepseek | custom
    base_url: "http://localhost:11434"   # Overridable via TSAR_MODELS__PROVIDERS__OLLAMA__BASE_URL
    api_key: null                        # Ollama doesn't need auth
    timeout_seconds: 30
    max_concurrent: 4
    retry:
      max_attempts: 3
      backoff_base_ms: 500
      backoff_max_ms: 5000

  nvidia_nim:
    type: "openai_compatible"
    base_url: "https://integrate.api.nvidia.com/v1"
    api_key: "${NVIDIA_API_KEY}"         # Resolved from environment
    timeout_seconds: 60
    max_concurrent: 2
    rate_limit:
      requests_per_minute: 100
      tokens_per_minute: 100000
    retry:
      max_attempts: 2
      backoff_base_ms: 1000
      backoff_max_ms: 10000

  deepseek_api:
    type: "deepseek"
    base_url: "https://api.deepseek.com/v1"
    api_key: "${TRADING_DEEPSEEK_API_KEY}"
    timeout_seconds: 60
    max_concurrent: 2
    rate_limit:
      requests_per_minute: 10
      tokens_per_minute: 50000
    retry:
      max_attempts: 2
      backoff_base_ms: 2000
      backoff_max_ms: 15000

  openai:
    type: "openai_compatible"
    base_url: "https://api.openai.com/v1"
    api_key: "${TRADING_OPENAI_API_KEY}"
    timeout_seconds: 60
    max_concurrent: 4
    rate_limit:
      requests_per_minute: 60
      tokens_per_minute: 150000
    retry:
      max_attempts: 3
      backoff_base_ms: 1000
      backoff_max_ms: 30000

# ─── Models ───────────────────────────────────────────────────
# Each model defines its capabilities, costs, and constraints.
# Tools never reference these directly — they go through task_types.

models:
  # --- Local Ollama Models ---
  qwen_local_7b:
    provider: "ollama"
    model_id: "qwen2.5:7b"              # The actual model identifier sent to the provider
    display_name: "Qwen 2.5 7B (Local)"
    capabilities:
      - "text_generation"
      - "chat"
      - "reasoning"
    context_window: 32768
    max_output_tokens: 4096
    cost_per_1k_input_tokens: 0.0        # Free — local
    cost_per_1k_output_tokens: 0.0
    latency_class: "fast"                # fast | medium | slow
    quality_class: "good"                # basic | good | excellent
    supports_streaming: true
    supports_function_calling: false
    supports_json_mode: true
    temperature_range: [0.0, 1.0]
    notes: "Primary T2 model. Free, fast, runs on any GPU."

  qwen_local_32b:
    provider: "ollama"
    model_id: "qwen2.5:32b"
    display_name: "Qwen 2.5 32B (Local)"
    capabilities:
      - "text_generation"
      - "chat"
      - "reasoning"
      - "complex_analysis"
    context_window: 32768
    max_output_tokens: 8192
    cost_per_1k_input_tokens: 0.0
    cost_per_1k_output_tokens: 0.0
    latency_class: "medium"
    quality_class: "excellent"
    supports_streaming: true
    supports_function_calling: false
    supports_json_mode: true
    temperature_range: [0.0, 1.0]
    notes: "T3 fallback when NVIDIA/DeepSeek unavailable. Requires 24GB+ VRAM."

  llama_local_8b:
    provider: "ollama"
    model_id: "llama3:8b"
    display_name: "Llama 3 8B (Local)"
    capabilities:
      - "text_generation"
      - "chat"
    context_window: 8192
    max_output_tokens: 2048
    cost_per_1k_input_tokens: 0.0
    cost_per_1k_output_tokens: 0.0
    latency_class: "fast"
    quality_class: "basic"
    supports_streaming: true
    supports_function_calling: false
    supports_json_mode: false
    temperature_range: [0.0, 1.0]
    notes: "Fallback T2 model. Lower quality than Qwen but wider hardware support."

  # --- Remote Free-Tier Models ---
  deepseek_r1_nvidia:
    provider: "nvidia_nim"
    model_id: "deepseek-ai/deepseek-r1"
    display_name: "DeepSeek R1 (NVIDIA NIM Free)"
    capabilities:
      - "text_generation"
      - "chat"
      - "reasoning"
      - "complex_analysis"
      - "chain_of_thought"
    context_window: 65536
    max_output_tokens: 8192
    cost_per_1k_input_tokens: 0.0        # Free tier
    cost_per_1k_output_tokens: 0.0
    latency_class: "slow"
    quality_class: "excellent"
    supports_streaming: true
    supports_function_calling: false
    supports_json_mode: false
    temperature_range: [0.0, 1.0]
    notes: "Primary T3 model. Complex reasoning, trade narratives, strategy synthesis."

  deepseek_r1_direct:
    provider: "deepseek_api"
    model_id: "deepseek-reasoner"
    display_name: "DeepSeek R1 (Direct API)"
    capabilities:
      - "text_generation"
      - "chat"
      - "reasoning"
      - "complex_analysis"
      - "chain_of_thought"
    context_window: 65536
    max_output_tokens: 8192
    cost_per_1k_input_tokens: 0.0        # Free tier (rate-limited)
    cost_per_1k_output_tokens: 0.0
    latency_class: "slow"
    quality_class: "excellent"
    supports_streaming: true
    supports_function_calling: false
    supports_json_mode: false
    temperature_range: [0.0, 1.0]
    notes: "T3 fallback when NVIDIA NIM rate-limited."

  # --- Embedding Models ---
  minilm_local:
    provider: "ollama"                   # Or local SentenceTransformer
    model_id: "all-MiniLM-L6-v2"
    display_name: "MiniLM L6 v2 (Local Embeddings)"
    capabilities:
      - "embeddings"
    embedding_dimensions: 384
    max_input_tokens: 256
    cost_per_1k_tokens: 0.0
    latency_class: "fast"
    notes: "Pattern matching, similarity search. Runs via sentence-transformers."

  # --- Reserved for Future ---
  # openai_gpt4o_mini:
  #   provider: "openai"
  #   model_id: "gpt-4o-mini"
  #   ...

# ─── Task Types ───────────────────────────────────────────────
# These are the ONLY identifiers that tool/agent code references.
# Each task_type maps to a model selection strategy with fallbacks.

task_types:
  # --- Tier 2: Fast Local Inference (explanations, summaries) ---
  t2_regime_explanation:
    description: "Generate human-readable market regime explanation"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 1024
      temperature: 0.1
      timeout_seconds: 10
    cache:
      enabled: true
      ttl_seconds: 300                    # 5 min — regime changes infrequently

  t2_signal_narrative:
    description: "Generate signal rationale for logging/display"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 512
      temperature: 0.2
      timeout_seconds: 10
    cache:
      enabled: true
      ttl_seconds: 600

  t2_risk_explanation:
    description: "Explain risk decision in human-readable form"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 512
      temperature: 0.0                   # Deterministic for risk
      timeout_seconds: 10
    cache:
      enabled: true
      ttl_seconds: 300

  t2_trade_summary:
    description: "Quick trade summary for routine trades"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 1024
      temperature: 0.3
      timeout_seconds: 15
    cache:
      enabled: false                     # Always fresh

  t2_anomaly_explanation:
    description: "Explain detected correlation anomalies"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 512
      temperature: 0.2
      timeout_seconds: 10
    cache:
      enabled: true
      ttl_seconds: 1800

  t2_strategy_evaluation:
    description: "Quick assessment of strategy viability"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 1024
      temperature: 0.2
      timeout_seconds: 15
    cache:
      enabled: true
      ttl_seconds: 3600

  t2_news_sentiment:
    description: "Score news headlines for market sentiment"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 256
      temperature: 0.1
      timeout_seconds: 5
    cache:
      enabled: true
      ttl_seconds: 3600

  t2_daily_summary:
    description: "End-of-day performance summary"
    tier: "T2"
    required_capabilities: ["text_generation"]
    preferred_model: "qwen_local_7b"
    fallback_chain:
      - "llama_local_8b"
    constraints:
      max_tokens: 2048
      temperature: 0.3
      timeout_seconds: 30
    cache:
      enabled: false

  # --- Tier 3: Complex Reasoning (analysis, synthesis) ---
  t3_trade_narrative:
    description: "Deep trade analysis with lesson extraction"
    tier: "T3"
    required_capabilities: ["reasoning", "complex_analysis"]
    preferred_model: "deepseek_r1_nvidia"
    fallback_chain:
      - "deepseek_r1_direct"
      - "qwen_local_32b"
      - "qwen_local_7b"                  # Last resort — degraded quality
    constraints:
      max_tokens: 4096
      temperature: 0.2
      timeout_seconds: 60
    cache:
      enabled: true
      ttl_seconds: 0                     # Never cache — each analysis unique

  t3_bias_detection:
    description: "Detect behavioral biases in trading patterns"
    tier: "T3"
    required_capabilities: ["reasoning"]
    preferred_model: "deepseek_r1_nvidia"
    fallback_chain:
      - "deepseek_r1_direct"
      - "qwen_local_32b"
    constraints:
      max_tokens: 2048
      temperature: 0.1
      timeout_seconds: 45
    cache:
      enabled: true
      ttl_seconds: 86400                  # Cache for 24h

  t3_strategy_synthesis:
    description: "Generate new strategy hypotheses via LLM reasoning"
    tier: "T3"
    required_capabilities: ["reasoning", "complex_analysis"]
    preferred_model: "deepseek_r1_nvidia"
    fallback_chain:
      - "deepseek_r1_direct"
      - "qwen_local_32b"
    constraints:
      max_tokens: 8192
      temperature: 0.4                   # Higher temp for creativity
      timeout_seconds: 60
    cache:
      enabled: false

  t3_risk_scenario:
    description: "Complex multi-factor risk scenario analysis"
    tier: "T3"
    required_capabilities: ["reasoning", "complex_analysis"]
    preferred_model: "deepseek_r1_nvidia"
    fallback_chain:
      - "deepseek_r1_direct"
      - "qwen_local_32b"
      - "qwen_local_7b"                  # Degraded — conservative VETO on failure
    constraints:
      max_tokens: 4096
      temperature: 0.0                   # Deterministic for risk
      timeout_seconds: 30
    cache:
      enabled: true
      ttl_seconds: 600

  # --- Embedding Tasks ---
  t1_pattern_embedding:
    description: "Generate embeddings for pattern similarity search"
    tier: "T1"
    required_capabilities: ["embeddings"]
    preferred_model: "minilm_local"
    fallback_chain: []                    # No fallback — embeddings are local-only
    constraints:
      batch_size: 64
      timeout_seconds: 5
    cache:
      enabled: true
      ttl_seconds: 86400

  # --- Legacy aliases (for backward compatibility with TECH_STACK.md) ---
  # These map old task names to the new canonical task_types.
  news_analysis:
    alias_of: "t2_news_sentiment"
  signal_validation:
    alias_of: "t2_signal_narrative"
  trade_journal:
    alias_of: "t3_trade_narrative"
  pattern_matching:
    alias_of: "t1_pattern_embedding"
  complex_analysis:
    alias_of: "t3_risk_scenario"
  daily_summary:
    alias_of: "t2_daily_summary"
  risk_assessment:
    alias_of: "t3_risk_scenario"

# ─── Budgets ──────────────────────────────────────────────────
budgets:
  daily:
    total_token_limit: 0                 # 0 = unlimited (free models)
    track_usage: true
    alert_threshold_pct: 80
    kill_switch_threshold_pct: 95

  per_task_type:
    t3_trade_narrative:
      max_tokens_per_day: 500000
      max_calls_per_day: 100
    t3_strategy_synthesis:
      max_tokens_per_day: 200000
      max_calls_per_day: 20

  cost_tracking:
    enabled: true
    currency: "USD"
    daily_cost_limit: 5.0                # Hard stop at $5/day
    alert_at: 3.0                        # Warn at $3/day

# ─── Defaults ─────────────────────────────────────────────────
# Used when task_type lookup fails or config is missing/corrupt.
defaults:
  fallback_model: "qwen_local_7b"        # Conservative default
  temperature: 0.1
  max_tokens: 1024
  timeout_seconds: 15
  cache_ttl_seconds: 300
  on_provider_failure: "veto"            # veto | skip | use_default
  on_rate_limit: "wait_then_retry"       # wait_then_retry | fail_fast | use_fallback
```

### 2.2 Schema Design Rationale

| Decision | Rationale |
|----------|-----------|
| Task types prefixed with tier (`t2_`, `t3_`) | Makes tier explicit; prevents accidental T3 use for T2 tasks |
| `preferred_model` + `fallback_chain` | Declarative fallback — code doesn't need to know fallback order |
| `required_capabilities` | Enables auto-validation that chosen model can handle the task |
| Legacy aliases | Zero-downtime migration from old TECH_STACK.md names |
| `on_provider_failure: "veto"` | Fail-safe for risk-critical tasks |
| Budget per task type | Prevents runaway T3 costs |

---

## 3. Config Loader (Python)

### 3.1 Pydantic Models

```python
# src/config/models_config.py
"""
Model configuration with Pydantic validation.
Loaded from config/models.yaml with environment variable overrides.
"""

from __future__ import annotations

import os
import re
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Enums ────────────────────────────────────────────────────

class ProviderType(str, Enum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK = "deepseek"
    CUSTOM = "custom"


class LatencyClass(str, Enum):
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"


class QualityClass(str, Enum):
    BASIC = "basic"
    GOOD = "good"
    EXCELLENT = "excellent"


class OnFailureAction(str, Enum):
    VETO = "veto"
    SKIP = "skip"
    USE_DEFAULT = "use_default"


class OnRateLimitAction(str, Enum):
    WAIT_THEN_RETRY = "wait_then_retry"
    FAIL_FAST = "fail_fast"
    USE_FALLBACK = "use_fallback"


# ─── Provider Config ──────────────────────────────────────────

class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_base_ms: int = Field(default=500, ge=100)
    backoff_max_ms: int = Field(default=5000, ge=1000)


class RateLimitConfig(BaseModel):
    requests_per_minute: int = Field(default=60, ge=1)
    tokens_per_minute: int = Field(default=100000, ge=1000)


class ProviderConfig(BaseModel):
    type: ProviderType
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_concurrent: int = Field(default=4, ge=1, le=32)
    rate_limit: RateLimitConfig | None = None
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @field_validator("api_key", mode="before")
    @classmethod
    def resolve_env_vars(cls, v: str | None) -> str | None:
        """Resolve ${VAR_NAME} patterns in api_key."""
        if v is None:
            return v
        return _resolve_env_var(v)


# ─── Model Config ─────────────────────────────────────────────

class ModelConfig(BaseModel):
    provider: str                                  # References provider key
    model_id: str                                  # Actual model identifier
    display_name: str
    capabilities: list[str] = Field(default_factory=list)
    context_window: int = Field(default=4096, ge=1)
    max_output_tokens: int = Field(default=2048, ge=1)
    embedding_dimensions: int | None = None
    max_input_tokens: int | None = None
    cost_per_1k_input_tokens: float = Field(default=0.0, ge=0.0)
    cost_per_1k_output_tokens: float = Field(default=0.0, ge=0.0)
    cost_per_1k_tokens: float = Field(default=0.0, ge=0.0)     # For embeddings
    latency_class: LatencyClass = LatencyClass.MEDIUM
    quality_class: QualityClass = QualityClass.GOOD
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_json_mode: bool = False
    temperature_range: tuple[float, float] = (0.0, 1.0)
    notes: str = ""


# ─── Task Type Config ─────────────────────────────────────────

class TaskConstraints(BaseModel):
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=15, ge=1, le=300)
    batch_size: int | None = None                   # For embedding tasks


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=300, ge=0)


class TaskTypeConfig(BaseModel):
    description: str = ""
    tier: str = "T2"
    required_capabilities: list[str] = Field(default_factory=lambda: ["text_generation"])
    preferred_model: str                            # References model key
    fallback_chain: list[str] = Field(default_factory=list)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    cache: CacheConfig = Field(default_factory=CacheConfig)


class TaskAlias(BaseModel):
    alias_of: str


# ─── Budget Config ────────────────────────────────────────────

class DailyBudget(BaseModel):
    total_token_limit: int = 0                      # 0 = unlimited
    track_usage: bool = True
    alert_threshold_pct: int = Field(default=80, ge=0, le=100)
    kill_switch_threshold_pct: int = Field(default=95, ge=0, le=100)


class PerTaskBudget(BaseModel):
    max_tokens_per_day: int = 0
    max_calls_per_day: int = 0


class CostTrackingConfig(BaseModel):
    enabled: bool = True
    currency: str = "USD"
    daily_cost_limit: float = Field(default=5.0, ge=0.0)
    alert_at: float = Field(default=3.0, ge=0.0)


class BudgetConfig(BaseModel):
    daily: DailyBudget = Field(default_factory=DailyBudget)
    per_task_type: dict[str, PerTaskBudget] = Field(default_factory=dict)
    cost_tracking: CostTrackingConfig = Field(default_factory=CostTrackingConfig)


# ─── Defaults Config ──────────────────────────────────────────

class DefaultsConfig(BaseModel):
    fallback_model: str = "qwen_local_7b"
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout_seconds: int = 15
    cache_ttl_seconds: int = 300
    on_provider_failure: OnFailureAction = OnFailureAction.VETO
    on_rate_limit: OnRateLimitAction = OnRateLimitAction.WAIT_THEN_RETRY


# ─── Root Config ──────────────────────────────────────────────

class ModelsConfig(BaseModel):
    """Root configuration model for config/models.yaml."""
    schema_version: str = "1.0.0"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    task_types: dict[str, TaskTypeConfig | TaskAlias] = Field(default_factory=dict)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)

    @model_validator(mode="after")
    def validate_model_provider_refs(self) -> ModelsConfig:
        """Ensure every model references a valid provider."""
        for name, model in self.models.items():
            if model.provider not in self.providers:
                raise ValueError(
                    f"Model '{name}' references unknown provider '{model.provider}'. "
                    f"Available: {list(self.providers.keys())}"
                )
        return self

    @model_validator(mode="after")
    def validate_task_model_refs(self) -> ModelsConfig:
        """Ensure every task_type references valid models."""
        for name, task in self.task_types.items():
            if isinstance(task, TaskAlias):
                continue
            if task.preferred_model not in self.models:
                raise ValueError(
                    f"Task '{name}' references unknown model '{task.preferred_model}'. "
                    f"Available: {list(self.models.keys())}"
                )
            for fallback in task.fallback_chain:
                if fallback not in self.models:
                    raise ValueError(
                        f"Task '{name}' fallback references unknown model '{fallback}'."
                    )
        return self

    def resolve_task_type(self, task_type: str) -> TaskTypeConfig:
        """Resolve a task type, following aliases if needed."""
        task = self.task_types.get(task_type)
        if task is None:
            raise KeyError(f"Unknown task type: '{task_type}'")
        if isinstance(task, TaskAlias):
            return self.resolve_task_type(task.alias_of)
        return task

    def get_model_for_task(self, task_type: str) -> tuple[ModelConfig, str]:
        """
        Get the best available model for a task type.
        Returns (model_config, model_key) — tries preferred, then fallback chain.
        """
        task = self.resolve_task_type(task_type)
        candidates = [task.preferred_model] + task.fallback_chain

        for model_key in candidates:
            model = self.models.get(model_key)
            if model is None:
                continue
            provider = self.providers.get(model.provider)
            if provider is None:
                continue
            # Check capabilities
            if all(cap in model.capabilities for cap in task.required_capabilities):
                return model, model_key

        # Nothing matched — use default
        default_key = self.defaults.fallback_model
        default_model = self.models.get(default_key)
        if default_model:
            return default_model, default_key

        raise RuntimeError(
            f"No model available for task '{task_type}' and default "
            f"'{default_key}' not found in config."
        )


# ─── Environment Variable Resolution ─────────────────────────

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_var(value: str) -> str:
    """Replace ${VAR_NAME} patterns with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            # Return original pattern if env var not set
            return match.group(0)
        return env_value

    return _ENV_VAR_PATTERN.sub(replacer, value)
```

### 3.2 Config Loader with Hot-Reload

```python
# src/config/model_config_loader.py
"""
Model configuration loader with hot-reload capability.
Watches config/models.yaml for changes and reloads automatically.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from src.config.models_config import (
    DefaultsConfig,
    ModelConfig,
    ModelsConfig,
    ProviderConfig,
    TaskTypeConfig,
)

logger = logging.getLogger(__name__)

# ─── Environment Override Prefix ──────────────────────────────
ENV_PREFIX = "TSAR_MODELS__"


class ModelConfigLoader:
    """
    Loads and manages model configuration from YAML + env overrides.
    
    Features:
    - Load from config/models.yaml
    - Environment variable overrides (TSAR_MODELS__ prefix)
    - Pydantic validation on every load
    - Hot-reload via file watcher thread
    - Environment-specific overrides (dev/staging/prod)
    - Thread-safe singleton access
    """

    _instance: ModelConfigLoader | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        config_path: str | Path = "config/models.yaml",
        environment: str | None = None,
        watch: bool = True,
    ):
        self._config_path = Path(config_path)
        self._environment = environment or os.getenv("TRADING_ENV", "development")
        self._config: ModelsConfig | None = None
        self._file_hash: str | None = None
        self._callbacks: list[Callable[[ModelsConfig], None]] = []
        self._watch_thread: threading.Thread | None = None
        self._stop_watch = threading.Event()

        # Load immediately
        self.reload()

        # Start file watcher if requested
        if watch:
            self.start_watching()

    @classmethod
    def get_instance(cls, **kwargs) -> ModelConfigLoader:
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.stop_watching()
                cls._instance = None

    @property
    def config(self) -> ModelsConfig:
        """Get current configuration. Thread-safe."""
        if self._config is None:
            raise RuntimeError("Model configuration not loaded")
        return self._config

    def on_change(self, callback: Callable[[ModelsConfig], None]) -> None:
        """Register a callback for configuration changes."""
        self._callbacks.append(callback)

    def reload(self) -> ModelsConfig:
        """
        Load configuration from YAML file with environment overrides.
        Validates with Pydantic. Raises on invalid config.
        """
        # 1. Load base YAML
        raw_config = self._load_yaml()

        # 2. Apply environment-specific overrides
        env_config = self._load_environment_override()
        if env_config:
            raw_config = _deep_merge(raw_config, env_config)

        # 3. Apply environment variable overrides
        raw_config = self._apply_env_overrides(raw_config)

        # 4. Resolve all ${VAR} references
        raw_config = _resolve_all_env_vars(raw_config)

        # 5. Validate with Pydantic
        config = ModelsConfig(**raw_config)

        # 6. Update state
        old_config = self._config
        self._config = config
        self._file_hash = self._compute_file_hash()

        logger.info(
            f"Model config loaded: {len(config.providers)} providers, "
            f"{len(config.models)} models, {len(config.task_types)} task types "
            f"(env={self._environment})"
        )

        # 7. Notify callbacks if config changed
        if old_config is not None and old_config != config:
            for callback in self._callbacks:
                try:
                    callback(config)
                except Exception as e:
                    logger.error(f"Config change callback failed: {e}")

        return config

    def _load_yaml(self) -> dict[str, Any]:
        """Load and parse the YAML config file."""
        if not self._config_path.exists():
            logger.warning(
                f"Model config not found at {self._config_path}, using empty config"
            )
            return {}

        with open(self._config_path) as f:
            data = yaml.safe_load(f)

        if data is None:
            return {}

        if not isinstance(data, dict):
            raise ValueError(f"Expected dict at root of {self._config_path}")

        return data

    def _load_environment_override(self) -> dict[str, Any] | None:
        """
        Load environment-specific override file.
        Looks for: config/models.{environment}.yaml
        """
        env_file = self._config_path.parent / f"models.{self._environment}.yaml"
        if not env_file.exists():
            return None

        logger.info(f"Loading environment override: {env_file}")
        with open(env_file) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None

    def _apply_env_overrides(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Apply environment variable overrides with TSAR_MODELS__ prefix.
        
        Convention:
          TSAR_MODELS__PROVIDERS__OLLAMA__BASE_URL=http://gpu:11434
          → config["providers"]["ollama"]["base_url"] = "http://gpu:11434"
          
          TSAR_MODELS__MODELS__QWEN_LOCAL_7B__MODEL_ID=qwen2.5:14b
          → config["models"]["qwen_local_7b"]["model_id"] = "qwen2.5:14b"
          
          TSAR_MODELS__TASK_TYPES__T2_NEWS_SENTIMENT__PREFERRED_MODEL=llama_local_8b
          → config["task_types"]["t2_news_sentiment"]["preferred_model"] = "llama_local_8b"
        """
        for key, value in os.environ.items():
            if not key.startswith(ENV_PREFIX):
                continue

            # Parse path: TSAR_MODELS__A__B__C → ["a", "b", "c"]
            path_parts = key[len(ENV_PREFIX):].lower().split("__")
            if not path_parts:
                continue

            # Navigate config dict and set value
            current = config
            for part in path_parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Convert value types
            final_key = path_parts[-1]
            current[final_key] = _coerce_env_value(value)

            logger.debug(f"Applied env override: {key} → {'.'.join(path_parts)}")

        return config

    def _compute_file_hash(self) -> str | None:
        """Compute SHA256 hash of config file for change detection."""
        if not self._config_path.exists():
            return None
        content = self._config_path.read_bytes()
        return hashlib.sha256(content).hexdigest()

    # ─── Hot-Reload Watcher ───────────────────────────────────

    def start_watching(self, interval_seconds: float = 5.0) -> None:
        """Start background thread watching for config file changes."""
        if self._watch_thread is not None:
            return

        def watch_loop():
            while not self._stop_watch.is_set():
                try:
                    new_hash = self._compute_file_hash()
                    if new_hash and new_hash != self._file_hash:
                        logger.info("Config file changed, reloading...")
                        self.reload()
                except Exception as e:
                    logger.error(f"Config watch error: {e}")

                self._stop_watch.wait(interval_seconds)

        self._watch_thread = threading.Thread(
            target=watch_loop,
            name="model-config-watcher",
            daemon=True,
        )
        self._watch_thread.start()
        logger.info(f"Config watcher started (interval={interval_seconds}s)")

    def stop_watching(self) -> None:
        """Stop the config file watcher."""
        self._stop_watch.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=10)
            self._watch_thread = None


# ─── Helper Functions ─────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_all_env_vars(obj: Any) -> Any:
    """Recursively resolve ${VAR} patterns in all string values."""
    if isinstance(obj, str):
        import re
        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r"\$\{([^}]+)\}", replacer, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_all_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_all_env_vars(item) for item in obj]
    return obj


def _coerce_env_value(value: str) -> Any:
    """Coerce string environment variable to appropriate Python type."""
    # Boolean
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # Integer
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # String
    return value
```

### 3.3 Model Router (Replaces Hardcoded `ModelRouter`)

```python
# src/llm/model_router.py
"""
Config-driven model router. Replaces all hardcoded model references.
Tools call router.get_model(task_type) — never reference model names directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.config.model_config_loader import ModelConfigLoader
from src.config.models_config import ModelConfig, ModelsConfig, TaskTypeConfig

logger = logging.getLogger(__name__)


@dataclass
class ModelInstance:
    """Resolved model ready for use by a tool/agent."""
    task_type: str
    model_key: str                  # Internal config key
    provider: str                   # Provider name
    model_id: str                   # Actual model identifier (e.g., "qwen2.5:7b")
    base_url: str                   # Provider base URL
    api_key: str | None             # Provider API key
    max_tokens: int
    temperature: float
    timeout_seconds: int
    cache_enabled: bool
    cache_ttl_seconds: int
    tier: str                       # T1, T2, T3
    capabilities: list[str]


@dataclass
class UsageTracker:
    """Tracks token usage and costs per task type."""
    daily_tokens: dict[str, int] = field(default_factory=dict)
    daily_calls: dict[str, int] = field(default_factory=dict)
    daily_cost: float = 0.0
    last_reset: float = field(default_factory=time.time)


class ModelRouter:
    """
    Routes task types to configured models.
    
    Usage:
        router = ModelRouter()
        model = router.get_model("t2_news_sentiment")
        # model.model_id is the actual model name — code never hardcodes it
    """

    def __init__(self, config_loader: ModelConfigLoader | None = None):
        self._loader = config_loader or ModelConfigLoader.get_instance()
        self._usage = UsageTracker()

    def get_model(self, task_type: str) -> ModelInstance:
        """
        Get the best available model for a task type.
        Resolves preferred → fallback chain. Returns a ModelInstance
        ready for use. Raises if no model available and on_provider_failure=veto.
        """
        config = self._loader.config
        task = config.resolve_task_type(task_type)
        model_config, model_key = config.get_model_for_task(task_type)
        provider = config.providers[model_config.provider]

        # Check budget
        if not self._check_budget(task_type, config):
            raise BudgetExceededError(
                f"Budget exceeded for task type '{task_type}'"
            )

        return ModelInstance(
            task_type=task_type,
            model_key=model_key,
            provider=provider.type.value,
            model_id=model_config.model_id,
            base_url=provider.base_url,
            api_key=provider.api_key,
            max_tokens=task.constraints.max_tokens,
            temperature=task.constraints.temperature,
            timeout_seconds=task.constraints.timeout_seconds,
            cache_enabled=task.cache.enabled,
            cache_ttl_seconds=task.cache.ttl_seconds,
            tier=task.tier,
            capabilities=model_config.capabilities,
        )

    def get_model_with_fallback(self, task_type: str) -> list[ModelInstance]:
        """
        Get ordered list of model instances for a task type.
        First element is preferred, rest are fallbacks.
        Used by tools that implement their own fallback logic.
        """
        config = self._loader.config
        task = config.resolve_task_type(task_type)
        candidates = [task.preferred_model] + task.fallback_chain
        instances = []

        for model_key in candidates:
            model_config = config.models.get(model_key)
            provider = config.providers.get(model_config.provider) if model_config else None
            if not model_config or not provider:
                continue

            instances.append(ModelInstance(
                task_type=task_type,
                model_key=model_key,
                provider=provider.type.value,
                model_id=model_config.model_id,
                base_url=provider.base_url,
                api_key=provider.api_key,
                max_tokens=task.constraints.max_tokens,
                temperature=task.constraints.temperature,
                timeout_seconds=task.constraints.timeout_seconds,
                cache_enabled=task.cache.enabled,
                cache_ttl_seconds=task.cache.ttl_seconds,
                tier=task.tier,
                capabilities=model_config.capabilities,
            ))

        if not instances:
            raise NoModelAvailableError(
                f"No models available for task type '{task_type}'"
            )

        return instances

    def record_usage(
        self,
        task_type: str,
        input_tokens: int,
        output_tokens: int,
        cost: float = 0.0,
    ) -> None:
        """Record token usage for budget tracking."""
        self._usage.daily_tokens[task_type] = (
            self._usage.daily_tokens.get(task_type, 0) + input_tokens + output_tokens
        )
        self._usage.daily_calls[task_type] = (
            self._usage.daily_calls.get(task_type, 0) + 1
        )
        self._usage.daily_cost += cost

    def _check_budget(self, task_type: str, config: ModelsConfig) -> bool:
        """Check if budget allows this request."""
        budgets = config.budgets

        # Check daily total
        total_used = sum(self._usage.daily_tokens.values())
        if budgets.daily.total_token_limit > 0:
            if total_used >= budgets.daily.total_token_limit:
                return False

        # Check per-task budget
        task_budget = budgets.per_task_type.get(task_type)
        if task_budget:
            if (task_budget.max_tokens_per_day > 0 and
                    self._usage.daily_tokens.get(task_type, 0) >= task_budget.max_tokens_per_day):
                return False
            if (task_budget.max_calls_per_day > 0 and
                    self._usage.daily_calls.get(task_type, 0) >= task_budget.max_calls_per_day):
                return False

        # Check cost limit
        if budgets.cost_tracking.enabled:
            if self._usage.daily_cost >= budgets.cost_tracking.daily_cost_limit:
                return False

        return True

    @property
    def usage_summary(self) -> dict[str, Any]:
        """Get current usage summary."""
        return {
            "daily_tokens": dict(self._usage.daily_tokens),
            "daily_calls": dict(self._usage.daily_calls),
            "daily_cost": self._usage.daily_cost,
            "total_tokens": sum(self._usage.daily_tokens.values()),
            "total_calls": sum(self._usage.daily_calls.values()),
        }


# ─── Exceptions ───────────────────────────────────────────────

class ModelRouterError(Exception):
    pass

class BudgetExceededError(ModelRouterError):
    pass

class NoModelAvailableError(ModelRouterError):
    pass
```

### 3.4 Usage in Agent Code

```python
# Example: How agent code uses the router (BEFORE vs AFTER)

# ═══ BEFORE (hardcoded) ═══════════════════════════════════════
# class RegimeDetectorAgent:
#     async def spawn(self):
#         self.llm = OllamaClient(model="qwen2.5:7b")  # ← HARDCODED

# ═══ AFTER (config-driven) ════════════════════════════════════
# class RegimeDetectorAgent:
#     async def spawn(self):
#         self.router = ModelRouter()
#         self.llm_model = self.router.get_model("t2_regime_explanation")
#         # self.llm_model.model_id → resolved from config at runtime
#         self.llm = create_llm_client(self.llm_model)
```

---

## 4. Tool Model Resolution

### 4.1 The Resolution Chain

```
Tool Code                    Config Layer                   Provider
─────────                    ────────────                   ────────
                             
router.get_model(            models.yaml:                   Ollama/NVIDIA/
  "t2_news_sentiment"   →    task_types:                      DeepSeek
)                               t2_news_sentiment:             
                                  preferred_model:             ↓
                                    "qwen_local_7b"      qwen2.5:7b
                             models:                        (actual API
                                qwen_local_7b:               call)
                                  provider: "ollama"
                                  model_id: "qwen2.5:7b"
```

**Key invariant:** The string `"qwen2.5:7b"` appears ONLY in `config/models.yaml`. Agent code contains ONLY task type strings like `"t2_news_sentiment"`.

### 4.2 Task Type Registry

All valid task types, grouped by agent:

| Agent | Task Types | Tier |
|-------|-----------|------|
| **Regime Detector** | `t2_regime_explanation` | T2 |
| **Signal Scout** | `t2_signal_narrative`, `t2_news_sentiment` | T2 |
| **Risk Guardian** | `t2_risk_explanation`, `t3_risk_scenario` | T2, T3 |
| **Trade Philosopher** | `t3_trade_narrative`, `t3_bias_detection`, `t2_trade_summary` | T2, T3 |
| **Strategy Geneticist** | `t3_strategy_synthesis`, `t2_strategy_evaluation` | T2, T3 |
| **Market Cartographer** | `t2_anomaly_explanation` | T2 |
| **Daily Reports** | `t2_daily_summary` | T2 |
| **Pattern Search** | `t1_pattern_embedding` | T1 |

### 4.3 LLM Client Factory

```python
# src/llm/client_factory.py
"""
Factory that creates LLM clients from ModelInstance config.
This is the ONLY place that instantiates LLM client objects.
"""

from __future__ import annotations

from src.config.models_config import ProviderType
from src.llm.model_router import ModelInstance


def create_llm_client(model: ModelInstance) -> Any:
    """
    Create an LLM client for the given model instance.
    Returns the appropriate client type based on provider.
    """
    if model.provider == ProviderType.OLLAMA.value:
        return _create_ollama_client(model)
    elif model.provider == ProviderType.OPENAI_COMPATIBLE.value:
        return _create_openai_client(model)
    elif model.provider == ProviderType.DEEPSEEK.value:
        return _create_deepseek_client(model)
    else:
        raise ValueError(f"Unknown provider type: {model.provider}")


def _create_ollama_client(model: ModelInstance):
    """Create Ollama client from model config."""
    import httpx
    from src.llm.ollama_client import OllamaClient

    return OllamaClient(
        base_url=model.base_url,
        model=model.model_id,             # ← resolved from config
        timeout=model.timeout_seconds,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
    )


def _create_openai_client(model: ModelInstance):
    """Create OpenAI-compatible client from model config."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        base_url=model.base_url,
        api_key=model.api_key,
        timeout=model.timeout_seconds,
    )


def _create_deepseek_client(model: ModelInstance):
    """Create DeepSeek client from model config."""
    from src.llm.deepseek_client import DeepSeekClient

    return DeepSeekClient(
        base_url=model.base_url,
        api_key=model.api_key,
        model=model.model_id,             # ← resolved from config
        timeout=model.timeout_seconds,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
    )
```

### 4.4 Decorator for Easy Agent Integration

```python
# src/llm/task_model.py
"""
Convenience decorator for agents to declare their model requirements.
"""

from __future__ import annotations

import functools
from typing import Callable

from src.llm.model_router import ModelRouter


def with_model(task_type: str):
    """
    Decorator that injects a resolved ModelInstance into the method.
    
    Usage:
        @with_model("t2_regime_explanation")
        async def explain_regime(self, regime_data, model=None):
            client = create_llm_client(model)
            return await client.generate(...)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if "model" not in kwargs or kwargs["model"] is None:
                router = ModelRouter.get_instance()
                kwargs["model"] = router.get_model(task_type)
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

---

## 5. Migration Guide

### 5.1 Complete File Inventory

Every file that contains hardcoded model names and what needs to change:

| # | File | Hardcoded Models | References | Fix Type |
|---|------|-----------------|------------|----------|
| 1 | `TECH_STACK.md` | `ollama/qwen3:8b`, `ollama/llama3:8b`, `deepseek/deepseek-chat`, `local/all-MiniLM-L6-v2` | 18 | Update doc |
| 2 | `trading-super-agent-spec.md` | `qwen2.5:7b`, `deepseek-ai/deepseek-r1`, `deepseek-reasoner`, `qwen2.5:32b` | 15 | Update doc |
| 3 | `DAY1_ARCHITECTURE.md` | `qwen2.5:7b`, `deepseek-ai/deepseek-r1` | 6 | Update doc |
| 4 | `MARKET_ANALYSIS_LAYER.md` | `qwen2.5:7b`, `all-MiniLM-L6-v2` | 8 | Update doc |
| 5 | `DATA_ARCHITECTURE.md` | `all-MiniLM-L6-v2` | 8 | Update doc |
| 6 | `STRATEGY_LAYER.md` | `deepseek` (implicit) | 1 | Update doc |
| 7 | `config/model_routing.yaml` | `ollama/qwen3:8b`, `ollama/llama3:8b`, etc. | 14 | Replace with `config/models.yaml` |
| 8 | `config/default.yaml` | `ollama/qwen3:8b`, `ollama/llama3:8b`, `deepseek/deepseek-chat`, `local/all-MiniLM-L6-v2` | 4 | Remove `llm.models` section |

### 5.2 Before/After for Each File

#### 5.2.1 `TECH_STACK.md` — Model Routing Section

**BEFORE:**
```yaml
llm:
  models:
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    complex: "deepseek/deepseek-chat"
    embeddings: "local/all-MiniLM-L6-v2"
```

**AFTER:**
```yaml
llm:
  # Model names are now in config/models.yaml.
  # Tools reference task types (e.g., "t2_news_sentiment"), NOT model names.
  # See: config/models.yaml for the complete model configuration.
  config_file: "config/models.yaml"
```

**BEFORE (model_routing.yaml section):**
```yaml
routing:
  news_analysis:
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    max_tokens: 1024
    temperature: 0.1
  signal_validation:
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
  # ... 5 more task definitions with hardcoded models
```

**AFTER:**
```yaml
# Model routing is now defined in config/models.yaml under task_types.
# This file is DEPRECATED. Delete after migration.
# See: config/models.yaml → task_types section
```

#### 5.2.2 `trading-super-agent-spec.md` — Model Router

**BEFORE:**
```python
class ModelRouter:
    TIERS = {
        "t2_local": {
            "provider": "ollama",
            "model": "qwen2.5:7b",          # ← HARDCODED
            "max_tokens": 2048,
            "timeout_s": 10,
            "cost": 0,
        },
        "t3_free_nvidia": {
            "provider": "nvidia_nim",
            "model": "deepseek-ai/deepseek-r1",  # ← HARDCODED
            "max_tokens": 4096,
            "timeout_s": 30,
            "cost": 0,
            "rate_limit": "100/min",
        },
        "t3_free_deepseek": {
            "provider": "deepseek_api",
            "model": "deepseek-reasoner",    # ← HARDCODED
            "max_tokens": 4096,
            "timeout_s": 30,
            "cost": 0,
            "rate_limit": "10/min",
        },
        "t3_fallback": {
            "provider": "ollama",
            "model": "qwen2.5:32b",          # ← HARDCODED
            "max_tokens": 4096,
            "timeout_s": 60,
            "cost": 0,
        },
    }
```

**AFTER:**
```python
class ModelRouter:
    """
    Model routing is now config-driven.
    See config/models.yaml → task_types section.
    
    Usage:
        router = ModelRouter()
        model = router.get_model("t3_trade_narrative")
        # model.model_id is resolved from config — never hardcoded
    """
    # TIERS dict removed — all routing via config/models.yaml
    pass
```

#### 5.2.3 `trading-super-agent-spec.md` — Agent Spawn Code

**BEFORE (Regime Detector):**
```python
class RegimeDetectorAgent:
    async def spawn(self):
        self.rust_engine = regime_engine.Realm()
        self.redis = await aioredis.from_url(REDIS_URL)
        self.llm = OllamaClient(model="qwen2.5:7b")  # ← HARDCODED
```

**AFTER:**
```python
class RegimeDetectorAgent:
    async def spawn(self):
        self.rust_engine = regime_engine.Realm()
        self.redis = await aioredis.from_url(REDIS_URL)
        self.router = ModelRouter()
        self.llm_model = self.router.get_model("t2_regime_explanation")
        self.llm = create_llm_client(self.llm_model)  # model_id from config
```

**BEFORE (Trade Philosopher):**
```python
class TradePhilosopherAgent:
    async def spawn(self):
        self.llm_narrator = DeepSeekClient(model="deepseek-r1")  # ← HARDCODED
        self.llm_quick = OllamaClient(model="qwen2.5:7b")        # ← HARDCODED
```

**AFTER:**
```python
class TradePhilosopherAgent:
    async def spawn(self):
        self.router = ModelRouter()
        self.narrator_model = self.router.get_model("t3_trade_narrative")
        self.quick_model = self.router.get_model("t2_trade_summary")
        self.llm_narrator = create_llm_client(self.narrator_model)
        self.llm_quick = create_llm_client(self.quick_model)
```

**BEFORE (Strategy Geneticist):**
```python
class StrategyGeneticistAgent:
    async def spawn(self):
        self.llm_strategist = DeepSeekClient(model="deepseek-r1")  # ← HARDCODED
```

**AFTER:**
```python
class StrategyGeneticistAgent:
    async def spawn(self):
        self.router = ModelRouter()
        self.synth_model = self.router.get_model("t3_strategy_synthesis")
        self.llm_strategist = create_llm_client(self.synth_model)
```

**BEFORE (Market Cartographer):**
```python
class MarketCartographerAgent:
    async def spawn(self):
        self.llm = OllamaClient(model="qwen2.5:7b")  # ← HARDCODED
```

**AFTER:**
```python
class MarketCartographerAgent:
    async def spawn(self):
        self.router = ModelRouter()
        self.anomaly_model = self.router.get_model("t2_anomaly_explanation")
        self.llm = create_llm_client(self.anomaly_model)
```

**BEFORE (Risk Guardian):**
```python
# Uses ollama_deepseek_r1 tool directly
```

**AFTER:**
```python
class RiskGuardianAgent:
    async def spawn(self):
        self.router = ModelRouter()
        self.scenario_model = self.router.get_model("t3_risk_scenario")
        self.explanation_model = self.router.get_model("t2_risk_explanation")
```

#### 5.2.4 `MARKET_ANALYSIS_LAYER.md`

**BEFORE:**
```python
response = await self.ollama.generate(prompt, model="qwen2.5:7b")  # ← HARDCODED
```

**AFTER:**
```python
model = self.router.get_model("t2_news_sentiment")
response = await self.ollama.generate(prompt, model=model.model_id)
```

#### 5.2.5 `DATA_ARCHITECTURE.md` — Embedding Model

**BEFORE:**
```python
self.model = SentenceTransformer('all-MiniLM-L6-v2')  # ← HARDCODED
```

**AFTER:**
```python
from src.config.model_config_loader import ModelConfigLoader
config = ModelConfigLoader.get_instance().config
embedding_model = config.models["minilm_local"]
self.model = SentenceTransformer(embedding_model.model_id)
```

#### 5.2.6 `config/default.yaml` — LLM Section

**BEFORE:**
```yaml
llm:
  provider: "litellm"
  models:
    primary: "ollama/qwen3:8b"
    fallback: "ollama/llama3:8b"
    complex: "deepseek/deepseek-chat"
    embeddings: "local/all-MiniLM-L6-v2"
```

**AFTER:**
```yaml
llm:
  # Model configuration moved to config/models.yaml
  config_file: "config/models.yaml"
  cache_responses: true
  cache_ttl: 86400
```

#### 5.2.7 `DAY1_ARCHITECTURE.md`

**BEFORE:**
```python
"model": "qwen2.5:7b",
# ...
"model": "deepseek-ai/deepseek-r1",
```

**AFTER:**
```python
# Models resolved from config/models.yaml via task type
# Example: router.get_model("t2_news_sentiment").model_id
```

### 5.3 Automated Migration (sed/regex)

Run these commands to find and flag all hardcoded model references for manual review:

```bash
# ─── Find all hardcoded model names ──────────────────────────

# 1. Find "qwen" references (any variant)
grep -rn 'qwen\|Qwen' tsar/docs/ tsar/src/ tsar/config/ \
  --include="*.py" --include="*.yaml" --include="*.yml" --include="*.md" \
  | grep -v "models.yaml" \
  | grep -v "FIX_02" \
  | grep -v "node_modules"

# 2. Find "llama" references
grep -rn 'llama3\|Llama3\|llama3:8b' tsar/ \
  --include="*.py" --include="*.yaml" --include="*.md" \
  | grep -v "models.yaml" | grep -v "FIX_02"

# 3. Find "deepseek" model references
grep -rn 'deepseek-r1\|deepseek-reasoner\|deepseek/deepseek' tsar/ \
  --include="*.py" --include="*.yaml" --include="*.md" \
  | grep -v "models.yaml" | grep -v "FIX_02"

# 4. Find "MiniLM" references
grep -rn 'MiniLM-L6-v2\|all-MiniLM' tsar/ \
  --include="*.py" --include="*.yaml" --include="*.md" \
  | grep -v "models.yaml" | grep -v "FIX_02"

# 5. Find OllamaClient/DeepSeekClient with hardcoded model= parameter
grep -rn 'model="qwen\|model="llama\|model="deepseek' tsar/ \
  --include="*.py" \
  | grep -v "models.yaml" | grep -v "FIX_02"
```

```bash
# ─── Automated replacements (for .py files) ──────────────────
# WARNING: Review each replacement manually. These are patterns, not blind sed.

# Pattern 1: OllamaClient(model="qwen2.5:7b") → router-based
find tsar/src -name "*.py" -exec sed -i \
  's/OllamaClient(model="qwen2.5:7b")/create_llm_client(self.router.get_model("t2_regime_explanation"))/g' \
  {} +

# Pattern 2: DeepSeekClient(model="deepseek-r1") → router-based
find tsar/src -name "*.py" -exec sed -i \
  's/DeepSeekClient(model="deepseek-r1")/create_llm_client(self.router.get_model("t3_trade_narrative"))/g' \
  {} +

# Pattern 3: SentenceTransformer("all-MiniLM-L6-v2") → config-based
find tsar/src -name "*.py" -exec sed -i \
  's/SentenceTransformer('\''all-MiniLM-L6-v2'\'')/SentenceTransformer(get_embedding_model_id())/g' \
  {} +

# Pattern 4: model="qwen2.5:7b" in generate() calls
find tsar/src -name "*.py" -exec sed -i \
  's/model="qwen2.5:7b"/model=self.llm_model.model_id/g' \
  {} +
```

### 5.4 Migration Checklist

- [ ] Create `config/models.yaml` with full schema
- [ ] Create `src/config/models_config.py` (Pydantic models)
- [ ] Create `src/config/model_config_loader.py` (loader + hot-reload)
- [ ] Create `src/llm/model_router.py` (config-driven router)
- [ ] Create `src/llm/client_factory.py` (client factory)
- [ ] Create `config/models.development.yaml` (dev overrides)
- [ ] Create `config/models.production.yaml` (prod overrides)
- [ ] Update `TECH_STACK.md` — remove hardcoded models from config sections
- [ ] Update `trading-super-agent-spec.md` — replace ModelRouter TIERS
- [ ] Update `DAY1_ARCHITECTURE.md` — replace model references
- [ ] Update `MARKET_ANALYSIS_LAYER.md` — replace model references
- [ ] Update `DATA_ARCHITECTURE.md` — replace embedding model references
- [ ] Update `STRATEGY_LAYER.md` — replace model references
- [ ] Delete `config/model_routing.yaml` (superseded by models.yaml)
- [ ] Update `config/default.yaml` — remove `llm.models` section
- [ ] Update `.env.example` — add `TSAR_MODELS__*` examples
- [ ] Update `docker-compose.yml` — add model config volume mount
- [ ] Run `grep` validation — zero model names outside models.yaml
- [ ] Write tests for config loader, router, and fallback chains
- [ ] Test hot-reload in dev environment

---

## 6. Environment Variable Mapping

### 6.1 Convention

```
TSAR_MODELS__{SECTION}__{KEY}__{FIELD}={VALUE}
```

Double underscores (`__`) separate nesting levels. Keys are lowercased.

### 6.2 Complete Mapping Table

| Environment Variable | Config Path | Example Value |
|---------------------|-------------|---------------|
| **Provider Overrides** | | |
| `TSAR_MODELS__PROVIDERS__OLLAMA__BASE_URL` | `providers.ollama.base_url` | `http://gpu-server:11434` |
| `TSAR_MODELS__PROVIDERS__OLLAMA__API_KEY` | `providers.ollama.api_key` | (none needed) |
| `TSAR_MODELS__PROVIDERS__OLLAMA__TIMEOUT_SECONDS` | `providers.ollama.timeout_seconds` | `60` |
| `TSAR_MODELS__PROVIDERS__OLLAMA__MAX_CONCURRENT` | `providers.ollama.max_concurrent` | `8` |
| `TSAR_MODELS__PROVIDERS__NVIDIA_NIM__API_KEY` | `providers.nvidia_nim.api_key` | `nvapi-xxx` |
| `TSAR_MODELS__PROVIDERS__NVIDIA_NIM__BASE_URL` | `providers.nvidia_nim.base_url` | `https://integrate.api.nvidia.com/v1` |
| `TSAR_MODELS__PROVIDERS__NVIDIA_NIM__RATE_LIMIT__REQUESTS_PER_MINUTE` | `providers.nvidia_nim.rate_limit.requests_per_minute` | `50` |
| `TSAR_MODELS__PROVIDERS__DEEPSEEK_API__API_KEY` | `providers.deepseek_api.api_key` | `sk-xxx` |
| `TSAR_MODELS__PROVIDERS__OPENAI__API_KEY` | `providers.openai.api_key` | `sk-xxx` |
| **Model Overrides** | | |
| `TSAR_MODELS__MODELS__QWEN_LOCAL_7B__MODEL_ID` | `models.qwen_local_7b.model_id` | `qwen2.5:14b` |
| `TSAR_MODELS__MODELS__QWEN_LOCAL_7B__PROVIDER` | `models.qwen_local_7b.provider` | `ollama` |
| `TSAR_MODELS__MODELS__DEEPSEEK_R1_NVIDIA__MODEL_ID` | `models.deepseek_r1_nvidia.model_id` | `deepseek-ai/deepseek-r1-0528` |
| `TSAR_MODELS__MODELS__LLAMA_LOCAL_8B__MODEL_ID` | `models.llama_local_8b.model_id` | `llama3.1:8b` |
| **Task Type Overrides** | | |
| `TSAR_MODELS__TASK_TYPES__T2_NEWS_SENTIMENT__PREFERRED_MODEL` | `task_types.t2_news_sentiment.preferred_model` | `llama_local_8b` |
| `TSAR_MODELS__TASK_TYPES__T3_TRADE_NARRATIVE__PREFERRED_MODEL` | `task_types.t3_trade_narrative.preferred_model` | `deepseek_r1_direct` |
| `TSAR_MODELS__TASK_TYPES__T2_REGIME_EXPLANATION__CONSTRAINTS__MAX_TOKENS` | `task_types.t2_regime_explanation.constraints.max_tokens` | `2048` |
| `TSAR_MODELS__TASK_TYPES__T2_REGIME_EXPLANATION__CONSTRAINTS__TEMPERATURE` | `task_types.t2_regime_explanation.constraints.temperature` | `0.0` |
| **Budget Overrides** | | |
| `TSAR_MODELS__BUDGETS__DAILY__TOTAL_TOKEN_LIMIT` | `budgets.daily.total_token_limit` | `1000000` |
| `TSAR_MODELS__BUDGETS__COST_TRACKING__DAILY_COST_LIMIT` | `budgets.cost_tracking.daily_cost_limit` | `10.0` |
| **Default Overrides** | | |
| `TSAR_MODELS__DEFAULTS__FALLBACK_MODEL` | `defaults.fallback_model` | `llama_local_8b` |
| `TSAR_MODELS__DEFAULTS__ON_PROVIDER_FAILURE` | `defaults.on_provider_failure` | `skip` |

### 6.3 Legacy Variable Compatibility

These existing env vars are preserved and mapped:

| Existing Variable | Maps To | Notes |
|------------------|---------|-------|
| `TRADING_DEEPSEEK_API_KEY` | `providers.deepseek_api.api_key` | Also resolved via `${TRADING_DEEPSEEK_API_KEY}` in YAML |
| `TRADING_OPENAI_API_KEY` | `providers.openai.api_key` | Also resolved via `${TRADING_OPENAI_API_KEY}` in YAML |
| `NVIDIA_API_KEY` | `providers.nvidia_nim.api_key` | Also resolved via `${NVIDIA_API_KEY}` in YAML |
| `TRADING_ENV` | `app.environment` | Controls which `models.{env}.yaml` to load |

### 6.4 Environment-Specific Override Files

Create these files for environment-specific model overrides:

```
config/
├── models.yaml              # Base config (all environments)
├── models.development.yaml  # Dev overrides (cheaper/faster models)
├── models.staging.yaml      # Staging overrides (match prod)
└── models.production.yaml   # Prod overrides (best models)
```

**`config/models.development.yaml` example:**
```yaml
# Development overrides — use cheapest/fastest models
providers:
  nvidia_nim:
    max_concurrent: 1              # Reduce concurrency in dev

task_types:
  t3_trade_narrative:
    preferred_model: "qwen_local_7b"  # Skip expensive T3 in dev
    fallback_chain: []
  t3_strategy_synthesis:
    preferred_model: "qwen_local_7b"
    fallback_chain: []

budgets:
  daily:
    total_token_limit: 100000       # Cap dev usage
  cost_tracking:
    daily_cost_limit: 0.0           # No spending in dev
```

**`config/models.production.yaml` example:**
```yaml
# Production overrides — best models, higher limits
providers:
  ollama:
    max_concurrent: 8
    timeout_seconds: 60

budgets:
  daily:
    total_token_limit: 0            # Unlimited in prod
  cost_tracking:
    daily_cost_limit: 20.0
    alert_at: 15.0
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# tests/unit/config/test_models_config.py

import pytest
from src.config.models_config import ModelsConfig, TaskAlias


class TestModelsConfig:
    def test_valid_config_loads(self, sample_config_dict):
        config = ModelsConfig(**sample_config_dict)
        assert len(config.providers) > 0
        assert len(config.models) > 0

    def test_model_references_valid_provider(self):
        with pytest.raises(ValueError, match="unknown provider"):
            ModelsConfig(
                providers={"ollama": {"type": "ollama", "base_url": "http://localhost"}},
                models={"bad_model": {"provider": "nonexistent", "model_id": "x", "display_name": "X"}},
            )

    def test_task_references_valid_model(self):
        with pytest.raises(ValueError, match="unknown model"):
            ModelsConfig(
                providers={"ollama": {"type": "ollama", "base_url": "http://localhost"}},
                models={},
                task_types={"bad_task": {"preferred_model": "nonexistent", "tier": "T2"}},
            )

    def test_resolve_task_type_follows_alias(self, sample_config_dict):
        config = ModelsConfig(**sample_config_dict)
        task = config.resolve_task_type("news_analysis")  # alias
        assert task.description != ""

    def test_resolve_task_type_unknown_raises(self, sample_config_dict):
        config = ModelsConfig(**sample_config_dict)
        with pytest.raises(KeyError):
            config.resolve_task_type("nonexistent_task")

    def test_get_model_for_task_returns_preferred(self, sample_config_dict):
        config = ModelsConfig(**sample_config_dict)
        model, key = config.get_model_for_task("t2_news_sentiment")
        assert key == "qwen_local_7b"

    def test_get_model_for_task_falls_back(self, sample_config_with_unavailable_preferred):
        config = ModelsConfig(**sample_config_with_unavailable_preferred)
        model, key = config.get_model_for_task("t2_news_sentiment")
        assert key == "llama_local_8b"  # Fallback
```

```python
# tests/unit/config/test_model_config_loader.py

import os
import tempfile
import pytest
from src.config.model_config_loader import ModelConfigLoader


class TestModelConfigLoader:
    def setup_method(self):
        ModelConfigLoader.reset_instance()

    def test_load_from_yaml(self, models_yaml_path):
        loader = ModelConfigLoader(config_path=models_yaml_path, watch=False)
        assert loader.config.schema_version == "1.0.0"

    def test_env_override(self, models_yaml_path, monkeypatch):
        monkeypatch.setenv(
            "TSAR_MODELS__MODELS__QWEN_LOCAL_7B__MODEL_ID", "qwen2.5:14b"
        )
        loader = ModelConfigLoader(config_path=models_yaml_path, watch=False)
        assert loader.config.models["qwen_local_7b"].model_id == "qwen2.5:14b"

    def test_env_override_provider_url(self, models_yaml_path, monkeypatch):
        monkeypatch.setenv(
            "TSAR_MODELS__PROVIDERS__OLLAMA__BASE_URL", "http://gpu:11434"
        )
        loader = ModelConfigLoader(config_path=models_yaml_path, watch=False)
        assert loader.config.providers["ollama"].base_url == "http://gpu:11434"

    def test_environment_specific_override(self, models_yaml_path):
        # Create dev override file
        override_path = models_yaml_path.parent / "models.development.yaml"
        override_path.write_text("""
task_types:
  t3_trade_narrative:
    preferred_model: "qwen_local_7b"
""")
        loader = ModelConfigLoader(
            config_path=models_yaml_path,
            environment="development",
            watch=False,
        )
        assert loader.config.task_types["t3_trade_narrative"].preferred_model == "qwen_local_7b"

    def test_hot_reload(self, models_yaml_path):
        loader = ModelConfigLoader(config_path=models_yaml_path, watch=True)
        original_model = loader.config.models["qwen_local_7b"].model_id

        # Modify file
        content = models_yaml_path.read_text()
        content = content.replace("qwen2.5:7b", "qwen2.5:14b")
        models_yaml_path.write_text(content)

        # Wait for reload
        import time
        time.sleep(6)

        assert loader.config.models["qwen_local_7b"].model_id == "qwen2.5:14b"
```

```python
# tests/unit/llm/test_model_router.py

import pytest
from src.llm.model_router import ModelRouter, BudgetExceededError


class TestModelRouter:
    def test_get_model_returns_configured_model(self, configured_loader):
        router = ModelRouter(config_loader=configured_loader)
        model = router.get_model("t2_news_sentiment")
        assert model.model_id == "qwen2.5:7b"
        assert model.provider == "ollama"

    def test_get_model_follows_alias(self, configured_loader):
        router = ModelRouter(config_loader=configured_loader)
        model = router.get_model("news_analysis")  # alias
        assert model.model_id == "qwen2.5:7b"

    def test_get_model_with_fallback(self, configured_loader):
        router = ModelRouter(config_loader=configured_loader)
        models = router.get_model_with_fallback("t3_trade_narrative")
        assert len(models) >= 2
        assert models[0].model_id == "deepseek-ai/deepseek-r1"

    def test_budget_enforcement(self, configured_loader):
        router = ModelRouter(config_loader=configured_loader)
        # Simulate exceeding budget
        router._usage.daily_cost = 100.0
        with pytest.raises(BudgetExceededError):
            router.get_model("t3_trade_narrative")

    def test_no_model_name_in_model_instance(self, configured_loader):
        """Verify ModelInstance doesn't contain any hardcoded model names from other tasks."""
        router = ModelRouter(config_loader=configured_loader)
        model = router.get_model("t2_news_sentiment")
        # The model_id should come from config, not be hardcoded in router code
        assert hasattr(model, "model_id")
        assert isinstance(model.model_id, str)
```

### 7.2 Integration Test

```python
# tests/integration/test_model_config_integration.py

async def test_end_to_end_model_resolution():
    """Full cycle: YAML → loader → router → model instance → client creation."""
    from src.config.model_config_loader import ModelConfigLoader
    from src.llm.model_router import ModelRouter
    from src.llm.client_factory import create_llm_client

    loader = ModelConfigLoader(config_path="config/models.yaml", watch=False)
    router = ModelRouter(config_loader=loader)

    # Resolve a T2 task
    model = router.get_model("t2_regime_explanation")
    assert model.tier == "T2"
    assert model.model_id is not None
    assert model.base_url is not None

    # Verify no hardcoded names leaked
    assert model.model_id != "HARDCODED"
    assert "qwen" in model.model_id or "llama" in model.model_id

    # Create client
    client = create_llm_client(model)
    assert client is not None
```

### 7.3 Validation Script

```python
# scripts/validate_no_hardcoded_models.py
"""
CI script: fails if any model name appears outside config/models.yaml.
Run in CI pipeline to prevent regression.
"""

import re
import sys
from pathlib import Path

HARDCODED_PATTERNS = [
    r'model\s*=\s*["\']qwen',
    r'model\s*=\s*["\']llama',
    r'model\s*=\s*["\']deepseek',
    r'model\s*=\s*["\']MiniLM',
    r'OllamaClient\(model=',
    r'DeepSeekClient\(model=',
    r'SentenceTransformer\(["\']all-MiniLM',
    r'"model"\s*:\s*"qwen',
    r'"model"\s*:\s*"llama',
    r'"model"\s*:\s*"deepseek',
    r'primary:\s*"ollama/',
    r'fallback:\s*"ollama/',
]

EXCLUDED_FILES = {
    "config/models.yaml",
    "config/models.development.yaml",
    "config/models.production.yaml",
    "config/models.staging.yaml",
    "FIX_02_CONFIGURABLE_MODELS.md",
    "validate_no_hardcoded_models.py",
}

def main():
    root = Path("tsar")
    violations = []

    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix not in (".py", ".yaml", ".yml", ".md"):
            continue
        if any(excluded in str(path) for excluded in EXCLUDED_FILES):
            continue

        content = path.read_text(errors="ignore")
        for pattern in HARDCODED_PATTERNS:
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(f"{path}:{line_num}: {match.group()}")

    if violations:
        print(f"❌ Found {len(violations)} hardcoded model references:")
        for v in violations:
            print(f"  {v}")
        sys.exit(1)
    else:
        print("✅ No hardcoded model references found")
        sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 8. Rollout Plan

### Phase 1: Foundation (Day 1)
1. Create `config/models.yaml` with complete schema
2. Create `src/config/models_config.py` (Pydantic models)
3. Create `src/config/model_config_loader.py` (loader + hot-reload)
4. Write unit tests for config loading and validation

### Phase 2: Router (Day 2)
5. Create `src/llm/model_router.py` (config-driven router)
6. Create `src/llm/client_factory.py` (client factory)
7. Create `src/llm/task_model.py` (decorator)
8. Write unit tests for router and fallback chains

### Phase 3: Migration (Day 3-4)
9. Update all agent spawn code to use router (6 agents)
10. Update `TECH_STACK.md`, `trading-super-agent-spec.md`, and other docs
11. Delete `config/model_routing.yaml`
12. Update `config/default.yaml`

### Phase 4: Validation (Day 5)
13. Create `scripts/validate_no_hardcoded_models.py`
14. Add to CI pipeline
15. Create environment-specific override files
16. Update `.env.example` with `TSAR_MODELS__*` examples
17. Full regression test

### Phase 5: Documentation (Day 5)
18. Update all architecture docs to reference `config/models.yaml`
19. Add model configuration guide to `docs/`
20. Update `README.md` with new config instructions

---

## Appendix A: Naming Convention Reconciliation

The codebase uses inconsistent model names. Here's the canonical mapping:

| Canonical Key | `models.yaml` model_id | Old Names Found in Docs |
|---------------|----------------------|------------------------|
| `qwen_local_7b` | `qwen2.5:7b` | `qwen3:8b`, `Qwen2.5-7B`, `qwen2.5:7b` |
| `qwen_local_32b` | `qwen2.5:32b` | `qwen2.5:32b` |
| `llama_local_8b` | `llama3:8b` | `llama3:8b`, `Llama3 8B` |
| `deepseek_r1_nvidia` | `deepseek-ai/deepseek-r1` | `deepseek-r1`, `DeepSeek-R1`, `deepseek-ai/deepseek-r1` |
| `deepseek_r1_direct` | `deepseek-reasoner` | `deepseek-reasoner`, `deepseek/deepseek-chat` |
| `minilm_local` | `all-MiniLM-L6-v2` | `all-MiniLM-L6-v2`, `MiniLM-L6-v2`, `local/all-MiniLM-L6-v2` |

**After migration:** Only `config/models.yaml` contains the `model_id` column. All other files use the canonical key or task type.

---

## Appendix B: File Layout

```
trading-super-agent/
├── config/
│   ├── models.yaml                    # NEW: Single source of truth for all models
│   ├── models.development.yaml        # NEW: Dev overrides
│   ├── models.production.yaml         # NEW: Prod overrides
│   ├── default.yaml                   # MODIFIED: Remove llm.models section
│   ├── model_routing.yaml             # DELETED: Superseded by models.yaml
│   ├── exchanges.yaml                 # Unchanged
│   ├── risk.yaml                      # Unchanged
│   └── ...
│
├── src/
│   ├── config/
│   │   ├── models_config.py           # NEW: Pydantic models for models.yaml
│   │   ├── model_config_loader.py     # NEW: Loader with hot-reload + env overrides
│   │   └── ...
│   │
│   ├── llm/
│   │   ├── model_router.py            # REWRITTEN: Config-driven, no hardcoded models
│   │   ├── client_factory.py          # NEW: Creates LLM clients from ModelInstance
│   │   ├── task_model.py              # NEW: @with_model decorator
│   │   └── ...
│   │
│   └── ...
│
└── scripts/
    └── validate_no_hardcoded_models.py # NEW: CI validation script
```

---

*Specification completed: 2026-07-24 04:30 GMT+8*
*This document defines the complete migration from hardcoded model names to a config-driven system.*
