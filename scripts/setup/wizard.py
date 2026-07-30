"""Main setup wizard flow controller."""

from __future__ import annotations

import getpass
import os
import secrets
import sys
from pathlib import Path

from .config_writer import setup_gitignore, write_env_file, write_local_yaml_config
from .crypto import encrypt_secrets
from .report import SetupReport, print_report, write_report_file
from .safety import check_go_live_gates, enforce_safe_defaults
from .validators import (
    fail,
    ok,
    test_binance_api,
    test_nvidia_api,
    test_telegram_bot,
    validate_binance_key,
    validate_binance_secret,
    validate_nvidia_key,
    validate_telegram_chat_id,
    validate_telegram_token,
    ValidationResult,
)

W = 60  # Terminal width for boxes


def _box(title: str) -> None:
    print()
    print("╔" + "═" * W + "╗")
    print("║" + title.center(W) + "║")
    print("╚" + "═" * W + "╝")


def _section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, W - len(title) - 5))


def _prompt_credential(
    name: str,
    prompt: str,
    required: bool,
    help_text: str,
    validator,
    sensitive: bool = False,
) -> str | None:
    """Prompt for a single credential with validation."""
    _section(prompt)
    if help_text:
        for line in help_text.split("\n"):
            print(f"   {line.strip()}")

    if sensitive:
        value = getpass.getpass(f"   {prompt}: ")
    else:
        value = input(f"   {prompt}: ").strip()

    if not value and not required:
        print("   ⏭️  Skipped")
        return None

    if not value and required:
        print("   ❌ Required — cannot continue without this")
        return None

    result: ValidationResult = validator(value)
    if not result.valid:
        print(f"   ❌ {result.message}")
        return None

    print(f"   ✅ {result.message}")
    for w in result.warnings:
        print(f"   ⚠️  {w}")

    return value.strip()


class SetupWizard:
    """Interactive setup wizard for TSAR."""

    def __init__(self, interactive: bool = True, force: bool = False, go_live: bool = False):
        self.interactive = interactive
        self.force = force
        self.go_live = go_live
        self.report = SetupReport()

    def run(self) -> None:
        """Execute the full setup wizard."""
        _box("TSAR — Trading Super Agent for Returns")
        print("   One-command setup wizard")
        print("   All secrets encrypted. Paper mode default.")

        if self.go_live:
            self._run_go_live()
            return

        try:
            self._phase_1_environment()
            credentials = self._phase_2_credentials()
            if credentials is None:
                return
            self._phase_3_validation(credentials)
            credentials = self._phase_4_safe_defaults(credentials)
            self._phase_5_encrypt_and_write(credentials)
            self._phase_6_gitignore()
            self._phase_7_report()
        except KeyboardInterrupt:
            print("\n\n   Setup cancelled by user.")
            sys.exit(1)

    # ── Phase 1: Environment Check ──────────────────────────────

    def _phase_1_environment(self) -> None:
        _box("Phase 1: Environment Check")

        # Python version
        v = sys.version_info
        if v >= (3, 12):
            print(f"   ✅ Python {v.major}.{v.minor}.{v.micro}")
        else:
            print(f"   ❌ Python 3.12+ required, got {v.major}.{v.minor}.{v.micro}")
            self.report.errors.append(f"Python {v.major}.{v.minor} < 3.12")
            sys.exit(1)

        # Required packages
        for pkg in ("cryptography", "yaml", "httpx"):
            try:
                __import__(pkg)
                print(f"   ✅ Package: {pkg}")
            except ImportError:
                print(f"   ❌ Package missing: {pkg}  →  pip install {pkg}")
                self.report.errors.append(f"Missing package: {pkg}")

        # ccxt optional (needed for Binance test)
        try:
            __import__("ccxt")
            print("   ✅ Package: ccxt")
        except ImportError:
            print("   ⚠️  Package: ccxt not installed (Binance test will be skipped)")

        if self.report.errors:
            print("\n   ❌ Fix the above errors and re-run.")
            sys.exit(1)

        # .env check
        if Path(".env").exists() and not self.force:
            print("   ❌ .env already exists. Use --force to overwrite.")
            sys.exit(1)
        elif Path(".env").exists() and self.force:
            print("   ⚠️  .env exists — will overwrite (--force)")
            Path(".env").rename(".env.bak")
            print("   📦 Backed up to .env.bak")

        # data/ directory
        Path("data").mkdir(exist_ok=True)
        print("   ✅ data/ directory ready")

    # ── Phase 2: Credential Collection ──────────────────────────

    def _phase_2_credentials(self) -> dict[str, str] | None:
        _box("Phase 2: Credentials")
        print("   Paste your API keys. Press Enter to skip optional ones.")
        print("   All secrets are encrypted before storage.")
        print()
        print("   ⚠️  Starting in PAPER mode. Testnet keys recommended.")

        credentials: dict[str, str] = {}

        # Binance API Key
        key = _prompt_credential(
            name="EXCHANGE_API_KEY",
            prompt="Binance API Key",
            required=True,
            help_text=(
                "Get testnet keys: https://testnet.binance.vision/\n"
                "Get real keys:    https://www.binance.com → API Management"
            ),
            validator=validate_binance_key,
        )
        if key is None:
            self.report.errors.append("Binance API Key is required")
            return None
        credentials["EXCHANGE_API_KEY"] = key
        self.report.credentials_collected.append("EXCHANGE_API_KEY")

        # Binance API Secret
        secret = _prompt_credential(
            name="EXCHANGE_SECRET",
            prompt="Binance API Secret",
            required=True,
            help_text="Shown only once when you created the API key",
            validator=validate_binance_secret,
            sensitive=True,
        )
        if secret is None:
            self.report.errors.append("Binance API Secret is required")
            return None
        credentials["EXCHANGE_SECRET"] = secret
        self.report.credentials_collected.append("EXCHANGE_SECRET")

        # NVIDIA API Key
        nvidia = _prompt_credential(
            name="NVIDIA_API_KEY",
            prompt="NVIDIA API Key",
            required=True,
            help_text="Get free key: https://build.nvidia.com → Get API Key",
            validator=validate_nvidia_key,
        )
        if nvidia is None:
            self.report.errors.append("NVIDIA API Key is required")
            return None
        credentials["NVIDIA_API_KEY"] = nvidia
        self.report.credentials_collected.append("NVIDIA_API_KEY")

        # Telegram Bot Token (optional)
        tg_token = _prompt_credential(
            name="TELEGRAM_BOT_TOKEN",
            prompt="Telegram Bot Token (optional)",
            required=False,
            help_text=(
                "Message @BotFather on Telegram → /newbot → copy token\n"
                "Press Enter to skip. You can add this later."
            ),
            validator=validate_telegram_token,
        )
        if tg_token:
            credentials["TELEGRAM_BOT_TOKEN"] = tg_token
            self.report.credentials_collected.append("TELEGRAM_BOT_TOKEN")

            # Telegram Chat ID (only ask if token provided)
            tg_chat = _prompt_credential(
                name="TELEGRAM_CHAT_ID",
                prompt="Telegram Chat ID (optional)",
                required=False,
                help_text=(
                    "Message your bot, then visit:\n"
                    "https://api.telegram.org/bot<TOKEN>/getUpdates\n"
                    "Find your chat_id in the response"
                ),
                validator=validate_telegram_chat_id,
            )
            if tg_chat:
                credentials["TELEGRAM_CHAT_ID"] = tg_chat
                self.report.credentials_collected.append("TELEGRAM_CHAT_ID")

        # Auto-generated secrets
        _section("Auto-Generated Secrets")
        auto = {
            "TSAR_API_KEY": secrets.token_urlsafe(48),
            "REDIS_PASSWORD": secrets.token_urlsafe(32),
            "TSAR_TRADING_MODE": "paper",
            "EXCHANGE_SANDBOX": "true",
            "TSAR_API_PORT": "8000",
            "TSAR_CORS_ORIGINS": "http://localhost:3000,http://localhost:8000",
        }
        for name in ("TSAR_API_KEY", "REDIS_PASSWORD", "TSAR_CORS_ORIGINS", "TSAR_TRADING_MODE", "EXCHANGE_SANDBOX"):
            print(f"   🔑 {name} — generated")
            self.report.auto_generated.append(name)

        credentials.update(auto)
        return credentials

    # ── Phase 3: Validation (API Connectivity) ──────────────────

    def _phase_3_validation(self, credentials: dict[str, str]) -> None:
        _box("Phase 3: API Connectivity Tests")

        # Binance
        print("   Testing Binance API...")
        try:
            result = test_binance_api(
                credentials["EXCHANGE_API_KEY"],
                credentials["EXCHANGE_SECRET"],
            )
            icon = "✅" if result.success else "❌"
            print(f"   {icon} Binance: {result.message}")
            self.report.api_tests.append({
                "name": "Binance", "success": result.success, "message": result.message,
            })
            if not result.success:
                self.report.warnings.append(f"Binance test failed: {result.message}")
        except Exception as e:
            print(f"   ⚠️  Binance test skipped: {e}")
            self.report.api_tests.append({
                "name": "Binance", "success": False, "message": f"Skipped: {e}",
            })

        # NVIDIA
        print("   Testing NVIDIA NIM API...")
        try:
            result = test_nvidia_api(credentials["NVIDIA_API_KEY"])
            icon = "✅" if result.success else "❌"
            print(f"   {icon} NVIDIA: {result.message}")
            self.report.api_tests.append({
                "name": "NVIDIA NIM", "success": result.success, "message": result.message,
            })
            if not result.success:
                self.report.warnings.append(f"NVIDIA test failed: {result.message}")
        except Exception as e:
            print(f"   ⚠️  NVIDIA test skipped: {e}")

        # Telegram (only if provided)
        if credentials.get("TELEGRAM_BOT_TOKEN"):
            print("   Testing Telegram bot...")
            try:
                result = test_telegram_bot(
                    credentials["TELEGRAM_BOT_TOKEN"],
                    credentials.get("TELEGRAM_CHAT_ID"),
                )
                icon = "✅" if result.success else "❌"
                print(f"   {icon} Telegram: {result.message}")
                self.report.api_tests.append({
                    "name": "Telegram", "success": result.success, "message": result.message,
                })
            except Exception as e:
                print(f"   ⚠️  Telegram test skipped: {e}")

    # ── Phase 4: Safe Defaults ──────────────────────────────────

    def _phase_4_safe_defaults(self, credentials: dict[str, str]) -> dict[str, str]:
        _box("Phase 4: Safe Defaults")

        credentials = enforce_safe_defaults(credentials)

        if "_live_trading_warning" in credentials:
            print(f"   ⚠️  {credentials.pop('_live_trading_warning')}")
            self.report.warnings.append("Live trading blocked — paper mode enforced")

        print("   ✅ Trading mode: paper")
        print("   ✅ Exchange sandbox: true")
        print("   ✅ CORS: localhost only")
        print("   ✅ Max positions: 3 (conservative)")
        print("   ✅ Daily loss limit: 2%")

        return credentials

    # ── Phase 5: Encrypt & Write ────────────────────────────────

    def _phase_5_encrypt_and_write(self, credentials: dict[str, str]) -> None:
        _box("Phase 5: Encryption & File Generation")

        # Separate secrets from non-secrets
        secret_keys = {"EXCHANGE_API_KEY", "EXCHANGE_SECRET", "NVIDIA_API_KEY",
                       "TSAR_API_KEY", "REDIS_PASSWORD", "TELEGRAM_BOT_TOKEN"}
        secrets_to_encrypt = {k: v for k, v in credentials.items() if k in secret_keys and v}

        # Encrypt
        print("   Encrypting secrets with Fernet (AES-128-CBC)...")
        encrypt_secrets(secrets_to_encrypt)
        print("   ✅ Secrets encrypted → .env.secrets")
        self.report.files_created.append(".secrets.key (encryption key)")
        self.report.files_created.append(".env.secrets (encrypted secrets)")

        # Write .env
        auto = {k: v for k, v in credentials.items() if k not in secret_keys}
        write_env_file(credentials, auto)
        print("   ✅ Configuration written → .env")
        self.report.files_created.append(".env")

        # Write config/local.yaml
        write_local_yaml_config(credentials.get("TSAR_TRADING_MODE", "paper"))
        print("   ✅ Local overrides → config/local.yaml")
        self.report.files_created.append("config/local.yaml")

    # ── Phase 6: Gitignore ──────────────────────────────────────

    def _phase_6_gitignore(self) -> None:
        added = setup_gitignore()
        if added:
            print(f"   ✅ .gitignore updated: {', '.join(added)}")
            self.report.gitignore_entries = added
        else:
            print("   ✅ .gitignore already configured")

    # ── Phase 7: Report ─────────────────────────────────────────

    def _phase_7_report(self) -> None:
        print_report(self.report)
        write_report_file(self.report)
        self.report.files_created.append("setup_report.txt")

    # ── Go-Live Gate ────────────────────────────────────────────

    def _run_go_live(self) -> None:
        _box("Live Trading Gate Check")
        gates = check_go_live_gates()

        all_passed = True
        for gate in gates:
            icon = "✅" if gate["passed"] else "❌"
            print(f"   {icon} {gate['name']}: {gate['current']} / {gate['required']}")
            if not gate["passed"]:
                all_passed = False
                print(f"      → {gate['note']}")

        print()
        if all_passed:
            print("   ✅ All gates passed! You can enable live trading.")
            print("   Run: TSAR_TRADING_MODE=live make run")
        else:
            failed = sum(1 for g in gates if not g["passed"])
            print(f"   ❌ {failed} of {len(gates)} gates failed.")
            print("   Keep trading in paper mode. Live trading unlocks automatically.")
