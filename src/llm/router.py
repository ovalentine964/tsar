"""
ModelRouter — Task-type to model resolution with fallback chains.

Agents call: ``router.generate(task_type="t2_signal_narrative", prompt=...)``
Router resolves task_type → (provider, model) from config/models.yaml.
Supports fallback chains with circuit breaker and cost tracking.

Zero model names in agent code — all routing via task_type.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import yaml

from src.backends.python.deepseek_provider import DeepSeekProvider
from src.backends.python.ollama_provider import OllamaProvider
from src.backends.python.openai_provider import OpenAIProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.interfaces.llm_provider import LLMProvider
    from src.interfaces.types import LLMChunk, LLMResponse

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker.

    Tracks consecutive failures and transitions between states.
    """

    failure_threshold: int = 5
    recovery_timeout_s: float = 60.0
    half_open_max_calls: int = 1

    _state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _consecutive_failures: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _half_open_calls: int = field(default=0, repr=False)

    @property
    def state(self) -> CircuitState:
        """Get current state, transitioning OPEN → HALF_OPEN if recovery timeout elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN

    def record_success(self) -> None:
        """Record a successful call — resets the breaker."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — may trip the breaker."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN after %d failures", self._consecutive_failures)


# ═══════════════════════════════════════════════════════════════════════
# Cost Tracker
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CostTracker:
    """Tracks cumulative LLM costs per provider and total.

    Attributes:
        total_cost_usd: Running total cost.
        call_count: Total number of calls.
        per_provider: Cost breakdown by provider name.
    """

    total_cost_usd: float = 0.0
    call_count: int = 0
    per_provider: dict[str, float] = field(default_factory=dict)

    def record(self, provider: str, cost_usd: float) -> None:
        """Record cost for a single call."""
        self.total_cost_usd += cost_usd
        self.call_count += 1
        self.per_provider[provider] = self.per_provider.get(provider, 0.0) + cost_usd

    def summary(self) -> dict[str, Any]:
        """Return a summary dict."""
        return {
            "total_cost_usd": round(self.total_cost_usd, 6),
            "call_count": self.call_count,
            "per_provider": {k: round(v, 6) for k, v in self.per_provider.items()},
        }


# ═══════════════════════════════════════════════════════════════════════
# Model Router
# ═══════════════════════════════════════════════════════════════════════

# Maps provider type strings from config to provider classes
_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai_compatible": DeepSeekProvider,  # Default for openai_compatible; overridden by name
}


def _create_provider(name: str, provider_cfg: dict[str, Any]) -> LLMProvider:
    """Instantiate a provider from config.

    Args:
        name: Provider name (e.g. "ollama", "deepseek", "openai").
        provider_cfg: Provider config dict from models.yaml.

    Returns:
        An initialized LLMProvider instance.
    """
    ptype = provider_cfg.get("type", name)

    if name == "ollama" or ptype == "ollama":
        return OllamaProvider(
            base_url=provider_cfg.get("base_url", "http://localhost:11434"),
            timeout_s=provider_cfg.get("timeout_s", 30),
        )
    elif name == "deepseek" or (ptype == "openai_compatible" and "deepseek" in name):
        return DeepSeekProvider(
            api_key=provider_cfg.get("api_key", ""),
            base_url=provider_cfg.get("base_url", "https://api.deepseek.com"),
            timeout_s=provider_cfg.get("timeout_s", 60),
        )
    elif name == "openai" or (ptype == "openai_compatible" and "openai" in name):
        return OpenAIProvider(
            api_key=provider_cfg.get("api_key", ""),
            base_url=provider_cfg.get("base_url", "https://api.openai.com/v1"),
            timeout_s=provider_cfg.get("timeout_s", 60),
            provider_name="openai",
        )
    elif name == "nvidia_nim":
        # NVIDIA NIM uses OpenAI-compatible API — use OpenAIProvider with custom base
        return OpenAIProvider(
            api_key=provider_cfg.get("api_key", ""),
            base_url=provider_cfg.get("base_url", "https://integrate.api.nvidia.com/v1"),
            timeout_s=provider_cfg.get("timeout_s", 60),
            provider_name="nvidia_nim",
        )
    else:
        raise ValueError(f"Unknown provider: {name} (type={ptype})")


class ModelRouter:
    """Route LLM requests by task_type with fallback chains and circuit breakers.

    The router reads ``config/models.yaml`` and resolves each ``task_type``
    to a primary provider+model, with automatic fallback to alternatives
    when the primary fails.

    Args:
        config: Parsed models.yaml config dict.  If None, loads from default path.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if config is None:
            config = self._load_default_config()
        self._config = config
        self._routing: dict[str, Any] = config.get("routing", {})
        self._providers_cfg: dict[str, Any] = config.get("providers", {})
        self._models_cfg: dict[str, Any] = config.get("models", {})

        # Lazy-initialized provider instances keyed by provider name
        self._providers: dict[str, LLMProvider] = {}

        # Circuit breakers per provider
        cb_cfg = config.get("circuit_breaker", {})
        self._breakers: dict[str, CircuitBreaker] = {}
        self._cb_kwargs = {
            "failure_threshold": cb_cfg.get("failure_threshold", 5),
            "recovery_timeout_s": cb_cfg.get("recovery_timeout_s", 60),
            "half_open_max_calls": cb_cfg.get("half_open_max_calls", 1),
        }

        # Cost tracking
        self.cost_tracker = CostTracker()

        # Ollama fallback tracking (H-004)
        self._ollama_fallback_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion for the given task type.

        Resolves ``task_type`` to a provider+model, tries the primary
        first, then falls back through the chain on failure.

        Args:
            task_type: Task type key (e.g. ``"t2_signal_narrative"``).
            prompt: User prompt text.
            system_prompt: System prompt text.
            **kwargs: Override parameters (max_tokens, temperature, etc.).

        Returns:
            LLMResponse from the first successful provider.

        Raises:
            RuntimeError: All providers in the fallback chain failed.
            ValueError: Unknown task_type.
        """
        route = self._resolve_route(task_type)
        chain = [route["primary"]] + route.get("fallback", [])
        params = route.get("params", {})
        merged = {**params, **kwargs}

        last_error: Exception | None = None
        for model_path in chain:
            provider, model_name = self._get_provider_and_model(model_path)
            provider_name = model_path.split("/")[0]

            breaker = self._get_breaker(provider_name)
            if not breaker.allow_request():
                logger.warning("Circuit breaker OPEN for %s — skipping", provider_name)
                continue

            try:
                merged["model"] = model_name
                if system_prompt:
                    merged["system"] = system_prompt

                response = await provider.generate(prompt, **merged)

                # Track cost
                cost = response.metadata.get("cost_usd", 0.0)
                self.cost_tracker.record(provider_name, cost)

                breaker.record_success()
                return response

            except Exception as exc:
                last_error = exc
                breaker.record_failure()
                logger.warning(
                    "Provider %s failed for %s: %s — trying fallback",
                    provider_name, task_type, exc,
                )
                continue

        raise RuntimeError(
            f"All providers failed for task_type={task_type}. "
            f"Last error: {last_error}"
        )

    async def stream(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        """Stream a completion for the given task type.

        Args:
            task_type: Task type key.
            prompt: User prompt text.
            system_prompt: System prompt text.
            **kwargs: Override parameters.

        Yields:
            LLMChunk objects from the provider.
        """
        route = self._resolve_route(task_type)
        chain = [route["primary"]] + route.get("fallback", [])
        params = route.get("params", {})
        merged = {**params, **kwargs}

        for model_path in chain:
            provider, model_name = self._get_provider_and_model(model_path)
            provider_name = model_path.split("/")[0]

            breaker = self._get_breaker(provider_name)
            if not breaker.allow_request():
                logger.warning("Circuit breaker OPEN for %s — skipping", provider_name)
                continue

            try:
                merged["model"] = model_name
                if system_prompt:
                    merged["system"] = system_prompt

                chunk_index = 0
                async for chunk in provider.stream(prompt, **merged):
                    yield chunk
                    chunk_index += 1

                breaker.record_success()
                return  # Successfully streamed

            except Exception as exc:
                breaker.record_failure()
                logger.warning(
                    "Provider %s stream failed for %s: %s — trying fallback",
                    provider_name, task_type, exc,
                )
                continue

        raise RuntimeError(f"All providers failed for stream task_type={task_type}")

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all initialized providers.

        Returns:
            Dict mapping provider name to health status.
        """
        results: dict[str, bool] = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results

    async def initialize_all(self) -> None:
        """Initialize all configured providers.

        Creates provider instances and calls their ``initialize()`` methods.
        """
        for name, cfg in self._providers_cfg.items():
            if name not in self._providers:
                try:
                    provider = _create_provider(name, cfg)
                    await provider.initialize()
                    self._providers[name] = provider
                    logger.info("Initialized provider: %s", name)
                except Exception:
                    logger.exception("Failed to initialize provider: %s", name)

    async def shutdown_all(self) -> None:
        """Shutdown all providers gracefully."""
        for name, provider in self._providers.items():
            try:
                await provider.shutdown()
                logger.info("Shutdown provider: %s", name)
            except Exception:
                logger.exception("Error shutting down provider: %s", name)
        self._providers.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_route(self, task_type: str) -> dict[str, Any]:
        """Look up the routing config for a task type."""
        route = self._routing.get(task_type)
        if not route:
            raise ValueError(f"Unknown task_type: {task_type}")
        return route

    def _get_provider_and_model(self, model_path: str) -> tuple[LLMProvider, str]:
        """Resolve a model path like 'ollama/qwen2.5:7b' to (provider, model_name)."""
        parts = model_path.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid model path: {model_path} (expected 'provider/model')")

        provider_name, model_name = parts

        if provider_name not in self._providers:
            cfg = self._providers_cfg.get(provider_name)
            if not cfg:
                raise ValueError(f"No provider config for: {provider_name}")
            provider = _create_provider(provider_name, cfg)
            self._providers[provider_name] = provider
            # Note: caller should ensure initialize() is called
            # For lazy init, we rely on the provider's _ensure_client pattern

        return self._providers[provider_name], model_name

    def _get_breaker(self, provider_name: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a provider."""
        if provider_name not in self._breakers:
            self._breakers[provider_name] = CircuitBreaker(**self._cb_kwargs)
        return self._breakers[provider_name]

    def get_router_status(self) -> dict[str, Any]:
        """Get router status including fallback chain health.

        Returns:
            Dict with provider health, circuit breaker states,
            and fallback chain status.
        """
        breaker_states = {}
        for name, breaker in self._breakers.items():
            breaker_states[name] = {
                "state": breaker.state.value,
                "consecutive_failures": breaker._consecutive_failures,
            }

        return {
            "initialized_providers": list(self._providers.keys()),
            "circuit_breakers": breaker_states,
            "cost_tracker": self.cost_tracker.summary(),
            "ollama_fallback_count": self._ollama_fallback_count,
        }

    @staticmethod
    def _load_default_config() -> dict[str, Any]:
        """Load config from the default path."""
        import os

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "models.yaml"
        )
        config_path = os.path.normpath(config_path)
        with open(config_path) as f:
            return yaml.safe_load(f)
