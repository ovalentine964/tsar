"""TSAR — Structured Logging.

Provides structlog-based structured logging with JSON output for production
and human-readable console output for development.

Usage::

    from src.utils.logging import get_logger, setup_logging

    setup_logging(json_output=True)   # call once at startup
    logger = get_logger(__name__)
    logger.info("trade_executed", symbol="BTC/USDT", pnl=150.0)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

try:
    import structlog
except ImportError:
    structlog = None  # type: ignore[assignment]


_LOGGING_CONFIGURED = False


def setup_logging(
    *,
    json_output: bool | None = None,
    level: str = "INFO",
    service_name: str = "tsar",
) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    if json_output is None:
        json_output = os.environ.get("TSAR_LOG_FORMAT", "").lower() == "json"

    log_level = getattr(logging, level.upper(), logging.INFO)

    if structlog is not None:
        _setup_structlog(json_output=json_output, log_level=log_level, service_name=service_name)
    else:
        _setup_fallback(log_level=log_level, json_output=json_output)

    _LOGGING_CONFIGURED = True


def _setup_structlog(
    *,
    json_output: bool,
    log_level: int,
    service_name: str,
) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _add_service_field(service_name),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    for name in ("httpx", "httpcore", "urllib3", "ccxt"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _add_service_field(service_name: str) -> structlog.types.Processor:
    def processor(
        logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        event_dict["service"] = service_name
        return event_dict
    return processor


def _setup_fallback(*, log_level: int, json_output: bool) -> None:
    import json as _json
    from datetime import datetime, timezone

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info and record.exc_info[1]:
                entry["exception"] = self.formatException(record.exc_info)
            return _json.dumps(entry, default=str)

    if json_output:
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)


class _FallbackLogger:
    """Thin wrapper around stdlib Logger that accepts keyword args
    like structlog (ignores them, logs the event string)."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, event: str, **kwargs: Any) -> None:
        self._logger.debug(event)

    def info(self, event: str, **kwargs: Any) -> None:
        self._logger.info(event)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._logger.warning(event)

    def error(self, event: str, **kwargs: Any) -> None:
        self._logger.error(event)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._logger.critical(event)

    def exception(self, event: str, **kwargs: Any) -> None:
        self._logger.exception(event)

    def bind(self, **kwargs: Any) -> "_FallbackLogger":
        return self

    def unbind(self, *args: Any) -> "_FallbackLogger":
        return self


def get_logger(name: str) -> Any:
    """Return a structured logger for the given module name.

    If structlog is installed, returns a ``structlog.stdlib.BoundLogger``.
    Otherwise, returns a wrapper that accepts keyword args like structlog.
    """
    if structlog is not None:
        return structlog.get_logger(name)
    return _FallbackLogger(logging.getLogger(name))
