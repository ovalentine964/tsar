/// News Timing & Execution Council
/// Institutional-grade news-aware trading execution
///
/// # Architecture
///
/// ```text
/// ┌─────────────────────────────────────────────────────────────┐
/// │                    NEWS TIMING COUNCIL                       │
/// ├─────────────────────────────────────────────────────────────┤
/// │                                                              │
/// │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
/// │  │  Calendar    │  │  Blackout   │  │  Recovery   │         │
/// │  │  Integration │  │  Manager    │  │  Detector   │         │
/// │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
/// │         │                │                 │                 │
/// │         ▼                ▼                 ▼                 │
/// │  ┌─────────────────────────────────────────────────────┐   │
/// │  │              News-Aware Executor                      │   │
/// │  │  ┌─────────┐  ┌──────────┐  ┌───────────┐          │   │
/// │  │  │ Blackout│  │ Recovery │  │Opportunity│          │   │
/// │  │  │ Periods │  │ Detection│  │ Detection │          │   │
/// │  │  └─────────┘  └──────────┘  └───────────┘          │   │
/// │  │                                                      │   │
/// │  │  ┌──────────────────────────────────────────────┐   │   │
/// │  │  │         Risk Management Layer                  │   │   │
/// │  │  │  Position Sizing │ Stop Loss │ Leverage       │   │   │
/// │  │  └──────────────────────────────────────────────┘   │   │
/// │  └─────────────────────────────────────────────────────┘   │
/// │         │                                                   │
/// │         ▼                                                   │
/// │  ┌─────────────────────────────────────────────────────┐   │
/// │  │              Execution Decision                       │   │
/// │  │  Enter / Exit / Reduce / Hold / Flatten / NoAction   │   │
/// │  └─────────────────────────────────────────────────────┘   │
/// └─────────────────────────────────────────────────────────────┘
/// ```
///
/// # News Severity Levels
///
/// | Severity  | Action                          | Example Events              |
/// |-----------|--------------------------------|----------------------------|
/// | Critical  | Flatten all, no new trades     | FOMC, CPI, NFP, Flash Crash |
/// | High      | Reduce 50%, tighten stops      | Token Unlock, ETF Decision  |
/// | Medium    | Reduce 25%, monitor            | Protocol Upgrade, Whale     |
/// | Low       | Normal trading                 | Minor news, Sentiment       |
///
/// # Blackout Periods
///
/// | Event          | Before  | After   | Action                    |
/// |----------------|---------|---------|---------------------------|
/// | FOMC           | 2 hours | 2 hours | No new trades             |
/// | CPI            | 1 hour  | 1 hour  | No new trades             |
/// | NFP            | 30 min  | 1 hour  | No new trades             |
/// | Bitcoin Halving| 24 hours| 72 hours| Increase position         |
/// | Token Unlock   | 24 hours| 24 hours| Flatten all               |
/// | ETF Decision   | 1 hour  | 24 hours| Trade momentum            |
/// | Flash Crash    | 0       | 2 hours | Flatten all               |
/// | Extreme Fear   | 0       | 4 hours | Contrarian buy            |
/// | Extreme Greed  | 0       | 4 hours | Reduce exposure           |
///
/// # Recovery Detection
///
/// After CRITICAL news, the system waits for recovery before resuming:
///
/// 1. **Initial Shock** — Price chaotic, high volatility → DO NOT TRADE
/// 2. **Volatile** — Still moving, elevated vol → Reduce size only
/// 3. **Stabilizing** — Volatility decreasing → Small positions
/// 4. **Recovered** — 50%+ retracement → Resume normal trading
/// 5. **Trend Established** — New direction clear → Trade the trend
///
/// # News-Driven Opportunities
///
/// | Trigger              | Action                    | Urgency   |
/// |---------------------|--------------------------|-----------|
/// | ETF Approval        | Buy BTC immediately       | Immediate |
/// | Extreme Fear (F&G<20)| Contrarian buy           | Short     |
/// | Whale Accumulation  | Follow smart money         | Medium    |
/// | Protocol Upgrade    | Buy before, sell after     | Medium    |
/// | Flash Crash         | Wait for stability, buy    | Immediate |
/// | Liquidation Cascade | Wait for dust, buy recovery| Short     |

pub mod blackout_periods;
pub mod recovery_detection;
pub mod news_opportunities;
pub mod risk_management;
pub mod calendar;
pub mod executor;

pub use blackout_periods::*;
pub use recovery_detection::*;
pub use news_opportunities::*;
pub use risk_management::*;
pub use calendar::*;
pub use executor::*;
