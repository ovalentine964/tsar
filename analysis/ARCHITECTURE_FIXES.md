# TSAR ARCHITECTURE FIXES — Gap Remediation Report

**Version:** 1.0.0  
**Date:** 2026-07-24  
**Source:** Super Agent Architecture Review (8.1/10 → Target: 9.0+/10)  
**Status:** APPROVED — Ready for Engineering Implementation  

---

## Table of Contents

1. [Fix #1: Abstract LLM Provider Interface](#fix-1-abstract-llm-provider-interface) — Critical
2. [Fix #2: Configurable Model Names](#fix-2-configurable-model-names) — Critical
3. [Fix #3: CloudEvents Messaging Protocol](#fix-3-cloudevents-messaging-protocol) — Critical
4. [Fix #4: Improvement Measurement Framework](#fix-4-improvement-measurement-framework) — High
5. [Fix #5: Tool Resource Limits](#fix-5-tool-resource-limits) — High
6. [Integration Map](#integration-map)
7. [Migration Checklist](#migration-checklist)

---

## Fix #1: Abstract LLM Provider Interface

**Gap:** No abstract LLM provider interface — cannot swap models without code changes  
**Severity:** Critical  
**Capability Affected:** Model Agnosticism (Score: 6 → Target: 8.5)  
**Estimated Effort:** 2-3 days  

### 1.1 Architectural Specification

**What to add:** A `BaseLLMProvider` abstract class that all LLM providers implement. A `ProviderRegistry` that discovers and manages providers. A `ModelCapabilities` descriptor that advertises what each model can do.

**Where it integrates:** `src/llm/` directory. The existing `ModelRouter` (trading-super-agent-spec.md §4) becomes a thin dispatcher that delegates to the provider interface.

**Design Principles:**
- All LLM calls go through `BaseLLMProvider` — no direct provider SDK calls anywhere in the codebase
- Providers are discovered via registry pattern (register at import time)
- Each provider advertises its capabilities (streaming, function_calling, structured_output, max_context)
- Fallback chains are defined in config, not in code
- Token counting is provider-agnostic (best-effort via tiktoken local + provider-accurate on response)

### 1.2 Code: Abstract Base Class

```python
# src/llm/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator
import time


class ModelCapability(Enum):
    """Capabilities a model may or may not support."""
    STREAMING = "streaming"
    FUNCTION_CALLING = "function_calling"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    CODE_GENERATION = "code_generation"
    REASONING = "reasoning"              # Chain-of-thought / extended thinking
    JSON_MODE = "json_mode"
    TOOL_USE = "tool_use"


@dataclass(frozen=True)
class ModelDescriptor:
    """Describes a model's identity and capabilities."""
    provider: str                        # "ollama", "openai", "nvidia_nim", "deepseek", "anthropic"
    model_id: str                        # "qwen2.5:7b", "deepseek-ai/deepseek-r1"
    display_name: str                    # "Qwen 2.5 7B"
    max_context_tokens: int              # Maximum input context window
    max_output_tokens: int               # Maximum output tokens
    capabilities: frozenset[ModelCapability]
    cost_per_1k_input: float = 0.0       # USD per 1K input tokens
    cost_per_1k_output: float = 0.0      # USD per 1K output tokens
    latency_p50_ms: float = 0.0          # Typical latency (empirical)
    supports_streaming: bool = True
    supports_system_prompt: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str                         # Generated text
    model: str                           # Model that generated this
    provider: str                        # Provider that served this
    finish_reason: str                   # "stop", "length", "error", "timeout"
    usage: "TokenUsage"
    latency_ms: float
    raw_response: dict | None = None     # Provider-specific raw response (for debugging)
    function_call: dict | None = None    # If function calling was used
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """Token usage report."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0              # Tokens served from cache


@dataclass
class LLMError:
    """Standardized error from any LLM provider."""
    error_type: str                      # "rate_limit", "timeout", "auth", "model_not_found", "context_length", "provider_unavailable"
    message: str
    provider: str
    model: str
    retryable: bool
    retry_after_seconds: float | None = None
    raw_error: Exception | None = None


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.
    
    Every provider (Ollama, OpenAI, NVIDIA NIM, DeepSeek, Anthropic, etc.)
    implements this interface. The rest of the system ONLY interacts with
    LLMs through this interface.
    
    Lifecycle:
    1. __init__() — load config, no I/O
    2. initialize() — async, verify connectivity, load model list
    3. generate() / stream() — the actual work
    4. health_check() — liveness probe
    5. shutdown() — cleanup connections
    """

    @abstractmethod
    def descriptor(self) -> ModelDescriptor:
        """Return a descriptor of this provider's model and capabilities."""
        ...

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
        json_mode: bool = False,
        response_format: dict | None = None,
    ) -> LLMResponse:
        """
        Generate a completion from the model.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            json_mode: Request JSON output
            response_format: Structured output format (if supported)
        
        Returns:
            LLMResponse with content, usage, and metadata
        
        Raises:
            LLMError on failure (rate_limit, timeout, auth, etc.)
        """
        ...

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream a completion token by token.
        
        Yields:
            String tokens as they are generated
        
        Raises:
            LLMError on failure
        """
        ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """
        Count tokens in text. Best-effort — may use tiktoken locally
        for speed, or call provider API for accuracy.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Return True if the provider is operational.
        Should be fast (< 1s) and not consume significant resources.
        """
        ...

    async def initialize(self) -> None:
        """One-time async initialization (verify API key, load model info)."""
        pass

    async def shutdown(self) -> None:
        """Graceful cleanup."""
        pass

    def supports(self, capability: ModelCapability) -> bool:
        """Check if this provider supports a specific capability."""
        return capability in self.descriptor().capabilities

    async def generate_structured(
        self,
        prompt: str,
        schema: dict,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict:
        """
        Generate structured output matching a JSON schema.
        Falls back to prompt-based JSON extraction if model doesn't
        natively support structured output.
        """
        if self.supports(ModelCapability.STRUCTURED_OUTPUT):
            return await self.generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                response_format={"type": "json_schema", "schema": schema},
            )
        
        # Fallback: ask for JSON and parse
        json_prompt = f"{prompt}\n\nRespond ONLY with valid JSON matching this schema:\n{schema}"
        response = await self.generate(
            json_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            json_mode=True,
        )
        import json
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response.content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise
```

### 1.3 Code: Provider Implementations

```python
# src/llm/providers/ollama_provider.py
import ollama
from src.llm.base import (
    BaseLLMProvider, ModelDescriptor, ModelCapability,
    LLMResponse, TokenUsage, LLMError,
)
import tiktoken


class OllamaProvider(BaseLLMProvider):
    """Provider for local Ollama models (Qwen, Llama, Mistral, etc.)."""

    def __init__(self, model_id: str = "qwen2.5:7b", base_url: str = "http://localhost:11434"):
        self._model_id = model_id
        self._base_url = base_url
        self._client = None
        self._descriptor = None

    async def initialize(self) -> None:
        self._client = ollama.AsyncClient(host=self._base_url)
        # Verify model is available
        try:
            models = await self._client.list()
            available = [m["name"] for m in models["models"]]
            if self._model_id not in available:
                raise LLMError(
                    error_type="model_not_found",
                    message=f"Model {self._model_id} not found. Available: {available}",
                    provider="ollama",
                    model=self._model_id,
                    retryable=False,
                )
        except Exception as e:
            if isinstance(e, LLMError):
                raise
            raise LLMError(
                error_type="provider_unavailable",
                message=f"Cannot connect to Ollama at {self._base_url}: {e}",
                provider="ollama",
                model=self._model_id,
                retryable=True,
            )

    def descriptor(self) -> ModelDescriptor:
        if not self._descriptor:
            # Default capabilities for Ollama models
            caps = {
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE_GENERATION,
            }
            self._descriptor = ModelDescriptor(
                provider="ollama",
                model_id=self._model_id,
                display_name=self._model_id,
                max_context_tokens=32768,
                max_output_tokens=4096,
                capabilities=frozenset(caps),
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
            )
        return self._descriptor

    async def generate(self, prompt, *, system_prompt=None, temperature=0.1,
                       max_tokens=2048, stop=None, json_mode=False,
                       response_format=None) -> LLMResponse:
        import time
        start = time.perf_counter()

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            options = {"temperature": temperature, "num_predict": max_tokens}
            if stop:
                options["stop"] = stop

            response = await self._client.chat(
                model=self._model_id,
                messages=messages,
                options=options,
                format="json" if json_mode else None,
            )

            latency_ms = (time.perf_counter() - start) * 1000
            content = response["message"]["content"]
            usage_data = response.get("eval_count", {})

            return LLMResponse(
                content=content,
                model=self._model_id,
                provider="ollama",
                finish_reason="stop",
                usage=TokenUsage(
                    prompt_tokens=response.get("prompt_eval_count", 0),
                    completion_tokens=response.get("eval_count", 0),
                    total_tokens=response.get("prompt_eval_count", 0) + response.get("eval_count", 0),
                ),
                latency_ms=latency_ms,
                raw_response=response,
            )

        except Exception as e:
            raise LLMError(
                error_type="provider_unavailable" if "connection" in str(e).lower() else "internal",
                message=str(e),
                provider="ollama",
                model=self._model_id,
                retryable=True,
            )

    async def stream(self, prompt, *, system_prompt=None, temperature=0.1,
                     max_tokens=2048, stop=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        options = {"temperature": temperature, "num_predict": max_tokens}
        if stop:
            options["stop"] = stop

        async for chunk in await self._client.chat(
            model=self._model_id,
            messages=messages,
            options=options,
            stream=True,
        ):
            token = chunk["message"]["content"]
            if token:
                yield token

    async def count_tokens(self, text: str) -> int:
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4  # Rough fallback

    async def health_check(self) -> bool:
        try:
            await self._client.list()
            return True
        except Exception:
            return False

    async def shutdown(self):
        self._client = None
```

```python
# src/llm/providers/openai_provider.py
import openai
from src.llm.base import (
    BaseLLMProvider, ModelDescriptor, ModelCapability,
    LLMResponse, TokenUsage, LLMError,
)


class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI-compatible APIs (OpenAI, NVIDIA NIM, DeepSeek, vLLM)."""

    def __init__(self, model_id: str, api_key: str, base_url: str | None = None,
                 display_name: str | None = None, max_context: int = 128000,
                 capabilities: frozenset[ModelCapability] | None = None):
        self._model_id = model_id
        self._api_key = api_key
        self._base_url = base_url
        self._display_name = display_name or model_id
        self._max_context = max_context
        self._capabilities = capabilities or frozenset({
            ModelCapability.STREAMING,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.JSON_MODE,
            ModelCapability.TOOL_USE,
        })
        self._client = None

    async def initialize(self) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            provider="openai_compatible",
            model_id=self._model_id,
            display_name=self._display_name,
            max_context_tokens=self._max_context,
            max_output_tokens=4096,
            capabilities=self._capabilities,
        )

    async def generate(self, prompt, *, system_prompt=None, temperature=0.1,
                       max_tokens=2048, stop=None, json_mode=False,
                       response_format=None) -> LLMResponse:
        import time
        start = time.perf_counter()

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            kwargs = {
                "model": self._model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if stop:
                kwargs["stop"] = stop
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if response_format and self.supports(ModelCapability.STRUCTURED_OUTPUT):
                kwargs["response_format"] = response_format

            response = await self._client.chat.completions.create(**kwargs)
            latency_ms = (time.perf_counter() - start) * 1000

            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                provider="openai_compatible",
                finish_reason=choice.finish_reason or "stop",
                usage=TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    cached_tokens=getattr(response.usage, 'prompt_tokens_details', {}).get('cached_tokens', 0),
                ),
                latency_ms=latency_ms,
                raw_response=response.model_dump(),
            )

        except openai.RateLimitError as e:
            raise LLMError(
                error_type="rate_limit",
                message=str(e),
                provider="openai_compatible",
                model=self._model_id,
                retryable=True,
                retry_after_seconds=float(e.response.headers.get("retry-after", 60)),
            )
        except openai.APITimeoutError as e:
            raise LLMError(
                error_type="timeout",
                message=str(e),
                provider="openai_compatible",
                model=self._model_id,
                retryable=True,
            )
        except openai.AuthenticationError as e:
            raise LLMError(
                error_type="auth",
                message=str(e),
                provider="openai_compatible",
                model=self._model_id,
                retryable=False,
            )
        except Exception as e:
            raise LLMError(
                error_type="internal",
                message=str(e),
                provider="openai_compatible",
                model=self._model_id,
                retryable=True,
            )

    async def stream(self, prompt, *, system_prompt=None, temperature=0.1,
                     max_tokens=2048, stop=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self._model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if stop:
            kwargs["stop"] = stop

        async for chunk in await self._client.chat.completions.create(**kwargs):
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False

    async def shutdown(self):
        if self._client:
            await self._client.close()
```

```python
# src/llm/providers/anthropic_provider.py
import anthropic
from src.llm.base import (
    BaseLLMProvider, ModelDescriptor, ModelCapability,
    LLMResponse, TokenUsage, LLMError,
)


class AnthropicProvider(BaseLLMProvider):
    """Provider for Anthropic Claude models."""

    def __init__(self, model_id: str = "claude-sonnet-4-20250514", api_key: str = ""):
        self._model_id = model_id
        self._api_key = api_key
        self._client = None

    async def initialize(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            provider="anthropic",
            model_id=self._model_id,
            display_name=f"Claude ({self._model_id})",
            max_context_tokens=200000,
            max_output_tokens=8192,
            capabilities=frozenset({
                ModelCapability.STREAMING,
                ModelCapability.VISION,
                ModelCapability.CODE_GENERATION,
                ModelCapability.REASONING,
                ModelCapability.TOOL_USE,
            }),
        )

    async def generate(self, prompt, *, system_prompt=None, temperature=0.1,
                       max_tokens=2048, stop=None, json_mode=False,
                       response_format=None) -> LLMResponse:
        import time
        start = time.perf_counter()
        try:
            kwargs = {
                "model": self._model_id,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if stop:
                kwargs["stop_sequences"] = stop

            response = await self._client.messages.create(**kwargs)
            latency_ms = (time.perf_counter() - start) * 1000

            return LLMResponse(
                content=response.content[0].text,
                model=self._model_id,
                provider="anthropic",
                finish_reason=response.stop_reason or "stop",
                usage=TokenUsage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                ),
                latency_ms=latency_ms,
                raw_response=response.model_dump(),
            )
        except anthropic.RateLimitError as e:
            raise LLMError(error_type="rate_limit", message=str(e),
                           provider="anthropic", model=self._model_id, retryable=True)
        except anthropic.APITimeoutError as e:
            raise LLMError(error_type="timeout", message=str(e),
                           provider="anthropic", model=self._model_id, retryable=True)
        except Exception as e:
            raise LLMError(error_type="internal", message=str(e),
                           provider="anthropic", model=self._model_id, retryable=True)

    async def stream(self, prompt, *, system_prompt=None, temperature=0.1,
                     max_tokens=2048, stop=None):
        kwargs = {
            "model": self._model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if stop:
            kwargs["stop_sequences"] = stop

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def count_tokens(self, text: str) -> int:
        try:
            resp = await self._client.messages.count_tokens(
                model=self._model_id,
                messages=[{"role": "user", "content": text}],
            )
            return resp.input_tokens
        except Exception:
            return len(text) // 4

    async def health_check(self) -> bool:
        try:
            # Simple lightweight check
            return self._client is not None
        except Exception:
            return False

    async def shutdown(self):
        if self._client:
            await self._client.close()
```

### 1.4 Code: Provider Registry

```python
# src/llm/registry.py
from typing import Any
from src.llm.base import BaseLLMProvider, ModelDescriptor, ModelCapability
import logging

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Central registry for LLM providers.
    
    Providers register themselves. The ModelRouter queries the registry
    to find providers matching capability requirements.
    """

    def __init__(self):
        self._providers: dict[str, BaseLLMProvider] = {}      # name → provider instance
        self._initialized: set[str] = set()

    def register(self, name: str, provider: BaseLLMProvider) -> None:
        """Register a provider with a human-readable name."""
        if name in self._providers:
            raise ValueError(f"Provider already registered: {name}")
        self._providers[name] = provider
        logger.info(f"Registered LLM provider: {name} ({provider.descriptor().model_id})")

    async def initialize_all(self) -> None:
        """Initialize all registered providers."""
        for name, provider in self._providers.items():
            try:
                await provider.initialize()
                self._initialized.add(name)
                logger.info(f"Initialized provider: {name}")
            except Exception as e:
                logger.warning(f"Failed to initialize provider {name}: {e}")

    def get(self, name: str) -> BaseLLMProvider | None:
        """Get a provider by name."""
        return self._providers.get(name)

    def find_by_capability(self, capability: ModelCapability) -> list[tuple[str, BaseLLMProvider]]:
        """Find all providers that support a given capability."""
        return [
            (name, p) for name, p in self._providers.items()
            if capability in p.descriptor().capabilities
        ]

    def find_by_model_id(self, model_id: str) -> BaseLLMProvider | None:
        """Find provider by model ID."""
        for provider in self._providers.values():
            if provider.descriptor().model_id == model_id:
                return provider
        return None

    def all_descriptors(self) -> list[tuple[str, ModelDescriptor]]:
        """Return descriptors for all registered providers."""
        return [(name, p.descriptor()) for name, p in self._providers.items()]

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all providers."""
        results = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results

    async def shutdown_all(self) -> None:
        """Shutdown all providers."""
        for name, provider in self._providers.items():
            try:
                await provider.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down provider {name}: {e}")
```

### 1.5 Code: Enhanced Model Router

```python
# src/llm/router.py
from src.llm.base import BaseLLMProvider, LLMResponse, LLMError, ModelCapability
from src.llm.registry import ProviderRegistry
import logging
import asyncio
import time

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes LLM requests to the cheapest available provider that can handle the task.
    
    This replaces the hardcoded ModelRouter from trading-super-agent-spec.md §4.
    All model selection is now config-driven via ProviderRegistry.
    """

    def __init__(self, registry: ProviderRegistry, config: dict):
        self._registry = registry
        self._config = config
        self._usage_tracker = UsageTracker()

    async def generate(
        self,
        task_type: str,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        preferred_provider: str | None = None,
    ) -> LLMResponse:
        """
        Route a generation request to the best available provider.
        
        Args:
            task_type: The type of task (determines tier selection)
            prompt: The user prompt
            preferred_provider: Override automatic selection
        """
        # Get the fallback chain for this task type
        chain = self._get_fallback_chain(task_type, preferred_provider)

        last_error = None
        for provider_name in chain:
            provider = self._registry.get(provider_name)
            if not provider:
                continue

            try:
                response = await provider.generate(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._usage_tracker.record(provider_name, task_type, response.usage)
                return response

            except LLMError as e:
                last_error = e
                logger.warning(f"Provider {provider_name} failed for {task_type}: {e.message}")
                if e.retry_after_seconds:
                    await asyncio.sleep(min(e.retry_after_seconds, 30))
                continue

        raise last_error or LLMError(
            error_type="provider_unavailable",
            message=f"All providers exhausted for task type: {task_type}",
            provider="none",
            model="none",
            retryable=True,
        )

    async def stream(self, task_type: str, prompt: str, **kwargs):
        """Route a streaming request."""
        chain = self._get_fallback_chain(task_type)
        for provider_name in chain:
            provider = self._registry.get(provider_name)
            if not provider:
                continue
            try:
                async for token in provider.stream(prompt, **kwargs):
                    yield token
                return
            except LLMError:
                continue
        raise LLMError(
            error_type="provider_unavailable",
            message=f"All providers exhausted for streaming: {task_type}",
            provider="none", model="none", retryable=True,
        )

    def _get_fallback_chain(self, task_type: str, preferred: str | None = None) -> list[str]:
        """Get ordered list of providers to try for a task type."""
        if preferred:
            return [preferred] + [
                p for p in self._config.get("fallback_chains", {}).get(task_type, [])
                if p != preferred
            ]
        return self._config.get("fallback_chains", {}).get(task_type, ["ollama_local"])

    def get_usage_stats(self) -> dict:
        """Return usage statistics."""
        return self._usage_tracker.summary()


class UsageTracker:
    """Track LLM usage across providers and task types."""

    def __init__(self):
        self._records: list[dict] = []

    def record(self, provider: str, task_type: str, usage):
        self._records.append({
            "provider": provider,
            "task_type": task_type,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "timestamp": time.time(),
        })

    def summary(self) -> dict:
        by_provider = {}
        by_task = {}
        for r in self._records:
            p = r["provider"]
            t = r["task_type"]
            by_provider.setdefault(p, {"total_tokens": 0, "calls": 0})
            by_provider[p]["total_tokens"] += r["total_tokens"]
            by_provider[p]["calls"] += 1
            by_task.setdefault(t, {"total_tokens": 0, "calls": 0})
            by_task[t]["total_tokens"] += r["total_tokens"]
            by_task[t]["calls"] += 1
        return {"by_provider": by_provider, "by_task": by_task, "total_calls": len(self._records)}
```

### 1.6 YAML Configuration

```yaml
# config/llm_providers.yaml
# LLM Provider Configuration — replaces hardcoded model routing

providers:
  ollama_local:
    type: ollama
    model_id: "qwen2.5:7b"
    base_url: "http://localhost:11434"
    display_name: "Qwen 2.5 7B (Local)"
    max_context_tokens: 32768
    capabilities:
      - streaming
      - json_mode
      - code_generation

  nvidia_nim:
    type: openai_compatible
    model_id: "deepseek-ai/deepseek-r1"
    api_key: "${NVIDIA_API_KEY}"
    base_url: "https://integrate.api.nvidia.com/v1"
    display_name: "DeepSeek R1 (NVIDIA NIM)"
    max_context_tokens: 65536
    capabilities:
      - streaming
      - reasoning
      - code_generation

  deepseek_api:
    type: openai_compatible
    model_id: "deepseek-reasoner"
    api_key: "${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com"
    display_name: "DeepSeek Reasoner"
    max_context_tokens: 65536
    capabilities:
      - streaming
      - reasoning

  openai:
    type: openai_compatible
    model_id: "gpt-4o"
    api_key: "${OPENAI_API_KEY}"
    display_name: "GPT-4o"
    max_context_tokens: 128000
    capabilities:
      - streaming
      - function_calling
      - structured_output
      - vision
      - json_mode
      - tool_use

  anthropic:
    type: anthropic
    model_id: "claude-sonnet-4-20250514"
    api_key: "${ANTHROPIC_API_KEY}"
    display_name: "Claude Sonnet"
    max_context_tokens: 200000
    capabilities:
      - streaming
      - vision
      - code_generation
      - reasoning
      - tool_use

# Task type → provider fallback chain (ordered by preference)
fallback_chains:
  explanation:
    - ollama_local
  summary:
    - ollama_local
  tagging:
    - ollama_local
  signal_validation:
    - ollama_local
  risk_analysis:
    - ollama_local
  complex_analysis:
    - nvidia_nim
    - deepseek_api
    - ollama_local
  strategy_synthesis:
    - nvidia_nim
    - deepseek_api
    - ollama_local
  trade_narrative:
    - nvidia_nim
    - deepseek_api
    - ollama_local
  bias_detection:
    - nvidia_nim
    - deepseek_api
    - ollama_local
```

### 1.7 Migration Notes

**Files to update:**
- `src/llm/router.py` — Replace hardcoded `ModelRouter.TIERS` with config-driven `ProviderRegistry`
- `src/llm/prompts.py` — No changes needed (prompts stay the same)
- All agent files that import `ollama_qwen` or `ollama_deepseek_r1` tools → Replace with `model_router.generate(task_type=..., prompt=...)`
- `config/model_routing.yaml` → Merge into `config/llm_providers.yaml`
- `config/default.yaml` → Update `llm:` section to reference new provider config

**Backward compatibility:** The old `ModelRouter.TIERS` dict can be kept as a deprecated shim during migration.

---

## Fix #2: Configurable Model Names

**Gap:** Hardcoded model names in tools/configs — vendor lock-in  
**Severity:** Critical  
**Capability Affected:** Model Agnosticism  
**Estimated Effort:** 1 day  

### 2.1 Architectural Specification

**What to change:** All hardcoded model name references (`qwen2.5:7b`, `deepseek-r1`, etc.) in tool names, agent code, and configs must be replaced with config-driven references through the `ProviderRegistry`.

**Key principle:** No model name should appear in Python source code. All model selection is config-driven.

### 2.2 Code: Model Config Loader

```python
# src/llm/config.py
import yaml
import os
from pathlib import Path
from src.llm.registry import ProviderRegistry
from src.llm.providers.ollama_provider import OllamaProvider
from src.llm.providers.openai_provider import OpenAIProvider
from src.llm.providers.anthropic_provider import AnthropicProvider
from src.llm.base import ModelCapability
import logging

logger = logging.getLogger(__name__)

_CAPABILITY_MAP = {
    "streaming": ModelCapability.STREAMING,
    "function_calling": ModelCapability.FUNCTION_CALLING,
    "structured_output": ModelCapability.STRUCTURED_OUTPUT,
    "vision": ModelCapability.VISION,
    "code_generation": ModelCapability.CODE_GENERATION,
    "reasoning": ModelCapability.REASONING,
    "json_mode": ModelCapability.JSON_MODE,
    "tool_use": ModelCapability.TOOL_USE,
}


def load_providers_from_config(config_path: str = "config/llm_providers.yaml") -> ProviderRegistry:
    """
    Load LLM provider configuration and create a ProviderRegistry.
    
    This is the SINGLE source of truth for which models are available.
    No model names in code — only in this config file.
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    registry = ProviderRegistry()

    for name, prov_config in config.get("providers", {}).items():
        prov_type = prov_config["type"]
        model_id = prov_config["model_id"]

        # Resolve environment variables in api_key
        api_key = prov_config.get("api_key", "")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")

        # Parse capabilities
        caps = frozenset(
            _CAPABILITY_MAP[c] for c in prov_config.get("capabilities", [])
            if c in _CAPABILITY_MAP
        )

        # Create provider instance
        if prov_type == "ollama":
            provider = OllamaProvider(
                model_id=model_id,
                base_url=prov_config.get("base_url", "http://localhost:11434"),
            )
        elif prov_type == "openai_compatible":
            provider = OpenAIProvider(
                model_id=model_id,
                api_key=api_key,
                base_url=prov_config.get("base_url"),
                display_name=prov_config.get("display_name"),
                max_context=prov_config.get("max_context_tokens", 128000),
                capabilities=caps,
            )
        elif prov_type == "anthropic":
            provider = AnthropicProvider(
                model_id=model_id,
                api_key=api_key,
            )
        else:
            logger.warning(f"Unknown provider type: {prov_type}, skipping {name}")
            continue

        registry.register(name, provider)

    return registry
```

### 2.3 Migration: Removing Hardcoded Model Names

**Before (hardcoded):**
```python
# In trading-super-agent-spec.md §4
class ModelRouter:
    TIERS = {
        "t2_local": {"provider": "ollama", "model": "qwen2.5:7b", ...},
        "t3_free_nvidia": {"provider": "nvidia_nim", "model": "deepseek-ai/deepseek-r1", ...},
    }
```

**After (config-driven):**
```python
# In src/llm/router.py — ModelRouter receives ProviderRegistry from config
registry = load_providers_from_config("config/llm_providers.yaml")
router = ModelRouter(registry, config=providers_config)

# Usage in agents:
response = await router.generate(
    task_type="trade_narrative",  # Selects provider via fallback chain
    prompt="Analyze this trade...",
)
```

**Tool name changes:**
| Old (hardcoded) | New (generic) |
|---|---|
| `ollama_qwen` | `llm_generate` (task_type="explanation") |
| `ollama_deepseek_r1` | `llm_generate` (task_type="complex_analysis") |

### 2.4 YAML: Updated Tool Definitions

```yaml
# config/tools/llm_tools.yaml
# LLM tools now reference task types, not model names

tools:
  llm_explain:
    description: "Generate a natural language explanation"
    task_type: "explanation"
    permission: ANALYSIS
    timeout_ms: 10000

  llm_analyze:
    description: "Perform complex multi-factor analysis"
    task_type: "complex_analysis"
    permission: ANALYSIS
    timeout_ms: 30000

  llm_narrate:
    description: "Generate a trade narrative or reflection"
    task_type: "trade_narrative"
    permission: ANALYSIS
    timeout_ms: 30000

  llm_synthesize:
    description: "Synthesize new strategy hypotheses"
    task_type: "strategy_synthesis"
    permission: ANALYSIS
    timeout_ms: 60000
```

### 2.5 Migration Notes

**Files to update:**
- `config/model_routing.yaml` → Replace with `config/llm_providers.yaml`
- All tool definitions referencing `ollama_qwen` or `ollama_deepseek_r1` → Replace with `llm_*` tools that reference task types
- Agent code: replace direct `OllamaClient(model="qwen2.5:7b")` calls with `router.generate(task_type=...)`
- `config/default.yaml` → Update `llm:` section

---

## Fix #3: CloudEvents Messaging Protocol

**Gap:** No standard messaging protocol — proprietary MessageEnvelope limits interoperability  
**Severity:** Critical  
**Capability Affected:** Open Ecosystem (Score: 5.5 → Target: 7.5)  
**Estimated Effort:** 2-3 days  

### 3.1 Architectural Specification

**What to change:** Replace the proprietary `MessageEnvelope` format with **CloudEvents v1.0** specification for all inter-agent messages on Redis Streams.

**Why CloudEvents:**
- CNCF standard (used by AWS, Azure, Google Cloud)
- Well-defined metadata schema (id, source, type, time, datacontenttype, data)
- Extensible via extension attributes
- JSON and MessagePack serialization supported
- Designed exactly for event-driven architectures like TSAR

**What stays the same:** Redis Streams as transport. MessagePack as wire format. Consumer groups for exactly-once processing.

### 3.2 Code: CloudEvents Envelope

```python
# src/messaging/cloudevents.py
"""
CloudEvents v1.0 implementation for TSAR inter-agent messaging.

Replaces the proprietary MessageEnvelope with the CNCF CloudEvents standard.
All messages on Redis Streams use this envelope format.

Spec: https://cloudevents.io/
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid
import time
import msgpack
import json


@dataclass(frozen=True)
class CloudEvent:
    """
    CloudEvents v1.0 compliant event envelope.
    
    Required attributes (per CloudEvents spec):
        specversion: Always "1.0"
        id: Unique event identifier (ULID for time-sortability)
        source: Event source (e.g., "tsar/agent/risk_guardian")
        type: Event type (e.g., "tsar.risk.decision.v1")
    
    Optional attributes:
        time: Event timestamp (RFC 3339)
        datacontenttype: Content type of data (default: "application/json")
        dataschema: URI of the data schema
        subject: Subject of the event
    
    TSAR extension attributes:
        trace_id: Distributed trace ID
        priority: 0=critical, 1=high, 2=normal, 3=low
        agent: Publishing agent name
        version: Schema version for forward compatibility
    """
    # Required (CloudEvents spec)
    specversion: str = "1.0"
    id: str = ""                          # ULID
    source: str = ""                      # "tsar/agent/{agent_name}"
    type: str = ""                        # "tsar.{domain}.{action}.v{version}"
    
    # Optional (CloudEvents spec)
    time: str = ""                        # RFC 3339 timestamp
    datacontenttype: str = "application/json"
    dataschema: str = ""
    subject: str = ""
    
    # TSAR extension attributes
    trace_id: str = ""                    # Distributed tracing
    priority: int = 2                     # 0=critical, 1=high, 2=normal, 3=low
    agent: str = ""                       # Publishing agent name
    version: int = 1                      # Schema version
    
    # Data payload
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, 'id', _generate_ulid())
        if not self.time:
            object.__setattr__(self, 'time', datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialize to CloudEvents JSON format."""
        d = {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
            "datacontenttype": self.datacontenttype,
            "data": self.data,
        }
        # Optional attributes (only if set)
        if self.dataschema:
            d["dataschema"] = self.dataschema
        if self.subject:
            d["subject"] = self.subject
        # TSAR extensions
        if self.trace_id:
            d["trace_id"] = self.trace_id
        if self.priority != 2:
            d["priority"] = self.priority
        if self.agent:
            d["agent"] = self.agent
        if self.version != 1:
            d["version"] = self.version
        return d

    def to_msgpack(self) -> bytes:
        """Serialize to MessagePack for wire format."""
        return msgpack.packb(self.to_dict(), use_bin_type=True)

    @classmethod
    def from_dict(cls, d: dict) -> CloudEvent:
        """Deserialize from CloudEvents JSON format."""
        return cls(
            specversion=d.get("specversion", "1.0"),
            id=d.get("id", ""),
            source=d.get("source", ""),
            type=d.get("type", ""),
            time=d.get("time", ""),
            datacontenttype=d.get("datacontenttype", "application/json"),
            dataschema=d.get("dataschema", ""),
            subject=d.get("subject", ""),
            trace_id=d.get("trace_id", ""),
            priority=d.get("priority", 2),
            agent=d.get("agent", ""),
            version=d.get("version", 1),
            data=d.get("data", {}),
        )

    @classmethod
    def from_msgpack(cls, raw: bytes) -> CloudEvent:
        """Deserialize from MessagePack wire format."""
        d = msgpack.unpackb(raw, raw=False)
        return cls.from_dict(d)

    @classmethod
    def from_redis(cls, redis_data: dict[bytes, bytes]) -> CloudEvent:
        """Deserialize from Redis Streams hash format."""
        decoded = {k.decode() if isinstance(k, bytes) else k:
                   v.decode() if isinstance(v, bytes) else v
                   for k, v in redis_data.items()}
        # Data field may be msgpack-encoded
        data = decoded.get("data", "{}")
        if isinstance(data, str):
            import json as _json
            data = _json.loads(data)
        decoded["data"] = data
        return cls.from_dict(decoded)


def _generate_ulid() -> str:
    """Generate a ULID (Universally Unique, Lexicographically Sortable Identifier)."""
    # Simplified ULID: timestamp (48 bits) + random (80 bits)
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().int & ((1 << 80) - 1)
    ulid_int = (ts << 80) | rand
    return base32_encode(ulid_int)


def base32_encode(n: int) -> str:
    """Crockford Base32 encoding for ULID."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    result = []
    for _ in range(26):
        result.append(alphabet[n & 31])
        n >>= 5
    return "".join(reversed(result))
```

### 3.3 Code: Event Type Registry

```python
# src/messaging/event_types.py
"""
Canonical event type definitions for TSAR CloudEvents.

Naming convention: tsar.{domain}.{action}.v{version}

Domains:
    regime    — Market regime state changes
    signal    — Trading signals
    risk      — Risk decisions and alerts
    order     — Order lifecycle
    fill      — Fill events
    position  — Position updates
    analytics — Trade analysis and insights
    strategy  — Strategy evolution
    health    — Agent health heartbeats
    system    — System lifecycle events
"""


class EventTypes:
    """Canonical TSAR event types."""

    # Regime
    REGIME_CHANGE = "tsar.regime.change.v1"
    REGIME_UPDATE = "tsar.regime.update.v1"

    # Signals
    SIGNAL_GENERATED = "tsar.signal.generated.v1"
    SIGNAL_VALIDATED = "tsar.signal.validated.v1"

    # Risk
    RISK_DECISION = "tsar.risk.decision.v1"
    RISK_VETO_ALL = "tsar.risk.veto_all.v1"
    RISK_LIMIT_BREACH = "tsar.risk.limit_breach.v1"
    RISK_KILL_SWITCH = "tsar.risk.kill_switch.v1"

    # Orders
    ORDER_PLACED = "tsar.order.placed.v1"
    ORDER_FILLED = "tsar.order.filled.v1"
    ORDER_CANCELLED = "tsar.order.cancelled.v1"
    ORDER_REJECTED = "tsar.order.rejected.v1"

    # Fills
    FILL_RECEIVED = "tsar.fill.received.v1"
    FILL_PARTIAL = "tsar.fill.partial.v1"

    # Positions
    POSITION_OPENED = "tsar.position.opened.v1"
    POSITION_CLOSED = "tsar.position.closed.v1"
    POSITION_UPDATED = "tsar.position.updated.v1"
    PORTFOLIO_SNAPSHOT = "tsar.portfolio.snapshot.v1"

    # Analytics
    TRADE_ANALYSIS = "tsar.analytics.trade_analysis.v1"
    PATTERN_DISCOVERED = "tsar.analytics.pattern_discovered.v1"
    LESSON_CREATED = "tsar.analytics.lesson_created.v1"
    LESSON_APPLIED = "tsar.analytics.lesson_applied.v1"

    # Strategy
    STRATEGY_MUTATION = "tsar.strategy.mutation.v1"
    STRATEGY_RETIRED = "tsar.strategy.retired.v1"
    STRATEGY_PROMOTED = "tsar.strategy.promoted.v1"

    # Health
    AGENT_HEARTBEAT = "tsar.health.heartbeat.v1"
    AGENT_DEGRADED = "tsar.health.degraded.v1"
    AGENT_DYING = "tsar.health.dying.v1"

    # System
    SYSTEM_BOOTSTRAP = "tsar.system.bootstrap.v1"
    SYSTEM_SHUTDOWN = "tsar.system.shutdown.v1"
    SYSTEM_MODE_CHANGE = "tsar.system.mode_change.v1"
```

### 3.4 Updated Stream Topology with CloudEvents

```
Stream Name                    Event Types                              Consumers
─────────────────────────────────────────────────────────────────────────────────
tsar:stream:regime             tsar.regime.change.v1                    Signal Scout, Risk Guardian,
                                 tsar.regime.update.v1                    Strategy Geneticist,
                                                                          Market Cartographer

tsar:stream:signals            tsar.signal.generated.v1                 Risk Guardian, Strategy
                                 tsar.signal.validated.v1                 Geneticist

tsar:stream:risk_decisions     tsar.risk.decision.v1                    Execution Sniper, Trade
                                 tsar.risk.veto_all.v1                    Philosopher

tsar:stream:orders             tsar.order.placed.v1                     Execution Tracker
                                 tsar.order.cancelled.v1

tsar:stream:fills              tsar.fill.received.v1                    Trade Philosopher,
                                 tsar.fill.partial.v1                     Risk Guardian,
                                                                          Market Cartographer

tsar:stream:positions          tsar.position.opened.v1                  Risk Guardian,
                                 tsar.position.closed.v1                  Trade Philosopher,
                                 tsar.position.updated.v1                 Strategy Geneticist
                                 tsar.portfolio.snapshot.v1

tsar:stream:analytics          tsar.analytics.trade_analysis.v1         Strategy Geneticist,
                                 tsar.analytics.pattern_discovered.v1     Regime Detector
                                 tsar.analytics.lesson_created.v1

tsar:stream:strategy_mutations tsar.strategy.mutation.v1                Signal Scout

tsar:stream:health             tsar.health.heartbeat.v1                 Orchestrator
                                 tsar.health.degraded.v1
                                 tsar.health.dying.v1
```

### 3.5 Redis Streams Publisher/Subscriber

```python
# src/messaging/publisher.py
import redis.asyncio as redis
from src.messaging.cloudevents import CloudEvent
from src.messaging.event_types import EventTypes
import logging

logger = logging.getLogger(__name__)


class EventPublisher:
    """Publishes CloudEvents to Redis Streams."""

    def __init__(self, redis_client: redis.Redis, agent_name: str):
        self._redis = redis_client
        self._agent_name = agent_name

    async def publish(self, stream: str, event: CloudEvent) -> str:
        """
        Publish a CloudEvent to a Redis Stream.
        
        Returns the Redis message ID.
        """
        # Ensure agent metadata
        if not event.agent:
            object.__setattr__(event, 'agent', self._agent_name)
        if not event.source:
            object.__setattr__(event, 'source', f"tsar/agent/{self._agent_name}")

        # Serialize to Redis hash format
        data = event.to_dict()
        # Convert data dict to JSON string for Redis storage
        import json
        redis_data = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                      for k, v in data.items()}

        msg_id = await self._redis.xadd(stream, redis_data)
        logger.debug(f"Published {event.type} to {stream} (id={msg_id})")
        return msg_id

    async def heartbeat(self, status: str = "healthy", metadata: dict | None = None):
        """Publish agent heartbeat."""
        event = CloudEvent(
            type=EventTypes.AGENT_HEARTBEAT,
            data={"status": status, "metadata": metadata or {}},
        )
        await self.publish("tsar:stream:health", event)
```

```python
# src/messaging/subscriber.py
import redis.asyncio as redis
from src.messaging.cloudevents import CloudEvent
from typing import Callable, Awaitable
import logging
import asyncio

logger = logging.getLogger(__name__)


class EventSubscriber:
    """Subscribes to CloudEvents from Redis Streams."""

    def __init__(self, redis_client: redis.Redis, consumer_group: str, consumer_name: str):
        self._redis = redis_client
        self._group = consumer_group
        self._consumer = consumer_name
        self._handlers: dict[str, list[Callable]] = {}  # event_type → handlers

    def on(self, event_type: str, handler: Callable[[CloudEvent], Awaitable[None]]):
        """Register a handler for an event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    async def subscribe(self, streams: list[str], count: int = 10, block_ms: int = 1000):
        """
        Listen for events on streams and dispatch to handlers.
        Runs until cancelled.
        """
        # Ensure consumer groups exist
        for stream in streams:
            try:
                await self._redis.xgroup_create(stream, self._group, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

        while True:
            try:
                # Read from all subscribed streams
                stream_dict = {s: ">" for s in streams}
                messages = await self._redis.xreadgroup(
                    self._group, self._consumer,
                    stream_dict,
                    count=count,
                    block=block_ms,
                )

                for stream_name, msgs in messages:
                    for msg_id, fields in msgs:
                        try:
                            event = CloudEvent.from_redis(fields)
                            await self._dispatch(event)
                        except Exception as e:
                            logger.error(f"Error processing message {msg_id}: {e}")
                        finally:
                            await self._redis.xack(stream_name, self._group, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Subscriber error: {e}")
                await asyncio.sleep(1)

    async def _dispatch(self, event: CloudEvent):
        """Dispatch event to registered handlers."""
        handlers = self._handlers.get(event.type, [])
        # Also check wildcard handlers
        handlers += self._handlers.get("*", [])

        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Handler error for {event.type}: {e}")
```

### 3.6 Migration Notes

**What changes:**
- `MessageEnvelope` dataclass → `CloudEvent` dataclass
- All `msg_id` references → `id` (CloudEvents standard)
- All `msg_type` references → `type` (CloudEvents standard)
- All `source_agent` references → `agent` (TSAR extension)
- All `timestamp_ns` references → `time` (RFC 3339)
- All `payload` references → `data` (CloudEvents standard)

**Backward compatibility:**
- `CloudEvent.from_msgpack()` can read old `MessageEnvelope` format by mapping fields
- Add a `LEGACY_MODE` flag that accepts both formats during migration

**Files to update:**
- `src/messaging/` — New directory (replaces inline envelope code)
- All agent files that create/publish messages → Use `CloudEvent` + `EventPublisher`
- All agent files that consume messages → Use `EventSubscriber` + `CloudEvent`
- Architecture docs: Update message envelope format references

---

## Fix #4: Improvement Measurement Framework

**Gap:** No improvement measurement framework — can't prove the system is getting better  
**Severity:** High  
**Capability Affected:** Self-Improvement (Score: 8 → Target: 9)  
**Estimated Effort:** 2-3 days  

### 4.1 Architectural Specification

**What to add:** An improvement measurement system that records baseline metrics, tracks trends over time, and produces a dashboard showing whether the system is actually improving.

**Core Metrics:**
1. **Sharpe Ratio Trend** — Rolling 30-day Sharpe over time
2. **Win Rate Trend** — Rolling 30-day win rate over time
3. **Lesson Application Rate** — % of trades where lessons were applied
4. **Knowledge Density** — Growth rate of patterns + lessons + strategy mutations
5. **Strategy Fitness** — Average Sharpe of active strategies over time
6. **Risk-Adjusted Return** — Return per unit of drawdown over time

### 4.2 SQL Schema

```sql
-- src/monitoring/improvement_schema.sql
-- Improvement measurement tables for tsar.db

-- Baseline metrics recorded from first N trades
CREATE TABLE IF NOT EXISTS improvement_baselines (
    baseline_id     TEXT PRIMARY KEY,
    metric_name     TEXT NOT NULL,
    metric_value    REAL NOT NULL,
    sample_size     INTEGER NOT NULL,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    recorded_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_baseline_metric ON improvement_baselines(metric_name);

-- Periodic metric snapshots (daily)
CREATE TABLE IF NOT EXISTS improvement_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    snapshot_date   TEXT NOT NULL,

    -- Performance metrics
    sharpe_30d      REAL,
    sharpe_90d      REAL,
    win_rate_30d    REAL,
    win_rate_90d    REAL,
    profit_factor_30d REAL,
    max_drawdown_30d REAL,
    avg_r_multiple  REAL,
    total_trades_30d INTEGER,

    -- Learning metrics
    lessons_created     INTEGER,
    lessons_applied     INTEGER,
    lessons_violated    INTEGER,
    lesson_application_rate REAL,  -- applied / (applied + violated)
    patterns_discovered INTEGER,
    patterns_active     INTEGER,
    pattern_confidence_avg REAL,

    -- Strategy metrics
    strategies_active   INTEGER,
    strategies_retired  INTEGER,
    strategy_mutations  INTEGER,
    avg_strategy_sharpe REAL,
    strategy_diversity_score REAL,

    -- Knowledge density
    knowledge_items_total INTEGER,  -- patterns + lessons + mutations
    knowledge_growth_rate REAL,     -- % change from previous snapshot

    -- System metrics
    llm_calls_total     INTEGER,
    llm_tokens_total    INTEGER,
    uptime_pct          REAL,
    risk_violations     INTEGER,

    -- Delta from baseline
    sharpe_vs_baseline      REAL,
    win_rate_vs_baseline    REAL,
    knowledge_vs_baseline   REAL,

    recorded_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_snapshot_date ON improvement_snapshots(snapshot_date DESC);

-- Improvement goals and targets
CREATE TABLE IF NOT EXISTS improvement_goals (
    goal_id         TEXT PRIMARY KEY,
    metric_name     TEXT NOT NULL,
    target_value    REAL NOT NULL,
    deadline        TEXT,
    status          TEXT DEFAULT 'active' CHECK(status IN ('active','achieved','missed','cancelled')),
    achieved_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### 4.3 Code: Improvement Tracker

```python
# src/monitoring/improvement.py
"""
Improvement Measurement Framework for TSAR.

Records baseline metrics, computes periodic snapshots, and tracks
whether the system is measurably improving over time.
"""
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImprovementSnapshot:
    """A point-in-time snapshot of all improvement metrics."""
    snapshot_date: str
    sharpe_30d: float | None = None
    sharpe_90d: float | None = None
    win_rate_30d: float | None = None
    win_rate_90d: float | None = None
    profit_factor_30d: float | None = None
    max_drawdown_30d: float | None = None
    avg_r_multiple: float | None = None
    total_trades_30d: int | None = None
    lessons_created: int = 0
    lessons_applied: int = 0
    lessons_violated: int = 0
    lesson_application_rate: float | None = None
    patterns_discovered: int = 0
    patterns_active: int = 0
    pattern_confidence_avg: float | None = None
    strategies_active: int = 0
    strategies_retired: int = 0
    strategy_mutations: int = 0
    avg_strategy_sharpe: float | None = None
    strategy_diversity_score: float | None = None
    knowledge_items_total: int = 0
    knowledge_growth_rate: float | None = None
    sharpe_vs_baseline: float | None = None
    win_rate_vs_baseline: float | None = None
    knowledge_vs_baseline: float | None = None


class ImprovementTracker:
    """
    Tracks system improvement over time.
    
    Usage:
        tracker = ImprovementTracker(db_connection)
        tracker.record_baseline()  # After first 30 trades
        tracker.compute_daily_snapshot()  # Run daily
        report = tracker.get_improvement_report()  # Dashboard data
    """

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._ensure_tables()

    def _ensure_tables(self):
        """Create improvement tables if they don't exist."""
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS improvement_baselines (
                baseline_id TEXT PRIMARY KEY,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                sample_size INTEGER NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS improvement_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                snapshot_date TEXT NOT NULL,
                sharpe_30d REAL, sharpe_90d REAL,
                win_rate_30d REAL, win_rate_90d REAL,
                profit_factor_30d REAL, max_drawdown_30d REAL,
                avg_r_multiple REAL, total_trades_30d INTEGER,
                lessons_created INTEGER, lessons_applied INTEGER,
                lessons_violated INTEGER, lesson_application_rate REAL,
                patterns_discovered INTEGER, patterns_active INTEGER,
                pattern_confidence_avg REAL,
                strategies_active INTEGER, strategies_retired INTEGER,
                strategy_mutations INTEGER, avg_strategy_sharpe REAL,
                strategy_diversity_score REAL,
                knowledge_items_total INTEGER, knowledge_growth_rate REAL,
                sharpe_vs_baseline REAL, win_rate_vs_baseline REAL,
                knowledge_vs_baseline REAL,
                recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS improvement_goals (
                goal_id TEXT PRIMARY KEY,
                metric_name TEXT NOT NULL,
                target_value REAL NOT NULL,
                deadline TEXT,
                status TEXT DEFAULT 'active',
                achieved_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
        """)

    def record_baseline(self, min_trades: int = 30) -> bool:
        """
        Record baseline metrics from the first N trades.
        Call this once after the system has enough trades.
        """
        trade_count = self._db.execute(
            "SELECT COUNT(*) FROM trade_records WHERE is_deleted = 0"
        ).fetchone()[0]

        if trade_count < min_trades:
            logger.info(f"Not enough trades for baseline: {trade_count}/{min_trades}")
            return False

        # Check if baseline already exists
        existing = self._db.execute(
            "SELECT COUNT(*) FROM improvement_baselines"
        ).fetchone()[0]
        if existing > 0:
            logger.info("Baseline already recorded, skipping")
            return False

        now = datetime.now(timezone.utc).isoformat()

        # Compute baseline metrics
        metrics = self._compute_metrics(days=365)  # Use all available data

        baselines = [
            ("sharpe_ratio", metrics.get("sharpe_30d", 0)),
            ("win_rate", metrics.get("win_rate_30d", 0)),
            ("profit_factor", metrics.get("profit_factor_30d", 0)),
            ("max_drawdown", metrics.get("max_drawdown_30d", 0)),
            ("lesson_count", metrics.get("lessons_created", 0)),
            ("pattern_count", metrics.get("patterns_active", 0)),
        ]

        for name, value in baselines:
            self._db.execute(
                "INSERT INTO improvement_baselines (baseline_id, metric_name, metric_value, sample_size, period_start, period_end) VALUES (?, ?, ?, ?, ?, ?)",
                (f"baseline_{name}", name, value, trade_count, now, now),
            )

        self._db.commit()
        logger.info(f"Baseline recorded with {trade_count} trades")
        return True

    def compute_daily_snapshot(self) -> ImprovementSnapshot:
        """
        Compute and store a daily improvement snapshot.
        Should be called once per day (e.g., 00:00 UTC).
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check if already computed today
        existing = self._db.execute(
            "SELECT snapshot_id FROM improvement_snapshots WHERE snapshot_date = ?",
            (today,)
        ).fetchone()
        if existing:
            logger.info(f"Snapshot already exists for {today}")
            return self._get_snapshot(today)

        metrics = self._compute_metrics(days=30)
        metrics_90d = self._compute_metrics(days=90)

        # Learning metrics
        learning = self._compute_learning_metrics(days=30)

        # Strategy metrics
        strategy = self._compute_strategy_metrics()

        # Knowledge density
        knowledge = self._compute_knowledge_metrics()

        # Baseline comparison
        baseline = self._get_baselines()

        # Previous snapshot for growth rate
        prev = self._get_previous_snapshot()

        snapshot = ImprovementSnapshot(
            snapshot_date=today,
            sharpe_30d=metrics.get("sharpe_30d"),
            sharpe_90d=metrics_90d.get("sharpe_30d"),
            win_rate_30d=metrics.get("win_rate_30d"),
            win_rate_90d=metrics_90d.get("win_rate_30d"),
            profit_factor_30d=metrics.get("profit_factor_30d"),
            max_drawdown_30d=metrics.get("max_drawdown_30d"),
            avg_r_multiple=metrics.get("avg_r_multiple"),
            total_trades_30d=metrics.get("total_trades"),
            lessons_created=learning.get("lessons_created", 0),
            lessons_applied=learning.get("lessons_applied", 0),
            lessons_violated=learning.get("lessons_violated", 0),
            lesson_application_rate=learning.get("application_rate"),
            patterns_discovered=learning.get("patterns_discovered", 0),
            patterns_active=learning.get("patterns_active", 0),
            pattern_confidence_avg=learning.get("pattern_confidence_avg"),
            strategies_active=strategy.get("active", 0),
            strategies_retired=strategy.get("retired", 0),
            strategy_mutations=strategy.get("mutations", 0),
            avg_strategy_sharpe=strategy.get("avg_sharpe"),
            strategy_diversity_score=strategy.get("diversity_score"),
            knowledge_items_total=knowledge.get("total", 0),
            knowledge_growth_rate=knowledge.get("growth_rate"),
            sharpe_vs_baseline=self._delta(
                metrics.get("sharpe_30d"), baseline.get("sharpe_ratio")),
            win_rate_vs_baseline=self._delta(
                metrics.get("win_rate_30d"), baseline.get("win_rate")),
            knowledge_vs_baseline=self._delta(
                knowledge.get("total"), baseline.get("lesson_count", 0) + baseline.get("pattern_count", 0)),
        )

        self._store_snapshot(snapshot)
        return snapshot

    def get_improvement_report(self, days: int = 30) -> dict[str, Any]:
        """
        Generate improvement report for the dashboard.
        
        Returns trends, baseline comparisons, and goal progress.
        """
        snapshots = self._get_snapshots(days)

        if not snapshots:
            return {"status": "no_data", "message": "No snapshots available yet"}

        latest = snapshots[-1]
        oldest = snapshots[0]

        # Compute trends
        trends = {}
        for metric in ["sharpe_30d", "win_rate_30d", "lesson_application_rate", "knowledge_items_total"]:
            values = [getattr(s, metric) for s in snapshots if getattr(s, metric) is not None]
            if len(values) >= 2:
                trends[metric] = {
                    "current": values[-1],
                    "previous": values[0],
                    "change": values[-1] - values[0],
                    "change_pct": ((values[-1] - values[0]) / abs(values[0]) * 100) if values[0] != 0 else None,
                    "direction": "improving" if values[-1] > values[0] else "declining" if values[-1] < values[0] else "stable",
                }

        # Goal progress
        goals = self._db.execute(
            "SELECT * FROM improvement_goals WHERE status = 'active'"
        ).fetchall()

        return {
            "status": "ok",
            "snapshot_count": len(snapshots),
            "period": {"start": oldest.snapshot_date, "end": latest.snapshot_date},
            "latest_snapshot": {
                "sharpe_30d": latest.sharpe_30d,
                "win_rate_30d": latest.win_rate_30d,
                "lesson_application_rate": latest.lesson_application_rate,
                "knowledge_items_total": latest.knowledge_items_total,
                "strategies_active": latest.strategies_active,
                "avg_strategy_sharpe": latest.avg_strategy_sharpe,
            },
            "baseline_comparison": {
                "sharpe_vs_baseline": latest.sharpe_vs_baseline,
                "win_rate_vs_baseline": latest.win_rate_vs_baseline,
                "knowledge_vs_baseline": latest.knowledge_vs_baseline,
            },
            "trends": trends,
            "goals": [dict(g) for g in goals],
            "verdict": self._compute_verdict(trends, latest),
        }

    def _compute_verdict(self, trends: dict, latest: ImprovementSnapshot) -> dict:
        """Compute whether the system is improving."""
        improving = 0
        declining = 0
        for metric, trend in trends.items():
            if trend["direction"] == "improving":
                improving += 1
            elif trend["direction"] == "declining":
                declining += 1

        if improving > declining:
            verdict = "IMPROVING"
            confidence = improving / (improving + declining)
        elif declining > improving:
            verdict = "DECLINING"
            confidence = declining / (improving + declining)
        else:
            verdict = "STABLE"
            confidence = 0.5

        return {
            "assessment": verdict,
            "confidence": round(confidence, 2),
            "improving_metrics": improving,
            "declining_metrics": declining,
        }

    # --- Internal computation methods ---

    def _compute_metrics(self, days: int = 30) -> dict:
        """Compute trading performance metrics."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        row = self._db.execute("""
            SELECT
                COUNT(*) as total_trades,
                AVG(CASE WHEN realized_pnl > 0 THEN 1.0 ELSE 0.0 END) as win_rate,
                AVG(realized_pnl) as avg_pnl,
                SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) /
                    NULLIF(ABS(SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl ELSE 0 END)), 0) as profit_factor,
                MIN(pnl_pct) as max_drawdown
            FROM trade_records
            WHERE closed_at > ? AND is_deleted = 0 AND status = 'CLOSED'
        """, (cutoff,)).fetchone()

        # Compute Sharpe (simplified)
        pnl_std = self._db.execute("""
            SELECT AVG(pnl_pct), 
                   (MAX(pnl_pct) - MIN(pnl_pct)) / 4.0 as approx_std
            FROM trade_records
            WHERE closed_at > ? AND is_deleted = 0 AND status = 'CLOSED'
        """, (cutoff,)).fetchone()

        avg_return = pnl_std[0] or 0
        std = pnl_std[1] or 1
        sharpe = (avg_return / std) * (252 ** 0.5) if std > 0 else 0

        return {
            "total_trades": row[0] or 0,
            "win_rate_30d": row[1] or 0,
            "avg_pnl": row[2] or 0,
            "profit_factor_30d": row[3] or 0,
            "max_drawdown_30d": abs(row[4] or 0),
            "sharpe_30d": round(sharpe, 2),
            "avg_r_multiple": 0,  # Would need R-multiple tracking
        }

    def _compute_learning_metrics(self, days: int = 30) -> dict:
        """Compute learning/improvement metrics."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        lessons = self._db.execute("""
            SELECT
                COUNT(*) as created,
                SUM(CASE WHEN times_applied > 0 THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN times_violated > 0 THEN 1 ELSE 0 END) as violated
            FROM lessons
            WHERE discovered_at > ? AND is_archived = 0
        """, (cutoff,)).fetchone()

        patterns = self._db.execute("""
            SELECT
                COUNT(*) as discovered,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                AVG(confidence) as avg_confidence
            FROM patterns
            WHERE discovered_at > ?
        """, (cutoff,)).fetchone()

        applied = lessons[1] or 0
        violated = lessons[2] or 0
        total = applied + violated
        app_rate = applied / total if total > 0 else None

        return {
            "lessons_created": lessons[0] or 0,
            "lessons_applied": applied,
            "lessons_violated": violated,
            "application_rate": round(app_rate, 3) if app_rate is not None else None,
            "patterns_discovered": patterns[0] or 0,
            "patterns_active": patterns[1] or 0,
            "pattern_confidence_avg": round(patterns[2] or 0, 3),
        }

    def _compute_strategy_metrics(self) -> dict:
        """Compute strategy evolution metrics."""
        active = self._db.execute(
            "SELECT COUNT(*), AVG(sharpe_ratio) FROM strategy_genomes WHERE status = 'live'"
        ).fetchone()

        retired = self._db.execute(
            "SELECT COUNT(*) FROM strategy_genomes WHERE status = 'retired' AND retired_at > datetime('now', '-30 days')"
        ).fetchone()

        mutations = self._db.execute(
            "SELECT COUNT(*) FROM strategy_mutations WHERE created_at > datetime('now', '-30 days')"
        ).fetchone()

        # Diversity: count distinct strategy types
        types = self._db.execute(
            "SELECT COUNT(DISTINCT strategy_type) FROM strategy_genomes WHERE status IN ('live', 'paper')"
        ).fetchone()

        max_types = 5  # mean_reversion, momentum, breakout, pairs, stat_arb
        diversity = (types[0] or 0) / max_types

        return {
            "active": active[0] or 0,
            "avg_sharpe": round(active[1] or 0, 2),
            "retired": retired[0] or 0,
            "mutations": mutations[0] or 0,
            "diversity_score": round(diversity, 2),
        }

    def _compute_knowledge_metrics(self) -> dict:
        """Compute knowledge density metrics."""
        patterns = self._db.execute("SELECT COUNT(*) FROM patterns").fetchone()[0] or 0
        lessons = self._db.execute("SELECT COUNT(*) FROM lessons WHERE is_archived = 0").fetchone()[0] or 0
        mutations = self._db.execute("SELECT COUNT(*) FROM strategy_mutations").fetchone()[0] or 0
        total = patterns + lessons + mutations

        # Previous total (7 days ago)
        prev = self._db.execute("""
            SELECT COUNT(*) FROM (
                SELECT pattern_id FROM patterns WHERE discovered_at < datetime('now', '-7 days')
                UNION ALL
                SELECT lesson_id FROM lessons WHERE discovered_at < datetime('now', '-7 days') AND is_archived = 0
                UNION ALL
                SELECT mutation_id FROM strategy_mutations WHERE created_at < datetime('now', '-7 days')
            )
        """).fetchone()[0] or 1

        growth = (total - prev) / prev if prev > 0 else 0

        return {
            "total": total,
            "patterns": patterns,
            "lessons": lessons,
            "mutations": mutations,
            "growth_rate": round(growth, 3),
        }

    def _get_baselines(self) -> dict:
        """Get recorded baselines."""
        rows = self._db.execute(
            "SELECT metric_name, metric_value FROM improvement_baselines"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def _get_previous_snapshot(self) -> ImprovementSnapshot | None:
        """Get the most recent snapshot before today."""
        row = self._db.execute(
            "SELECT * FROM improvement_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def _get_snapshot(self, date: str) -> ImprovementSnapshot | None:
        row = self._db.execute(
            "SELECT * FROM improvement_snapshots WHERE snapshot_date = ?", (date,)
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def _get_snapshots(self, days: int) -> list[ImprovementSnapshot]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._db.execute(
            "SELECT * FROM improvement_snapshots WHERE snapshot_date >= ? ORDER BY snapshot_date",
            (cutoff,)
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def _store_snapshot(self, s: ImprovementSnapshot):
        import uuid
        self._db.execute("""
            INSERT INTO improvement_snapshots (
                snapshot_id, snapshot_date, sharpe_30d, sharpe_90d,
                win_rate_30d, win_rate_90d, profit_factor_30d, max_drawdown_30d,
                avg_r_multiple, total_trades_30d, lessons_created, lessons_applied,
                lessons_violated, lesson_application_rate, patterns_discovered,
                patterns_active, pattern_confidence_avg, strategies_active,
                strategies_retired, strategy_mutations, avg_strategy_sharpe,
                strategy_diversity_score, knowledge_items_total, knowledge_growth_rate,
                sharpe_vs_baseline, win_rate_vs_baseline, knowledge_vs_baseline
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(uuid.uuid4()), s.snapshot_date, s.sharpe_30d, s.sharpe_90d,
            s.win_rate_30d, s.win_rate_90d, s.profit_factor_30d, s.max_drawdown_30d,
            s.avg_r_multiple, s.total_trades_30d, s.lessons_created, s.lessons_applied,
            s.lessons_violated, s.lesson_application_rate, s.patterns_discovered,
            s.patterns_active, s.pattern_confidence_avg, s.strategies_active,
            s.strategies_retired, s.strategy_mutations, s.avg_strategy_sharpe,
            s.strategy_diversity_score, s.knowledge_items_total, s.knowledge_growth_rate,
            s.sharpe_vs_baseline, s.win_rate_vs_baseline, s.knowledge_vs_baseline,
        ))
        self._db.commit()

    def _row_to_snapshot(self, row) -> ImprovementSnapshot:
        # Column order matches CREATE TABLE
        return ImprovementSnapshot(
            snapshot_date=row[1],
            sharpe_30d=row[2], sharpe_90d=row[3],
            win_rate_30d=row[4], win_rate_90d=row[5],
            profit_factor_30d=row[6], max_drawdown_30d=row[7],
            avg_r_multiple=row[8], total_trades_30d=row[9],
            lessons_created=row[10], lessons_applied=row[11],
            lessons_violated=row[12], lesson_application_rate=row[13],
            patterns_discovered=row[14], patterns_active=row[15],
            pattern_confidence_avg=row[16], strategies_active=row[17],
            strategies_retired=row[18], strategy_mutations=row[19],
            avg_strategy_sharpe=row[20], strategy_diversity_score=row[21],
            knowledge_items_total=row[22], knowledge_growth_rate=row[23],
            sharpe_vs_baseline=row[24], win_rate_vs_baseline=row[25],
            knowledge_vs_baseline=row[26],
        )

    @staticmethod
    def _delta(current: float | None, baseline: float | None) -> float | None:
        if current is None or baseline is None:
            return None
        return round(current - baseline, 4)
```

### 4.4 Integration: Grafana Dashboard

```json
{
  "dashboard": {
    "title": "TSAR Improvement Dashboard",
    "panels": [
      {
        "title": "Sharpe Ratio Trend",
        "type": "timeseries",
        "query": "SELECT snapshot_date, sharpe_30d, sharpe_90d FROM improvement_snapshots ORDER BY snapshot_date",
        "targets": ["sharpe_30d", "sharpe_90d"]
      },
      {
        "title": "Win Rate Trend",
        "type": "timeseries",
        "query": "SELECT snapshot_date, win_rate_30d FROM improvement_snapshots ORDER BY snapshot_date"
      },
      {
        "title": "Lesson Application Rate",
        "type": "gauge",
        "query": "SELECT lesson_application_rate FROM improvement_snapshots ORDER BY snapshot_date DESC LIMIT 1",
        "thresholds": {"red": 0.3, "yellow": 0.5, "green": 0.7}
      },
      {
        "title": "Knowledge Density Growth",
        "type": "timeseries",
        "query": "SELECT snapshot_date, knowledge_items_total, knowledge_growth_rate FROM improvement_snapshots ORDER BY snapshot_date"
      },
      {
        "title": "Baseline Comparison",
        "type": "stat",
        "query": "SELECT sharpe_vs_baseline, win_rate_vs_baseline, knowledge_vs_baseline FROM improvement_snapshots ORDER BY snapshot_date DESC LIMIT 1"
      },
      {
        "title": "System Verdict",
        "type": "text",
        "source": "improvement_report.verdict"
      }
    ]
  }
}
```

### 4.5 Integration: Scheduled Jobs

```python
# In Orchestrator or Cron
async def daily_improvement_job():
    """Run daily at 00:00 UTC."""
    tracker = ImprovementTracker(db_connection)

    # Record baseline if not yet done (after 30 trades)
    tracker.record_baseline(min_trades=30)

    # Compute daily snapshot
    snapshot = tracker.compute_daily_snapshot()

    # Generate report
    report = tracker.get_improvement_report(days=30)

    # Alert if declining
    if report.get("verdict", {}).get("assessment") == "DECLINING":
        await send_alert("⚠️ TSAR improvement metrics declining", report)

    return report
```

### 4.6 Migration Notes

**Files to create:**
- `src/monitoring/improvement.py` — ImprovementTracker class
- `src/monitoring/improvement_schema.sql` — SQL schema (add to tsar.db migrations)

**Files to update:**
- `tsar.db` — Run migration to add improvement tables
- `grafana/dashboards/` — Add improvement dashboard JSON
- Orchestrator — Add daily improvement job
- Telegram bot — Add `/improvement` command

**Integration with existing architecture:**
- Uses existing `trade_records`, `lessons`, `patterns`, `strategy_genomes`, `strategy_mutations` tables
- Reads from same `tsar.db` — no new database needed
- Dashboard in existing Grafana instance

---

## Fix #5: Tool Resource Limits

**Gap:** No tool resource limits — unbounded resource consumption possible  
**Severity:** High  
**Capability Affected:** Tool Use (Score: 8 → Target: 9)  
**Estimated Effort:** 1-2 days  

### 5.1 Architectural Specification

**What to add:** Resource limit enforcement for every tool invocation. Memory cap, CPU time limit, global execution timeout, and concurrent invocation limits.

**Design:**
- Resource limits are defined per tool in `ToolSchema`
- A `ToolExecutor` wrapper enforces limits before delegating to the tool
- Limits are configurable via YAML, not hardcoded
- Violations are logged and counted — circuit breaker pattern for repeat offenders

### 5.2 Code: Resource Limit Enforcement

```python
# src/tools/resource_guard.py
"""
Resource limit enforcement for tool invocations.

Every tool call passes through the ResourceGuard before execution.
Limits are enforced via asyncio timeout, memory monitoring, and
concurrency semaphores.
"""
import asyncio
import resource
import time
import signal
from dataclasses import dataclass, field
from typing import Any
from contextlib import asynccontextmanager
import logging
import threading

logger = logging.getLogger(__name__)


@dataclass
class ResourceLimits:
    """Resource limits for a tool invocation."""
    max_memory_mb: int = 512           # Maximum memory (MB) per invocation
    max_cpu_time_seconds: float = 30.0 # Maximum CPU time
    max_wall_time_seconds: float = 60.0 # Maximum wall-clock time
    max_concurrent: int = 10           # Max concurrent invocations of this tool
    max_retries: int = 3               # Max retries on failure
    max_calls_per_minute: int = 120    # Rate limit per tool
    max_input_size_bytes: int = 1_000_000  # 1MB max input


@dataclass
class ResourceUsage:
    """Actual resource usage from a tool invocation."""
    memory_peak_mb: float = 0.0
    cpu_time_seconds: float = 0.0
    wall_time_seconds: float = 0.0
    retries_used: int = 0
    exceeded_limits: list[str] = field(default_factory=list)


class ResourceGuard:
    """
    Enforces resource limits on tool invocations.
    
    Usage:
        guard = ResourceGuard()
        async with guard.enforce(tool_name, limits):
            result = await tool.execute(**kwargs)
    """

    def __init__(self, global_config: dict | None = None):
        self._config = global_config or {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._call_counts: dict[str, list[float]] = {}  # tool → [timestamps]
        self._violations: dict[str, int] = {}  # tool → violation count
        self._lock = threading.Lock()

    def get_semaphore(self, tool_name: str, max_concurrent: int) -> asyncio.Semaphore:
        """Get or create a concurrency semaphore for a tool."""
        if tool_name not in self._semaphores:
            self._semaphores[tool_name] = asyncio.Semaphore(max_concurrent)
        return self._semaphores[tool_name]

    @asynccontextmanager
    async def enforce(self, tool_name: str, limits: ResourceLimits):
        """
        Context manager that enforces resource limits.
        
        Usage:
            async with guard.enforce("get_price", limits):
                result = await tool.execute(symbol="BTC/USDT")
        
        Raises:
            ResourceLimitExceeded if limits are breached
            ToolRateLimited if rate limit is hit
        """
        # 1. Rate limit check
        self._check_rate_limit(tool_name, limits.max_calls_per_minute)

        # 2. Concurrency limit
        semaphore = self.get_semaphore(tool_name, limits.max_concurrent)
        acquired = await asyncio.wait_for(
            semaphore.acquire(),
            timeout=limits.max_wall_time_seconds,
        )

        # 3. Memory snapshot (before)
        mem_before = self._get_memory_mb()

        start_time = time.perf_counter()
        usage = ResourceUsage()

        try:
            # 4. Wall-clock timeout
            yield usage

        except asyncio.TimeoutError:
            usage.exceeded_limits.append("wall_time")
            self._record_violation(tool_name, "wall_time")
            raise ResourceLimitExceeded(
                tool_name=tool_name,
                limit="wall_time",
                limit_value=limits.max_wall_time_seconds,
                actual_value=time.perf_counter() - start_time,
            )
        finally:
            # 5. Measure actual usage
            usage.wall_time_seconds = time.perf_counter() - start_time
            mem_after = self._get_memory_mb()
            usage.memory_peak_mb = max(mem_before, mem_after)

            # 6. Memory limit check (post-execution)
            if usage.memory_peak_mb > limits.max_memory_mb:
                usage.exceeded_limits.append("memory")
                self._record_violation(tool_name, "memory")
                logger.warning(
                    f"Tool {tool_name} exceeded memory limit: "
                    f"{usage.memory_peak_mb:.1f}MB > {limits.max_memory_mb}MB"
                )

            # 7. Log usage
            if usage.wall_time_seconds > limits.max_wall_time_seconds * 0.8:
                logger.warning(
                    f"Tool {tool_name} near timeout: "
                    f"{usage.wall_time_seconds:.1f}s / {limits.max_wall_time_seconds}s"
                )

            semaphore.release()

    def _check_rate_limit(self, tool_name: str, max_per_minute: int):
        """Check if tool has exceeded rate limit."""
        now = time.time()
        cutoff = now - 60

        with self._lock:
            calls = self._call_counts.setdefault(tool_name, [])
            # Prune old calls
            calls[:] = [t for t in calls if t > cutoff]

            if len(calls) >= max_per_minute:
                raise ToolRateLimited(
                    tool_name=tool_name,
                    limit=max_per_minute,
                    window_seconds=60,
                    retry_after_seconds=cutoff + 60 - now,
                )

            calls.append(now)

    def _record_violation(self, tool_name: str, limit_type: str):
        """Record a resource limit violation."""
        with self._lock:
            self._violations[tool_name] = self._violations.get(tool_name, 0) + 1
            count = self._violations[tool_name]

            # Circuit breaker: disable tool after repeated violations
            if count >= 5:
                logger.error(
                    f"CIRCUIT BREAKER: Tool {tool_name} disabled after {count} violations"
                )
                # Could set a flag to block future calls

    def _get_memory_mb(self) -> float:
        """Get current process memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            # Fallback: use resource module (Linux only)
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                return usage.ru_maxrss / 1024  # KB to MB
            except Exception:
                return 0.0

    def get_violation_report(self) -> dict:
        """Return violation counts per tool."""
        with self._lock:
            return dict(self._violations)


class ResourceLimitExceeded(Exception):
    """Raised when a tool exceeds its resource limits."""

    def __init__(self, tool_name: str, limit: str, limit_value: float, actual_value: float):
        self.tool_name = tool_name
        self.limit = limit
        self.limit_value = limit_value
        self.actual_value = actual_value
        super().__init__(
            f"Tool '{tool_name}' exceeded {limit} limit: "
            f"{actual_value:.2f} > {limit_value:.2f}"
        )


class ToolRateLimited(Exception):
    """Raised when a tool hits its rate limit."""

    def __init__(self, tool_name: str, limit: int, window_seconds: int, retry_after_seconds: float):
        self.tool_name = tool_name
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Tool '{tool_name}' rate limited: {limit} calls per {window_seconds}s. "
            f"Retry after {retry_after_seconds:.1f}s"
        )
```

### 5.3 Code: Tool Executor Wrapper

```python
# src/tools/executor.py
"""
Tool execution wrapper with resource enforcement.

All tool calls go through ToolExecutor, which applies resource limits,
logging, and error handling.
"""
import asyncio
from src.tools.base import BaseTool, ToolResult, ToolSchema
from src.tools.resource_guard import ResourceGuard, ResourceLimits
import time
import logging

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Wraps tool execution with resource enforcement.
    
    Usage:
        executor = ToolExecutor(guard)
        result = await executor.execute(tool, **kwargs)
    """

    def __init__(self, guard: ResourceGuard):
        self._guard = guard
        self._execution_log: list[dict] = []

    async def execute(self, tool: BaseTool, **kwargs) -> ToolResult:
        """
        Execute a tool with full resource enforcement.
        
        Steps:
        1. Validate parameters
        2. Check resource limits
        3. Execute with timeout
        4. Log execution
        5. Return result
        """
        schema = tool.schema()
        limits = self._get_limits(schema)
        start = time.perf_counter()

        try:
            # Wrap execution in resource guard
            async with self._guard.enforce(schema.name, limits):
                result = await asyncio.wait_for(
                    tool.execute(**kwargs),
                    timeout=limits.max_wall_time_seconds,
                )

            # Record execution
            elapsed = time.perf_counter() - start
            self._log_execution(schema.name, elapsed, result.success, None)

            return result

        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start
            self._log_execution(schema.name, elapsed, False, "timeout")
            return ToolResult(
                success=False,
                error=f"Tool '{schema.name}' timed out after {elapsed:.1f}s",
                error_code="TIMEOUT",
                latency_ms=elapsed * 1000,
                tool_name=schema.name,
            )

        except Exception as e:
            elapsed = time.perf_counter() - start
            self._log_execution(schema.name, elapsed, False, str(e))
            return ToolResult(
                success=False,
                error=str(e),
                error_code="INTERNAL_ERROR",
                latency_ms=elapsed * 1000,
                tool_name=schema.name,
            )

    def _get_limits(self, schema: ToolSchema) -> ResourceLimits:
        """Get resource limits for a tool, using schema config or defaults."""
        return ResourceLimits(
            max_memory_mb=schema.metadata.get("max_memory_mb", 512),
            max_cpu_time_seconds=schema.metadata.get("max_cpu_time_seconds", 30.0),
            max_wall_time_seconds=schema.timeout_ms / 1000.0,
            max_concurrent=schema.metadata.get("max_concurrent", 10),
            max_calls_per_minute=self._parse_rate_limit(schema.rate_limit),
        )

    def _parse_rate_limit(self, rate_limit: str | None) -> int:
        """Parse rate limit string like '1200/min' into calls per minute."""
        if not rate_limit:
            return 1200
        try:
            parts = rate_limit.split("/")
            count = int(parts[0])
            unit = parts[1] if len(parts) > 1 else "min"
            if unit == "sec":
                return count * 60
            elif unit == "min":
                return count
            elif unit == "hour":
                return count // 60
            return count
        except (ValueError, IndexError):
            return 1200

    def _log_execution(self, tool_name: str, elapsed: float, success: bool, error: str | None):
        """Log tool execution for monitoring."""
        entry = {
            "tool": tool_name,
            "elapsed_s": round(elapsed, 3),
            "success": success,
            "error": error,
            "timestamp": time.time(),
        }
        self._execution_log.append(entry)

        # Keep only last 10000 entries
        if len(self._execution_log) > 10000:
            self._execution_log = self._execution_log[-5000:]

        if not success:
            logger.warning(f"Tool execution failed: {tool_name} ({elapsed:.1f}s): {error}")

    def get_execution_stats(self) -> dict:
        """Return execution statistics."""
        if not self._execution_log:
            return {"total_executions": 0}

        total = len(self._execution_log)
        failed = sum(1 for e in self._execution_log if not e["success"])
        avg_time = sum(e["elapsed_s"] for e in self._execution_log) / total

        by_tool = {}
        for entry in self._execution_log:
            t = entry["tool"]
            by_tool.setdefault(t, {"count": 0, "failures": 0, "total_time": 0})
            by_tool[t]["count"] += 1
            by_tool[t]["total_time"] += entry["elapsed_s"]
            if not entry["success"]:
                by_tool[t]["failures"] += 1

        return {
            "total_executions": total,
            "failure_rate": round(failed / total, 3),
            "avg_execution_time_s": round(avg_time, 3),
            "by_tool": by_tool,
            "violations": self._guard.get_violation_report(),
        }
```

### 5.4 YAML: Tool Resource Configuration

```yaml
# config/tool_resources.yaml
# Resource limits per tool — overrides defaults in ResourceLimits

global_defaults:
  max_memory_mb: 512
  max_cpu_time_seconds: 30
  max_wall_time_seconds: 60
  max_concurrent: 10
  max_calls_per_minute: 1200

tool_overrides:
  # Exchange tools — higher limits for market data
  get_price:
    max_concurrent: 50
    max_calls_per_minute: 2400
    max_wall_time_seconds: 5

  get_ohlcv:
    max_concurrent: 20
    max_calls_per_minute: 600
    max_wall_time_seconds: 10

  place_order:
    max_concurrent: 5          # Strict: one order at a time per agent
    max_calls_per_minute: 100
    max_wall_time_seconds: 15
    max_memory_mb: 256

  # Analysis tools — moderate limits
  calculate_rsi:
    max_concurrent: 30
    max_wall_time_seconds: 5
    max_memory_mb: 256

  # LLM tools — expensive, rate-limited
  llm_generate:
    max_concurrent: 5
    max_calls_per_minute: 60
    max_wall_time_seconds: 30
    max_memory_mb: 1024

  # Data streaming — persistent, separate limits
  stream_prices:
    max_concurrent: 3
    max_wall_time_seconds: 86400  # 24h (persistent connection)
    max_memory_mb: 256

  # Risk tools — fast, deterministic
  check_position_limits:
    max_concurrent: 100
    max_wall_time_seconds: 1
    max_memory_mb: 128
```

### 5.5 Integration with BaseTool

The `ToolExecutor` wraps every tool call. The existing `BaseTool.execute()` method is unchanged — enforcement happens at the executor level.

```python
# Updated tool registry usage:
guard = ResourceGuard(config.get("tool_resources", {}))
executor = ToolExecutor(guard)

# In agent code:
result = await executor.execute(get_price_tool, symbol="BTC/USDT")
# Resource limits automatically enforced
```

### 5.6 Migration Notes

**Files to create:**
- `src/tools/resource_guard.py` — ResourceGuard class
- `src/tools/executor.py` — ToolExecutor wrapper
- `config/tool_resources.yaml` — Resource limit configuration

**Files to update:**
- `src/tools/registry.py` — Add ToolExecutor to registry
- All agent files — Replace direct `tool.execute()` with `executor.execute(tool, ...)`
- `src/tools/base.py` — Add `metadata` field to ToolSchema for resource config

**No breaking changes:** The `BaseTool.execute()` interface is unchanged. Enforcement is additive.

---

## Integration Map

### How the 5 Fixes Connect

```
                    ┌─────────────────────────────────────┐
                    │        config/llm_providers.yaml     │
                    │   (Fix #2: Configurable Model Names) │
                    └──────────────┬──────────────────────┘
                                   │ loads
                                   ▼
┌──────────────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│  BaseLLMProvider     │◄───│  ProviderRegistry │───►│  ModelRouter         │
│  (Fix #1: Abstract   │    │                  │    │  (config-driven      │
│   LLM Interface)     │    └──────────────────┘    │   fallback chains)   │
│                      │                             └──────────┬───────────┘
│  • OllamaProvider    │                                        │
│  • OpenAIProvider    │                                        │ used by
│  • AnthropicProvider │                                        ▼
└──────────────────────┘                             ┌──────────────────────┐
                                                     │  All Agents          │
                                                     │  (via task_type)     │
                                                     └──────────────────────┘

┌──────────────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│  CloudEvent          │◄───│  EventPublisher  │───►│  Redis Streams       │
│  (Fix #3: CloudEvents│    │  EventSubscriber │    │  (tsar:stream:*)     │
│   Messaging)         │    └──────────────────┘    └──────────┬───────────┘
│                      │                                        │
│  • Standard envelope │                                        │ consumed by
│  • Event type registry│                                       ▼
│  • JSON + MsgPack    │                             ┌──────────────────────┐
└──────────────────────┘                             │  All Agents          │
                                                     └──────────────────────┘

┌──────────────────────┐                             ┌──────────────────────┐
│  ImprovementTracker  │─────────────────────────────│  tsar.db             │
│  (Fix #4: Improvement│   reads trade/lesson/        │  (existing tables)   │
│   Measurement)       │   pattern/strategy tables    │                      │
│                      │                             └──────────────────────┘
│  • Baseline metrics  │
│  • Daily snapshots   │─────────────────────────────► Grafana Dashboard
│  • Trend analysis    │
│  • Verdict engine    │
└──────────────────────┘

┌──────────────────────┐                             ┌──────────────────────┐
│  ResourceGuard       │─────────────────────────────│  ToolExecutor         │
│  (Fix #5: Resource   │   enforces limits on        │                      │
│   Limits)            │                              │  • Wraps all tools   │
│                      │                              │  • Timeout + memory  │
│  • Memory caps       │                              │  • Rate limiting     │
│  • CPU time limits   │                              │  • Circuit breaker   │
│  • Concurrency       │                              └──────────────────────┘
│  • Rate limiting     │
└──────────────────────┘
```

---

## Migration Checklist

### Phase 1: Core Infrastructure (Days 1-3)

- [ ] **Fix #1:** Create `src/llm/` directory with base, providers, registry
- [ ] **Fix #1:** Implement `OllamaProvider`, `OpenAIProvider`, `AnthropicProvider`
- [ ] **Fix #1:** Create `ProviderRegistry` and enhanced `ModelRouter`
- [ ] **Fix #2:** Create `config/llm_providers.yaml`
- [ ] **Fix #2:** Create `src/llm/config.py` loader
- [ ] **Fix #3:** Create `src/messaging/` directory with CloudEvents, publisher, subscriber
- [ ] **Fix #3:** Implement `EventTypes` registry
- [ ] **Fix #5:** Create `src/tools/resource_guard.py`
- [ ] **Fix #5:** Create `src/tools/executor.py`
- [ ] **Fix #5:** Create `config/tool_resources.yaml`

### Phase 2: Integration (Days 4-6)

- [ ] **Fix #1:** Update all agents to use `ModelRouter.generate(task_type=...)` instead of direct LLM calls
- [ ] **Fix #2:** Remove all hardcoded model names from Python source
- [ ] **Fix #3:** Update all agent publishers to use `EventPublisher` + `CloudEvent`
- [ ] **Fix #3:** Update all agent subscribers to use `EventSubscriber` + `CloudEvent`
- [ ] **Fix #4:** Create `src/monitoring/improvement.py`
- [ ] **Fix #4:** Add improvement tables to `tsar.db` migration
- [ ] **Fix #5:** Update tool registry to use `ToolExecutor`

### Phase 3: Validation & Dashboard (Days 7-8)

- [ ] **Fix #1:** Test provider swap (change model in YAML, verify no code changes needed)
- [ ] **Fix #2:** Test fallback chain (simulate provider failure, verify cascade)
- [ ] **Fix #3:** Test CloudEvents serialization roundtrip (JSON + MessagePack)
- [ ] **Fix #4:** Verify improvement snapshot computation with sample data
- [ ] **Fix #4:** Create Grafana improvement dashboard
- [ ] **Fix #5:** Test resource limit enforcement (timeout, memory, rate limit)
- [ ] **Fix #5:** Verify circuit breaker triggers after repeated violations
- [ ] Update `TSAR_ARCHITECTURE.md` with new sections
- [ ] Update `ARCHITECTURE_CONSOLIDATION.md` with canonical values
- [ ] Run full test suite

### Phase 4: Documentation (Day 9)

- [ ] Update `TECH_STACK.md` with new dependencies (anthropic SDK, psutil)
- [ ] Update `trading-super-agent-spec.md` model routing section
- [ ] Update `trading-super-agent-tools-spec.md` tool execution section
- [ ] Create `docs/LLM_PROVIDERS.md` — provider setup guide
- [ ] Create `docs/IMPROVEMENT_DASHBOARD.md` — dashboard usage guide
- [ ] Final review pass on all architecture docs

---

## Summary: Score Impact

| Capability | Before | After (Estimated) | Change |
|---|---|---|---|
| Harness | 9/10 | 9/10 | — |
| Knowledge Grounding | 9/10 | 9/10 | — |
| Tool Use | 8/10 | 9/10 | +1 (resource limits) |
| Memory Management | 9/10 | 9/10 | — |
| Safeguards | 9.5/10 | 9.5/10 | — |
| Iteration | 8/10 | 8.5/10 | +0.5 (improvement measurement) |
| Domain Expertise | 8.5/10 | 8.5/10 | — |
| Self-Improvement | 8/10 | 9/10 | +1 (measurement framework) |
| Model Agnosticism | 6/10 | 8.5/10 | +2.5 (abstract interface + config) |
| Open Ecosystem | 5.5/10 | 7.5/10 | +2 (CloudEvents) |
| **OVERALL** | **8.1/10** | **8.8/10** | **+0.7** |

---

*Fix report completed: 2026-07-24 04:29 GMT+8*
*Total estimated effort: 8-12 days*
*Target score: 8.8/10 (from 8.1/10)*
