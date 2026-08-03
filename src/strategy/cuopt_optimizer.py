"""TSAR — cuOpt Multi-Objective Strategy Parameter Optimizer.

Uses NVIDIA cuOpt for GPU-accelerated optimization of trading strategy
parameters. Optimizes multiple objectives simultaneously:
- Win rate (maximize)
- Profit factor (maximize)
- Max drawdown (minimize)
- Sharpe ratio (maximize)

cuOpt is optional — falls back to scipy.optimize if unavailable.
Includes a quantum-inspired simulated annealing optimizer as an
additional fallback that borrows quantum concepts (tunneling,
thermal fluctuations) for better global optimization.

Integrates with TSAR's strategy backtest engine for fitness evaluation.

Requires: nvidia-cuopt (pip install nvidia-cuopt)
GPU: NVIDIA GPU with CUDA 12.x+
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── cuOpt availability check ────────────────────────────────

def _check_cuopt_available() -> bool:
    """Check if cuOpt is available with a working GPU.

    Verifies:
    1. cupy can be imported
    2. cuopt can be imported
    3. At least one CUDA GPU is accessible
    """
    try:
        import cupy as cp  # noqa: F811
        from cuopt import Optimizer  # noqa: F811

        # Verify GPU is actually accessible
        gpu_count = cp.cuda.runtime.getDeviceCount()
        if gpu_count == 0:
            logger.warning("cuopt_no_gpu", msg="cuOpt packages installed but no CUDA GPU found")
            return False
        return True
    except (ImportError, RuntimeError, OSError) as exc:
        logger.debug("cuopt_check_failed", error=str(exc))
        return False


CUOPT_AVAILABLE = _check_cuopt_available()

if CUOPT_AVAILABLE:
    import cupy as cp
    from cuopt import Optimizer as CuOptOptimizer
    logger.info("cuopt_available", msg="GPU-accelerated optimization enabled")
else:
    cp = None  # type: ignore[assignment]

    class _Stub:
        """Stub for missing cuOpt classes."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "cuOpt not installed or no GPU available. "
                "Install with: pip install nvidia-cuopt cupy-cuda12x"
            )

    CuOptOptimizer = _Stub  # type: ignore[assignment,misc]


# ── Data classes ─────────────────────────────────────────────


@dataclass
class OptimizationObjective:
    """A single optimization objective."""

    name: str
    weight: float = 1.0
    direction: str = "maximize"  # maximize | minimize


@dataclass
class ParameterRange:
    """Valid range for a strategy parameter."""

    name: str
    min_value: float
    max_value: float
    step: float = 1.0
    param_type: str = "float"  # float | int


@dataclass
class OptimizationResult:
    """Result of multi-objective optimization."""

    best_parameters: dict[str, float]
    best_score: float
    objectives: dict[str, float]  # objective_name → achieved value
    pareto_front: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    converged: bool = False
    method: str = "cuopt"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_parameters": self.best_parameters,
            "best_score": round(self.best_score, 6),
            "objectives": {k: round(v, 6) for k, v in self.objectives.items()},
            "pareto_front_count": len(self.pareto_front),
            "iterations": self.iterations,
            "converged": self.converged,
            "method": self.method,
            "metadata": self.metadata,
        }


# ── Fitness function type ───────────────────────────────────

# Fitness function: takes parameters dict, returns dict of objective values
FitnessFunction = Callable[[dict[str, float]], dict[str, float]]


# ── Main Optimizer ──────────────────────────────────────────


class CuOptStrategyOptimizer:
    """Multi-objective strategy parameter optimizer using NVIDIA cuOpt.

    Optimizes trading strategy parameters across multiple objectives
    simultaneously. Uses GPU-accelerated solvers for speed.

    Falls back to scipy differential evolution if cuOpt unavailable.

    Usage::

        optimizer = CuOptStrategyOptimizer(config)

        # Define parameter space
        optimizer.add_parameter("rsi_period", min_value=5, max_value=50, step=1)
        optimizer.add_parameter("macd_fast", min_value=5, max_value=20, step=1)

        # Define objectives
        optimizer.add_objective("win_rate", weight=0.3, direction="maximize")
        optimizer.add_objective("max_drawdown", weight=0.2, direction="minimize")

        # Run optimization (fitness_fn evaluates parameters via backtest)
        result = await optimizer.optimize(fitness_fn=my_backtest_fn)
        print(f"Best params: {result.best_parameters}")
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._available = CUOPT_AVAILABLE
        self._fallback = self._config.get("fallback", "scipy")
        self._parameters: list[ParameterRange] = []
        self._objectives: list[OptimizationObjective] = []

        # Load objectives from config
        obj_cfg = self._config.get("objectives", [])
        for obj in obj_cfg:
            self._objectives.append(
                OptimizationObjective(
                    name=obj.get("name", ""),
                    weight=obj.get("weight", 1.0),
                    direction=obj.get("direction", "maximize"),
                )
            )

        # Load parameter bounds from config
        bounds_cfg = self._config.get("parameter_bounds", {})
        for name, bounds in bounds_cfg.items():
            if isinstance(bounds, list) and len(bounds) >= 2:
                self._parameters.append(
                    ParameterRange(
                        name=name,
                        min_value=float(bounds[0]),
                        max_value=float(bounds[1]),
                    )
                )

        if not self._available:
            logger.warning(
                "cuopt_not_available",
                msg=f"cuOpt not installed. Using {self._fallback} fallback.",
            )

    @property
    def available(self) -> bool:
        """Check if cuOpt GPU backend is available."""
        return self._available

    # ── Configuration ────────────────────────────────────────

    def add_parameter(
        self,
        name: str,
        min_value: float,
        max_value: float,
        step: float = 1.0,
        param_type: str = "float",
    ) -> None:
        """Add a parameter to the optimization space."""
        self._parameters.append(
            ParameterRange(
                name=name,
                min_value=min_value,
                max_value=max_value,
                step=step,
                param_type=param_type,
            )
        )

    def add_objective(
        self,
        name: str,
        weight: float = 1.0,
        direction: str = "maximize",
    ) -> None:
        """Add an optimization objective."""
        self._objectives.append(
            OptimizationObjective(name=name, weight=weight, direction=direction)
        )

    # ── Optimization ─────────────────────────────────────────

    async def optimize(
        self,
        fitness_fn: FitnessFunction,
        max_iterations: int | None = None,
        time_limit_seconds: int | None = None,
        method: str | None = None,
    ) -> OptimizationResult:
        """Run multi-objective optimization.

        Args:
            fitness_fn: Function that takes parameter dict and returns
                       objective values dict. Called via backtest engine.
            max_iterations: Override max iterations.
            time_limit_seconds: Override time limit.
            method: Override optimization method.
                "cuopt" — GPU-accelerated (requires NVIDIA GPU)
                "scipy" — scipy differential evolution
                "quantum_annealing" — simulated quantum annealing
                None — auto-select best available

        Returns:
            OptimizationResult with best parameters and Pareto front.
        """
        if not self._parameters:
            return OptimizationResult(
                best_parameters={},
                best_score=0.0,
                objectives={},
                method="no_parameters",
            )

        solver_cfg = self._config.get("solver", {})
        max_iter = max_iterations or solver_cfg.get("time_limit_seconds", 30) * 10
        time_limit = time_limit_seconds or solver_cfg.get("time_limit_seconds", 30)

        # Method selection
        if method == "quantum_annealing":
            return await self._quantum_annealing_optimize(fitness_fn, max_iter)
        elif method == "cuopt" and self._available:
            return await self._cuopt_optimize(fitness_fn, max_iter, time_limit)
        elif method == "scipy":
            return await self._scipy_optimize(fitness_fn, max_iter)
        elif self._available:
            return await self._cuopt_optimize(fitness_fn, max_iter, time_limit)
        else:
            return await self._scipy_optimize(fitness_fn, max_iter)

    async def _cuopt_optimize(
        self,
        fitness_fn: FitnessFunction,
        max_iterations: int,
        time_limit: int,
    ) -> OptimizationResult:
        """GPU-accelerated optimization via cuOpt."""
        assert cp is not None

        def _run() -> OptimizationResult:
            # Build parameter bounds for cuOpt
            num_params = len(self._parameters)
            lower = cp.array([p.min_value for p in self._parameters])
            upper = cp.array([p.max_value for p in self._parameters])

            # Wrapper: evaluate fitness on GPU then transfer results
            def gpu_fitness(params_gpu: Any) -> Any:
                params_cpu = cp.asnumpy(params_gpu)
                param_dict = {
                    self._parameters[i].name: float(params_cpu[i])
                    for i in range(num_params)
                }
                # Run fitness evaluation (backtest)
                objectives = fitness_fn(param_dict)

                # Compute weighted score
                score = 0.0
                for obj in self._objectives:
                    val = objectives.get(obj.name, 0.0)
                    if obj.direction == "minimize":
                        score += obj.weight * (1.0 / max(abs(val), 1e-8))
                    else:
                        score += obj.weight * val

                return cp.float64(score)

            # Initialize cuOpt optimizer
            optimizer = CuOptOptimizer(
                dimension=num_params,
                lower_bounds=lower,
                upper_bounds=upper,
                objective_function=gpu_fitness,
                population_size=min(100, max_iterations),
                max_iterations=max_iterations,
                time_limit=time_limit,
            )

            # Run optimization
            result = optimizer.solve()

            # Extract best parameters
            best_params_cpu = cp.asnumpy(result.best_solution)
            best_params = {
                self._parameters[i].name: float(best_params_cpu[i])
                for i in range(num_params)
            }

            # Round integer parameters
            for p in self._parameters:
                if p.param_type == "int":
                    best_params[p.name] = float(round(best_params[p.name]))

            # Evaluate final objectives
            final_objectives = fitness_fn(best_params)

            # Extract Pareto front if available
            pareto = []
            if hasattr(result, "pareto_front"):
                for sol in result.pareto_front:
                    params = {
                        self._parameters[i].name: float(cp.asnumpy(sol[i]))
                        for i in range(num_params)
                    }
                    obj_vals = fitness_fn(params)
                    pareto.append({"parameters": params, "objectives": obj_vals})

            return OptimizationResult(
                best_parameters=best_params,
                best_score=float(result.best_fitness),
                objectives=final_objectives,
                pareto_front=pareto,
                iterations=int(result.iterations),
                converged=result.converged,
                method="cuopt_gpu",
                metadata={
                    "gpu_accelerated": True,
                    "num_objectives": len(self._objectives),
                    "num_parameters": num_params,
                },
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _scipy_optimize(
        self,
        fitness_fn: FitnessFunction,
        max_iterations: int,
    ) -> OptimizationResult:
        """Scipy differential evolution fallback."""
        import numpy as np
        from scipy.optimize import differential_evolution

        def _run() -> OptimizationResult:
            bounds = [(p.min_value, p.max_value) for p in self._parameters]

            # Combined objective (negative because scipy minimizes)
            def neg_score(params_array: np.ndarray) -> float:
                param_dict = {
                    self._parameters[i].name: float(params_array[i])
                    for i in range(len(self._parameters))
                }
                # Round integer parameters
                for p in self._parameters:
                    if p.param_type == "int":
                        param_dict[p.name] = float(round(param_dict[p.name]))

                objectives = fitness_fn(param_dict)

                score = 0.0
                for obj in self._objectives:
                    val = objectives.get(obj.name, 0.0)
                    if obj.direction == "minimize":
                        score += obj.weight * (1.0 / max(abs(val), 1e-8))
                    else:
                        score += obj.weight * val

                return -score  # Minimize negative = maximize

            result = differential_evolution(
                neg_score,
                bounds=bounds,
                maxiter=max_iterations // 10,
                tol=1e-6,
                seed=42,
                workers=1,  # Single-threaded for async compat
            )

            best_params = {
                self._parameters[i].name: float(result.x[i])
                for i in range(len(self._parameters))
            }

            # Round integer parameters
            for p in self._parameters:
                if p.param_type == "int":
                    best_params[p.name] = float(round(best_params[p.name]))

            final_objectives = fitness_fn(best_params)

            return OptimizationResult(
                best_parameters=best_params,
                best_score=float(-result.fun),
                objectives=final_objectives,
                iterations=int(result.nfev),
                converged=bool(result.success),
                method="fallback_scipy_differential_evolution",
                metadata={
                    "gpu_accelerated": False,
                    "num_objectives": len(self._objectives),
                    "num_parameters": len(self._parameters),
                },
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _quantum_annealing_optimize(
        self,
        fitness_fn: FitnessFunction,
        max_iterations: int,
    ) -> OptimizationResult:
        """Simulated Quantum Annealing optimizer.

        Borrows quantum concepts for classical optimization:
        - **Quantum tunneling**: Accepts worse solutions with probability
          proportional to a "tunneling" energy, allowing escape from
          local minima that classical simulated annealing gets stuck in.
        - **Thermal fluctuations**: Temperature schedule controls
          exploration vs exploitation.
        - **Superposition-inspired population**: Maintains multiple
          candidate solutions simultaneously.

        Based on: Chen & Wang (2023), "Simulated Quantum Annealing for
        Combinatorial Optimization" and IBM's quantum-inspired
        optimization benchmarks.

        This is NOT quantum computing — it's a classical algorithm
        that borrows quantum heuristics for better optimization.
        """
        import math
        import random

        def _run() -> OptimizationResult:
            num_params = len(self._parameters)
            bounds = [(p.min_value, p.max_value) for p in self._parameters]

            # ── Helper: compute weighted objective score ──────
            def _score(params_dict: dict[str, float]) -> float:
                objectives = fitness_fn(params_dict)
                score = 0.0
                for obj in self._objectives:
                    val = objectives.get(obj.name, 0.0)
                    if obj.direction == "minimize":
                        score += obj.weight * (1.0 / max(abs(val), 1e-8))
                    else:
                        score += obj.weight * val
                return score

            # ── Helper: random neighbor via quantum tunneling ──
            def _tunnel_move(
                current: list[float],
                temperature: float,
            ) -> list[float]:
                """Generate a neighbor using quantum-inspired tunneling.

                Unlike classical SA (small Gaussian perturbation),
                quantum tunneling can "jump" across barriers.
                The step size is proportional to temperature and
                the barrier width (estimated from parameter range).
                """
                new = list(current)
                # Tunnel through 1-3 dimensions at once
                n_dims = random.randint(1, min(3, num_params))
                dims = random.sample(range(num_params), n_dims)

                for d in dims:
                    lo, hi = bounds[d]
                    range_d = hi - lo
                    # Quantum tunneling: large jumps at high T, small at low T
                    # Uses Cauchy distribution (heavy tails) instead of
                    # Gaussian — this is the key quantum-inspired difference
                    cauchy_sample = math.tan(math.pi * (random.random() - 0.5))
                    step = temperature * cauchy_sample * range_d * 0.1
                    new[d] = max(lo, min(hi, current[d] + step))

                return new

            # ── Main SQA loop ────────────────────────────────
            # Temperature schedule: exponential decay
            T_init = 1.0
            T_min = 0.001
            alpha = (T_min / T_init) ** (1.0 / max(max_iterations, 1))

            # Initialize population (superposition-inspired)
            pop_size = min(20, max(5, max_iterations // 50))
            population: list[list[float]] = []
            scores: list[float] = []

            for _ in range(pop_size):
                params = [
                    random.uniform(lo, hi) for lo, hi in bounds
                ]
                population.append(params)
                param_dict = {
                    self._parameters[i].name: params[i]
                    for i in range(num_params)
                }
                scores.append(_score(param_dict))

            best_idx = max(range(pop_size), key=lambda i: scores[i])
            best_params = list(population[best_idx])
            best_score = scores[best_idx]

            T = T_init
            iterations = 0
            no_improve_count = 0

            for iteration in range(max_iterations):
                iterations = iteration + 1

                # Select a member of the population to evolve
                idx = random.randint(0, pop_size - 1)
                current = population[idx]
                current_score = scores[idx]

                # Generate tunneling neighbor
                candidate = _tunnel_move(current, T)
                param_dict = {
                    self._parameters[i].name: candidate[i]
                    for i in range(num_params)
                }
                candidate_score = _score(param_dict)

                # Quantum acceptance criterion:
                # Accept if better, or with tunneling probability if worse
                delta = candidate_score - current_score
                if delta > 0:
                    # Better — always accept
                    population[idx] = candidate
                    scores[idx] = candidate_score
                    no_improve_count = 0
                else:
                    # Worse — quantum tunneling probability
                    # P = exp(-delta / T) but with tunneling modifier
                    # that allows larger jumps than classical SA
                    tunnel_prob = math.exp(delta / max(T, 1e-10))
                    if random.random() < tunnel_prob:
                        population[idx] = candidate
                        scores[idx] = candidate_score
                        no_improve_count = 0
                    else:
                        no_improve_count += 1

                # Update global best
                if candidate_score > best_score:
                    best_score = candidate_score
                    best_params = list(candidate)

                # Cool down
                T *= alpha

                # Reheat if stuck (quantum-inspired: maintain exploration)
                if no_improve_count > max(50, max_iterations // 10):
                    T = min(T_init * 0.5, T * 10.0)
                    no_improve_count = 0

            # Final evaluation
            final_params = {
                self._parameters[i].name: float(best_params[i])
                for i in range(num_params)
            }
            for p in self._parameters:
                if p.param_type == "int":
                    final_params[p.name] = float(round(final_params[p.name]))

            final_objectives = fitness_fn(final_params)

            return OptimizationResult(
                best_parameters=final_params,
                best_score=best_score,
                objectives=final_objectives,
                iterations=iterations,
                converged=T < T_min * 10,
                method="simulated_quantum_annealing",
                metadata={
                    "gpu_accelerated": False,
                    "quantum_inspired": True,
                    "population_size": pop_size,
                    "final_temperature": round(T, 6),
                    "num_objectives": len(self._objectives),
                    "num_parameters": num_params,
                },
            )

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── Convenience: Optimize from config ────────────────────

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> CuOptStrategyOptimizer:
        """Create optimizer from nvidia_skills.yaml cuopt section."""
        return cls(config)

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return optimizer status."""
        return {
            "available": True,  # Always available (scipy or quantum_annealing fallback)
            "cuopt_gpu": self._available,
            "method": "cuopt_gpu" if self._available else f"fallback_{self._fallback}",
            "quantum_annealing": True,  # Always available (pure Python + numpy)
            "parameters": len(self._parameters),
            "objectives": len(self._objectives),
            "gpu_accelerated": self._available,
        }
