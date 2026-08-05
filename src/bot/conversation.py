"""
TSAR Conversational State Machine — Setup wizard and interactive flows.

Tracks per-user conversation state for multi-step interactive flows
like the setup wizard. Handles graceful error recovery, /cancel, /skip,
and unexpected input.

State is kept in-memory (dict per user_id). For production, this could
be backed by Redis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    """Possible conversation states."""

    IDLE = "idle"
    # Setup wizard steps
    SETUP_API_KEY = "setup_api_key"
    SETUP_API_SECRET = "setup_api_secret"
    SETUP_TEST_CONNECTION = "setup_test_connection"
    SETUP_TELEGRAM_TOKEN = "setup_telegram_token"
    SETUP_CHAT_ID = "setup_chat_id"
    SETUP_COMPLETE = "setup_complete"
    # Generic awaiting input
    AWAITING_INPUT = "awaiting_input"


@dataclass
class UserSession:
    """Per-user conversation state."""

    user_id: str
    chat_id: str
    state: ConversationState = ConversationState.IDLE
    data: dict[str, Any] = field(default_factory=dict)
    step_index: int = 0
    started_at: float = 0.0

    def reset(self) -> None:
        """Reset to idle state."""
        self.state = ConversationState.IDLE
        self.data = {}
        self.step_index = 0

    def set_state(self, state: ConversationState, **kwargs: Any) -> None:
        """Transition to a new state with optional data."""
        self.state = state
        self.data.update(kwargs)

    def is_in_setup(self) -> bool:
        """Check if user is in any setup wizard step."""
        return self.state in {
            ConversationState.SETUP_API_KEY,
            ConversationState.SETUP_API_SECRET,
            ConversationState.SETUP_TEST_CONNECTION,
            ConversationState.SETUP_TELEGRAM_TOKEN,
            ConversationState.SETUP_CHAT_ID,
        }


class ConversationManager:
    """Manages per-user conversation state for interactive flows.

    Thread-safe for single-event-loop usage (asyncio).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}

    def get_session(self, user_id: str, chat_id: str = "") -> UserSession:
        """Get or create a user session."""
        if user_id not in self._sessions:
            import time

            self._sessions[user_id] = UserSession(
                user_id=user_id,
                chat_id=chat_id,
                started_at=time.time(),
            )
        session = self._sessions[user_id]
        if chat_id:
            session.chat_id = chat_id
        return session

    def clear_session(self, user_id: str) -> None:
        """Clear a user's session."""
        self._sessions.pop(user_id, None)

    def get_all_active(self) -> list[UserSession]:
        """Get all sessions currently in a non-IDLE state."""
        return [s for s in self._sessions.values() if s.state != ConversationState.IDLE]


# ── Setup Wizard Flow Definition ────────────────────────────

SETUP_WELCOME = (
    "👋 <b>Welcome to TSAR — your Trading Super Agent.</b>\n"
    "\n"
    "I'm an autonomous crypto trading system powered by AI.\n"
    "I scan markets 24/7, propose trades for your approval,\n"
    "and continuously improve my strategies.\n"
    "\n"
    "🔐 I need a few credentials to get you started.\n"
    "All credentials are <b>encrypted</b> and stored securely — "
    "I'll never echo them back."
)

SETUP_STEPS: list[dict[str, Any]] = [
    {
        "state": ConversationState.SETUP_API_KEY,
        "prompt": (
            "<b>Step 1/4:</b> Paste your Binance API Key\n"
            "\n"
            "Get one at: https://testnet.binance.vision/\n"
            "(Use testnet for safe testing)\n"
            "\n"
            "Type /cancel to abort setup."
        ),
        "key": "EXCHANGE_API_KEY",
        "label": "Binance API Key",
        "success": "✅ Binance API Key received and encrypted.",
    },
    {
        "state": ConversationState.SETUP_API_SECRET,
        "prompt": (
            "<b>Step 2/4:</b> Paste your Binance API Secret\n"
            "\n"
            "This is the secret paired with your API key.\n"
            "I'll test the connection after you provide it."
        ),
        "key": "EXCHANGE_SECRET",
        "label": "Binance API Secret",
        "success": "✅ Binance API Secret received and encrypted.",
        "test_after": True,
    },
    {
        "state": ConversationState.SETUP_TELEGRAM_TOKEN,
        "prompt": (
            "<b>Step 3/4:</b> Paste your Telegram Bot Token\n"
            "\n"
            "Get one from @BotFather on Telegram.\n"
            "Format: <code>123456789:ABCdef...</code>"
        ),
        "key": "TELEGRAM_BOT_TOKEN",
        "label": "Telegram Bot Token",
        "success": "✅ Telegram token received and encrypted.",
    },
    {
        "state": ConversationState.SETUP_CHAT_ID,
        "prompt": (
            "<b>Step 4/4:</b> What's your Telegram Chat ID?\n"
            "\n"
            "I already detected yours: <code>{chat_id}</code>\n"
            'Reply <b>"yes"</b> to use this, or paste a different one.'
        ),
        "key": "TELEGRAM_CHAT_ID",
        "label": "Chat ID",
        "success": "✅ Chat ID saved.",
        "auto_detect": True,
    },
]

SETUP_COMPLETE_MSG = (
    "🎉 <b>All credentials configured!</b>\n"
    "\n"
    "🔐 Credentials encrypted and stored securely.\n"
    "📊 Connection to Binance: {connection_status}\n"
    "\n"
    "🚀 <b>TSAR is ready.</b>\n"
    "\n"
    "Type /trade to start trading\n"
    "Type /status to see system status\n"
    "Type /help to see all commands\n"
    "Type /config to view configuration\n"
)

SETUP_CANCELLED_MSG = (
    "❌ Setup cancelled.\n\nYour credentials were NOT saved.\nType /setup anytime to restart."
)

SETUP_ALREADY_CONFIGURED = (
    "✅ <b>Credentials already configured.</b>\n"
    "\n"
    "{status_table}\n"
    "\n"
    "Type /setup to re-configure\n"
    "Type /config to view details"
)
