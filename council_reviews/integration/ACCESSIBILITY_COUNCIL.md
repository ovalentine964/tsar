# ACCESSIBILITY COUNCIL — Multi-Channel Access Architecture

**TSAR: Trading Super Agent Regime**
**Version:** 1.0.0 | **Date:** 2026-07-30 | **Status:** FINAL
**Authority:** Accessibility Council — Cross-Channel Integration Review

---

## TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [Channel Inventory & Capability Matrix](#2-channel-inventory--capability-matrix)
3. [Role-Based Access Control (RBAC)](#3-role-based-access-control-rbac)
4. [Cross-Channel State Synchronization](#4-cross-channel-state-synchronization)
5. [Push Notification Architecture](#5-push-notification-architecture)
6. [Security Model](#6-security-model)
7. [Offline Capability](#7-offline-capability)
8. [User Journey Maps](#8-user-journey-maps)
9. [API Gateway Design](#9-api-gateway-design)
10. [Mobile App Accessibility](#10-mobile-app-accessibility)
11. [Telegram Bot Deep Dive](#11-telegram-bot-deep-dive)
12. [Web Dashboard](#12-web-dashboard)
13. [Cross-Channel Command Parity](#13-cross-channel-command-parity)
14. [Failover & Degraded Mode](#14-failover--degraded-mode)
15. [Implementation Roadmap](#15-implementation-roadmap)
16. [Open Issues & Decisions](#16-open-issues--decisions)

---

## 1. EXECUTIVE SUMMARY

TSAR is accessed through four primary channels: **Telegram Bot**, **REST API**, **Mobile App (Flutter)**, and **Web Dashboard**. Each channel serves a distinct user context but must provide a unified, consistent view of the trading system's state. This document defines how users access TSAR across all channels, what they can do from each, and how the system maintains consistency, security, and resilience.

### Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Channel parity for reads** | Any query available on one channel must be answerable on all others |
| **Write operations channel-gated** | Destructive actions (trade execution, mandate changes) require appropriate channel security |
| **Single source of truth** | All channels read from the same SQLite `tsar.db` + Redis state; no channel maintains independent state |
| **Fail-safe everywhere** | Kill switch accessible from every channel; degraded mode preserves read access |
| **Least privilege** | API keys scoped per channel; Telegram chat ID whitelist; no shared credentials |

---

## 2. CHANNEL INVENTORY & CAPABILITY MATRIX

### 2.1 Channels

| Channel | Protocol | Primary Context | Auth Method | Latency Target |
|---------|----------|-----------------|-------------|----------------|
| **Telegram Bot** | Long-polling / Bot API | Mobile-first, conversational | Chat ID whitelist + Bot token | < 2s message delivery |
| **REST API** | HTTP/1.1 + JSON | Programmatic, integrations | Bearer token (`TSAR_API_KEY`) | < 200ms p95 |
| **Mobile App** | HTTP → REST API | On-the-go monitoring, quick actions | Bearer token (stored in app) | < 500ms including render |
| **Web Dashboard** | HTTP + vanilla JS | Desktop monitoring, quick overview | Bearer token (localStorage) | < 1s full page load |

### 2.2 Feature Parity Matrix

| Capability | Telegram | API | Mobile | Web |
|------------|----------|-----|--------|-----|
| **System status** | ✅ `/status` | ✅ `GET /health` | ✅ Dashboard | ✅ Auto-refresh |
| **P&L summary** | ✅ `/pnl` | ✅ `GET /api/v1/pnl` | ✅ P&L card | ✅ Stats card |
| **Open positions** | ✅ `/positions` | ✅ `GET /api/v1/positions` | ✅ Positions list | ✅ Positions card |
| **Risk state** | ✅ `/risk` | ✅ `GET /api/v1/risk` | ✅ Risk screen | ✅ Risk indicator |
| **Kill switch** | ✅ `/stop` + `/start` | ✅ `POST /api/v1/kill-switch` | ✅ FAB button | ✅ Red button |
| **Trade proposals** | ✅ Inline buttons | ❌ N/A (no approval flow) | ❌ Not yet | ❌ Not yet |
| **Trade approval** | ✅ Approve/Reject/Modify | ❌ | ❌ | ❌ |
| **Market regime** | ✅ `/regime` | ✅ `GET /api/v1/regime` | ✅ Via API | ✅ Via API |
| **Strategy genome** | ✅ `/strategy` | ✅ `GET /api/v1/strategies` | ✅ Strategies sheet | ❌ Not yet |
| **Flywheel health** | ✅ `/flywheel` | ✅ `GET /api/v1/flywheel` | ✅ Via API | ❌ Not yet |
| **Factor library** | ❌ Not exposed | ✅ `GET /api/v1/factors` | ✅ Factors screen | ❌ Not yet |
| **Backtest** | ❌ Not exposed | ✅ `POST /api/v1/backtest` | ❌ Not yet | ❌ Not yet |
| **Knowledge search** | ✅ `/ask` | ✅ `GET /api/v1/knowledge/search` | ✅ Settings sheet | ❌ Not yet |
| **Mandate management** | ❌ Not exposed | ✅ `GET/POST /api/v1/mandate` | ✅ Mandate sheet | ❌ Not yet |
| **Trade discussion** | ✅ `/discuss`, `/why` | ❌ | ❌ | ❌ |
| **Risk alerts** | ✅ Push notifications | ❌ (pull only) | ❌ (pull only) | ❌ (pull only) |
| **Regime change alerts** | ✅ Push notifications | ❌ | ❌ | ❌ |
| **Flywheel cycle alerts** | ✅ Push notifications | ❌ | ❌ | ❌ |

### 2.3 Channel Strengths

- **Telegram**: Only channel with **interactive trade approval** and **proactive push notifications**. The human-in-the-loop interface.
- **API**: Only channel with **full programmatic access** including backtest, factor computation, and mandate management. The integration interface.
- **Mobile**: Best **on-the-go monitoring** with kill switch FAB, auto-refresh, and offline-tolerant design. The emergency interface.
- **Web**: Fastest **overview glance** — single-page dashboard with zero dependencies. The status board.

---

## 3. ROLE-BASED ACCESS CONTROL (RBAC)

### 3.1 Current Model (Day1)

TSAR currently operates as a **single-operator system** (solo trader). The access model is:

```
┌─────────────────────────────────────────────────┐
│                  OPERATOR (Owner)                │
│  - Full access to all channels                  │
│  - Sole authority for trade approval             │
│  - Mandate commit/revoke                         │
│  - Kill switch activation                        │
└─────────────────────────────────────────────────┘
```

### 3.2 Authentication Per Channel

| Channel | Mechanism | Scope | Rotation |
|---------|-----------|-------|----------|
| **API** | `TSAR_API_KEY` env var → Bearer token | All endpoints except `/health` | Manual env update |
| **Telegram** | Bot token (server-side) + Chat ID whitelist | All commands + inline buttons | Bot token via BotFather |
| **Mobile** | Bearer token stored in Flutter `SharedPreferences` | Same as API (proxies through API) | Via Settings screen |
| **Web** | Bearer token in `localStorage` | Same as API (proxies through API) | Re-prompt on 401 |

### 3.3 Multi-Operator Expansion Path (Level 3+)

When TSAR moves beyond solo operation, implement:

```yaml
roles:
  viewer:
    permissions: [read:all]
    channels: [api, web, mobile]
    
  trader:
    permissions: [read:all, approve:trades, modify:trades]
    channels: [telegram, api, mobile]
    
  risk_officer:
    permissions: [read:all, kill_switch, mandate:revoke, risk:override]
    channels: [telegram, api, mobile, web]
    
  admin:
    permissions: [all]
    channels: [all]
```

**Implementation**: JWT tokens with `role` claim, verified per-request in `require_api_key()` dependency.

### 3.4 Channel-Specific Authorization

| Action | Telegram Requirement | API Requirement | Mobile Requirement |
|--------|---------------------|-----------------|-------------------|
| Read portfolio | Chat ID in whitelist | Valid API key | Valid API key |
| Approve trade | Chat ID + inline callback | N/A | N/A |
| Kill switch | Chat ID in whitelist | Valid API key | Valid API key |
| Mandate commit | N/A (not exposed) | Valid API key | Valid API key |
| Backtest | N/A | Valid API key | N/A |

**Recommendation**: Expose mandate and backtest commands on Telegram (Phase 2) to achieve full channel parity for critical operations.

---

## 4. CROSS-CHANNEL STATE SYNCHRONIZATION

### 4.1 Architecture

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Telegram │   │ REST API │   │  Mobile  │   │   Web    │
│   Bot    │   │ (FastAPI)│   │  (Flutter)│   │  (HTML)  │
└────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │              │
     │  ┌───────────┴──────────────┴──────────────┘
     │  │
     ▼  ▼
┌─────────────────────────────────────────────────┐
│              TSAR CORE (Python)                  │
│  ┌─────────────┐  ┌─────────────┐              │
│  │ TradeMemory │  │  KillSwitch │              │
│  │  (SQLite)   │  │ (File+Redis)│              │
│  └──────┬──────┘  └──────┬──────┘              │
│         │                │                      │
│  ┌──────┴────────────────┴──────┐              │
│  │        Event Bus             │              │
│  │   (Redis Streams / In-Mem)  │              │
│  └─────────────────────────────┘              │
└─────────────────────────────────────────────────┘
```

### 4.2 State Consistency Model

**Read path**: All channels read directly from the same data sources:
- `tsar.db` (SQLite) — trade history, positions, strategies, knowledge
- Kill switch file (`./data/kill_switch`) — authoritative halt state
- Redis (optional) — cached state, event streams

**Write path**: Writes go through the Python core:
- Trade approvals: Telegram → CloudEvent → ExecutionSniper
- Kill switch: Any channel → `KillSwitch.activate()` → file + Redis
- Mandate changes: API/Mobile → `Mandate.commit()/revoke()`

### 4.3 Event Bus Integration

The `EventBus` (`src/comms/event_bus.py`) is the synchronization backbone:

| Event Type | Producers | Consumers | Cross-Channel Effect |
|------------|-----------|-----------|---------------------|
| `tsar.signal.detected.v1` | SignalScout | RiskGuardian | Telegram: trade proposal |
| `tsar.signal.approved.v1` | Telegram bot | ExecutionSniper | All: position appears |
| `tsar.risk.kill_switch.v1` | Any channel | All agents | All: status changes to HALTED |
| `tsar.trade.closed.v1` | ExecutionTracker | Telegram bot, TradePhilosopher | Telegram: post-trade report |
| `tsar.regime.changed.v1` | RegimeDetector | Telegram bot | Telegram: regime alert |
| `tsar.flywheel.cycle_complete.v1` | FlywheelOrchestrator | Telegram bot | Telegram: flywheel notification |

### 4.4 Cache Invalidation Strategy

| Data | TTL | Invalidation Trigger |
|------|-----|---------------------|
| Trade stats | 0 (no cache) | Always fresh from SQLite |
| Risk state | 0 (no cache) | Always fresh from file/Redis |
| Kill switch | 0 (no cache) | File read on every check |
| Factor registry | Module load | Process restart |
| Regime state | 60s | Regime change event |

**Decision**: No application-level caching for financial state. SQLite reads are fast enough (< 1ms for indexed queries). Consistency > performance for trading systems.

---

## 5. PUSH NOTIFICATION ARCHITECTURE

### 5.1 Current State

Only **Telegram** supports push notifications. The bot proactively sends:

| Notification | Trigger | Priority | Format |
|-------------|---------|----------|--------|
| Trade proposal | Signal detected + risk approved | HIGH | Inline keyboard with approve/reject |
| Trade report | Trade closed | MEDIUM | Rich HTML with P&L, lesson, flywheel |
| Risk alert | Risk level change (GREEN→YELLOW→ORANGE→RED) | CRITICAL | Severity-colored message |
| Regime change | RegimeDetector transition | MEDIUM | Regime emoji + confidence |
| Flywheel cycle | Cycle complete | LOW | Stats summary |
| Kill switch | Activation from any source | CRITICAL | 🛑 Alert with reason |

### 5.2 Mobile Push Notifications (Phase 2)

**Architecture**: Firebase Cloud Messaging (FCM) for Android, APNs for iOS.

```
TSAR Event Bus
    │
    ├── tsar.trade.closed.v1 ──→ Push Service ──→ FCM/APNs ──→ Mobile
    ├── tsar.risk.alert.v1 ────→ Push Service ──→ FCM/APNs ──→ Mobile
    ├── tsar.regime.changed.v1 → Push Service ──→ FCM/APNs ──→ Mobile
    └── tsar.kill_switch.v1 ──→ Push Service ──→ FCM/APNs ──→ Mobile
```

**Implementation Requirements**:
1. FCM token registration on mobile app launch
2. Token stored in `tsar.db` table: `device_tokens(user_id, platform, token, created_at)`
3. Push service subscribes to event bus, maps events to notification payloads
4. Priority mapping: CRITICAL → high priority + sound, LOW → silent background

### 5.3 Web Push Notifications (Phase 3)

**Architecture**: Web Push API (W3C standard) with VAPID keys.

```
Browser registers Service Worker
    → Subscribes to Push Manager
    → Sends subscription to TSAR API
    → Stored in tsar.db

Event Bus → Push Service → Web Push Protocol → Service Worker → Notification
```

### 5.4 Notification Preferences (Future)

```yaml
notification_preferences:
  trade_proposals:
    telegram: true
    mobile_push: true
    web_push: false
    email: false
  risk_alerts:
    telegram: true
    mobile_push: true
    web_push: true
    email: true  # Critical safety
  regime_changes:
    telegram: true
    mobile_push: false
    web_push: false
  flywheel_cycles:
    telegram: true
    mobile_push: false
    web_push: false
```

---

## 6. SECURITY MODEL

### 6.1 Threat Model

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Stolen API key | Full system control | Key rotation, per-channel scoping, rate limiting |
| Telegram chat ID spoofing | Trade approval from unauthorized user | Chat ID whitelist (`TELEGRAM_ALLOWED_CHAT_IDS`) |
| Man-in-the-middle (API) | Credential theft | TLS required for production, HSTS headers |
| Brute force API key | Unauthorized access | Rate limiting, fail2ban, account lockout |
| Kill switch tampering | Trading continues when it should halt | File-based primary (survives Redis), fail-safe defaults to HALTED |
| Replay attack | Re-executing approved trades | Proposal ID + TTL expiry, idempotent execution |

### 6.2 Current Security Controls

| Control | Implementation | Status |
|---------|---------------|--------|
| API authentication | Bearer token (`TSAR_API_KEY`) | ✅ Implemented |
| Telegram auth | Chat ID whitelist | ✅ Implemented |
| Health endpoint exemption | `_is_health_path()` bypass | ✅ Implemented |
| CORS | `TSAR_CORS_ORIGINS` env whitelist | ✅ Implemented |
| Rate limiting | ❌ Not implemented | 🔴 GAP |
| TLS | Reverse proxy (nginx/caddy) | ⚠️ External dependency |
| Audit logging | Kill switch immutable log | ⚠️ Partial |
| Input validation | FastAPI Pydantic models | ✅ Implemented |

### 6.3 Security Gaps & Recommendations

#### GAP-1: No Rate Limiting
**Risk**: API key brute force, DoS.
**Fix**: Add `slowapi` or Redis-based rate limiter:
```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)
@app.get("/api/v1/trades")
@limiter.limit("60/minute")
async def get_trades(...): ...
```

#### GAP-2: No API Key Rotation Mechanism
**Risk**: Compromised key requires full restart.
**Fix**: Support multiple valid keys via env: `TSAR_API_KEY=current,previous`. Rotate without downtime.

#### GAP-3: No Audit Trail for Read Operations
**Risk**: Cannot detect reconnaissance.
**Fix**: Log all authenticated requests with timestamp, channel, endpoint, IP.

#### GAP-4: Telegram Bot Token Exposure
**Risk**: Bot token in env allows full bot control.
**Fix**: Store in encrypted secrets manager. Rotate via BotFather if compromised.

#### GAP-5: Mobile App Stores API Key in Plaintext
**Risk**: Rooted device exposes key.
**Fix**: Use Flutter `flutter_secure_storage` (Keychain/Keystore backed).

### 6.4 Security Hardening Roadmap

| Phase | Action | Priority |
|-------|--------|----------|
| Phase 1 (Day1) | Rate limiting on all endpoints | HIGH |
| Phase 1 | API key rotation support | HIGH |
| Phase 1 | Secure storage in mobile app | HIGH |
| Phase 2 | JWT tokens with expiry + refresh | MEDIUM |
| Phase 2 | Request audit logging | MEDIUM |
| Phase 3 | mTLS for API-to-API communication | LOW |
| Phase 3 | OAuth2 for third-party integrations | LOW |

---

## 7. OFFLINE CAPABILITY

### 7.1 Current State: No Offline Support

All channels require live connectivity to the TSAR API server. There is no:
- Client-side data caching
- Offline queue for actions
- Local state persistence (beyond mobile settings)

### 7.2 Offline Strategy by Channel

#### Telegram (No offline needed)
Telegram is inherently online. Messages queue at the Telegram server level. If TSAR bot is down, messages are lost (no persistent queue). **Mitigation**: Bot health monitoring + auto-restart via systemd.

#### API (No offline needed)
API consumers are expected to be server-to-server. Offline is not a relevant concern. **Mitigation**: Retry logic in client libraries, idempotent endpoints.

#### Mobile App (Offline-capable design)

**Architecture**: Offline-first with sync-when-connected.

```
┌─────────────────────────────────────────┐
│            Mobile App (Flutter)          │
│                                          │
│  ┌──────────────┐  ┌──────────────────┐ │
│  │  SQLite Cache │  │  Action Queue    │ │
│  │  (read-only)  │  │  (write ops)     │ │
│  └──────┬───────┘  └────────┬─────────┘ │
│         │                   │            │
│  ┌──────┴───────────────────┴─────────┐ │
│  │         Sync Manager               │ │
│  │  - Pull: fetch delta since last_ts │ │
│  │  - Push: flush action queue        │ │
│  │  - Conflict: server wins           │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

**Cached Data**:
| Data | Cache Strategy | Max Staleness |
|------|---------------|---------------|
| Trade history | Incremental sync | 5 minutes |
| Open positions | Full refresh on connect | 0 (always fresh when online) |
| Risk state | Full refresh | 0 |
| Kill switch | Poll file/local flag | 0 |
| P&L stats | Computed from cached trades | Derived |
| Strategies | Full refresh | 1 hour |

**Offline Actions**:
| Action | Offline Behavior |
|--------|-----------------|
| View trades | ✅ From cache |
| View positions | ✅ From cache (may be stale) |
| Kill switch | ✅ Local flag + queue activation for server sync |
| Approve trade | ❌ Requires online (trade proposals expire in 300s) |
| Settings change | ✅ Local + sync |

#### Web Dashboard (Minimal offline)
The web dashboard is a single-page HTML file. For offline:
- **Service Worker** caches the static shell
- **IndexedDB** stores last-known state
- **Background Sync** queues kill switch activation

**Priority**: LOW. Web dashboard is a convenience view; mobile is the emergency interface.

### 7.3 Kill Switch Offline Guarantee

The kill switch must work even when all network connectivity is lost:

1. **Mobile**: Local kill switch flag stored in `SharedPreferences`. On reconnect, sends `POST /api/v1/kill-switch` to server. UI immediately reflects HALTED state locally.
2. **Telegram**: No offline capability. If Telegram is unreachable, user must use mobile app or direct API.
3. **API**: Direct file write: `echo '{"active":true,"reason":"manual"}' > ./data/kill_switch` — the KillSwitch file is the primary store.
4. **Web**: Service Worker caches kill switch button. Activation queues via Background Sync API.

---

## 8. USER JOURNEY MAPS

### 8.1 Journey: Morning Routine (Monitoring)

```
User wakes up
    │
    ├── Opens Telegram → /status
    │   Response: System active, 3 open positions, P&L +$12.50
    │
    ├── Checks /risk
    │   Response: GREEN, drawdown 0.8%, kill switch inactive
    │
    ├── Checks /regime
    │   Response: RANGING, confidence 72%
    │
    └── Satisfied, goes about day
```

### 8.2 Journey: Trade Approval (Interactive)

```
Signal detected by SignalScout
    │
    ├── RiskGuardian approves
    │
    ├── Telegram bot sends trade proposal:
    │   🤖 TSAR wants to open a trade:
    │   🟢 BTC/USDT LONG
    │   💰 Entry: $67,450
    │   🎯 Target: $68,800 (+2.0%)
    │   🛑 Stop: $66,800 (-1.0%)
    │   📊 R:R = 1:2.0
    │
    │   [✅ Approve] [❌ Reject] [📝 Modify] [💬 Discuss]
    │
    ├── User taps [💬 Discuss]
    │   Bot provides deeper analysis: regime context, similar trades,
    │   score breakdown, active patterns
    │
    ├── User taps [✅ Approve]
    │   Bot: "Trade APPROVED — executing via TSAR pipeline..."
    │   ExecutionSniper places order
    │
    └── Trade closes → Bot sends detailed report:
        ✅ Trade CLOSED — BTC/USDT LONG
        💰 Result: +$27.50 (+0.4%)
        ⏱️ Duration: 2h 15m
        📝 Lesson: "Volume confirmed breakout, RSI divergence was false"
        🔄 Flywheel: Strategy genome updated
```

### 8.3 Journey: Emergency Kill Switch

```
User receives risk alert on Telegram: 🔴 RISK [HIGH] Drawdown at 4.2%
    │
    ├── Option A: Telegram
    │   User sends /stop
    │   Bot: 🛑 KILL SWITCH ACTIVATED
    │
    ├── Option B: Mobile App
    │   User opens app → taps red FAB button
    │   App: "Kill switch activated"
    │   (Works even if API is unreachable — local flag)
    │
    ├── Option C: Direct API
    │   curl -X POST https://tsar/api/v1/kill-switch -H "Authorization: Bearer KEY"
    │
    └── Option D: File override (last resort)
        echo '{"active":true,"reason":"emergency"}' > ./data/kill_switch
        KillSwitch reads file → activates → cancels all orders → closes all positions
```

### 8.4 Journey: Performance Review

```
User wants weekly review
    │
    ├── Mobile app → Settings → Strategies sheet
    │   Views: strategy performance, fitness scores, recent mutations
    │
    ├── Telegram → /performance
    │   Detailed breakdown: overall stats, per-strategy, recent lessons,
    │   active patterns, regime performance
    │
    └── Web dashboard → glances at P&L card, positions list
        Quick visual check — no deep analysis needed
```

### 8.5 Journey: Knowledge Exploration

```
User wants to understand a past trade
    │
    ├── Telegram → /discuss trade-abc123
    │   Bot shows: entry/exit, P&L, reasoning, reflection,
    │   similar past trades (vector search)
    │
    ├── Telegram → /why trade-abc123
    │   Bot shows: signal reasoning, indicator values at entry,
    │   score breakdown, patterns detected, regime at entry
    │
    └── API → GET /api/v1/knowledge/search?query=BTC+breakout+volume
        Returns: ranked results from FTS5 across all knowledge stores
```

---

## 9. API GATEWAY DESIGN

### 9.1 Current Architecture

```
Client ──HTTP──→ FastAPI (port 8000)
                    │
                    ├── /health (no auth)
                    ├── /docs (Swagger UI)
                    ├── /api/v1/* (auth required)
                    └── /app (static web dashboard)
```

### 9.2 Endpoint Inventory

#### Health (No Auth)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Full system health with component status |
| GET | `/health/ready` | Simple readiness probe |
| GET | `/api/health` | Alias for `/health` |

#### Dashboard (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | System overview aggregation |

#### Trades (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/trades` | Trade history with filters |
| GET | `/api/v1/trades/stats` | Aggregate trade statistics |
| GET | `/api/v1/strategies` | Strategy performance summaries |

#### Positions (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/positions` | Open positions |

#### P&L (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/pnl` | P&L summary with regime breakdown |

#### Risk (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/risk` | Risk state with level classification |
| POST | `/api/v1/kill-switch` | Activate kill switch |
| POST | `/api/v1/resume` | Deactivate kill switch |

#### Regime (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/regime` | Current regime + performance by regime |

#### Factors (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/factors` | Factor library |
| GET | `/api/v1/factors/compute` | Compute factors for symbol |
| GET | `/api/v1/factors/benchmark` | IC/IR benchmark |

#### Backtest (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/backtest` | Run backtest |

#### Flywheel (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/flywheel` | Flywheel health score |

#### Mandate (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/mandate` | Mandate status |
| POST | `/api/v1/mandate/commit` | Commit mandate (enable live trading) |
| POST | `/api/v1/mandate/revoke` | Revoke mandate (block live trading) |

#### Shadow (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/shadow/rules` | Extracted shadow rules |
| POST | `/api/v1/shadow/extract` | Trigger shadow extraction |

#### Knowledge (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/knowledge/search` | FTS5 search across stores |

#### Patterns & Lessons (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/patterns` | Discovered patterns |
| GET | `/api/v1/lessons` | Trade lessons |

#### Backends (Auth Required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/backends` | Backend registry status |

#### Mobile Aliases (Auth Required)
| Method | Path | Maps To |
|--------|------|---------|
| GET | `/api/dashboard` | `/` |
| GET | `/api/trades` | `/api/v1/trades` |
| GET | `/api/risk` | `/api/v1/risk` |
| GET | `/api/positions` | `/api/v1/positions` |
| GET | `/api/pnl` | `/api/v1/pnl` |
| GET | `/api/mandate` | `/api/v1/mandate` |
| GET | `/api/factors` | `/api/v1/factors` |
| GET | `/api/strategies` | `/api/v1/strategies` |
| GET | `/api/regime` | `/api/v1/regime` |
| GET | `/api/backends` | `/api/v1/backends` |
| GET | `/api/flywheel` | `/api/v1/flywheel` |
| GET | `/api/patterns` | `/api/v1/patterns` |
| GET | `/api/lessons` | `/api/v1/lessons` |

### 9.3 API Versioning Strategy

**Current**: Both `/api/v1/` and `/api/` (alias) paths exist.
**Recommendation**: Maintain `/api/v1/` as canonical. Mobile aliases are convenience shortcuts. Future breaking changes use `/api/v2/`.

### 9.4 Response Envelope Standard

All API responses should follow:
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2026-07-30T17:00:00Z",
    "version": "v1"
  },
  "error": null
}
```

**Current state**: Responses are direct data objects. The envelope pattern is recommended for Phase 2 to enable consistent error handling and metadata across channels.

---

## 10. MOBILE APP ACCESSIBILITY

### 10.1 Architecture

```
┌─────────────────────────────────────────┐
│           Flutter Mobile App             │
│                                          │
│  Screens:                                │
│  ├── DashboardScreen (home)             │
│  ├── TradesScreen                       │
│  ├── FactorsScreen                      │
│  ├── RiskScreen                         │
│  └── SettingsScreen                     │
│                                          │
│  Providers (State Management):           │
│  ├── DashboardProvider                  │
│  ├── TradeProvider                      │
│  ├── RiskProvider                       │
│  ├── PortfolioProvider                  │
│  ├── FactorProvider                     │
│  ├── MandateProvider                    │
│  ├── KnowledgeProvider                  │
│  ├── StrategyProvider                   │
│  └── SettingsProvider                   │
│                                          │
│  Services:                               │
│  └── ApiService (HTTP → REST API)       │
│                                          │
│  Widgets:                                │
│  ├── TsarCard                           │
│  ├── Charts (fl_chart)                  │
│  └── KillSwitchFAB                      │
└─────────────────────────────────────────┘
```

### 10.2 Key Accessibility Features

| Feature | Implementation |
|---------|---------------|
| **Kill switch FAB** | Floating action button, always visible, red, one-tap activation |
| **Auto-refresh** | Configurable interval (10s/30s/1m/5m) via Settings |
| **Pull-to-refresh** | All list screens support swipe-down refresh |
| **Dark mode** | Default-on, trading terminal aesthetic |
| **Offline kill switch** | Local flag in SharedPreferences, syncs on reconnect |
| **Error recovery** | ErrorBanner widget with retry button on all screens |
| **Responsive layout** | Works on phones and tablets |

### 10.3 Missing Mobile Features (Gaps)

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| No push notifications | User must manually check | Phase 2: FCM integration |
| No trade approval | Cannot approve trades from mobile | Phase 2: WebSocket for real-time proposals |
| No charts on trades | Limited visual analysis | Phase 2: Candlestick chart with trade markers |
| No biometric auth | API key in plaintext storage | Phase 2: `flutter_secure_storage` + biometric |
| No widget (iOS/Android) | Must open app for status | Phase 3: Home screen widget |

---

## 11. TELEGRAM BOT DEEP DIVE

### 11.1 Architecture

```
┌──────────────────────────────────────────────────┐
│                TsarBot (Telegram)                 │
│                                                   │
│  Message Flow:                                    │
│  Telegram API ←── Long Polling ──→ poll_loop()   │
│       │                              │            │
│       │                    ┌─────────┴─────────┐ │
│       │                    │   Router           │ │
│       │                    │   ├── /command     │ │
│       │                    │   ├── callback_q   │ │
│       │                    │   └── freeform     │ │
│       │                    └────────────────────┘ │
│       │                                           │
│  Trade Proposal Lifecycle:                        │
│  SignalScout → propose_trade() → send_message()  │
│       │                              │            │
│       │              [✅ Approve] [❌ Reject]    │
│       │              [📝 Modify] [💬 Discuss]    │
│       │                              │            │
│       └── handle_callback_query() ───┘            │
│              │                                    │
│              ├── _handle_approve() → execute      │
│              ├── _handle_reject() → log           │
│              ├── _handle_modify() → prompt        │
│              ├── _handle_discuss() → analyze      │
│              └── _handle_details() → indicators   │
└──────────────────────────────────────────────────┘
```

### 11.2 Command Reference

| Command | Response Time | Data Source |
|---------|--------------|-------------|
| `/start` | < 1s | KillSwitch.deactivate() |
| `/stop` | < 1s | KillSwitch.activate() |
| `/status` | < 2s | TradeMemory + KillSwitch |
| `/pnl` | < 2s | TradeMemory.get_trade_stats() |
| `/positions` | < 2s | TradeMemory.get_open_positions() |
| `/risk` | < 2s | KillSwitch + TradeMemory |
| `/regime` | < 3s | KnowledgeTools + TradeMemory |
| `/flywheel` | < 2s | FlywheelHealth.compute() |
| `/performance` | < 5s | TradeMemory + KnowledgeTools |
| `/strategy` | < 3s | KnowledgeTools |
| `/discuss [id]` | < 5s | KnowledgeTools + vector search |
| `/why [id]` | < 5s | KnowledgeTools |
| `/ask [question]` | < 5s | FTS5 search + context aggregation |

### 11.3 Security Controls

| Control | Implementation |
|---------|---------------|
| Chat ID whitelist | `_is_authorized()` check on every message and callback |
| Extra allowed IDs | `TELEGRAM_ALLOWED_CHAT_IDS` env (comma-separated) |
| Unauthorized logging | Logs chat_id of rejected messages |
| Proposal TTL | 300 seconds, auto-expire with message edit |
| No secrets in messages | Bot never sends API keys, tokens, or internal paths |

### 11.4 Reliability

| Concern | Mitigation |
|---------|-----------|
| Bot crash | systemd restart, or supervisor |
| Telegram API down | Poll loop catches exceptions, sleeps 5s, retries |
| Proposal lost (bot restart) | In-memory state lost; proposals expire. Acceptable for Day1. |
| Duplicate message delivery | Telegram delivers at-least-once; proposal_id deduplicates |
| Rate limiting (Telegram) | 30 messages/second per chat; bot sends sequentially |

---

## 12. WEB DASHBOARD

### 12.1 Architecture

Single HTML file (`src/api/static/index.html`) with:
- Vanilla JavaScript (no framework)
- CSS variables for theming
- `fetch()` API for data
- Auto-refresh via `setInterval`
- `localStorage` for API key persistence

### 12.2 Features

| Feature | Status |
|---------|--------|
| System status (mode, regime, kill switch, uptime) | ✅ |
| Portfolio stats (P&L, win rate, trades today) | ✅ |
| Open positions list | ✅ |
| Kill switch button | ✅ |
| Auto-refresh | ✅ |
| Mobile-responsive layout | ✅ |
| PWA manifest | ❌ |
| Service Worker (offline) | ❌ |
| Charts | ❌ |
| Trade history | ❌ |
| Factor/regime details | ❌ |

### 12.3 Recommendations

1. **Add PWA manifest** for "Add to Home Screen" on mobile browsers
2. **Add Service Worker** for offline shell caching
3. **Add WebSocket** for real-time updates instead of polling
4. **Expand to multi-page** or SPA framework for deeper analysis views

---

## 13. CROSS-CHANNEL COMMAND PARITY

### 13.1 Command Mapping

Every user intent should be achievable from at least two channels:

| Intent | Telegram | API | Mobile | Web |
|--------|----------|-----|--------|-----|
| "Is the system running?" | `/status` | `GET /health` | Dashboard | Status dot |
| "How much money have I made?" | `/pnl` | `GET /api/v1/pnl` | P&L card | P&L card |
| "What positions are open?" | `/positions` | `GET /api/v1/positions` | Positions list | Positions card |
| "Should I be worried?" | `/risk` | `GET /api/v1/risk` | Risk screen | Risk indicator |
| "Stop everything NOW" | `/stop` | `POST /api/v1/kill-switch` | Kill FAB | Red button |
| "Resume trading" | `/start` | `POST /api/v1/resume` | Kill FAB | — (gap) |
| "What regime are we in?" | `/regime` | `GET /api/v1/regime` | Via API | — (gap) |
| "How's the flywheel?" | `/flywheel` | `GET /api/v1/flywheel` | Via API | — (gap) |
| "Should I take this trade?" | [Approve button] | — | — | — |
| "Why was this trade taken?" | `/why [id]` | — | — | — |
| "Run a backtest" | — | `POST /api/v1/backtest` | — | — |
| "Commit the mandate" | — | `POST /api/v1/mandate/commit` | Mandate sheet | — |

### 13.2 Parity Gaps (Priority Order)

| Gap | Priority | Channels Affected |
|-----|----------|-------------------|
| Trade approval only on Telegram | HIGH | Mobile, Web |
| Resume trading missing on Web | HIGH | Web |
| Regime/flywheel not on Web | MEDIUM | Web |
| Backtest not on Telegram/Mobile | MEDIUM | Telegram, Mobile |
| Mandate not on Telegram | MEDIUM | Telegram |
| Knowledge search not on Web | LOW | Web |
| `/discuss` and `/why` API-only | LOW | API, Mobile, Web |

---

## 14. FAILOVER & DEGRADED MODE

### 14.1 Failure Scenarios

| Failure | Impact | Degraded Mode |
|---------|--------|---------------|
| Redis down | Event bus falls back to in-memory; no persistence | System continues, events not persisted |
| SQLite locked | Reads block temporarily | Retry with backoff; WAL mode reduces contention |
| Telegram API down | No trade proposals, no alerts | Mobile/API/Web still functional |
| FastAPI crash | API/Mobile/Web down | Telegram bot continues (separate process); kill switch via file |
| All channels down | No user access | Kill switch file can be written directly; system watchdog activates |
| Exchange API down | No execution | Risk system halts new trades; existing positions managed by exchange-side stops |

### 14.2 Watchdog Architecture

```
┌─────────────────────────────────────────────┐
│             System Watchdog                  │
│                                              │
│  Monitors:                                   │
│  ├── FastAPI process (health endpoint)       │
│  ├── Telegram bot process (heartbeat)        │
│  ├── Redis connectivity                      │
│  ├── Exchange WebSocket                      │
│  └── Kill switch file integrity              │
│                                              │
│  Actions:                                    │
│  ├── Restart crashed services                │
│  ├── Activate kill switch on critical failure│
│  ├── Send alerts via surviving channels      │
│  └── Log to immutable audit trail            │
└─────────────────────────────────────────────┘
```

### 14.3 Channel Failover Priority

When the primary channel fails, users should know which channel to try:

```
Primary: Telegram (richest interaction)
    ↓ (Telegram down)
Fallback 1: Mobile App (kill switch FAB works)
    ↓ (Mobile offline)
Fallback 2: Web Dashboard (browser)
    ↓ (Web down)
Fallback 3: Direct API (curl/Postman)
    ↓ (API down)
Fallback 4: File-based kill switch (echo > kill_switch file)
```

---

## 15. IMPLEMENTATION ROADMAP

### Phase 1: Day1 (Weeks 1-4) — Current State

- [x] Telegram bot with commands and inline buttons
- [x] REST API with all endpoints
- [x] Web dashboard (single HTML)
- [x] Mobile app (Flutter) with 5 screens
- [x] Kill switch (file + Redis dual-write)
- [x] Chat ID whitelist security
- [x] Bearer token auth

### Phase 2: Hardening (Weeks 5-8)

- [ ] Rate limiting on all API endpoints
- [ ] API key rotation support
- [ ] Mobile: `flutter_secure_storage` for API key
- [ ] Mobile: Push notifications (FCM)
- [ ] Web: Service Worker for offline shell
- [ ] Telegram: Expose mandate and backtest commands
- [ ] API: Response envelope standardization
- [ ] Audit logging for all authenticated requests

### Phase 3: Multi-Channel Trade Approval (Weeks 9-12)

- [ ] WebSocket endpoint for real-time trade proposals
- [ ] Mobile: Trade approval screen with approve/reject/modify
- [ ] Web: Trade proposal notification + approval UI
- [ ] Unified notification preferences (per-channel, per-event)
- [ ] Cross-channel proposal sync (proposal seen on Telegram → marked on Mobile)

### Phase 4: Enterprise (Level 3+)

- [ ] JWT with role-based access control
- [ ] Multi-user support with invitation system
- [ ] OAuth2 for third-party API consumers
- [ ] API versioning (`/api/v2/`)
- [ ] WebSocket streaming for all real-time data
- [ ] iOS app (currently Android-focused)
- [ ] Desktop app (Electron or native)

---

## 16. OPEN ISSUES & DECISIONS

### Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | No application-level caching for financial data | Consistency > performance; SQLite is fast enough |
| D2 | Telegram is the primary trade approval channel | Richest interaction model; inline buttons are natural |
| D3 | File is the primary kill switch store | Survives Redis failure; supports external override |
| D4 | Mobile aliases on API (`/api/trades` vs `/api/v1/trades`) | Convenience; both supported |
| D5 | Single API key for all channels (Day1) | Solo operator; simplicity over sophistication |

### Open Issues

| # | Issue | Priority | Owner |
|---|-------|----------|-------|
| O1 | Should trade proposals survive bot restart? | HIGH | Telegram Bot |
| O2 | How to handle concurrent approvals from multiple channels? | MEDIUM | Architecture |
| O3 | Should mobile have a separate auth flow from API? | MEDIUM | Mobile |
| O4 | WebSocket vs SSE for real-time updates? | MEDIUM | API |
| O5 | Should web dashboard expand to SPA or stay minimal? | LOW | Web |
| O6 | How to handle timezone differences across channels? | LOW | All |
| O7 | Should `/ask` responses be cached for repeat questions? | LOW | Telegram |

### Cross-Council Dependencies

| Dependency | Council | Impact |
|------------|---------|--------|
| Event bus types | Chief Architect | Event type names must match across all producers/consumers |
| Risk thresholds | Chief Risk Officer | Risk level classification (GREEN/YELLOW/ORANGE/RED) must be consistent |
| Strategy genome format | Chief Strategist | Strategy display on all channels must parse genome correctly |
| Tool permissions | Tools Architect | Read/analysis/trade tool access must map to channel capabilities |
| Rust/C++ integration | Integration Council | Performance-critical paths (tick processing, execution) must not block channel responsiveness |

---

## APPENDIX A: ENVIRONMENT VARIABLES

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TSAR_API_KEY` | Yes | — | Bearer token for API authentication |
| `TSAR_DB_PATH` | No | `./data/tsar.db` | SQLite database path |
| `TSAR_CORS_ORIGINS` | No | `""` (deny all) | Comma-separated allowed origins |
| `TSAR_KILL_SWITCH_PATH` | No | `./data/kill_switch` | Kill switch file path |
| `TELEGRAM_BOT_TOKEN` | Yes (for bot) | — | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | Yes (for bot) | — | Primary authorized chat ID |
| `TELEGRAM_ALLOWED_CHAT_IDS` | No | — | Additional authorized chat IDs (comma-separated) |

## APPENDIX B: CLOUD EVENTS CROSS-REFERENCE

| Event Type | Source | Consumers | Channel Impact |
|------------|--------|-----------|----------------|
| `tsar.signal.detected.v1` | SignalScout | RiskGuardian | Telegram: trade proposal queued |
| `tsar.signal.approved.v1` | Telegram bot | ExecutionSniper | All: position appears |
| `tsar.signal.rejected.v1` | Telegram bot | TradePhilosopher | Telegram: rejection logged |
| `tsar.risk.kill_switch.v1` | Any channel | All agents, Telegram bot | All: HALTED status |
| `tsar.trade.opened.v1` | ExecutionTracker | Telegram bot | Telegram: position notification |
| `tsar.trade.closed.v1` | ExecutionTracker | Telegram bot, TradePhilosopher | Telegram: trade report |
| `tsar.regime.changed.v1` | RegimeDetector | Telegram bot, StrategyGeneticist | Telegram: regime alert |
| `tsar.flywheel.cycle_complete.v1` | FlywheelOrchestrator | Telegram bot | Telegram: flywheel notification |
| `tsar.mandate.committed.v1` | Mandate | RiskGuardian | All: live trading enabled |
| `tsar.mandate.revoked.v1` | Mandate | RiskGuardian | All: live trading blocked |

---

*End of Accessibility Council Review*
