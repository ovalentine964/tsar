"""TSAR — Configuration Loader.

Loads configuration from YAML files with environment variable overrides
and Pydantic validation.

Priority (highest wins):
  1. Environment variables (``TSAR_*`` prefix)
  2. YAML config file
  3. Pydantic field defaults

Usage::

    from src.utils.config import load_config, TSARConfig

    config = load_config()                    # auto-discover config file
    config = load_config("config/tsar.yaml")  # explicit path
    print(config.database.db_path)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:

    class _FieldInfo:
        def __init__(self, default: Any = None, default_factory: Any = None, **kwargs: Any) -> None:
            self.default = default
            self.default_factory = default_factory

    def Field(default: Any = ..., **kwargs: Any) -> Any:  # type: ignore[misc]
        return _FieldInfo(default=default, default_factory=kwargs.get("default_factory"))

    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            hints: dict[str, Any] = {}
            for cls in type(self).__mro__:
                if hasattr(cls, "__annotations__"):
                    hints.update(cls.__annotations__)
            for name, annotation in hints.items():
                if name.startswith("_"):
                    continue
                value = kwargs.get(name)
                if value is None:
                    cls_val = getattr(type(self), name, None)
                    if isinstance(cls_val, _FieldInfo):
                        if cls_val.default is not ... and cls_val.default is not None:
                            value = cls_val.default
                        elif cls_val.default_factory is not None:
                            value = cls_val.default_factory()
                    elif cls_val is not None and not isinstance(cls_val, (classmethod, staticmethod, property)):
                        value = cls_val
                if isinstance(value, dict) and hasattr(annotation, "__mro__") and BaseModel in annotation.__mro__:
                    value = annotation(**value)
                setattr(self, name, value)

    def field_validator(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        def decorator(fn: Any) -> Any:
            return fn
        return decorator


from src.utils.logging import get_logger

logger = get_logger(__name__)

_ENV_PREFIX = "TSAR_"

_DEFAULT_SEARCH_PATHS = [
    "config/tsar.yaml",
    "config/tsar.yml",
    "tsar.yaml",
    "tsar.yml",
    "~/.tsar/config.yaml",
]


class DatabaseConfig(BaseModel):
    db_path: str = Field(default="data/tsar.db")
    journal_mode: str = Field(default="WAL")
    cache_size_mb: int = Field(default=64)
    mmap_size_mb: int = Field(default=256)
    busy_timeout_ms: int = Field(default=5000)
    foreign_keys: bool = Field(default=True)


class RedisConfig(BaseModel):
    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    password: str | None = Field(default=None)
    ssl: bool = Field(default=False)
    decode_responses: bool = Field(default=True)
    socket_timeout_s: float = Field(default=5.0)
    key_prefix: str = Field(default="tsar:")

    @property
    def url(self) -> str:
        scheme = "rediss" if self.ssl else "redis"
        auth = f":{self.password}@" if self.password else ""
        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"


class ExchangeConfig(BaseModel):
    name: str = Field(default="binance")
    sandbox: bool = Field(default=True)
    api_key: str | None = Field(default=None)
    api_secret: str | None = Field(default=None)
    symbols: list[str] = Field(default=["BTC/USDT"])
    rate_limit_per_minute: int = Field(default=1200)


class RiskConfig(BaseModel):
    daily_loss_limit_pct: float = Field(default=2.0)
    max_drawdown_pct: float = Field(default=5.0)
    max_open_positions: int = Field(default=3)
    max_single_position_pct: float = Field(default=15.0)
    kelly_fraction: float = Field(default=0.25)
    max_correlation: float = Field(default=0.7)
    min_risk_reward: float = Field(default=2.0)
    max_daily_trades: int = Field(default=30)
    max_sector_concentration_pct: float = Field(default=30.0)


class LLMConfig(BaseModel):
    default_provider: str = Field(default="ollama")
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen2.5:7b")
    deepseek_api_key: str | None = Field(default=None)
    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    daily_budget_usd: float = Field(default=0.0)
    monthly_budget_usd: float = Field(default=0.0)
    request_timeout_s: float = Field(default=30.0)


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO")
    json_output: bool = Field(default=False)
    service_name: str = Field(default="tsar")


class StrategyConfig(BaseModel):
    default_strategy: str = Field(default="mean_reversion")
    min_trades_for_evaluation: int = Field(default=30)
    min_win_rate: float = Field(default=0.45)
    max_consecutive_losses: int = Field(default=7)
    min_profit_factor: float = Field(default=1.2)


class MEVConfig(BaseModel):
    """MEV protection and oracle configuration."""
    enabled: bool = Field(default=True)
    chain: str = Field(default="ethereum")

    # Flashbots Protect
    flashbots_relay_url: str = Field(default="https://relay.flashbots.net")
    flashbots_enabled: bool = Field(default=True)

    # Jito (Solana)
    jito_tip_lamports: int = Field(default=10_000)
    jito_block_engine_url: str = Field(default="https://mainnet.block-engine.jito.wtf")
    jito_enabled: bool = Field(default=False)

    # Oracle contract addresses (Ethereum mainnet)
    oracle_rpc_url: str = Field(default="")
    chainlink_feeds: dict[str, str] = Field(default={
        "ETH/USD": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
        "BTC/USD": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
        "USDC/USD": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
        "USDT/USD": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",
        "SOL/USD": "0x4ffC43a60e009B551865A93d232E33Fce9f01507",
        "LINK/USD": "0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c",
    })
    pyth_hermes_url: str = Field(default="https://hermes.pyth.network")
    pyth_enabled: bool = Field(default=True)

    # Price deviation thresholds
    deviation_warning_pct: float = Field(default=1.0)
    deviation_alert_pct: float = Field(default=3.0)
    deviation_critical_pct: float = Field(default=5.0)

    # Gas optimisation
    gas_refresh_interval_s: int = Field(default=12)

    # Sandwich detection
    sandwich_detection_enabled: bool = Field(default=True)
    mempool_poll_interval_s: int = Field(default=5)


class TSARConfig(BaseModel):
    """Top-level TSAR configuration."""
    environment: str = Field(default="development")
    trading_mode: str = Field(default="paper")
    database: DatabaseConfig = Field(default=DatabaseConfig())
    redis: RedisConfig = Field(default=RedisConfig())
    exchange: ExchangeConfig = Field(default=ExchangeConfig())
    risk: RiskConfig = Field(default=RiskConfig())
    llm: LLMConfig = Field(default=LLMConfig())
    logging: LoggingConfig = Field(default=LoggingConfig())
    strategy: StrategyConfig = Field(default=StrategyConfig())
    mev: MEVConfig = Field(default=MEVConfig())


def _discover_config_path(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
        logger.warning("config_file_not_found", path=str(p))
        return None
    for candidate in _DEFAULT_SEARCH_PATHS:
        p = Path(candidate).expanduser()
        if p.exists():
            return p
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise ImportError("PyYAML required. Install: pip install pyyaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _apply_env_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        key = env_key[len(_ENV_PREFIX):].replace("__", ".").lower()
        parts = key.split(".")
        current: Any = config_dict
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        leaf = parts[-1]
        existing = current.get(leaf)
        if existing is not None:
            try:
                if isinstance(existing, bool):
                    current[leaf] = env_val.lower() in ("true", "1", "yes")
                elif isinstance(existing, int):
                    current[leaf] = int(env_val)
                elif isinstance(existing, float):
                    current[leaf] = float(env_val)
                else:
                    current[leaf] = env_val
            except (ValueError, TypeError):
                current[leaf] = env_val
        else:
            current[leaf] = _coerce_env_value(env_val)
    return config_dict


def _coerce_env_value(val: str) -> Any:
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def load_config(
    config_path: str | Path | None = None,
    *,
    apply_env: bool = True,
) -> TSARConfig:
    """Load and validate TSAR configuration."""
    config_dict: dict[str, Any] = {}
    path = _discover_config_path(config_path)
    if path:
        logger.info("config_loaded", path=str(path))
        config_dict = _load_yaml(path)
    else:
        logger.info("config_no_file_found", using="defaults")
    if apply_env:
        config_dict = _apply_env_overrides(config_dict)
    try:
        config = TSARConfig(**config_dict)
    except Exception as exc:
        logger.error("config_validation_failed", error=str(exc))
        config = TSARConfig()
    logger.info(
        "config_resolved",
        environment=config.environment,
        trading_mode=config.trading_mode,
        db_path=config.database.db_path,
    )
    return config


_config_instance: TSARConfig | None = None


def get_config() -> TSARConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance


def reset_config() -> None:
    global _config_instance
    _config_instance = None
