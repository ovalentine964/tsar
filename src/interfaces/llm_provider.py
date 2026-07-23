"""
TSAR Interface — LLMProvider Abstract Base Class.

Abstracts all LLM calls. No direct provider SDK calls anywhere in the
codebase. Zero model names in source code — all routing via task_type.

Day1: OllamaProvider (local Ollama)
Level 2: LiteLLMRouter (multi-provider routing)
Additional: OpenAIProvider, AnthropicProvider, DeepSeekProvider
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from typing import Any

from src.interfaces.types import (
    LLMChunk,
    LLMResponse,
    ModelCapabilities,
)


class LLMProvider(abc.ABC):
    """Abstract interface for LLM (Large Language Model) providers.

    All LLM communication flows through this interface.
    Agents NEVER import ollama, openai, anthropic, or any provider SDK directly.

    Design principles (from TSAR_ARCHITECTURE.md §8.1):
    - Zero model names in code — code references task_type only.
    - Single config source — config/models.yaml defines everything.
    - Capability-aware — models declare what they can do.
    - Fail-safe — every call has a fallback chain.
    - Observable — every LLM call tracked (latency, tokens, cost).

    Implementations:
    - OllamaProvider: Local Ollama (Day1)
    - OpenAIProvider: OpenAI API
    - AnthropicProvider: Anthropic API
    - DeepSeekProvider: DeepSeek API
    """

    # ═══════════════════════════════════════════════════════════════
    # GENERATION
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a complete response from the LLM.

        This is the primary generation method. Blocks until the full
        response is received.

        Args:
            prompt: The input prompt text.
            **kwargs: Provider-specific parameters:
                model (str): Model identifier override.
                system (str): System prompt.
                temperature (float): Sampling temperature (0.0-2.0).
                max_tokens (int): Maximum tokens to generate.
                stop (list[str]): Stop sequences.
                json_mode (bool): Request JSON output format.

        Returns:
            LLMResponse with generated content, token counts, and metadata.

        Raises:
            LLMTimeoutError: Response exceeded timeout.
            LLMRateLimitError: Provider rate limit exceeded.
            LLMAuthenticationError: Invalid API key.
        """
        ...

    @abc.abstractmethod
    async def stream(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        """Stream a response from the LLM chunk by chunk.

        Yields chunks as they arrive from the provider, enabling
        real-time display and early termination.

        Args:
            prompt: The input prompt text.
            **kwargs: Same as generate().

        Yields:
            LLMChunk objects with incremental content.

        Raises:
            LLMTimeoutError: Stream exceeded timeout.
            LLMRateLimitError: Provider rate limit exceeded.
        """
        ...
        # Needed for AsyncIterator return type with @abstractmethod
        yield  # type: ignore[misc]  # pragma: no cover

    # ═══════════════════════════════════════════════════════════════
    # TOKENIZATION
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in a text string.

        Used for context window management and cost estimation.
        Must return a reasonable estimate even if exact tokenization
        is not available (e.g. len(text) / 4 as fallback).

        Args:
            text: Text to tokenize.

        Returns:
            Number of tokens.
        """
        ...

    # ═══════════════════════════════════════════════════════════════
    # CAPABILITIES & HEALTH
    # ═══════════════════════════════════════════════════════════════

    @abc.abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """Get the capabilities of this LLM provider.

        Used by the ModelRouter to match task requirements to available
        providers. Capabilities include context window size, streaming
        support, function calling, JSON mode, vision, and cost.

        Returns:
            ModelCapabilities describing what this provider can do.
        """
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM provider is available and responsive.

        Performs a lightweight call to verify the provider is reachable.
        Used by the watchdog and orchestrator for health monitoring.

        Returns:
            True if the provider is healthy, False otherwise.
        """
        ...
