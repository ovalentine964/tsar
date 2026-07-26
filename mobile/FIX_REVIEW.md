# TSAR Mobile App — Fix Review

**Date:** 2026-07-27
**Scope:** All P0 critical issues + additional improvements

---

## P0-1: API Paths Fixed ✅

**Problem:** All API endpoints used `/api/` prefix instead of the real `/api/v1/` prefix.

**Changes in `lib/services/api_service.dart`:**

| Old Path | New Path |
|---|---|
| `/api/trades` | `/api/v1/trades` |
| `/api/trades/stats` | `/api/v1/trades/stats` |
| `/api/pnl/summary` | `/api/v1/pnl` |
| `/api/pnl/daily` | `/api/v1/pnl` |
| `/api/risk/state` | `/api/v1/risk` |
| `/api/risk/kill-switch` | `/api/v1/kill-switch` |
| `/api/mandates` | `/api/v1/mandate` |
| `/api/mandates/$id/revoke` | `/api/v1/mandate/revoke` |
| `/api/factors` | `/api/v1/factors` |
| `/api/factors/categories` | `/api/v1/factors` (categories built client-side) |
| `/api/strategies` | `/api/v1/strategies` |
| `/api/strategies/$id/backtest` | `/api/v1/backtest` |
| `/api/shadow/rules` | `/api/v1/shadow/rules` |
| `/api/knowledge/search` | `/api/v1/knowledge/search` (param `q` → `query`) |
| `/api/knowledge/stores` | Removed (endpoint doesn't exist) |
| `/api/patterns` | `/api/v1/patterns` |
| `/api/lessons` | `/api/v1/lessons` |
| `/api/regime` | `/api/v1/regime` |
| `/api/flywheel/health` | `/api/v1/flywheel` |
| `/api/dashboard` | `/` (root dashboard) |

**Additional:** ApiService is now a singleton to ensure consistent state.

---

## P0-2: Settings → ApiService Wiring ✅

**Problem:** Settings changes (base URL, API key) never propagated to ApiService.

**Changes:**
- `SettingsProvider` now takes `ApiService` as constructor parameter
- `_load()` calls `_apiService.configure(baseUrl: _baseUrl, apiKey: _apiKey)` on startup
- `setBaseUrl()` and `setApiKey()` both call `_apiService.configure()` after updating values
- `main.dart` passes the same `ApiService` instance to both `SettingsProvider` and all other providers

---

## P0-3: Font Assets Fixed ✅

**Problem:** `pubspec.yaml` referenced `assets/fonts/JetBrainsMono-*.ttf` files that don't exist.

**Changes:**
- **`pubspec.yaml`:** Removed `fonts:` asset section, added `google_fonts: ^6.0.0` dependency
- **`lib/theme.dart`:** Replaced all `TextStyle(fontFamily: 'JetBrainsMono', ...)` with `GoogleFonts.jetBrainsMono(...)` via a private `_mono()` helper
- **All screens & widgets:** Replaced `fontFamily: 'JetBrainsMono'` with `GoogleFonts.jetBrainsMono().fontFamily`

---

## P0-4: API Key Secure Storage ✅

**Problem:** API key stored in plain text via `SharedPreferences`.

**Changes:**
- **`lib/providers/settings_provider.dart`:**
  - Added `FlutterSecureStorage` for API key storage
  - `_load()` reads API key from `_secureStorage.read(key: 'tsar_api_key')`
  - `setApiKey()` writes to `_secureStorage.write()` or `_secureStorage.delete()`
  - Falls back gracefully if secure storage is unavailable
- `flutter_secure_storage: ^9.0.0` was already in pubspec.yaml

---

## P0-5: Model/Response Shape Mismatches ✅

**Problem:** Model `fromJson()` methods expected fields the API doesn't return.

**Fixes applied to all models with `try-catch` blocks and flexible field mapping:**

### `lib/models/trade.dart`
- `Trade.fromJson`: Added fallback fields (`trade_id` → `id`, `price` → `entry_price`, `qty` → `quantity`, `timestamp`/`created_at` → `opened_at`)
- `TradeStats.fromJson`: `total_trades` falls back to `total`, `wins`/`losses` fall back to `win_count`/`loss_count`
- Added `_toDouble()` helper for safe numeric parsing

### `lib/models/risk.dart`
- `RiskState.fromJson`: Maps API's `level` (e.g., "GREEN") to `circuitBreaker` enum, `drawdown_pct` → `currentDrawdown`, `open_positions` → `currentPositions`
- `_parseBreaker`: Handles "green", "yellow", "red", "halt" in addition to standard names
- `RiskAlert.fromJson`: Falls back to `severity`/`text`/`created_at` fields

### `lib/models/factor.dart`
- `Factor.fromJson`: Maps API's minimal response (name, category, description, universe) with defaults for missing IC/IR/turnover
- `universe` list stored in `metadata`

### `lib/models/strategy.dart`
- `Strategy.fromJson`: Falls back to `name` for `id`, handles missing performance metrics with defaults
- `BacktestResult.fromJson`: Reads from nested `metrics` object if present

### `lib/models/mandate.dart`
- `Mandate.fromJson`: Maps API's `{status, rules_count}` to model with defaults for missing fields
- Added `Pattern` and `Lesson` model classes

### `lib/models/knowledge.dart`
- `KnowledgeResult.fromJson`: Maps `record_id` → `id`, `snippet` → `content`, `score` → `relevance`
- `MarketRegime.fromJson`: Maps `regime` → `currentRegime`
- `FlywheelHealth.fromJson`: Computes `score` from component status strings ("ok" → 1.0), maps `last_cycle` → `checkedAt`

### `lib/models/position.dart`
- `Position.fromJson`: Added fallback fields (`qty` → `quantity`, `avg_entry` → `entry_price`, `price` → `current_price`)
- `PnlSummary.fromJson`: Handles missing `weekly_pnl`, `monthly_pnl`, `equity_curve` with defaults

---

## P0-6: Dead UI Wired to Real Endpoints ✅

### Knowledge Search (Settings → Knowledge Base)
- `KnowledgeSearchSheet` now uses `KnowledgeProvider` to call `/api/v1/knowledge/search`
- Search field triggers real API calls
- Results display store, score, and snippet
- Loading/error/empty states all handled

### Strategies (Settings → Strategies)
- `StrategiesSheet` now uses `StrategyProvider` to call `/api/v1/strategies`
- Displays strategy list with name, description, status
- Tap to view detail (genome, performance metrics)
- Pull-to-refresh via refresh button

### Mandate (Settings → Mandate)
- `MandateSheet` now uses `MandateProvider` to call `/api/v1/mandate`
- Shows mandate status (ACTIVE/DRAFT/REVOKED) with color coding
- Lists rules if available
- Commit/Revoke buttons wired to `/api/v1/mandate/commit` and `/api/v1/mandate/revoke`
- Loading states on commit/revoke buttons

---

## Additional Fixes ✅

### Error States in All Providers
All providers now have:
- `clearError()` method
- `_error` field exposed as `String? get error`
- Error set on caught exceptions, cleared on new requests

### Loading Indicators
- All providers track `_loading` state
- All screens show `CircularProgressIndicator` when loading
- `ErrorBanner` with RETRY button shown on errors

### Pull-to-Refresh
- `DashboardScreen`: ✅ `RefreshIndicator` wraps ListView
- `TradesScreen`: ✅ `RefreshIndicator` wraps ListView
- `RiskScreen`: ✅ `RefreshIndicator` wraps ListView
- `FactorsScreen`: ✅ `RefreshIndicator` on all 3 tabs

### Circuit Breaker Level Type Safety
- `risk_screen.dart`: `_breakerColor()` and `_breakerDescription()` now accept `CircuitBreakerLevel?` instead of `dynamic`

---

## Files Modified

| File | Changes |
|---|---|
| `pubspec.yaml` | Added `google_fonts`, removed font assets |
| `lib/main.dart` | Pass `ApiService` to `SettingsProvider` |
| `lib/app.dart` | No changes needed |
| `lib/theme.dart` | Use `GoogleFonts.jetBrainsMono()` via helper |
| `lib/services/api_service.dart` | All endpoint paths fixed, singleton pattern |
| `lib/providers/settings_provider.dart` | Secure storage, ApiService wiring |
| `lib/providers/dashboard_provider.dart` | Fixed API response parsing |
| `lib/providers/trade_provider.dart` | Added `clearError()`, flexible parsing |
| `lib/providers/risk_provider.dart` | Added `clearError()`, null-safe error handling |
| `lib/providers/portfolio_provider.dart` | Added `clearError()` |
| `lib/providers/factor_provider.dart` | Categories built client-side from factors |
| `lib/providers/strategy_provider.dart` | Added `backtestLoading` state, `clearError()` |
| `lib/providers/mandate_provider.dart` | Rewired to single mandate endpoint, commit/revoke |
| `lib/providers/knowledge_provider.dart` | Removed dead `loadStores`, simplified |
| `lib/models/trade.dart` | try-catch, flexible field mapping, `_toDouble()` |
| `lib/models/risk.dart` | try-catch, maps API's "GREEN" level, `_toDouble()` |
| `lib/models/factor.dart` | try-catch, handles minimal API response |
| `lib/models/strategy.dart` | try-catch, flexible field mapping |
| `lib/models/mandate.dart` | try-catch, maps `{status, rules_count}` shape |
| `lib/models/knowledge.dart` | try-catch, maps `record_id`/`snippet`/`score`, added Pattern/Lesson |
| `lib/models/position.dart` | try-catch, flexible field mapping |
| `lib/screens/dashboard_screen.dart` | Fixed const/GoogleFonts issue |
| `lib/screens/risk_screen.dart` | Typed breaker methods, added risk model import |
| `lib/screens/settings_screen.dart` | Fully wired Mandate/Knowledge/Strategies sheets |
| `lib/screens/trades_screen.dart` | Updated fontFamily references |
| `lib/screens/factors_screen.dart` | Updated fontFamily references |
| `lib/widgets/cards.dart` | Updated fontFamily, fixed const issue |
