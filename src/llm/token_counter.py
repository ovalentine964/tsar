"""TSAR — Accurate Token Counting (M-011).

Replaces the `len(text) // 4` heuristic with tiktoken for accurate
token counts. Falls back to the heuristic if tiktoken is unavailable.

Usage::

    from src.llm.token_counter import count_tokens, count_tokens_batch

    n = count_tokens("Hello world", model="gpt-4o")
    n = count_tokens("你好世界", model="deepseek-chat")
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Lazy-loaded tiktoken encoders
_tiktoken_available: bool | None = None


def _check_tiktoken() -> bool:
    global _tiktoken_available
    if _tiktoken_available is None:
        try:
            import tiktoken  # noqa: F401
            _tiktoken_available = True
        except ImportError:
            _tiktoken_available = False
            logger.debug("tiktoken not installed — falling back to heuristic token counting")
    return _tiktoken_available


# Model → tiktoken encoding name mapping
_MODEL_ENCODING_MAP: dict[str, str] = {
    # OpenAI models
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    # DeepSeek (cl100k_base is close enough)
    "deepseek-chat": "cl100k_base",
    "deepseek-coder": "cl100k_base",
    "deepseek-reasoner": "cl100k_base",
    # Qwen/Llama (cl100k_base is a reasonable approximation)
    "qwen2.5": "cl100k_base",
    "qwen": "cl100k_base",
    "llama": "cl100k_base",
    "llama3": "cl100k_base",
}


@lru_cache(maxsize=8)
def _get_encoder(model: str = "") -> object | None:
    """Get tiktoken encoder for a model. Returns None if unavailable."""
    if not _check_tiktoken():
        return None

    import tiktoken

    # Try direct model encoding first
    try:
        return tiktoken.encoding_for_model(model)
    except (KeyError, Exception):
        pass

    # Try mapped encoding
    for prefix, enc_name in _MODEL_ENCODING_MAP.items():
        if prefix in model.lower():
            try:
                return tiktoken.get_encoding(enc_name)
            except Exception:
                pass

    # Default fallback encoding
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str, model: str = "") -> int:
    """Count tokens accurately using tiktoken.

    Args:
        text: Text to tokenize.
        model: Model name (used to select the right encoding).

    Returns:
        Number of tokens.
    """
    if not text:
        return 0

    encoder = _get_encoder(model)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass

    # Fallback heuristic: ~4 chars per token (conservative for mixed content)
    return max(1, len(text) // 4)


def count_tokens_batch(texts: list[str], model: str = "") -> list[int]:
    """Count tokens for multiple texts.

    Args:
        texts: List of texts to tokenize.
        model: Model name.

    Returns:
        List of token counts.
    """
    return [count_tokens(t, model) for t in texts]
