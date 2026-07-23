"""
TSAR LLM Module — Model-agnostic LLM routing and management.

ZERO model names in source code. All routing via task_type.

Components:
  - Router:  Task-type → model resolution with fallback chains
  - Prompts: Prompt templates for each task type
  - Cache:   Response caching for repeated queries
"""

from src.llm.prompts import get_prompt, get_system_prompt
from src.llm.router import ModelRouter

__all__: list[str] = [
    "ModelRouter",
    "get_prompt",
    "get_system_prompt",
]
