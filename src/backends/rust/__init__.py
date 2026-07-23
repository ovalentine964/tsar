"""
Rust backends — Level 2+ implementations via PyO3.

Placeholder for Rust-accelerated backends:
  - RustWsGateway: WebSocket market data streaming (tokio-tungstenite)
  - RustTickEngine: High-performance OHLCV aggregation
  - RustExecEngine: Smart order routing
  - RustRiskEngine: Fast risk computation

These backends are loaded via PyO3 when the Rust extension is built.
Swap to them by changing config/backends.yaml — no code changes needed.
"""

__all__: list[str] = []
