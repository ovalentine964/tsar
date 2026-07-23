# PORTFOLIO LAYER — Complete Specification

**TSAR Trading Super Agent**
**Version:** 1.0.0 | **Date:** 2026-07-24
**Layer Coverage:** 15% → Target 100% specification

---

## Table of Contents

1. [Multi-Asset Portfolio](#1-multi-asset-portfolio)
2. [Portfolio Rebalancing](#2-portfolio-rebalancing)
3. [Performance Attribution](#3-performance-attribution)
4. [Benchmark Comparison](#4-benchmark-comparison)
5. [Portfolio Risk Metrics](#5-portfolio-risk-metrics)
6. [Day1 vs Full Implementation](#6-day1-vs-full-implementation)
7. [Database Schema Extensions](#7-database-schema-extensions)
8. [Integration Points](#8-integration-points)

---

## 1. Multi-Asset Portfolio

### 1.1 Purpose

Manage positions across multiple asset classes (crypto, forex, gold) as a unified portfolio. Each asset class has different characteristics — volatility, trading hours, correlation, liquidity — and the portfolio manager must account for all of them.

### 1.2 Asset Class Definitions

```python
# portfolio/asset_class.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class AssetClass(Enum):
    CRYPTO = "crypto"
    FOREX = "forex"
    GOLD = "gold"
    EQUITIES = "equities"       # Level 4+
    COMMODITIES = "commodities" # Level 4+

@dataclass
class AssetSpec:
    """Specification for a tradeable asset."""
    symbol: str                     # e.g., "BTC/USDT", "EUR/USD", "XAU/USD"
    asset_class: AssetClass
    exchange: str                   # e.g., "binance", "oanda"
    
    # Trading characteristics
    pip_value: float                # Minimum price movement
    lot_size: float                 # Standard lot size
    min_order_size: float           # Minimum order in base units
    max_leverage: float             # Maximum leverage available
    
    # Cost structure
    maker_fee_pct: float            # Maker fee percentage
    taker_fee_pct: float            # Taker fee percentage
    spread_typical_pips: float      # Typical spread in pips
    swap_long: float                # Overnight swap for long positions
    swap_short: float               # Overnight swap for short positions
    
    # Market hours (UTC)
    market_open: str = "00:00"      # Market open time (24h for crypto)
    market_close: str = "23:59"     # Market close time
    trading_days: list = field(default_factory=lambda: [0,1,2,3,4,5,6])  # 0=Mon, 6=Sun
    
    # Risk characteristics
    typical_daily_range_pct: float = 2.0    # Average daily range as % of price
    correlation_to_btc: float = 0.0         # Correlation to BTC
    liquidity_score: float = 1.0            # 0-1, 1 = most liquid


# Asset specifications
ASSET_SPECS = {
    # ── Crypto ──
    'BTC/USDT': AssetSpec(
        symbol='BTC/USDT', asset_class=AssetClass.CRYPTO, exchange='binance',
        pip_value=0.01, lot_size=0.001, min_order_size=0.0001, max_leverage=1.0,
        maker_fee_pct=0.1, taker_fee_pct=0.1, spread_typical_pips=5.0,
        swap_long=0.0, swap_short=0.0,
        market_open='00:00', market_close='23:59',
        typical_daily_range_pct=3.5, correlation_to_btc=1.0, liquidity_score=0.95
    ),
    'ETH/USDT': AssetSpec(
        symbol='ETH/USDT', asset_class=AssetClass.CRYPTO, exchange='binance',
        pip_value=0.01, lot_size=0.01, min_order_size=0.001, max_leverage=1.0,
        maker_fee_pct=0.1, taker_fee_pct=0.1, spread_typical_pips=3.0,
        swap_long=0.0, swap_short=0.0,
        market_open='00:00', market_close='23:59',
        typical_daily_range_pct=4.0, correlation_to_btc=0.85, liquidity_score=0.90
    ),
    
    # ── Forex ──
    'EUR/USD': AssetSpec(
        symbol='EUR/USD', asset_class=AssetClass.FOREX, exchange='oanda',
        pip_value=0.0001, lot_size=100000, min_order_size=1000, max_leverage=50.0,
        maker_fee_pct=0.0, taker_fee_pct=0.0, spread_typical_pips=1.2,
        swap_long=-0.5, swap_short=0.3,
        market_open='22:00', market_close='22:00',  # 24h forex (Sun-Fri)
        trading_days=[0,1,2,3,4],
        typical_daily_range_pct=0.6, correlation_to_btc=0.15, liquidity_score=1.0
    ),
    'GBP/USD': AssetSpec(
        symbol='GBP/USD', asset_class=AssetClass.FOREX, exchange='oanda',
        pip_value=0.0001, lot_size=100000, min_order_size=1000, max_leverage=50.0,
        maker_fee_pct=0.0, taker_fee_pct=0.0, spread_typical_pips=1.5,
        swap_long=-0.4, swap_short=0.2,
        market_open='22:00', market_close='22:00',
        trading_days=[0,1,2,3,4],
        typical_daily_range_pct=0.7, correlation_to_btc=0.10, liquidity_score=0.95
    ),
    'USD/JPY': AssetSpec(
        symbol='USD/JPY', asset_class=AssetClass.FOREX, exchange='oanda',
        pip_value=0.01, lot_size=100000, min_order_size=1000, max_leverage=50.0,
        maker_fee_pct=0.0, taker_fee_pct=0.0, spread_typical_pips=1.0,
        swap_long=0.2, swap_short=-0.6,
        market_open='22:00', market_close='22:00',
        trading_days=[0,1,2,3,4],
        typical_daily_range_pct=0.5, correlation_to_btc=-0.20, liquidity_score=1.0
    ),
    
    # ── Gold ──
    'XAU/USD': AssetSpec(
        symbol='XAU/USD', asset_class=AssetClass.GOLD, exchange='oanda',
        pip_value=0.01, lot_size=100, min_order_size=1, max_leverage=20.0,
        maker_fee_pct=0.0, taker_fee_pct=0.0, spread_typical_pips=3.0,
        swap_long=-1.5, swap_short=0.5,
        market_open='22:00', market_close='22:00',
        trading_days=[0,1,2,3,4],
        typical_daily_range_pct=1.0, correlation_to_btc=0.25, liquidity_score=0.90
    ),
}
```

### 1.3 Multi-Asset Portfolio Manager

```python
# portfolio/portfolio_manager.py

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Position:
    """A single position in the portfolio."""
    symbol: str
    side: str                    # 'long' | 'short'
    quantity: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    strategy: str                # Which strategy opened this
    
    # Computed
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    value_usd: float = 0.0
    risk_usd: float = 0.0
    hold_duration_hours: float = 0.0
    
    # Metadata
    opened_at: datetime = field(default_factory=datetime.now)
    exchange_order_id: str = ""
    asset_class: str = ""


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state."""
    timestamp: datetime
    total_equity: float
    cash: float
    
    # By asset class
    crypto_value: float = 0.0
    forex_value: float = 0.0
    gold_value: float = 0.0
    
    # Positions
    positions: list = field(default_factory=list)
    total_positions: int = 0
    
    # Risk
    total_exposure_usd: float = 0.0
    net_exposure_usd: float = 0.0
    gross_exposure_usd: float = 0.0
    portfolio_heat: float = 0.0     # Total open risk as % of equity
    
    # Performance
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    ytd_pnl: float = 0.0


class PortfolioManager:
    """
    Unified portfolio manager across all asset classes.
    Single source of truth for portfolio state.
    """
    
    def __init__(self, db_path: str = 'data/tsar.db'):
        self.db_path = db_path
        self._positions: dict[str, Position] = {}
        self._target_allocations: dict[str, float] = {}  # asset_class -> target %
    
    def add_position(self, position: Position) -> None:
        """Add a new position to the portfolio."""
        key = f"{position.symbol}_{position.side}_{position.strategy}"
        self._positions[key] = position
        self._persist_position(position)
    
    def close_position(self, symbol: str, side: str, strategy: str, 
                       exit_price: float, exit_reason: str) -> dict:
        """Close a position and calculate final P&L."""
        key = f"{symbol}_{side}_{strategy}"
        pos = self._positions.get(key)
        if not pos:
            return {'error': 'Position not found'}
        
        # Calculate P&L
        if pos.side == 'long':
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity
        
        pnl_pct = pnl / (pos.entry_price * pos.quantity) * 100
        
        # Update database
        self._close_position_db(key, exit_price, pnl, pnl_pct, exit_reason)
        
        # Remove from active positions
        del self._positions[key]
        
        return {
            'symbol': symbol,
            'side': side,
            'strategy': strategy,
            'entry_price': pos.entry_price,
            'exit_price': exit_price,
            'quantity': pos.quantity,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'hold_duration_hours': (datetime.now() - pos.opened_at).total_seconds() / 3600,
            'exit_reason': exit_reason
        }
    
    def update_prices(self, prices: dict[str, float]) -> None:
        """Update current prices for all positions."""
        for key, pos in self._positions.items():
            if pos.symbol in prices:
                pos.current_price = prices[pos.symbol]
                
                if pos.side == 'long':
                    pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.quantity
                else:
                    pos.unrealized_pnl = (pos.entry_price - pos.current_price) * pos.quantity
                
                pos.unrealized_pnl_pct = pos.unrealized_pnl / (pos.entry_price * pos.quantity) * 100
                pos.value_usd = pos.current_price * pos.quantity
                
                # Risk = distance to stop-loss
                if pos.stop_loss > 0:
                    if pos.side == 'long':
                        pos.risk_usd = (pos.entry_price - pos.stop_loss) * pos.quantity
                    else:
                        pos.risk_usd = (pos.stop_loss - pos.entry_price) * pos.quantity
    
    def get_snapshot(self, balance: float) -> PortfolioSnapshot:
        """Get current portfolio snapshot."""
        now = datetime.now()
        
        positions = list(self._positions.values())
        
        crypto_value = sum(p.value_usd for p in positions if ASSET_SPECS.get(p.symbol, AssetSpec('', AssetClass.CRYPTO, '')).asset_class == AssetClass.CRYPTO)
        forex_value = sum(p.value_usd for p in positions if ASSET_SPECS.get(p.symbol, AssetSpec('', AssetClass.FOREX, '')).asset_class == AssetClass.FOREX)
        gold_value = sum(p.value_usd for p in positions if ASSET_SPECS.get(p.symbol, AssetSpec('', AssetClass.GOLD, '')).asset_class == AssetClass.GOLD)
        
        total_exposure = sum(p.value_usd for p in positions)
        long_exposure = sum(p.value_usd for p in positions if p.side == 'long')
        short_exposure = sum(p.value_usd for p in positions if p.side == 'short')
        total_risk = sum(p.risk_usd for p in positions)
        
        return PortfolioSnapshot(
            timestamp=now,
            total_equity=balance + sum(p.unrealized_pnl for p in positions),
            cash=balance,
            crypto_value=crypto_value,
            forex_value=forex_value,
            gold_value=gold_value,
            positions=positions,
            total_positions=len(positions),
            total_exposure_usd=total_exposure,
            net_exposure_usd=long_exposure - short_exposure,
            gross_exposure_usd=long_exposure + short_exposure,
            portfolio_heat=total_risk / balance * 100 if balance > 0 else 0,
            daily_pnl=self._calc_period_pnl(1),
            weekly_pnl=self._calc_period_pnl(7),
            monthly_pnl=self._calc_period_pnl(30),
            ytd_pnl=self._calc_ytd_pnl()
        )
    
    def get_positions_by_asset_class(self) -> dict[str, list[Position]]:
        """Group positions by asset class."""
        result = {}
        for pos in self._positions.values():
            spec = ASSET_SPECS.get(pos.symbol)
            ac = spec.asset_class.value if spec else 'unknown'
            if ac not in result:
                result[ac] = []
            result[ac].append(pos)
        return result
    
    def get_positions_by_strategy(self) -> dict[str, list[Position]]:
        """Group positions by strategy."""
        result = {}
        for pos in self._positions.values():
            if pos.strategy not in result:
                result[pos.strategy] = []
            result[pos.strategy].append(pos)
        return result
    
    def _persist_position(self, pos: Position):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO portfolio_positions 
            (symbol, side, quantity, entry_price, stop_loss, take_profit, 
             strategy, asset_class, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pos.symbol, pos.side, pos.quantity, pos.entry_price,
              pos.stop_loss, pos.take_profit, pos.strategy, 
              pos.asset_class, pos.opened_at))
        conn.commit()
        conn.close()
    
    def _close_position_db(self, key: str, exit_price: float, 
                           pnl: float, pnl_pct: float, exit_reason: str):
        # Update trades table (existing schema)
        pass
    
    def _calc_period_pnl(self, days: int) -> float:
        conn = sqlite3.connect(self.db_path)
        cutoff = datetime.now() - timedelta(days=days)
        result = conn.execute(
            "SELECT SUM(pnl) FROM trades WHERE closed_at >= ?", (cutoff,)
        ).fetchone()
        conn.close()
        return result[0] or 0.0
    
    def _calc_ytd_pnl(self) -> float:
        conn = sqlite3.connect(self.db_path)
        year_start = datetime(datetime.now().year, 1, 1)
        result = conn.execute(
            "SELECT SUM(pnl) FROM trades WHERE closed_at >= ?", (year_start,)
        ).fetchone()
        conn.close()
        return result[0] or 0.0
```

### 1.4 Cross-Asset Correlation Matrix

```python
# portfolio/cross_asset_correlation.py

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class CrossAssetCorrelation:
    """
    Tracks correlation between different assets and asset classes.
    Critical for portfolio diversification and risk management.
    """
    
    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days
        self._price_history: dict[str, list[tuple[datetime, float]]] = {}
    
    def record_price(self, symbol: str, timestamp: datetime, price: float):
        """Record a price observation."""
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        self._price_history[symbol].append((timestamp, price))
    
    def get_correlation_matrix(self) -> pd.DataFrame:
        """
        Calculate pairwise return correlation between all tracked assets.
        Uses daily returns to avoid intraday noise.
        """
        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        
        # Build daily returns for each asset
        asset_returns = {}
        for symbol, prices in self._price_history.items():
            recent = [(ts, p) for ts, p in prices if ts >= cutoff]
            if len(recent) < 10:
                continue
            
            df = pd.DataFrame(recent, columns=['timestamp', 'price'])
            df['date'] = df['timestamp'].dt.date
            daily = df.groupby('date')['price'].last()
            returns = daily.pct_change().dropna()
            asset_returns[symbol] = returns
        
        if len(asset_returns) < 2:
            return pd.DataFrame()
        
        returns_df = pd.DataFrame(asset_returns)
        return returns_df.corr()
    
    def get_asset_class_correlation(self) -> dict[str, float]:
        """
        Get average correlation between asset classes.
        Returns dict like: {'crypto_forex': 0.15, 'crypto_gold': 0.25, 'forex_gold': -0.10}
        """
        matrix = self.get_correlation_matrix()
        if matrix.empty:
            return {}
        
        # Group symbols by asset class
        class_members = {}
        for symbol in matrix.index:
            spec = ASSET_SPECS.get(symbol)
            if spec:
                ac = spec.asset_class.value
                if ac not in class_members:
                    class_members[ac] = []
                class_members[ac].append(symbol)
        
        # Calculate inter-class correlations
        result = {}
        classes = list(class_members.keys())
        for i, class_a in enumerate(classes):
            for j, class_b in enumerate(classes):
                if i >= j:
                    continue
                
                correlations = []
                for sym_a in class_members[class_a]:
                    for sym_b in class_members[class_b]:
                        if sym_a in matrix.index and sym_b in matrix.columns:
                            correlations.append(matrix.loc[sym_a, sym_b])
                
                if correlations:
                    result[f"{class_a}_{class_b}"] = np.mean(correlations)
        
        return result
    
    def is_diversified(self, threshold: float = 0.7) -> bool:
        """
        Check if portfolio is sufficiently diversified.
        Returns False if any two positions have correlation > threshold.
        """
        matrix = self.get_correlation_matrix()
        if matrix.empty:
            return True
        
        # Check all pairs
        for i in range(len(matrix)):
            for j in range(i + 1, len(matrix)):
                if abs(matrix.iloc[i, j]) > threshold:
                    return False
        
        return True
    
    def get_most_correlated_pair(self) -> tuple[str, str, float]:
        """Find the most correlated pair of assets."""
        matrix = self.get_correlation_matrix()
        if matrix.empty:
            return None, None, 0.0
        
        max_corr = 0
        pair = (None, None)
        
        for i in range(len(matrix)):
            for j in range(i + 1, len(matrix)):
                corr = abs(matrix.iloc[i, j])
                if corr > max_corr:
                    max_corr = corr
                    pair = (matrix.index[i], matrix.columns[j])
        
        return pair[0], pair[1], max_corr
```

### 1.5 Exchange Integration Layer

```python
# portfolio/exchange_manager.py

from abc import ABC, abstractmethod
from dataclasses import dataclass

class ExchangeAdapter(ABC):
    """Abstract base for exchange adapters."""
    
    @abstractmethod
    def get_price(self, symbol: str) -> float:
        pass
    
    @abstractmethod
    def get_balance(self) -> dict:
        pass
    
    @abstractmethod
    def place_order(self, symbol: str, side: str, quantity: float, 
                    order_type: str, price: float = None) -> dict:
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        pass
    
    @abstractmethod
    def get_positions(self) -> list:
        pass


class BinanceAdapter(ExchangeAdapter):
    """Binance spot exchange adapter."""
    
    def __init__(self, config: dict):
        import ccxt
        self.exchange = ccxt.binance(config)
    
    def get_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        return ticker['last']
    
    def get_balance(self) -> dict:
        bal = self.exchange.fetch_balance()
        return {
            'total_usd': bal['total'].get('USDT', 0),
            'free_usd': bal['free'].get('USDT', 0),
            'positions': self.get_positions()
        }
    
    def place_order(self, symbol, side, quantity, order_type='market', price=None):
        order = self.exchange.create_order(symbol, order_type, side, quantity, price)
        return {
            'order_id': order['id'],
            'symbol': order['symbol'],
            'side': order['side'],
            'price': order.get('average', order.get('price')),
            'quantity': order['amount'],
            'status': order['status']
        }
    
    def cancel_order(self, order_id, symbol):
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception:
            return False
    
    def get_positions(self):
        balance = self.exchange.fetch_balance()
        positions = []
        for currency, amount in balance['total'].items():
            if amount and amount > 0 and currency not in ['USDT', 'USD']:
                positions.append({
                    'symbol': f"{currency}/USDT",
                    'quantity': amount,
                    'value_usd': amount * self.get_price(f"{currency}/USDT")
                })
        return positions


class OandaAdapter(ExchangeAdapter):
    """OANDA forex/gold exchange adapter."""
    
    def __init__(self, config: dict):
        self.api_key = config['api_key']
        self.account_id = config['account_id']
        self.base_url = config.get('base_url', 'https://api-fxpractice.oanda.com')
    
    def get_price(self, symbol: str) -> float:
        """Fetch current price from OANDA."""
        import requests
        oanda_symbol = self._to_oanda_symbol(symbol)
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.get(
            f"{self.base_url}/v3/accounts/{self.account_id}/pricing",
            headers=headers,
            params={'instruments': oanda_symbol}
        )
        data = response.json()
        if 'prices' in data and data['prices']:
            return float(data['prices'][0]['bids'][0]['price'])
        return 0.0
    
    def get_balance(self) -> dict:
        import requests
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.get(
            f"{self.base_url}/v3/accounts/{self.account_id}/summary",
            headers=headers
        )
        data = response.json()
        account = data.get('account', {})
        return {
            'total_usd': float(account.get('balance', 0)),
            'free_usd': float(account.get('marginAvailable', 0)),
            'positions': self.get_positions()
        }
    
    def place_order(self, symbol, side, quantity, order_type='market', price=None):
        import requests
        oanda_symbol = self._to_oanda_symbol(symbol)
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        order_body = {
            'order': {
                'type': 'MARKET' if order_type == 'market' else 'LIMIT',
                'instrument': oanda_symbol,
                'units': str(int(quantity) if side == 'buy' else -int(quantity)),
                'timeInForce': 'FOK' if order_type == 'market' else 'GTC',
            }
        }
        
        if price and order_type == 'limit':
            order_body['order']['price'] = str(price)
        
        response = requests.post(
            f"{self.base_url}/v3/accounts/{self.account_id}/orders",
            headers=headers,
            json=order_body
        )
        data = response.json()
        
        if 'orderFillTransaction' in data:
            fill = data['orderFillTransaction']
            return {
                'order_id': fill.get('orderID', ''),
                'symbol': symbol,
                'side': side,
                'price': float(fill.get('price', 0)),
                'quantity': abs(float(fill.get('units', 0))),
                'status': 'FILLED'
            }
        
        return {'error': data.get('errorMessage', 'Unknown error')}
    
    def cancel_order(self, order_id, symbol):
        import requests
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.put(
            f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel",
            headers=headers
        )
        return response.status_code == 200
    
    def get_positions(self):
        import requests
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.get(
            f"{self.base_url}/v3/accounts/{self.account_id}/openTrades",
            headers=headers
        )
        data = response.json()
        positions = []
        for trade in data.get('trades', []):
            positions.append({
                'symbol': self._from_oanda_symbol(trade['instrument']),
                'quantity': abs(float(trade['currentUnits'])),
                'side': 'long' if float(trade['currentUnits']) > 0 else 'short',
                'unrealized_pnl': float(trade.get('unrealizedPL', 0))
            })
        return positions
    
    def _to_oanda_symbol(self, symbol: str) -> str:
        """Convert 'EUR/USD' to OANDA format 'EUR_USD'."""
        return symbol.replace('/', '_')
    
    def _from_oanda_symbol(self, oanda_symbol: str) -> str:
        """Convert 'EUR_USD' to standard format 'EUR/USD'."""
        return oanda_symbol.replace('_', '/')


class ExchangeManager:
    """
    Unified exchange manager.
    Routes orders to the correct exchange based on asset class.
    """
    
    def __init__(self):
        self._adapters: dict[str, ExchangeAdapter] = {}
    
    def register(self, name: str, adapter: ExchangeAdapter):
        self._adapters[name] = adapter
    
    def get_adapter(self, symbol: str) -> ExchangeAdapter:
        """Get the correct adapter for a symbol."""
        spec = ASSET_SPECS.get(symbol)
        if spec:
            return self._adapters.get(spec.exchange)
        # Default to binance for crypto
        return self._adapters.get('binance')
    
    def get_price(self, symbol: str) -> float:
        adapter = self.get_adapter(symbol)
        if adapter:
            return adapter.get_price(symbol)
        return 0.0
    
    def place_order(self, symbol: str, side: str, quantity: float,
                    order_type: str = 'market', price: float = None) -> dict:
        adapter = self.get_adapter(symbol)
        if adapter:
            return adapter.place_order(symbol, side, quantity, order_type, price)
        return {'error': f'No adapter for {symbol}'}
    
    def get_all_balances(self) -> dict:
        """Get combined balance across all exchanges."""
        total = 0
        balances = {}
        for name, adapter in self._adapters.items():
            bal = adapter.get_balance()
            balances[name] = bal
            total += bal.get('total_usd', 0)
        return {'total_usd': total, 'by_exchange': balances}
```

---

## 2. Portfolio Rebalancing

### 2.1 Purpose

Automatic portfolio rebalancing maintains target allocations as positions drift with market movements. Without rebalancing, winners become oversized and losers shrink — concentrating risk in what's already worked (and may reverse).

### 2.2 Rebalancing Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    REBALANCING ENGINE                                    │
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐               │
│  │  Target      │──▶│  Drift       │──▶│  Rebalance   │               │
│  │  Allocator   │   │  Detector    │   │  Executor    │               │
│  └──────────────┘   └──────────────┘   └──────────────┘               │
│         │                  │                     │                      │
│         ▼                  ▼                     ▼                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐               │
│  │  Current     │   │  Threshold   │   │  Order       │               │
│  │  Portfolio   │   │  Config      │   │  Generator   │               │
│  └──────────────┘   └──────────────┘   └──────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Rebalancing Specification

```python
# portfolio/rebalancer.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

class RebalanceReason(Enum):
    SCHEDULED = "scheduled"         # Time-based rebalance
    DRIFT = "drift"                 # Allocation drifted beyond threshold
    REGIME_CHANGE = "regime_change" # Market regime changed
    STRATEGY_CHANGE = "strategy_change" # Strategy added/removed/retired
    DRAWDOWN = "drawdown"          # Portfolio drawdown triggered rebalance
    MANUAL = "manual"              # User-triggered

@dataclass
class RebalanceOrder:
    """An order needed to rebalance the portfolio."""
    symbol: str
    side: str                       # 'buy' | 'sell'
    quantity: float
    current_weight: float           # Current % of portfolio
    target_weight: float            # Target % of portfolio
    drift: float                    # |current - target|
    reason: str

@dataclass
class RebalanceResult:
    """Result of a rebalance check/execution."""
    timestamp: datetime
    reason: RebalanceReason
    needed: bool                    # Whether rebalancing is needed
    orders: list[RebalanceOrder]
    estimated_cost_usd: float       # Estimated trading costs
    max_drift: float                # Largest drift before rebalance
    portfolio_before: dict          # Current allocations
    portfolio_after: dict           # Target allocations


class Rebalancer:
    """
    Portfolio rebalancing engine.
    
    Triggers:
    1. Scheduled: Weekly (configurable)
    2. Drift: Any asset class drifts >5% from target
    3. Regime: Regime change with >70% confidence
    4. Strategy: Strategy added/removed/retired
    5. Drawdown: Portfolio drawdown >10%
    """
    
    # Default configuration
    CONFIG = {
        'schedule': {
            'frequency': 'weekly',
            'day': 'sunday',
            'hour': 0,  # UTC
        },
        'drift_threshold_pct': 5.0,      # Rebalance if any allocation drifts >5%
        'min_trade_usd': 10.0,           # Don't trade less than $10
        'max_slippage_pct': 0.5,         # Abort if slippage > 0.5%
        'regime_confidence_min': 0.7,    # Only rebalance on regime change if confident
        'drawdown_trigger_pct': 10.0,    # Rebalance if portfolio DD > 10%
        'cooldown_hours': 24,            # Min time between rebalances
    }
    
    def __init__(self, portfolio_manager, strategy_allocator, exchange_manager):
        self.portfolio = portfolio_manager
        self.allocator = strategy_allocator
        self.exchange = exchange_manager
        self._last_rebalance: Optional[datetime] = None
    
    def check(self, reason: RebalanceReason, 
              current_regime: str = None,
              balance: float = 0) -> RebalanceResult:
        """
        Check if rebalancing is needed and generate orders.
        Does NOT execute — returns orders for approval.
        """
        now = datetime.now()
        
        # Cooldown check
        if self._last_rebalance:
            hours_since = (now - self._last_rebalance).total_seconds() / 3600
            if hours_since < self.CONFIG['cooldown_hours'] and reason != RebalanceReason.MANUAL:
                return RebalanceResult(
                    timestamp=now, reason=reason, needed=False, orders=[],
                    estimated_cost_usd=0, max_drift=0, portfolio_before={}, portfolio_after={}
                )
        
        # Get current portfolio state
        snapshot = self.portfolio.get_snapshot(balance)
        current_allocations = self._calc_current_allocations(snapshot)
        
        # Get target allocations
        target_allocations = self._get_target_allocations(current_regime, balance)
        
        # Calculate drift
        drift = {}
        for asset_class, target in target_allocations.items():
            current = current_allocations.get(asset_class, 0.0)
            drift[asset_class] = abs(current - target)
        
        max_drift = max(drift.values()) if drift else 0
        needed = max_drift > self.CONFIG['drift_threshold_pct'] / 100
        
        if not needed:
            return RebalanceResult(
                timestamp=now, reason=reason, needed=False, orders=[],
                estimated_cost_usd=0, max_drift=max_drift,
                portfolio_before=current_allocations,
                portfolio_after=target_allocations
            )
        
        # Generate rebalance orders
        orders = self._generate_orders(snapshot, current_allocations, 
                                        target_allocations, balance)
        
        # Estimate costs
        estimated_cost = sum(
            self._estimate_trade_cost(o) for o in orders
        )
        
        return RebalanceResult(
            timestamp=now, reason=reason, needed=True, orders=orders,
            estimated_cost_usd=estimated_cost, max_drift=max_drift,
            portfolio_before=current_allocations,
            portfolio_after=target_allocations
        )
    
    def execute(self, result: RebalanceResult) -> list[dict]:
        """
        Execute rebalance orders.
        Returns list of execution results.
        """
        if not result.needed:
            return []
        
        executions = []
        for order in result.orders:
            if order.quantity * self.exchange.get_price(order.symbol) < self.CONFIG['min_trade_usd']:
                continue  # Skip tiny trades
            
            exec_result = self.exchange.place_order(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                order_type='market'
            )
            executions.append(exec_result)
        
        self._last_rebalance = datetime.now()
        
        # Log rebalance
        self._log_rebalance(result, executions)
        
        return executions
    
    def _calc_current_allocations(self, snapshot) -> dict[str, float]:
        """Calculate current allocation percentages by asset class."""
        total = snapshot.total_equity
        if total <= 0:
            return {}
        
        return {
            'crypto': snapshot.crypto_value / total,
            'forex': snapshot.forex_value / total,
            'gold': snapshot.gold_value / total,
            'cash': snapshot.cash / total,
        }
    
    def _get_target_allocations(self, current_regime: str, balance: float) -> dict[str, float]:
        """
        Get target allocations based on regime and balance size.
        
        Default allocation (Level 4):
        - Crypto: 60% (primary market)
        - Forex: 25% (diversification)
        - Gold: 10% (safe haven)
        - Cash: 5% (dry powder)
        
        Regime adjustments:
        - Risk-on: Crypto 70%, Forex 20%, Gold 5%, Cash 5%
        - Risk-off: Crypto 30%, Forex 30%, Gold 30%, Cash 10%
        - High volatility: Crypto 40%, Forex 25%, Gold 25%, Cash 10%
        """
        # Base allocation
        targets = {
            'crypto': 0.60,
            'forex': 0.25,
            'gold': 0.10,
            'cash': 0.05,
        }
        
        # Regime adjustments
        if current_regime == 'risk_off' or current_regime == 'trending_down':
            targets = {
                'crypto': 0.30,
                'forex': 0.30,
                'gold': 0.30,
                'cash': 0.10,
            }
        elif current_regime == 'volatile':
            targets = {
                'crypto': 0.40,
                'forex': 0.25,
                'gold': 0.25,
                'cash': 0.10,
            }
        elif current_regime == 'trending_up' or current_regime == 'risk_on':
            targets = {
                'crypto': 0.70,
                'forex': 0.20,
                'gold': 0.05,
                'cash': 0.05,
            }
        
        # Small account adjustment — crypto only for <$500
        if balance < 500:
            targets = {
                'crypto': 0.90,
                'forex': 0.0,
                'gold': 0.0,
                'cash': 0.10,
            }
        
        return targets
    
    def _generate_orders(self, snapshot, current: dict, target: dict, 
                         balance: float) -> list[RebalanceOrder]:
        """Generate orders to move from current to target allocation."""
        orders = []
        
        for asset_class, target_pct in target.items():
            current_pct = current.get(asset_class, 0.0)
            drift = target_pct - current_pct
            
            if abs(drift) < self.CONFIG['drift_threshold_pct'] / 100:
                continue
            
            # Determine direction and amount
            if drift > 0:
                # Need to BUY more of this asset class
                usd_to_buy = drift * balance
                # Find best asset in this class to buy
                symbol = self._select_asset_for_class(asset_class, 'buy')
                if symbol:
                    price = self.exchange.get_price(symbol)
                    if price > 0:
                        quantity = usd_to_buy / price
                        orders.append(RebalanceOrder(
                            symbol=symbol, side='buy', quantity=quantity,
                            current_weight=current_pct, target_weight=target_pct,
                            drift=abs(drift), reason=f"Rebalance {asset_class}: {current_pct:.1%} → {target_pct:.1%}"
                        ))
            else:
                # Need to SELL some of this asset class
                usd_to_sell = abs(drift) * balance
                symbol = self._select_asset_for_class(asset_class, 'sell')
                if symbol:
                    price = self.exchange.get_price(symbol)
                    if price > 0:
                        quantity = usd_to_sell / price
                        orders.append(RebalanceOrder(
                            symbol=symbol, side='sell', quantity=quantity,
                            current_weight=current_pct, target_weight=target_pct,
                            drift=abs(drift), reason=f"Rebalance {asset_class}: {current_pct:.1%} → {target_pct:.1%}"
                        ))
        
        return orders
    
    def _select_asset_for_class(self, asset_class: str, side: str) -> Optional[str]:
        """Select the best asset to trade for a given asset class."""
        # Default selections
        defaults = {
            'crypto': 'BTC/USDT',
            'forex': 'EUR/USD',
            'gold': 'XAU/USD',
        }
        
        # If selling, prefer the asset we have the most of
        if side == 'sell':
            positions = self.portfolio.get_positions_by_asset_class().get(asset_class, [])
            if positions:
                # Sell the largest position
                largest = max(positions, key=lambda p: p.value_usd)
                return largest.symbol
        
        return defaults.get(asset_class)
    
    def _estimate_trade_cost(self, order: RebalanceOrder) -> float:
        """Estimate trading cost for an order."""
        spec = ASSET_SPECS.get(order.symbol)
        if not spec:
            return 0.0
        
        trade_value = order.quantity * self.exchange.get_price(order.symbol)
        fee = trade_value * spec.taker_fee_pct / 100
        spread_cost = trade_value * spec.spread_typical_pips * spec.pip_value / self.exchange.get_price(order.symbol)
        
        return fee + spread_cost
    
    def _log_rebalance(self, result: RebalanceResult, executions: list):
        """Log rebalance to database."""
        import sqlite3, json
        conn = sqlite3.connect('data/tsar.db')
        conn.execute("""
            INSERT INTO rebalance_log 
            (reason, orders_json, executions_json, max_drift, estimated_cost, executed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            result.reason.value,
            json.dumps([o.__dict__ for o in result.orders]),
            json.dumps(executions),
            result.max_drift,
            result.estimated_cost_usd,
            datetime.now()
        ))
        conn.commit()
        conn.close()
```

### 2.4 Rebalancing Telegram Notifications

```
⚖️ PORTFOLIO REBALANCE
━━━━━━━━━━━━━━━━━━━━━━
Reason: Drift detected
Max drift: 7.2% (crypto overweight)

Orders:
  🟢 BUY  0.0015 BTC/USDT  ($100)  → Crypto 60%
  🔴 SELL 0.12 XAU/USD     ($25)   → Gold 10%
  
Estimated cost: $0.15
━━━━━━━━━━━━━━━━━━━━━━
Approve? /approve_rebalance or /cancel
```

---

## 3. Performance Attribution

### 3.1 Purpose

Understand WHAT is making/losing money and WHY. Without attribution, you're flying blind — you don't know if profits come from skill or luck, from one strategy or many, from one asset or diversified.

### 3.2 Attribution Dimensions

```python
# portfolio/attribution.py

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field

@dataclass
class AttributionResult:
    """Multi-dimensional performance attribution."""
    period: str                     # 'daily' | 'weekly' | 'monthly'
    start_date: str
    end_date: str
    total_pnl: float
    total_pnl_pct: float
    
    # By strategy
    by_strategy: dict = field(default_factory=dict)
    # {'mean_reversion': {'pnl': 15.2, 'pnl_pct': 1.5, 'trades': 12, 'contribution_pct': 45.2}}
    
    # By asset
    by_asset: dict = field(default_factory=dict)
    # {'BTC/USDT': {'pnl': 20.5, 'pnl_pct': 2.0, 'trades': 15}}
    
    # By asset class
    by_asset_class: dict = field(default_factory=dict)
    # {'crypto': {'pnl': 25.0, 'contribution_pct': 74.3}}
    
    # By regime
    by_regime: dict = field(default_factory=dict)
    # {'trending_up': {'pnl': 30.0, 'trades': 20, 'win_rate': 0.65}}
    
    # By time
    by_hour: dict = field(default_factory=dict)
    by_day_of_week: dict = field(default_factory=dict)
    
    # By exit reason
    by_exit_reason: dict = field(default_factory=dict)
    # {'tp_hit': {'count': 8, 'pnl': 25.0}, 'sl_hit': {'count': 5, 'pnl': -12.0}}
    
    # Top/bottom trades
    top_trades: list = field(default_factory=list)
    bottom_trades: list = field(default_factory=list)


class PerformanceAttributor:
    """
    Calculates multi-dimensional performance attribution.
    Answers: What's making money? What's losing money? Why?
    """
    
    def __init__(self, db_path: str = 'data/tsar.db'):
        self.db_path = db_path
    
    def attribute(self, start_date: str, end_date: str) -> AttributionResult:
        """Calculate full attribution for a period."""
        trades = self._load_trades(start_date, end_date)
        
        if not trades:
            return AttributionResult(
                period='custom', start_date=start_date, end_date=end_date,
                total_pnl=0, total_pnl_pct=0
            )
        
        total_pnl = sum(t['pnl'] for t in trades)
        total_pnl_pct = sum(t['pnl_pct'] for t in trades)
        
        result = AttributionResult(
            period='custom',
            start_date=start_date,
            end_date=end_date,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            by_strategy=self._attribute_by_strategy(trades, total_pnl),
            by_asset=self._attribute_by_asset(trades),
            by_asset_class=self._attribute_by_asset_class(trades, total_pnl),
            by_regime=self._attribute_by_regime(trades),
            by_hour=self._attribute_by_hour(trades),
            by_day_of_week=self._attribute_by_day_of_week(trades),
            by_exit_reason=self._attribute_by_exit_reason(trades),
            top_trades=sorted(trades, key=lambda t: t['pnl'], reverse=True)[:5],
            bottom_trades=sorted(trades, key=lambda t: t['pnl'])[:5]
        )
        
        return result
    
    def _load_trades(self, start: str, end: str) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT * FROM trades 
            WHERE closed_at BETWEEN ? AND ?
            AND status = 'CLOSED'
            ORDER BY closed_at
        """, (start, end))
        
        columns = [desc[0] for desc in cursor.description]
        trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return trades
    
    def _attribute_by_strategy(self, trades: list, total_pnl: float) -> dict:
        result = {}
        for t in trades:
            s = t.get('strategy', 'unknown')
            if s not in result:
                result[s] = {'pnl': 0, 'pnl_pct': 0, 'trades': 0, 'wins': 0}
            result[s]['pnl'] += t.get('pnl', 0)
            result[s]['pnl_pct'] += t.get('pnl_pct', 0)
            result[s]['trades'] += 1
            if t.get('pnl', 0) > 0:
                result[s]['wins'] += 1
        
        # Calculate contribution percentage
        for s in result:
            result[s]['win_rate'] = result[s]['wins'] / result[s]['trades'] if result[s]['trades'] > 0 else 0
            result[s]['contribution_pct'] = (result[s]['pnl'] / total_pnl * 100) if total_pnl != 0 else 0
        
        return result
    
    def _attribute_by_asset(self, trades: list) -> dict:
        result = {}
        for t in trades:
            a = t.get('symbol', 'unknown')
            if a not in result:
                result[a] = {'pnl': 0, 'pnl_pct': 0, 'trades': 0, 'wins': 0}
            result[a]['pnl'] += t.get('pnl', 0)
            result[a]['pnl_pct'] += t.get('pnl_pct', 0)
            result[a]['trades'] += 1
            if t.get('pnl', 0) > 0:
                result[a]['wins'] += 1
        
        for a in result:
            result[a]['win_rate'] = result[a]['wins'] / result[a]['trades'] if result[a]['trades'] > 0 else 0
        
        return result
    
    def _attribute_by_asset_class(self, trades: list, total_pnl: float) -> dict:
        result = {}
        for t in trades:
            spec = ASSET_SPECS.get(t.get('symbol'))
            ac = spec.asset_class.value if spec else 'unknown'
            if ac not in result:
                result[ac] = {'pnl': 0, 'trades': 0}
            result[ac]['pnl'] += t.get('pnl', 0)
            result[ac]['trades'] += 1
        
        for ac in result:
            result[ac]['contribution_pct'] = (result[ac]['pnl'] / total_pnl * 100) if total_pnl != 0 else 0
        
        return result
    
    def _attribute_by_regime(self, trades: list) -> dict:
        result = {}
        for t in trades:
            r = t.get('regime_at_entry', 'unknown')
            if r not in result:
                result[r] = {'pnl': 0, 'trades': 0, 'wins': 0}
            result[r]['pnl'] += t.get('pnl', 0)
            result[r]['trades'] += 1
            if t.get('pnl', 0) > 0:
                result[r]['wins'] += 1
        
        for r in result:
            result[r]['win_rate'] = result[r]['wins'] / result[r]['trades'] if result[r]['trades'] > 0 else 0
        
        return result
    
    def _attribute_by_hour(self, trades: list) -> dict:
        result = {}
        for t in trades:
            ts = t.get('opened_at')
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            hour = ts.hour if isinstance(ts, datetime) else 0
            
            if hour not in result:
                result[hour] = {'pnl': 0, 'trades': 0}
            result[hour]['pnl'] += t.get('pnl', 0)
            result[hour]['trades'] += 1
        
        return dict(sorted(result.items()))
    
    def _attribute_by_day_of_week(self, trades: list) -> dict:
        days = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
        result = {}
        for t in trades:
            ts = t.get('opened_at')
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            dow = ts.weekday() if isinstance(ts, datetime) else 0
            day_name = days.get(dow, 'Unknown')
            
            if day_name not in result:
                result[day_name] = {'pnl': 0, 'trades': 0}
            result[day_name]['pnl'] += t.get('pnl', 0)
            result[day_name]['trades'] += 1
        
        return result
    
    def _attribute_by_exit_reason(self, trades: list) -> dict:
        result = {}
        for t in trades:
            reason = t.get('exit_reason', 'unknown')
            if reason not in result:
                result[reason] = {'pnl': 0, 'count': 0}
            result[reason]['pnl'] += t.get('pnl', 0)
            result[reason]['count'] += 1
        
        return result
```

### 3.3 Attribution Report (Telegram)

```
📊 PERFORMANCE ATTRIBUTION — Last 30 Days
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total P&L: +$45.20 (+4.5%)

BY STRATEGY:
  Mean Reversion:  +$32.10 (71%)  ✅ 15W/8L = 65%
  Momentum:        +$13.10 (29%)  ✅ 8W/5L = 61%

BY ASSET:
  BTC/USDT:  +$28.50  (63%)  18 trades
  ETH/USDT:  +$10.20  (23%)   8 trades
  EUR/USD:   +$6.50   (14%)   5 trades

BY REGIME:
  trending_up:  +$35.00  15 trades, 73% win rate
  ranging:      +$8.20   10 trades, 50% win rate
  volatile:     +$2.00    5 trades, 40% win rate

BEST TRADE:  BTC/USDT +$8.50 (Jul 15)
WORST TRADE: BTC/USDT -$3.20 (Jul 8)

TOP INSIGHT: Mean Reversion performs 2x better
in trending_up regime than ranging.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 4. Benchmark Comparison

### 4.1 Purpose

"Am I beating just holding BTC?" — The most fundamental question. If your strategy can't beat buy-and-hold, you're adding complexity without adding value.

### 4.2 Benchmark Specification

```python
# portfolio/benchmark.py

import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class BenchmarkComparison:
    """Comparison of strategy performance vs benchmark."""
    period: str
    start_date: str
    end_date: str
    
    # Strategy metrics
    strategy_return_pct: float
    strategy_sharpe: float
    strategy_max_dd_pct: float
    strategy_trades: int
    
    # Benchmark metrics
    benchmark_return_pct: float
    benchmark_sharpe: float
    benchmark_max_dd_pct: float
    
    # Alpha
    alpha: float                    # strategy_return - benchmark_return
    alpha_annualized: float
    information_ratio: float        # alpha / tracking_error
    
    # Risk-adjusted comparison
    strategy_sortino: float
    benchmark_sortino: float
    
    # Win/loss vs benchmark
    days_outperformed: int
    days_total: int
    outperformance_rate: float
    
    # Specific benchmarks
    vs_buy_and_hold_btc: float      # Alpha vs holding BTC
    vs_buy_and_hold_eth: float      # Alpha vs holding ETH
    vs_equal_weight_crypto: float   # Alpha vs equal-weight crypto basket


class BenchmarkComparator:
    """
    Compare strategy performance against benchmarks.
    Benchmarks: buy-and-hold BTC, buy-and-hold ETH, equal-weight crypto.
    """
    
    def __init__(self, db_path: str = 'data/tsar.db'):
        self.db_path = db_path
    
    def compare(self, start_date: str, end_date: str, 
                initial_balance: float = 1000.0) -> BenchmarkComparison:
        """Full benchmark comparison for a period."""
        
        # Load strategy trades
        trades = self._load_trades(start_date, end_date)
        
        # Calculate strategy metrics
        strategy_returns = self._calc_daily_strategy_returns(trades, initial_balance, start_date, end_date)
        strategy_total_return = sum(strategy_returns)
        strategy_sharpe = self._calc_sharpe(strategy_returns)
        strategy_max_dd = self._calc_max_drawdown(strategy_returns)
        strategy_sortino = self._calc_sortino(strategy_returns)
        
        # Load benchmark prices
        btc_returns = self._load_benchmark_returns('BTC/USDT', start_date, end_date)
        eth_returns = self._load_benchmark_returns('ETH/USDT', start_date, end_date)
        
        # Calculate benchmark metrics
        btc_total_return = sum(btc_returns) if btc_returns else 0
        btc_sharpe = self._calc_sharpe(btc_returns) if btc_returns else 0
        btc_max_dd = self._calc_max_drawdown(btc_returns) if btc_returns else 0
        
        # Equal-weight crypto benchmark
        if btc_returns and eth_returns:
            min_len = min(len(btc_returns), len(eth_returns))
            equal_weight_returns = [(btc_returns[i] + eth_returns[i]) / 2 for i in range(min_len)]
            ew_total_return = sum(equal_weight_returns)
        else:
            ew_total_return = btc_total_return
        
        # Alpha calculation
        alpha = strategy_total_return - btc_total_return
        
        # Tracking error
        if btc_returns and strategy_returns:
            min_len = min(len(strategy_returns), len(btc_returns))
            excess = [strategy_returns[i] - btc_returns[i] for i in range(min_len)]
            tracking_error = np.std(excess) * np.sqrt(252) if len(excess) > 1 else 0
            info_ratio = (alpha * 252 / len(min_len)) / tracking_error if tracking_error > 0 else 0
        else:
            tracking_error = 0
            info_ratio = 0
        
        # Days outperformed
        if btc_returns and strategy_returns:
            min_len = min(len(strategy_returns), len(btc_returns))
            outperformed = sum(1 for i in range(min_len) if strategy_returns[i] > btc_returns[i])
            outperformance_rate = outperformed / min_len if min_len > 0 else 0
        else:
            outperformed = 0
            outperformance_rate = 0
        
        return BenchmarkComparison(
            period=f"{start_date} to {end_date}",
            start_date=start_date,
            end_date=end_date,
            strategy_return_pct=strategy_total_return * 100,
            strategy_sharpe=strategy_sharpe,
            strategy_max_dd_pct=strategy_max_dd * 100,
            strategy_trades=len(trades),
            benchmark_return_pct=btc_total_return * 100,
            benchmark_sharpe=btc_sharpe,
            benchmark_max_dd_pct=btc_max_dd * 100,
            alpha=alpha * 100,
            alpha_annualized=self._annualize_return(alpha, start_date, end_date),
            information_ratio=info_ratio,
            strategy_sortino=strategy_sortino,
            benchmark_sortino=self._calc_sortino(btc_returns) if btc_returns else 0,
            days_outperformed=outperformed,
            days_total=min_len if btc_returns and strategy_returns else 0,
            outperformance_rate=outperformance_rate,
            vs_buy_and_hold_btc=alpha * 100,
            vs_buy_and_hold_eth=(strategy_total_return - (ew_total_return - btc_total_return)) * 100 if eth_returns else 0,
            vs_equal_weight_crypto=(strategy_total_return - ew_total_return) * 100
        )
    
    def _load_trades(self, start: str, end: str) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT * FROM trades 
            WHERE closed_at BETWEEN ? AND ? AND status = 'CLOSED'
            ORDER BY closed_at
        """, (start, end))
        columns = [desc[0] for desc in cursor.description]
        trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return trades
    
    def _calc_daily_strategy_returns(self, trades: list, initial_balance: float,
                                      start: str, end: str) -> list[float]:
        """Calculate daily portfolio returns."""
        # Group trades by day
        daily_pnl = {}
        for t in trades:
            day = t.get('closed_at', '')[:10]  # YYYY-MM-DD
            daily_pnl[day] = daily_pnl.get(day, 0) + t.get('pnl', 0)
        
        # Convert to returns
        balance = initial_balance
        returns = []
        current = datetime.strptime(start, '%Y-%m-%d')
        end_dt = datetime.strptime(end, '%Y-%m-%d')
        
        while current <= end_dt:
            day_str = current.strftime('%Y-%m-%d')
            pnl = daily_pnl.get(day_str, 0)
            ret = pnl / balance if balance > 0 else 0
            returns.append(ret)
            balance += pnl
            current += timedelta(days=1)
        
        return returns
    
    def _load_benchmark_returns(self, symbol: str, start: str, end: str) -> list[float]:
        """Load benchmark daily returns from cache or API."""
        # Try cache first
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("""
                SELECT timestamp, close FROM market_data 
                WHERE symbol = ? AND timeframe = '1d'
                AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """, (symbol, start, end))
            rows = cursor.fetchall()
            
            if len(rows) > 1:
                prices = [r[1] for r in rows]
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                return returns
        except Exception:
            pass
        finally:
            conn.close()
        
        # Fallback to API
        try:
            import ccxt
            exchange = ccxt.binance()
            since = exchange.parse8601(f"{start}T00:00:00Z")
            end_ts = exchange.parse8601(f"{end}T00:00:00Z")
            candles = exchange.fetch_ohlcv(symbol, '1d', since=since, limit=365)
            
            if len(candles) > 1:
                prices = [c[4] for c in candles]  # Close prices
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                return returns
        except Exception:
            pass
        
        return []
    
    def _calc_sharpe(self, returns: list[float]) -> float:
        if not returns or len(returns) < 5:
            return 0.0
        r = np.array(returns)
        if np.std(r) == 0:
            return 0.0
        return np.mean(r) / np.std(r) * np.sqrt(252)
    
    def _calc_sortino(self, returns: list[float]) -> float:
        if not returns or len(returns) < 5:
            return 0.0
        r = np.array(returns)
        downside = r[r < 0]
        if len(downside) == 0 or np.std(downside) == 0:
            return 0.0
        return np.mean(r) / np.std(downside) * np.sqrt(252)
    
    def _calc_max_drawdown(self, returns: list[float]) -> float:
        if not returns:
            return 0.0
        cumulative = np.cumsum(returns)
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        return np.max(drawdown) if len(drawdown) > 0 else 0.0
    
    def _annualize_return(self, total_return: float, start: str, end: str) -> float:
        days = (datetime.strptime(end, '%Y-%m-%d') - datetime.strptime(start, '%Y-%m-%d')).days
        if days <= 0:
            return 0.0
        return ((1 + total_return) ** (365 / days) - 1) * 100
```

### 4.3 Benchmark Telegram Report

```
📈 BENCHMARK COMPARISON — Last 30 Days
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

              Strategy    BTC Buy&Hold   Alpha
Return:       +4.52%      +3.18%        +1.34%  ✅
Sharpe:       1.42        0.89          +0.53
Max DD:       -3.2%       -8.5%         +5.3%   ✅
Sortino:      2.15        1.12          +1.03

Days beating BTC: 18/30 (60%)

VERDICT: ✅ Strategy adds value above buy-and-hold
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 5. Portfolio Risk Metrics

### 5.1 Portfolio-Level VaR

```python
# portfolio/risk_metrics.py

import numpy as np
from scipy import stats

class PortfolioRiskMetrics:
    """
    Portfolio-level risk metrics.
    Goes beyond per-trade risk to measure overall portfolio health.
    """
    
    def calc_var(self, returns: list[float], confidence: float = 0.95) -> float:
        """
        Historical Value at Risk.
        "What's the most I can lose on a bad day, X% of the time?"
        """
        if len(returns) < 20:
            return 0.0
        return abs(np.percentile(returns, (1 - confidence) * 100))
    
    def calc_cvar(self, returns: list[float], confidence: float = 0.95) -> float:
        """
        Conditional VaR (Expected Shortfall).
        "If we exceed VaR, what's the average loss?"
        """
        if len(returns) < 20:
            return 0.0
        var = self.calc_var(returns, confidence)
        tail = [r for r in returns if r <= -var]
        return abs(np.mean(tail)) if tail else var
    
    def calc_portfolio_beta(self, returns: list[float], 
                            benchmark_returns: list[float]) -> float:
        """
        Portfolio beta vs benchmark.
        β > 1: More volatile than benchmark
        β < 1: Less volatile than benchmark
        β = 0: Uncorrelated
        """
        if len(returns) < 20 or len(benchmark_returns) < 20:
            return 0.0
        
        min_len = min(len(returns), len(benchmark_returns))
        r = np.array(returns[:min_len])
        b = np.array(benchmark_returns[:min_len])
        
        covariance = np.cov(r, b)[0][1]
        benchmark_variance = np.var(b)
        
        return covariance / benchmark_variance if benchmark_variance > 0 else 0.0
    
    def calc_treynor_ratio(self, returns: list[float], 
                           benchmark_returns: list[float],
                           risk_free_rate: float = 0.0) -> float:
        """
        Treynor ratio = (return - risk_free) / beta
        Risk-adjusted return per unit of systematic risk.
        """
        beta = self.calc_portfolio_beta(returns, benchmark_returns)
        if beta == 0:
            return 0.0
        
        annual_return = np.mean(returns) * 252
        return (annual_return - risk_free_rate) / beta
    
    def calc_information_ratio(self, returns: list[float],
                                benchmark_returns: list[float]) -> float:
        """
        Information ratio = alpha / tracking_error
        Measures active return per unit of active risk.
        """
        if len(returns) < 20 or len(benchmark_returns) < 20:
            return 0.0
        
        min_len = min(len(returns), len(benchmark_returns))
        excess = [returns[i] - benchmark_returns[i] for i in range(min_len)]
        
        tracking_error = np.std(excess) * np.sqrt(252)
        alpha = np.mean(excess) * 252
        
        return alpha / tracking_error if tracking_error > 0 else 0.0
    
    def stress_test(self, positions: list, scenarios: list[dict]) -> list[dict]:
        """
        Run stress test scenarios on current portfolio.
        
        Scenarios:
        - Flash crash: BTC -30% in 1 hour
        - Exchange halt: All positions frozen for 24h
        - Correlation spike: All assets move together
        - Liquidity crisis: Spreads widen 10x
        """
        results = []
        
        for scenario in scenarios:
            total_pnl = 0
            position_impacts = []
            
            for pos in positions:
                asset_shock = scenario.get('shocks', {}).get(pos.symbol, 0)
                if asset_shock == 0:
                    # Use asset class default
                    spec = ASSET_SPECS.get(pos.symbol)
                    if spec:
                        asset_shock = scenario.get('class_shocks', {}).get(
                            spec.asset_class.value, 0
                        )
                
                if pos.side == 'long':
                    impact = pos.value_usd * asset_shock
                else:
                    impact = pos.value_usd * -asset_shock
                
                total_pnl += impact
                position_impacts.append({
                    'symbol': pos.symbol,
                    'impact_usd': impact,
                    'impact_pct': asset_shock * 100
                })
            
            results.append({
                'scenario': scenario['name'],
                'total_pnl': total_pnl,
                'position_impacts': position_impacts,
                'survives': abs(total_pnl) < positions[0].value_usd * 10 if positions else True  # Rough check
            })
        
        return results


# Default stress test scenarios
STRESS_SCENARIOS = [
    {
        'name': 'BTC Flash Crash (-30%)',
        'shocks': {'BTC/USDT': -0.30, 'ETH/USDT': -0.35},
        'class_shocks': {'crypto': -0.30, 'forex': 0.0, 'gold': 0.02}
    },
    {
        'name': 'Crypto Winter (-50%)',
        'shocks': {'BTC/USDT': -0.50, 'ETH/USDT': -0.55},
        'class_shocks': {'crypto': -0.50, 'forex': 0.0, 'gold': 0.05}
    },
    {
        'name': 'USD Collapse',
        'shocks': {'EUR/USD': 0.05, 'GBP/USD': 0.06, 'USD/JPY': -0.04},
        'class_shocks': {'crypto': 0.10, 'forex': 0.05, 'gold': 0.08}
    },
    {
        'name': 'Correlation Spike (All Down)',
        'class_shocks': {'crypto': -0.20, 'forex': -0.05, 'gold': -0.10}
    },
    {
        'name': 'Liquidity Crisis (Wide Spreads)',
        'class_shocks': {'crypto': -0.05, 'forex': -0.01, 'gold': -0.02}
    },
]
```

---

## 6. Day1 vs Full Implementation

### 6.1 Implementation Levels

| Component | Day1 | Level 2 | Level 3 | Level 4 |
|-----------|------|---------|---------|---------|
| **Multi-Asset** | ❌ BTC only | ⚠️ BTC + ETH | ✅ + Forex (EUR/USD) | ✅ + Gold + all forex |
| **Rebalancing** | ❌ N/A (1 asset) | ❌ N/A | ⚠️ Strategy rebalance | ✅ Full cross-asset |
| **Attribution** | ⚠️ Daily P&L report | ✅ By strategy | ✅ + By asset + regime | ✅ Full multi-dimensional |
| **Benchmark** | ⚠️ vs BTC buy-hold | ✅ + vs ETH | ✅ + Equal-weight | ✅ + Custom benchmarks |
| **VaR/Stress** | ❌ Skip | ⚠️ Basic VaR | ✅ Full VaR + CVaR | ✅ + Stress scenarios |
| **Exchange** | ❌ Binance only | ⚠️ Binance | ✅ + OANDA | ✅ Multi-exchange |
| **Correlation** | ❌ N/A | ⚠️ Basic | ✅ Cross-asset matrix | ✅ + regime-aware |

### 6.2 Day1 Portfolio (Minimal)

**What exists:** Single asset (BTC/USDT), single strategy (Mean Reversion), single exchange (Binance).

**What to add:**
- Benchmark tracking: Compare strategy P&L vs buy-and-hold BTC
- Daily P&L report via Telegram

```python
# Day1: Simple benchmark comparison (add to daily_report.py)

def daily_benchmark_report():
    """Compare today's strategy P&L vs BTC buy-and-hold."""
    conn = sqlite3.connect('data/tsar.db')
    
    # Get today's strategy P&L
    today = datetime.now().date()
    strategy_pnl = conn.execute(
        "SELECT SUM(pnl) FROM trades WHERE date(closed_at) = ?", (today,)
    ).fetchone()[0] or 0
    
    # Get BTC price change today
    yesterday = today - timedelta(days=1)
    btc_prices = conn.execute(
        "SELECT close FROM market_data WHERE symbol='BTC/USDT' AND timeframe='1d' AND date(timestamp) IN (?, ?)",
        (str(yesterday), str(today))
    ).fetchall()
    
    if len(btc_prices) >= 2:
        btc_return = (btc_prices[1][0] - btc_prices[0][0]) / btc_prices[0][0] * 100
        alpha = strategy_pnl - btc_return
        emoji = "✅" if alpha > 0 else "❌"
        
        return f"""
📈 Benchmark: {emoji} Alpha = {alpha:+.2f}% vs BTC ({btc_return:+.2f}%)
"""
    return ""
```

### 6.3 Level 2 Portfolio (Months 2-3)

**Add:**
- ETH/USDT trading (same strategies)
- Per-strategy attribution
- Basic VaR calculation (historical, 95%)
- Benchmark comparison (vs BTC, vs ETH)

### 6.4 Level 3 Portfolio (Months 4-6)

**Add:**
- OANDA integration for EUR/USD
- Cross-asset correlation matrix
- Full attribution (strategy × asset × regime)
- Strategy-level rebalancing (Kelly + risk parity)
- Information ratio, Treynor ratio

### 6.5 Level 4 Portfolio (Months 7-12)

**Add:**
- Gold (XAU/USD) via OANDA
- Full forex pairs (GBP/USD, USD/JPY)
- Cross-asset rebalancing
- Stress testing with historical scenarios
- Custom benchmark creation
- Portfolio-level VaR + CVaR

---

## 7. Database Schema Extensions

```sql
-- ============================================
-- PORTFOLIO_POSITIONS: Multi-asset position tracking
-- ============================================
CREATE TABLE IF NOT EXISTS portfolio_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    entry_price     REAL NOT NULL,
    current_price   REAL,
    stop_loss       REAL,
    take_profit     REAL,
    strategy        TEXT NOT NULL,
    asset_class     TEXT NOT NULL,              -- 'crypto', 'forex', 'gold'
    exchange        TEXT NOT NULL,
    unrealized_pnl  REAL DEFAULT 0.0,
    opened_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at       TIMESTAMP,
    exit_price      REAL,
    realized_pnl    REAL DEFAULT 0.0,
    exit_reason     TEXT
);

-- ============================================
-- REBALANCE_LOG: Rebalancing history
-- ============================================
CREATE TABLE IF NOT EXISTS rebalance_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reason          TEXT NOT NULL,
    orders_json     TEXT,                       -- JSON array of orders
    executions_json TEXT,                       -- JSON array of execution results
    max_drift       REAL,
    estimated_cost  REAL,
    executed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- PORTFOLIO_SNAPSHOTS: Periodic portfolio state
-- ============================================
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   DATE NOT NULL,
    total_equity    REAL NOT NULL,
    cash            REAL NOT NULL,
    crypto_value    REAL DEFAULT 0.0,
    forex_value     REAL DEFAULT 0.0,
    gold_value      REAL DEFAULT 0.0,
    total_positions INTEGER DEFAULT 0,
    daily_pnl       REAL DEFAULT 0.0,
    weekly_pnl      REAL DEFAULT 0.0,
    monthly_pnl     REAL DEFAULT 0.0,
    var_95          REAL,
    max_drawdown    REAL,
    portfolio_heat  REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- BENCHMARK_DATA: Benchmark price history
-- ============================================
CREATE TABLE IF NOT EXISTS benchmark_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    benchmark_name  TEXT NOT NULL,              -- 'BTC_BUY_HOLD', 'ETH_BUY_HOLD', 'EQUAL_WEIGHT'
    date            DATE NOT NULL,
    value           REAL NOT NULL,
    daily_return    REAL,
    UNIQUE(benchmark_name, date)
);

-- ============================================
-- ATTRIBUTION_REPORTS: Cached attribution reports
-- ============================================
CREATE TABLE IF NOT EXISTS attribution_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    report_type     TEXT NOT NULL,              -- 'daily', 'weekly', 'monthly'
    report_json     TEXT NOT NULL,              -- Full AttributionResult as JSON
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_symbol ON portfolio_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_strategy ON portfolio_positions(strategy);
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_class ON portfolio_positions(asset_class);
CREATE INDEX IF NOT EXISTS idx_rebalance_date ON rebalance_log(executed_at);
CREATE INDEX IF NOT EXISTS idx_snapshot_date ON portfolio_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_benchmark_name_date ON benchmark_data(benchmark_name, date);
```

---

## 8. Integration Points

### 8.1 With Strategy Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Strategy Allocator → Rebalancer | Strategy → Portfolio | Target allocations per strategy |
| Strategy Monitor → Attribution | Strategy → Portfolio | Per-strategy P&L for attribution |
| Retirement Gates → Portfolio | Strategy → Portfolio | Close positions on strategy retirement |
| Signal Aggregator → Portfolio | Strategy → Portfolio | Composite signals with allocation weights |

### 8.2 With Risk Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Portfolio VaR → Risk Guardian | Portfolio → Risk | Portfolio-level risk limits |
| Stress Test → Risk Guardian | Portfolio → Risk | Scenario-based position limits |
| Correlation Matrix → Risk Guardian | Portfolio → Risk | Cross-asset correlation for risk checks |
| Rebalancer → Risk Guardian | Portfolio → Risk | Rebalance orders need risk approval |

### 8.3 With Execution Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Rebalancer → Execution Sniper | Portfolio → Execution | Rebalance orders |
| Exchange Manager → Execution | Portfolio → Execution | Multi-exchange routing |
| Position Tracker → Portfolio | Execution → Portfolio | Fill updates, position state |

### 8.4 With Data Layer

| Integration | Direction | Data |
|-------------|-----------|------|
| Market Data → Benchmark | Data → Portfolio | Benchmark price history |
| Market Data → Correlation | Data → Portfolio | Cross-asset price data |
| Regime Detector → Rebalancer | Data → Portfolio | Regime for allocation adjustment |
| Market Data → VaR | Data → Portfolio | Historical returns for VaR calculation |

### 8.5 With Telegram

| Command | Handler | Description |
|---------|---------|-------------|
| `/portfolio` | PortfolioManager | Full portfolio snapshot |
| `/positions` | PortfolioManager | All open positions |
| `/attribution` | PerformanceAttributor | P&L attribution report |
| `/benchmark` | BenchmarkComparator | vs buy-and-hold comparison |
| `/rebalance` | Rebalancer | Check/trigger rebalance |
| `/var` | PortfolioRiskMetrics | Current VaR and stress test |
| `/correlations` | CrossAssetCorrelation | Asset correlation matrix |

---

*Portfolio Layer specification complete. See STRATEGY_LAYER.md for strategy-level specifications.*
