"""
TSAR Security Audit Logger — Telegram Security Events.

Logs all security-relevant events to a dedicated audit log.
NEVER logs credential values — only metadata (key names, masked values, outcomes).

Storage: data/security_audit.jsonl (append-only JSON lines)
Rotation: On startup if >10MB, or on each write if >10MB
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = Path("data/security_audit.jsonl")
MAX_AUDIT_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


# ── Credential redaction patterns ──────────────────────────────

_CREDENTIAL_RE = re.compile(r"^[A-Za-z0-9]{20,}$")
_SECRET_LABELS = re.compile(r"(key|secret|token|password|credential)", re.IGNORECASE)


def _sanitize_value(key: str, value: Any) -> Any:
    """Redact anything that looks like a credential value.

    Defense-in-depth: even if a caller accidentally passes a raw
    credential, this strips it before it hits disk.
    """
    if not isinstance(value, str):
        return value

    # Redact long alphanumeric strings (likely API keys)
    if len(value) > 20 and _CREDENTIAL_RE.match(value):
        return value[:4] + "..." + value[-4:]

    # Redact values of fields with secret-sounding names
    if _SECRET_LABELS.search(key) and len(value) > 8:
        return value[:3] + "..." + value[-3:]

    return value


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Sanitize all values in a details dict."""
    return {k: _sanitize_value(k, v) for k, v in details.items()}


# ── Core audit logger ──────────────────────────────────────────

def audit_log(event_type: str, details: dict[str, Any] | None = None) -> None:
    """Append a security event to the audit log.

    Args:
        event_type: One of the AUDIT_EVENT_* constants.
        details: Event-specific metadata. MUST NOT contain credential values.
                 Values are auto-sanitized as defense-in-depth.
    """
    details = details or {}
    details = _sanitize_details(details)

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event_type,
        "details": details,
    }

    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Rotate if too large
    if AUDIT_LOG_PATH.exists() and AUDIT_LOG_PATH.stat().st_size > MAX_AUDIT_SIZE_BYTES:
        rotated = AUDIT_LOG_PATH.with_suffix(f".{int(time.time())}.jsonl")
        try:
            AUDIT_LOG_PATH.rename(rotated)
            logger.info("Rotated audit log to %s", rotated)
        except OSError:
            pass

    try:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        logger.error("Failed to write audit log: %s", exc)

    # Also log to standard logger (truncated for safety)
    logger.info("AUDIT|%s|%s", event_type, json.dumps(details, default=str)[:200])


# ── Event type constants ───────────────────────────────────────

# Credential events
AUDIT_CREDENTIAL_STORED = "credential_stored"
AUDIT_CREDENTIAL_DELETED = "credential_deleted"
AUDIT_CREDENTIAL_ROTATED = "credential_rotated"
AUDIT_CREDENTIAL_VALIDATION_FAILED = "credential_validation_failed"
AUDIT_CREDENTIAL_ACCESS = "credential_access"

# Auth events
AUDIT_AUTH_SUCCESS = "auth_success"
AUDIT_AUTH_FAILURE = "auth_failure"
AUDIT_SESSION_STARTED = "session_started"
AUDIT_SESSION_EXPIRED = "session_expired"
AUDIT_REAUTH_REQUIRED = "reauth_required"

# Message events
AUDIT_SENSITIVE_MSG_DELETED = "sensitive_message_deleted"
AUDIT_MSG_DELETE_FAILED = "message_delete_failed"

# Command events
AUDIT_KILL_SWITCH_ON = "kill_switch_activated"
AUDIT_KILL_SWITCH_OFF = "kill_switch_deactivated"
AUDIT_TRADE_APPROVED = "trade_approved"
AUDIT_TRADE_REJECTED = "trade_rejected"
AUDIT_CONFIG_CHANGED = "config_changed"

# Threat events
AUDIT_RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
AUDIT_SPOOFING_ATTEMPT = "spoofing_attempt"
AUDIT_BOT_TOKEN_SUSPICIOUS = "bot_token_suspicious"


# ── Credential filter for stdlib logging ───────────────────────

class CredentialLogFilter(logging.Filter):
    """Logging filter that redacts strings that look like credentials.

    Apply to the root logger to prevent accidental credential leakage
    into any log output (files, stderr, journald, etc.).
    """

    _PATTERNS = [
        re.compile(r"[A-Za-z0-9]{64}"),           # Binance API key/secret
        re.compile(r"\d+:[A-Za-z0-9_-]{35}"),     # Telegram bot token
        re.compile(r"(?i)(key|secret|token|password)\s*[:=]\s*\S+"),  # Labeled
    ]
    _REPLACEMENT = "[REDACTED]"

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in self._PATTERNS:
                record.msg = pattern.sub(self._REPLACEMENT, record.msg)

        if record.args:
            if isinstance(record.args, dict):
                for key in list(record.args.keys()):
                    if _SECRET_LABELS.search(key):
                        record.args[key] = self._REPLACEMENT
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._REPLACEMENT
                    if isinstance(a, str) and len(a) > 20 and _CREDENTIAL_RE.match(a)
                    else a
                    for a in record.args
                )
        return True


def install_credential_filter() -> None:
    """Install the credential redaction filter on the root logger.

    Call once at application startup.
    """
    root = logging.getLogger()
    if not any(isinstance(f, CredentialLogFilter) for f in root.filters):
        root.addFilter(CredentialLogFilter())
        logger.info("Credential log filter installed")
