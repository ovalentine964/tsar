"""
Tool Registry — OpenHarness tool registration adapted for TSAR.

Adapts OpenHarness's tool registration pattern:
  - Declarative tool definitions with JSON Schema
  - On-demand skill loading from .md files
  - Auto-discovery of TSAR's existing tools
  - Tool execution with middleware chain

TSAR-specific:
  - Maps all 30+ TSAR tools to OpenHarness format
  - Skills load from skills/*.md files (trading, risk, defi, news)
  - Middleware chain: logging → rate limiting → governance → execute
  - Tool categories: market, analysis, execution, risk, knowledge, defi

Usage:
    registry = ToolRegistry()
    await registry.load_skills_from_dir("skills/")

    # Get tool definitions for LLM
    defs = registry.get_tool_definitions()

    # Execute a tool
    result = await registry.execute("market_data", {"symbol": "BTC/USDT"})
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Tool Definition (OpenHarness format)
# ═══════════════════════════════════════════════════════════════


@dataclass
class ToolParameter:
    """JSON Schema parameter for a tool."""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: list[str] = field(default_factory=list)
    default: Any = None


@dataclass
class ToolDefinition:
    """OpenHarness-compatible tool definition.

    Maps directly to the tool schema expected by LLM APIs:
    {
        "type": "function",
        "function": {
            "name": "...",
            "description": "...",
            "parameters": { "type": "object", "properties": {...}, "required": [...] }
        }
    }
    """
    name: str
    description: str
    category: str = "general"
    parameters: list[ToolParameter] = field(default_factory=list)
    handler: Callable[..., Awaitable[Any]] | None = None
    priority: int = 2  # 0=critical, 1=high, 2=normal, 3=low
    requires_governance: bool = False  # Trade execution tools
    rate_limit_per_minute: int = 60
    skill_source: str | None = None  # Path to .md skill file

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        properties = {}
        required = []
        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


# ═══════════════════════════════════════════════════════════════
# Skill Loader (loads .md skill files on demand)
# ═══════════════════════════════════════════════════════════════


@dataclass
class SkillDefinition:
    """A skill loaded from a .md file."""
    name: str
    description: str
    path: str
    tools: list[str] = field(default_factory=list)
    instructions: str = ""
    loaded: bool = False


class SkillLoader:
    """On-demand skill loader from .md files.

    Skills are markdown files that define:
    - Skill name and description
    - Available tools and their parameters
    - Execution instructions for the agent
    - Risk constraints and governance hooks

    Format:
        ---
        name: trading
        description: Crypto trading operations
        tools: [market_data, execution, order_router]
        requires_governance: true
        ---

        ## Instructions
        When executing trades...
    """

    def __init__(self, skills_dir: str = "skills") -> None:
        self._skills_dir = Path(skills_dir)
        self._skills: dict[str, SkillDefinition] = {}

    async def discover(self) -> list[str]:
        """Discover all .md skill files in the skills directory.

        Returns:
            List of discovered skill names.
        """
        if not self._skills_dir.exists():
            logger.warning("Skills directory not found: %s", self._skills_dir)
            return []

        skill_files = list(self._skills_dir.glob("*.md"))
        discovered = []

        for path in skill_files:
            skill = self._parse_skill_file(path)
            if skill:
                self._skills[skill.name] = skill
                discovered.append(skill.name)
                logger.info("Discovered skill: %s (%s)", skill.name, path)

        return discovered

    async def load(self, name: str) -> SkillDefinition | None:
        """Load a skill by name (on-demand).

        Args:
            name: Skill name (matches .md filename without extension).

        Returns:
            SkillDefinition or None if not found.
        """
        if name in self._skills and self._skills[name].loaded:
            return self._skills[name]

        path = self._skills_dir / f"{name}.md"
        if not path.exists():
            logger.warning("Skill file not found: %s", path)
            return None

        skill = self._parse_skill_file(path)
        if skill:
            skill.loaded = True
            self._skills[name] = skill
            logger.info("Loaded skill: %s", name)

        return skill

    def get_skill(self, name: str) -> SkillDefinition | None:
        """Get an already-loaded skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """List all discovered/loaded skill names."""
        return list(self._skills.keys())

    def _parse_skill_file(self, path: Path) -> SkillDefinition | None:
        """Parse a .md skill file into a SkillDefinition."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read skill file %s: %s", path, e)
            return None

        # Parse frontmatter
        frontmatter = {}
        body = content
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2)
            for line in fm_text.strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    frontmatter[key.strip()] = val.strip()

        name = frontmatter.get("name", path.stem)
        description = frontmatter.get("description", "")
        tools_str = frontmatter.get("tools", "")
        tools = [t.strip() for t in tools_str.strip("[]").split(",") if t.strip()] if tools_str else []

        return SkillDefinition(
            name=name,
            description=description,
            path=str(path),
            tools=tools,
            instructions=body.strip(),
            loaded=False,
        )


# ═══════════════════════════════════════════════════════════════
# Tool Registry
# ═══════════════════════════════════════════════════════════════


# Middleware type: (tool_name, arguments, next_handler) -> result
ToolMiddleware = Callable[
    [str, dict[str, Any], Callable[..., Awaitable[Any]]],
    Awaitable[Any],
]


class ToolRegistry:
    """
    OpenHarness-compatible tool registry adapted for TSAR.

    Features:
      - Register tools with declarative definitions
      - Auto-discover TSAR's existing tools
      - Load skills from .md files on demand
      - Middleware chain for logging, rate limiting, governance
      - Execute tools with full lifecycle hooks
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._middleware: list[ToolMiddleware] = []
        self._skill_loader: SkillLoader | None = None
        self._rate_limit_state: dict[str, list[float]] = {}
        self._execution_count: dict[str, int] = {}

    # ── Registration ─────────────────────────────────────────────

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a tool definition.

        Args:
            tool_def: Tool definition with handler, parameters, metadata.
        """
        self._tools[tool_def.name] = tool_def
        logger.debug("Registered tool: %s (category=%s)", tool_def.name, tool_def.category)

    def register_handler(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        description: str = "",
        category: str = "general",
        parameters: list[ToolParameter] | None = None,
        requires_governance: bool = False,
    ) -> None:
        """Quick-register a tool with just a handler function.

        Args:
            name: Tool name.
            handler: Async function to handle tool calls.
            description: What the tool does.
            category: Tool category.
            parameters: Tool parameters (auto-inferred if None).
            requires_governance: Whether this tool needs risk checks.
        """
        self.register(ToolDefinition(
            name=name,
            description=description,
            category=category,
            parameters=parameters or [],
            handler=handler,
            requires_governance=requires_governance,
        ))

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)

    # ── Auto-Discovery from TSAR ─────────────────────────────────

    async def auto_discover_tsar_tools(self) -> int:
        """Auto-discover and register TSAR's existing tools.

        Reads from src/tools/__init__.py's registry and maps each
        tool to OpenHarness format.

        Returns:
            Number of tools discovered.
        """
        try:
            from src.tools import get_registered_tools
            tsar_tools = get_registered_tools()
        except ImportError:
            logger.warning("Could not import TSAR tools")
            return 0

        count = 0
        for name, tool_class in tsar_tools.items():
            # Build description from docstring
            description = ""
            if tool_class.__doc__:
                description = tool_class.__doc__.strip().split("\n")[0]

            # Determine category from module path
            module = tool_class.__module__ or ""
            category = self._infer_category(name, module)

            # Determine if governance-required
            needs_gov = name in {
                "execution", "order_router", "defi_execution",
                "dex_executor", "intent_executor", "cross_chain",
                "settlement",
            }

            self.register(ToolDefinition(
                name=name,
                description=description or f"TSAR tool: {name}",
                category=category,
                handler=self._make_tsar_handler(name, tool_class),
                requires_governance=needs_gov,
                priority=0 if needs_gov else 2,
            ))
            count += 1

        logger.info("Auto-discovered %d TSAR tools", count)
        return count

    # ── Skill Loading ────────────────────────────────────────────

    async def load_skills(self, skills_dir: str = "skills") -> int:
        """Load skills from .md files and register their tools.

        Args:
            skills_dir: Path to skills directory.

        Returns:
            Number of skills loaded.
        """
        self._skill_loader = SkillLoader(skills_dir)
        discovered = await self._skill_loader.discover()

        count = 0
        for skill_name in discovered:
            skill = await self._skill_loader.load(skill_name)
            if skill and skill.tools:
                for tool_name in skill.tools:
                    if tool_name in self._tools:
                        # Tag the tool with its skill source
                        existing = self._tools[tool_name]
                        self._tools[tool_name] = ToolDefinition(
                            name=existing.name,
                            description=existing.description,
                            category=skill_name,
                            parameters=existing.parameters,
                            handler=existing.handler,
                            priority=existing.priority,
                            requires_governance=existing.requires_governance,
                            rate_limit_per_minute=existing.rate_limit_per_minute,
                            skill_source=skill.path,
                        )
                count += 1

        logger.info("Loaded %d skills from %s", count, skills_dir)
        return count

    def get_skill_instructions(self, skill_name: str) -> str:
        """Get instructions from a loaded skill.

        Args:
            skill_name: Name of the skill.

        Returns:
            Skill instructions text, or empty string if not found.
        """
        if self._skill_loader:
            skill = self._skill_loader.get_skill(skill_name)
            if skill:
                return skill.instructions
        return ""

    # ── Middleware ────────────────────────────────────────────────

    def add_middleware(self, middleware: ToolMiddleware) -> None:
        """Add a middleware to the execution chain.

        Middleware runs in order: first added = outermost wrapper.
        """
        self._middleware.append(middleware)

    # ── Execution ────────────────────────────────────────────────

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool by name with middleware chain.

        Execution flow:
          middleware[0] → middleware[1] → ... → actual handler

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool result.

        Raises:
            KeyError: If tool not found.
            RuntimeError: If tool has no handler.
        """
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(f"Tool not found: {name}")

        if tool.handler is None:
            raise RuntimeError(f"Tool {name} has no handler")

        # Rate limiting check
        if not self._check_rate_limit(name, tool.rate_limit_per_minute):
            return {"error": f"Rate limit exceeded for {name}", "retry_after_seconds": 60}

        # Build the execution chain
        async def _inner_handler(n: str, args: dict[str, Any]) -> Any:
            self._execution_count[name] = self._execution_count.get(name, 0) + 1
            return await tool.handler(**args)

        # Wrap with middleware (outermost first)
        handler = _inner_handler
        for mw in reversed(self._middleware):
            prev = handler

            async def _wrap(mw=mw, prev=prev, n=name, a=arguments):
                return await mw(n, a, lambda nn, aa: prev(nn, aa))

            handler = _wrap

        return await handler(name, arguments)

    # ── Tool Definitions for LLM ─────────────────────────────────

    def get_tool_definitions(self, category: str | None = None) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI function-calling format.

        Args:
            category: Optional filter by category.

        Returns:
            List of tool definitions.
        """
        tools = self._tools.values()
        if category:
            tools = [t for t in tools if t.category == category]
        return [t.to_openai_format() for t in tools]

    def list_tools(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all registered tools with metadata."""
        tools = self._tools.values()
        if category:
            tools = [t for t in tools if t.category == category]
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "priority": t.priority,
                "requires_governance": t.requires_governance,
                "parameters": len(t.parameters),
                "skill_source": t.skill_source,
            }
            for t in tools
        ]

    def get_tool_count(self) -> int:
        """Get the number of registered tools."""
        return len(self._tools)

    def get_execution_stats(self) -> dict[str, int]:
        """Get execution counts per tool."""
        return dict(self._execution_count)

    # ── Internal Helpers ─────────────────────────────────────────

    def _check_rate_limit(self, name: str, limit: int) -> bool:
        """Check if a tool call is within its rate limit."""
        now = time.time()
        window_start = now - 60

        if name not in self._rate_limit_state:
            self._rate_limit_state[name] = []

        # Prune old entries
        self._rate_limit_state[name] = [
            t for t in self._rate_limit_state[name] if t > window_start
        ]

        if len(self._rate_limit_state[name]) >= limit:
            return False

        self._rate_limit_state[name].append(now)
        return True

    def _infer_category(self, name: str, module: str) -> str:
        """Infer tool category from name and module path."""
        if "market" in name or "data" in name:
            return "market"
        if "risk" in name or "guard" in name or "kill" in name:
            return "risk"
        if "exec" in name or "order" in name or "router" in name:
            return "execution"
        if "news" in name or "sentiment" in name or "social" in name:
            return "information"
        if "defi" in name or "dex" in name or "bridge" in name or "chain" in name:
            return "defi"
        if "knowledge" in name or "memory" in name or "pattern" in name:
            return "knowledge"
        if "backtest" in name or "strategy" in name:
            return "strategy"
        if "tech" in name or "indicator" in name or "pattern" in name:
            return "analysis"
        return "general"

    def _make_tsar_handler(
        self,
        tool_name: str,
        tool_class: type,
    ) -> Callable[..., Awaitable[Any]]:
        """Create an async handler wrapper for a TSAR tool class.

        TSAR tools are class-based. This creates an async function
        that instantiates and calls the appropriate method.
        """
        async def handler(**kwargs: Any) -> Any:
            try:
                instance = tool_class() if callable(tool_class) else tool_class
                # Try common method names
                for method_name in ["execute", "run", "analyze", "get", "check", "process"]:
                    if hasattr(instance, method_name):
                        method = getattr(instance, method_name)
                        if asyncio.iscoroutinefunction(method):
                            return await method(**kwargs)
                        return method(**kwargs)
                # Fallback: return the class itself
                return {"status": "no_handler", "tool": tool_name}
            except Exception as e:
                logger.error("TSAR tool %s failed: %s", tool_name, e)
                return {"error": str(e), "tool": tool_name}

        return handler
