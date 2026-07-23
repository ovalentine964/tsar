# FIX-01: Model-Agnostic LLM Abstraction Layer

**Severity:** CRITICAL  
**Status:** SPECIFICATION — Ready for Implementation  
**Date:** 2026-07-24  
**Author:** LLM Integration Specialist  
**Scope:** `src/llm/` — Complete replacement of current hardcoded router

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Design Principles](#2-design-principles)
3. [Architecture Overview](#3-architecture-overview)
4. [Core Data Types](#4-core-data-types)
5. [BaseLLMProvider Abstract Class](#5-basellmprovider-abstract-class)
6. [Provider Implementations](#6-provider-implementations)
   - 6.1 [OllamaProvider](#61-ollamaprovider)
   - 6.2 [OpenAIProvider](#62-openaiprovider)
   - 6.3 [AnthropicProvider](#63-anthropicprovider)
   - 6.4 [DeepSeekProvider](#64-deepseekprovider)
7. [ModelRegistry](#7-modelregistry)
8. [ModelRouter Redesign](#8-modelrouter-redesign)
9. [Token Counting](#9-token-counting)
10. [Configuration Schema](#10-configuration-schema)
11. [Integration with Existing Agents](#11-integration-with-existing-agents)
12. [Testing Strategy](#12-testing-strategy)
13. [Migration Plan](#13-migration-plan)
14. [File Layout](#14-file-layout)

---

## 1. Problem Statement

The current LLM integration in `src/llm/router.py` uses **hardcoded model identifiers** (e.g., `ollama/qwen3:8b`, `deepseek/deepseek-chat`) and routes through **LiteLLM** as a monolithic abstraction. This creates three critical problems:

| Problem | Impact | Example |
|---------|--------|---------|
| **No provider interface** | Cannot swap models without code changes | Changing from Qwen to Llama requires editing `router.py` internals |
| **LiteLLM coupling** | System depends on LiteLLM's API surface and bugs | LiteLLM version upgrade breaks model name parsing |
| **No capability-aware routing** | Cannot select models based on what they support | Agent needs tool-use but doesn't know if model supports it |

### Current State (Broken)

```python
# src/llm/router.py — CURRENT (hardcoded)
class ModelRouter:
    TIERS = {
        "t2_local": {
            "provider": "ollama",
            "model": "qwen2.5:7b",          # ← Hardcoded
            "max_tokens": 2048,
            "timeout_s": 10,
            "cost": 0,
        },
        "t3_free_nvidia": {
            "provider": "nvidia_nim",
            "model": "deepseek-ai/deepseek-r1",  # ← Hardcoded
            ...
        },
    }
```

### Target State (Fixed)

```python
# src/llm/router.py — TARGET (config-driven)
router = ModelRouter(registry)
provider, model = router.route(
    task_type="trade_narrative",
    required_capabilities={Capability.TOOL_USE, Capability.STREAMING},
    prefer="cheapest",
)
response = await provider.generate(prompt, model=model.name)
```

---

## 2. Design Principles

| Principle | Rule | Rationale |
|-----------|------|-----------|
| **Provider-agnostic** | No agent code references a specific provider | Swap Ollama for vLLM without touching agent code |
| **Config-driven** | All model definitions in YAML, zero in code | Ops can add/remove models without code deploys |
| **Capability-aware** | Models declare what they can do | Router selects models that match task requirements |
| **Fail-safe** | Every call has a fallback chain | System degrades gracefully, never hard-fails |
| **Observable** | Every LLM call is tracked (latency, tokens, cost) | Budget enforcement and performance monitoring |
| **Async-first** | All methods are `async` | Non-blocking I/O for concurrent agent execution |
| **Type-safe** | Pydantic models for all data structures | Catch config errors at load time, not runtime |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT LAYER                                 │
│  Regime Detector · Signal Scout · Risk Guardian · Philosopher    │
│  Strategy Geneticist · Market Cartographer                       │
│         │            │            │            │                  │
│         ▼            ▼            ▼            ▼                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   ModelRouter                            │    │
│  │  route(task_type, context) → (provider, model_spec)     │    │
│  │  • Task-to-model mapping (config-driven)                │    │
│  │  • Fallback chain with circuit breaker                  │    │
│  │  • Cost tracking per model                              │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │                   ModelRegistry                          │    │
│  │  register_model(provider, name, capabilities)           │    │
│  │  find_model(required_caps, prefer) → ModelSpec          │    │
│  │  get_fallback_chain(task_type) → list[ModelSpec]        │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │              BaseLLMProvider (abstract)                   │    │
│  │  generate(prompt, **kwargs) → LLMResponse               │    │
│  │  stream(prompt, **kwargs) → AsyncIterator[LLMChunk]     │    │
│  │  count_tokens(text) → int                               │    │
│  │  get_capabilities() → ModelCapabilities                  │    │
│  │  health_check() → bool                                  │    │
│  └───┬────────┬────────┬────────┬──────────────────────────┘    │
│      │        │        │        │                                │
│  ┌───▼──┐ ┌──▼───┐ ┌──▼────┐ ┌▼──────────┐                    │
│  │Ollama│ │OpenAI│ │Anthrop│ │DeepSeek   │                    │
│  │  ..  │ │  ..  │ │  ic.. │ │  Provider │                    │
│  └──────┘ └──────┘ └───────┘ └───────────┘                    │
│      │        │        │        │                                │
│  ┌───▼────────▼────────▼────────▼──────────────────────────┐    │
│  │              CircuitBreaker + CostTracker                │    │
│  │  • Per-provider failure tracking                        │    │
│  │  • Daily/monthly budget enforcement                     │    │
│  │  • Automatic provider disabling                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Configuration (YAML)                        │    │
│  │  config/models.yaml — providers, models, routing        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Core Data Types

```python
# src/llm/types.py

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# CAPABILITIES
# ═══════════════════════════════════════════════════════════════

class Capability(str, Enum):
    """What a model can do."""
    TEXT_GENERATION = "text_generation"
    STREAMING = "streaming"
    TOOL_USE = "tool_use"           # Function calling / tool use
    JSON_MODE = "json_mode"         # Structured JSON output
    VISION = "vision"               # Image understanding
    CODE_GENERATION = "code_generation"
    LONG_CONTEXT = "long_context"   # >32k context window
    REASONING = "reasoning"         # Chain-of-thought / extended thinking


# ═══════════════════════════════════════════════════════════════
# MODEL SPECIFICATION
# ═══════════════════════════════════════════════════════════════

class ModelCapabilities(BaseModel):
    """Declarative capabilities of a model."""
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_json_mode: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    max_context_tokens: int = 4096
    max_output_tokens: int = 4096
    cost_per_1k_input_tokens: float = 0.0    # USD
    cost_per_1k_output_tokens: float = 0.0   # USD
    tokens_per_second: float | None = None   # Estimated throughput
    capabilities: set[Capability] = Field(default_factory=set)

    def has_all(self, required: set[Capability]) -> bool:
        """Check if this model has all required capabilities."""
        return required.issubset(self.capabilities)


class ModelSpec(BaseModel):
    """A specific model available on a provider."""
    provider_name: str               # e.g. "ollama", "openai"
    model_name: str                  # e.g. "qwen2.5:7b", "gpt-4o"
    display_name: str = ""           # Human-readable name
    capabilities: ModelCapabilities
    enabled: bool = True
    priority: int = 100              # Lower = higher priority (used for ordering)
    tags: list[str] = Field(default_factory=list)  # e.g. ["local", "free", "fast"]

    @property
    def full_id(self) -> str:
        """Unique identifier: provider/model."""
        return f"{self.provider_name}/{self.model_name}"


# ═══════════════════════════════════════════════════════════════
# REQUEST / RESPONSE
# ═══════════════════════════════════════════════════════════════

class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class Message:
    """A single message in a conversation."""
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """Definition of a tool the model can call."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass
class LLMRequest:
    """Standardized request to any LLM provider."""
    messages: list[Message]
    model: str                                  # Model name on the provider
    max_tokens: int = 2048
    temperature: float = 0.1
    top_p: float = 1.0
    stop: list[str] | None = None
    tools: list[ToolDefinition] | None = None
    tool_choice: str | dict | None = None       # "auto", "none", {"name": "..."}
    json_mode: bool = False
    response_format: dict | None = None         # {"type": "json_object"}
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # Provider-specific params


@dataclass(frozen=True)
class TokenUsage:
    """Token usage for a single LLM call."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0              # Tokens served from cache (prompt caching)


@dataclass(frozen=True)
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str                            # Generated text
    model: str                              # Model that actually served the request
    provider: str                           # Provider name
    usage: TokenUsage
    finish_reason: str                      # "stop", "length", "tool_calls", "error"
    tool_calls: list[dict[str, Any]] | None = None  # Parsed tool calls
    raw_response: dict[str, Any] | None = None      # Original provider response (debug)
    latency_ms: float = 0.0                         # End-to-end latency
    cached: bool = False                            # Was this served from cache?


@dataclass(frozen=True)
class LLMChunk:
    """A single chunk in a streaming response."""
    content: str                            # Incremental text delta
    model: str
    provider: str
    finish_reason: str | None = None        # None until final chunk
    tool_calls_delta: list[dict] | None = None  # Incremental tool call data
    usage: TokenUsage | None = None         # Only populated on final chunk


# ═══════════════════════════════════════════════════════════════
# COST TRACKING
# ═══════════════════════════════════════════════════════════════

@dataclass
class CostRecord:
    """A single cost entry for an LLM call."""
    timestamp: float
    provider: str
    model: str
    task_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class CostTracker:
    """Tracks LLM usage and cost across all providers."""

    def __init__(self, daily_budget_usd: float = 0.0, monthly_budget_usd: float = 0.0):
        self.daily_budget_usd = daily_budget_usd    # 0 = unlimited
        self.monthly_budget_usd = monthly_budget_usd
        self._records: list[CostRecord] = []

    def record(self, record: CostRecord) -> None:
        """Record a cost entry."""
        self._records.append(record)

    def get_daily_cost(self, provider: str | None = None) -> float:
        """Get total cost for today, optionally filtered by provider."""
        today_start = time.time() - (time.time() % 86400)
        return sum(
            r.cost_usd for r in self._records
            if r.timestamp >= today_start
            and (provider is None or r.provider == provider)
        )

    def get_monthly_cost(self) -> float:
        """Get total cost for current month."""
        # Simplified: last 30 days
        cutoff = time.time() - (30 * 86400)
        return sum(r.cost_usd for r in self._records if r.timestamp >= cutoff)

    def is_within_budget(self, estimated_cost: float = 0.0) -> bool:
        """Check if we can afford another call."""
        if self.daily_budget_usd > 0:
            if self.get_daily_cost() + estimated_cost > self.daily_budget_usd:
                return False
        if self.monthly_budget_usd > 0:
            if self.get_monthly_cost() + estimated_cost > self.monthly_budget_usd:
                return False
        return True

    def get_usage_summary(self) -> dict[str, Any]:
        """Get usage summary by provider and model."""
        summary: dict[str, dict[str, Any]] = {}
        for r in self._records:
            key = f"{r.provider}/{r.model}"
            if key not in summary:
                summary[key] = {
                    "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "total_cost_usd": 0.0, "avg_latency_ms": 0.0,
                    "_latencies": [],
                }
            s = summary[key]
            s["calls"] += 1
            s["input_tokens"] += r.input_tokens
            s["output_tokens"] += r.output_tokens
            s["total_cost_usd"] += r.cost_usd
            s["_latencies"].append(r.latency_ms)

        # Calculate averages
        for s in summary.values():
            lats = s.pop("_latencies")
            s["avg_latency_ms"] = sum(lats) / len(lats) if lats else 0.0

        return summary


# ═══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════

class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Provider failing, requests blocked
    HALF_OPEN = "half_open" # Testing if provider recovered


@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker."""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout_s: float = 60.0    # Seconds before half-open
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    success_count: int = 0              # In half-open state

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)  # Decay

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def is_available(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout_s:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        return True  # HALF_OPEN: allow probe requests

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
```

---

## 5. BaseLLMProvider Abstract Class

```python
# src/llm/providers/base.py

from __future__ import annotations

import abc
from typing import AsyncIterator

from src.llm.types import (
    LLMChunk,
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ModelSpec,
    TokenUsage,
)


class BaseLLMProvider(abc.ABC):
    """
    Abstract base class for all LLM providers.
    
    Every provider must implement this interface. The router and registry
    work exclusively through this abstraction — no agent code ever touches
    a concrete provider.
    
    Lifecycle:
        1. __init__(config) — Load provider-specific config
        2. initialize()    — Async setup (HTTP clients, auth validation)
        3. generate() / stream() — Serve requests
        4. shutdown()       — Cleanup (close HTTP clients, flush metrics)
    """

    def __init__(self, name: str, config: dict) -> None:
        """
        Initialize provider with configuration.
        
        Args:
            name: Provider identifier (e.g. "ollama", "openai")
            config: Provider-specific config dict from models.yaml
        """
        self.name = name
        self.config = config
        self._models: dict[str, ModelSpec] = {}

    # ═══════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def initialize(self) -> None:
        """
        Async initialization. Called once after construction.
        
        Must:
        - Create HTTP clients
        - Validate API keys (if applicable)
        - Register available models
        
        Must NOT:
        - Make test LLM calls (use health_check() for that)
        - Block for more than 5 seconds
        """
        ...

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """
        Graceful shutdown. Called once before process exit.
        
        Must:
        - Close HTTP clients
        - Flush pending metrics
        - Release resources
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # CORE METHODS
    # ═══════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Generate a complete (non-streaming) response.
        
        Args:
            request: Standardized LLM request with messages, model, params
            
        Returns:
            LLMResponse with content, usage, metadata
            
        Raises:
            ProviderRateLimitError: Rate limit hit, retryable
            ProviderAuthError: Authentication failed, not retryable
            ProviderTimeoutError: Request timed out, retryable
            ProviderModelError: Model not found or unavailable
            ProviderCapacityError: Provider at capacity, retryable
        """
        ...

    @abc.abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        """
        Generate a streaming response.
        
        Args:
            request: Standardized LLM request (stream=True implied)
            
        Yields:
            LLMChunk objects with incremental content
            
        Raises:
            Same exceptions as generate()
        """
        ...

    @abc.abstractmethod
    def count_tokens(self, text: str, model: str | None = None) -> int:
        """
        Count tokens in text for the given model.
        
        Must be fast (<1ms for <10k chars). Used for:
        - Budget checking before API calls
        - Context window management
        - Prompt truncation decisions
        
        Args:
            text: Text to count tokens for
            model: Specific model (tokenizer varies by model)
            
        Returns:
            Number of tokens
        """
        ...

    @abc.abstractmethod
    def get_capabilities(self, model: str) -> ModelCapabilities:
        """
        Get capabilities for a specific model on this provider.
        
        Args:
            model: Model name on this provider
            
        Returns:
            ModelCapabilities describing what the model can do
            
        Raises:
            ValueError: Model not found on this provider
        """
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is currently reachable and operational.
        
        Must:
        - Complete within 5 seconds
        - Not consume significant tokens (use a minimal prompt)
        - Return False on any failure (auth, network, capacity)
        
        Returns:
            True if provider is healthy, False otherwise
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # CONVENIENCE METHODS (non-abstract, default implementations)
    # ═══════════════════════════════════════════════════════════

    def list_models(self) -> list[ModelSpec]:
        """List all models registered on this provider."""
        return list(self._models.values())

    def get_model(self, model_name: str) -> ModelSpec | None:
        """Get a specific model spec by name."""
        return self._models.get(model_name)

    def has_model(self, model_name: str) -> bool:
        """Check if a model is available on this provider."""
        return model_name in self._models

    def supports_streaming(self, model: str) -> bool:
        """Quick check if a model supports streaming."""
        spec = self._models.get(model)
        return spec is not None and spec.capabilities.supports_streaming

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Estimate cost in USD for a request."""
        caps = self.get_capabilities(model)
        input_cost = (input_tokens / 1000) * caps.cost_per_1k_input_tokens
        output_cost = (output_tokens / 1000) * caps.cost_per_1k_output_tokens
        return input_cost + output_cost

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} models={len(self._models)}>"
```

---

## 6. Provider Implementations

### 6.1 OllamaProvider

```python
# src/llm/providers/ollama.py

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import httpx

from src.llm.providers.base import BaseLLMProvider
from src.llm.types import (
    Capability,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ModelCapabilities,
    ModelSpec,
    TokenUsage,
)
from src.llm.errors import (
    ProviderModelError,
    ProviderTimeoutError,
    ProviderCapacityError,
)


class OllamaProvider(BaseLLMProvider):
    """
    Provider for local models served by Ollama.
    
    Supports:
    - All Ollama-served models (Qwen, Llama, Mistral, DeepSeek, etc.)
    - Streaming via NDJSON
    - Tool use (model-dependent)
    - JSON mode
    - Vision (for multimodal models like llava)
    
    Config:
        base_url: "http://localhost:11434"
        timeout_s: 30
        keep_alive_s: 300
    """

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self.timeout_s = config.get("timeout_s", 30)
        self.keep_alive_s = config.get("keep_alive_s", 300)
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_s, connect=5.0),
        )
        # Discover available models from Ollama
        try:
            resp = await self._client.get("/api/tags")
            if resp.status_code == 200:
                available = {m["name"] for m in resp.json().get("models", [])}
                # Match against configured models
                for model_name, spec in self._models.items():
                    if model_name in available:
                        spec.enabled = True
                    else:
                        spec.enabled = False
        except httpx.ConnectError:
            # Ollama not running — models stay in configured state
            pass

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert self._client is not None, "Provider not initialized"
        
        start_time = time.monotonic()
        ollama_messages = self._convert_messages(request.messages)
        
        payload = {
            "model": request.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
                "top_p": request.top_p,
            },
            "keep_alive": f"{self.keep_alive_s}s",
        }
        
        if request.stop:
            payload["options"]["stop"] = request.stop
        
        if request.json_mode:
            payload["format"] = "json"
        
        if request.tools:
            payload["tools"] = [self._convert_tool(t) for t in request.tools]
        
        try:
            resp = await self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Ollama timeout: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ProviderModelError(f"Model not found: {request.model}")
            raise

        latency_ms = (time.monotonic() - start_time) * 1000
        
        # Parse response
        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls")
        
        # Ollama returns prompt/eval token counts
        usage = TokenUsage(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        )
        
        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.name,
            usage=usage,
            finish_reason="stop" if data.get("done") else "length",
            tool_calls=tool_calls,
            raw_response=data,
            latency_ms=latency_ms,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        assert self._client is not None, "Provider not initialized"
        
        ollama_messages = self._convert_messages(request.messages)
        
        payload = {
            "model": request.model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
                "top_p": request.top_p,
            },
            "keep_alive": f"{self.keep_alive_s}s",
        }
        
        if request.stop:
            payload["options"]["stop"] = request.stop
        if request.json_mode:
            payload["format"] = "json"
        if request.tools:
            payload["tools"] = [self._convert_tool(t) for t in request.tools]
        
        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                
                message = data.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls")
                
                finish_reason = None
                usage = None
                if data.get("done"):
                    finish_reason = "stop"
                    usage = TokenUsage(
                        prompt_tokens=data.get("prompt_eval_count", 0),
                        completion_tokens=data.get("eval_count", 0),
                        total_tokens=(
                            data.get("prompt_eval_count", 0) +
                            data.get("eval_count", 0)
                        ),
                    )
                
                yield LLMChunk(
                    content=content,
                    model=request.model,
                    provider=self.name,
                    finish_reason=finish_reason,
                    tool_calls_delta=tool_calls,
                    usage=usage,
                )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        # Ollama doesn't expose a token counting API.
        # Use approximation: ~4 chars per token for English, ~2 for CJK.
        # For production, integrate tiktoken with the model's tokenizer.
        # This is a reasonable default:
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii = len(text) - ascii_chars
        return (ascii_chars // 4) + (non_ascii // 2)

    def get_capabilities(self, model: str) -> ModelCapabilities:
        spec = self._models.get(model)
        if spec:
            return spec.capabilities
        # Default capabilities for unknown Ollama models
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=False,
            supports_json_mode=True,
            max_context_tokens=4096,
            max_output_tokens=2048,
            cost_per_1k_input_tokens=0.0,
            cost_per_1k_output_tokens=0.0,
            capabilities={Capability.TEXT_GENERATION, Capability.STREAMING},
        )

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ═══════════════════════════════════════════════════════════

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert our Message format to Ollama's format."""
        result = []
        for msg in messages:
            ollama_msg: dict = {"role": msg.role.value, "content": msg.content}
            if msg.tool_calls:
                ollama_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                ollama_msg["tool_call_id"] = msg.tool_call_id
            result.append(ollama_msg)
        return result

    def _convert_tool(self, tool) -> dict:
        """Convert ToolDefinition to Ollama tool format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
```

### 6.2 OpenAIProvider

```python
# src/llm/providers/openai.py

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import openai

from src.llm.providers.base import BaseLLMProvider
from src.llm.types import (
    Capability,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ModelCapabilities,
    ModelSpec,
    TokenUsage,
)
from src.llm.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderModelError,
    ProviderCapacityError,
)


class OpenAIProvider(BaseLLMProvider):
    """
    Provider for OpenAI-compatible APIs.
    
    Supports:
    - GPT-4o, GPT-4o-mini, GPT-3.5-turbo
    - Any OpenAI-compatible endpoint (vLLM, NVIDIA NIM, etc.)
    - Streaming via SSE
    - Tool use / function calling
    - JSON mode
    - Vision (GPT-4o)
    
    Config:
        api_key: "${OPENAI_API_KEY}"     # env var reference
        base_url: "https://api.openai.com/v1"  # override for compatible APIs
        organization: null
        timeout_s: 30
        max_retries: 2
    """

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._api_key = config.get("api_key", "")
        self._base_url = config.get("base_url", "https://api.openai.com/v1")
        self._organization = config.get("organization")
        self._timeout_s = config.get("timeout_s", 30)
        self._max_retries = config.get("max_retries", 2)
        self._client: openai.AsyncOpenAI | None = None

    async def initialize(self) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            organization=self._organization,
            timeout=self._timeout_s,
            max_retries=self._max_retries,
        )

    async def shutdown(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert self._client is not None, "Provider not initialized"
        
        start_time = time.monotonic()
        messages = self._convert_messages(request.messages)
        
        kwargs: dict = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": False,
        }
        
        if request.stop:
            kwargs["stop"] = request.stop
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        elif request.response_format:
            kwargs["response_format"] = request.response_format
        if request.seed is not None:
            kwargs["seed"] = request.seed
        if request.tools:
            kwargs["tools"] = [self._convert_tool(t) for t in request.tools]
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice
        
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as e:
            raise ProviderAuthError(f"OpenAI auth failed: {e}") from e
        except openai.RateLimitError as e:
            raise ProviderRateLimitError(f"OpenAI rate limit: {e}") from e
        except openai.APITimeoutError as e:
            raise ProviderTimeoutError(f"OpenAI timeout: {e}") from e
        except openai.NotFoundError as e:
            raise ProviderModelError(f"Model not found: {request.model}") from e
        except openai.APIStatusError as e:
            if e.status_code == 529:
                raise ProviderCapacityError(f"OpenAI overloaded: {e}") from e
            raise

        latency_ms = (time.monotonic() - start_time) * 1000
        
        choice = response.choices[0]
        content = choice.message.content or ""
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
        
        usage = TokenUsage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            cached_tokens=getattr(response.usage, "prompt_tokens_details", {})
                .get("cached_tokens", 0) if hasattr(response.usage, "prompt_tokens_details") else 0,
        )
        
        finish_reason = choice.finish_reason or "stop"
        
        return LLMResponse(
            content=content,
            model=response.model,
            provider=self.name,
            usage=usage,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            raw_response=response.model_dump(),
            latency_ms=latency_ms,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        assert self._client is not None, "Provider not initialized"
        
        messages = self._convert_messages(request.messages)
        
        kwargs: dict = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
        }
        
        if request.stop:
            kwargs["stop"] = request.stop
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if request.tools:
            kwargs["tools"] = [self._convert_tool(t) for t in request.tools]
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice
        
        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as e:
            raise ProviderAuthError(f"OpenAI auth failed: {e}") from e
        except openai.RateLimitError as e:
            raise ProviderRateLimitError(f"OpenAI rate limit: {e}") from e
        
        async for chunk in stream:
            if not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason
            
            content = delta.content or ""
            tool_calls_delta = None
            if delta.tool_calls:
                tool_calls_delta = [
                    {
                        "index": tc.index,
                        "id": tc.id,
                        "type": "function" if tc.type else None,
                        "function": {
                            "name": tc.function.name if tc.function else None,
                            "arguments": tc.function.arguments if tc.function else None,
                        },
                    }
                    for tc in delta.tool_calls
                ]
            
            usage = None
            if finish_reason and chunk.usage:
                usage = TokenUsage(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                )
            
            yield LLMChunk(
                content=content,
                model=chunk.model or request.model,
                provider=self.name,
                finish_reason=finish_reason,
                tool_calls_delta=tool_calls_delta,
                usage=usage,
            )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        try:
            import tiktoken
            # Map model to encoding
            model_lower = (model or "").lower()
            if "gpt-4o" in model_lower or "gpt-4-turbo" in model_lower:
                enc = tiktoken.encoding_for_model("gpt-4o")
            elif "gpt-3.5" in model_lower:
                enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
            else:
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            # Fallback: approximate
            return len(text) // 4

    def get_capabilities(self, model: str) -> ModelCapabilities:
        spec = self._models.get(model)
        if spec:
            return spec.capabilities
        
        # Sensible defaults for unknown OpenAI models
        model_lower = model.lower()
        if "gpt-4o" in model_lower:
            return ModelCapabilities(
                supports_streaming=True,
                supports_tools=True,
                supports_json_mode=True,
                supports_vision=True,
                max_context_tokens=128_000,
                max_output_tokens=16_384,
                cost_per_1k_input_tokens=0.0025,
                cost_per_1k_output_tokens=0.010,
                capabilities={
                    Capability.TEXT_GENERATION, Capability.STREAMING,
                    Capability.TOOL_USE, Capability.JSON_MODE,
                    Capability.VISION, Capability.LONG_CONTEXT,
                },
            )
        
        # Generic fallback
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_json_mode=True,
            max_context_tokens=16_384,
            max_output_tokens=4096,
            capabilities={Capability.TEXT_GENERATION, Capability.STREAMING, Capability.TOOL_USE},
        )

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            models = await self._client.models.list()
            return True
        except Exception:
            return False

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            m: dict = {"role": msg.role.value, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
            result.append(m)
        return result

    def _convert_tool(self, tool) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
```

### 6.3 AnthropicProvider

```python
# src/llm/providers/anthropic.py

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import anthropic

from src.llm.providers.base import BaseLLMProvider
from src.llm.types import (
    Capability,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ModelCapabilities,
    ModelSpec,
    TokenUsage,
)
from src.llm.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderModelError,
    ProviderCapacityError,
)


class AnthropicProvider(BaseLLMProvider):
    """
    Provider for Anthropic Claude models.
    
    Supports:
    - Claude 3.5 Sonnet, Claude 3 Opus/Haiku
    - Streaming via SSE
    - Tool use
    - Vision
    - Extended thinking (Claude 3.5 Sonnet)
    
    Config:
        api_key: "${ANTHROPIC_API_KEY}"
        base_url: "https://api.anthropic.com"
        timeout_s: 30
        max_retries: 2
        default_max_tokens: 4096
    """

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._api_key = config.get("api_key", "")
        self._base_url = config.get("base_url", "https://api.anthropic.com")
        self._timeout_s = config.get("timeout_s", 30)
        self._max_retries = config.get("max_retries", 2)
        self._default_max_tokens = config.get("default_max_tokens", 4096)
        self._client: anthropic.AsyncAnthropic | None = None

    async def initialize(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout_s,
            max_retries=self._max_retries,
        )

    async def shutdown(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert self._client is not None, "Provider not initialized"
        
        start_time = time.monotonic()
        
        # Anthropic uses separate system message
        system_text, messages = self._extract_system_and_messages(request.messages)
        
        kwargs: dict = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or self._default_max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        
        if system_text:
            kwargs["system"] = system_text
        if request.stop:
            kwargs["stop_sequences"] = request.stop
        if request.tools:
            kwargs["tools"] = [self._convert_tool(t) for t in request.tools]
        
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise ProviderAuthError(f"Anthropic auth failed: {e}") from e
        except anthropic.RateLimitError as e:
            raise ProviderRateLimitError(f"Anthropic rate limit: {e}") from e
        except anthropic.APITimeoutError as e:
            raise ProviderTimeoutError(f"Anthropic timeout: {e}") from e
        except anthropic.NotFoundError as e:
            raise ProviderModelError(f"Model not found: {request.model}") from e
        except anthropic.APIStatusError as e:
            if e.status_code == 529:
                raise ProviderCapacityError(f"Anthropic overloaded: {e}") from e
            raise

        latency_ms = (time.monotonic() - start_time) * 1000
        
        # Extract content — Anthropic returns content blocks
        content = ""
        tool_calls = None
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": block.input,
                    },
                })
        
        usage = TokenUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            cached_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
        )
        
        return LLMResponse(
            content=content,
            model=response.model,
            provider=self.name,
            usage=usage,
            finish_reason=response.stop_reason or "stop",
            tool_calls=tool_calls,
            raw_response=response.model_dump(),
            latency_ms=latency_ms,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        assert self._client is not None, "Provider not initialized"
        
        system_text, messages = self._extract_system_and_messages(request.messages)
        
        kwargs: dict = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or self._default_max_tokens,
            "temperature": request.temperature,
        }
        
        if system_text:
            kwargs["system"] = system_text
        if request.stop:
            kwargs["stop_sequences"] = request.stop
        if request.tools:
            kwargs["tools"] = [self._convert_tool(t) for t in request.tools]
        
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield LLMChunk(
                    content=text,
                    model=request.model,
                    provider=self.name,
                )
            
            # Final message with usage
            final = await stream.get_final_message()
            yield LLMChunk(
                content="",
                model=final.model,
                provider=self.name,
                finish_reason=final.stop_reason or "stop",
                usage=TokenUsage(
                    prompt_tokens=final.usage.input_tokens,
                    completion_tokens=final.usage.output_tokens,
                    total_tokens=final.usage.input_tokens + final.usage.output_tokens,
                ),
            )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        try:
            if self._client:
                return self._client.count_tokens(text)
        except Exception:
            pass
        # Fallback approximation
        return len(text) // 4

    def get_capabilities(self, model: str) -> ModelCapabilities:
        spec = self._models.get(model)
        if spec:
            return spec.capabilities
        
        model_lower = model.lower()
        if "claude-3-5-sonnet" in model_lower or "claude-3.5" in model_lower:
            return ModelCapabilities(
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                supports_reasoning=True,
                max_context_tokens=200_000,
                max_output_tokens=8192,
                cost_per_1k_input_tokens=0.003,
                cost_per_1k_output_tokens=0.015,
                capabilities={
                    Capability.TEXT_GENERATION, Capability.STREAMING,
                    Capability.TOOL_USE, Capability.VISION,
                    Capability.LONG_CONTEXT, Capability.REASONING,
                },
            )
        
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
            max_context_tokens=200_000,
            max_output_tokens=4096,
            capabilities={
                Capability.TEXT_GENERATION, Capability.STREAMING,
                Capability.TOOL_USE, Capability.VISION, Capability.LONG_CONTEXT,
            },
        )

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.messages.create(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True
        except Exception:
            return False

    def _extract_system_and_messages(
        self, messages: list[Message]
    ) -> tuple[str, list[dict]]:
        """Separate system message from conversation (Anthropic requirement)."""
        system_text = ""
        conversation = []
        
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_text += msg.content + "\n"
            else:
                m: dict = {"role": msg.role.value, "content": msg.content}
                if msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
                if msg.tool_calls:
                    m["tool_calls"] = msg.tool_calls
                conversation.append(m)
        
        return system_text.strip(), conversation

    def _convert_tool(self, tool) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
```

### 6.4 DeepSeekProvider

```python
# src/llm/providers/deepseek.py

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import httpx

from src.llm.providers.base import BaseLLMProvider
from src.llm.types import (
    Capability,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ModelCapabilities,
    ModelSpec,
    TokenUsage,
)
from src.llm.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderModelError,
    ProviderCapacityError,
)


class DeepSeekProvider(BaseLLMProvider):
    """
    Provider for DeepSeek API (both direct and via NVIDIA NIM).
    
    Supports:
    - deepseek-chat, deepseek-reasoner
    - Streaming via SSE
    - Tool use
    - JSON mode
    - Reasoning (deepseek-reasoner chain-of-thought)
    
    Config:
        api_key: "${DEEPSEEK_API_KEY}"
        base_url: "https://api.deepseek.com"    # or NVIDIA NIM URL
        timeout_s: 60
        max_retries: 3
        
    Note: DeepSeek uses OpenAI-compatible API format, so this provider
    extends OpenAI-compatible patterns but with DeepSeek-specific handling
    for reasoning models.
    """

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._api_key = config.get("api_key", "")
        self._base_url = config.get("base_url", "https://api.deepseek.com").rstrip("/")
        self._timeout_s = config.get("timeout_s", 60)
        self._max_retries = config.get("max_retries", 3)
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self._timeout_s, connect=10.0),
        )

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert self._client is not None, "Provider not initialized"
        
        start_time = time.monotonic()
        messages = self._convert_messages(request.messages)
        
        payload: dict = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": False,
        }
        
        if request.stop:
            payload["stop"] = request.stop
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [self._convert_tool(t) for t in request.tools]
            if request.tool_choice:
                payload["tool_choice"] = request.tool_choice
        
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post("/chat/completions", json=payload)
                
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    raise ProviderRateLimitError("DeepSeek rate limit exceeded")
                
                if resp.status_code == 401:
                    raise ProviderAuthError("DeepSeek authentication failed")
                
                if resp.status_code == 404:
                    raise ProviderModelError(f"Model not found: {request.model}")
                
                resp.raise_for_status()
                data = resp.json()
                break
                
            except httpx.TimeoutException as e:
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise ProviderTimeoutError(f"DeepSeek timeout: {e}") from e
            except httpx.ConnectError as e:
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise ProviderCapacityError(f"DeepSeek connection failed: {e}") from e
        else:
            raise ProviderCapacityError("DeepSeek: all retries exhausted")

        latency_ms = (time.monotonic() - start_time) * 1000
        
        choice = data["choices"][0]
        content = choice["message"].get("content", "") or ""
        
        # Handle reasoning content (DeepSeek-R1)
        reasoning_content = choice["message"].get("reasoning_content")
        if reasoning_content:
            # Prepend reasoning as hidden context (not shown to user)
            content = content  # Keep only the final answer
        
        tool_calls = None
        if choice["message"].get("tool_calls"):
            tool_calls = choice["message"]["tool_calls"]
        
        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        
        return LLMResponse(
            content=content,
            model=data.get("model", request.model),
            provider=self.name,
            usage=usage,
            finish_reason=choice.get("finish_reason", "stop"),
            tool_calls=tool_calls,
            raw_response=data,
            latency_ms=latency_ms,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        assert self._client is not None, "Provider not initialized"
        
        messages = self._convert_messages(request.messages)
        
        payload: dict = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        
        if request.stop:
            payload["stop"] = request.stop
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [self._convert_tool(t) for t in request.tools]
        
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                
                import json
                data = json.loads(data_str)
                choice = data["choices"][0]
                delta = choice.get("delta", {})
                
                content = delta.get("content", "") or ""
                finish_reason = choice.get("finish_reason")
                
                usage = None
                if finish_reason and data.get("usage"):
                    u = data["usage"]
                    usage = TokenUsage(
                        prompt_tokens=u.get("prompt_tokens", 0),
                        completion_tokens=u.get("completion_tokens", 0),
                        total_tokens=u.get("total_tokens", 0),
                    )
                
                yield LLMChunk(
                    content=content,
                    model=data.get("model", request.model),
                    provider=self.name,
                    finish_reason=finish_reason,
                    usage=usage,
                )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        # DeepSeek uses a custom tokenizer; approximate with tiktoken
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return len(text) // 4

    def get_capabilities(self, model: str) -> ModelCapabilities:
        spec = self._models.get(model)
        if spec:
            return spec.capabilities
        
        model_lower = model.lower()
        if "reasoner" in model_lower:
            return ModelCapabilities(
                supports_streaming=True,
                supports_tools=True,
                supports_json_mode=True,
                supports_reasoning=True,
                max_context_tokens=64_000,
                max_output_tokens=8192,
                cost_per_1k_input_tokens=0.00055,
                cost_per_1k_output_tokens=0.00219,
                capabilities={
                    Capability.TEXT_GENERATION, Capability.STREAMING,
                    Capability.TOOL_USE, Capability.JSON_MODE,
                    Capability.REASONING, Capability.LONG_CONTEXT,
                },
            )
        
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_json_mode=True,
            max_context_tokens=64_000,
            max_output_tokens=4096,
            cost_per_1k_input_tokens=0.00014,
            cost_per_1k_output_tokens=0.00028,
            capabilities={
                Capability.TEXT_GENERATION, Capability.STREAMING,
                Capability.TOOL_USE, Capability.JSON_MODE, Capability.LONG_CONTEXT,
            },
        )

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            m: dict = {"role": msg.role.value, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
            result.append(m)
        return result

    def _convert_tool(self, tool) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
```

---

## 7. ModelRegistry

```python
# src/llm/registry.py

from __future__ import annotations

import logging
from typing import Any

from src.llm.providers.base import BaseLLMProvider
from src.llm.types import (
    Capability,
    CircuitBreaker,
    CostTracker,
    ModelCapabilities,
    ModelSpec,
)

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    Central registry of all available models and providers.
    
    Responsibilities:
    - Maintain provider instances and their models
    - Map capability requirements to available models
    - Provide fallback chains for task types
    - Enforce circuit breakers per provider
    
    Usage:
        registry = ModelRegistry()
        registry.register_provider(ollama_provider)
        registry.register_model("ollama", "qwen2.5:7b", ModelSpec(...))
        
        # Find cheapest model that supports tool use
        model = registry.find_model(
            required={Capability.TOOL_USE},
            prefer="cheapest",
        )
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseLLMProvider] = {}
        self._models: dict[str, ModelSpec] = {}  # full_id → ModelSpec
        self._circuit_breakers: dict[str, CircuitBreaker] = {}  # provider_name → CB
        self._fallback_chains: dict[str, list[str]] = {}  # task_type → [full_id, ...]
        self._cost_tracker = CostTracker()

    # ═══════════════════════════════════════════════════════════
    # REGISTRATION
    # ═══════════════════════════════════════════════════════════

    def register_provider(self, provider: BaseLLMProvider) -> None:
        """Register a provider instance."""
        self._providers[provider.name] = provider
        if provider.name not in self._circuit_breakers:
            self._circuit_breakers[provider.name] = CircuitBreaker()
        logger.info(f"Registered provider: {provider.name}")

    def register_model(self, provider_name: str, model_name: str, spec: ModelSpec) -> None:
        """Register a model on a provider."""
        full_id = spec.full_id
        self._models[full_id] = spec
        
        # Also register on the provider instance
        provider = self._providers.get(provider_name)
        if provider:
            provider._models[model_name] = spec
        
        logger.debug(f"Registered model: {full_id}")

    def register_fallback_chain(self, task_type: str, model_ids: list[str]) -> None:
        """Register a fallback chain for a task type."""
        self._fallback_chains[task_type] = model_ids

    # ═══════════════════════════════════════════════════════════
    # LOOKUP
    # ═══════════════════════════════════════════════════════════

    def get_provider(self, name: str) -> BaseLLMProvider | None:
        """Get a provider by name."""
        return self._providers.get(name)

    def get_model(self, full_id: str) -> ModelSpec | None:
        """Get a model spec by full_id (provider/model)."""
        return self._models.get(full_id)

    def list_providers(self) -> list[BaseLLMProvider]:
        """List all registered providers."""
        return list(self._providers.values())

    def list_models(
        self,
        provider: str | None = None,
        enabled_only: bool = True,
        tags: set[str] | None = None,
    ) -> list[ModelSpec]:
        """List all models, optionally filtered."""
        models = list(self._models.values())
        if provider:
            models = [m for m in models if m.provider_name == provider]
        if enabled_only:
            models = [m for m in models if m.enabled]
        if tags:
            models = [m for m in models if tags.issubset(set(m.tags))]
        return models

    def find_model(
        self,
        required_capabilities: set[Capability] | None = None,
        prefer: str = "cheapest",
        max_cost_per_1k: float | None = None,
        min_context_tokens: int | None = None,
        exclude: set[str] | None = None,
    ) -> ModelSpec | None:
        """
        Find the best model matching requirements.
        
        Args:
            required_capabilities: Capabilities the model MUST have
            prefer: Sort preference — "cheapest", "fastest", "largest_context"
            max_cost_per_1k: Maximum cost per 1k tokens (input)
            min_context_tokens: Minimum context window required
            exclude: Model full_ids to exclude
            
        Returns:
            Best matching ModelSpec, or None if no match
        """
        exclude = exclude or set()
        candidates = []
        
        for full_id, spec in self._models.items():
            if not spec.enabled:
                continue
            if full_id in exclude:
                continue
            
            # Check circuit breaker
            cb = self._circuit_breakers.get(spec.provider_name)
            if cb and not cb.is_available():
                continue
            
            # Check capabilities
            if required_capabilities and not spec.capabilities.has_all(required_capabilities):
                continue
            
            # Check cost
            if max_cost_per_1k is not None:
                if spec.capabilities.cost_per_1k_input_tokens > max_cost_per_1k:
                    continue
            
            # Check context
            if min_context_tokens is not None:
                if spec.capabilities.max_context_tokens < min_context_tokens:
                    continue
            
            candidates.append(spec)
        
        if not candidates:
            return None
        
        # Sort by preference
        if prefer == "cheapest":
            candidates.sort(key=lambda m: m.capabilities.cost_per_1k_input_tokens)
        elif prefer == "fastest":
            candidates.sort(
                key=lambda m: m.capabilities.tokens_per_second or 0, reverse=True
            )
        elif prefer == "largest_context":
            candidates.sort(key=lambda m: m.capabilities.max_context_tokens, reverse=True)
        else:
            # Default: sort by priority
            candidates.sort(key=lambda m: m.priority)
        
        return candidates[0]

    def get_fallback_chain(self, task_type: str) -> list[ModelSpec]:
        """
        Get ordered fallback chain for a task type.
        
        Returns models in order of preference, filtering out
        those with open circuit breakers.
        """
        chain_ids = self._fallback_chains.get(task_type, [])
        chain = []
        
        for full_id in chain_ids:
            spec = self._models.get(full_id)
            if not spec or not spec.enabled:
                continue
            cb = self._circuit_breakers.get(spec.provider_name)
            if cb and not cb.is_available():
                continue
            chain.append(spec)
        
        return chain

    # ═══════════════════════════════════════════════════════════
    # CIRCUIT BREAKER
    # ═══════════════════════════════════════════════════════════

    def record_success(self, provider_name: str) -> None:
        """Record a successful call to a provider."""
        cb = self._circuit_breakers.get(provider_name)
        if cb:
            cb.record_success()

    def record_failure(self, provider_name: str) -> None:
        """Record a failed call to a provider."""
        cb = self._circuit_breakers.get(provider_name)
        if cb:
            cb.record_failure()
            if cb.state.value == "open":
                logger.warning(f"Circuit breaker OPENED for provider: {provider_name}")

    def get_circuit_state(self, provider_name: str) -> str:
        """Get circuit breaker state for a provider."""
        cb = self._circuit_breakers.get(provider_name)
        return cb.state.value if cb else "unknown"

    # ═══════════════════════════════════════════════════════════
    # COST TRACKING
    # ═══════════════════════════════════════════════════════════

    @property
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker

    def is_within_budget(self, estimated_cost: float = 0.0) -> bool:
        """Check if we can afford another call."""
        return self._cost_tracker.is_within_budget(estimated_cost)

    # ═══════════════════════════════════════════════════════════
    # HEALTH
    # ═══════════════════════════════════════════════════════════

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all providers."""
        results = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results

    def get_status(self) -> dict[str, Any]:
        """Get registry status summary."""
        return {
            "providers": {
                name: {
                    "models": len(provider._models),
                    "circuit_state": self.get_circuit_state(name),
                }
                for name, provider in self._providers.items()
            },
            "total_models": len(self._models),
            "enabled_models": sum(1 for m in self._models.values() if m.enabled),
            "daily_cost_usd": self._cost_tracker.get_daily_cost(),
            "monthly_cost_usd": self._cost_tracker.get_monthly_cost(),
            "usage": self._cost_tracker.get_usage_summary(),
        }
```

---

## 8. ModelRouter Redesign

```python
# src/llm/router.py

from __future__ import annotations

import logging
import time
from typing import AsyncIterator

from src.llm.providers.base import BaseLLMProvider
from src.llm.registry import ModelRegistry
from src.llm.types import (
    Capability,
    CostRecord,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    ModelSpec,
    TokenUsage,
)
from src.llm.errors import (
    LLMProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderModelError,
    ProviderCapacityError,
)

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes LLM requests to the best available provider/model.
    
    This is the ONLY class that agents interact with. It:
    1. Selects the best provider+model for a task
    2. Executes the request with fallback handling
    3. Tracks costs and circuit breakers
    4. Provides streaming and non-streaming interfaces
    
    Usage:
        router = ModelRouter(registry)
        
        # Simple generation
        response = await router.generate(
            prompt="Analyze BTC/USDT trend",
            task_type="news_analysis",
        )
        
        # With specific requirements
        response = await router.generate(
            prompt="...",
            task_type="complex_analysis",
            required_capabilities={Capability.REASONING, Capability.TOOL_USE},
            tools=[my_tool_def],
            prefer="cheapest",
        )
        
        # Streaming
        async for chunk in router.stream(prompt="...", task_type="daily_summary"):
            print(chunk.content, end="")
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry
        self._default_request_kwargs: dict = {
            "max_tokens": 2048,
            "temperature": 0.1,
        }

    # ═══════════════════════════════════════════════════════════
    # PRIMARY INTERFACE
    # ═══════════════════════════════════════════════════════════

    async def generate(
        self,
        prompt: str,
        task_type: str = "default",
        system_prompt: str | None = None,
        messages: list | None = None,
        required_capabilities: set[Capability] | None = None,
        prefer: str = "cheapest",
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: list | None = None,
        tool_choice: str | dict | None = None,
        json_mode: bool = False,
        response_format: dict | None = None,
        stop: list[str] | None = None,
        extra: dict | None = None,
    ) -> LLMResponse:
        """
        Generate a response with automatic model selection and fallback.
        
        Args:
            prompt: The user prompt (used if messages not provided)
            task_type: Task category for model routing (e.g. "news_analysis")
            system_prompt: Optional system message
            messages: Full message list (overrides prompt/system_prompt)
            required_capabilities: Capabilities the model must have
            prefer: Model selection preference ("cheapest", "fastest", "largest_context")
            max_tokens: Max output tokens
            temperature: Sampling temperature
            tools: Tool definitions for function calling
            tool_choice: Tool choice constraint
            json_mode: Request JSON output
            response_format: Response format constraint
            stop: Stop sequences
            extra: Provider-specific parameters
            
        Returns:
            LLMResponse from the selected provider
            
        Raises:
            LLMProviderError: All fallbacks exhausted
        """
        request = self._build_request(
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
            json_mode=json_mode,
            response_format=response_format,
            stop=stop,
            extra=extra,
        )
        
        # Get fallback chain
        chain = self._get_execution_chain(
            task_type=task_type,
            required_capabilities=required_capabilities,
            prefer=prefer,
        )
        
        if not chain:
            raise LLMProviderError(
                f"No available model for task_type={task_type}, "
                f"capabilities={required_capabilities}"
            )
        
        # Try each model in the chain
        last_error: Exception | None = None
        for spec in chain:
            provider = self.registry.get_provider(spec.provider_name)
            if not provider:
                continue
            
            request.model = spec.model_name
            
            try:
                response = await provider.generate(request)
                
                # Record success
                self.registry.record_success(spec.provider_name)
                self._record_cost(response, task_type)
                
                logger.info(
                    f"LLM call: provider={spec.provider_name} model={spec.model_name} "
                    f"task={task_type} tokens={response.usage.total_tokens} "
                    f"latency={response.latency_ms:.0f}ms"
                )
                
                return response
                
            except ProviderAuthError:
                # Auth errors are not retryable — skip this provider entirely
                logger.error(f"Auth error on {spec.provider_name}, skipping")
                self.registry.record_failure(spec.provider_name)
                continue
                
            except (ProviderRateLimitError, ProviderTimeoutError, ProviderCapacityError) as e:
                # Retryable errors — try next in chain
                logger.warning(f"Retryable error on {spec.provider_name}: {e}")
                self.registry.record_failure(spec.provider_name)
                last_error = e
                continue
                
            except ProviderModelError as e:
                # Model not available — skip this model
                logger.warning(f"Model error on {spec.full_id}: {e}")
                continue
                
            except Exception as e:
                # Unexpected error
                logger.error(f"Unexpected error on {spec.full_id}: {e}", exc_info=True)
                self.registry.record_failure(spec.provider_name)
                last_error = e
                continue
        
        raise LLMProviderError(
            f"All models exhausted for task_type={task_type}. "
            f"Last error: {last_error}"
        )

    async def stream(
        self,
        prompt: str,
        task_type: str = "default",
        system_prompt: str | None = None,
        messages: list | None = None,
        required_capabilities: set[Capability] | None = None,
        prefer: str = "cheapest",
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: list | None = None,
        stop: list[str] | None = None,
        extra: dict | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """
        Stream a response with automatic model selection.
        
        Same parameters as generate(). Yields LLMChunk objects.
        Falls back to non-streaming if streaming not supported.
        """
        request = self._build_request(
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            stop=stop,
            extra=extra,
        )
        
        chain = self._get_execution_chain(
            task_type=task_type,
            required_capabilities=required_capabilities | {Capability.STREAMING}
            if required_capabilities else {Capability.STREAMING},
            prefer=prefer,
        )
        
        if not chain:
            # Fall back to non-streaming if no streaming-capable model
            chain = self._get_execution_chain(
                task_type=task_type,
                required_capabilities=required_capabilities,
                prefer=prefer,
            )
            if chain:
                # Use generate() and yield as single chunk
                response = await self.generate(
                    prompt=prompt, task_type=task_type,
                    system_prompt=system_prompt, messages=messages,
                    required_capabilities=required_capabilities,
                    prefer=prefer, max_tokens=max_tokens,
                    temperature=temperature, tools=tools, stop=stop, extra=extra,
                )
                yield LLMChunk(
                    content=response.content,
                    model=response.model,
                    provider=response.provider,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                )
                return
            raise LLMProviderError("No available model for streaming")

        last_error = None
        for spec in chain:
            provider = self.registry.get_provider(spec.provider_name)
            if not provider:
                continue
            
            request.model = spec.model_name
            
            try:
                full_content = ""
                async for chunk in provider.stream(request):
                    full_content += chunk.content
                    yield chunk
                
                self.registry.record_success(spec.provider_name)
                return
                
            except (ProviderRateLimitError, ProviderTimeoutError, ProviderCapacityError) as e:
                logger.warning(f"Stream error on {spec.provider_name}: {e}")
                self.registry.record_failure(spec.provider_name)
                last_error = e
                continue
            except Exception as e:
                logger.error(f"Stream error on {spec.full_id}: {e}")
                self.registry.record_failure(spec.provider_name)
                last_error = e
                continue
        
        raise LLMProviderError(f"All streaming models exhausted. Last error: {last_error}")

    # ═══════════════════════════════════════════════════════════
    # ROUTING LOGIC
    # ═══════════════════════════════════════════════════════════

    def _get_execution_chain(
        self,
        task_type: str,
        required_capabilities: set[Capability] | None = None,
        prefer: str = "cheapest",
    ) -> list[ModelSpec]:
        """
        Get ordered list of models to try for a request.
        
        Priority:
        1. Registered fallback chain for task_type (if exists)
        2. find_model() with capability requirements
        3. Any available model
        """
        # Try registered fallback chain first
        chain = self.registry.get_fallback_chain(task_type)
        if chain:
            # Filter by capabilities
            if required_capabilities:
                chain = [
                    m for m in chain
                    if m.capabilities.has_all(required_capabilities)
                ]
            if chain:
                return chain
        
        # Use find_model for a single best match
        best = self.registry.find_model(
            required_capabilities=required_capabilities,
            prefer=prefer,
        )
        if best:
            return [best]
        
        # Last resort: any enabled model
        return self.registry.list_models(enabled_only=True)

    def _build_request(
        self,
        prompt: str,
        system_prompt: str | None = None,
        messages: list | None = None,
        **kwargs,
    ) -> LLMRequest:
        """Build an LLMRequest from convenience parameters."""
        from src.llm.types import Message, MessageRole
        
        if messages:
            msg_list = messages
        else:
            msg_list = []
            if system_prompt:
                msg_list.append(Message(role=MessageRole.SYSTEM, content=system_prompt))
            msg_list.append(Message(role=MessageRole.USER, content=prompt))
        
        # Merge defaults
        params = dict(self._default_request_kwargs)
        params.update({k: v for k, v in kwargs.items() if v is not None})
        
        return LLMRequest(messages=msg_list, model="", **params)  # model set by router

    def _record_cost(self, response: LLMResponse, task_type: str) -> None:
        """Record cost for a completed LLM call."""
        provider = self.registry.get_provider(response.provider)
        if not provider:
            return
        
        cost = provider.estimate_cost(
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=response.model,
        )
        
        self.registry.cost_tracker.record(CostRecord(
            timestamp=time.time(),
            provider=response.provider,
            model=response.model,
            task_type=task_type,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cost_usd=cost,
            latency_ms=response.latency_ms,
        ))

    # ═══════════════════════════════════════════════════════════
    # CONVENIENCE METHODS
    # ═══════════════════════════════════════════════════════════

    def get_status(self) -> dict:
        """Get router status including registry info."""
        return self.registry.get_status()
```

---

## 9. Token Counting

```python
# src/llm/tokens.py

"""
Token counting utilities.

Token counting is provider-specific. This module provides:
1. A unified interface via BaseLLMProvider.count_tokens()
2. A fallback approximation for providers without native counting
3. tiktoken integration for OpenAI-compatible models
"""

from __future__ import annotations


def estimate_tokens_approximate(text: str) -> int:
    """
    Approximate token count without a specific tokenizer.
    
    Rules of thumb:
    - English: ~4 chars per token
    - Chinese/Japanese: ~1.5 chars per token (UTF-8 multibyte)
    - Code: ~3 chars per token
    - Mixed: weighted average
    
    This is accurate to ±20% for most use cases.
    """
    if not text:
        return 0
    
    total_chars = len(text)
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = total_chars - ascii_chars - cjk_chars
    
    tokens = (ascii_chars / 4) + (cjk_chars / 1.5) + (other_chars / 3)
    return max(1, int(tokens))


def truncate_to_token_limit(text: str, max_tokens: int, count_fn=None) -> str:
    """
    Truncate text to fit within a token limit.
    
    Uses binary search for efficiency.
    """
    if count_fn is None:
        count_fn = estimate_tokens_approximate
    
    if count_fn(text) <= max_tokens:
        return text
    
    # Binary search for the right cutoff
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_fn(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    
    return text[:lo]
```

---

## 10. Configuration Schema

```yaml
# config/models.yaml
# ═══════════════════════════════════════════════════════════════
# TSAR LLM Model Configuration
# ═══════════════════════════════════════════════════════════════
# This is the SINGLE source of truth for all LLM model definitions.
# No model names appear in code — they are all defined here.
#
# Environment variables can be referenced as ${VAR_NAME}.
# ═══════════════════════════════════════════════════════════════

# ─── Provider Definitions ─────────────────────────────────────

providers:
  ollama:
    class: "src.llm.providers.ollama.OllamaProvider"
    config:
      base_url: "http://localhost:11434"
      timeout_s: 30
      keep_alive_s: 300

  openai:
    class: "src.llm.providers.openai.OpenAIProvider"
    config:
      api_key: "${OPENAI_API_KEY}"
      base_url: "https://api.openai.com/v1"
      timeout_s: 30
      max_retries: 2

  anthropic:
    class: "src.llm.providers.anthropic.AnthropicProvider"
    config:
      api_key: "${ANTHROPIC_API_KEY}"
      base_url: "https://api.anthropic.com"
      timeout_s: 30
      max_retries: 2
      default_max_tokens: 4096

  deepseek:
    class: "src.llm.providers.deepseek.DeepSeekProvider"
    config:
      api_key: "${DEEPSEEK_API_KEY}"
      base_url: "https://api.deepseek.com"
      timeout_s: 60
      max_retries: 3

  nvidia_nim:
    class: "src.llm.providers.openai.OpenAIProvider"   # NIM uses OpenAI-compatible API
    config:
      api_key: "${NVIDIA_API_KEY}"
      base_url: "https://integrate.api.nvidia.com/v1"
      timeout_s: 30
      max_retries: 2

# ─── Model Definitions ────────────────────────────────────────

models:
  # ── Local Models (Ollama) ───────────────────────────────────

  ollama/qwen2.5:7b:
    display_name: "Qwen 2.5 7B (Local)"
    enabled: true
    priority: 10
    tags: ["local", "free", "fast"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_json_mode: true
      max_context_tokens: 32768
      max_output_tokens: 4096
      cost_per_1k_input_tokens: 0.0
      cost_per_1k_output_tokens: 0.0
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - json_mode

  ollama/qwen2.5:32b:
    display_name: "Qwen 2.5 32B (Local)"
    enabled: false   # Enable if hardware supports it
    priority: 20
    tags: ["local", "free", "reasoning"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_json_mode: true
      supports_reasoning: true
      max_context_tokens: 32768
      max_output_tokens: 8192
      cost_per_1k_input_tokens: 0.0
      cost_per_1k_output_tokens: 0.0
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - json_mode
        - reasoning

  ollama/llama3.1:8b:
    display_name: "Llama 3.1 8B (Local)"
    enabled: true
    priority: 20
    tags: ["local", "free", "fast"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_json_mode: true
      max_context_tokens: 131072
      max_output_tokens: 4096
      cost_per_1k_input_tokens: 0.0
      cost_per_1k_output_tokens: 0.0
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - json_mode
        - long_context

  ollama/deepseek-r1:8b:
    display_name: "DeepSeek R1 8B (Local)"
    enabled: false   # Enable if hardware supports it
    priority: 30
    tags: ["local", "free", "reasoning"]
    capabilities:
      supports_streaming: true
      supports_tools: false
      supports_json_mode: true
      supports_reasoning: true
      max_context_tokens: 65536
      max_output_tokens: 8192
      cost_per_1k_input_tokens: 0.0
      cost_per_1k_output_tokens: 0.0
      capabilities:
        - text_generation
        - streaming
        - json_mode
        - reasoning

  # ── Embedding Models ────────────────────────────────────────

  ollama/all-minilm-l6-v2:
    display_name: "All-MiniLM-L6-v2 (Embeddings)"
    enabled: true
    priority: 5
    tags: ["local", "free", "embeddings"]
    capabilities:
      max_context_tokens: 512
      cost_per_1k_input_tokens: 0.0
      cost_per_1k_output_tokens: 0.0
      capabilities: []

  # ── Cloud Models ────────────────────────────────────────────

  deepseek/deepseek-chat:
    display_name: "DeepSeek Chat (Cloud)"
    enabled: true
    priority: 40
    tags: ["cloud", "free-tier", "fast"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_json_mode: true
      max_context_tokens: 65536
      max_output_tokens: 4096
      cost_per_1k_input_tokens: 0.00014
      cost_per_1k_output_tokens: 0.00028
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - json_mode
        - long_context

  deepseek/deepseek-reasoner:
    display_name: "DeepSeek Reasoner (Cloud)"
    enabled: true
    priority: 50
    tags: ["cloud", "free-tier", "reasoning"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_json_mode: true
      supports_reasoning: true
      max_context_tokens: 65536
      max_output_tokens: 8192
      cost_per_1k_input_tokens: 0.00055
      cost_per_1k_output_tokens: 0.00219
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - json_mode
        - reasoning
        - long_context

  nvidia_nim/deepseek-ai/deepseek-r1:
    display_name: "DeepSeek R1 via NVIDIA NIM (Free)"
    enabled: true
    priority: 45
    tags: ["cloud", "free-tier", "reasoning"]
    capabilities:
      supports_streaming: true
      supports_tools: false
      supports_json_mode: true
      supports_reasoning: true
      max_context_tokens: 65536
      max_output_tokens: 8192
      cost_per_1k_input_tokens: 0.0
      cost_per_1k_output_tokens: 0.0
      capabilities:
        - text_generation
        - streaming
        - reasoning
        - long_context

  openai/gpt-4o:
    display_name: "GPT-4o"
    enabled: false   # Paid — enable if budget allows
    priority: 100
    tags: ["cloud", "paid", "reasoning", "vision"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_json_mode: true
      supports_vision: true
      supports_reasoning: true
      max_context_tokens: 128000
      max_output_tokens: 16384
      cost_per_1k_input_tokens: 0.0025
      cost_per_1k_output_tokens: 0.010
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - json_mode
        - vision
        - long_context
        - reasoning

  anthropic/claude-3-5-sonnet-20241022:
    display_name: "Claude 3.5 Sonnet"
    enabled: false   # Paid — enable if budget allows
    priority: 100
    tags: ["cloud", "paid", "reasoning", "vision"]
    capabilities:
      supports_streaming: true
      supports_tools: true
      supports_vision: true
      supports_reasoning: true
      max_context_tokens: 200000
      max_output_tokens: 8192
      cost_per_1k_input_tokens: 0.003
      cost_per_1k_output_tokens: 0.015
      capabilities:
        - text_generation
        - streaming
        - tool_use
        - vision
        - long_context
        - reasoning

# ─── Task Routing ─────────────────────────────────────────────
# Maps task types to model selection preferences.
# Each task has:
#   primary: First model to try
#   fallback: Ordered list of fallback models
#   params: Default parameters for this task type

routing:
  news_analysis:
    description: "Analyze news articles for market sentiment"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "ollama/llama3.1:8b"
      - "deepseek/deepseek-chat"
    params:
      max_tokens: 1024
      temperature: 0.1
    required_capabilities:
      - text_generation

  signal_validation:
    description: "Validate technical analysis signals"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "ollama/llama3.1:8b"
    params:
      max_tokens: 512
      temperature: 0.0

  trade_journal:
    description: "Generate trade rationale and journal entries"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "deepseek/deepseek-chat"
      - "ollama/llama3.1:8b"
    params:
      max_tokens: 2048
      temperature: 0.3

  complex_analysis:
    description: "Multi-factor analysis requiring deep reasoning"
    primary: "deepseek/deepseek-reasoner"
    fallback:
      - "nvidia_nim/deepseek-ai/deepseek-r1"
      - "ollama/qwen2.5:32b"
      - "ollama/qwen2.5:7b"
    params:
      max_tokens: 4096
      temperature: 0.2
    required_capabilities:
      - reasoning

  pattern_matching:
    description: "Find similar historical patterns"
    primary: "ollama/all-minilm-l6-v2"
    fallback: []
    params:
      max_tokens: 0  # Embeddings only

  daily_summary:
    description: "End-of-day performance summary"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "ollama/llama3.1:8b"
    params:
      max_tokens: 2048
      temperature: 0.3

  risk_assessment:
    description: "Evaluate portfolio risk factors"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "ollama/llama3.1:8b"
    params:
      max_tokens: 1024
      temperature: 0.0

  trade_narrative:
    description: "Deep trade analysis and narrative (Trade Philosopher)"
    primary: "deepseek/deepseek-reasoner"
    fallback:
      - "nvidia_nim/deepseek-ai/deepseek-r1"
      - "deepseek/deepseek-chat"
      - "ollama/qwen2.5:7b"
    params:
      max_tokens: 4096
      temperature: 0.3
    required_capabilities:
      - reasoning

  strategy_synthesis:
    description: "LLM-based strategy hypothesis generation (Strategy Geneticist)"
    primary: "deepseek/deepseek-reasoner"
    fallback:
      - "nvidia_nim/deepseek-ai/deepseek-r1"
      - "ollama/qwen2.5:32b"
    params:
      max_tokens: 4096
      temperature: 0.5
    required_capabilities:
      - reasoning

  regime_explanation:
    description: "Human-readable regime change explanation"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "ollama/llama3.1:8b"
    params:
      max_tokens: 512
      temperature: 0.2

  anomaly_explanation:
    description: "Explain correlation anomalies (Market Cartographer)"
    primary: "ollama/qwen2.5:7b"
    fallback:
      - "ollama/llama3.1:8b"
    params:
      max_tokens: 512
      temperature: 0.2

# ─── Budget & Cost Control ────────────────────────────────────

budget:
  daily_limit_usd: 0.0        # 0 = unlimited (local models are free)
  monthly_limit_usd: 0.0      # 0 = unlimited
  alert_threshold_pct: 80     # Alert when 80% of budget used
  track_usage: true

# ─── Circuit Breaker Defaults ─────────────────────────────────

circuit_breaker:
  failure_threshold: 5        # Open after 5 consecutive failures
  recovery_timeout_s: 60      # Try again after 60 seconds

# ─── Defaults ─────────────────────────────────────────────────

defaults:
  max_tokens: 2048
  temperature: 0.1
  prefer: "cheapest"          # Model selection preference
```

---

## 11. Integration with Existing Agents

### Bootstrap / Initialization

```python
# src/llm/__init__.py

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from src.llm.registry import ModelRegistry
from src.llm.router import ModelRouter
from src.llm.providers.base import BaseLLMProvider
from src.llm.types import ModelSpec, ModelCapabilities, Capability

logger = logging.getLogger(__name__)

# Global singleton (initialized once at startup)
_router: ModelRouter | None = None
_registry: ModelRegistry | None = None


async def initialize_llm(config_path: str = "config/models.yaml") -> ModelRouter:
    """
    Initialize the LLM subsystem from configuration.
    
    Called once at application startup. Returns the global ModelRouter.
    """
    global _router, _registry
    
    config = _load_config(config_path)
    _registry = ModelRegistry()
    
    # Initialize providers
    for provider_name, provider_config in config.get("providers", {}).items():
        provider_class = _import_class(provider_config["class"])
        provider = provider_class(name=provider_name, config=provider_config.get("config", {}))
        await provider.initialize()
        _registry.register_provider(provider)
    
    # Register models
    for model_id, model_config in config.get("models", {}).items():
        parts = model_id.split("/", 1)
        if len(parts) != 2:
            logger.warning(f"Invalid model id (must be provider/model): {model_id}")
            continue
        
        provider_name, model_name = parts
        
        caps_config = model_config.get("capabilities", {})
        caps = ModelCapabilities(
            supports_streaming=caps_config.get("supports_streaming", False),
            supports_tools=caps_config.get("supports_tools", False),
            supports_json_mode=caps_config.get("supports_json_mode", False),
            supports_vision=caps_config.get("supports_vision", False),
            supports_reasoning=caps_config.get("supports_reasoning", False),
            max_context_tokens=caps_config.get("max_context_tokens", 4096),
            max_output_tokens=caps_config.get("max_output_tokens", 4096),
            cost_per_1k_input_tokens=caps_config.get("cost_per_1k_input_tokens", 0.0),
            cost_per_1k_output_tokens=caps_config.get("cost_per_1k_output_tokens", 0.0),
            capabilities={Capability(c) for c in caps_config.get("capabilities", [])},
        )
        
        spec = ModelSpec(
            provider_name=provider_name,
            model_name=model_name,
            display_name=model_config.get("display_name", model_name),
            capabilities=caps,
            enabled=model_config.get("enabled", True),
            priority=model_config.get("priority", 100),
            tags=model_config.get("tags", []),
        )
        
        _registry.register_model(provider_name, model_name, spec)
    
    # Register fallback chains from routing config
    for task_type, routing_config in config.get("routing", {}).items():
        chain = [routing_config.get("primary", [])] + routing_config.get("fallback", [])
        chain = [m for m in chain if m]  # Remove empty entries
        _registry.register_fallback_chain(task_type, chain)
    
    # Configure cost tracker
    budget = config.get("budget", {})
    _registry.cost_tracker.daily_budget_usd = budget.get("daily_limit_usd", 0.0)
    _registry.cost_tracker.monthly_budget_usd = budget.get("monthly_limit_usd", 0.0)
    
    _router = ModelRouter(_registry)
    
    # Health check
    health = await _registry.health_check_all()
    for provider_name, healthy in health.items():
        status = "✓" if healthy else "✗"
        logger.info(f"Provider {provider_name}: {status}")
    
    logger.info(
        f"LLM initialized: {len(_registry.list_providers())} providers, "
        f"{len(_registry.list_models())} models"
    )
    
    return _router


def get_router() -> ModelRouter:
    """Get the global ModelRouter. Must call initialize_llm() first."""
    if _router is None:
        raise RuntimeError("LLM not initialized. Call initialize_llm() first.")
    return _router


def get_registry() -> ModelRegistry:
    """Get the global ModelRegistry."""
    if _registry is None:
        raise RuntimeError("LLM not initialized. Call initialize_llm() first.")
    return _registry


async def shutdown_llm() -> None:
    """Shutdown all providers."""
    if _registry:
        for provider in _registry.list_providers():
            await provider.shutdown()
        logger.info("LLM shutdown complete")


def _load_config(path: str) -> dict:
    """Load and resolve YAML config with env var substitution."""
    config_path = Path(path)
    if not config_path.exists():
        logger.warning(f"Config not found: {path}, using defaults")
        return {}
    
    with open(config_path) as f:
        raw = f.read()
    
    # Resolve ${VAR_NAME} references
    import re
    def resolve_env(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    
    resolved = re.sub(r'\$\{(\w+)\}', resolve_env, raw)
    return yaml.safe_load(resolved) or {}


def _import_class(class_path: str):
    """Import a class from a dotted path."""
    module_path, class_name = class_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
```

### Agent Usage Examples

```python
# ─── Regime Detector ──────────────────────────────────────────

class RegimeDetectorAgent:
    async def _generate_explanation(self, regime: RegimeReport) -> str:
        """Use LLM to explain regime change (T2 task)."""
        from src.llm import get_router
        
        router = get_router()
        response = await router.generate(
            prompt=f"Explain this market regime change concisely:\n"
                   f"From: {regime.previous_regime_label}\n"
                   f"To: {regime.regime_label}\n"
                   f"Confidence: {regime.confidence:.2f}\n"
                   f"Dimension confidences: {regime.dimension_confidences}",
            task_type="regime_explanation",
            max_tokens=512,
            temperature=0.2,
        )
        return response.content


# ─── Trade Philosopher ────────────────────────────────────────

class TradePhilosopherAgent:
    async def _deep_analysis(self, trade: TradeData) -> str:
        """Deep reasoning about a significant trade (T3 task)."""
        from src.llm import get_router
        
        router = get_router()
        response = await router.generate(
            prompt=self._build_trade_analysis_prompt(trade),
            task_type="trade_narrative",
            required_capabilities={Capability.REASONING},
            max_tokens=4096,
            temperature=0.3,
        )
        return response.content
    
    async def _quick_summary(self, trade: TradeData) -> str:
        """Quick summary for routine trades (T2 task)."""
        from src.llm import get_router
        
        router = get_router()
        response = await router.generate(
            prompt=f"Summarize this trade in 2 sentences: {trade.summary}",
            task_type="daily_summary",
            max_tokens=256,
        )
        return response.content


# ─── Strategy Geneticist ─────────────────────────────────────

class StrategyGeneticistAgent:
    async def _synthesize_strategy(self, context: dict) -> str:
        """LLM proposes new strategy hypotheses (T3 task)."""
        from src.llm import get_router
        
        router = get_router()
        response = await router.generate(
            prompt=self._build_synthesis_prompt(context),
            task_type="strategy_synthesis",
            required_capabilities={Capability.REASONING},
            max_tokens=4096,
            temperature=0.5,
        )
        return response.content
```

---

## 12. Testing Strategy

```python
# tests/unit/llm/test_router.py

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.llm.router import ModelRouter
from src.llm.registry import ModelRegistry
from src.llm.types import (
    Capability,
    LLMResponse,
    ModelCapabilities,
    ModelSpec,
    TokenUsage,
)
from src.llm.providers.base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    """Mock provider for testing."""
    
    def __init__(self, name: str, models: dict, healthy: bool = True, fail_on: str = None):
        super().__init__(name, {})
        self._healthy = healthy
        self._fail_on = fail_on
        self._call_count = 0
        for model_name, caps in models.items():
            self._models[model_name] = ModelSpec(
                provider_name=name,
                model_name=model_name,
                capabilities=caps,
            )
    
    async def initialize(self): pass
    async def shutdown(self): pass
    
    async def generate(self, request):
        self._call_count += 1
        if self._fail_on == "generate":
            raise Exception(f"Mock failure on {self.name}")
        return LLMResponse(
            content=f"Response from {self.name}/{request.model}",
            model=request.model,
            provider=self.name,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            finish_reason="stop",
            latency_ms=100.0,
        )
    
    async def stream(self, request):
        yield LLMChunk(content="chunk1", model=request.model, provider=self.name)
        yield LLMChunk(content="chunk2", model=request.model, provider=self.name,
                       finish_reason="stop")
    
    def count_tokens(self, text, model=None):
        return len(text) // 4
    
    def get_capabilities(self, model):
        return self._models.get(model, ModelCapabilities())
    
    async def health_check(self):
        return self._healthy


@pytest.fixture
def registry():
    reg = ModelRegistry()
    
    # Local provider (free)
    local = MockProvider("ollama", {
        "qwen2.5:7b": ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            cost_per_1k_input_tokens=0.0,
            capabilities={Capability.TEXT_GENERATION, Capability.STREAMING, Capability.TOOL_USE},
        ),
    })
    reg.register_provider(local)
    reg.register_model("ollama", "qwen2.5:7b", local._models["qwen2.5:7b"])
    
    # Cloud provider (paid)
    cloud = MockProvider("openai", {
        "gpt-4o": ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
            cost_per_1k_input_tokens=0.0025,
            capabilities={
                Capability.TEXT_GENERATION, Capability.STREAMING,
                Capability.TOOL_USE, Capability.VISION,
            },
        ),
    })
    reg.register_provider(cloud)
    reg.register_model("openai", "gpt-4o", cloud._models["gpt-4o"])
    
    # Fallback chain
    reg.register_fallback_chain("news_analysis", [
        "ollama/qwen2.5:7b",
        "openai/gpt-4o",
    ])
    
    return reg


@pytest.fixture
def router(registry):
    return ModelRouter(registry)


class TestModelRouter:
    async def test_generate_uses_task_fallback_chain(self, router):
        response = await router.generate("test", task_type="news_analysis")
        assert response.provider == "ollama"
        assert response.model == "qwen2.5:7b"
    
    async def test_generate_falls_back_on_failure(self, router, registry):
        # Make ollama fail
        ollama = registry.get_provider("ollama")
        ollama._fail_on = "generate"
        
        response = await router.generate("test", task_type="news_analysis")
        assert response.provider == "openai"
        assert response.model == "gpt-4o"
    
    async def test_generate_selects_cheapest(self, router):
        response = await router.generate("test", prefer="cheapest")
        assert response.provider == "ollama"  # Free
    
    async def test_generate_respects_capabilities(self, router, registry):
        response = await router.generate(
            "test",
            required_capabilities={Capability.VISION},
        )
        assert response.provider == "openai"  # Only openai has vision
    
    async def test_generate_raises_when_no_model_available(self, router, registry):
        with pytest.raises(Exception, match="No available model"):
            await router.generate(
                "test",
                required_capabilities={Capability.VISION},
                # But openai is broken
            )
            # This would need openai to also be broken
    
    async def test_circuit_breaker_opens_after_failures(self, router, registry):
        ollama = registry.get_provider("ollama")
        ollama._fail_on = "generate"
        
        # Trigger 5 failures
        for _ in range(5):
            try:
                await router.generate("test", task_type="news_analysis")
            except:
                pass
        
        assert registry.get_circuit_state("ollama") == "open"
    
    async def test_cost_tracking(self, router, registry):
        await router.generate("test", task_type="news_analysis")
        assert registry.cost_tracker.get_daily_cost("ollama") == 0.0  # Free
        assert registry.cost_tracker.get_daily_cost("openai") == 0.0  # Not used


class TestModelRegistry:
    def test_find_model_cheapest(self, registry):
        model = registry.find_model(prefer="cheapest")
        assert model.provider_name == "ollama"
    
    def test_find_model_with_capabilities(self, registry):
        model = registry.find_model(
            required_capabilities={Capability.VISION},
        )
        assert model.provider_name == "openai"
    
    def test_get_fallback_chain(self, registry):
        chain = registry.get_fallback_chain("news_analysis")
        assert len(chain) == 2
        assert chain[0].provider_name == "ollama"
        assert chain[1].provider_name == "openai"
    
    def test_get_fallback_chain_filters_disabled(self, registry):
        registry._models["ollama/qwen2.5:7b"].enabled = False
        chain = registry.get_fallback_chain("news_analysis")
        assert len(chain) == 1
        assert chain[0].provider_name == "openai"
```

---

## 13. Migration Plan

### Phase 1: Parallel Implementation (Week 1)

| Step | Action | Files |
|------|--------|-------|
| 1.1 | Create `src/llm/types.py` with all data types | `src/llm/types.py` |
| 1.2 | Create `src/llm/errors.py` with exception hierarchy | `src/llm/errors.py` |
| 1.3 | Create `src/llm/providers/base.py` | `src/llm/providers/base.py` |
| 1.4 | Create `src/llm/providers/ollama.py` | `src/llm/providers/ollama.py` |
| 1.5 | Create `src/llm/providers/openai.py` | `src/llm/providers/openai.py` |
| 1.6 | Create `src/llm/providers/anthropic.py` | `src/llm/providers/anthropic.py` |
| 1.7 | Create `src/llm/providers/deepseek.py` | `src/llm/providers/deepseek.py` |
| 1.8 | Create `src/llm/registry.py` | `src/llm/registry.py` |
| 1.9 | Create `src/llm/tokens.py` | `src/llm/tokens.py` |
| 1.10 | Create `config/models.yaml` | `config/models.yaml` |
| 1.11 | Create `src/llm/__init__.py` (bootstrap) | `src/llm/__init__.py` |

### Phase 2: Router Replacement (Week 2)

| Step | Action | Files |
|------|--------|-------|
| 2.1 | Rewrite `src/llm/router.py` (replace old ModelRouter) | `src/llm/router.py` |
| 2.2 | Update `src/llm/analysis.py` to use new router | `src/llm/analysis.py` |
| 2.3 | Update `src/llm/validator.py` to use new router | `src/llm/validator.py` |
| 2.4 | Update `src/llm/journal.py` to use new router | `src/llm/journal.py` |
| 2.5 | Update `src/llm/cache.py` (key on model full_id) | `src/llm/cache.py` |
| 2.6 | Update `src/core/engine.py` bootstrap | `src/core/engine.py` |

### Phase 3: Agent Migration (Week 3)

| Step | Action | Files |
|------|--------|-------|
| 3.1 | Update all agent files to use `get_router()` | All agent files |
| 3.2 | Remove LiteLLM dependency | `pyproject.toml`, `requirements.txt` |
| 3.3 | Remove hardcoded model names from all files | Grep & replace |
| 3.4 | Update `config/model_routing.yaml` → redirect to `config/models.yaml` | Config files |
| 3.5 | Update `config/default.yaml` LLM section | `config/default.yaml` |

### Phase 4: Testing & Validation (Week 4)

| Step | Action | Files |
|------|--------|-------|
| 4.1 | Unit tests for all providers | `tests/unit/llm/test_providers.py` |
| 4.2 | Unit tests for registry and router | `tests/unit/llm/test_registry.py`, `test_router.py` |
| 4.3 | Integration test: full agent → LLM → response | `tests/integration/test_llm_integration.py` |
| 4.4 | Load test: concurrent requests from multiple agents | `tests/integration/test_llm_load.py` |
| 4.5 | Verify Prometheus metrics still work | `tests/integration/test_metrics.py` |

### Backward Compatibility

During migration, the old `ModelRouter` is kept as `src/llm/router_legacy.py` with a deprecation warning. Agents that haven't been migrated yet can still use it. Once all agents are migrated, the legacy file is deleted.

---

## 14. File Layout

```
src/llm/
├── __init__.py                 # Bootstrap: initialize_llm(), get_router(), shutdown_llm()
├── types.py                    # All data types (ModelSpec, LLMRequest, LLMResponse, etc.)
├── errors.py                   # Exception hierarchy (ProviderError, RateLimitError, etc.)
├── registry.py                 # ModelRegistry (model catalog, fallback chains, circuit breakers)
├── router.py                   # ModelRouter (request routing, fallback execution)
├── tokens.py                   # Token counting utilities
├── cache.py                    # Response caching (unchanged, updated key format)
├── prompts.py                  # Prompt templates (unchanged)
├── analysis.py                 # News & sentiment analysis (updated to use router)
├── validator.py                # Signal validation (updated to use router)
├── journal.py                  # Trade journaling (updated to use router)
├── router_legacy.py            # Old router (deprecated, removed in Phase 4)
│
└── providers/                  # Provider implementations
    ├── __init__.py             # Provider registry
    ├── base.py                 # BaseLLMProvider abstract class
    ├── ollama.py               # OllamaProvider
    ├── openai.py               # OpenAIProvider (also handles NVIDIA NIM)
    ├── anthropic.py            # AnthropicProvider
    └── deepseek.py             # DeepSeekProvider

config/
└── models.yaml                 # NEW: All model definitions, routing, budget

config/model_routing.yaml       # DEPRECATED: Redirects to models.yaml (Phase 3.4)
```

---

## Appendix A: Error Hierarchy

```python
# src/llm/errors.py

class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""
    pass

class ProviderAuthError(LLMProviderError):
    """Authentication failed. Not retryable."""
    pass

class ProviderRateLimitError(LLMProviderError):
    """Rate limit hit. Retryable after backoff."""
    pass

class ProviderTimeoutError(LLMProviderError):
    """Request timed out. Retryable."""
    pass

class ProviderModelError(LLMProviderError):
    """Model not found or unavailable on this provider."""
    pass

class ProviderCapacityError(LLMProviderError):
    """Provider at capacity. Retryable."""
    pass

class BudgetExceededError(LLMProviderError):
    """Daily/monthly budget exceeded."""
    pass
```

---

## Appendix B: Prometheus Metrics Updates

```python
# Additions to src/monitoring/metrics.py

from prometheus_client import Counter, Histogram, Gauge

# LLM Provider Metrics (provider-aware)
llm_requests_by_provider = Counter(
    "tsar_llm_requests_total",
    "LLM requests by provider and model",
    ["provider", "model", "task_type", "status"],
)

llm_latency_by_provider = Histogram(
    "tsar_llm_latency_seconds",
    "LLM request latency by provider",
    ["provider", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

llm_tokens_by_provider = Counter(
    "tsar_llm_tokens_total",
    "LLM tokens consumed by provider",
    ["provider", "model", "direction"],  # direction: input/output
)

llm_cost_by_provider = Counter(
    "tsar_llm_cost_usd_total",
    "LLM cost in USD by provider",
    ["provider", "model"],
)

llm_circuit_breaker_state = Gauge(
    "tsar_llm_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["provider"],
)

llm_budget_remaining = Gauge(
    "tsar_llm_budget_remaining_usd",
    "Remaining LLM budget in USD",
    ["period"],  # period: daily/monthly
)
```

---

## Appendix C: Relationship to Existing LiteLLM Dependency

| Aspect | Current (LiteLLM) | New (Abstraction Layer) |
|--------|-------------------|------------------------|
| Model routing | LiteLLM's model name parsing | `ModelRouter` + `ModelRegistry` |
| Provider abstraction | LiteLLM's unified API | `BaseLLMProvider` ABC |
| Fallback chains | LiteLLM's `fallbacks` param | `ModelRegistry.get_fallback_chain()` |
| Token counting | LiteLLM + tiktoken | `BaseLLMProvider.count_tokens()` |
| Cost tracking | LiteLLM's `cost_calculator` | `CostTracker` class |
| Streaming | LiteLLM's `stream=True` | `BaseLLMProvider.stream()` |
| Caching | LiteLLM cache | Existing `src/llm/cache.py` (unchanged) |

**After migration:** Remove `litellm` from `pyproject.toml` and `requirements.txt`. The `openai` package is kept (used by `OpenAIProvider` and as base for `DeepSeekProvider`). Add `anthropic` package for `AnthropicProvider`.

Updated dependencies:
```toml
# REMOVE
"litellm>=1.30,<2.0",

# ADD
"anthropic>=0.34,<1.0",

# KEEP
"openai>=1.12,<2.0",
"tiktoken>=0.6,<1.0",
"httpx>=0.27,<1.0",
```

---

*Specification complete. Ready for implementation.*
*Total new files: 11 | Modified files: ~15 | Removed: 1 (LiteLLM)*
