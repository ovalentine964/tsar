"""Leverage enforcement guard — prevents overleveraging."""

import yaml

from src.risk.guards import Guard, GuardResult


class LeverageGuard(Guard):
    def __init__(self, config_path: str = "config/risk.yaml"):
        super().__init__("leverage_guard")
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
        except FileNotFoundError:
            cfg = {}
        self.max_leverage = cfg.get(
            "max_leverage", {"crypto_perp": 3, "forex_major": 20, "gold": 10}
        )

    def check(self, order) -> GuardResult:
        leverage = getattr(order, "leverage", 1.0)
        asset_type = getattr(order, "asset_type", "crypto_perp")
        max_lev = self.max_leverage.get(asset_type, 3)

        if leverage > max_lev:
            return GuardResult(
                passed=False,
                guard_name=self.name,
                reason=f"Leverage {leverage}x exceeds max {max_lev}x for {asset_type}",
                severity="CRITICAL",
            )
        return GuardResult(passed=True, guard_name=self.name)
