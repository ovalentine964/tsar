"""
TSAR Credential Manager — Secure encrypted storage for Telegram setup.

Encrypts credentials with Fernet (AES-128-CBC + HMAC-SHA256) before
writing to disk. Never stores plaintext. Auto-generates a master key
from TSAR_MASTER_KEY env var or creates one on first use.

Storage: data/credentials.enc (JSON with encrypted values)
Key:     TSAR_MASTER_KEY env var, or auto-generated and stored in
         data/.master_key (chmod 600)
"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Paths relative to project root
CREDENTIALS_PATH = Path("data/credentials.enc")
MASTER_KEY_PATH = Path("data/.master_key")

# Credential names and their setup step labels
CREDENTIAL_STEPS: list[dict[str, Any]] = [
    {
        "key": "EXCHANGE_API_KEY",
        "label": "Binance API Key",
        "step": 1,
        "total": 4,
        "optional": False,
    },
    {
        "key": "EXCHANGE_SECRET",
        "label": "Binance API Secret",
        "step": 2,
        "total": 4,
        "optional": False,
        "test_connection": True,
    },
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "label": "Telegram Bot Token",
        "step": 3,
        "total": 4,
        "optional": False,
    },
    {
        "key": "TELEGRAM_CHAT_ID",
        "label": "Chat ID",
        "step": 4,
        "total": 4,
        "optional": False,
        "auto_detect": True,
    },
]


def _load_or_create_master_key() -> bytes:
    """Load master key from env or file. Auto-generates if missing.

    Priority:
      1. TSAR_MASTER_KEY env var
      2. data/.master_key file
      3. Generate new key, save to file
    """
    env_key = os.environ.get("TSAR_MASTER_KEY")
    if env_key:
        return env_key.encode()

    if MASTER_KEY_PATH.exists():
        return MASTER_KEY_PATH.read_bytes().strip()

    # Generate new key
    key = Fernet.generate_key()
    MASTER_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_KEY_PATH.write_bytes(key)
    try:
        MASTER_KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass  # Windows or restricted FS
    logger.info("Generated new master key → %s", MASTER_KEY_PATH)
    return key


def _get_fernet() -> Fernet:
    """Create a Fernet instance from the master key."""
    key = _load_or_create_master_key()
    return Fernet(key)


def mask_credential(value: str) -> str:
    """Mask a credential showing only last 4 chars.

    Examples:
        mask_credential("abc123def456") → "abc...def456"
        mask_credential("short") → "***"
        mask_credential("") → "(empty)"
    """
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "***" + value[-2:] if len(value) >= 2 else "***"
    return value[:3] + "..." + value[-4:]


def encrypt_credentials(creds: dict[str, str]) -> None:
    """Encrypt and store credentials to data/credentials.enc.

    Each credential is individually encrypted so they can be
    read/updated independently.
    """
    f = _get_fernet()
    encrypted: dict[str, str] = {}
    for name, value in creds.items():
        if value:
            encrypted[name] = f.encrypt(value.encode()).decode()

    data = {
        "version": 1,
        "encrypted_at": datetime.now(UTC).isoformat(),
        "credentials": encrypted,
    }

    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    try:
        CREDENTIALS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass
    logger.info("Credentials encrypted → %s", CREDENTIALS_PATH)


def decrypt_credentials() -> dict[str, str]:
    """Decrypt credentials from data/credentials.enc at runtime.

    Returns empty dict if file doesn't exist.
    Raises RuntimeError on decryption failure.
    """
    if not CREDENTIALS_PATH.exists():
        return {}

    f = _get_fernet()
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Corrupted credentials file: {exc}") from exc

    result: dict[str, str] = {}
    for name, encrypted_value in data.get("credentials", {}).items():
        try:
            result[name] = f.decrypt(encrypted_value.encode()).decode()
        except InvalidToken:
            logger.error("Failed to decrypt credential: %s", name)
            raise RuntimeError(
                f"Decryption failed for {name}. Check TSAR_MASTER_KEY."
            ) from None

    return result


def has_credentials() -> bool:
    """Check if all required credentials are configured."""
    creds = decrypt_credentials()
    for step in CREDENTIAL_STEPS:
        if not step.get("optional") and not creds.get(step["key"]):
            return False
    return True


def get_missing_credentials() -> list[str]:
    """Return list of missing required credential keys."""
    creds = decrypt_credentials()
    missing = []
    for step in CREDENTIAL_STEPS:
        if not step.get("optional") and not creds.get(step["key"]):
            missing.append(step["key"])
    return missing


def get_credential_status() -> dict[str, dict[str, Any]]:
    """Get status of all credentials (configured/masked)."""
    creds = decrypt_credentials()
    status = {}
    for step in CREDENTIAL_STEPS:
        key = step["key"]
        value = creds.get(key, "")
        status[key] = {
            "label": step["label"],
            "configured": bool(value),
            "masked": mask_credential(value) if value else None,
            "optional": step.get("optional", False),
        }
    return status


def update_single_credential(key: str, value: str) -> None:
    """Update a single credential, preserving others."""
    existing = decrypt_credentials()
    existing[key] = value
    encrypt_credentials(existing)


def rotate_master_key(new_key: bytes | None = None) -> bytes:
    """Rotate the master encryption key.

    1. Decrypt all credentials with old key
    2. Generate (or use provided) new key
    3. Re-encrypt all credentials with new key
    4. Save new key
    5. Old key is no longer valid

    Returns the new key bytes.
    """
    # 1. Decrypt with old key
    old_creds = decrypt_credentials()

    # 2. New key
    if new_key is None:
        new_key = Fernet.generate_key()

    # 3. Re-encrypt with new key
    f = Fernet(new_key)
    encrypted = {}
    for name, value in old_creds.items():
        if value:
            encrypted[name] = f.encrypt(value.encode()).decode()

    data = {
        "version": 1,
        "encrypted_at": datetime.now(UTC).isoformat(),
        "key_rotated_at": datetime.now(UTC).isoformat(),
        "credentials": encrypted,
    }

    # 4. Save
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    try:
        CREDENTIALS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass

    # Save new key file (if not using env var)
    if not os.environ.get("TSAR_MASTER_KEY"):
        MASTER_KEY_PATH.write_bytes(new_key)
        try:
            MASTER_KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass

    logger.info("Master key rotated successfully")
    return new_key


def backup_encrypted_credentials(backup_path: Path) -> None:
    """Create a backup of the encrypted credentials file.

    The backup is still encrypted — it can only be restored
    with the same master key.
    """
    import shutil

    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError("No credentials file to backup")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CREDENTIALS_PATH, backup_path)
    try:
        backup_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass
    logger.info("Credentials backed up to %s", backup_path)


def restore_encrypted_credentials(backup_path: Path) -> None:
    """Restore credentials from a backup.

    Requires the same master key that was used during backup.
    Raises RuntimeError if decryption fails (wrong key).
    """
    import shutil

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    # Verify we can decrypt the backup
    f = _get_fernet()
    try:
        data = json.loads(backup_path.read_text())
        for name, enc_val in data.get("credentials", {}).items():
            f.decrypt(enc_val.encode())
    except (InvalidToken, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Cannot decrypt backup. Master key may have changed since backup was created."
        ) from exc

    shutil.copy2(backup_path, CREDENTIALS_PATH)
    logger.info("Credentials restored from %s", backup_path)


async def test_binance_connection(api_key: str, secret: str) -> dict[str, Any]:
    """Test Binance API connectivity.

    Returns {"ok": bool, "message": str, "balance": float|None}.
    """
    try:
        import ccxt

        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "sandbox": True,  # Always test with testnet first
            "enableRateLimit": True,
        })
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {}).get("free", 0)
        return {
            "ok": True,
            "message": f"Connected! Balance: {usdt:.2f} USDT",
            "balance": usdt,
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:120], "balance": None}
