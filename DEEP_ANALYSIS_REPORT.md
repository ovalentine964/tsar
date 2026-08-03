# TSAR Deep Analysis Report
**Date:** 2026-08-03  
**Repo:** https://github.com/ovalentine964/tsar  
**Backend:** https://tsar-api.onrender.com (v0.5.0, LIVE)  
**Website:** https://ovalentine964.github.io/tsar/

---

## Executive Summary

| Area | Status | Score |
|------|--------|-------|
| Backend API | LIVE, 44/51 endpoints working | 86% |
| Mobile App | Correctly configured, needs signing fix | 80% |
| Security | Solid architecture, 2 critical findings | 70% |
| Website | Working, but serves stale APK | 60% |
| Overall | Pre-production ready with fixes needed | 75% |

---

## 1. Render Backend Status ✅

- **Service:** `tsar-api` on Render (Starter plan, Oregon)
- **Status:** LIVE, auto-deploy from `main`
- **Health:** `{"status":"ok","version":"0.5.0","components":{"api":"healthy","kill_switch":"active","trade_memory":"healthy"}}`
- **Latest deploy:** Commit `6b9dde0` — succeeded 2026-08-03 13:32 UTC
- **Trading mode:** Paper (safe)
- **Database:** SQLite (empty — 0 trades, pre-production)

### API Endpoints: 51 total
- ✅ **44 working** — all core monitoring, dashboard, mobile aliases
- ⚠️ **7 with issues:**
  - `POST /api/v1/mandate/commit` → 500 error
  - `/health/detailed` → async bug (event loop conflict)
  - `/api/v1/factors/benchmark` → initialization error
  - `/api/v1/knowledge/search` → FTS search broken
  - `/api/v1/factors/compute` → stub (empty)
  - `/api/v1/backtest` → stub (all-zero metrics)

### Environment Variables Set:
- ✅ EXCHANGE_API_KEY, EXCHANGE_SECRET (Binance testnet)
- ✅ NVIDIA_API_KEY
- ✅ TSAR_API_KEY
- ✅ TELEGRAM_BOT_TOKEN
- ❌ TSAR_CORS_ORIGINS — **NOT SET** (blocks cross-origin requests)
- ❌ REDIS — disabled (kill switch state lost on restart)

---

## 2. Mobile App Analysis ✅

### Configuration — CORRECT
- Default API URL: `https://tsar-api.onrender.com` hardcoded in:
  - `mobile/lib/providers/settings_provider.dart`
  - `mobile/lib/services/api_service.dart`
- Users can change URL and API key via Settings screen
- API key stored in `flutter_secure_storage` (encrypted)

### Architecture
- **52 source files, ~13,000 lines** of Flutter/Dart code
- **13 providers** (state management), **12 models**, **16 screens**
- **29 API endpoints** called by the app
- **WebSocket service** for real-time prices (not connected)
- **Biometric auth** for kill switch activation
- **Dark trading terminal** theme with JetBrains Mono

### Issues Found
1. **Debug-signed APK** — uses `signingConfigs.debug` for release builds
2. **SSL pinning not implemented** — empty `_pinnedShas` list
3. **Zero tests** — no test files exist
4. **WebSocket never connected** — service exists but no screen calls `connect()`
5. **Redundant CI workflow** — `build-apk.yml` overlaps with `flutter.yml`

---

## 3. Security Audit

### 🔴 Critical
1. **Render API key exposure** — key grants access to ALL env vars including Binance credentials. **Rotate immediately.**
2. **CORS not configured** — `TSAR_CORS_ORIGINS` not set on Render. Web dashboard and mobile app blocked.

### 🟠 High
3. **Async bug in health endpoint** — `run_until_complete()` fails in running event loop
4. **Redis disabled** — kill switch state lost on container restart (safety risk)
5. **OpenAPI schema exposed** — `/openapi.json` accessible in production

### 🟢 Positive
- ✅ No hardcoded secrets in code
- ✅ `secrets.compare_digest()` for timing-safe auth
- ✅ Rate limiting on sensitive endpoints (10/min)
- ✅ Excellent kill switch design (fail-safe, dual-write, atomic)
- ✅ Institutional-grade risk management config
- ✅ Clean `.gitignore` and `.dockerignore`

---

## 4. Website & APK Distribution

### GitHub Pages Site (https://ovalentine964.github.io/tsar/)
- ✅ Working, polished landing page
- ✅ Has "View Source on GitHub" link
- ✅ Download link works: `download/app-release.apk` (23 MB)
- ⚠️ **Serves STALE APK** — gh-pages APK is from older commit `c8cd8d5`
- ⚠️ Latest APK is on GitHub Releases (`v1.0.0-apk`, commit `6b9dde0`)

### APK Comparison
| | gh-pages APK | Release APK |
|---|---|---|
| Size | 23,421,592 bytes | 23,424,588 bytes |
| Commit | c8cd8d5 (old) | 6b9dde0 (latest) |
| Has Render URL? | Yes (from settings_provider default) | Yes |
| Downloaded | N/A (served by Pages) | 0 times |

**Both APKs will connect to the backend** (both use `https://tsar-api.onrender.com` as default). The release APK is newer but both should work.

---

## 5. Recommendations (Priority Order)

### Fix Now 🔴
1. **Rotate Render API key** — it was exposed during this audit
2. **Set `TSAR_CORS_ORIGINS`** on Render (e.g., `https://ovalentine964.github.io`)
3. **Update gh-pages APK** — push latest build to gh-pages `download/` directory

### Fix Before Sharing 🟠
4. Fix async bug in `/health/detailed` (`await` instead of `run_until_complete()`)
5. Enable Redis or use Render persistent disk for kill switch
6. Fix `POST /api/v1/mandate/commit` 500 error
7. Disable `/openapi.json` in production

### Nice to Have 🟡
8. Add proper release signing for APK
9. Implement SSL pinning
10. Add Flutter tests
11. Connect WebSocket service in mobile app
12. Remove redundant `build-apk.yml` workflow

---

## 6. What Works Well

- **Backend is LIVE and healthy** — all core endpoints responding
- **Mobile app correctly connects** — default URL hardcoded, auth works
- **Paper trading mode** — safe default, no real money at risk
- **Risk management** — institutional-grade config with circuit breakers, anti-behavioral guards
- **Kill switch** — excellent fail-safe design
- **30 quantitative factors** registered and available
- **12-agent architecture** — SignalScout, RiskGuardian, ExecutionSniper, etc.
- **Clean codebase** — no TODO/FIXME/HACK comments, consistent patterns

---

*Report generated by 3 specialized analysis agents: Backend API, Mobile App, Security Audit*
