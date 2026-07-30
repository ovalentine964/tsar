"""
OllamaProvider — Local LLM via Ollama.

Day1 primary LLM provider. Runs models locally (qwen2.5:7b, llama3.1:8b).
Zero cost, low latency, full privacy.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from src.interfaces.llm_provider import LLMProvider
from src.interfaces.types import (
    LLMChunk,
    LLMResponse,
    ModelCapabilities,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Default model capabilities by model name substring
_MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "qwen2.5": {
        "max_context_tokens": 32768,
        "supports_function_calling": True,
        "supports_json_mode": True,
    },
    "llama3": {
        "max_context_tokens": 131072,
        "supports_function_calling": True,
        "supports_json_mode": True,
    },
}


class OllamaProvider(LLMProvider):
    """LLM provider using local Ollama instance.

    Connects to Ollama's HTTP API at ``base_url``.  Supports all
    abstract methods of :class:`LLMProvider`.

    Args:
        base_url: Ollama HTTP endpoint (default ``http://localhost:11434``).
        default_model: Model to use when caller doesn't specify one via kwargs.
        timeout_s: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "qwen2.5:7b",
        timeout_s: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout_s
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle helpers (not part of the ABC, but useful for setup)
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the underlying HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )
        logger.info("OllamaProvider initialized (base_url=%s)", self._base_url)

    async def shutdown(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Generate a complete response from Ollama.

        Keyword Args:
            model (str): Ollama model name (default ``qwen2.5:7b``).
            system (str): System prompt.
            temperature (float): Sampling temperature.
            max_tokens (int): Max tokens to predict.
            stop (list[str]): Stop sequences.

        Returns:
            LLMResponse with content, token counts, and metadata.
        """
        self._ensure_client()
        model: str = kwargs.get("model", self._default_model)
        system: str = kwargs.get("system", "")
        temperature: float = kwargs.get("temperature", 0.3)
        max_tokens: int = kwargs.get("max_tokens", 1024)
        stop: list[str] | None = kwargs.get("stop")

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system
        if stop:
            payload["options"]["stop"] = stop

        start = time.monotonic()
        assert self._client is not None
        response = await self._client.post("/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        latency_ms = (time.monotonic() - start) * 1000

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=data.get("response", ""),
            model=model,
            provider="ollama",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            finish_reason="stop" if data.get("done") else "length",
            metadata={
                "eval_duration_ns": data.get("eval_duration", 0),
                "prompt_eval_duration_ns": data.get("prompt_eval_duration", 0),
            },
        )

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[LLMChunk]:
        """Stream a response from Ollama chunk by chunk.

        Yields:
            LLMChunk objects with incremental content.
        """
        self._ensure_client()
        model: str = kwargs.get("model", self._default_model)
        system: str = kwargs.get("system", "")
        temperature: float = kwargs.get("temperature", 0.3)
        max_tokens: int = kwargs.get("max_tokens", 1024)
        stop: list[str] | None = kwargs.get("stop")

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system
        if stop:
            payload["options"]["stop"] = stop

        assert self._client is not None
        chunk_index = 0
        async with self._client.stream("POST", "/api/generate", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                content = data.get("response", "")
                done = data.get("done", False)
                yield LLMChunk(
                    content=content,
                    chunk_index=chunk_index,
                    finish_reason="stop" if done else None,
                    metadata={"model": model},
                )
                chunk_index += 1

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (falls back to heuristic).

        Ollama does not expose a tokenizer endpoint. Uses tiktoken
        for accurate counting with cl100k_base as approximation.
        """
        from src.llm.token_counter import count_tokens
        return count_tokens(text, model=self._default_model)

    def get_capabilities(self) -> ModelCapabilities:
        """Return capabilities for the default model."""
        model = self._default_model
        caps = _MODEL_CAPABILITIES.get("qwen2.5", {})
        for key, val in _MODEL_CAPABILITIES.items():
            if key in model:
                caps = val
                break

        return ModelCapabilities(
            model=model,
            max_context_tokens=caps.get("max_context_tokens", 32768),
            supports_streaming=True,
            supports_function_calling=caps.get("supports_function_calling", False),
            supports_json_mode=caps.get("supports_json_mode", False),
            supports_vision=False,
            cost_per_1k_input_tokens=0.0,
            cost_per_1k_output_tokens=0.0,
            avg_latency_ms=500.0,
        )

    async def health_check(self) -> bool:
        """Check if Ollama is running and responsive.

        Returns:
            True if Ollama responds to ``/api/tags``.
        """
        try:
            assert self._client is not None
            resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Lazily initialize the HTTP client if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
