"""
TSAR Interface — BackendRegistry.

Central discovery engine mapping abstract interfaces to concrete backends.
The single source of truth for which implementation backs each interface.

Usage::

    registry = BackendRegistry()
    registry.register("exchange_gateway", CcxtGateway, backend_name="ccxt")
    registry.load_from_config("config/backends.yaml")

    # Get the configured backend for an interface
    gateway = registry.create("exchange_gateway", sandbox=True)

    # Get fallback chain
    chain = registry.get_fallback_chain("exchange_gateway")
    # → ["ccxt", "rust_ws", "fix"]

    # Hot-swap at runtime (testing / fallback)
    registry.register("exchange_gateway", MockGateway, backend_name="mock")

Config format (config/backends.yaml)::

    exchange_gateway:
      primary: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
      fallback:
        - "src.interfaces.exchange.rust_gateway.RustGateway"
      config:
        sandbox: true
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BackendRegistry:
    """Central registry for all interface → backend mappings.

    Responsibilities:
    - Register backend implementations for each interface.
    - Load registrations from YAML config.
    - Create backend instances on demand.
    - Manage fallback chains.
    - Track backend health status.

    The registry is the ONLY place where concrete backend classes are
    referenced. Agent code calls convenience getters (get_exchange_gateway, etc.)
    which delegate to this registry.
    """

    def __init__(self) -> None:
        # interface_name → {backend_name → class}
        self._backends: dict[str, dict[str, type]] = {}
        # interface_name → ordered list of backend names (primary first)
        self._fallback_chains: dict[str, list[str]] = {}
        # interface_name → default config
        self._configs: dict[str, dict[str, Any]] = {}

    # ═══════════════════════════════════════════════════════════════
    # REGISTRATION
    # ═══════════════════════════════════════════════════════════════

    def register(
        self,
        interface_name: str,
        backend_name: str,
        cls: type,
    ) -> None:
        """Register a backend implementation for an interface.

        Args:
            interface_name: Interface identifier (e.g. "exchange_gateway").
            backend_name: Human-readable backend name (e.g. "ccxt", "rust_ws").
            cls: The concrete implementation class.

        Example::

            registry.register("exchange_gateway", "ccxt", CcxtGateway)
            registry.register("exchange_gateway", "rust_ws", RustWsGateway)
        """
        if interface_name not in self._backends:
            self._backends[interface_name] = {}
            self._fallback_chains[interface_name] = []

        self._backends[interface_name][backend_name] = cls

        # Maintain fallback chain order (first registered = primary)
        if backend_name not in self._fallback_chains[interface_name]:
            self._fallback_chains[interface_name].append(backend_name)

        logger.info(
            "Registered backend: %s → %s.%s",
            interface_name,
            cls.__module__,
            cls.__qualname__,
        )

    # ═══════════════════════════════════════════════════════════════
    # INSTANCE CREATION
    # ═══════════════════════════════════════════════════════════════

    def create(self, interface_name: str, config: dict[str, Any] | None = None) -> Any:
        """Create a backend instance for an interface.

        Uses the PRIMARY (first-registered) backend. Merge the provided
        config with any default config loaded from YAML.

        Args:
            interface_name: Interface identifier (e.g. "exchange_gateway").
            config: Override configuration passed to the backend constructor.

        Returns:
            An instance of the primary backend class.

        Raises:
            ValueError: No backend registered for the given interface.
        """
        chain = self._fallback_chains.get(interface_name, [])
        if not chain:
            raise ValueError(
                f"No backend registered for interface '{interface_name}'. "
                f"Registered: {list(self._backends.keys())}"
            )

        backend_name = chain[0]  # Primary
        cls = self._backends[interface_name][backend_name]
        merged_config = {**self._configs.get(interface_name, {}), **(config or {})}

        logger.info("Creating backend: %s → %s", interface_name, backend_name)
        return cls(**merged_config)

    def create_with_fallback(
        self,
        interface_name: str,
        config: dict[str, Any] | None = None,
    ) -> tuple[Any, str]:
        """Create a backend instance with automatic fallback.

        Attempts to instantiate backends in fallback-chain order (primary
        first). If the primary raises during construction, the next backend
        in the chain is tried. All construction errors are logged.

        Args:
            interface_name: Interface identifier.
            config: Override configuration passed to the backend constructor.

        Returns:
            Tuple of (backend_instance, backend_name).

        Raises:
            ValueError: No backend registered for the given interface.
            RuntimeError: All backends in the chain failed to instantiate.
        """
        chain = self._fallback_chains.get(interface_name, [])
        if not chain:
            raise ValueError(
                f"No backend registered for interface '{interface_name}'. "
                f"Registered: {list(self._backends.keys())}"
            )

        merged_config = {**self._configs.get(interface_name, {}), **(config or {})}
        errors: list[str] = []

        for backend_name in chain:
            cls = self._backends[interface_name][backend_name]
            try:
                logger.info(
                    "Attempting backend: %s → %s", interface_name, backend_name
                )
                instance = cls(**merged_config)
                if errors:
                    logger.warning(
                        "Fallback activated for %s: primary failed, using %s",
                        interface_name,
                        backend_name,
                    )
                return instance, backend_name
            except Exception as exc:
                error_msg = f"{backend_name}: {type(exc).__name__}: {exc}"
                errors.append(error_msg)
                logger.warning(
                    "Backend %s failed for %s: %s",
                    backend_name,
                    interface_name,
                    error_msg,
                )

        raise RuntimeError(
            f"All backends failed for interface '{interface_name}'. "
            f"Errors: {errors}"
        )

    async def execute_with_fallback(
        self,
        interface_name: str,
        method_name: str,
        config: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a method on a backend with automatic fallback on failure.

        Tries to call ``method_name`` on each backend in the fallback chain.
        If the primary backend raises during *execution* (not construction),
        the next backend is tried. Each backend is freshly constructed to
        avoid stale state.

        Args:
            interface_name: Interface identifier.
            method_name: Name of the method to call on the backend.
            config: Override configuration for backend construction.
            *args: Positional args passed to the method.
            **kwargs: Keyword args passed to the method.

        Returns:
            The return value of the method call.

        Raises:
            ValueError: No backend registered.
            RuntimeError: All backends failed during execution.
        """
        chain = self._fallback_chains.get(interface_name, [])
        if not chain:
            raise ValueError(
                f"No backend registered for interface '{interface_name}'. "
                f"Registered: {list(self._backends.keys())}"
            )

        merged_config = {**self._configs.get(interface_name, {}), **(config or {})}
        errors: list[str] = []

        for backend_name in chain:
            cls = self._backends[interface_name][backend_name]
            try:
                logger.info(
                    "Executing %s.%s via %s",
                    interface_name,
                    method_name,
                    backend_name,
                )
                instance = cls(**merged_config)
                method = getattr(instance, method_name, None)
                if method is None:
                    raise AttributeError(
                        f"Backend '{backend_name}' has no method '{method_name}'"
                    )
                result = method(*args, **kwargs)
                if errors:
                    logger.warning(
                        "Fallback execution for %s.%s: succeeded on %s after %d failure(s)",
                        interface_name,
                        method_name,
                        backend_name,
                        len(errors),
                    )
                return result
            except Exception as exc:
                error_msg = f"{backend_name}: {type(exc).__name__}: {exc}"
                errors.append(error_msg)
                logger.warning(
                    "Backend %s.%s failed: %s",
                    backend_name,
                    method_name,
                    error_msg,
                )

        raise RuntimeError(
            f"All backends failed for {interface_name}.{method_name}. "
            f"Errors: {errors}"
        )

    # ═══════════════════════════════════════════════════════════════
    # FALLBACK CHAINS
    # ═══════════════════════════════════════════════════════════════

    def get_fallback_chain(self, interface_name: str) -> list[str]:
        """Get the ordered fallback chain for an interface.

        The first element is the primary backend. Subsequent elements
        are fallbacks in priority order.

        Args:
            interface_name: Interface identifier.

        Returns:
            Ordered list of backend names. Empty list if not registered.
        """
        return list(self._fallback_chains.get(interface_name, []))

    # ═══════════════════════════════════════════════════════════════
    # STATUS & DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════

    def get_backend_status(self) -> dict[str, Any]:
        """Get the full registry status for all interfaces.

        Returns a snapshot of all registered interfaces, their backends,
        fallback chains, and configuration.

        Returns:
            Dict with structure::

                {
                    "exchange_gateway": {
                        "backends": ["ccxt", "rust_ws"],
                        "primary": "ccxt",
                        "fallback_count": 1,
                    },
                    ...
                }
        """
        return {
            interface_name: {
                "backends": list(self._backends.get(interface_name, {}).keys()),
                "primary": (self._fallback_chains.get(interface_name, [None]) or [None])[0],
                "fallback_count": max(0, len(self._fallback_chains.get(interface_name, [])) - 1),
            }
            for interface_name in self._backends
        }

    # ═══════════════════════════════════════════════════════════════
    # CONFIG LOADING
    # ═══════════════════════════════════════════════════════════════


    def _register_defaults(self) -> None:
        """Register all default Python backends."""
        from src.backends.python.ccxt_exec_engine import CcxtExecEngine
        from src.backends.python.ccxt_gateway import CcxtGateway
        from src.backends.python.deepseek_provider import DeepSeekProvider
        from src.backends.python.ollama_provider import OllamaProvider
        from src.backends.python.openai_provider import OpenAIProvider
        from src.backends.python.pandas_ta_engine import PandasTAEngine
        from src.backends.python.paper_execution_engine import PaperExecutionEngine
        from src.backends.python.python_risk_engine import PythonRiskEngine

        self.register("exchange_gateway", CcxtGateway.__name__, CcxtGateway)
        self.register("execution_engine", CcxtExecEngine.__name__, CcxtExecEngine)
        self.register("execution_engine", PaperExecutionEngine.__name__, PaperExecutionEngine)
        self.register("pricing_engine", PandasTAEngine.__name__, PandasTAEngine)
        self.register("risk_engine", PythonRiskEngine.__name__, PythonRiskEngine)
        self.register("llm_provider", OllamaProvider.__name__, OllamaProvider)
        self.register("llm_provider_openai", OpenAIProvider.__name__, OpenAIProvider)
        self.register("llm_provider_deepseek", DeepSeekProvider.__name__, DeepSeekProvider)

    def create_for_mode(
        self,
        interface_name: str,
        trading_mode: str,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Create a backend instance based on trading mode.

        For execution_engine:
        - "paper" → PaperExecutionEngine (simulated fills, real market data)
        - "live"  → CcxtExecEngine (real exchange orders)

        For all other interfaces, delegates to normal create().

        Args:
            interface_name: Interface identifier.
            trading_mode: "paper" or "live".
            config: Override configuration.

        Returns:
            Backend instance appropriate for the trading mode.
        """
        if interface_name == "execution_engine":
            if trading_mode == "paper":
                from src.backends.python.paper_execution_engine import PaperExecutionEngine
                merged_config = {**self._configs.get(interface_name, {}), **(config or {})}
                logger.info("Creating PaperExecutionEngine for paper mode")
                return PaperExecutionEngine(config=merged_config)
            else:
                from src.backends.python.ccxt_exec_engine import CcxtExecEngine
                merged_config = {**self._configs.get(interface_name, {}), **(config or {})}
                logger.info("Creating CcxtExecEngine for live mode")
                return CcxtExecEngine(config=merged_config)

        return self.create(interface_name, config=config)

    def load_from_config(self, config_path: str) -> None:
        """Load backend registrations from a YAML config file.

        Config format::

            exchange_gateway:
              primary: "src.interfaces.exchange.ccxt_gateway.CcxtGateway"
              fallback:
                - "src.interfaces.exchange.rust_gateway.RustGateway"
              config:
                sandbox: true

        Args:
            config_path: Path to the YAML configuration file.

        Raises:
            FileNotFoundError: Config file does not exist.
            yaml.YAMLError: Config file is malformed.
        """
        from pathlib import Path

        import yaml

        path = Path(config_path)
        if not path.exists():
            logger.warning("Backend config not found: %s", config_path)
            return

        with open(path) as f:
            config = yaml.safe_load(f) or {}

        for interface_name, interface_config in config.items():
            if not isinstance(interface_config, dict):
                continue

            # Store default config
            self._configs[interface_name] = interface_config.get("config", {})

            # Load primary
            primary_path = interface_config.get("primary")
            if primary_path:
                cls = self._import_class(primary_path)
                backend_name = cls.__qualname__.lower().replace(cls.__name__, cls.__name__)
                self.register(interface_name, backend_name, cls)

            # Load fallbacks
            for fallback_path in interface_config.get("fallback", []):
                if isinstance(fallback_path, str):
                    cls = self._import_class(fallback_path)
                    backend_name = cls.__qualname__.lower().replace(cls.__name__, cls.__name__)
                    self.register(interface_name, backend_name, cls)

    # ═══════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _import_class(class_path: str) -> type:
        """Import a class from a dotted module path.

        Args:
            class_path: Dotted path (e.g. "src.interfaces.exchange.ccxt_gateway.CcxtGateway").

        Returns:
            The imported class.

        Raises:
            ImportError: Module or class not found.
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
