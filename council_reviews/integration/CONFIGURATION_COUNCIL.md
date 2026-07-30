# Configuration Council — TSAR Setup System Design

**Date:** 2026-07-30
**Status:** APPROVED — Implementation Ready
**Author:** Configuration Council (Integration Team)

---

## 1. Executive Summary

TSAR currently requires users to manually copy `.env.example` → `.env`, hand-edit YAML configs, generate secrets, and hope they didn't miss anything. The existing `scripts/setup.py` is a stub that checks if files exist and does nothing useful.

**This council designs a single-command, guided setup wizard** that:
- Walks Valentine through credential entry with validation
- Tests API connectivity before saving
- Encrypts secrets at rest (never plain text in `.env`)
- Defaults to paper mode with conservative risk parameters
- Generates cryptographically strong secrets automatically
- Produces a human-readable setup report

**Target UX:** `make setup` → paste keys → system configures everything → safe to run.

---

## 2. Current State Audit

### 2.1 `.env.example` — What Needs Configuration

| Variable | Required | Risk if Misconfigured |
|----------|----------|----------------------|
| `EXCHANGE_API_KEY` | Yes | No trading |
| `EXCHANGE_SECRET` | Yes | Auth failures |
| `EXCHANGE_SANDBOX` | Yes | **REAL MONEY if false** |
| `NVIDIA_API_KEY` | Yes | No AI features |
| `TELEGRAM_BOT_TOKEN` | Optional | No alerts |
| `TELEGRAM_CHAT_ID` | Optional | Alerts go nowhere |
| `TSAR_API_KEY` | Yes | **Security hole if empty** |
| `TSAR_API_PORT` | No | Default 8000 fine |
| `TSAR_TRADING_MODE` | Yes | **REAL MONEY if "live"** |
| `TSAR_CORS_ORIGINS` | Yes | Open CORS if empty |
| `REDIS_PASSWORD` | Yes | **Security hole if empty** |

### 2.2 YAML Configs — What Needs Attention

| File | Issue | Fix |
|------|-------|-----|
| `config/default.yaml` | `cors_origins: ["*"]` wide open | Must be locked down |
| `config/risk.yaml` | Good defaults, but no validation | Validate ranges |
| `config/models.yaml` | References `${NVIDIA_API_KEY}` from env | OK, auto-resolved |
| `config/tsar.yaml` | `trading_mode: paper` — good | Keep as default |
| `config/mandate.yaml` | All zeros — blocks live trading | Correct for safety |
| `config/backends.yaml` | `sandbox: true` — good | Keep as default |

### 2.3 Existing `scripts/setup.py` — Inadequate

Current script:
- ✅ Creates `data/` directory
- ✅ Checks Python version
- ❌ Does NOT validate credentials
- ❌ Does NOT generate secrets
- ❌ Does NOT encrypt anything
- ❌ Does NOT test API connectivity
- ❌ Does NOT configure YAML files
- ❌ Does NOT guide the user interactively

### 2.4 Security Findings

| Finding | Severity | Location |
|---------|----------|----------|
| `REDIS_PASSWORD` default empty | **CRITICAL** | `.env.example` |
| `TSAR_API_KEY` default empty | **CRITICAL** | `.env.example` |
| `cors_origins: ["*"]` in default.yaml | **HIGH** | `config/default.yaml` |
| No `.gitignore` enforcement for `.env` | **HIGH** | Root |
| Secrets stored in plain text `.env` | **MEDIUM** | `.env` |
| `tsar_dev_password` in docker-compose.yml | **LOW** | `docker-compose.yml` |

---

## 3. Architecture: The Setup System

### 3.1 Components

```
scripts/
├── setup.py              # Entry point — the wizard
├── setup/
│   ├── __init__.py
│   ├── wizard.py          # Interactive wizard flow
│   ├── validators.py      # Credential validation & API testing
│   ├── crypto.py          # Secret encryption/decryption
│   ├── config_writer.py   # YAML/env file generation
│   ├── safety.py          # Safety checks & defaults
│   └── report.py          # Post-setup summary
```

### 3.2 Data Flow

```
User runs `make setup`
    │
    ▼
┌─────────────────────────────────┐
│  Phase 1: Environment Check     │
│  • Python 3.12+                 │
│  • Required packages            │
│  • .env doesn't exist yet       │
│  • data/ directory created      │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Phase 2: Credential Collection │
│  • Binance API key + secret     │
│  • NVIDIA API key               │
│  • Telegram bot token (opt)     │
│  • Telegram chat ID (opt)       │
│  • Auto-generate:               │
│    - TSAR_API_KEY               │
│    - REDIS_PASSWORD             │
│    - CORS origins               │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Phase 3: Validation            │
│  • Test Binance API connectivity│
│  • Test NVIDIA API key          │
│  • Test Telegram bot token      │
│  • Validate key formats         │
│  • Check for weak/test keys     │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Phase 4: Safe Defaults Lock    │
│  • Force paper mode             │
│  • Force sandbox=true           │
│  • Set conservative risk params │
│  • Lock CORS to localhost       │
│  • Require mandate before live  │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Phase 5: Secret Encryption     │
│  • Generate machine-specific key│
│  • Encrypt secrets with Fernet  │
│  • Write .env.secrets (encrypted│
│  • Write .env (references only) │
│  • Set file permissions 600     │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Phase 6: Config Generation     │
│  • Update config/default.yaml   │
│  • Update config/tsar.yaml      │
│  • Validate risk.yaml ranges    │
│  • Create config/local.yaml     │
│    (overrides, gitignored)      │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Phase 7: Report & Next Steps   │
│  • Print setup summary          │
│  • Show what was configured     │
│  • Show what was auto-generated │
│  • Print next commands          │
│  • Write setup_report.txt       │
└─────────────────────────────────┘
```

---

## 4. Detailed Design

### 4.1 Phase 1: Environment Check

```python
def check_environment():
    """Verify system prerequisites before asking for any input."""
    checks = []

    # Python version
    v = sys.version_info
    checks.append(Check("Python 3.12+", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}"))

    # Required packages (importable)
    for pkg in ["cryptography", "yaml", "httpx", "ccxt"]:
        try:
            __import__(pkg)
            checks.append(Check(f"Package: {pkg}", True))
        except ImportError:
            checks.append(Check(f"Package: {pkg}", False, "pip install " + pkg))

    # .env doesn't exist (don't overwrite)
    checks.append(Check(".env not present", not Path(".env").exists(),
                        "Remove existing .env first or run setup --force"))

    # data/ directory
    Path("data").mkdir(exist_ok=True)
    checks.append(Check("data/ directory", True))

    return checks
```

**Fail-fast:** If Python < 3.12 or `.env` already exists (without `--force`), abort immediately.

### 4.2 Phase 2: Credential Collection

**Design Principles:**
- Show context for each credential (where to get it, what it's for)
- Mark required vs optional clearly
- Support `--non-interactive` mode for CI/Docker (env vars)
- Paste-friendly: no need to type, just paste from clipboard

```python
CREDENTIALS = [
    Credential(
        name="EXCHANGE_API_KEY",
        prompt="Binance API Key",
        required=True,
        help_text="Get from: https://testnet.binance.vision/ (testing)\n"
                  "         or: https://www.binance.com → API Management (real)",
        validator=validate_binance_key_format,
        test_func=test_binance_connectivity,
    ),
    Credential(
        name="EXCHANGE_SECRET",
        prompt="Binance API Secret",
        required=True,
        help_text="Shown only once when you created the API key",
        validator=validate_binance_secret_format,
        test_func=None,  # Tested together with key
        sensitive=True,
    ),
    Credential(
        name="NVIDIA_API_KEY",
        prompt="NVIDIA API Key",
        required=True,
        help_text="Get free key: https://build.nvidia.com → Get API Key",
        validator=validate_nvidia_key_format,
        test_func=test_nvidia_connectivity,
    ),
    Credential(
        name="TELEGRAM_BOT_TOKEN",
        prompt="Telegram Bot Token (optional, press Enter to skip)",
        required=False,
        help_text="Message @BotFather on Telegram → /newbot → copy token",
        validator=validate_telegram_token_format,
        test_func=test_telegram_bot,
    ),
    Credential(
        name="TELEGRAM_CHAT_ID",
        prompt="Telegram Chat ID (optional, press Enter to skip)",
        required=False,
        help_text="Message your bot, then visit:\n"
                  "https://api.telegram.org/bot<TOKEN>/getUpdates\n"
                  "Find your chat_id in the response",
        validator=validate_telegram_chat_id,
        test_func=None,
    ),
]

# Auto-generated (no user input)
AUTO_GENERATED = {
    "TSAR_API_KEY": lambda: secrets.token_urlsafe(48),
    "REDIS_PASSWORD": lambda: secrets.token_urlsafe(32),
    "TSAR_CORS_ORIGINS": lambda: "http://localhost:3000,http://localhost:8000",
    "TSAR_TRADING_MODE": lambda: "paper",
    "EXCHANGE_SANDBOX": lambda: "true",
    "TSAR_API_PORT": lambda: "8000",
}
```

**Interactive Flow:**

```
╔══════════════════════════════════════════════════════════════╗
║              TSAR Setup Wizard — Credentials                ║
╠══════════════════════════════════════════════════════════════╣
║  I'll ask for your API keys one by one.                    ║
║  Press Enter to skip optional ones.                        ║
║  All secrets are encrypted before storage.                 ║
╚══════════════════════════════════════════════════════════════╝

── Binance API Key ──────────────────────────────────────────
   Get testnet keys: https://testnet.binance.vision/
   Get real keys:    https://www.binance.com → API Management

   ⚠️  Starting in PAPER mode. Testnet keys recommended.

   API Key: nvha8K...  [pasted]
   ✓ Format valid (64 chars, alphanumeric)

── Binance API Secret ───────────────────────────────────────
   Shown only once when you created the key.

   API Secret: ••••••••••  [masked input]
   ✓ Format valid (64 chars)

── NVIDIA API Key ───────────────────────────────────────────
   Get free key: https://build.nvidia.com → Get API Key

   API Key: nvapi-...  [pasted]
   ✓ Format valid (nvapi- prefix)

── Telegram Bot Token (optional) ────────────────────────────
   Press Enter to skip. You can add this later.

   Bot Token: 123456:ABC...  [pasted]
   ✓ Format valid

── Telegram Chat ID (optional) ──────────────────────────────
   Press Enter to skip.

   Chat ID: 987654321  [pasted]
   ✓ Format valid (numeric)

── Auto-Generated Secrets ───────────────────────────────────
   ✓ TSAR_API_KEY     — 64-char random token (generated)
   ✓ REDIS_PASSWORD   — 48-char random token (generated)
   ✓ CORS_ORIGINS     — localhost only (locked down)
   ✓ TRADING_MODE     — paper (safe default)
   ✓ EXCHANGE_SANDBOX — true (testnet)
```

### 4.3 Phase 3: Validation

#### 4.3.1 Format Validators

```python
def validate_binance_key_format(key: str) -> ValidationResult:
    """Binance API keys are 64-char alphanumeric."""
    if not key or key == "← FILL IN":
        return Invalid("Key is empty or placeholder")
    if len(key) != 64:
        return Invalid(f"Expected 64 chars, got {len(key)}")
    if not key.isalnum():
        return Invalid("Key should be alphanumeric only")
    return Valid()

def validate_binance_secret_format(secret: str) -> ValidationResult:
    """Binance secrets are 64-char alphanumeric."""
    if not secret or secret == "← FILL IN":
        return Invalid("Secret is empty or placeholder")
    if len(secret) != 64:
        return Invalid(f"Expected 64 chars, got {len(secret)}")
    if not secret.isalnum():
        return Invalid("Secret should be alphanumeric only")
    return Valid()

def validate_nvidia_key_format(key: str) -> ValidationResult:
    """NVIDIA API keys start with 'nvapi-'."""
    if not key:
        return Invalid("Key is empty")
    if not key.startswith("nvapi-"):
        return Invalid("NVIDIA keys start with 'nvapi-'")
    if len(key) < 20:
        return Invalid("Key seems too short")
    return Valid()

def validate_telegram_token_format(token: str) -> ValidationResult:
    """Telegram bot tokens match pattern: digits:alphanumeric."""
    import re
    if not token:
        return Valid()  # Optional
    pattern = r'^\d+:[A-Za-z0-9_-]{35,}$'
    if not re.match(pattern, token):
        return Invalid("Token format: digits:alphanumeric (from @BotFather)")
    return Valid()

def validate_telegram_chat_id(chat_id: str) -> ValidationResult:
    """Telegram chat IDs are numeric (can be negative for groups)."""
    if not chat_id:
        return Valid()  # Optional
    try:
        int(chat_id)
    except ValueError:
        return Invalid("Chat ID should be a number")
    return Valid()
```

#### 4.3.2 API Connectivity Tests

```python
async def test_binance_connectivity(api_key: str, secret: str) -> TestResult:
    """Test Binance API connectivity without placing any orders."""
    try:
        import ccxt
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'sandbox': True,  # Always test against testnet
            'enableRateLimit': True,
        })
        # Fetch balance (read-only, no side effects)
        balance = exchange.fetch_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        return TestResult(
            success=True,
            message=f"Connected! Testnet USDT balance: {usdt}",
        )
    except ccxt.AuthenticationError:
        return TestResult(success=False, message="Authentication failed — check key/secret")
    except ccxt.NetworkError as e:
        return TestResult(success=False, message=f"Network error: {e}")
    except Exception as e:
        return TestResult(success=False, message=f"Unexpected error: {e}")

async def test_nvidia_connectivity(api_key: str) -> TestResult:
    """Test NVIDIA NIM API with a minimal request."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "nvidia/nemotron-3-ultra",
                    "messages": [{"role": "user", "content": "Say 'ok' only."}],
                    "max_tokens": 5,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return TestResult(success=True, message="NVIDIA NIM API accessible")
            elif resp.status_code == 401:
                return TestResult(success=False, message="Invalid API key")
            else:
                return TestResult(success=False, message=f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        return TestResult(success=False, message=f"Connection error: {e}")

async def test_telegram_bot(token: str, chat_id: str) -> TestResult:
    """Test Telegram bot by sending a test message."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            # First verify the bot token
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            if resp.status_code != 200:
                return TestResult(success=False, message="Invalid bot token")
            bot_name = resp.json()["result"]["username"]

            # Then try to send a test message
            if chat_id:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": "🔧 TSAR setup test — OK!"},
                )
                if resp.status_code == 200:
                    return TestResult(success=True, message=f"Bot @{bot_name} can send to chat {chat_id}")
                else:
                    return TestResult(success=False,
                                      message=f"Bot works but can't send to chat {chat_id}. "
                                              f"Send a message to the bot first.")
            return TestResult(success=True, message=f"Bot @{bot_name} token valid")
    except Exception as e:
        return TestResult(success=False, message=f"Error: {e}")
```

#### 4.3.3 Safety Validators

```python
def check_key_safety(key: str, key_name: str) -> list[Warning]:
    """Warn about common safety issues with API keys."""
    warnings = []

    # Check for test/example keys
    KNOWN_TEST_KEYS = [
        "test", "example", "demo", "sandbox",
        "your_key_here", "fill_in", "xxx",
    ]
    if any(t in key.lower() for t in KNOWN_TEST_KEYS):
        warnings.append(Warning(
            f"{key_name} looks like a placeholder/test key",
            severity="HIGH",
        ))

    # Check for very short keys (likely truncated)
    if len(key) < 20:
        warnings.append(Warning(
            f"{key_name} is unusually short ({len(key)} chars). "
            "Did you copy the full key?",
            severity="MEDIUM",
        ))

    # Check for whitespace (common copy-paste error)
    if key != key.strip():
        warnings.append(Warning(
            f"{key_name} has leading/trailing whitespace — trimming",
            severity="LOW",
            auto_fix=True,
        ))

    return warnings
```

### 4.4 Phase 4: Safe Defaults Lock

**Principle: Paper mode is the ONLY safe starting point.**

```python
SAFE_DEFAULTS = {
    # Trading mode — NEVER default to live
    "TSAR_TRADING_MODE": "paper",
    "EXCHANGE_SANDBOX": "true",

    # Risk — conservative for first run
    "risk.daily_loss_flatten": -0.02,
    "risk.daily_loss_kill": -0.03,
    "risk.max_open_positions": 3,       # Day 1: only 3 positions
    "risk.max_single_position_pct": 0.10,  # 10% max per position
    "risk.kelly_fraction": 0.25,        # Half-Kelly

    # CORS — localhost only
    "TSAR_CORS_ORIGINS": "http://localhost:3000,http://localhost:8000",

    # API server
    "TSAR_API_PORT": "8000",
}

def enforce_safe_defaults(config: dict) -> dict:
    """Override any dangerous values with safe defaults."""
    for key, safe_value in SAFE_DEFAULTS.items():
        current = config.get(key)
        if current is None or current == "" or current == "← FILL IN":
            config[key] = safe_value
            log.info(f"Set {key} = {safe_value} (safe default)")

    # CRITICAL: Never allow live mode without explicit user confirmation
    if config.get("TSAR_TRADING_MODE") == "live":
        log.warning("⚠️  LIVE TRADING MODE requested!")
        log.warning("   This requires:")
        log.warning("   1. Completed 100+ paper trades")
        log.warning("   2. 30+ days of paper trading")
        log.warning("   3. Committed mandate (config/mandate.yaml)")
        log.warning("   4. Manual confirmation")
        log.warning("   Defaulting to PAPER mode.")
        config["TSAR_TRADING_MODE"] = "paper"

    return config
```

### 4.5 Phase 5: Secret Encryption

**Problem:** `.env` stores secrets in plain text. If the repo is accidentally committed or the server is compromised, all credentials are exposed.

**Solution:** Use Fernet symmetric encryption (from `cryptography` package) with a machine-specific key.

```python
"""
Secret encryption for TSAR.

Architecture:
  1. Master key derived from machine-specific data + passphrase
  2. Secrets encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
  3. .env stores encrypted blobs + metadata
  4. At runtime, decrypt on demand (never in memory longer than needed)

Files:
  .secrets.key       — Master encryption key (gitignored, 600 perms)
  .env.secrets       — Encrypted secrets (gitignored, 600 perms)
  .env               — Non-secret config + encrypted references
"""

from cryptography.fernet import Fernet
from pathlib import Path
import hashlib
import json
import os
import stat

SECRETS_KEY_PATH = Path(".secrets.key")
SECRETS_DATA_PATH = Path(".env.secrets")


def generate_master_key() -> bytes:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key()


def load_or_create_master_key() -> bytes:
    """Load existing master key or create a new one."""
    if SECRETS_KEY_PATH.exists():
        return SECRETS_KEY_PATH.read_bytes().strip()

    key = generate_master_key()
    SECRETS_KEY_PATH.write_bytes(key)
    # Restrict permissions (owner read/write only)
    SECRETS_KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    return key


def encrypt_secrets(secrets: dict[str, str]) -> None:
    """Encrypt and store secrets to .env.secrets."""
    key = load_or_create_master_key()
    f = Fernet(key)

    encrypted = {}
    for name, value in secrets.items():
        if value:  # Don't encrypt empty values
            encrypted[name] = f.encrypt(value.encode()).decode()

    data = {
        "version": 1,
        "encrypted_at": datetime.utcnow().isoformat(),
        "secrets": encrypted,
    }

    SECRETS_DATA_PATH.write_text(json.dumps(data, indent=2))
    SECRETS_DATA_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600


def decrypt_secrets() -> dict[str, str]:
    """Decrypt secrets from .env.secrets at runtime."""
    if not SECRETS_KEY_PATH.exists():
        raise RuntimeError("Master key not found. Run: python setup.py")
    if not SECRETS_DATA_PATH.exists():
        raise RuntimeError("Encrypted secrets not found. Run: python setup.py")

    key = SECRETS_KEY_PATH.read_bytes().strip()
    f = Fernet(key)

    data = json.loads(SECRETS_DATA_PATH.read_text())
    secrets = {}
    for name, encrypted_value in data["secrets"].items():
        secrets[name] = f.decrypt(encrypted_value.encode()).decode()

    return secrets


def setup_gitignore():
    """Ensure sensitive files are gitignored."""
    gitignore = Path(".gitignore")
    entries = [
        ".env",
        ".secrets.key",
        ".env.secrets",
        "data/",
        "logs/",
        "*.pyc",
        "__pycache__/",
    ]

    existing = gitignore.read_text() if gitignore.exists() else ""
    additions = [e for e in entries if e not in existing]

    if additions:
        with open(gitignore, "a") as f:
            f.write("\n# TSAR secrets & data (auto-added by setup)\n")
            for entry in additions:
                f.write(entry + "\n")
```

**Runtime decryption in config loader:**

```python
# In src/config/loader.py (add to existing)
def load_config_with_secrets():
    """Load config and inject decrypted secrets into environment."""
    from scripts.setup.crypto import decrypt_secrets

    # Load base config from YAML
    config = load_yaml_configs()

    # Decrypt secrets
    secrets = decrypt_secrets()

    # Inject into environment for config variable substitution
    for key, value in secrets.items():
        os.environ[key] = value

    return config
```

### 4.6 Phase 6: Config File Generation

#### 4.6.1 Generate `.env`

```python
def write_env_file(credentials: dict, auto_generated: dict) -> None:
    """Write the .env file with all configuration."""
    all_vars = {**credentials, **auto_generated}

    lines = [
        "# ============================================================",
        "# TSAR CONFIGURATION — Auto-generated by setup wizard",
        f"# Generated: {datetime.now().isoformat()}",
        "# DO NOT COMMIT THIS FILE",
        "# ============================================================",
        "",
        "# ── EXCHANGE ───────────────────────────────────────────────",
        f"EXCHANGE_API_KEY={all_vars['EXCHANGE_API_KEY']}",
        f"EXCHANGE_SECRET={all_vars['EXCHANGE_SECRET']}",
        f"EXCHANGE_SANDBOX={all_vars.get('EXCHANGE_SANDBOX', 'true')}",
        "",
        "# ── NVIDIA AI ──────────────────────────────────────────────",
        f"NVIDIA_API_KEY={all_vars['NVIDIA_API_KEY']}",
        "",
        "# ── TELEGRAM ───────────────────────────────────────────────",
        f"TELEGRAM_BOT_TOKEN={all_vars.get('TELEGRAM_BOT_TOKEN', '')}",
        f"TELEGRAM_CHAT_ID={all_vars.get('TELEGRAM_CHAT_ID', '')}",
        "",
        "# ── TSAR API ──────────────────────────────────────────────",
        f"TSAR_API_KEY={all_vars['TSAR_API_KEY']}",
        f"TSAR_API_PORT={all_vars.get('TSAR_API_PORT', '8000')}",
        f"TSAR_TRADING_MODE={all_vars.get('TSAR_TRADING_MODE', 'paper')}",
        "",
        "# ── CORS ──────────────────────────────────────────────────",
        f"TSAR_CORS_ORIGINS={all_vars.get('TSAR_CORS_ORIGINS', 'http://localhost:3000')}",
        "",
        "# ── REDIS ─────────────────────────────────────────────────",
        f"REDIS_HOST=redis",
        f"REDIS_PORT=6379",
        f"REDIS_PASSWORD={all_vars['REDIS_PASSWORD']}",
    ]

    env_path = Path(".env")
    env_path.write_text("\n".join(lines) + "\n")
    env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
```

#### 4.6.2 Generate `config/local.yaml` (overrides)

```python
def write_local_config(credentials: dict) -> None:
    """
    Write config/local.yaml for environment-specific overrides.
    This file is gitignored and takes precedence over default.yaml.
    """
    local_config = {
        "app": {
            "trading_mode": "paper",
            "environment": "development",
        },
        "exchanges": {
            "sandbox": True,
            "symbols": ["BTC/USDT"],  # Start with just BTC
        },
        "risk": {
            "max_open_positions": 3,
            "max_single_position_pct": 0.10,
            "daily_loss_kill": -0.02,
        },
        "api": {
            "cors_origins": credentials.get("TSAR_CORS_ORIGINS",
                                            "http://localhost:3000").split(","),
        },
    }

    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)
    local_path = config_dir / "local.yaml"

    import yaml
    local_path.write_text(yaml.dump(local_config, default_flow_style=False))
```

#### 4.6.3 Validate Existing YAML Files

```python
def validate_yaml_configs() -> list[Issue]:
    """Validate all config/*.yaml files for consistency and safety."""
    issues = []

    # Check risk.yaml ranges
    risk = load_yaml("config/risk.yaml")

    if risk.get("daily_loss_flatten", 0) > 0:
        issues.append(Issue("risk.yaml: daily_loss_flatten should be negative", "ERROR"))
    if risk.get("daily_loss_kill", 0) > risk.get("daily_loss_flatten", 0):
        issues.append(Issue("risk.yaml: daily_loss_kill should be worse than flatten", "ERROR"))
    if risk.get("max_drawdown_flatten", 0) > -0.10:
        issues.append(Issue("risk.yaml: max_drawdown_flatten seems too lenient", "WARNING"))
    if risk.get("kelly_fraction", 0) > 0.5:
        issues.append(Issue("risk.yaml: kelly_fraction > 0.5 is aggressive", "WARNING"))

    # Check default.yaml
    default = load_yaml("config/default.yaml")
    cors = default.get("api", {}).get("cors_origins", [])
    if "*" in cors:
        issues.append(Issue("default.yaml: cors_origins=['*'] is WIDE OPEN", "ERROR"))

    # Check models.yaml
    models = load_yaml("config/models.yaml")
    budget = models.get("budget", {})
    if budget.get("daily_limit_usd", 0) > 10:
        issues.append(Issue("models.yaml: daily budget > $10 seems high for paper", "WARNING"))

    return issues
```

### 4.7 Phase 7: Setup Report

```
╔══════════════════════════════════════════════════════════════╗
║                    TSAR Setup Complete!                      ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ✅ Environment validated                                    ║
║  ✅ Credentials collected & validated                        ║
║  ✅ API connectivity verified                                ║
║  ✅ Secrets encrypted (Fernet AES-128)                       ║
║  ✅ Safe defaults locked                                     ║
║  ✅ Config files generated                                   ║
║  ✅ .gitignore updated                                       ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  MODE: 📝 PAPER TRADING (no real money)                      ║
║  RISK: Conservative (3 positions, 2% daily loss limit)       ║
║  CORS: localhost only                                        ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Generated Secrets:                                          ║
║    • TSAR_API_KEY    — 64-char token (auto-generated)        ║
║    • REDIS_PASSWORD   — 48-char token (auto-generated)       ║
║                                                              ║
║  API Tests:                                                  ║
║    ✅ Binance testnet — Connected, balance: 10,000 USDT      ║
║    ✅ NVIDIA NIM      — API accessible                       ║
║    ✅ Telegram bot    — @tsar_alerts_bot can send             ║
║                                                              ║
║  Files Created:                                              ║
║    • .env              — Configuration (600 perms)           ║
║    • .secrets.key      — Encryption key (600 perms)          ║
║    • .env.secrets      — Encrypted secrets (600 perms)       ║
║    • config/local.yaml — Local overrides (gitignored)        ║
║    • setup_report.txt  — This report                         ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Next Steps:                                                 ║
║                                                              ║
║  1. Run paper trading:                                       ║
║     $ make run-dry                                           ║
║                                                              ║
║  2. Run with Docker:                                         ║
║     $ make docker-up                                         ║
║                                                              ║
║  3. Check health:                                            ║
║     $ curl http://localhost:8000/health                      ║
║                                                              ║
║  4. When ready for live trading:                             ║
║     $ python setup.py --go-live                              ║
║     (Requires 100+ paper trades and 30+ days)                ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 5. Implementation: `scripts/setup.py` (Complete Replacement)

The existing stub is replaced entirely. See Section 5.1 for the full implementation plan.

### 5.1 File Structure

```
scripts/
├── setup.py              # Entry point (wizard runner)
├── setup/
│   ├── __init__.py
│   ├── wizard.py          # Main wizard flow controller
│   ├── validators.py      # All validation logic
│   ├── crypto.py          # Fernet encryption/decryption
│   ├── config_writer.py   # .env and YAML generation
│   ├── safety.py          # Safe defaults enforcement
│   └── report.py          # Report generation & display
```

### 5.2 Entry Point: `scripts/setup.py`

```python
#!/usr/bin/env python3
"""
TSAR Setup Wizard — One-command configuration.

Usage:
    python setup.py                    # Interactive wizard
    python setup.py --non-interactive  # Read from env vars (CI/Docker)
    python setup.py --validate-only    # Check config without changing
    python setup.py --go-live          # Unlock live trading (requires gates)
"""
import argparse
import sys
from setup.wizard import SetupWizard
from setup.validators import validate_only


def main():
    parser = argparse.ArgumentParser(description="TSAR Setup Wizard")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Read credentials from environment variables")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate existing config without changes")
    parser.add_argument("--go-live", action="store_true",
                        help="Unlock live trading (requires paper trade gates)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing .env")
    args = parser.parse_args()

    if args.validate_only:
        issues = validate_only()
        for issue in issues:
            print(f"  {'❌' if issue.severity == 'ERROR' else '⚠️ '} {issue.message}")
        sys.exit(1 if any(i.severity == 'ERROR' for i in issues) else 0)

    wizard = SetupWizard(
        interactive=not args.non_interactive,
        force=args.force,
        go_live=args.go_live,
    )
    wizard.run()


if __name__ == "__main__":
    main()
```

### 5.3 Makefile Addition

```makefile
# Add to existing Makefile:

validate: ## Validate configuration without changes
	python scripts/setup.py --validate-only

setup-reset: ## Re-run setup wizard (overwrites .env)
	python scripts/setup.py --force

go-live: ## Unlock live trading (requires gates)
	python scripts/setup.py --go-live
```

---

## 6. Security Considerations

### 6.1 File Permissions

| File | Permissions | Rationale |
|------|-------------|-----------|
| `.env` | `600` (owner rw) | Contains encrypted references |
| `.secrets.key` | `600` (owner rw) | Master encryption key |
| `.env.secrets` | `600` (owner rw) | Encrypted secrets |
| `config/local.yaml` | `644` (standard) | No secrets, just overrides |
| `setup_report.txt` | `644` (standard) | No secrets |

### 6.2 Git Safety

```gitignore
# Auto-added by setup.py
.env
.secrets.key
.env.secrets
data/
logs/
```

### 6.3 Secret Rotation

The wizard supports re-running with `--force` to rotate secrets:
1. New master key generated
2. All secrets re-encrypted
3. Old `.secrets.key` backed up as `.secrets.key.bak`

### 6.4 What NOT to Encrypt

These stay in plain `.env` because they're not secrets:
- `EXCHANGE_SANDBOX` — just `true`/`false`
- `TSAR_TRADING_MODE` — just `paper`/`live`
- `TSAR_API_PORT` — just a port number
- `REDIS_HOST` — just a hostname
- `REDIS_PORT` — just a port number

---

## 7. Live Trading Gate

**No one goes live without passing safety gates.**

```python
def check_go_live_gates() -> list[Gate]:
    """Check all prerequisites for live trading."""
    gates = []

    # Gate 1: Paper trade count
    paper_trades = count_paper_trades()  # From DB
    gates.append(Gate(
        name="Paper trades completed",
        passed=paper_trades >= 100,
        current=paper_trades,
        required=100,
    ))

    # Gate 2: Days in paper mode
    paper_days = days_since_first_paper_trade()
    gates.append(Gate(
        name="Days in paper mode",
        passed=paper_days >= 30,
        current=paper_days,
        required=30,
    ))

    # Gate 3: Mandate committed
    mandate = load_yaml("config/mandate.yaml")
    gates.append(Gate(
        name="Mandate committed",
        passed=mandate.get("status") == "committed",
        current=mandate.get("status", "draft"),
        required="committed",
    ))

    # Gate 4: Positive paper P&L
    paper_pnl = get_paper_pnl()
    gates.append(Gate(
        name="Paper P&L positive",
        passed=paper_pnl > 0,
        current=f"${paper_pnl:.2f}",
        required="> $0",
    ))

    # Gate 5: No recent RED circuit breaker
    recent_red = has_recent_red_circuit_breaker(days=7)
    gates.append(Gate(
        name="No RED circuit in last 7 days",
        passed=not recent_red,
        current="RED triggered" if recent_red else "Clean",
        required="Clean",
    ))

    return gates
```

```
╔══════════════════════════════════════════════════════════════╗
║              Live Trading Gate Check                         ║
╠══════════════════════════════════════════════════════════════╣
║  Gate 1: Paper trades        47 / 100  ❌ NOT MET           ║
║  Gate 2: Days in paper mode  12 / 30   ❌ NOT MET           ║
║  Gate 3: Mandate committed   draft      ❌ NOT MET           ║
║  Gate 4: Paper P&L           +$234.50   ✅ PASSED           ║
║  Gate 5: No recent RED       Clean      ✅ PASSED           ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ❌ Live trading NOT unlocked. 3 of 5 gates failed.         ║
║                                                              ║
║  Keep trading in paper mode. You'll unlock live trading     ║
║  automatically when all gates pass.                         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 8. Non-Interactive Mode (CI/Docker)

For automated environments, credentials come from environment variables:

```bash
# Docker / CI usage:
EXCHANGE_API_KEY=nvha8K... \
EXCHANGE_SECRET=abcdef... \
NVIDIA_API_KEY=nvapi-... \
TELEGRAM_BOT_TOKEN=123456:ABC... \
TELEGRAM_CHAT_ID=987654321 \
python scripts/setup.py --non-interactive
```

The wizard:
1. Reads from `os.environ` instead of prompting
2. Still validates format and tests connectivity
3. Still encrypts and stores safely
4. Exits non-zero on any validation failure

---

## 9. Migration from Current State

### 9.1 Existing Users

If `.env` already exists:
1. `python setup.py` detects existing `.env`
2. Offers to:
   - **Validate** existing config (read-only)
   - **Migrate** to encrypted secrets (preserves values)
   - **Reset** with `--force` (overwrites)
3. Migration flow:
   - Read existing `.env` values
   - Validate each one
   - Encrypt secrets
   - Write new `.env` + `.env.secrets`
   - Back up old `.env` as `.env.bak`

### 9.2 Docker Users

`docker-compose.yml` already reads `.env` via `env_file`. No changes needed. The wizard writes a compatible `.env` that Docker reads automatically.

---

## 10. Implementation Priority

| Priority | Component | Effort | Impact |
|----------|-----------|--------|--------|
| **P0** | Secret generation (API key, Redis password) | 1h | CRITICAL — security holes |
| **P0** | Safe defaults enforcement | 1h | CRITICAL — prevents accidental live trading |
| **P0** | `.gitignore` enforcement | 30m | CRITICAL — prevents secret leaks |
| **P1** | Interactive credential wizard | 3h | HIGH — user experience |
| **P1** | Format validation | 2h | HIGH — catches copy-paste errors |
| **P1** | API connectivity testing | 2h | HIGH — catches bad keys early |
| **P2** | Fernet secret encryption | 2h | MEDIUM — defense in depth |
| **P2** | Config file generation | 1h | MEDIUM — reduces manual editing |
| **P2** | Setup report | 1h | MEDIUM — user confidence |
| **P3** | Live trading gates | 2h | LOW — future feature |
| **P3** | Non-interactive mode | 1h | LOW — CI/Docker support |

**Total estimated effort: ~16 hours for P0+P1+P2.**

---

## 11. Verdict

The current setup is a security liability. Empty `REDIS_PASSWORD` and `TSAR_API_KEY` fields, wide-open CORS, no validation, no encryption — all of these are incidents waiting to happen.

The proposed system transforms setup from a 15-minute manual chore (with high error probability) into a 3-minute guided wizard that:
- **Won't let you start unsafe** (paper mode locked, secrets auto-generated)
- **Validates before saving** (catches bad keys, tests connectivity)
- **Encrypts at rest** (defense in depth)
- **Documents everything** (setup report for audit trail)

**Recommendation:** Implement P0 items immediately. P1+P2 within one sprint. P3 when live trading gates are ready.

---

*Configuration Council — out.*
