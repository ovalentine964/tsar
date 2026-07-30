#!/usr/bin/env python3
"""
TSAR Setup Wizard — One-command configuration.

Usage:
    python scripts/setup.py                    # Interactive wizard
    python scripts/setup.py --non-interactive  # Read from env vars (CI/Docker)
    python scripts/setup.py --validate-only    # Check config without changing
    python scripts/setup.py --go-live          # Unlock live trading (requires gates)
    python scripts/setup.py --force            # Overwrite existing .env
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent))

from setup.wizard import SetupWizard
from setup.validators import validate_only


def main() -> None:
    parser = argparse.ArgumentParser(description="TSAR Setup Wizard")
    parser.add_argument(
        "--non-interactive", action="store_true",
        help="Read credentials from environment variables (for CI/Docker)",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Validate existing config without making changes",
    )
    parser.add_argument(
        "--go-live", action="store_true",
        help="Check live trading gates",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing .env",
    )
    args = parser.parse_args()

    if args.validate_only:
        issues = validate_only()
        if not issues:
            print("✅ Configuration looks good!")
            sys.exit(0)
        for issue in issues:
            icon = "❌" if issue["severity"] == "ERROR" else "⚠️ "
            print(f"  {icon} {issue['message']}")
        sys.exit(1 if any(i["severity"] == "ERROR" for i in issues) else 0)

    wizard = SetupWizard(
        interactive=not args.non_interactive,
        force=args.force,
        go_live=args.go_live,
    )
    wizard.run()


if __name__ == "__main__":
    main()
