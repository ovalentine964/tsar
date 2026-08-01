---
name: trading
description: Crypto trading operations — signal analysis, order execution, position management
tools: [market_data, technical_analysis, execution, order_router, portfolio, stop_loss_calculator, take_profit_calculator, fee_calculator]
requires_governance: true
---

# Trading Skill

## Purpose
Execute crypto trading operations across centralized and decentralized exchanges.
This skill covers the full trade lifecycle: signal analysis → risk check → order placement → position management → exit.

## Instructions

### Signal Analysis
When analyzing a trading signal:
1. Fetch current market data (price, volume, orderbook depth)
2. Run technical analysis (indicators, patterns, trend)
3. Check market microstructure (spread, liquidity, whale activity)
4. Calculate optimal entry, stop-loss, and take-profit levels
5. Verify risk-reward ratio meets minimum 2:1 threshold

### Order Execution
When executing a trade:
1. ALWAYS run RiskGovernor check first (7-layer veto protocol)
2. Calculate position size using Half-Kelly criterion
3. Account for exchange fees in sizing
4. Use SmartOrderRouter for best execution
5. Monitor fill quality and slippage

### Position Management
For open positions:
1. Track unrealized P&L in real-time
2. Adjust stop-loss to breakeven after 1R profit
3. Trail stops in trending markets
4. Scale out at key resistance/support levels
5. Never add to losing positions

### Exit Strategy
When closing a position:
1. Check if stop-loss or take-profit triggered
2. Evaluate if original thesis is still valid
3. Consider partial exits at multiple targets
4. Log the trade outcome to TradeMemory
5. Trigger flywheel reflection cycle

## Risk Constraints
- Maximum single position: 15% of equity
- Maximum stop-loss distance: 2% from entry
- Minimum risk-reward: 2:1 after fees
- Mandatory stop-loss on every trade
- No revenge trading (3-loss cooldown)
- Position sizing reduced during drawdown

## Tool Usage
```
market_data      → Get price, volume, orderbook
technical_analysis → RSI, MACD, Bollinger, trend
execution        → Place market/limit orders
order_router     → Smart routing across venues
portfolio        → Current positions and equity
stop_loss_calculator → Optimal stop placement
take_profit_calculator → Multi-target exits
fee_calculator   → Fee-aware sizing
```
