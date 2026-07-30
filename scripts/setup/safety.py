"""Safe defaults enforcement — paper mode, conservative risk."""

from __future__ import annotations

SAFE_DEFAULTS: dict[str, str] = {
    "TSAR_TRADING_MODE": "paper",
    "EXCHANGE_SANDBOX": "true",
    "TSAR_API_PORT": "8000",
    "TSAR_CORS_ORIGINS": "http://localhost:3000,http://localhost:8000",
}


def enforce_safe_defaults(config: dict[str, str]) -> dict[str, str]:
    """Override dangerous values with safe defaults. Returns updated config."""
    for key, safe_value in SAFE_DEFAULTS.items():
        current = config.get(key, "").strip()
        if not current or current in ("← FILL IN", "FILL IN"):
            config[key] = safe_value

    # CRITICAL: Never allow live mode without explicit confirmation
    if config.get("TSAR_TRADING_MODE", "").strip() == "live":
        config["_live_trading_warning"] = (
            "LIVE TRADING MODE requires:\n"
            "  1. 100+ completed paper trades\n"
            "  2. 30+ days of paper trading\n"
            "  3. Committed mandate (config/mandate.yaml)\n"
            "  4. Manual confirmation via: python setup.py --go-live\n"
            "Defaulting to PAPER mode."
        )
        config["TSAR_TRADING_MODE"] = "paper"

    return config


def check_go_live_gates() -> list[dict]:
    """Check prerequisites for live trading. Returns gate status list."""
    gates: list[dict] = []

    # Gate 1: Paper trade count (placeholder — real check reads from DB)
    gates.append({
        "name": "Paper trades completed",
        "required": 100,
        "current": 0,
        "passed": False,
        "note": "Start paper trading to accumulate trades",
    })

    # Gate 2: Days in paper mode
    gates.append({
        "name": "Days in paper mode",
        "required": 30,
        "current": 0,
        "passed": False,
        "note": "Keep paper trading for at least 30 days",
    })

    # Gate 3: Mandate committed
    try:
        from pathlib import Path
        import yaml  # type: ignore[import-untyped]
        mandate = yaml.safe_load(Path("config/mandate.yaml").read_text())
        committed = mandate.get("status") == "committed"
    except Exception:
        committed = False
    gates.append({
        "name": "Mandate committed",
        "required": "committed",
        "current": "draft" if not committed else "committed",
        "passed": committed,
        "note": "Commit your mandate via API/CLI",
    })

    return gates
