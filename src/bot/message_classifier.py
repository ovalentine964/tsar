"""
TSAR Message Classifier — Telegram Message Security.

Classifies incoming Telegram messages as sensitive, operational, or system.
Detects credential patterns and triggers auto-delete for sensitive content.
"""

from __future__ import annotations

import re
from typing import Literal

MessageClass = Literal["sensitive", "operational", "system"]

# ── Credential patterns ────────────────────────────────────────

# Binance API key/secret: 64 alphanumeric characters
_BINANCE_KEY_RE = re.compile(r"^[A-Za-z0-9]{64}$")

# Telegram bot token: digits:alphanumeric
_TELEGRAM_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{35}$")

# Labeled credentials: "api_key: xxx" or "secret = xxx"
_LABELED_CRED_RE = re.compile(
    r"(?i)^(api.?key|api.?secret|secret|token|password|private.?key|seed.?phrase)"
    r"\s*[:=]\s*\S+"
)

# Generic long alphanumeric (catch-all for unknown API keys)
_GENERIC_KEY_RE = re.compile(r"^[A-Za-z0-9+/=_-]{40,}$")

# Private keys / seed phrases
_PRIVATE_KEY_RE = re.compile(r"(?i)(0x[a-fA-F0-9]{64}|([a-z]+\s){11,23}[a-z]+)")

# All sensitive patterns combined
_SENSITIVE_PATTERNS = [
    _BINANCE_KEY_RE,
    _TELEGRAM_TOKEN_RE,
    _LABELED_CRED_RE,
    _PRIVATE_KEY_RE,
]


def classify_message(text: str) -> MessageClass:
    """Classify a Telegram message by sensitivity level.

    Returns:
        "sensitive"  — Contains credentials or secrets. Must be deleted.
        "system"     — Bot command (/status, /help, etc.). Safe to keep.
        "operational" — Normal conversation. Safe to keep.
    """
    text = text.strip()

    if not text:
        return "operational"

    # Commands are system-level
    if text.startswith("/"):
        return "system"

    # Check sensitive patterns
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return "sensitive"

    # Catch-all: very long single-token alphanumeric might be a key
    if len(text) >= 40 and " " not in text and _GENERIC_KEY_RE.match(text):
        return "sensitive"

    return "operational"


def detect_credential_key(text: str) -> str | None:
    """Detect which credential type a message likely contains.

    Returns the credential key name (e.g., "EXCHANGE_API_KEY") or None.

    This is context-aware: it considers what credential the bot is
    currently expecting (set via set_expected_credential()).
    """
    text = text.strip()

    # Check global expected credential first (bot is in collection mode)
    if _expected_credential:
        return _expected_credential

    # Labeled detection
    label_map = {
        "api_key": "EXCHANGE_API_KEY",
        "api secret": "EXCHANGE_SECRET",
        "api_secret": "EXCHANGE_SECRET",
        "secret": "EXCHANGE_SECRET",
        "token": "TELEGRAM_BOT_TOKEN",
        "bot_token": "TELEGRAM_BOT_TOKEN",
    }
    text_lower = text.lower()
    for label, key in label_map.items():
        if text_lower.startswith(label + ":") or text_lower.startswith(label + "="):
            return key

    # Pattern detection
    if _BINANCE_KEY_RE.match(text):
        # Could be either API key or secret — context resolves
        return _expected_credential or "EXCHANGE_API_KEY"

    if _TELEGRAM_TOKEN_RE.match(text):
        return "TELEGRAM_BOT_TOKEN"

    return None


# ── Expected credential context (set by bot during setup flow) ─

_expected_credential: str | None = None


def set_expected_credential(key: str | None) -> None:
    """Set the credential key the bot is currently expecting.

    During the setup wizard, the bot tells the user "send your API key"
    and sets this to "EXCHANGE_API_KEY". The next message is then
    unambiguously classified as that credential.
    """
    global _expected_credential
    _expected_credential = key


def get_expected_credential() -> str | None:
    """Get the currently expected credential key, if any."""
    return _expected_credential


def validate_credential_format(key: str, value: str) -> tuple[bool, str]:
    """Validate a credential matches its expected format.

    Returns (is_valid, error_message).
    """
    value = value.strip()

    if not value:
        return False, "Empty value"

    if key == "EXCHANGE_API_KEY":
        if not _BINANCE_KEY_RE.match(value):
            return False, "Binance API key must be exactly 64 alphanumeric characters"
        return True, ""

    if key == "EXCHANGE_SECRET":
        if not _BINANCE_KEY_RE.match(value):
            return False, "Binance API secret must be exactly 64 alphanumeric characters"
        return True, ""

    if key == "TELEGRAM_BOT_TOKEN":
        if not _TELEGRAM_TOKEN_RE.match(value):
            return False, "Telegram bot token format: digits:alphanumeric"
        return True, ""

    # Generic validation
    if len(value) < 16:
        return False, "Credential too short (minimum 16 characters)"

    return True, ""
