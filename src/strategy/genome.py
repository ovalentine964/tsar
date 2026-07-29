"""
Strategy Genome — Encoding for strategy evolution.

A genome encodes all evolvable parameters of a strategy.
Used by Strategy Geneticist for mutation and crossover operations.

Supports YAML genome loading from config/strategies/*.yaml
with parameter bounds, steps, and mutation constraints.
"""

from __future__ import annotations

import copy
import logging
import random
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class StrategyGenome:
    """Strategy genome for evolutionary optimization.

    Loads parameters from YAML config, supports bounded mutation
    and crossover operations.

    Usage::

        genome = StrategyGenome.from_yaml("config/strategies/mean_reversion.yaml")
        mutated = genome.mutate(mutation_rate=0.2)
        child = genome.crossover(other_genome)
        genome.save_yaml("config/strategies/mean_reversion_v2.yaml")
    """

    def __init__(
        self,
        name: str,
        params: dict[str, Any],
        mutable_params: dict[str, dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.params = params
        self.mutable_params = mutable_params or {}
        self.metadata = metadata or {}
        self.fitness: float = 0.0

    # ── YAML Loading ─────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> StrategyGenome:
        """Load a genome from a YAML strategy config file.

        Args:
            path: Path to YAML file (e.g. config/strategies/mean_reversion.yaml)

        Returns:
            StrategyGenome instance with parameters and mutation bounds.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Genome YAML not found: {path}")

        with open(path) as f:
            config = yaml.safe_load(f)

        name = config.get("name", path.stem)
        version = config.get("version", 1)
        thesis = config.get("thesis", "")
        status = config.get("status", "candidate")

        # Extract mutable parameters with their bounds
        mutable_section = config.get("mutable_parameters", {})
        mutable_params: dict[str, dict[str, Any]] = {}
        params: dict[str, Any] = {}

        for param_name, param_def in mutable_section.items():
            if isinstance(param_def, dict):
                current = param_def.get("current", 0)
                mutable_params[param_name] = {
                    "current": current,
                    "min": param_def.get("min", current * 0.5),
                    "max": param_def.get("max", current * 1.5),
                    "step": param_def.get("step", 1),
                    "description": param_def.get("description", ""),
                }
                params[param_name] = current

        # Extract entry/exit rules for metadata
        entry_rules = config.get("entry_rules", {})
        exit_rules = config.get("exit_rules", {})
        sizing = config.get("sizing", {})
        risk_constraints = config.get("risk_constraints", {})

        metadata = {
            "version": version,
            "thesis": thesis,
            "status": status,
            "entry_rules": entry_rules,
            "exit_rules": exit_rules,
            "sizing": sizing,
            "risk_constraints": risk_constraints,
            "backtesting": config.get("backtesting", {}),
            "retirement_gates": config.get("retirement_gates", {}),
            "source_path": str(path),
        }

        logger.info(f"Loaded genome: {name} v{version} ({len(mutable_params)} mutable params)")
        return cls(name=name, params=params, mutable_params=mutable_params, metadata=metadata)

    def save_yaml(self, path: str | Path) -> None:
        """Save current genome state to a YAML file.

        Args:
            path: Output path for the YAML file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Reconstruct the YAML structure
        config: dict[str, Any] = {
            "name": self.name,
            "version": self.metadata.get("version", 1),
            "thesis": self.metadata.get("thesis", ""),
            "status": self.metadata.get("status", "candidate"),
        }

        # Update mutable_parameters with current values
        if self.mutable_params:
            mutable_section: dict[str, Any] = {}
            for param_name, bounds in self.mutable_params.items():
                mutable_section[param_name] = {
                    "current": self.params.get(param_name, bounds["current"]),
                    "min": bounds["min"],
                    "max": bounds["max"],
                    "step": bounds["step"],
                    "description": bounds.get("description", ""),
                }
            config["mutable_parameters"] = mutable_section

        # Preserve non-mutable sections
        for key in ("entry_rules", "exit_rules", "sizing", "risk_constraints", "backtesting", "retirement_gates"):
            if key in self.metadata:
                config[key] = self.metadata[key]

        with open(path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, width=120)

        logger.info(f"Saved genome: {self.name} -> {path}")

    # ── Mutation ─────────────────────────────────────────────

    def mutate(self, mutation_rate: float = 0.1) -> StrategyGenome:
        """Create a mutated copy of this genome.

        Mutation respects parameter bounds (min/max) and step sizes
        defined in the YAML config.

        Args:
            mutation_rate: Probability of mutating each parameter (0.0-1.0).

        Returns:
            New StrategyGenome with mutated parameters.
        """
        child = StrategyGenome(
            name=self.name,
            params=copy.deepcopy(self.params),
            mutable_params=copy.deepcopy(self.mutable_params),
            metadata=copy.deepcopy(self.metadata),
        )

        mutations_applied: list[str] = []

        for param_name, value in child.params.items():
            if random.random() > mutation_rate:
                continue

            bounds = child.mutable_params.get(param_name)
            if bounds is None:
                # No bounds defined — mutate with ±20% delta
                if isinstance(value, (int, float)):
                    delta = value * random.uniform(-0.2, 0.2)
                    new_value = type(value)(value + delta)
                    child.params[param_name] = new_value
                    mutations_applied.append(f"{param_name}: {value} -> {new_value}")
                continue

            # Bounded mutation
            step = bounds.get("step", 1)
            min_val = bounds["min"]
            max_val = bounds["max"]

            # Random step: -2 to +2 steps
            num_steps = random.randint(-2, 2)
            delta = num_steps * step
            new_value = value + delta

            # Clamp to bounds
            new_value = max(min_val, min(max_val, new_value))

            # Preserve type
            if isinstance(value, int):
                new_value = int(round(new_value))
            elif isinstance(value, float):
                new_value = round(new_value, 6)

            child.params[param_name] = new_value
            mutations_applied.append(f"{param_name}: {value} -> {new_value}")

        if mutations_applied:
            logger.info(f"Mutated {self.name}: {', '.join(mutations_applied)}")

        return child

    def crossover(self, other: StrategyGenome) -> StrategyGenome:
        """Create a child genome by crossing over with another.

        For each parameter, randomly picks the value from either parent.
        Both parents must have the same parameter names.

        Args:
            other: Another StrategyGenome to crossover with.

        Returns:
            New StrategyGenome child.
        """
        child_params = copy.deepcopy(self.params)

        for key in child_params:
            if random.random() < 0.5 and key in other.params:
                child_params[key] = copy.deepcopy(other.params[key])

        # Merge mutable_params (take the wider bounds)
        child_mutable = copy.deepcopy(self.mutable_params)
        for key, other_bounds in other.mutable_params.items():
            if key not in child_mutable:
                child_mutable[key] = copy.deepcopy(other_bounds)
            else:
                existing = child_mutable[key]
                child_mutable[key] = {
                    "current": child_params.get(key, existing["current"]),
                    "min": min(existing["min"], other_bounds["min"]),
                    "max": max(existing["max"], other_bounds["max"]),
                    "step": min(existing["step"], other_bounds["step"]),
                    "description": existing.get("description", ""),
                }

        child = StrategyGenome(
            name=self.name,
            params=child_params,
            mutable_params=child_mutable,
            metadata=copy.deepcopy(self.metadata),
        )

        logger.info(f"Crossover: {self.name} x {other.name}")
        return child

    # ── Utilities ────────────────────────────────────────────

    def get_param(self, name: str, default: Any = None) -> Any:
        """Get a parameter value by name."""
        return self.params.get(name, default)

    def set_param(self, name: str, value: Any) -> None:
        """Set a parameter value, respecting bounds if defined."""
        bounds = self.mutable_params.get(name)
        if bounds:
            value = max(bounds["min"], min(bounds["max"], value))
        self.params[name] = value

    def get_bounds(self, name: str) -> dict[str, Any] | None:
        """Get mutation bounds for a parameter."""
        return self.mutable_params.get(name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize genome to dict."""
        return {
            "name": self.name,
            "params": self.params,
            "mutable_params": self.mutable_params,
            "metadata": self.metadata,
            "fitness": self.fitness,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyGenome:
        """Deserialize genome from dict."""
        genome = cls(
            name=data["name"],
            params=data["params"],
            mutable_params=data.get("mutable_params", {}),
            metadata=data.get("metadata", {}),
        )
        genome.fitness = data.get("fitness", 0.0)
        return genome

    def __repr__(self) -> str:
        return f"StrategyGenome(name={self.name!r}, params={len(self.params)}, fitness={self.fitness:.4f})"
