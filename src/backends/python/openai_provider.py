"""
OpenAIProvider — Cloud LLM via OpenAI API.

Optional fallback provider for Tier 2 and Tier 3 tasks.
Uses the standard OpenAI Python SDK.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from src.interfaces.llm_provider import LLMProvider
from src.interfaces.types import (
    LLMChunk,
    LLMResponse,
    ModelCapabilities,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """LLM provider using OpenAI's API.

    Args:
        api_key: OpenAI API key (falls back to ``OPENAI_API_KEY`` env var).
        base_url: API base URL.
        default_model: Default model identifier.
        timeout_s: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o-mini",
        timeout_s: int = 60,
        provider_name: str = "openai",
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url
        self._default_model = default_model
        self._timeout = timeout_s
        self._provider_name = provider_name
        self._client: Any = None  # openai.AsyncOpenAI

    # ------------------------------------------------------------------
    # Cost tables (USD per 1k tokens)
    # ------------------------------------------------------------------

    _COST_TABLE: dict[str, dict[str, float]] = {
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        # NVIDIA NIM free-tier models
        "deepseek-ai/deepseek-r1": {"input": 0.0, "output": 0.0},
        "nvidia/nemotron-3-ultra": {"input": 0.0, "output": 0.0},
        "nvidia/nv-embed-v2": {"input": 0.0, "output": 0.0},
        "minimaxai/minimax-m3": {"input": 0.0, "output": 0.0},
    }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the async OpenAI client."""
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )
        logger.info("OpenAIProvider initialized")

    async def shutdown(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Generate a complete response from OpenAI.

        Keyword Args:
            model (str): Model identifier.
            system (str): System prompt.
            temperature (float): Sampling temperature.
            max_tokens (int): Maximum tokens to generate.
            stop (list[str]): Stop sequences.
            json_mode (bool): Request JSON output format.

        Returns:
            LLMResponse with content, token counts, cost, and metadata.
        """
        self._ensure_client()
        model: str = kwargs.get("model", self._default_model)
        system: str = kwargs.get("system", "")
        temperature: float = kwargs.get("temperature", 0.3)
        max_tokens: int = kwargs.get("max_tokens", 4096)
        stop: list[str] | None = kwargs.get("stop")
        json_mode: bool = kwargs.get("json_mode", False)

        messages = self._build_messages(prompt, system)

        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            create_kwargs["stop"] = stop
        if json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}

        start = time.monotonic()
        assert self._client is not None
        response = await self._client.chat.completions.create(**create_kwargs)
        latency_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        return LLMResponse(
            content=choice.message.content or "",
            model=model,
            provider=self._provider_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason or "stop",
            metadata={"cost_usd": self._estimate_cost(prompt_tokens, completion_tokens, model)},
        )

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[LLMChunk]:
        """Stream a response from OpenAI chunk by chunk.

        Yields:
            LLMChunk objects with incremental content.
        """
        self._ensure_client()
        model: str = kwargs.get("model", self._default_model)
        system: str = kwargs.get("system", "")
        temperature: float = kwargs.get("temperature", 0.3)
        max_tokens: int = kwargs.get("max_tokens", 4096)
        stop: list[str] | None = kwargs.get("stop")
        json_mode: bool = kwargs.get("json_mode", False)

        messages = self._build_messages(prompt, system)

        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if stop:
            create_kwargs["stop"] = stop
        if json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}

        assert self._client is not None
        stream = await self._client.chat.completions.create(**create_kwargs)

        chunk_index = 0
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield LLMChunk(
                    content=delta.content,
                    chunk_index=chunk_index,
                    finish_reason=None,
                    metadata={"model": model},
                )
                chunk_index += 1

        # Final chunk with finish reason
        yield LLMChunk(
            content="",
            chunk_index=chunk_index,
            finish_reason="stop",
            metadata={"model": model},
        )

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (falls back to heuristic)."""
        from src.llm.token_counter import count_tokens
        return count_tokens(text, model=self._default_model)

    def get_capabilities(self) -> ModelCapabilities:
        """Return capabilities for the default OpenAI model."""
        model = self._default_model
        cost = self._COST_TABLE.get(model, {"input": 0.0, "output": 0.0})

        context_windows: dict[str, int] = {
            "gpt-4o-mini": 128000,
            "gpt-4o": 128000,
            "gpt-4-turbo": 128000,
            "gpt-3.5-turbo": 16385,
        }

        return ModelCapabilities(
            model=model,
            max_context_tokens=context_windows.get(model, 128000),
            supports_streaming=True,
            supports_function_calling=True,
            supports_json_mode=True,
            supports_vision="4o" in model or "4-turbo" in model,
            cost_per_1k_input_tokens=cost["input"],
            cost_per_1k_output_tokens=cost["output"],
            avg_latency_ms=2000.0,
        )

    async def health_check(self) -> bool:
        """Check if the OpenAI API is reachable.

        Returns:
            True if the models endpoint responds.
        """
        try:
            assert self._client is not None
            await self._client.models.list()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Lazily initialize the client."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )

    @staticmethod
    def _build_messages(prompt: str, system: str) -> list[dict[str, str]]:
        """Build the OpenAI-style messages list."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        """Estimate cost in USD for a request."""
        cost = self._COST_TABLE.get(model, {"input": 0.0, "output": 0.0})
        return (prompt_tokens * cost["input"] + completion_tokens * cost["output"]) / 1000
