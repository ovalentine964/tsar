"""Credential format validators and API connectivity tests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    valid: bool
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def ok(msg: str = "") -> ValidationResult:
    return ValidationResult(valid=True, message=msg)


def fail(msg: str) -> ValidationResult:
    return ValidationResult(valid=False, message=msg)


def warn(msg: str) -> ValidationResult:
    return ValidationResult(valid=True, warnings=[msg])


# ── Format Validators ──────────────────────────────────────────


def validate_binance_key(key: str) -> ValidationResult:
    """Binance API keys are 64-char alphanumeric."""
    if not key or key.strip() in ("", "← FILL IN", "FILL IN"):
        return fail("Key is empty or placeholder")
    key = key.strip()
    if len(key) != 64:
        return fail(f"Expected 64 chars, got {len(key)}")
    if not key.isalnum():
        return fail("Key should be alphanumeric only")
    result = ok("Format valid (64 chars, alphanumeric)")
    if any(t in key.lower() for t in ("test", "example", "demo", "xxx")):
        result.warnings.append("Looks like a test/example key")
    return result


def validate_binance_secret(secret: str) -> ValidationResult:
    """Binance secrets are 64-char alphanumeric."""
    if not secret or secret.strip() in ("", "← FILL IN", "FILL IN"):
        return fail("Secret is empty or placeholder")
    secret = secret.strip()
    if len(secret) != 64:
        return fail(f"Expected 64 chars, got {len(secret)}")
    if not secret.isalnum():
        return fail("Secret should be alphanumeric only")
    return ok("Format valid (64 chars)")


def validate_nvidia_key(key: str) -> ValidationResult:
    """NVIDIA API keys start with 'nvapi-'."""
    if not key or key.strip() in ("", "← FILL IN", "FILL IN"):
        return fail("Key is empty")
    key = key.strip()
    if not key.startswith("nvapi-"):
        return fail("NVIDIA keys start with 'nvapi-'")
    if len(key) < 20:
        return fail("Key seems too short")
    return ok("Format valid (nvapi- prefix)")


def validate_telegram_token(token: str) -> ValidationResult:
    """Telegram bot tokens match pattern: digits:alphanumeric."""
    if not token or not token.strip():
        return ok("Skipped (optional)")
    token = token.strip()
    pattern = r"^\d+:[A-Za-z0-9_-]{35,}$"
    if not re.match(pattern, token):
        return fail("Token format: digits:alphanumeric (from @BotFather)")
    return ok("Format valid")


def validate_telegram_chat_id(chat_id: str) -> ValidationResult:
    """Telegram chat IDs are numeric (can be negative for groups)."""
    if not chat_id or not chat_id.strip():
        return ok("Skipped (optional)")
    chat_id = chat_id.strip()
    try:
        int(chat_id)
    except ValueError:
        return fail("Chat ID should be a number")
    return ok("Format valid (numeric)")


# ── API Connectivity Tests ─────────────────────────────────────


@dataclass
class TestResult:
    success: bool
    message: str


def test_binance_api(api_key: str, secret: str) -> TestResult:
    """Test Binance API connectivity (read-only, no orders)."""
    try:
        import ccxt  # type: ignore[import-untyped]

        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "sandbox": True,
            "enableRateLimit": True,
        })
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {}).get("free", 0)
        return TestResult(True, f"Connected! Testnet USDT balance: {usdt}")
    except Exception as e:
        name = type(e).__name__
        if "Authentication" in name or "Invalid" in name:
            return TestResult(False, "Authentication failed — check key/secret")
        if "Network" in name:
            return TestResult(False, f"Network error: {e}")
        return TestResult(False, f"Error: {e}")


def test_nvidia_api(api_key: str) -> TestResult:
    """Test NVIDIA NIM API with a minimal request."""
    try:
        import httpx  # type: ignore[import-untyped]

        resp = httpx.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "nvidia/nemotron-3-ultra",
                "messages": [{"role": "user", "content": "Say ok"}],
                "max_tokens": 5,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return TestResult(True, "NVIDIA NIM API accessible")
        if resp.status_code == 401:
            return TestResult(False, "Invalid API key")
        return TestResult(False, f"HTTP {resp.status_code}")
    except Exception as e:
        return TestResult(False, f"Connection error: {e}")


def test_telegram_bot(token: str, chat_id: str | None = None) -> TestResult:
    """Test Telegram bot token validity."""
    try:
        import httpx  # type: ignore[import-untyped]

        resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if resp.status_code != 200:
            return TestResult(False, "Invalid bot token")
        bot_name = resp.json()["result"]["username"]

        if chat_id:
            resp = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "🔧 TSAR setup test — OK!"},
                timeout=10,
            )
            if resp.status_code == 200:
                return TestResult(True, f"Bot @{bot_name} can send to chat {chat_id}")
            return TestResult(
                False,
                f"Bot works but can't send to chat {chat_id}. "
                "Send a message to the bot first.",
            )
        return TestResult(True, f"Bot @{bot_name} token valid")
    except Exception as e:
        return TestResult(False, f"Error: {e}")


# ── Full Validation (for --validate-only) ──────────────────────


def validate_only() -> list[dict]:
    """Validate existing .env without making changes. Returns list of issues."""
    issues: list[dict] = []
    env_path = Path(".env")
    if not env_path.exists():
        issues.append({"severity": "ERROR", "message": ".env file not found"})
        return issues

    env = _parse_env_file(env_path)

    # Check required vars
    required = [
        "EXCHANGE_API_KEY", "EXCHANGE_SECRET", "NVIDIA_API_KEY",
        "TSAR_API_KEY", "REDIS_PASSWORD",
    ]
    for var in required:
        val = env.get(var, "").strip()
        if not val or val in ("← FILL IN", "FILL IN"):
            issues.append({"severity": "ERROR", "message": f"{var} is empty or placeholder"})

    # Check safety
    if env.get("TSAR_TRADING_MODE", "").strip() == "live":
        issues.append({"severity": "WARNING", "message": "TSAR_TRADING_MODE=live — are you sure?"})
    if env.get("EXCHANGE_SANDBOX", "").strip() == "false":
        issues.append({"severity": "WARNING", "message": "EXCHANGE_SANDBOX=false — real exchange!"})

    # Check secrets strength
    redis_pw = env.get("REDIS_PASSWORD", "").strip()
    if redis_pw and len(redis_pw) < 16:
        issues.append({"severity": "WARNING", "message": "REDIS_PASSWORD is short (<16 chars)"})
    api_key = env.get("TSAR_API_KEY", "").strip()
    if api_key and len(api_key) < 16:
        issues.append({"severity": "WARNING", "message": "TSAR_API_KEY is short (<16 chars)"})

    return issues


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser."""
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result
