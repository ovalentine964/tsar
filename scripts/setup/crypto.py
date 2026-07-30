"""Secret encryption/decryption using Fernet (AES-128-CBC + HMAC-SHA256)."""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

SECRETS_KEY_PATH = Path(".secrets.key")
SECRETS_DATA_PATH = Path(".env.secrets")


def generate_master_key() -> bytes:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key()


def load_or_create_master_key() -> bytes:
    """Load existing master key or create a new one with 600 permissions."""
    if SECRETS_KEY_PATH.exists():
        return SECRETS_KEY_PATH.read_bytes().strip()

    key = generate_master_key()
    SECRETS_KEY_PATH.write_bytes(key)
    SECRETS_KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    return key


def encrypt_secrets(secrets: dict[str, str]) -> None:
    """Encrypt and store secrets to .env.secrets."""
    key = load_or_create_master_key()
    f = Fernet(key)

    encrypted: dict[str, str] = {}
    for name, value in secrets.items():
        if value:
            encrypted[name] = f.encrypt(value.encode()).decode()

    data = {
        "version": 1,
        "encrypted_at": datetime.now(timezone.utc).isoformat(),
        "secrets": encrypted,
    }

    SECRETS_DATA_PATH.write_text(json.dumps(data, indent=2) + "\n")
    SECRETS_DATA_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600


def decrypt_secrets() -> dict[str, str]:
    """Decrypt secrets from .env.secrets at runtime."""
    if not SECRETS_KEY_PATH.exists():
        raise RuntimeError("Master key not found. Run: python scripts/setup.py")
    if not SECRETS_DATA_PATH.exists():
        raise RuntimeError("Encrypted secrets not found. Run: python scripts/setup.py")

    key = SECRETS_KEY_PATH.read_bytes().strip()
    f = Fernet(key)

    data = json.loads(SECRETS_DATA_PATH.read_text())
    result: dict[str, str] = {}
    for name, encrypted_value in data["secrets"].items():
        result[name] = f.decrypt(encrypted_value.encode()).decode()

    return result
