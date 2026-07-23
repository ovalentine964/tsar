"""
TSAR Backends — Concrete implementations of abstract interfaces.

Two language backends:
  - python/: Day1 implementations (ccxt, pandas-ta, ollama, etc.)
  - rust/: Level 2+ implementations (WebSocket, tick engine, etc.)

Backends are selected via config/backends.yaml. Agents never import directly.
"""

__all__: list[str] = []
