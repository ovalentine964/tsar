"""Setup report generation and display."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SetupReport:
    """Collects results from all setup phases for final report."""

    # Phase results
    env_checks: list[dict] = field(default_factory=list)
    credentials_collected: list[str] = field(default_factory=list)
    auto_generated: list[str] = field(default_factory=list)
    api_tests: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    gitignore_entries: list[str] = field(default_factory=list)
    live_trading_warning: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def print_report(report: SetupReport) -> None:
    """Print the setup report to terminal."""
    w = 60

    print()
    print("╔" + "═" * w + "╗")
    print("║" + " TSAR Setup Complete!".center(w) + "║")
    print("╠" + "═" * w + "╣")

    # Summary
    status = "✅" if report.success else "❌"
    print(f"║  {status} Overall: {'Success' if report.success else 'FAILED'}".ljust(w + 1) + "║")

    # Credentials
    if report.credentials_collected:
        print("║".ljust(w + 1) + "║")
        print("║  Credentials:".ljust(w + 1) + "║")
        for name in report.credentials_collected:
            print(f"║    ✅ {name}".ljust(w + 1) + "║")

    # Auto-generated
    if report.auto_generated:
        print("║".ljust(w + 1) + "║")
        print("║  Auto-Generated:".ljust(w + 1) + "║")
        for name in report.auto_generated:
            print(f"║    🔑 {name}".ljust(w + 1) + "║")

    # API tests
    if report.api_tests:
        print("║".ljust(w + 1) + "║")
        print("║  API Tests:".ljust(w + 1) + "║")
        for test in report.api_tests:
            icon = "✅" if test["success"] else "❌"
            print(f"║    {icon} {test['name']}: {test['message'][:40]}".ljust(w + 1) + "║")

    # Files
    if report.files_created:
        print("║".ljust(w + 1) + "║")
        print("║  Files Created:".ljust(w + 1) + "║")
        for f in report.files_created:
            print(f"║    📄 {f}".ljust(w + 1) + "║")

    # Warnings
    if report.warnings:
        print("║".ljust(w + 1) + "║")
        print("║  Warnings:".ljust(w + 1) + "║")
        for warn in report.warnings:
            print(f"║    ⚠️  {warn[:50]}".ljust(w + 1) + "║")

    # Mode banner
    print("╠" + "═" * w + "╣")
    print("║  MODE: 📝 PAPER TRADING (no real money)".ljust(w + 1) + "║")
    print("║  RISK: Conservative (3 positions, 2% daily loss)".ljust(w + 1) + "║")
    print("║  CORS: localhost only".ljust(w + 1) + "║")

    # Next steps
    print("╠" + "═" * w + "╣")
    print("║  Next Steps:".ljust(w + 1) + "║")
    print("║".ljust(w + 1) + "║")
    print("║  1. Run paper trading:".ljust(w + 1) + "║")
    print("║     $ make run-dry".ljust(w + 1) + "║")
    print("║".ljust(w + 1) + "║")
    print("║  2. Run with Docker:".ljust(w + 1) + "║")
    print("║     $ make docker-up".ljust(w + 1) + "║")
    print("║".ljust(w + 1) + "║")
    print("║  3. Validate config:".ljust(w + 1) + "║")
    print("║     $ python setup.py --validate-only".ljust(w + 1) + "║")
    print("║".ljust(w + 1) + "║")
    print("║  4. When ready for live:".ljust(w + 1) + "║")
    print("║     $ python setup.py --go-live".ljust(w + 1) + "║")
    print("╚" + "═" * w + "╝")
    print()


def write_report_file(report: SetupReport) -> None:
    """Write setup report to setup_report.txt."""
    lines = [
        "TSAR Setup Report",
        f"Generated: {datetime.now().isoformat()}",
        "=" * 50,
        "",
        f"Status: {'SUCCESS' if report.success else 'FAILED'}",
        "",
    ]

    if report.credentials_collected:
        lines.append("Credentials collected:")
        for name in report.credentials_collected:
            lines.append(f"  ✅ {name}")
        lines.append("")

    if report.auto_generated:
        lines.append("Auto-generated:")
        for name in report.auto_generated:
            lines.append(f"  🔑 {name}")
        lines.append("")

    if report.api_tests:
        lines.append("API tests:")
        for test in report.api_tests:
            icon = "✅" if test["success"] else "❌"
            lines.append(f"  {icon} {test['name']}: {test['message']}")
        lines.append("")

    if report.files_created:
        lines.append("Files created:")
        for f in report.files_created:
            lines.append(f"  📄 {f}")
        lines.append("")

    if report.warnings:
        lines.append("Warnings:")
        for warn in report.warnings:
            lines.append(f"  ⚠️  {warn}")
        lines.append("")

    if report.errors:
        lines.append("Errors:")
        for err in report.errors:
            lines.append(f"  ❌ {err}")
        lines.append("")

    Path("setup_report.txt").write_text("\n".join(lines) + "\n")
