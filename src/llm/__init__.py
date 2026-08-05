"""
TSAR LLM Module — Model-agnostic LLM routing and management.

ZERO model names in source code. All routing via task_type.

Components:
  - Router:  Task-type → model resolution with fallback chains
  - Prompts: Prompt templates for each task type
  - Cache:   Response caching for repeated queries
"""

from src.llm.blueprint_selector import BlueprintRecommendation, BlueprintSelector, TraderProfile
from src.llm.complexity_router import ComplexityRouter, ROIReport, TaskComplexity
from src.llm.dataset_generator import DatasetGenerator, DatasetType, TrainingExample
from src.llm.evaluation import LLMEvaluator
from src.llm.post_training import (
    LoRATrainer,
    PostTrainingEvaluator,
    PostTrainingPipeline,
    TradeDatasetGenerator,
)
from src.llm.prompts import get_max_tokens, get_prompt, get_system_prompt
from src.llm.router import ModelRouter
from src.llm.token_counter import count_tokens, count_tokens_batch

__all__: list[str] = [
    "BlueprintRecommendation",
    "BlueprintSelector",
    "ComplexityRouter",
    "DatasetGenerator",
    "DatasetType",
    "LLMEvaluator",
    "LoRATrainer",
    "ModelRouter",
    "PostTrainingEvaluator",
    "PostTrainingPipeline",
    "ROIReport",
    "TaskComplexity",
    "TraderProfile",
    "TradeDatasetGenerator",
    "TrainingExample",
    "count_tokens",
    "count_tokens_batch",
    "get_max_tokens",
    "get_prompt",
    "get_system_prompt",
]
