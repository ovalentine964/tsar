"""
TSAR LLM Module — Model-agnostic LLM routing and management.

ZERO model names in source code. All routing via task_type.

Components:
  - Router:  Task-type → model resolution with fallback chains
  - Prompts: Prompt templates for each task type
  - Cache:   Response caching for repeated queries
"""

from src.llm.evaluation import LLMEvaluator
from src.llm.prompts import get_max_tokens, get_prompt, get_system_prompt
from src.llm.router import ModelRouter
from src.llm.token_counter import count_tokens, count_tokens_batch

__all__: list[str] = [
    "LLMEvaluator",
    "ModelRouter",
    "count_tokens",
    "count_tokens_batch",
    "get_max_tokens",
    "get_prompt",
    "get_system_prompt",
]
