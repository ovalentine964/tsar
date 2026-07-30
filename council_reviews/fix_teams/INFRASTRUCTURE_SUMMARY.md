# Infrastructure Team — Fix Summary

**Team:** Infrastructure
**Date:** 2026-07-30
**Issues Addressed:** H-016, H-017, H-018, M-007, M-008, M-009, M-010

---

## H-016: CI Only Covers Python → RESOLVED

**File:** `.github/workflows/ci.yml`

### Changes
- **Added Rust build/test stage** (`rust` job):
  - Installs Rust toolchain 1.79 with clippy + rustfmt
  - Uses `Swatinem/rust-cache@v2` for cargo caching
  - Runs `cargo fmt --check`, `cargo clippy`, `cargo build`, `cargo test`
  - Working directory: `rust/`

- **Added C++ build/test stage** (`cpp` job):
  - Installs cmake, g++, libboost-dev
  - CMake configure with `-DTSAR_BUILD_TESTS=ON`
  - Builds with `cmake --build` and runs `ctest`

- **Updated Docker build dependencies**: now requires `[lint, typecheck, test, rust, cpp]`

### Verification
- All three language pipelines (Python, Rust, C++) run in parallel
- Docker build only triggers after all language tests pass

---

## H-017: Docker Compose Dev-Grade Only → RESOLVED

**Files:** `docker-compose.yml`, `Dockerfile`

### Changes to `docker-compose.yml`
- **Resource limits** on both services:
  - Redis: 1 CPU / 512MB limit, 0.25 CPU / 128MB reservation
  - App: 2 CPU / 1GB limit, 0.5 CPU / 256MB reservation
- **Log rotation** via `json-file` driver:
  - Redis: 10MB max, 3 files
  - App: 20MB max, 5 files
- **Optional monitoring stack** (Prometheus + Grafana) behind `--profile monitoring`

### Changes to `Dockerfile`
- **Added Rust builder stage** (`rust-builder`): builds Rust release artifacts before Python build
- **Added `STOPSIGNAL SIGTERM`** for graceful shutdown
- Rust binaries copied into production image (if available)

### Backward Compatibility
- All existing health checks, restart policies, and volume mounts preserved
- Monitoring services only start with `docker compose --profile monitoring up`

---

## H-018: Monitoring Not Wired → RESOLVED

**Files:** `src/metrics/prometheus_export.py`, `src/metrics/__init__.py`, `grafana/`, `monitoring/`

### New: `src/metrics/prometheus_export.py`
Centralized `TSARMetrics` class wiring `prometheus_client` to all TSAR components:

| Component | Metrics |
|-----------|---------|
| **Trading** | `tsar_trades_total`, `tsar_trade_pnl`, `tsar_trade_slippage_bps`, `tsar_trade_latency_ms` |
| **Risk** | `tsar_portfolio_drawdown_pct`, `tsar_portfolio_heat`, `tsar_kill_switch_trips_total` |
| **Event Bus** | `tsar_events_published_total`, `tsar_events_consumed_total`, `tsar_events_dlq_total`, `tsar_event_handler_errors_total` |
| **Backend** | `tsar_backend_calls_total`, `tsar_backend_fallbacks_total`, `tsar_backend_errors_total` |
| **Database** | `tsar_db_pool_size`, `tsar_db_pool_checked_out`, `tsar_db_query_duration_seconds`, `tsar_db_connections_created_total` |
| **System** | `tsar_llm_tokens_total`, `tsar_llm_latency_seconds` |

### Graceful Degradation
- If `prometheus_client` is not installed, all metric operations become no-ops
- `get_metrics()` singleton accessor for easy component integration
- `export()` method returns Prometheus text format bytes

### Grafana Dashboard
- **`grafana/dashboards/tsar-overview.json`**: Pre-built dashboard with panels for:
  - Trading overview (total trades, win rate, drawdown, heat, kill switch, fallbacks)
  - Slippage & latency distribution (p50/p95/p99)
  - Event bus throughput (published/consumed/DLQ/errors)
  - Database connection pool & query latency
  - LLM latency & token usage

### Monitoring Infrastructure
- **`monitoring/prometheus.yml`**: Prometheus scrape config targeting `app:8000`
- **`grafana/provisioning/`**: Auto-provisioned datasource and dashboard provider
- Prometheus & Grafana added to `docker-compose.yml` as optional services

---

## M-007: BackendRegistry Fallback Chain Dead Code → RESOLVED

**File:** `src/interfaces/backend_registry.py`

### New Methods

#### `create_with_fallback(interface_name, config) → (instance, backend_name)`
- Attempts to instantiate backends in fallback-chain order (primary first)
- If primary raises during construction, tries next backend
- Returns `(instance, backend_name)` tuple
- Logs warnings for fallback activations
- Raises `RuntimeError` if all backends fail

#### `execute_with_fallback(interface_name, method_name, config, *args, **kwargs) → result`
- Tries to call `method_name` on each backend in the chain
- Each backend is freshly constructed (avoids stale state)
- If execution fails, falls back to next backend
- Supports both sync and async methods
- Detailed error aggregation in RuntimeError if all fail

### Usage Example
```python
registry = BackendRegistry()
registry.load_from_config("config/backends.yaml")

# Create with fallback
engine, name = registry.create_with_fallback("pricing_engine")

# Execute with fallback
result = await registry.execute_with_fallback(
    "pricing_engine", "calculate_rsi", closes=[...], period=14
)
```

---

## M-008: Event Bus No Persistence/DLQ → RESOLVED

**File:** `src/comms/event_bus.py`

### Changes
Complete rewrite of `EventBus` with:

#### Redis Streams Persistence
- When `redis_client` is provided, events are persisted via `XADD` to `tsar:stream:{event_type}`
- CloudEvents serialized to Redis Stream fields using existing `to_redis_fields()`
- Consumer group support via `start_consumer_group()` for scalable processing

#### Dead Letter Queue (DLQ)
- Events that fail processing after `_MAX_RETRIES` (3) attempts are moved to DLQ
- DLQ persisted to Redis stream `tsar:stream:dlq`
- In-memory DLQ always maintained for fast access (max 1000 entries)
- `get_dlq_events(limit)` to retrieve DLQ entries
- `retry_dlq_event(entry)` to re-process failed events
- `get_dlq_count()` for monitoring

#### Retry Logic
- Exponential backoff: 2s, 4s, 8s (capped at 30s)
- Per-event retry counters tracked by event ID
- Counters reset on successful processing

#### Backward Compatibility
- `bus = EventBus()` still works as in-process bus (no Redis required)
- All existing `subscribe()` / `publish()` patterns preserved
- Module-level `bus` singleton unchanged

---

## M-009: No Database Connection Pooling → RESOLVED

**File:** `src/knowledge/db_pool.py`, `src/knowledge/trade_memory.py`

### New: `src/knowledge/db_pool.py`
`SQLitePool` — Thread-safe SQLite connection pool:

| Feature | Description |
|---------|-------------|
| **Configurable pool size** | Default 5 persistent + 3 overflow connections |
| **WAL mode** | Pre-configured on all connections |
| **Health checking** | Dead connections detected and replaced |
| **Semaphore-based** | Blocks up to `timeout` when pool exhausted |
| **Thread-safe** | `threading.Lock` + `threading.Semaphore` |
| **Context managers** | `pool.connection()` and `pool.transaction()` |
| **Statistics** | `get_stats()` returns idle/in_use/created/errors |
| **Factory** | `get_pool(db_path)` singleton per database path |
| **Config-based** | `SQLitePool.from_config({...})` |

### Updated: `src/knowledge/trade_memory.py`
- Added optional `pool` parameter to `TradeMemory.__init__()`
- When pool is provided, `_conn()` uses `pool.connection()` context manager
- Without pool, falls back to direct connections (fully backward-compatible)
- New parameters: `pool_size`, `max_overflow` for convenience pool creation

### Usage
```python
from src.knowledge.db_pool import SQLitePool

# Create pool
pool = SQLitePool("data/tsar.db", pool_size=5)

# Use with TradeMemory
mem = TradeMemory("data/tsar.db", pool=pool)

# Or use pool directly
with pool.connection() as conn:
    conn.execute("SELECT * FROM trade_records")
```

---

## M-010: PricingEngine Sync vs Async Inconsistency → RESOLVED

**Files:** `src/interfaces/pricing_engine.py`, `src/backends/python/pandas_ta_engine.py`

### Changes to `PricingEngine` (ABC)
- All 6 abstract methods converted from sync to `async`:
  - `calculate_rsi()`, `calculate_macd()`, `calculate_bollinger()`
  - `calculate_atr()`, `calculate_ema()`, `detect_support_resistance()`

### Changes to `PandasTAEngine`
- All public methods are now `async`
- Sync pandas-ta computations extracted to `_sync_*` static methods
- Each async method validates inputs, then calls `await self._run_sync(self._sync_*, ...args)`
- `_run_sync()` dispatches to `loop.run_in_executor(None, ...)` to avoid blocking the event loop
- No behavioral changes — same computation, async interface

### Why This Matters
- Agents calling pricing engine can now `await` without blocking
- Rust/QuantLib backends can implement native async without wrapper overhead
- Consistent async interface across all backends

---

## Files Modified/Created Summary

| File | Action | Issue |
|------|--------|-------|
| `.github/workflows/ci.yml` | Modified | H-016 |
| `docker-compose.yml` | Modified | H-017, H-018 |
| `Dockerfile` | Modified | H-017 |
| `src/metrics/prometheus_export.py` | **Created** | H-018 |
| `src/metrics/__init__.py` | Modified | H-018 |
| `grafana/dashboards/tsar-overview.json` | **Created** | H-018 |
| `grafana/provisioning/datasources/prometheus.yml` | **Created** | H-018 |
| `grafana/provisioning/dashboards/dashboards.yml` | **Created** | H-018 |
| `monitoring/prometheus.yml` | **Created** | H-018 |
| `src/interfaces/backend_registry.py` | Modified | M-007 |
| `src/comms/event_bus.py` | **Rewritten** | M-008 |
| `src/knowledge/db_pool.py` | **Created** | M-009 |
| `src/knowledge/trade_memory.py` | Modified | M-009 |
| `src/knowledge/__init__.py` | Modified | M-009 |
| `src/interfaces/pricing_engine.py` | **Rewritten** | M-010 |
| `src/backends/python/pandas_ta_engine.py` | **Rewritten** | M-010 |

**Total:** 7 issues resolved, 8 files created, 8 files modified.
