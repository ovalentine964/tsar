# STRATEGY LAYER — Complete Specification

**TSAR Trading Super Agent**
**Version:** 1.0.0 | **Date:** 2026-07-24
**Layer Coverage:** 30% → Target 100% specification

---

## Table of Contents

1. [Backtesting Engine](#1-backtesting-engine)
2. [Walk-Forward Validation](#2-walk-forward-validation)
3. [Strategy Portfolio](#3-strategy-portfolio)
4. [Strategy Allocation](#4-strategy-allocation)
5. [Strategy Monitoring](#5-strategy-monitoring)
6. [Strategy Retirement Gates](#6-strategy-retirement-gates)
7. [Strategy Research](#7-strategy-research)
8. [Day1 vs Full Implementation](#8-day1-vs-full-implementation)
9. [Database Schema Extensions](#9-database-schema-extensions)
10. [Integration Points](#10-integration-points)

---

## 1. Backtesting Engine

### 1.1 Purpose

Validate strategies against historical data BEFORE risking capital. No strategy goes live without passing backtesting. This is the single most critical gap in TSAR's current architecture.

### 1.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    BACKTESTING ENGINE                            │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │  Data Loader  │──▶│   Strategy   │──▶│  Performance     │    │
│  │  (OHLCV/tick) │   │   Simulator  │   │  Calculator      │    │
│  └──────────────┘   └──────────────┘   └──────────────────┘    │
│         │                  │                     │              │
│         ▼                  ▼                     ▼              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │  Fee Model   │   │  Slippage    │   │  Report          │    │
│  │  (exchange)   │   │  Model       │   │  Generator       │    │
│  └──────────────┘   └──────────────┘   └──────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Walk-Forward Validation Engine               │   │
│  │    (train → validate → test → deploy pipeline)           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Technology Choice

**Primary: vectorbt (Python)**

| Criterion | vectorbt | backtrader | zipline |
|-----------|----------|------------|---------|
| Speed | ⭐⭐⭐⭐⭐ (vectorized) | ⭐⭐⭐ (event-driven) | ⭐⭐⭐ |
| Python native | ✅ | ✅ | ✅ |
| Walk-forward support | ✅ (custom loops) | ✅ | ❌ |
| Fee modeling | ✅ | ✅ | ✅ |
| Multi-asset | ✅ | ✅ | ⚠️ |
| Maintenance | Active | Slow | Dead |
| Learning curve | Medium | Low | High |
| Integration with pandas | Native | Good | Good |

**Rationale:** vectorbt uses vectorized NumPy operations for backtesting — 100x faster than event-driven frameworks for parameter sweeps. Critical for genetic strategy evolution. Integrates natively with pandas DataFrames from `get_ohlcv`.

### 1.4 Backtest Engine Specification

```python
# engine/backtest_engine.py

import vectorbt as vbt
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""
    # Data
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    start_date: str = "2025-01-01"
    end_date: str = "2026-07-01"
    
    # Execution costs (CRITICAL — most backtests lie about costs)
    fee_pct: float = 0.1           # Binance spot: 0.1% maker/taker
    slippage_pct: float = 0.05     # 0.05% slippage estimate
    initial_cash: float = 1000.0   # Starting capital for backtest
    
    # Strategy parameters (filled by strategy)
    strategy_params: dict = field(default_factory=dict)
    
    # Validation
    walk_forward: bool = False
    train_pct: float = 0.70
    validation_pct: float = 0.15
    test_pct: float = 0.15

@dataclass
class BacktestResult:
    """Standardized backtest output — every strategy produces this format."""
    # Core metrics
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_hours: int
    
    # Trade statistics
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_hold_time_hours: float
    
    # Risk metrics
    calmar_ratio: float
    tail_ratio: float           # 95th percentile gain / 5th percentile loss
    var_95_pct: float           # Daily Value at Risk (95%)
    expected_shortfall_95: float
    
    # Strategy metadata
    strategy_name: str
    strategy_params: dict
    symbol: str
    timeframe: str
    backtest_period: str
    total_bars: int
    
    # Walk-forward results (if applicable)
    wf_train_sharpe: Optional[float] = None
    wf_validation_sharpe: Optional[float] = None
    wf_test_sharpe: Optional[float] = None
    wf_overfitting_ratio: Optional[float] = None  # test_sharpe / train_sharpe
    
    # Raw trades for further analysis
    trades_df: Optional[pd.DataFrame] = None
    
    @property
    def passed(self) -> bool:
        """Did this backtest pass minimum quality thresholds?"""
        return (
            self.sharpe_ratio >= 0.5 and
            self.max_drawdown_pct <= 20.0 and
            self.total_trades >= 30 and
            self.win_rate >= 0.40 and
            self.profit_factor >= 1.1
        )
    
    @property
    def institutional_grade(self) -> bool:
        """Is this strategy institutional quality?"""
        return (
            self.sharpe_ratio >= 1.5 and
            self.max_drawdown_pct <= 10.0 and
            self.total_trades >= 100 and
            self.win_rate >= 0.50 and
            self.profit_factor >= 1.5 and
            self.sortino_ratio >= 2.0
        )


class BacktestEngine:
    """
    Core backtesting engine using vectorbt.
    Handles data loading, strategy simulation, and performance calculation.
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.data = None
        self.results = None
    
    def load_data(self) -> pd.DataFrame:
        """
        Load historical OHLCV data.
        Sources: local SQLite cache → ccxt API fallback.
        """
        # Try local cache first
        cached = self._load_from_cache()
        if cached is not None and len(cached) > 0:
            self.data = cached
            return cached
        
        # Fallback to exchange API
        import ccxt
        exchange = ccxt.binance()
        
        # Fetch in chunks (ccxt limit per request)
        all_candles = []
        since = exchange.parse8601(f"{self.config.start_date}T00:00:00Z")
        end_ts = exchange.parse8601(f"{self.config.end_date}T00:00:00Z")
        
        while since < end_ts:
            candles = exchange.fetch_ohlcv(
                self.config.symbol, 
                self.config.timeframe,
                since=since,
                limit=1000
            )
            if not candles:
                break
            all_candles.extend(candles)
            since = candles[-1][0] + 1
        
        df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Cache locally
        self._save_to_cache(df)
        self.data = df
        return df
    
    def _load_from_cache(self) -> Optional[pd.DataFrame]:
        """Load from local SQLite cache."""
        import sqlite3
        try:
            conn = sqlite3.connect('data/tsar.db')
            query = """
                SELECT timestamp, open, high, low, close, volume 
                FROM market_data 
                WHERE symbol = ? AND timeframe = ? 
                AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """
            df = pd.read_sql_query(
                query, conn,
                params=(self.config.symbol, self.config.timeframe,
                       self.config.start_date, self.config.end_date)
            )
            conn.close()
            if len(df) > 0:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                return df
        except Exception:
            pass
        return None
    
    def _save_to_cache(self, df: pd.DataFrame):
        """Save OHLCV data to local SQLite cache."""
        import sqlite3
        conn = sqlite3.connect('data/tsar.db')
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
        """)
        for idx, row in df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO market_data 
                (symbol, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (self.config.symbol, self.config.timeframe, idx,
                  row['open'], row['high'], row['low'], row['close'], row['volume']))
        conn.commit()
        conn.close()
    
    def run(self, entries: pd.Series, exits: pd.Series) -> BacktestResult:
        """
        Run backtest with pre-computed entry/exit signals.
        
        Args:
            entries: Boolean Series — True where we enter
            exits: Boolean Series — True where we exit
        
        Returns:
            BacktestResult with all metrics
        """
        if self.data is None:
            self.load_data()
        
        pf = vbt.Portfolio.from_signals(
            close=self.data['close'],
            entries=entries,
            exits=exits,
            init_cash=self.config.initial_cash,
            fees=self.config.fee_pct / 100,
            slippage=self.config.slippage_pct / 100,
            freq=self.config.timeframe
        )
        
        # Extract metrics
        stats = pf.stats()
        trades = pf.trades.records_readable
        
        result = BacktestResult(
            total_return_pct=stats['Total Return [%]'],
            sharpe_ratio=stats.get('Sharpe Ratio', 0.0),
            sortino_ratio=self._calc_sortino(pf),
            max_drawdown_pct=stats['Max Drawdown [%]'],
            max_drawdown_duration_hours=self._calc_dd_duration(pf),
            total_trades=stats.get('Total Trades', 0),
            win_rate=self._calc_win_rate(trades),
            profit_factor=self._calc_profit_factor(trades),
            avg_win_pct=self._calc_avg_win(trades),
            avg_loss_pct=self._calc_avg_loss(trades),
            avg_hold_time_hours=self._calc_avg_hold(trades),
            calmar_ratio=self._calc_calmar(pf),
            tail_ratio=self._calc_tail_ratio(pf),
            var_95_pct=self._calc_var(pf, 0.95),
            expected_shortfall_95=self._calc_es(pf, 0.95),
            strategy_name=self.config.strategy_params.get('name', 'unknown'),
            strategy_params=self.config.strategy_params,
            symbol=self.config.symbol,
            timeframe=self.config.timeframe,
            backtest_period=f"{self.config.start_date} to {self.config.end_date}",
            total_bars=len(self.data),
            trades_df=trades
        )
        
        self.results = result
        return result
    
    # ── Metric Calculations ──────────────────────────────────
    
    def _calc_sortino(self, pf) -> float:
        """Sortino ratio — penalizes only downside volatility."""
        returns = pf.daily_returns()
        downside = returns[returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return (returns.mean() * 365) / (downside.std() * np.sqrt(365))
    
    def _calc_dd_duration(self, pf) -> int:
        """Maximum drawdown duration in hours."""
        dd = pf.drawdown()
        if dd.max() == 0:
            return 0
        # Find longest consecutive drawdown period
        in_dd = dd > 0
        groups = (~in_dd).cumsum()
        dd_periods = in_dd.groupby(groups).sum()
        max_periods = dd_periods.max() if len(dd_periods) > 0 else 0
        # Convert periods to hours based on timeframe
        tf_hours = {'1m': 1/60, '5m': 5/60, '15m': 0.25, '1h': 1, '4h': 4, '1d': 24}
        multiplier = tf_hours.get(self.config.timeframe, 1)
        return int(max_periods * multiplier)
    
    def _calc_win_rate(self, trades: pd.DataFrame) -> float:
        if len(trades) == 0:
            return 0.0
        wins = (trades['PnL'] > 0).sum() if 'PnL' in trades.columns else 0
        return wins / len(trades)
    
    def _calc_profit_factor(self, trades: pd.DataFrame) -> float:
        if len(trades) == 0 or 'PnL' not in trades.columns:
            return 0.0
        gross_profit = trades[trades['PnL'] > 0]['PnL'].sum()
        gross_loss = abs(trades[trades['PnL'] < 0]['PnL'].sum())
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        return gross_profit / gross_loss
    
    def _calc_avg_win(self, trades: pd.DataFrame) -> float:
        if len(trades) == 0 or 'PnL' not in trades.columns:
            return 0.0
        wins = trades[trades['PnL'] > 0]
        return wins['Return'].mean() * 100 if len(wins) > 0 and 'Return' in wins.columns else 0.0
    
    def _calc_avg_loss(self, trades: pd.DataFrame) -> float:
        if len(trades) == 0 or 'PnL' not in trades.columns:
            return 0.0
        losses = trades[trades['PnL'] < 0]
        return losses['Return'].mean() * 100 if len(losses) > 0 and 'Return' in losses.columns else 0.0
    
    def _calc_avg_hold(self, trades: pd.DataFrame) -> float:
        if len(trades) == 0:
            return 0.0
        if 'Entry Timestamp' in trades.columns and 'Exit Timestamp' in trades.columns:
            durations = (trades['Exit Timestamp'] - trades['Entry Timestamp']).dt.total_seconds() / 3600
            return durations.mean()
        return 0.0
    
    def _calc_calmar(self, pf) -> float:
        """Calmar ratio = annualized return / max drawdown."""
        total_return = pf.total_return()
        max_dd = pf.max_drawdown()
        if max_dd == 0:
            return 0.0
        # Annualize (rough)
        days = len(self.data) * {'1m': 1/1440, '5m': 1/288, '15m': 1/96, '1h': 1/24, '4h': 1/6, '1d': 1}.get(self.config.timeframe, 1/24)
        annual_return = (1 + total_return) ** (365 / max(days, 1)) - 1
        return annual_return / abs(max_dd)
    
    def _calc_tail_ratio(self, pf) -> float:
        """95th percentile return / 5th percentile return (absolute)."""
        returns = pf.daily_returns()
        if len(returns) < 20:
            return 0.0
        p95 = np.percentile(returns, 95)
        p5 = abs(np.percentile(returns, 5))
        return p95 / p5 if p5 > 0 else 0.0
    
    def _calc_var(self, pf, confidence: float) -> float:
        """Historical Value at Risk."""
        returns = pf.daily_returns()
        if len(returns) < 10:
            return 0.0
        return abs(np.percentile(returns, (1 - confidence) * 100)) * 100
    
    def _calc_es(self, pf, confidence: float) -> float:
        """Expected Shortfall (CVaR) — average loss beyond VaR."""
        returns = pf.daily_returns()
        if len(returns) < 10:
            return 0.0
        var = np.percentile(returns, (1 - confidence) * 100)
        tail = returns[returns <= var]
        return abs(tail.mean()) * 100 if len(tail) > 0 else 0.0
```

### 1.5 Strategy-Specific Backtest Integration

Each strategy implements a `generate_signals` method that produces entry/exit signals for the backtest engine:

```python
# strategies/base_strategy.py

from abc import ABC, abstractmethod
import pandas as pd
from engine.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult

class BaseStrategy(ABC):
    """Base class for all TSAR strategies."""
    
    name: str = "base"
    version: str = "0.0.1"
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """
        Generate entry and exit signals from OHLCV data.
        
        Returns:
            (entries, exits): Boolean Series aligned to data index
        """
        pass
    
    def backtest(self, config: BacktestConfig) -> BacktestResult:
        """Run backtest for this strategy."""
        engine = BacktestEngine(config)
        engine.load_data()
        entries, exits = self.generate_signals(engine.data)
        return engine.run(entries, exits)
```

```python
# strategies/mean_reversion.py

import pandas as pd
import numpy as np
from strategies.base_strategy import BaseStrategy

class MeanReversionStrategy(BaseStrategy):
    """
    Day1 Mean Reversion Strategy.
    RSI oversold/overbought at support/resistance levels.
    """
    
    name = "mean_reversion"
    version = "1.0.0"
    
    def __init__(self, params: dict = None):
        defaults = {
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'sr_lookback': 48,
            'sr_proximity_pct': 0.5,
            'volume_multiplier': 1.2,
            'sl_atr_multiple': 1.5,
            'tp_rr_ratio': 2.0,
        }
        self.params = {**defaults, **(params or {})}
    
    def generate_signals(self, data: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        close = data['close']
        high = data['high']
        low = data['low']
        volume = data['volume']
        
        # Calculate RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(self.params['rsi_period']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.params['rsi_period']).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        # Calculate ATR for stop-loss
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        
        # Find support/resistance levels
        supports = self._find_levels(low, 'support')
        resistances = self._find_levels(high, 'resistance')
        
        # Volume filter
        vol_sma = volume.rolling(20).mean()
        volume_ok = volume > vol_sma * self.params['volume_multiplier']
        
        # ── LONG Entry: RSI oversold + near support + volume ──
        near_support = self._near_level(close, supports, self.params['sr_proximity_pct'])
        long_entry = (rsi < self.params['rsi_oversold']) & near_support & volume_ok
        
        # ── SHORT Entry: RSI overbought + near resistance + volume ──
        near_resistance = self._near_level(close, resistances, self.params['sr_proximity_pct'])
        short_entry = (rsi > self.params['rsi_overbought']) & near_resistance & volume_ok
        
        # Combined entries
        entries = long_entry | short_entry
        
        # Exits: time-based (24 candles for 1H = 24 hours)
        exits = pd.Series(False, index=data.index)
        # The backtest engine handles stop-loss/take-profit via its own logic
        # This is a simplified version; full version uses ATR-based exits
        
        return entries, exits
    
    def _find_levels(self, series: pd.Series, level_type: str) -> pd.DataFrame:
        """Find swing highs/lows as support/resistance levels."""
        lookback = self.params['sr_lookback']
        levels = []
        
        for i in range(2, len(series) - 2):
            window = series.iloc[max(0, i-lookback):i+1]
            
            if level_type == 'support':
                if (series.iloc[i] < series.iloc[i-1] and 
                    series.iloc[i] < series.iloc[i-2] and
                    series.iloc[i] < series.iloc[i+1] and 
                    series.iloc[i] < series.iloc[i+2]):
                    levels.append({'index': series.index[i], 'price': series.iloc[i]})
            else:  # resistance
                if (series.iloc[i] > series.iloc[i-1] and 
                    series.iloc[i] > series.iloc[i-2] and
                    series.iloc[i] > series.iloc[i+1] and 
                    series.iloc[i] > series.iloc[i+2]):
                    levels.append({'index': series.index[i], 'price': series.iloc[i]})
        
        return pd.DataFrame(levels) if levels else pd.DataFrame(columns=['index', 'price'])
    
    def _near_level(self, price: pd.Series, levels: pd.DataFrame, pct: float) -> pd.Series:
        """Check if price is within pct% of any level."""
        result = pd.Series(False, index=price.index)
        if levels.empty:
            return result
        
        for _, level in levels.iterrows():
            distance = abs(price - level['price']) / level['price'] * 100
            result = result | (distance <= pct)
        
        return result
```

### 1.6 Backtest CLI

```python
# cli/backtest_cli.py

"""
CLI for running backtests.

Usage:
    python -m cli.backtest_cli --strategy mean_reversion --symbol BTC/USDT --start 2025-01-01 --end 2026-07-01
    python -m cli.backtest_cli --strategy momentum --walk-forward
"""

import argparse
import json
from engine.backtest_engine import BacktestEngine, BacktestConfig
from strategies.mean_reversion import MeanReversionStrategy
# from strategies.momentum import MomentumStrategy  # Level 2+
# from strategies.breakout import BreakoutStrategy   # Level 2+

STRATEGY_MAP = {
    'mean_reversion': MeanReversionStrategy,
    # 'momentum': MomentumStrategy,
    # 'breakout': BreakoutStrategy,
}

def main():
    parser = argparse.ArgumentParser(description='TSAR Backtest Engine')
    parser.add_argument('--strategy', required=True, choices=STRATEGY_MAP.keys())
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--timeframe', default='1h')
    parser.add_argument('--start', default='2025-01-01')
    parser.add_argument('--end', default='2026-07-01')
    parser.add_argument('--cash', type=float, default=1000.0)
    parser.add_argument('--walk-forward', action='store_true')
    parser.add_argument('--params', type=str, default='{}', help='JSON strategy params')
    parser.add_argument('--output', type=str, help='Output JSON file')
    
    args = parser.parse_args()
    
    config = BacktestConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start_date=args.start,
        end_date=args.end,
        initial_cash=args.cash,
        walk_forward=args.walk_forward,
        strategy_params=json.loads(args.params)
    )
    
    strategy_cls = STRATEGY_MAP[args.strategy]
    strategy = strategy_cls(config.strategy_params)
    
    if args.walk_forward:
        from engine.walk_forward import WalkForwardEngine
        wf = WalkForwardEngine(config)
        result = wf.run(strategy)
    else:
        result = strategy.backtest(config)
    
    # Print report
    print(f"\n{'='*60}")
    print(f"BACKTEST REPORT: {result.strategy_name} v{strategy.version}")
    print(f"{'='*60}")
    print(f"Symbol:          {result.symbol}")
    print(f"Period:          {result.backtest_period}")
    print(f"Bars:            {result.total_bars}")
    print(f"")
    print(f"Total Return:    {result.total_return_pct:+.2f}%")
    print(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print(f"Sortino Ratio:   {result.sortino_ratio:.2f}")
    print(f"Max Drawdown:    {result.max_drawdown_pct:.2f}%")
    print(f"DD Duration:     {result.max_drawdown_duration_hours}h")
    print(f"")
    print(f"Total Trades:    {result.total_trades}")
    print(f"Win Rate:        {result.win_rate:.1%}")
    print(f"Profit Factor:   {result.profit_factor:.2f}")
    print(f"Avg Win:         {result.avg_win_pct:+.2f}%")
    print(f"Avg Loss:        {result.avg_loss_pct:+.2f}%")
    print(f"Avg Hold:        {result.avg_hold_time_hours:.1f}h")
    print(f"")
    print(f"VaR (95%):       {result.var_95_pct:.2f}%")
    print(f"ES (95%):        {result.expected_shortfall_95:.2f}%")
    print(f"Calmar Ratio:    {result.calmar_ratio:.2f}")
    print(f"Tail Ratio:      {result.tail_ratio:.2f}")
    print(f"")
    print(f"PASS/FAIL:       {'✅ PASSED' if result.passed else '❌ FAILED'}")
    print(f"Inst. Grade:     {'✅ YES' if result.institutional_grade else '❌ NO'}")
    print(f"{'='*60}")
    
    if args.output:
        # Serialize without trades_df
        output = {k: v for k, v in result.__dict__.items() if k != 'trades_df'}
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
```

### 1.7 Pass/Fail Criteria

| Metric | Minimum (Paper Trade) | Minimum (Live) | Institutional |
|--------|----------------------|-----------------|---------------|
| Sharpe Ratio | ≥ 0.5 | ≥ 1.0 | ≥ 1.5 |
| Sortino Ratio | ≥ 0.7 | ≥ 1.2 | ≥ 2.0 |
| Max Drawdown | ≤ 20% | ≤ 15% | ≤ 10% |
| Total Trades | ≥ 30 | ≥ 50 | ≥ 100 |
| Win Rate | ≥ 40% | ≥ 45% | ≥ 50% |
| Profit Factor | ≥ 1.1 | ≥ 1.3 | ≥ 1.5 |
| Calmar Ratio | ≥ 0.5 | ≥ 1.0 | ≥ 2.0 |
| WF Overfitting Ratio | ≥ 0.3 | ≥ 0.5 | ≥ 0.7 |

---

## 2. Walk-Forward Validation

### 2.1 Purpose

Walk-forward validation prevents overfitting — the #1 killer of quantitative strategies. A strategy that looks amazing on historical data but fails on new data is worse than no strategy at all.

### 2.2 Process

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    WALK-FORWARD VALIDATION                              │
│                                                                         │
│  Data: [═════════════════════════════════════════════════════════════]  │
│                                                                         │
│  Fold 1: [TRAIN████████████][VAL██████][TEST██████]                     │
│  Fold 2:       [TRAIN████████████][VAL██████][TEST██████]              │
│  Fold 3:             [TRAIN████████████][VAL██████][TEST██████]        │
│  Fold 4:                   [TRAIN████████████][VAL██████][TEST██████]  │
│                                                                         │
│  Each fold:                                                             │
│    1. TRAIN: Optimize strategy parameters on training window            │
│    2. VALIDATE: Check for overfitting on validation window              │
│    3. TEST: Final out-of-sample performance measurement                 │
│                                                                         │
│  Final score = Average of all TEST fold results                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Specification

```python
# engine/walk_forward.py

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from engine.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult
from strategies.base_strategy import BaseStrategy

@dataclass
class WalkForwardFold:
    """Result of a single walk-forward fold."""
    fold_number: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    
    train_result: BacktestResult
    validation_result: BacktestResult
    test_result: BacktestResult
    
    best_params: dict
    overfitting_ratio: float  # test_sharpe / train_sharpe
    
    @property
    def passed(self) -> bool:
        """Did this fold pass validation?"""
        return (
            self.test_result.passed and
            self.overfitting_ratio >= 0.3 and  # Test must retain ≥30% of train performance
            self.validation_result.sharpe_ratio > 0  # Validation must be positive
        )


@dataclass
class WalkForwardResult:
    """Complete walk-forward validation result."""
    strategy_name: str
    total_folds: int
    passed_folds: int
    failed_folds: int
    
    avg_train_sharpe: float
    avg_validation_sharpe: float
    avg_test_sharpe: float
    avg_overfitting_ratio: float
    
    worst_test_sharpe: float
    best_test_sharpe: float
    test_sharpe_std: float  # Stability measure
    
    folds: list[WalkForwardFold]
    
    @property
    def passed(self) -> bool:
        """Did the strategy pass walk-forward validation?"""
        return (
            self.passed_folds >= self.total_folds * 0.6 and  # ≥60% of folds pass
            self.avg_test_sharpe >= 0.5 and                   # Average test Sharpe ≥ 0.5
            self.avg_overfitting_ratio >= 0.4 and             # Avg overfit ratio ≥ 0.4
            self.test_sharpe_std <= self.avg_test_sharpe * 0.8  # Reasonable stability
        )
    
    @property
    def deployment_ready(self) -> bool:
        """Is this strategy ready for live deployment?"""
        return (
            self.passed and
            self.avg_test_sharpe >= 1.0 and
            self.avg_overfitting_ratio >= 0.5 and
            self.passed_folds >= self.total_folds * 0.75
        )


class WalkForwardEngine:
    """
    Walk-forward validation engine.
    Splits data into rolling train/validation/test windows,
    optimizes on train, validates on validation, tests on test.
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.n_folds = 5  # Default 5 folds
        self.train_pct = config.train_pct
        self.val_pct = config.validation_pct
        self.test_pct = config.test_pct
    
    def run(self, strategy: BaseStrategy, optimize: bool = False) -> WalkForwardResult:
        """
        Run walk-forward validation.
        
        Args:
            strategy: Strategy to validate
            optimize: If True, optimize parameters on each training fold
                      If False, use strategy's default parameters
        """
        engine = BacktestEngine(self.config)
        data = engine.load_data()
        
        total_bars = len(data)
        fold_size = total_bars // self.n_folds
        
        folds = []
        
        for i in range(self.n_folds):
            # Calculate fold boundaries
            fold_start = i * fold_size
            fold_end = min((i + 1) * fold_size, total_bars)
            
            # Split into train/validation/test
            train_end = fold_start + int((fold_end - fold_start) * self.train_pct)
            val_end = train_end + int((fold_end - fold_start) * self.val_pct)
            
            train_data = data.iloc[fold_start:train_end]
            val_data = data.iloc[train_end:val_end]
            test_data = data.iloc[val_end:fold_end]
            
            if len(train_data) < 100 or len(val_data) < 20 or len(test_data) < 20:
                continue  # Skip folds with insufficient data
            
            # Optimize on training data (if enabled)
            best_params = strategy.params.copy()
            if optimize:
                best_params = self._optimize_params(strategy, train_data)
                strategy.params = best_params
            
            # Run backtests on each split
            train_result = self._run_fold(strategy, train_data)
            val_result = self._run_fold(strategy, val_data)
            test_result = self._run_fold(strategy, test_data)
            
            # Calculate overfitting ratio
            overfit_ratio = (
                test_result.sharpe_ratio / train_result.sharpe_ratio
                if train_result.sharpe_ratio > 0 else 0.0
            )
            
            fold = WalkForwardFold(
                fold_number=i + 1,
                train_start=str(train_data.index[0]),
                train_end=str(train_data.index[-1]),
                validation_start=str(val_data.index[0]),
                validation_end=str(val_data.index[-1]),
                test_start=str(test_data.index[0]),
                test_end=str(test_data.index[-1]),
                train_result=train_result,
                validation_result=val_result,
                test_result=test_result,
                best_params=best_params,
                overfitting_ratio=overfit_ratio
            )
            folds.append(fold)
        
        # Aggregate results
        passed_folds = sum(1 for f in folds if f.passed)
        
        result = WalkForwardResult(
            strategy_name=strategy.name,
            total_folds=len(folds),
            passed_folds=passed_folds,
            failed_folds=len(folds) - passed_folds,
            avg_train_sharpe=np.mean([f.train_result.sharpe_ratio for f in folds]),
            avg_validation_sharpe=np.mean([f.validation_result.sharpe_ratio for f in folds]),
            avg_test_sharpe=np.mean([f.test_result.sharpe_ratio for f in folds]),
            avg_overfitting_ratio=np.mean([f.overfitting_ratio for f in folds]),
            worst_test_sharpe=min([f.test_result.sharpe_ratio for f in folds]),
            best_test_sharpe=max([f.test_result.sharpe_ratio for f in folds]),
            test_sharpe_std=np.std([f.test_result.sharpe_ratio for f in folds]),
            folds=folds
        )
        
        return result
    
    def _run_fold(self, strategy: BaseStrategy, data: pd.DataFrame) -> BacktestResult:
        """Run backtest on a single data fold."""
        # Create temporary config for this fold
        fold_config = BacktestConfig(
            symbol=self.config.symbol,
            timeframe=self.config.timeframe,
            start_date=str(data.index[0]),
            end_date=str(data.index[-1]),
            initial_cash=self.config.initial_cash,
            fee_pct=self.config.fee_pct,
            slippage_pct=self.config.slippage_pct,
            strategy_params=strategy.params
        )
        
        fold_engine = BacktestEngine(fold_config)
        fold_engine.data = data  # Use pre-loaded data
        
        entries, exits = strategy.generate_signals(data)
        return fold_engine.run(entries, exits)
    
    def _optimize_params(self, strategy: BaseStrategy, train_data: pd.DataFrame) -> dict:
        """
        Grid search optimization on training data.
        Override in subclasses for Bayesian optimization.
        """
        best_sharpe = -np.inf
        best_params = strategy.params.copy()
        
        # Define parameter search space (strategy-specific)
        param_grid = strategy.get_optimization_grid()
        
        import itertools
        keys = param_grid.keys()
        for values in itertools.product(*param_grid.values()):
            params = dict(zip(keys, values))
            strategy.params = {**strategy.params, **params}
            
            result = self._run_fold(strategy, train_data)
            
            if result.sharpe_ratio > best_sharpe:
                best_sharpe = result.sharpe_ratio
                best_params = strategy.params.copy()
        
        return best_params
```

### 2.4 Walk-Forward Pass/Fail Criteria

| Metric | Pass | Fail | Notes |
|--------|------|------|-------|
| Folds passed | ≥ 60% | < 60% | Majority of folds must pass |
| Avg test Sharpe | ≥ 0.5 | < 0.3 | Out-of-sample must be positive |
| Overfitting ratio | ≥ 0.4 | < 0.2 | Test/train performance retention |
| Test Sharpe stability | σ < 0.8×mean | σ > 1.5×mean | Results shouldn't vary wildly |
| Worst fold Sharpe | > -0.5 | < -1.0 | No catastrophic failures |

### 2.5 Overfitting Detection

```python
def detect_overfitting(result: WalkForwardResult) -> dict:
    """
    Analyze walk-forward results for overfitting signals.
    Returns dict of warnings.
    """
    warnings = {}
    
    # Signal 1: Train >> Test performance
    if result.avg_train_sharpe > result.avg_test_sharpe * 3:
        warnings['train_test_gap'] = {
            'severity': 'HIGH',
            'message': f'Train Sharpe ({result.avg_train_sharpe:.2f}) >> Test Sharpe ({result.avg_test_sharpe:.2f}). '
                      f'Strategy is likely overfit.'
        }
    
    # Signal 2: High variance across folds
    if result.test_sharpe_std > result.avg_test_sharpe:
        warnings['high_variance'] = {
            'severity': 'MEDIUM',
            'message': f'Test Sharpe std ({result.test_sharpe_std:.2f}) > mean ({result.avg_test_sharpe:.2f}). '
                      f'Strategy performance is unstable.'
        }
    
    # Signal 3: Negative test folds
    negative_folds = sum(1 for f in result.folds if f.test_result.sharpe_ratio < 0)
    if negative_folds > len(result.folds) * 0.3:
        warnings['negative_folds'] = {
            'severity': 'HIGH',
            'message': f'{negative_folds}/{len(result.folds)} test folds had negative Sharpe. '
                      f'Strategy may not have a real edge.'
        }
    
    # Signal 4: Validation-test divergence
    val_test_gap = abs(result.avg_validation_sharpe - result.avg_test_sharpe)
    if val_test_gap > 1.0:
        warnings['val_test_divergence'] = {
            'severity': 'MEDIUM',
            'message': f'Validation Sharpe ({result.avg_validation_sharpe:.2f}) diverges from '
                      f'Test Sharpe ({result.avg_test_sharpe:.2f}). Regime shift or data snooping.'
        }
    
    return warnings
```

---

## 3. Strategy Portfolio

### 3.1 Purpose

Run multiple uncorrelated strategies simultaneously. If one strategy loses in a regime, another profits. The goal is smooth equity curves and consistent returns across market conditions.

### 3.2 Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY PORTFOLIO MANAGER                           │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │ Mean         │  │ Momentum     │  │ Breakout     │                  │
│  │ Reversion    │  │ Following    │  │ (Level 2+)   │                  │
│  │ (Day1)       │  │ (Level 2+)   │  │              │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                  │
│         │                 │                  │                          │
│         ▼                 ▼                  ▼                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │              STRATEGY ALLOCATOR                               │      │
│  │    (Kelly / Risk Parity / Equal Weight)                      │      │
│  └──────────────────────────┬───────────────────────────────────┘      │
│                             │                                          │
│                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │              COMPOSITE SIGNAL AGGREGATOR                     │      │
│  │    (Weight signals by allocation, resolve conflicts)         │      │
│  └──────────────────────────┬───────────────────────────────────┘      │
│                             │                                          │
│                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │              RISK GUARDIAN                                    │      │
│  │    (Portfolio-level risk checks)                             │      │
│  └──────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Strategy Registry

```python
# portfolio/strategy_registry.py

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum

class StrategyStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    PAPER = "paper"           # Paper trading only
    RETIRED = "retired"
    WARMUP = "warmup"         # Just added, building history

@dataclass
class StrategyEntry:
    """Registered strategy in the portfolio."""
    name: str
    version: str
    strategy_class: type
    status: StrategyStatus
    
    # Allocation
    allocation_pct: float = 0.0       # % of capital allocated
    max_allocation_pct: float = 50.0   # Never allocate more than this
    min_allocation_pct: float = 5.0    # Minimum viable allocation
    
    # Performance tracking
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    
    # Regime affinity
    preferred_regimes: list[str] = field(default_factory=list)
    blacklisted_regimes: list[str] = field(default_factory=list)
    
    # Correlation with other strategies
    correlation_matrix: dict = field(default_factory=dict)
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    last_signal_at: Optional[datetime] = None
    last_trade_at: Optional[datetime] = None
    warmup_trades_remaining: int = 30  # Trades before activation
    
    # Risk limits (per-strategy)
    max_concurrent_positions: int = 3
    max_daily_loss_pct: float = 2.0
    max_position_size_pct: float = 5.0


class StrategyRegistry:
    """
    Central registry of all strategies.
    Each strategy registers here before it can generate signals.
    """
    
    def __init__(self):
        self._strategies: dict[str, StrategyEntry] = {}
    
    def register(self, entry: StrategyEntry) -> None:
        """Register a new strategy."""
        if entry.name in self._strategies:
            raise ValueError(f"Strategy '{entry.name}' already registered")
        self._strategies[entry.name] = entry
    
    def get(self, name: str) -> Optional[StrategyEntry]:
        return self._strategies.get(name)
    
    def get_active(self) -> list[StrategyEntry]:
        """Get all active strategies."""
        return [s for s in self._strategies.values() if s.status == StrategyStatus.ACTIVE]
    
    def get_for_regime(self, regime: str) -> list[StrategyEntry]:
        """Get strategies that are active AND suitable for the current regime."""
        return [
            s for s in self._strategies.values()
            if s.status == StrategyStatus.ACTIVE
            and regime not in s.blacklisted_regimes
            and (not s.preferred_regimes or regime in s.preferred_regimes)
        ]
    
    def update_performance(self, name: str, trade_result: dict) -> None:
        """Update strategy performance after a trade."""
        s = self._strategies.get(name)
        if not s:
            return
        
        s.total_trades += 1
        if trade_result.get('pnl', 0) > 0:
            s.winning_trades += 1
        s.total_pnl += trade_result.get('pnl', 0)
        s.win_rate = s.winning_trades / s.total_trades if s.total_trades > 0 else 0
        s.last_trade_at = datetime.now()
        
        # Warmup countdown
        if s.status == StrategyStatus.WARMUP:
            s.warmup_trades_remaining -= 1
            if s.warmup_trades_remaining <= 0:
                s.status = StrategyStatus.ACTIVE
    
    def all_names(self) -> list[str]:
        return list(self._strategies.keys())
```

### 3.4 Signal Aggregation

When multiple strategies produce signals for the same symbol simultaneously, the Composite Signal Aggregator resolves conflicts:

```python
# portfolio/signal_aggregator.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class CompositeSignal:
    """Aggregated signal from multiple strategies."""
    symbol: str
    direction: str              # 'long' | 'short' | 'neutral'
    confidence: float           # Weighted average confidence
    contributing_strategies: list[dict]  # Which strategies contributed
    conflict_resolution: str    # How conflicts were resolved
    entry_price: float
    stop_loss: float
    take_profit: float
    allocation_pct: float       # How much of portfolio to allocate


class SignalAggregator:
    """
    Aggregates signals from multiple strategies.
    Resolves conflicts using allocation-weighted voting.
    """
    
    def aggregate(self, signals: list[dict], allocations: dict[str, float]) -> Optional[CompositeSignal]:
        """
        Aggregate multiple signals for the same symbol.
        
        Args:
            signals: List of signal dicts from different strategies
            allocations: Strategy name → allocation percentage
        
        Returns:
            CompositeSignal or None if signals cancel out
        """
        if not signals:
            return None
        
        symbol = signals[0]['symbol']
        
        # Group by direction
        long_signals = [s for s in signals if s['direction'] == 'long']
        short_signals = [s for s in signals if s['direction'] == 'short']
        
        # Weighted vote
        long_weight = sum(
            allocations.get(s['strategy'], 0) * s['confidence'] 
            for s in long_signals
        )
        short_weight = sum(
            allocations.get(s['strategy'], 0) * s['confidence'] 
            for s in short_signals
        )
        
        # Resolution rules
        if long_weight > 0 and short_weight > 0:
            # CONFLICT — strategies disagree
            if abs(long_weight - short_weight) < 0.1:
                # Too close to call — skip
                return None
            elif long_weight > short_weight:
                direction = 'long'
                confidence = (long_weight - short_weight) / long_weight
                resolution = 'long_majority'
            else:
                direction = 'short'
                confidence = (short_weight - long_weight) / short_weight
                resolution = 'short_majority'
        elif long_weight > 0:
            direction = 'long'
            confidence = long_weight / sum(allocations.get(s['strategy'], 0) for s in long_signals)
            resolution = 'unanimous_long'
        elif short_weight > 0:
            direction = 'short'
            confidence = short_weight / sum(allocations.get(s['strategy'], 0) for s in short_signals)
            resolution = 'unanimous_short'
        else:
            return None
        
        # Use weighted average for entry/SL/TP
        contributing = long_signals if direction == 'long' else short_signals
        total_alloc = sum(allocations.get(s['strategy'], 0) for s in contributing)
        
        entry_price = sum(
            s['entry_price'] * allocations.get(s['strategy'], 0) / total_alloc
            for s in contributing
        )
        stop_loss = min(s['stop_loss'] for s in contributing) if direction == 'long' else max(s['stop_loss'] for s in contributing)
        take_profit = max(s['take_profit'] for s in contributing) if direction == 'long' else min(s['take_profit'] for s in contributing)
        
        return CompositeSignal(
            symbol=symbol,
            direction=direction,
            confidence=min(confidence, 1.0),
            contributing_strategies=[{'name': s['strategy'], 'weight': allocations.get(s['strategy'], 0)} for s in contributing],
            conflict_resolution=resolution,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            allocation_pct=total_alloc
        )
```

### 3.5 Strategy Correlation Tracking

```python
# portfolio/correlation_tracker.py

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class CorrelationTracker:
    """
    Tracks return correlation between strategies.
    Used by Strategy Allocator for diversification-aware allocation.
    """
    
    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days
        self._returns: dict[str, list[tuple[datetime, float]]] = {}
    
    def record_return(self, strategy_name: str, timestamp: datetime, return_pct: float):
        """Record a strategy return."""
        if strategy_name not in self._returns:
            self._returns[strategy_name] = []
        self._returns[strategy_name].append((timestamp, return_pct))
    
    def get_correlation_matrix(self) -> pd.DataFrame:
        """
        Calculate pairwise correlation between all strategies.
        Returns DataFrame with strategy names as both index and columns.
        """
        # Build returns DataFrame
        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        
        strategy_daily = {}
        for name, returns in self._returns.items():
            recent = [(ts, r) for ts, r in returns if ts >= cutoff]
            if len(recent) < 10:
                continue
            df = pd.DataFrame(recent, columns=['timestamp', 'return'])
            df['date'] = df['timestamp'].dt.date
            daily = df.groupby('date')['return'].sum()
            strategy_daily[name] = daily
        
        if len(strategy_daily) < 2:
            return pd.DataFrame()
        
        returns_df = pd.DataFrame(strategy_daily)
        returns_df = returns_df.fillna(0)
        
        return returns_df.corr()
    
    def get_pair_correlation(self, strategy_a: str, strategy_b: str) -> float:
        """Get correlation between two specific strategies."""
        matrix = self.get_correlation_matrix()
        if strategy_a in matrix.index and strategy_b in matrix.columns:
            return matrix.loc[strategy_a, strategy_b]
        return 0.0
    
    def is_too_correlated(self, strategy_a: str, strategy_b: str, threshold: float = 0.7) -> bool:
        """Check if two strategies are too correlated to diversify."""
        corr = self.get_pair_correlation(strategy_a, strategy_b)
        return abs(corr) > threshold
```

---

## 4. Strategy Allocation

### 4.1 Purpose

Decide how much capital each strategy gets. Too much to one strategy = concentration risk. Too little = strategy can't generate meaningful returns.

### 4.2 Allocation Methods

#### 4.2.1 Kelly Criterion (Primary)

```python
# portfolio/allocator.py

import numpy as np
from dataclasses import dataclass

@dataclass
class AllocationResult:
    strategy_name: str
    kelly_raw: float           # Full Kelly %
    kelly_half: float          # Half Kelly (conservative)
    kelly_quarter: float       # Quarter Kelly (very conservative)
    allocated_pct: float       # Actual allocation %
    allocated_usd: float       # Dollar amount
    reason: str                # Why this allocation


class KellyAllocator:
    """
    Kelly Criterion allocation across strategies.
    
    Kelly % = (p * b - q) / b
    where:
        p = probability of winning
        q = probability of losing (1 - p)
        b = win/loss ratio (avg_win / avg_loss)
    
    We use Half-Kelly for safety (standard in quant finance).
    """
    
    def __init__(self, fraction: float = 0.5, max_single: float = 0.40, min_single: float = 0.05):
        """
        Args:
            fraction: Kelly fraction (0.5 = half-Kelly)
            max_single: Maximum allocation to any single strategy
            min_single: Minimum allocation to any single strategy
        """
        self.fraction = fraction
        self.max_single = max_single
        self.min_single = min_single
    
    def allocate(self, strategies: list[dict], total_capital: float) -> list[AllocationResult]:
        """
        Calculate Kelly allocation for each strategy.
        
        Args:
            strategies: List of dicts with keys: name, win_rate, avg_win, avg_loss, sharpe
            total_capital: Total capital to allocate
        
        Returns:
            List of AllocationResult, one per strategy
        """
        allocations = []
        raw_kellys = []
        
        for s in strategies:
            p = s.get('win_rate', 0.5)
            q = 1 - p
            avg_win = s.get('avg_win', 1.0)
            avg_loss = s.get('avg_loss', 1.0)
            
            if avg_loss == 0:
                avg_loss = 0.01  # Avoid division by zero
            
            b = avg_win / avg_loss  # Win/loss ratio
            
            # Kelly formula
            kelly_raw = (p * b - q) / b
            
            # Clamp to reasonable range
            kelly_raw = max(kelly_raw, 0.0)
            kelly_raw = min(kelly_raw, 0.5)  # Never more than 50% Kelly
            
            kelly_half = kelly_raw * 0.5
            kelly_quarter = kelly_raw * 0.25
            
            # Use half-Kelly by default
            allocated_pct = kelly_half * self.fraction * 2  # Adjust for fraction
            allocated_pct = max(allocated_pct, self.min_single if kelly_raw > 0 else 0)
            allocated_pct = min(allocated_pct, self.max_single)
            
            raw_kellys.append(kelly_raw)
            
            allocations.append(AllocationResult(
                strategy_name=s['name'],
                kelly_raw=kelly_raw,
                kelly_half=kelly_half,
                kelly_quarter=kelly_quarter,
                allocated_pct=allocated_pct,
                allocated_usd=total_capital * allocated_pct,
                reason=f"Kelly raw={kelly_raw:.3f}, half={kelly_half:.3f}, "
                       f"win_rate={p:.2f}, W/L ratio={b:.2f}"
            ))
        
        # Normalize to 100% if overallocated
        total_alloc = sum(a.allocated_pct for a in allocations)
        if total_alloc > 1.0:
            scale = 1.0 / total_alloc
            for a in allocations:
                a.allocated_pct *= scale
                a.allocated_usd = total_capital * a.allocated_pct
                a.reason += f" (scaled {scale:.2f}x to fit 100%)"
        
        return allocations
```

#### 4.2.2 Risk Parity (Alternative)

```python
class RiskParityAllocator:
    """
    Risk parity: allocate so each strategy contributes equal risk.
    
    Strategy with higher volatility gets less capital.
    Strategy with lower volatility gets more capital.
    """
    
    def allocate(self, strategies: list[dict], total_capital: float) -> list[AllocationResult]:
        """
        Calculate risk parity allocation.
        
        Args:
            strategies: List of dicts with keys: name, volatility (annualized std dev)
            total_capital: Total capital to allocate
        """
        # Inverse volatility weighting
        inv_vols = []
        for s in strategies:
            vol = s.get('volatility', 0.20)  # Default 20% annualized
            if vol <= 0:
                vol = 0.01
            inv_vols.append(1.0 / vol)
        
        total_inv_vol = sum(inv_vols)
        
        allocations = []
        for i, s in enumerate(strategies):
            alloc_pct = inv_vols[i] / total_inv_vol
            allocations.append(AllocationResult(
                strategy_name=s['name'],
                kelly_raw=0,  # Not applicable
                kelly_half=0,
                kelly_quarter=0,
                allocated_pct=alloc_pct,
                allocated_usd=total_capital * alloc_pct,
                reason=f"Risk parity: vol={s.get('volatility', 0.20):.3f}, "
                       f"inv_vol_weight={inv_vols[i]/total_inv_vol:.3f}"
            ))
        
        return allocations
```

#### 4.2.3 Adaptive Allocation (Level 3+)

```python
class AdaptiveAllocator:
    """
    Combines Kelly + regime awareness + correlation.
    
    1. Start with Kelly base allocation
    2. Adjust for current regime (boost strategies that work in this regime)
    3. Adjust for correlation (reduce correlated pairs)
    4. Apply drawdown penalty (reduce allocation to struggling strategies)
    """
    
    def __init__(self):
        self.kelly = KellyAllocator()
        self.regime_boost_factor = 1.5   # 50% boost for regime-matched strategies
        self.correlation_penalty = 0.7    # 30% reduction for correlated pairs
        self.drawdown_penalty_threshold = 0.10  # 10% drawdown triggers penalty
    
    def allocate(self, strategies: list[dict], total_capital: float,
                 current_regime: str = None,
                 correlation_matrix=None) -> list[AllocationResult]:
        """Multi-factor adaptive allocation."""
        
        # Step 1: Base Kelly allocation
        allocations = self.kelly.allocate(strategies, total_capital)
        
        # Step 2: Regime adjustment
        if current_regime:
            for alloc in allocations:
                s = next((s for s in strategies if s['name'] == alloc.strategy_name), None)
                if s and current_regime in s.get('preferred_regimes', []):
                    alloc.allocated_pct *= self.regime_boost_factor
                    alloc.reason += f" [regime boost: {current_regime}]"
                elif s and current_regime in s.get('blacklisted_regimes', []):
                    alloc.allocated_pct *= 0.1  # Near-zero for blacklisted regime
                    alloc.reason += f" [regime penalty: {current_regime}]"
        
        # Step 3: Correlation adjustment
        if correlation_matrix is not None:
            for i, alloc_i in enumerate(allocations):
                for j, alloc_j in enumerate(allocations):
                    if i >= j:
                        continue
                    if alloc_i.strategy_name in correlation_matrix.index and \
                       alloc_j.strategy_name in correlation_matrix.columns:
                        corr = correlation_matrix.loc[alloc_i.strategy_name, alloc_j.strategy_name]
                        if abs(corr) > 0.7:
                            # Reduce the smaller allocation
                            if alloc_i.allocated_pct < alloc_j.allocated_pct:
                                alloc_i.allocated_pct *= self.correlation_penalty
                                alloc_i.reason += f" [corr penalty with {alloc_j.strategy_name}: {corr:.2f}]"
                            else:
                                alloc_j.allocated_pct *= self.correlation_penalty
                                alloc_j.reason += f" [corr penalty with {alloc_i.strategy_name}: {corr:.2f}]"
        
        # Step 4: Drawdown penalty
        for alloc in allocations:
            s = next((s for s in strategies if s['name'] == alloc.strategy_name), None)
            if s and s.get('max_drawdown', 0) > self.drawdown_penalty_threshold:
                penalty = 1.0 - (s['max_drawdown'] - self.drawdown_penalty_threshold)
                penalty = max(penalty, 0.2)  # Don't reduce below 20%
                alloc.allocated_pct *= penalty
                alloc.reason += f" [DD penalty: {s['max_drawdown']:.1%}]"
        
        # Normalize
        total = sum(a.allocated_pct for a in allocations)
        if total > 0:
            for a in allocations:
                a.allocated_pct = a.allocated_pct / total
                a.allocated_usd = total_capital * a.allocated_pct
        
        return allocations
```

### 4.3 Rebalancing Triggers

```python
REBALANCE_TRIGGERS = {
    'schedule': {
        'frequency': 'weekly',        # Rebalance every week
        'day': 'sunday',
        'time': '00:00 UTC',
    },
    'drift': {
        'threshold_pct': 5.0,         # Rebalance if any strategy drifts >5% from target
    },
    'performance': {
        'drawdown_trigger': 15.0,     # Rebalance if any strategy hits 15% drawdown
        'sharpe_break': 0.3,          # Rebalance if Sharpe drops below 0.3
    },
    'regime_change': {
        'enabled': True,              # Rebalance on regime change
        'min_confidence': 0.7,        # Only if regime change confidence > 70%
    },
    'new_strategy': {
        'enabled': True,              # Rebalance when new strategy is added
        'warmup_period_days': 7,      # Wait 7 days before full allocation
    },
}
```

---

## 5. Strategy Monitoring

### 5.1 Real-Time Performance Tracking

```python
# portfolio/strategy_monitor.py

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

@dataclass
class StrategyHealth:
    """Real-time health status of a strategy."""
    name: str
    status: str                    # HEALTHY | DEGRADED | CRITICAL | DEAD
    
    # Rolling metrics (last N trades or days)
    rolling_sharpe_7d: float
    rolling_sharpe_30d: float
    rolling_win_rate_7d: float
    rolling_win_rate_30d: float
    rolling_profit_factor_7d: float
    
    # Current state
    open_positions: int
    unrealized_pnl: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    
    # Alerts
    alerts: list[str] = field(default_factory=list)
    
    @property
    def is_healthy(self) -> bool:
        return self.status == 'HEALTHY'


class StrategyMonitor:
    """
    Monitors strategy health and generates alerts.
    Runs every minute, checks all active strategies.
    """
    
    ALERT_THRESHOLDS = {
        'sharpe_critical': -0.5,       # Sharpe below this = CRITICAL
        'sharpe_degraded': 0.3,        # Sharpe below this = DEGRADED
        'drawdown_warning': 0.08,      # 8% drawdown = warning
        'drawdown_critical': 0.15,     # 15% drawdown = critical
        'win_rate_minimum': 0.35,      # Below 35% win rate = warning
        'loss_streak_alert': 5,        # 5 consecutive losses = alert
        'daily_loss_limit': -0.02,     # -2% daily = halt strategy
    }
    
    def check_health(self, strategy_name: str, trades: list, balance: float) -> StrategyHealth:
        """Check health of a single strategy."""
        now = datetime.now()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        
        recent_7d = [t for t in trades if t['closed_at'] >= seven_days_ago]
        recent_30d = [t for t in trades if t['closed_at'] >= thirty_days_ago]
        
        alerts = []
        status = 'HEALTHY'
        
        # Calculate rolling metrics
        sharpe_7d = self._calc_rolling_sharpe(recent_7d)
        sharpe_30d = self._calc_rolling_sharpe(recent_30d)
        win_rate_7d = self._calc_win_rate(recent_7d)
        win_rate_30d = self._calc_win_rate(recent_30d)
        pf_7d = self._calc_profit_factor(recent_7d)
        
        # Check alerts
        if sharpe_7d < self.ALERT_THRESHOLDS['sharpe_critical']:
            alerts.append(f"CRITICAL: 7-day Sharpe = {sharpe_7d:.2f}")
            status = 'CRITICAL'
        elif sharpe_7d < self.ALERT_THRESHOLDS['sharpe_degraded']:
            alerts.append(f"WARNING: 7-day Sharpe = {sharpe_7d:.2f}")
            status = 'DEGRADED'
        
        if win_rate_7d < self.ALERT_THRESHOLDS['win_rate_minimum'] and len(recent_7d) >= 10:
            alerts.append(f"WARNING: 7-day win rate = {win_rate_7d:.1%}")
            if status == 'HEALTHY':
                status = 'DEGRADED'
        
        # Loss streak detection
        loss_streak = self._calc_loss_streak(recent_30d)
        if loss_streak >= self.ALERT_THRESHOLDS['loss_streak_alert']:
            alerts.append(f"ALERT: {loss_streak} consecutive losses")
        
        # Drawdown check
        current_dd = self._calc_current_drawdown(trades, balance)
        if current_dd > self.ALERT_THRESHOLDS['drawdown_critical']:
            alerts.append(f"CRITICAL: Drawdown = {current_dd:.1%}")
            status = 'CRITICAL'
        elif current_dd > self.ALERT_THRESHOLDS['drawdown_warning']:
            alerts.append(f"WARNING: Drawdown = {current_dd:.1%}")
        
        # Daily P&L check
        daily_pnl = self._calc_daily_pnl(trades)
        if daily_pnl < self.ALERT_THRESHOLDS['daily_loss_limit']:
            alerts.append(f"HALT: Daily loss = {daily_pnl:.2%}")
            status = 'CRITICAL'
        
        return StrategyHealth(
            name=strategy_name,
            status=status,
            rolling_sharpe_7d=sharpe_7d,
            rolling_sharpe_30d=sharpe_30d,
            rolling_win_rate_7d=win_rate_7d,
            rolling_win_rate_30d=win_rate_30d,
            rolling_profit_factor_7d=pf_7d,
            open_positions=0,  # Filled by position tracker
            unrealized_pnl=0.0,
            daily_pnl=daily_pnl,
            weekly_pnl=self._calc_period_pnl(trades, 7),
            monthly_pnl=self._calc_period_pnl(trades, 30),
            alerts=alerts
        )
    
    def _calc_rolling_sharpe(self, trades: list) -> float:
        if len(trades) < 5:
            return 0.0
        returns = [t.get('pnl_pct', 0) for t in trades]
        if not returns or np.std(returns) == 0:
            return 0.0
        return np.mean(returns) / np.std(returns) * np.sqrt(252)
    
    def _calc_win_rate(self, trades: list) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        return wins / len(trades)
    
    def _calc_profit_factor(self, trades: list) -> float:
        gross_profit = sum(t['pnl'] for t in trades if t.get('pnl', 0) > 0)
        gross_loss = abs(sum(t['pnl'] for t in trades if t.get('pnl', 0) < 0))
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        return gross_profit / gross_loss
    
    def _calc_loss_streak(self, trades: list) -> int:
        max_streak = 0
        current_streak = 0
        for t in sorted(trades, key=lambda x: x.get('closed_at', '')):
            if t.get('pnl', 0) < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak
    
    def _calc_current_drawdown(self, trades: list, balance: float) -> float:
        if not trades or balance <= 0:
            return 0.0
        peak = balance
        current = balance
        for t in sorted(trades, key=lambda x: x.get('closed_at', '')):
            current += t.get('pnl', 0)
            peak = max(peak, current)
        return (peak - current) / peak if peak > 0 else 0.0
    
    def _calc_daily_pnl(self, trades: list) -> float:
        today = datetime.now().date()
        return sum(t.get('pnl_pct', 0) for t in trades if t.get('closed_at', datetime.min).date() == today)
    
    def _calc_period_pnl(self, trades: list, days: int) -> float:
        cutoff = datetime.now() - timedelta(days=days)
        return sum(t.get('pnl', 0) for t in trades if t.get('closed_at', datetime.min) >= cutoff)
```

### 5.2 Telegram Alerts

```
📊 STRATEGY HEALTH — Daily Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Mean Reversion: HEALTHY
   Sharpe(7d): 1.42 | Win Rate: 58% | PF: 1.67
   Open: 1 | Daily P&L: +0.8%

⚠️ Momentum: DEGRADED
   Sharpe(7d): 0.28 | Win Rate: 42% | PF: 0.95
   Open: 0 | Daily P&L: -0.3%
   ⚠️ 5 consecutive losses
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Portfolio Sharpe: 1.15 | Total P&L: +$2.45
```

---

## 6. Strategy Retirement Gates

### 6.1 Purpose

Strategies decay. Market regimes shift. A strategy that worked for 6 months may stop working. Auto-retirement prevents holding onto losing strategies out of hope or attachment.

### 6.2 Retirement Gates

```python
# portfolio/retirement_gates.py

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

class RetirementAction(Enum):
    CONTINUE = "continue"       # Strategy is fine
    WARN = "warn"               # Yellow flag, monitor closely
    REDUCE = "reduce"           # Reduce allocation by 50%
    PAUSE = "pause"             # Stop trading, keep monitoring
    RETIRE = "retire"           # Permanently retire

@dataclass
class RetirementDecision:
    strategy_name: str
    action: RetirementAction
    reason: str
    trigger: str                # Which gate triggered
    metrics: dict               # Current metrics that triggered
    grace_period_hours: int     # How long before action takes effect
    can_appeal: bool            # Whether human can override


class RetirementGates:
    """
    Automatic strategy retirement system.
    
    Gates are checked in order. First gate to trigger determines action.
    Multiple gates can trigger simultaneously (worst action wins).
    """
    
    # Gate definitions
    GATES = {
        # ── GATE 1: Rolling Sharpe ──
        'rolling_sharpe': {
            'lookback_days': 30,
            'warn_threshold': 0.5,
            'reduce_threshold': 0.2,
            'pause_threshold': -0.2,
            'retire_threshold': -0.5,
            'min_trades': 20,  # Need at least 20 trades in window
        },
        
        # ── GATE 2: Drawdown ──
        'max_drawdown': {
            'warn_pct': 8.0,
            'reduce_pct': 12.0,
            'pause_pct': 15.0,
            'retire_pct': 20.0,
        },
        
        # ── GATE 3: Win Rate Degradation ──
        'win_rate': {
            'lookback_days': 30,
            'warn_pct': 42.0,
            'reduce_pct': 38.0,
            'pause_pct': 33.0,
            'retire_pct': 28.0,
            'min_trades': 20,
        },
        
        # ── GATE 4: Loss Streak ──
        'loss_streak': {
            'warn_count': 5,
            'reduce_count': 7,
            'pause_count': 10,
            'retire_count': 15,
        },
        
        # ── GATE 5: Profit Factor ──
        'profit_factor': {
            'lookback_days': 30,
            'warn_threshold': 1.0,   # Breakeven
            'reduce_threshold': 0.8,  # Losing money
            'pause_threshold': 0.6,
            'retire_threshold': 0.4,
            'min_trades': 20,
        },
        
        # ── GATE 6: Consecutive Losing Days ──
        'losing_days': {
            'warn_days': 5,
            'reduce_days': 7,
            'pause_days': 10,
            'retire_days': 14,
        },
        
        # ── GATE 7: Regime Mismatch ──
        'regime_mismatch': {
            'lookback_days': 14,
            'min_trades': 10,
            'retire_if_all_regimes_negative': True,
        },
    }
    
    def evaluate(self, strategy_name: str, trades: list, 
                 current_regime: str = None, balance: float = 0) -> RetirementDecision:
        """
        Evaluate all retirement gates for a strategy.
        Returns the WORST action across all gates.
        """
        now = datetime.now()
        actions = []
        
        # Gate 1: Rolling Sharpe
        decision = self._check_rolling_sharpe(strategy_name, trades, now)
        if decision:
            actions.append(decision)
        
        # Gate 2: Drawdown
        decision = self._check_drawdown(strategy_name, trades, balance)
        if decision:
            actions.append(decision)
        
        # Gate 3: Win Rate
        decision = self._check_win_rate(strategy_name, trades, now)
        if decision:
            actions.append(decision)
        
        # Gate 4: Loss Streak
        decision = self._check_loss_streak(strategy_name, trades)
        if decision:
            actions.append(decision)
        
        # Gate 5: Profit Factor
        decision = self._check_profit_factor(strategy_name, trades, now)
        if decision:
            actions.append(decision)
        
        # Gate 6: Losing Days
        decision = self._check_losing_days(strategy_name, trades, now)
        if decision:
            actions.append(decision)
        
        # Gate 7: Regime Mismatch
        if current_regime:
            decision = self._check_regime_mismatch(strategy_name, trades, current_regime, now)
            if decision:
                actions.append(decision)
        
        if not actions:
            return RetirementDecision(
                strategy_name=strategy_name,
                action=RetirementAction.CONTINUE,
                reason="All gates passed",
                trigger="none",
                metrics={},
                grace_period_hours=0,
                can_appeal=False
            )
        
        # Return the worst action
        severity = {
            RetirementAction.CONTINUE: 0,
            RetirementAction.WARN: 1,
            RetirementAction.REDUCE: 2,
            RetirementAction.PAUSE: 3,
            RetirementAction.RETIRE: 4,
        }
        
        worst = max(actions, key=lambda d: severity[d.action])
        return worst
    
    def _check_rolling_sharpe(self, name, trades, now) -> RetirementDecision | None:
        gate = self.GATES['rolling_sharpe']
        cutoff = now - timedelta(days=gate['lookback_days'])
        recent = [t for t in trades if t.get('closed_at', datetime.min) >= cutoff]
        
        if len(recent) < gate['min_trades']:
            return None
        
        returns = [t.get('pnl_pct', 0) for t in recent]
        if not returns or np.std(returns) == 0:
            return None
        
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        if sharpe < gate['retire_threshold']:
            return RetirementDecision(name, RetirementAction.RETIRE,
                f"30-day Sharpe = {sharpe:.2f} < {gate['retire_threshold']}",
                'rolling_sharpe', {'sharpe_30d': sharpe}, 0, True)
        elif sharpe < gate['pause_threshold']:
            return RetirementDecision(name, RetirementAction.PAUSE,
                f"30-day Sharpe = {sharpe:.2f} < {gate['pause_threshold']}",
                'rolling_sharpe', {'sharpe_30d': sharpe}, 48, True)
        elif sharpe < gate['reduce_threshold']:
            return RetirementDecision(name, RetirementAction.REDUCE,
                f"30-day Sharpe = {sharpe:.2f} < {gate['reduce_threshold']}",
                'rolling_sharpe', {'sharpe_30d': sharpe}, 24, False)
        elif sharpe < gate['warn_threshold']:
            return RetirementDecision(name, RetirementAction.WARN,
                f"30-day Sharpe = {sharpe:.2f} < {gate['warn_threshold']}",
                'rolling_sharpe', {'sharpe_30d': sharpe}, 0, False)
        
        return None
    
    def _check_drawdown(self, name, trades, balance) -> RetirementDecision | None:
        gate = self.GATES['max_drawdown']
        
        if not trades or balance <= 0:
            return None
        
        peak = balance
        current = balance
        max_dd = 0
        
        for t in sorted(trades, key=lambda x: x.get('closed_at', '')):
            current += t.get('pnl', 0)
            peak = max(peak, current)
            dd = (peak - current) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
        
        if max_dd >= gate['retire_pct']:
            return RetirementDecision(name, RetirementAction.RETIRE,
                f"Max drawdown = {max_dd:.1f}% >= {gate['retire_pct']}%",
                'max_drawdown', {'max_drawdown_pct': max_dd}, 0, True)
        elif max_dd >= gate['pause_pct']:
            return RetirementDecision(name, RetirementAction.PAUSE,
                f"Max drawdown = {max_dd:.1f}% >= {gate['pause_pct']}%",
                'max_drawdown', {'max_drawdown_pct': max_dd}, 24, True)
        elif max_dd >= gate['reduce_pct']:
            return RetirementDecision(name, RetirementAction.REDUCE,
                f"Max drawdown = {max_dd:.1f}% >= {gate['reduce_pct']}%",
                'max_drawdown', {'max_drawdown_pct': max_dd}, 12, False)
        elif max_dd >= gate['warn_pct']:
            return RetirementDecision(name, RetirementAction.WARN,
                f"Max drawdown = {max_dd:.1f}% >= {gate['warn_pct']}%",
                'max_drawdown', {'max_drawdown_pct': max_dd}, 0, False)
        
        return None
    
    def _check_win_rate(self, name, trades, now) -> RetirementDecision | None:
        gate = self.GATES['win_rate']
        cutoff = now - timedelta(days=gate['lookback_days'])
        recent = [t for t in trades if t.get('closed_at', datetime.min) >= cutoff]
        
        if len(recent) < gate['min_trades']:
            return None
        
        wins = sum(1 for t in recent if t.get('pnl', 0) > 0)
        win_rate = wins / len(recent) * 100
        
        if win_rate < gate['retire_pct']:
            return RetirementDecision(name, RetirementAction.RETIRE,
                f"30-day win rate = {win_rate:.1f}% < {gate['retire_pct']}%",
                'win_rate', {'win_rate_30d': win_rate}, 0, True)
        elif win_rate < gate['pause_pct']:
            return RetirementDecision(name, RetirementAction.PAUSE,
                f"30-day win rate = {win_rate:.1f}% < {gate['pause_pct']}%",
                'win_rate', {'win_rate_30d': win_rate}, 48, True)
        elif win_rate < gate['reduce_pct']:
            return RetirementDecision(name, RetirementAction.REDUCE,
                f"30-day win rate = {win_rate:.1f}% < {gate['reduce_pct']}%",
                'win_rate', {'win_rate_30d': win_rate}, 24, False)
        elif win_rate < gate['warn_pct']:
            return RetirementDecision(name, RetirementAction.WARN,
                f"30-day win rate = {win_rate:.1f}% < {gate['warn_pct']}%",
                'win_rate', {'win_rate_30d': win_rate}, 0, False)
        
        return None
    
    def _check_loss_streak(self, name, trades) -> RetirementDecision | None:
        gate = self.GATES['loss_streak']
        
        streak = 0
        for t in sorted(trades, key=lambda x: x.get('closed_at', '')):
            if t.get('pnl', 0) < 0:
                streak += 1
            else:
                streak = 0
        
        if streak >= gate['retire_count']:
            return RetirementDecision(name, RetirementAction.RETIRE,
                f"{streak} consecutive losses >= {gate['retire_count']}",
                'loss_streak', {'current_streak': streak}, 0, True)
        elif streak >= gate['pause_count']:
            return RetirementDecision(name, RetirementAction.PAUSE,
                f"{streak} consecutive losses >= {gate['pause_count']}",
                'loss_streak', {'current_streak': streak}, 24, True)
        elif streak >= gate['reduce_count']:
            return RetirementDecision(name, RetirementAction.REDUCE,
                f"{streak} consecutive losses >= {gate['reduce_count']}",
                'loss_streak', {'current_streak': streak}, 12, False)
        elif streak >= gate['warn_count']:
            return RetirementDecision(name, RetirementAction.WARN,
                f"{streak} consecutive losses >= {gate['warn_count']}",
                'loss_streak', {'current_streak': streak}, 0, False)
        
        return None
    
    def _check_profit_factor(self, name, trades, now) -> RetirementDecision | None:
        gate = self.GATES['profit_factor']
        cutoff = now - timedelta(days=gate['lookback_days'])
        recent = [t for t in trades if t.get('closed_at', datetime.min) >= cutoff]
        
        if len(recent) < gate['min_trades']:
            return None
        
        gross_profit = sum(t['pnl'] for t in recent if t.get('pnl', 0) > 0)
        gross_loss = abs(sum(t['pnl'] for t in recent if t.get('pnl', 0) < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        
        if pf < gate['retire_threshold']:
            return RetirementDecision(name, RetirementAction.RETIRE,
                f"30-day profit factor = {pf:.2f} < {gate['retire_threshold']}",
                'profit_factor', {'profit_factor_30d': pf}, 0, True)
        elif pf < gate['pause_threshold']:
            return RetirementDecision(name, RetirementAction.PAUSE,
                f"30-day profit factor = {pf:.2f} < {gate['pause_threshold']}",
                'profit_factor', {'profit_factor_30d': pf}, 48, True)
        elif pf < gate['reduce_threshold']:
            return RetirementDecision(name, RetirementAction.REDUCE,
                f"30-day profit factor = {pf:.2f} < {gate['reduce_threshold']}",
                'profit_factor', {'profit_factor_30d': pf}, 24, False)
        elif pf < gate['warn_threshold']:
            return RetirementDecision(name, RetirementAction.WARN,
                f"30-day profit factor = {pf:.2f} < {gate['warn_threshold']}",
                'profit_factor', {'profit_factor_30d': pf}, 0, False)
        
        return None
    
    def _check_losing_days(self, name, trades, now) -> RetirementDecision | None:
        gate = self.GATES['losing_days']
        
        # Group trades by day
        daily_pnl = {}
        for t in trades:
            day = t.get('closed_at', datetime.min).date()
            daily_pnl[day] = daily_pnl.get(day, 0) + t.get('pnl', 0)
        
        # Count consecutive losing days
        streak = 0
        for day in sorted(daily_pnl.keys()):
            if daily_pnl[day] < 0:
                streak += 1
            else:
                streak = 0
        
        if streak >= gate['retire_days']:
            return RetirementDecision(name, RetirementAction.RETIRE,
                f"{streak} consecutive losing days >= {gate['retire_days']}",
                'losing_days', {'losing_day_streak': streak}, 0, True)
        elif streak >= gate['pause_days']:
            return RetirementDecision(name, RetirementAction.PAUSE,
                f"{streak} consecutive losing days >= {gate['pause_days']}",
                'losing_days', {'losing_day_streak': streak}, 24, True)
        elif streak >= gate['reduce_days']:
            return RetirementDecision(name, RetirementAction.REDUCE,
                f"{streak} consecutive losing days >= {gate['reduce_days']}",
                'losing_days', {'losing_day_streak': streak}, 12, False)
        elif streak >= gate['warn_days']:
            return RetirementDecision(name, RetirementAction.WARN,
                f"{streak} consecutive losing days >= {gate['warn_days']}",
                'losing_days', {'losing_day_streak': streak}, 0, False)
        
        return None
    
    def _check_regime_mismatch(self, name, trades, current_regime, now) -> RetirementDecision | None:
        gate = self.GATES['regime_mismatch']
        cutoff = now - timedelta(days=gate['lookback_days'])
        recent = [t for t in trades if t.get('closed_at', datetime.min) >= cutoff]
        
        if len(recent) < gate['min_trades']:
            return None
        
        # Check performance in current regime
        regime_trades = [t for t in recent if t.get('regime') == current_regime]
        if len(regime_trades) < 5:
            return None
        
        regime_pnl = sum(t.get('pnl', 0) for t in regime_trades)
        
        if regime_pnl < 0 and gate['retire_if_all_regimes_negative']:
            # Check if ALL regimes are negative
            regimes = set(t.get('regime') for t in recent if t.get('regime'))
            all_negative = all(
                sum(t.get('pnl', 0) for t in recent if t.get('regime') == r) < 0
                for r in regimes
            )
            if all_negative and len(regimes) >= 2:
                return RetirementDecision(name, RetirementAction.RETIRE,
                    f"Negative P&L in all {len(regimes)} regimes traded",
                    'regime_mismatch', {'regimes_traded': list(regimes)}, 0, True)
        
        return None
```

### 6.3 Graceful Retirement Process

```
RETIREMENT PROCESS:
━━━━━━━━━━━━━━━━━━

1. GATE TRIGGERED
   └─ Retirement gate fires (e.g., Sharpe < -0.5)

2. GRACE PERIOD
   └─ Action delayed by grace_period_hours
   └─ Telegram alert: "⚠️ Strategy X: RETIRE gate triggered. Grace period: 0h."

3. ACTION EXECUTED
   ├─ WARN: No action, just monitoring
   ├─ REDUCE: Allocation cut by 50%, new signals scaled down
   ├─ PAUSE: No new signals, existing positions managed to exit
   └─ RETIRE: All positions closed, strategy removed from active pool

4. POST-RETIREMENT
   └─ Strategy moves to RETIRED status
   └─ Historical data preserved for analysis
   └─ Can be reactivated after review (manual only)
   └─ Lessons extracted and archived

5. TELEGRAM NOTIFICATION
   └─ "🔴 Strategy X RETIRED. Reason: 30-day Sharpe = -0.62.
       47 trades, 32% win rate. All positions closed.
       Strategy can be reactivated with /reactivate X"
```

### 6.4 Appeal Mechanism

```python
# Human can override retirement via Telegram
# /reactivate <strategy_name> [reason]

def reactivate_strategy(strategy_name: str, reason: str) -> str:
    """
    Reactivate a retired strategy.
    Requires manual confirmation and starts in WARMUP status.
    """
    strategy = registry.get(strategy_name)
    if not strategy:
        return f"Strategy '{strategy_name}' not found"
    
    if strategy.status != StrategyStatus.RETIRED:
        return f"Strategy '{strategy_name}' is not retired (status: {strategy.status.value})"
    
    strategy.status = StrategyStatus.WARMUP
    strategy.warmup_trades_remaining = 20  # 20 trades before full activation
    strategy.allocation_pct = strategy.min_allocation_pct  # Start with minimum
    
    # Log the reactivation
    log_lesson(
        lesson_type='INSIGHT',
        category='STRATEGY',
        description=f"Strategy '{strategy_name}' manually reactivated. Reason: {reason}",
        action_item="Monitor closely for 20 trades before full allocation"
    )
    
    return f"✅ Strategy '{strategy_name}' reactivated in WARMUP mode. 20 trades before full activation."
```

---

## 7. Strategy Research

### 7.1 Purpose

Systematic process for discovering, validating, and deploying new strategies. This is where the Strategy Geneticist agent operates.

### 7.2 Research Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY RESEARCH PIPELINE                           │
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐               │
│  │  Hypothesis  │──▶│  Backtest    │──▶│  Walk-Forward│               │
│  │  Generation  │   │  (full)      │   │  Validation  │               │
│  └──────────────┘   └──────────────┘   └──────────────┘               │
│         │                                       │                      │
│         │              ┌──────────────┐          │                      │
│         │              │  Paper Trade │◀─────────┘                      │
│         │              │  (live sim)  │                                 │
│         │              └──────┬───────┘                                 │
│         │                     │                                         │
│         │              ┌──────────────┐                                │
│         │              │  Live Trade  │                                │
│         │              │  ($10 capital)│                                │
│         │              └──────┬───────┘                                 │
│         │                     │                                         │
│         │              ┌──────────────┐                                │
│         └─────────────▶│  Monitor &   │                                │
│                        │  Evolve      │                                │
│                        └──────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.3 Hypothesis Generation

```python
# research/hypothesis_generator.py

class HypothesisGenerator:
    """
    Generates new strategy hypotheses.
    Sources: LLM reasoning, pattern library, academic research, trade analysis.
    """
    
    HYPOTHESIS_TEMPLATE = """
    You are a quantitative trading researcher. Based on the following context,
    propose a new trading strategy hypothesis.
    
    Current strategies: {current_strategies}
    Current regime: {current_regime}
    Recent patterns: {recent_patterns}
    Market observations: {observations}
    
    Propose a strategy with:
    1. THESIS: Why this edge exists (market microstructure reason)
    2. ENTRY RULES: Specific, testable conditions
    3. EXIT RULES: Stop-loss, take-profit, time-based
    4. EXPECTED REGIME: Where this should work
    5. RISK FACTORS: What could go wrong
    6. FALSIFICATION: What data would prove this wrong
    
    Be specific. "Buy when RSI is low" is not a hypothesis.
    "When RSI(14) drops below 25 on 1H chart while price is within 0.3% 
    of the 48-hour VWAP and volume is 1.5x the 20-period average, 
    price tends to revert to VWAP within 4-8 candles with 62% probability"
    IS a hypothesis.
    """
    
    def generate(self, context: dict) -> list[dict]:
        """Generate N strategy hypotheses."""
        prompt = self.HYPOTHESIS_TEMPLATE.format(**context)
        
        # Use DeepSeek-R1 for creative strategy synthesis
        response = query_deepseek(prompt)
        
        hypotheses = self._parse_hypotheses(response)
        
        # Add metadata
        for h in hypotheses:
            h['generated_at'] = datetime.now().isoformat()
            h['source'] = 'llm_synthesis'
            h['status'] = 'unvalidated'
        
        return hypotheses
```

### 7.4 Statistical Validation

```python
# research/statistical_validator.py

import numpy as np
from scipy import stats

class StatisticalValidator:
    """
    Validates that strategy returns are statistically significant.
    Prevents deploying strategies that got lucky.
    """
    
    def validate(self, returns: list[float], benchmark_returns: list[float] = None) -> dict:
        """
        Run statistical tests on strategy returns.
        
        Returns dict with test results and pass/fail.
        """
        results = {}
        
        returns = np.array(returns)
        
        # Test 1: Is the mean return significantly different from zero?
        t_stat, p_value = stats.ttest_1samp(returns, 0)
        results['t_test'] = {
            't_statistic': t_stat,
            'p_value': p_value,
            'significant': p_value < 0.05,
            'interpretation': f"Mean return is {'significantly' if p_value < 0.05 else 'NOT significantly'} different from zero (p={p_value:.4f})"
        }
        
        # Test 2: Is Sharpe ratio significantly > 0?
        if np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
            # Bootstrap confidence interval for Sharpe
            sharpe_ci = self._bootstrap_sharpe_ci(returns, n_bootstrap=1000)
            results['sharpe_test'] = {
                'sharpe': sharpe,
                'ci_lower': sharpe_ci[0],
                'ci_upper': sharpe_ci[1],
                'significant': sharpe_ci[0] > 0,
                'interpretation': f"Sharpe = {sharpe:.2f}, 95% CI: [{sharpe_ci[0]:.2f}, {sharpe_ci[1]:.2f}]"
            }
        
        # Test 3: Is win rate significantly > 50%?
        wins = np.sum(returns > 0)
        total = len(returns)
        binom_result = stats.binomtest(wins, total, 0.5, alternative='greater')
        results['win_rate_test'] = {
            'win_rate': wins / total,
            'p_value': binom_result.pvalue,
            'significant': binom_result.pvalue < 0.05,
            'interpretation': f"Win rate = {wins/total:.1%} is {'significantly' if binom_result.pvalue < 0.05 else 'NOT significantly'} > 50%"
        }
        
        # Test 4: Runs test for randomness
        median = np.median(returns)
        runs = self._count_runs(returns, median)
        expected_runs = (2 * wins * (total - wins)) / total + 1
        run_std = np.sqrt((2 * wins * (total - wins) * (2 * wins * (total - wins) - total)) / (total**2 * (total - 1)))
        if run_std > 0:
            z_runs = (runs - expected_runs) / run_std
            p_runs = 2 * (1 - stats.norm.cdf(abs(z_runs)))
            results['runs_test'] = {
                'runs': runs,
                'expected': expected_runs,
                'z_score': z_runs,
                'p_value': p_runs,
                'significant': p_runs < 0.05,
                'interpretation': f"Returns are {'NOT ' if p_runs >= 0.05 else ''}randomly distributed (p={p_runs:.4f})"
            }
        
        # Test 5: Benchmark comparison (if provided)
        if benchmark_returns is not None:
            benchmark_returns = np.array(benchmark_returns)
            t_stat, p_value = stats.ttest_rel(returns[:len(benchmark_returns)], benchmark_returns[:len(returns)])
            results['benchmark_test'] = {
                't_statistic': t_stat,
                'p_value': p_value,
                'significant': p_value < 0.05 and np.mean(returns) > np.mean(benchmark_returns),
                'interpretation': f"Strategy {'outperforms' if p_value < 0.05 and np.mean(returns) > np.mean(benchmark_returns) else 'does NOT outperform'} benchmark"
            }
        
        # Overall verdict
        significant_tests = sum(1 for v in results.values() if v.get('significant', False))
        total_tests = len(results)
        results['overall'] = {
            'tests_passed': significant_tests,
            'total_tests': total_tests,
            'verdict': 'VALID' if significant_tests >= total_tests * 0.6 else 'INSUFFICIENT_EVIDENCE'
        }
        
        return results
    
    def _bootstrap_sharpe_ci(self, returns: np.ndarray, n_bootstrap: int = 1000, confidence: float = 0.95) -> tuple:
        """Bootstrap confidence interval for Sharpe ratio."""
        sharpes = []
        n = len(returns)
        for _ in range(n_bootstrap):
            sample = np.random.choice(returns, size=n, replace=True)
            if np.std(sample) > 0:
                sharpes.append(np.mean(sample) / np.std(sample) * np.sqrt(252))
        
        alpha = (1 - confidence) / 2
        return (np.percentile(sharpes, alpha * 100), np.percentile(sharpes, (1 - alpha) * 100))
    
    def _count_runs(self, data: np.ndarray, median: float) -> int:
        """Count runs above/below median."""
        above = data > median
        runs = 1
        for i in range(1, len(above)):
            if above[i] != above[i-1]:
                runs += 1
        return runs
```

---

## 8. Day1 vs Full Implementation

### 8.1 Implementation Levels

| Component | Day1 | Level 2 | Level 3 | Level 4 |
|-----------|------|---------|---------|---------|
| **Backtesting** | ❌ Skip (paper trading) | ✅ vectorbt + basic metrics | ✅ + walk-forward | ✅ + genetic optimization |
| **Walk-Forward** | ❌ Skip | ⚠️ Basic 3-fold | ✅ Full 5-fold + overfit detection | ✅ + Bayesian optimization |
| **Strategy Portfolio** | ❌ 1 strategy | ⚠️ 2-3 strategies | ✅ Full registry + correlation | ✅ + adaptive allocation |
| **Strategy Allocation** | ❌ Equal (100% to 1) | ⚠️ Fixed split | ✅ Kelly + risk parity | ✅ + adaptive + regime-aware |
| **Strategy Monitoring** | ⚠️ Daily report | ✅ Rolling metrics | ✅ Real-time + alerts | ✅ + regime-aware health |
| **Retirement Gates** | ❌ Manual | ⚠️ Basic (Sharpe + DD) | ✅ Full 7-gate system | ✅ + regime mismatch |
| **Strategy Research** | ❌ Manual | ⚠️ Basic backtest CLI | ✅ Hypothesis generator | ✅ + genetic evolution |

### 8.2 Day1 Strategy (Mean Reversion Only)

**What to build:**
- Single strategy class with `generate_signals()` method
- Basic performance tracking in `strategies` DB table
- Daily P&L report via Telegram
- Manual parameter adjustment based on lessons

**What NOT to build:**
- Backtesting engine (paper trading IS the backtest)
- Walk-forward validation (not enough data)
- Strategy allocation (only 1 strategy)
- Retirement gates (manual review only)

```python
# Day1: Simple strategy tracking (already in DAY1_ARCHITECTURE.md)
# Just add to daily_report.py:

def daily_strategy_report():
    conn = sqlite3.connect('data/tsar.db')
    
    # Today's trades
    today = datetime.now().date()
    trades = conn.execute(
        "SELECT * FROM trades WHERE date(closed_at) = ? AND strategy = 'mean_reversion'",
        (today,)
    ).fetchall()
    
    total_pnl = sum(t['pnl'] for t in trades)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    win_rate = wins / len(trades) if trades else 0
    
    report = f"""
📊 Daily Strategy Report — Mean Reversion
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Trades: {len(trades)} | Wins: {wins} | Win Rate: {win_rate:.0%}
P&L: ${total_pnl:+.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return report
```

### 8.3 Level 2 Strategy Additions (Months 2-3)

**Add Momentum Strategy:**
```python
class MomentumStrategy(BaseStrategy):
    """
    RSI + MACD trend following.
    Enters on momentum continuation in trending regimes.
    """
    name = "momentum"
    version = "1.0.0"
    
    def __init__(self, params=None):
        defaults = {
            'rsi_period': 14,
            'rsi_entry_low': 50,
            'rsi_entry_high': 70,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'adx_period': 14,
            'adx_threshold': 25,
            'atr_period': 14,
            'sl_atr_multiple': 2.0,
            'tp_rr_ratio': 2.5,
        }
        self.params = {**defaults, **(params or {})}
    
    def generate_signals(self, data: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        close = data['close']
        
        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(self.params['rsi_period']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.params['rsi_period']).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        # MACD
        ema_fast = close.ewm(span=self.params['macd_fast']).mean()
        ema_slow = close.ewm(span=self.params['macd_slow']).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.params['macd_signal']).mean()
        macd_hist = macd - signal
        
        # ADX (simplified)
        # ... ADX calculation ...
        
        # Entry: RSI in momentum zone + MACD histogram positive + trend
        long_entry = (
            (rsi > self.params['rsi_entry_low']) & 
            (rsi < self.params['rsi_entry_high']) & 
            (macd_hist > 0) &
            (macd_hist > macd_hist.shift(1))  # Histogram expanding
        )
        
        # Short: opposite
        short_entry = (
            (rsi < (100 - self.params['rsi_entry_low'])) & 
            (rsi > (100 - self.params['rsi_entry_high'])) & 
            (macd_hist < 0) &
            (macd_hist < macd_hist.shift(1))
        )
        
        entries = long_entry | short_entry
        exits = pd.Series(False, index=data.index)
        
        return entries, exits
```

**Add Breakout Strategy:**
```python
class BreakoutStrategy(BaseStrategy):
    """
    Price breakout with volume confirmation.
    Enters when price breaks above N-period high with volume surge.
    """
    name = "breakout"
    version = "1.0.0"
    
    def __init__(self, params=None):
        defaults = {
            'breakout_period': 20,
            'volume_multiplier': 1.5,
            'atr_period': 14,
            'sl_atr_multiple': 1.5,
            'tp_rr_ratio': 3.0,
            'consolidation_bars': 10,
            'max_atr_expansion': 2.0,
        }
        self.params = {**defaults, **(params or {})}
    
    def generate_signals(self, data: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        close = data['close']
        high = data['high']
        low = data['low']
        volume = data['volume']
        
        # N-period high/low
        period_high = high.rolling(self.params['breakout_period']).max()
        period_low = low.rolling(self.params['breakout_period']).min()
        
        # Volume confirmation
        vol_sma = volume.rolling(20).mean()
        volume_surge = volume > vol_sma * self.params['volume_multiplier']
        
        # ATR for volatility filter
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(self.params['atr_period']).mean()
        atr_expanding = atr > atr.shift(1)
        
        # Consolidation check (low ATR before breakout)
        atr_ratio = atr / atr.rolling(self.params['consolidation_bars']).mean()
        was_consolidating = atr_ratio.shift(1) < 1.0
        
        # Breakout entries
        long_breakout = (close > period_high.shift(1)) & volume_surge & atr_expanding & was_consolidating
        short_breakout = (close < period_low.shift(1)) & volume_surge & atr_expanding & was_consolidating
        
        entries = long_breakout | short_breakout
        exits = pd.Series(False, index=data.index)
        
        return entries, exits
```

### 8.4 Level 3 Full Strategy System (Months 4-6)

**Full implementation of:**
- Strategy Registry with warmup/active/paused/retired states
- Kelly Allocator with Half-Kelly default
- Correlation Tracker (30-day rolling)
- Signal Aggregator (weighted voting)
- Strategy Monitor (real-time health)
- Full 7-gate Retirement system
- Backtest CLI with walk-forward

### 8.5 Level 4 Genetic Evolution (Months 7-12)

**Add:**
- Strategy Geneticist agent
- Genetic programming (mutation, crossover, pruning)
- LLM-based hypothesis generation
- Bayesian parameter optimization
- Automated strategy discovery pipeline

---

## 9. Database Schema Extensions

### 9.1 New Tables for Strategy Layer

```sql
-- ============================================
-- STRATEGY_ALLOCATIONS: Capital allocation per strategy
-- ============================================
CREATE TABLE IF NOT EXISTS strategy_allocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    allocation_pct  REAL NOT NULL,
    allocated_usd   REAL NOT NULL,
    method          TEXT NOT NULL,              -- 'kelly' | 'risk_parity' | 'adaptive' | 'manual'
    reason          TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP                  -- When to rebalance
);

-- ============================================
-- STRATEGY_HEALTH_LOG: Periodic health snapshots
-- ============================================
CREATE TABLE IF NOT EXISTS strategy_health_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    status          TEXT NOT NULL,              -- 'HEALTHY' | 'DEGRADED' | 'CRITICAL'
    sharpe_7d       REAL,
    sharpe_30d      REAL,
    win_rate_7d     REAL,
    win_rate_30d    REAL,
    profit_factor_7d REAL,
    max_drawdown    REAL,
    loss_streak     INTEGER,
    alerts          TEXT,                       -- JSON array of alert strings
    checked_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- BACKTEST_RESULTS: Backtest run history
-- ============================================
CREATE TABLE IF NOT EXISTS backtest_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    
    total_return    REAL,
    sharpe_ratio    REAL,
    sortino_ratio   REAL,
    max_drawdown    REAL,
    total_trades    INTEGER,
    win_rate        REAL,
    profit_factor   REAL,
    
    walk_forward    INTEGER DEFAULT 0,         -- 1 = walk-forward test
    wf_avg_test_sharpe REAL,
    wf_overfit_ratio REAL,
    wf_passed       INTEGER,
    
    passed          INTEGER,                   -- 1 = passed minimum thresholds
    params_json     TEXT,                       -- Strategy parameters (JSON)
    notes           TEXT,
    
    run_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- STRATEGY_RETIREMENTS: Retirement history
-- ============================================
CREATE TABLE IF NOT EXISTS strategy_retirements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT NOT NULL,
    action          TEXT NOT NULL,              -- 'WARN' | 'REDUCE' | 'PAUSE' | 'RETIRED'
    trigger_gate    TEXT NOT NULL,              -- Which gate triggered
    reason          TEXT NOT NULL,
    metrics_json    TEXT,                       -- Metrics at retirement
    grace_period_hours INTEGER,
    appealed        INTEGER DEFAULT 0,
    appeal_reason   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- CORRELATION snapshots
-- ============================================
CREATE TABLE IF NOT EXISTS strategy_correlations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_a      TEXT NOT NULL,
    strategy_b      TEXT NOT NULL,
    correlation     REAL NOT NULL,
    lookback_days   INTEGER NOT NULL,
    calculated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_allocations_strategy ON strategy_allocations(strategy_name);
CREATE INDEX IF NOT EXISTS idx_health_strategy ON strategy_health_log(strategy_name);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_name);
CREATE INDEX IF NOT EXISTS idx_retirements_strategy ON strategy_retirements(strategy_name);
```

---

## 10. Integration Points

### 10.1 With Risk Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Strategy allocation → Risk Guardian | Strategy → Risk | Per-strategy max position size |
| Retirement gate → Risk Guardian | Strategy → Risk | Strategy paused/retired status |
| Risk Guardian → Strategy Monitor | Risk → Strategy | Current drawdown, daily P&L |
| Walk-forward → Risk Guardian | Strategy → Risk | Backtest pass/fail before deployment |

### 10.2 With Execution Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Signal Aggregator → Execution Sniper | Strategy → Execution | Composite signal with allocation |
| Execution Tracker → Strategy Monitor | Execution → Strategy | Trade fills, P&L |
| Retirement Gate → Execution Tracker | Strategy → Execution | Close all positions command |

### 10.3 With Data Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Market data → Backtest Engine | Data → Strategy | Historical OHLCV |
| Regime Detector → Strategy Allocator | Data → Strategy | Current regime for allocation |
| Market data → Strategy Monitor | Data → Strategy | Real-time prices for P&L |

### 10.4 With Telegram

| Command | Handler | Description |
|---------|---------|-------------|
| `/strategies` | StrategyRegistry | List all strategies and their status |
| `/strategy <name>` | StrategyMonitor | Detailed health report for one strategy |
| `/backtest <name>` | BacktestEngine | Run backtest for a strategy |
| `/retire <name>` | RetirementGates | Manually retire a strategy |
| `/reactivate <name>` | StrategyRegistry | Reactivate retired strategy |
| `/allocations` | StrategyAllocator | Show current capital allocation |
| `/rebalance` | StrategyAllocator | Force rebalance |

---

*Strategy Layer specification complete. See PORTFOLIO_LAYER.md for multi-asset portfolio management.*
