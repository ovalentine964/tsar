# TSAR Mobile — Connection Guide

## App Overview

**TSAR Mobile** is a Flutter trading dashboard that connects to the TSAR backend API. It provides real-time portfolio monitoring, trade management, risk controls, DeFi positions, and more.

---

## 1. Architecture Summary

### Backend URL
- **Default**: `https://tsar-api.onrender.com`
- Configurable in-app via Settings → API Connection → Base URL
- Stored locally via `SharedPreferences`

### Authentication
- **Bearer token** via `Authorization: Bearer <API_KEY>` header
- API key stored in **Flutter Secure Storage** (hardware-backed on Android)
- API key is **optional** — the app works without it if the backend allows unauthenticated access

### Real-Time Data
- **WebSocket** connection at `wss://<base_url>/ws`
- Streams: price ticks, trade fills, risk alerts
- Auto-reconnect with exponential backoff (max 10 attempts)
- Heartbeat ping every 30 seconds

---

## 2. API Endpoints Used by the App

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check / connection test |
| `/` | GET | Dashboard overview |
| `/api/v1/trades` | GET | Trade list (filterable by symbol, status, limit, offset) |
| `/api/v1/trades/{id}` | GET | Trade detail |
| `/api/v1/trades/stats` | GET | Trade statistics |
| `/api/v1/pnl` | GET | P&L summary (optional `days` param) |
| `/api/v1/risk` | GET | Risk state |
| `/api/v1/kill-switch` | POST | Activate kill switch |
| `/api/v1/resume` | POST | Deactivate kill switch |
| `/api/v1/mandate` | GET | Get current mandate |
| `/api/v1/mandate/commit` | POST | Commit a mandate |
| `/api/v1/mandate/revoke` | POST | Revoke a mandate |
| `/api/v1/factors` | GET | Factor data (filterable by category) |
| `/api/v1/factors/{id}` | GET | Factor detail |
| `/api/v1/factors/benchmark` | GET | Factor benchmarks |
| `/api/v1/factors/rank` | GET | Factor rankings |
| `/api/v1/strategies` | GET | Strategy list |
| `/api/v1/strategies/{id}` | GET | Strategy detail |
| `/api/v1/strategies/{id}/activate` | POST | Activate strategy |
| `/api/v1/strategies/{id}/deactivate` | POST | Deactivate strategy |
| `/api/v1/backtest` | POST | Run backtest |
| `/api/v1/shadow/rules` | GET | Shadow account rules |
| `/api/v1/shadow/extract` | POST | Trigger shadow extraction |
| `/api/v1/knowledge/search` | GET | Knowledge base search (FTS5) |
| `/api/v1/patterns` | GET | Trading patterns |
| `/api/v1/lessons` | GET | Trading lessons |
| `/api/v1/regime` | GET | Market regime |
| `/api/v1/backends` | GET | Backend status |
| `/api/v1/flywheel` | GET | Flywheel health |
| `/api/v1/news` | GET | News feed |
| `/api/v1/news/alerts` | GET | News alerts |
| `/api/v1/signals/quality` | GET | Signal quality |
| `/api/v1/signals/evaluate` | POST | Evaluate signal |
| `/api/v1/defi/positions` | GET | DeFi positions |
| `/api/v1/defi/yield` | GET | DeFi yield data |
| `/api/v1/scenarios` | GET | Risk scenarios |
| `/api/v1/blockchain/rules` | GET | On-chain rules |
| `/api/v1/blockchain/audit` | GET | Audit trail |
| `/api/v1/education` | GET | Trade education |
| `/ws` (WebSocket) | WS | Real-time price/fill/alert stream |

---

## 3. Build the APK

### Option A: Build Locally (requires Flutter SDK)

```bash
# Install Flutter on Pop!_OS / Ubuntu
sudo apt update
sudo apt install -y git curl unzip xz-utils
git clone https://github.com/flutter/flutter.git -b stable ~/flutter
export PATH="$HOME/flutter/bin:$PATH"
flutter doctor

# Build
cd /home/work/.openclaw/workspace/tsar/mobile
flutter pub get
flutter build apk --release

# Output: build/app/outputs/flutter-apk/app-release.apk
```

### Option B: Install from Pre-Built APK

No pre-built APK was found in the repository. You need to either:
1. Build locally (Option A)
2. Use CI/CD to build (GitHub Actions, Codemagic, etc.)
3. Transfer a pre-built APK from a colleague who has built it

---

## 4. Install & Connect

### Step 1: Install APK
```bash
# Via ADB (USB debugging enabled on phone)
adb install build/app/outputs/flutter-apk/app-release.apk

# Or transfer APK to phone and open it
# (Enable "Install from unknown sources" if needed)
```

### Step 2: Configure Backend URL
1. Open the TSAR app
2. Navigate to **Settings** (bottom nav)
3. Under **API CONNECTION**, enter the Render backend URL:
   ```
   https://tsar-api.onrender.com
   ```
4. Tap **SAVE & CONNECT**

### Step 3: Enter API Key (if required)
1. In the same **API CONNECTION** section
2. Enter the `TSAR_API_KEY` in the "API Key" field
3. Tap **SAVE & CONNECT**
4. The key is stored securely in Android Keystore

### Step 4: Verify Connection
1. Go back to the **Dashboard** (Command Center)
2. If connected: you'll see live P&L data, market regime, and stats
3. If disconnected: you'll see a "Connection Error" screen with a RETRY button
4. **Green status** = data is loading successfully from the backend

### Step 5: Configure Binance API Keys
- Binance API keys are managed **server-side** (in the backend `.env`), NOT in the mobile app
- The mobile app only stores the TSAR backend URL and TSAR API key
- Configure Binance keys on the backend first:
  ```bash
  # On the Render backend
  BINANCE_API_KEY=your_key
  BINANCE_API_SECRET=your_secret
  BINANCE_TESTNET=true  # Start with testnet!
  ```

### Step 6: Switch to Live Trading
1. On the backend, set `BINANCE_TESTNET=false`
2. In the app: Settings → Mandate → **COMMIT MANDATE** to enable live trading
3. Monitor the Dashboard for real-time trade fills via WebSocket

---

## 5. App Features

| Screen | What It Shows |
|---|---|
| **Dashboard** | P&L hero, stats grid, market regime, flywheel health, kill switch |
| **Trades** | Trade list with filtering, trade detail, trade stats |
| **Portfolio** | Portfolio positions and allocation |
| **Risk** | Risk state, kill switch controls |
| **Factors** | Factor analysis, benchmarks, rankings |
| **Strategies** | Strategy library, backtesting, activate/deactivate |
| **Knowledge** | FTS5 knowledge base search |
| **News** | Real-time news with sentiment |
| **Signal Quality** | Signal evaluation and quality metrics |
| **DeFi** | DeFi positions and yield data |
| **Blockchain** | On-chain rules, audit trail, scenarios |
| **Settings** | API config, appearance, mandates, strategies |

---

## 6. QR Code / Deep Link Support

**Not implemented.** The app does not currently support:
- QR code scanning for configuration
- Deep links / app links for auto-configuration
- `uni_links` or `app_links` packages

To add easy setup, consider implementing a QR code that encodes:
```json
{
  "baseUrl": "https://tsar-api.onrender.com",
  "apiKey": "tsar_key_here"
}
```

---

## 7. Dependencies

| Package | Version | Purpose |
|---|---|---|
| `provider` | ^6.1.1 | State management |
| `http` | ^1.2.0 | HTTP client |
| `flutter_secure_storage` | ^9.0.0 | Secure API key storage |
| `shared_preferences` | ^2.2.2 | Settings persistence |
| `web_socket_channel` | ^2.4.0 | Real-time WebSocket |
| `fl_chart` | ^0.66.0 | Charts (candlestick, etc.) |
| `local_auth` | ^2.1.8 | Biometric auth |
| `google_fonts` | ^6.0.0 | Typography |
| `intl` | ^0.19.0 | Number/date formatting |

---

## 8. Troubleshooting

| Issue | Fix |
|---|---|
| "Connection Error" on Dashboard | Check backend URL in Settings, verify backend is running |
| No data loading | Verify API key is correct, check backend logs |
| WebSocket disconnects | Normal — app auto-reconnects. Check network stability |
| "Install from unknown sources" blocked | Enable in Android Settings → Security |
| APK won't install | Ensure Android 6.0+ (API 23), check `minSdkVersion` in `android/app/build.gradle` |
