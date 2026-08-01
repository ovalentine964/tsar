"""
TSAR Bot — Telegram bot for setup, alerts, and interactive trading.

Components:
  - TelegramBot:        Main bot class with setup wizard, trade proposals,
                        inline keyboards, and conversational state machine
  - TsarBot:            Backward-compatible alias for TelegramBot
  - Commands:           Telegram command handlers (/start, /setup, /status,
                        /config, /trade, /risk, /pnl, /positions, etc.)
  - Credentials:        Encrypted credential storage with Fernet
  - ConversationManager: Per-user conversational state machine for setup wizard

Setup Wizard Flow:
  /start → Welcome → Step 1: API Key → Step 2: API Secret (test connection)
  → Step 3: Telegram Token → Step 4: Chat ID (auto-detect) → Done!

Security:
  - Credentials encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
  - User messages containing credentials deleted after reading
  - Credentials never echoed back (masked: abc...xyz)
  - TSAR_MASTER_KEY env var or auto-generated master key
  - Chat ID whitelist for authorization
"""

from src.bot.bot import TelegramBot, TsarBot, TradeProposal
from src.bot.commands import COMMANDS, handle_command
from src.bot.conversation import ConversationManager, ConversationState
from src.bot.credentials import (
    decrypt_credentials,
    encrypt_credentials,
    get_credential_status,
    has_credentials,
    mask_credential,
    update_single_credential,
)

__all__: list[str] = [
    # Bot
    "TelegramBot",
    "TsarBot",
    "TradeProposal",
    # Commands
    "COMMANDS",
    "handle_command",
    # Conversation
    "ConversationManager",
    "ConversationState",
    # Credentials
    "decrypt_credentials",
    "encrypt_credentials",
    "get_credential_status",
    "has_credentials",
    "mask_credential",
    "update_single_credential",
]
