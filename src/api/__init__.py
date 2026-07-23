"""
TSAR API — FastAPI REST endpoints for monitoring and control.

Endpoints:
  - /health:       System health (no auth)
  - /positions:    Current positions
  - /pnl:          P&L summary
  - /risk:         Risk state
  - /improvement:  Improvement metrics
  - /flywheel:     Flywheel health score
  - /kill-switch:  Emergency halt (POST, TRADE_ADMIN)
  - /resume:       Resume trading (POST, TRADE_ADMIN)
  - /strategies:   Strategy performance
  - /regime:       Current regime
  - /trades:       Trade history
  - /backends:     Backend registry status
"""

__all__: list[str] = []
