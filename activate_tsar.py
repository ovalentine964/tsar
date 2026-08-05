#!/usr/bin/env python3
"""
TSAR Activation Script — Prerequisite Check + Activation + Monitoring

This script:
  a. Checks all prerequisites (env vars, configs, connectivity)
  b. Verifies strategy configuration is loaded
  c. Tests exchange gateway connectivity
  d. Provides the exact commands to activate TSAR on Render
  e. Monitors the first 10 minutes of operation via API

Usage:
    python3 activate_tsar.py              # Full check + activation guide
    python3 activate_tsar.py --check-only # Prerequisites only
    python3 activate_tsar.py --monitor    # Monitor running instance
"""

import json
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, UTC


# ═══════════════════════════════════════════════════════════════
# Colors for terminal output
# ═══════════════════════════════════════════════════════════════

class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def ok(msg: str):
    print(f"  {C.GREEN}✓{C.END} {msg}")

def fail(msg: str):
    print(f"  {C.RED}✗{C.END} {msg}")

def warn(msg: str):
    print(f"  {C.YELLOW}!{C.END} {msg}")

def info(msg: str):
    print(f"  {C.CYAN}ℹ{C.END} {msg}")

def header(msg: str):
    print(f"\n{C.BOLD}{C.BLUE}{'─' * 60}{C.END}")
    print(f"{C.BOLD}{C.BLUE}  {msg}{C.END}")
    print(f"{C.BOLD}{C.BLUE}{'─' * 60}{C.END}")


# ═══════════════════════════════════════════════════════════════
# Prerequisite Checks
# ═══════════════════════════════════════════════════════════════

def check_env_vars() -> dict[str, bool]:
    """Check all required and optional environment variables."""
    header("1. ENVIRONMENT VARIABLES")

    results = {}

    # Critical (blocks startup)
    critical = {
        "TSAR_API_KEY": "API authentication — generate with: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\"",
        "EXCHANGE_API_KEY": "Binance API key — get from https://testnet.binance.vision",
        "EXCHANGE_SECRET": "Binance API secret — get from https://testnet.binance.vision",
    }

    for var, desc in critical.items():
        val = os.environ.get(var, "").strip()
        if val and val not in ("PASTE_YOUR_TESTNET_API_KEY_HERE", "PASTE_YOUR_TESTNET_SECRET_HERE",
                                "GENERATE_ME_WITH_THE_COMMAND_BELOW", "${" + var + "}"):
            ok(f"{var} = {val[:8]}...{val[-4:]}")
            results[var] = True
        else:
            fail(f"{var} NOT SET — {desc}")
            results[var] = False

    # Important (degrades gracefully)
    important = {
        "NVIDIA_API_KEY": "NVIDIA NIM for LLM-enhanced signals (optional, degrades to statistical mode)",
        "REDIS_PASSWORD": "Redis auth (optional, in-memory bus works without it)",
    }

    for var, desc in important.items():
        val = os.environ.get(var, "").strip()
        if val and val not in ("PASTE_YOUR_NVIDIA_API_KEY_HERE", "GENERATE_ME_WITH_THE_COMMAND_BELOW"):
            ok(f"{var} = {val[:8]}...{val[-4:]}")
            results[var] = True
        else:
            warn(f"{var} not set — {desc}")
            results[var] = False

    # Mode check
    mode = os.environ.get("TSAR_TRADING_MODE", "paper")
    if mode == "paper":
        ok(f"TSAR_TRADING_MODE = {mode} (safe)")
    else:
        warn(f"TSAR_TRADING_MODE = {mode} (LIVE — ensure mandate is committed)")
    results["mode"] = mode

    return results


def check_config_files() -> bool:
    """Check that required config files exist and are valid."""
    header("2. CONFIGURATION FILES")

    all_ok = True

    required_files = {
        "config/tsar.yaml": "Main configuration",
        "config/strategies/mean_reversion.yaml": "Default strategy genome",
        "config/mandate.yaml": "Trading mandate",
        "config/risk.yaml": "Risk parameters",
    }

    for path, desc in required_files.items():
        if Path(path).exists():
            ok(f"{path} — {desc}")
        else:
            fail(f"{path} MISSING — {desc}")
            all_ok = False

    # Check tsar.yaml content
    try:
        import yaml
        with open("config/tsar.yaml") as f:
            config = yaml.safe_load(f)

        symbols = config.get("exchange", {}).get("symbols", [])
        if symbols:
            ok(f"Symbols configured: {symbols}")
        else:
            fail("No symbols configured in config/tsar.yaml")
            all_ok = False

        mode = config.get("trading_mode", "paper")
        ok(f"Trading mode: {mode}")

        db_path = config.get("database", {}).get("db_path", "data/tsar.db")
        info(f"Database path: {db_path}")

    except Exception as e:
        warn(f"Could not parse config/tsar.yaml: {e}")

    return all_ok


def check_python_deps() -> bool:
    """Check that required Python packages are installed."""
    header("3. PYTHON DEPENDENCIES")

    all_ok = True

    required = [
        ("ccxt", "Exchange connectivity"),
        ("pandas", "Data manipulation"),
        ("numpy", "Numerical computing"),
        ("pydantic", "Data validation"),
        ("yaml", "Config parsing"),
        ("fastapi", "API framework"),
        ("uvicorn", "ASGI server"),
        ("httpx", "HTTP client"),
        ("structlog", "Structured logging"),
    ]

    for module, desc in required:
        try:
            mod = __import__(module)
            version = getattr(mod, "__version__", "installed")
            ok(f"{module} ({version}) — {desc}")
        except ImportError:
            fail(f"{module} NOT INSTALLED — {desc}")
            all_ok = False

    return all_ok


def check_directories() -> bool:
    """Ensure data and logs directories exist."""
    header("4. DIRECTORIES")

    dirs = ["data", "logs"]
    all_ok = True

    for d in dirs:
        p = Path(d)
        if p.exists():
            ok(f"{d}/ exists")
        else:
            try:
                p.mkdir(exist_ok=True)
                ok(f"{d}/ created")
            except Exception as e:
                fail(f"Cannot create {d}/: {e}")
                all_ok = False

    return all_ok


def check_exchange_connectivity() -> bool:
    """Test exchange gateway connectivity."""
    header("5. EXCHANGE CONNECTIVITY")

    api_key = os.environ.get("EXCHANGE_API_KEY", "").strip()
    api_secret = os.environ.get("EXCHANGE_SECRET", "").strip()

    if not api_key or api_key == "PASTE_YOUR_TESTNET_API_KEY_HERE":
        fail("Cannot test — EXCHANGE_API_KEY not set")
        return False

    try:
        import ccxt
        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "sandbox": True,
            "enableRateLimit": True,
        })

        # Test public endpoint (no auth needed)
        ticker = exchange.fetch_ticker("BTC/USDT")
        ok(f"Binance testnet connected — BTC/USDT = ${ticker['last']:,.2f}")

        # Test authenticated endpoint
        try:
            balance = exchange.fetch_balance()
            usdt = balance.get("USDT", {}).get("free", 0)
            ok(f"Account balance: {usdt} USDT")
        except Exception as e:
            warn(f"Auth test failed (may need testnet setup): {e}")

        return True

    except ImportError:
        fail("ccxt not installed — run: pip install ccxt")
        return False
    except Exception as e:
        fail(f"Exchange connection failed: {e}")
        return False


def check_strategy_config() -> bool:
    """Verify strategy configuration is properly loaded."""
    header("6. STRATEGY CONFIGURATION")

    try:
        import yaml
        with open("config/strategies/mean_reversion.yaml") as f:
            strategy = yaml.safe_load(f)

        ok(f"Strategy: {strategy.get('name', 'unknown')}")
        ok(f"Status: {strategy.get('status', 'unknown')}")
        ok(f"Thesis: {strategy.get('thesis', 'unknown')[:60]}...")

        entry_rules = strategy.get("entry_rules", {}).get("conditions", [])
        ok(f"Entry rules: {len(entry_rules)} conditions")

        mutable = strategy.get("mutable_parameters", {})
        ok(f"Mutable parameters: {len(mutable)} (evolvable by StrategyGeneticist)")

        # Check min_signal_score
        min_score = strategy.get("entry_rules", {}).get("min_signal_score", 0.6)
        ok(f"Min signal score: {min_score}")

        return True

    except Exception as e:
        fail(f"Strategy config error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# Render Activation
# ═══════════════════════════════════════════════════════════════

def print_render_activation_guide():
    """Print the exact steps to activate TSAR on Render."""
    header("7. RENDER ACTIVATION STEPS")

    print(f"""
{C.BOLD}The TSAR Dockerfile currently ONLY starts the API server.{C.END}
{C.BOLD}It does NOT start the trading agents.{C.END}

{C.RED}CURRENT (broken):{C.END}
  CMD ["python", "-m", "uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

{C.GREEN}FIXED (trading enabled):{C.END}
  CMD ["python", "-m", "src", "--paper", "--host", "0.0.0.0", "--port", "8000"]

{C.BOLD}Steps to activate on Render:{C.END}

{C.CYAN}Step 1:{C.END} Go to Render Dashboard → tsar-api service → Environment
  Set these env vars:
    EXCHANGE_API_KEY = <your Binance testnet API key>
    EXCHANGE_SECRET  = <your Binance testnet secret>
    NVIDIA_API_KEY   = <your NVIDIA NIM API key>
    TSAR_TRADING_MODE = paper

{C.CYAN}Step 2:{C.END} Update the Dockerfile CMD:
  Replace the CMD line with:
    CMD ["python", "-m", "src", "--paper", "--host", "0.0.0.0", "--port", "8000"]

{C.CYAN}Step 3:{C.END} Commit and push — Render will auto-deploy

{C.CYAN}Step 4:{C.END} Monitor via Render logs — look for:
  "🏰 TSAR v0.2.0 — PAPER MODE"
  "✅ Created 13 agents"
  "🔄 Orchestrator starting..."
  "Scanning BTC/USDT for signals..."
""")


# ═══════════════════════════════════════════════════════════════
# Monitoring
# ═══════════════════════════════════════════════════════════════

def monitor_instance(base_url: str, api_key: str, duration_minutes: int = 10):
    """Monitor a running TSAR instance for the specified duration."""
    header(f"8. MONITORING ({duration_minutes} minutes)")

    import urllib.request
    import urllib.error

    headers = {"Authorization": f"Bearer {api_key}"}
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    check_interval = 30  # seconds

    cycle = 0
    while time.time() < end_time:
        cycle += 1
        elapsed = (time.time() - start_time) / 60
        print(f"\n{C.BOLD}[{elapsed:.1f}min] Check #{cycle}{C.END}")

        # Health check
        try:
            req = urllib.request.Request(f"{base_url}/health")
            with urllib.request.urlopen(req, timeout=10) as resp:
                health = json.loads(resp.read())
                status = health.get("status", "unknown")
                if status == "ok":
                    ok(f"Health: {status}")
                    components = health.get("components", {})
                    for comp, comp_status in components.items():
                        if comp_status == "healthy" or comp_status == "inactive":
                            ok(f"  {comp}: {comp_status}")
                        else:
                            warn(f"  {comp}: {comp_status}")
                else:
                    fail(f"Health: {status}")
        except Exception as e:
            fail(f"Health check failed: {e}")

        # Dashboard check
        try:
            req = urllib.request.Request(f"{base_url}/", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                dashboard = json.loads(resp.read())
                trades = dashboard.get("trades", {})
                total = trades.get("total", 0)
                info(f"Total trades: {total}")

                ks = dashboard.get("kill_switch", {})
                if ks.get("active"):
                    fail("Kill switch: ACTIVE")
                else:
                    ok("Kill switch: inactive")
        except Exception as e:
            warn(f"Dashboard check failed: {e}")

        # Trade stats
        try:
            req = urllib.request.Request(f"{base_url}/api/v1/trades/stats", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                stats = json.loads(resp.read())
                total = stats.get("total", stats.get("trade_count", 0))
                win_rate = stats.get("win_rate", 0)
                pnl = stats.get("total_pnl", 0)
                info(f"Trades: {total} | Win rate: {win_rate:.1f}% | P&L: ${pnl:.2f}")
        except Exception as e:
            warn(f"Trade stats unavailable: {e}")

        # Risk status
        try:
            req = urllib.request.Request(f"{base_url}/api/v1/risk", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                risk = json.loads(resp.read())
                level = risk.get("level", "unknown")
                positions = risk.get("open_positions", 0)
                info(f"Risk level: {level} | Open positions: {positions}")
        except Exception as e:
            warn(f"Risk check unavailable: {e}")

        if time.time() < end_time:
            time.sleep(check_interval)

    print(f"\n{C.GREEN}Monitoring complete — {duration_minutes} minutes elapsed.{C.END}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"""
{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║         TSAR — Activation Script                            ║
║         Prerequisite Check + Activation Guide + Monitor     ║
╚══════════════════════════════════════════════════════════════╝{C.END}
""")

    args = sys.argv[1:]
    check_only = "--check-only" in args
    monitor_mode = "--monitor" in args

    # If monitoring mode
    if monitor_mode:
        base_url = os.environ.get("TSAR_BASE_URL", "http://localhost:8000")
        api_key = os.environ.get("TSAR_API_KEY", "")
        if not api_key:
            fail("TSAR_API_KEY not set — cannot monitor")
            sys.exit(1)
        monitor_instance(base_url, api_key)
        return

    # Run all checks
    results = {}

    env_results = check_env_vars()
    results["env"] = all(v for k, v in env_results.items() if k not in ("mode",))
    results["env_critical"] = all(
        env_results.get(k, False)
        for k in ("TSAR_API_KEY", "EXCHANGE_API_KEY", "EXCHANGE_SECRET")
    )

    results["config"] = check_config_files()
    results["deps"] = check_python_deps()
    results["dirs"] = check_directories()
    results["exchange"] = check_exchange_connectivity()
    results["strategy"] = check_strategy_config()

    # Summary
    header("SUMMARY")

    critical_pass = results["env_critical"] and results["config"] and results["deps"]
    all_pass = all(results.values())

    checks = {
        "env_critical": "Critical env vars (TSAR_API_KEY, EXCHANGE_*)",
        "config": "Config files",
        "deps": "Python dependencies",
        "dirs": "Data directories",
        "exchange": "Exchange connectivity",
        "strategy": "Strategy configuration",
    }

    for key, label in checks.items():
        if results[key]:
            ok(label)
        else:
            fail(label)

    # Optional (non-blocking)
    optional = {"env": "All env vars including optional"}
    for key, label in optional.items():
        if results.get(key):
            ok(label)
        else:
            warn(label + " (non-blocking)")

    print()

    if not critical_pass:
        print(f"{C.RED}{C.BOLD}❌ CRITICAL CHECKS FAILED — TSAR cannot start.{C.END}")
        print(f"{C.RED}   Fix the ✗ items above, then re-run this script.{C.END}")
        sys.exit(1)

    if not all_pass:
        print(f"{C.YELLOW}{C.BOLD}⚠️  Some non-critical checks failed.{C.END}")
        print(f"{C.YELLOW}   TSAR will start but may have degraded functionality.{C.END}")

    if not check_only:
        print_render_activation_guide()

    print(f"\n{C.GREEN}{C.BOLD}✅ TSAR is ready to activate.{C.END}\n")


if __name__ == "__main__":
    main()
