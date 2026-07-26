# TSAR Mobile — Trading Super Agent

A Flutter mobile app for the TSAR Trading Super Agent system.

## Screenshots

Dark-themed trading terminal aesthetic with real-time data, kill switch, and full API integration.

## Architecture

```
lib/
├── main.dart              # Entry point with Provider setup
├── app.dart               # MaterialApp, theme, routing, bottom nav
├── theme.dart             # Dark trading theme (green/red P&L)
├── models/
│   ├── trade.dart         # Trade, TradeStats models
│   ├── position.dart      # Position, PnlSummary, PnlPoint
│   ├── risk.dart          # RiskState, CircuitBreaker, RiskAlert
│   ├── mandate.dart       # Mandate, MandateRule
│   ├── factor.dart        # Factor, FactorCategory
│   ├── strategy.dart      # Strategy, BacktestResult
│   └── knowledge.dart     # KnowledgeResult, MarketRegime, FlywheelHealth
├── services/
│   └── api_service.dart   # HTTP client for all 28+ API endpoints
├── providers/
│   ├── dashboard_provider.dart
│   ├── trade_provider.dart
│   ├── portfolio_provider.dart
│   ├── risk_provider.dart
│   ├── mandate_provider.dart
│   ├── factor_provider.dart
│   ├── strategy_provider.dart
│   ├── knowledge_provider.dart
│   └── settings_provider.dart
├── screens/
│   ├── dashboard_screen.dart   # P&L, stats, equity curve, regime, flywheel
│   ├── trades_screen.dart      # Trade history with filters and detail sheet
│   ├── risk_screen.dart        # Risk gauges, positions, circuit breaker
│   ├── factors_screen.dart     # Factor library with tabs and rankings
│   └── settings_screen.dart    # API config, theme, mandates, knowledge
└── widgets/
    ├── cards.dart              # TsarCard, StatTile, PnlBadge, StatusDot, etc.
    ├── charts.dart             # PnlLineChart, RiskGauge, MiniBarChart
    └── kill_switch_fab.dart    # Kill switch FAB with biometric auth
```

## Features

- **Dashboard** — Real-time P&L, win rate, equity curve, market regime, flywheel health
- **Trades** — History with symbol/status filters, infinite scroll, detail sheets
- **Risk & Portfolio** — Risk gauges, circuit breaker, open positions, alerts
- **Factors** — Library browser with category filter, IC/IR rankings, computation details
- **Kill Switch** — Floating action button with biometric confirmation (fingerprint/face)
- **Settings** — API endpoint config, dark mode, auto-refresh interval
- **Knowledge Search** — FTS5 search across all knowledge stores
- **Mandate Management** — View and manage trading mandates
- **Strategy Library** — View strategy genomes and performance metrics

## Setup

### Prerequisites

- Flutter SDK ≥ 3.0
- Dart SDK ≥ 3.0
- TSAR API running at configurable endpoint (default: `http://localhost:8000`)

### Install

```bash
cd tsar/mobile
flutter pub get
```

### Run

```bash
# Android
flutter run

# iOS
flutter run -d ios

# Web
flutter run -d chrome
```

### Configure API

1. Launch the app
2. Go to **Settings** tab
3. Enter your TSAR API base URL
4. Optionally add API key for authentication
5. Tap **SAVE & CONNECT**

## Design

- **Theme:** Dark (#121212) with green (#00C853) for profit, red (#FF1744) for loss
- **Font:** JetBrains Mono for all financial data
- **Navigation:** Bottom nav with 5 tabs (Dashboard, Trades, Risk, Factors, Settings)
- **Kill Switch:** Always-visible FAB with pulsing glow effect
- **Cards:** Dark surface (#1A1A2E) with subtle borders
- **Charts:** FL Chart library for equity curves and P&L visualization

## State Management

Uses **Provider** pattern with one provider per domain:
- Each screen has its own provider managing loading, error, and data state
- All providers share the same `ApiService` singleton
- Pull-to-refresh triggers full data reload
- Auto-refresh via configurable timer on dashboard

## API Integration

The `ApiService` wraps all 28+ TSAR API endpoints:

| Category      | Endpoints                                    |
|---------------|----------------------------------------------|
| Health        | `GET /health`, `GET /api/dashboard`          |
| Trades        | `GET /api/trades`, `GET /api/trades/{id}`    |
| P&L           | `GET /api/pnl/summary`, `GET /api/pnl/daily` |
| Risk          | `GET /api/risk/state`, `POST /api/risk/kill-switch` |
| Mandates      | `GET /api/mandates`, `POST /api/mandates`, `POST /api/mandates/{id}/revoke` |
| Factors       | `GET /api/factors`, `GET /api/factors/{id}`, `GET /api/factors/categories` |
| Strategies    | `GET /api/strategies`, `POST /api/strategies/{id}/backtest` |
| Shadow        | `GET /api/shadow/rules`, `GET /api/shadow/trades` |
| Knowledge     | `GET /api/knowledge/search`, `GET /api/knowledge/stores` |
| Patterns      | `GET /api/patterns`, `GET /api/lessons`      |
| Regime        | `GET /api/regime`                            |
| Flywheel      | `GET /api/flywheel/health`                   |

## Dependencies

| Package | Purpose |
|---------|---------|
| `provider` | State management |
| `http` | API client |
| `fl_chart` | P&L charts and gauges |
| `local_auth` | Biometric kill switch confirmation |
| `flutter_secure_storage` | Secure API key storage |
| `shared_preferences` | Settings persistence |
| `intl` | Date/number formatting |
| `flutter_slidable` | Swipe gestures |
| `shimmer` | Loading skeleton effects |
