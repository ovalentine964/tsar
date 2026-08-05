# TSAR Connection Analysis — Full Stack Findings

## 1. Flutter Mobile App Analysis

### API Configuration (`mobile/lib/services/api_service.dart`)
- **Default backend URL**: `https://tsar-api.onrender.com`
- **Auth**: Bearer token via `Authorization` header
- **Singleton pattern**: `ApiService._instance` — one global client
- **Timeout**: 15 seconds default
- **Configure method**: `configure({baseUrl, apiKey, timeout})`

### Settings Storage (`mobile/lib/providers/settings_provider.dart`)
- **Base URL**: Stored in `SharedPreferences` under `api_base_url`
- **API Key**: Stored in `FlutterSecureStorage` (encrypted) under `tsar_api_key`
- **Default URL**: `https://tsar-api.onrender.com`
- **Auto-refresh**: Configurable 10s/30s/1m/5m intervals
- **On startup**: Loads settings from disk → calls `apiService.configure()` → unblocks all API calls

### Settings Screen (`mobile/lib/screens/settings_screen.dart`)
- **API CONNECTION** section with:
  - Base URL text field (hint: `https://tsar-api.onrender.com`)
  - API Key text field (obscured, hint: `Bearer token`)
  - "SAVE & CONNECT" button
- Also has: Appearance, Data Refresh, Mandate, Knowledge, DeFi, Blockchain, News, Strategies, About

### WebSocket (`mobile/lib/services/websocket_service.dart`)
- Converts `https://` → `wss://` for WebSocket connection
- Endpoint: `{baseUrl}/ws`
- Events: `price`, `trade_fill`, `risk_alert`, `pong`
- Auto-reconnect with exponential backoff (max 10 attempts)
- Heartbeat ping every 30 seconds

### Where Binance Keys Are Entered
**Binance keys are NOT entered in the app.** They are configured server-side in Render environment variables. The app only stores the TSAR backend URL and API key.

---

## 2. Render Backend API Analysis

### Main API (`src/api/app.py`)

**Authentication:**
- HTTPBearer scheme — `Authorization: Bearer <TSAR_API_KEY>`
- Health endpoints (`/health`, `/health/ready`, `/api/health`) are **exempt from auth**
- All other endpoints require valid API key
- Uses `secrets.compare_digest` for timing-safe comparison

**CORS:**
- Configured via `TSAR_CORS_ORIGINS` env var (comma-separated)
- If empty → all cross-origin requests denied
- Allows methods: GET, POST, PUT, DELETE
- Allows headers: Authorization, Content-Type

**Rate Limiting:**
- Global: 60 requests/minute per IP
- Kill switch & resume: 10/minute
- Backtest: 10/minute

**Endpoints (primary):**

| Endpoint | Method | Auth | Source |
|----------|--------|------|--------|
| `/health` | GET | No | KillSwitch + TradeMemory |
| `/health/ready` | GET | No | Static |
| `/health/detailed` | GET | Yes | Full component check |
| `/` | GET | Yes | Dashboard overview |
| `/api/v1/trades` | GET | Yes | TradeMemory.list_trades() |
| `/api/v1/trades/stats` | GET | Yes | TradeMemory.get_trade_stats() |
| `/api/v1/strategies` | GET | Yes | TradeMemory.get_strategy_summary() |
| `/api/v1/positions` | GET | Yes | TradeMemory.get_open_positions() |
| `/api/v1/pnl` | GET | Yes | TradeMemory stats + regime perf |
| `/api/v1/risk` | GET | Yes | KillSwitch + TradeMemory |
| `/api/v1/kill-switch` | POST | Yes | KillSwitch.activate() |
| `/api/v1/resume` | POST | Yes | KillSwitch.deactivate() |
| `/api/v1/regime` | GET | Yes | TradeMemory.get_performance_by_regime() |
| `/api/v1/factors` | GET | Yes | FACTOR_REGISTRY |
| `/api/v1/factors/compute` | GET | Yes | FactorLibrary |
| `/api/v1/factors/benchmark` | GET | Yes | FactorBenchmarker |
| `/api/v1/backtest` | POST | Yes | BacktestingTools |
| `/api/v1/flywheel` | GET | Yes | FlywheelHealth |
| `/api/v1/mandate` | GET | Yes | Mandate status |
| `/api/v1/mandate/commit` | POST | Yes | Mandate.commit() |
| `/api/v1/mandate/revoke` | POST | Yes | Mandate.revoke() |
| `/api/v1/paper/dashboard` | GET | Yes | Paper trading metrics |
| `/api/v1/paper/slippage` | GET | Yes | Slippage analysis |
| `/api/v1/paper/gate` | GET | Yes | Paper→live gate |
| `/api/v1/shadow/rules` | GET | Yes | RuleValidator |
| `/api/v1/shadow/extract` | POST | Yes | Shadow extraction |
| `/api/v1/knowledge/search` | GET | Yes | MemoryRecall FTS5 |
| `/api/v1/patterns` | GET | Yes | PatternLibrary |
| `/api/v1/lessons` | GET | Yes | LessonArchive |
| `/api/v1/backends` | GET | Yes | Backend registry |

**Mobile app aliases (no `/v1` prefix):**
All primary endpoints have aliases: `/api/dashboard`, `/api/trades`, `/api/risk`, `/api/positions`, `/api/pnl`, `/api/mandate`, `/api/factors`, `/api/strategies`, `/api/regime`, `/api/backends`, `/api/flywheel`, `/api/patterns`, `/api/lessons`

### Route Modules (`src/api/routes/`)

| Module | Endpoints |
|--------|-----------|
| `health.py` | `/health/detailed` (auth required) |
| `trading.py` | `/api/v1/trades/by-strategy`, `/api/v1/trades/by-symbol`, `/api/v1/trades/performance` |
| `portfolio.py` | `/api/v1/portfolio/summary`, `/api/v1/portfolio/equity-curve`, `/api/v1/portfolio/improvement` |

---

## 3. Dockerfile.trading Analysis

### Current State ✅
```dockerfile
FROM python:3.12-slim
CMD ["python", "-m", "src", "--paper", "--host", "0.0.0.0", "--port", "8000"]
```

**What it does right:**
- Runs `python -m src` which starts **both agents AND API** concurrently
- The `__main__.py` creates 13 agents + API server in the same process
- Paper mode by default (`--paper` flag)
- Copies `config/` directory (needed for mandate.yaml, tsar.yaml, etc.)
- SQLite database on persistent disk (`/app/data/tsar.db`)
- Health check at `/health` (no auth required)

**No updates needed.** The Dockerfile.trading is correctly configured for running API + trading together.

### Differences from main Dockerfile
| | `Dockerfile` | `Dockerfile.trading` |
|---|---|---|
| CMD | `uvicorn src.api.app:app` | `python -m src --paper` |
| What runs | API only | Full system (13 agents + API) |
| Use case | Web dashboard | Autonomous trading |

---

## 4. Connection Flow: App → Render → Binance

```
┌─────────────────┐                    ┌──────────────────────┐                  ┌─────────────────┐
│  Flutter App     │   Bearer token     │   Render Backend     │   API keys       │   Binance       │
│                  │                    │   (FastAPI)          │                  │   Testnet/Live  │
│  Settings Screen │ ── HTTPS ────────→│   Port 8000          │ ── HTTPS ──────→ │                 │
│  - Base URL      │   TSAR_API_KEY     │                      │   EXCHANGE_KEY   │   REST API      │
│  - API Key       │                    │   13 Trading Agents  │   EXCHANGE_SECRET│                 │
│                  │ ←── JSON ─────────│   TradeMemory (SQLite)│ ←── Market data ─│   WebSocket     │
│  Dashboard       │                    │   Risk Management    │ ←── Order fills ─│                 │
│  Trades          │   WebSocket        │   Strategy Engine    │                  │                 │
│  Risk            │ ←── wss:// ───────│                      │                  │                 │
│  Kill Switch     │   prices/fills     │   Kill Switch        │                  │                 │
└─────────────────┘                    └──────────────────────┘                  └─────────────────┘
```

### Key Security Points
1. **Binance keys never leave the server** — app only has TSAR_API_KEY
2. **TSAR_API_KEY** authenticates app → backend (separate from Binance keys)
3. **EXCHANGE_SANDBOX=true** routes to testnet.binance.vision (no real money)
4. **Mandate system** blocks live trading until paper gate requirements are met

---

## 5. Identified Issues & Fixes

### Issue 1: CORS must be configured for mobile ⚠️
**Problem**: If `TSAR_CORS_ORIGINS` is empty, all cross-origin requests are denied.
**Fix**: In Render Dashboard, set `TSAR_CORS_ORIGINS` to `*` (or specific origins).

### Issue 2: Mobile app default URL mismatch
**Problem**: `api_service.dart` defaults to `https://tsar-api.onrender.com` but `render.yaml` creates a service named `tsar-trading` → URL would be `https://tsar-trading.onrender.com`.
**Fix**: User must manually enter the correct Render URL in the app's Settings screen.

### Issue 3: No WebSocket endpoint in API ⚠️
**Problem**: The Flutter WebSocket service connects to `{baseUrl}/ws` but `app.py` doesn't define a `/ws` WebSocket endpoint.
**Impact**: WebSocket connection will fail → app falls back to polling (auto-refresh).
**Fix**: Either add a WebSocket endpoint to the API, or the app gracefully handles the missing endpoint (it does — `_scheduleReconnect` with backoff).

### Issue 4: Missing route aliases for some endpoints
**Problem**: Some `/api/v1/*` endpoints used by the mobile app don't have `/api/*` aliases:
- `/api/v1/trades/stats` → no `/api/trades/stats` alias
- `/api/v1/trades/performance` → no alias
- `/api/v1/portfolio/summary` → no alias
**Impact**: If the app uses non-v1 paths for these, they'll 404.
**Fix**: The app's `api_service.dart` consistently uses `/api/v1/*` paths, so this is not a blocker.

---

## 6. Files Created

| File | Purpose |
|------|---------|
| `CONNECTION_GUIDE.md` | Step-by-step guide: Binance keys → Render → APK → App |
| `test_chain.sh` | Full chain test script: health → auth → endpoints → Binance |
| `CONNECTION_ANALYSIS.md` | This file — detailed technical findings |
