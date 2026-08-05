"""
TSAR Harness — OpenHarness adaptation for crypto trading superagent.

Adapts OpenHarness's core patterns:
  - Streaming tool-call agent loop with retry/backoff
  - Tool registration with on-demand skill loading
  - Persistent memory with context compression
  - Governance/risk guard integration

Usage:
    from src.harness import AgentLoop, ToolRegistry, HarnessMemory, Governance
"""

from src.harness.agent_loop import AgentLoop, AgentLoopConfig
from src.harness.governance import Governance, GovernanceConfig
from src.harness.memory import HarnessMemory, MemoryConfig
from src.harness.tool_registry import SkillLoader, ToolRegistry

__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "Governance",
    "GovernanceConfig",
    "HarnessMemory",
    "MemoryConfig",
    "ToolRegistry",
    "SkillLoader",
]
