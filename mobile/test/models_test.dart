import 'package:flutter_test/flutter_test.dart';
import 'package:tsar_mobile/models/position.dart';
import 'package:tsar_mobile/models/trade.dart';
import 'package:tsar_mobile/models/risk.dart';
import 'package:tsar_mobile/models/strategy.dart';
import 'package:tsar_mobile/models/factor.dart';
import 'package:tsar_mobile/models/news.dart';
import 'package:tsar_mobile/models/signal_quality.dart';

void main() {
  // ── Position ─────────────────────────────────────────────────────
  group('Position.fromJson', () {
    test('parses standard JSON', () {
      final json = {
        'symbol': 'BTCUSD',
        'quantity': 0.5,
        'entry_price': 30000.0,
        'current_price': 31000.0,
        'unrealized_pnl': 500.0,
        'unrealized_pnl_percent': 3.33,
        'market_value': 15500.0,
        'weight': 0.25,
        'strategy': 'momentum',
      };
      final p = Position.fromJson(json);
      expect(p.symbol, 'BTCUSD');
      expect(p.quantity, 0.5);
      expect(p.entryPrice, 30000.0);
      expect(p.currentPrice, 31000.0);
      expect(p.unrealizedPnl, 500.0);
      expect(p.strategy, 'momentum');
    });

    test('handles alternative JSON keys (qty, avg_entry, price)', () {
      final json = {
        'symbol': 'ETHUSD',
        'qty': 10,
        'avg_entry': 2000.0,
        'price': 2100.0,
        'pnl': 1000.0,
        'pnl_percent': 5.0,
        'value': 21000.0,
        'allocation': 0.3,
      };
      final p = Position.fromJson(json);
      expect(p.symbol, 'ETHUSD');
      expect(p.quantity, 10.0);
      expect(p.entryPrice, 2000.0);
      expect(p.currentPrice, 2100.0);
      expect(p.unrealizedPnl, 1000.0);
    });

    test('handles string numeric values', () {
      final json = {
        'symbol': 'SOLUSD',
        'quantity': '5.0',
        'entry_price': '100.0',
        'current_price': '105.0',
        'unrealized_pnl': '25.0',
        'unrealized_pnl_percent': '5.0',
        'market_value': '525.0',
        'weight': '0.1',
      };
      final p = Position.fromJson(json);
      expect(p.quantity, 5.0);
      expect(p.entryPrice, 100.0);
    });

    test('returns zeroed Position on malformed JSON', () {
      final p = Position.fromJson({'symbol': 'BAD'});
      expect(p.symbol, 'BAD');
      expect(p.quantity, 0);
      expect(p.entryPrice, 0);
    });
  });

  // ── PnlSummary ───────────────────────────────────────────────────
  group('PnlSummary.fromJson', () {
    test('parses full JSON', () {
      final json = {
        'daily_pnl': 150.0,
        'weekly_pnl': 1200.0,
        'monthly_pnl': 5000.0,
        'total_pnl': 25000.0,
        'daily_return': 0.015,
        'max_drawdown': -0.08,
        'sharpe_ratio': 1.8,
        'equity_curve': [
          {'date': '2026-01-01', 'value': 100000.0},
          {'date': '2026-01-02', 'value': 100150.0},
        ],
      };
      final pnl = PnlSummary.fromJson(json);
      expect(pnl.dailyPnl, 150.0);
      expect(pnl.totalPnl, 25000.0);
      expect(pnl.sharpeRatio, 1.8);
      expect(pnl.equityCurve, hasLength(2));
      expect(pnl.equityCurve.first.value, 100000.0);
    });

    test('handles missing equity_curve', () {
      final json = {'daily_pnl': 100.0, 'total_pnl': 5000.0};
      final pnl = PnlSummary.fromJson(json);
      expect(pnl.equityCurve, isEmpty);
    });
  });

  // ── Trade ────────────────────────────────────────────────────────
  group('Trade.fromJson', () {
    test('parses a buy trade', () {
      final json = {
        'id': 't-001',
        'symbol': 'BTCUSD',
        'side': 'buy',
        'status': 'open',
        'entry_price': 30000.0,
        'quantity': 0.1,
        'opened_at': '2026-08-01T10:00:00Z',
      };
      final t = Trade.fromJson(json);
      expect(t.id, 't-001');
      expect(t.symbol, 'BTCUSD');
      expect(t.side, TradeSide.buy);
      expect(t.status, TradeStatus.open);
      expect(t.entryPrice, 30000.0);
    });

    test('parses a closed sell trade with P&L', () {
      final json = {
        'trade_id': 't-002',
        'symbol': 'ETHUSD',
        'side': 'sell',
        'status': 'closed',
        'price': 2000.0,
        'exit_price': 1950.0,
        'qty': 5.0,
        'pnl': 250.0,
        'pnl_percent': 2.5,
        'timestamp': '2026-08-01T12:00:00Z',
        'closed_at': '2026-08-01T14:00:00Z',
      };
      final t = Trade.fromJson(json);
      expect(t.side, TradeSide.sell);
      expect(t.status, TradeStatus.closed);
      expect(t.exitPrice, 1950.0);
      expect(t.pnl, 250.0);
      expect(t.closedAt, isNotNull);
    });

    test('defaults to closed status for unknown status string', () {
      final json = {
        'id': '1',
        'symbol': 'X',
        'entry_price': 1,
        'quantity': 1,
        'status': 'unknown_status',
        'opened_at': '2026-01-01',
      };
      final t = Trade.fromJson(json);
      expect(t.status, TradeStatus.closed);
    });
  });

  // ── TradeStats ───────────────────────────────────────────────────
  group('TradeStats.fromJson', () {
    test('parses stats JSON', () {
      final json = {
        'total_trades': 100,
        'wins': 60,
        'losses': 40,
        'win_rate': 60.0,
        'total_pnl': 15000.0,
        'avg_win': 500.0,
        'avg_loss': -300.0,
        'largest_win': 2000.0,
        'largest_loss': -1500.0,
        'profit_factor': 1.67,
      };
      final s = TradeStats.fromJson(json);
      expect(s.totalTrades, 100);
      expect(s.winRate, 60.0);
      expect(s.profitFactor, 1.67);
    });
  });

  // ── RiskState ────────────────────────────────────────────────────
  group('RiskState.fromJson', () {
    test('parses risk state with alerts', () {
      final json = {
        'circuit_breaker': 'warning',
        'portfolio_heat': 0.65,
        'max_drawdown': 0.15,
        'current_drawdown': 0.05,
        'daily_loss_limit': 2.0,
        'daily_loss_used': 0.8,
        'position_limit': 10,
        'current_positions': 5,
        'kill_switch_active': false,
        'exposure': {'long': 60, 'short': 40},
        'alerts': [
          {
            'id': 'a1',
            'level': 'warning',
            'message': 'Approaching daily loss limit',
            'timestamp': '2026-08-01T10:00:00Z',
          }
        ],
      };
      final r = RiskState.fromJson(json);
      expect(r.circuitBreaker, CircuitBreakerLevel.warning);
      expect(r.portfolioHeat, 0.65);
      expect(r.killSwitchActive, isFalse);
      expect(r.alerts, hasLength(1));
      expect(r.alerts.first.message, 'Approaching daily loss limit');
      expect(r.dailyLossPercent, closeTo(0.4, 0.01));
    });

    test('parses halted circuit breaker', () {
      final json = {'circuit_breaker': 'halted', 'kill_switch_active': true};
      final r = RiskState.fromJson(json);
      expect(r.circuitBreaker, CircuitBreakerLevel.halted);
      expect(r.killSwitchActive, isTrue);
    });

    test('defaults to none for unknown breaker level', () {
      final r = RiskState.fromJson({'circuit_breaker': 'banana'});
      expect(r.circuitBreaker, CircuitBreakerLevel.none);
    });
  });

  // ── Strategy ─────────────────────────────────────────────────────
  group('Strategy.fromJson', () {
    test('parses a full strategy', () {
      final json = {
        'id': 'strat-1',
        'name': 'Momentum Alpha',
        'description': 'Trend following on daily bars',
        'genome': 'abc123',
        'total_return': 0.35,
        'sharpe_ratio': 2.1,
        'max_drawdown': -0.12,
        'win_rate': 0.58,
        'trade_count': 200,
        'profit_factor': 1.9,
        'status': 'active',
        'created_at': '2026-01-15T00:00:00Z',
        'last_trade_at': '2026-08-01T09:00:00Z',
      };
      final s = Strategy.fromJson(json);
      expect(s.name, 'Momentum Alpha');
      expect(s.isActive, isTrue);
      expect(s.sharpeRatio, 2.1);
      expect(s.lastTradeAt, isNotNull);
    });

    test('isActive is false for inactive status', () {
      final json = {'name': 'X', 'status': 'inactive', 'created_at': '2026-01-01'};
      final s = Strategy.fromJson(json);
      expect(s.isActive, isFalse);
    });
  });

  // ── BacktestResult ───────────────────────────────────────────────
  group('BacktestResult.fromJson', () {
    test('parses nested metrics', () {
      final json = {
        'strategy_id': 'strat-1',
        'metrics': {
          'total_return': 0.25,
          'sharpe_ratio': 1.5,
          'max_drawdown': -0.1,
          'win_rate': 0.55,
          'total_trades': 150,
          'profit_factor': 1.4,
          'avg_holding_period': 3.5,
          'equity_curve': [],
          'monthly_returns': {'2026-01': 0.05},
        },
      };
      final b = BacktestResult.fromJson(json);
      expect(b.strategyId, 'strat-1');
      expect(b.totalReturn, 0.25);
      expect(b.monthlyReturns, contains('2026-01'));
    });
  });

  // ── Factor ───────────────────────────────────────────────────────
  group('Factor.fromJson', () {
    test('parses factor with all fields', () {
      final json = {
        'id': 'f-001',
        'name': 'Momentum 20d',
        'category': 'momentum',
        'description': '20-day price momentum',
        'ic': 0.05,
        'ir': 0.8,
        'turnover': 0.3,
        'correlation': 0.15,
        'computation': 'close / close.shift(20) - 1',
      };
      final f = Factor.fromJson(json);
      expect(f.name, 'Momentum 20d');
      expect(f.ic, 0.05);
      expect(f.icFormatted, '+0.0500');
      expect(f.irFormatted, '+0.8000');
    });

    test('icFormatted shows negative sign', () {
      final json = {
        'name': 'NegFactor',
        'category': 'test',
        'ic': -0.03,
        'ir': -0.5,
        'turnover': 0.1,
        'correlation': 0.0,
        'computation': '',
        'created_at': '2026-01-01',
      };
      final f = Factor.fromJson(json);
      expect(f.icFormatted, '-0.0300');
    });
  });

  // ── FactorCategory ───────────────────────────────────────────────
  group('FactorCategory.fromJson', () {
    test('parses category', () {
      final json = {'name': 'momentum', 'description': 'Price momentum', 'count': 5};
      final c = FactorCategory.fromJson(json);
      expect(c.name, 'momentum');
      expect(c.count, 5);
    });
  });

  // ── NewsItem ─────────────────────────────────────────────────────
  group('NewsItem.fromJson', () {
    test('parses bullish news', () {
      final json = {
        'id': 'n-001',
        'title': 'BTC hits new ATH',
        'summary': 'Bitcoin reached 100k',
        'source': 'CoinDesk',
        'url': 'https://coindesk.com/btc-ath',
        'sentiment': 'bullish',
        'sentiment_score': 0.85,
        'symbols': ['BTCUSD'],
        'tags': ['crypto', 'bitcoin'],
        'published_at': '2026-08-01T08:00:00Z',
        'is_alert': true,
      };
      final n = NewsItem.fromJson(json);
      expect(n.title, 'BTC hits new ATH');
      expect(n.sentiment, SentimentType.bullish);
      expect(n.symbols, ['BTCUSD']);
      expect(n.isAlert, isTrue);
    });

    test('defaults to neutral for unknown sentiment', () {
      final json = {
        'title': 'X',
        'sentiment': 'whatever',
        'published_at': '2026-01-01',
      };
      final n = NewsItem.fromJson(json);
      expect(n.sentiment, SentimentType.neutral);
    });

    test('sentimentLabel returns correct string', () {
      final json = {'title': 'X', 'sentiment': 'bearish', 'published_at': '2026-01-01'};
      final n = NewsItem.fromJson(json);
      expect(n.sentimentLabel, 'BEARISH');
    });
  });

  // ── SignalQuality ────────────────────────────────────────────────
  group('SignalQuality.fromJson', () {
    test('parses signal with factors', () {
      final json = {
        'id': 'sig-001',
        'symbol': 'BTCUSD',
        'overall_score': 0.82,
        'grade': 'A',
        'confidence': 0.9,
        'recommendation': 'BUY',
        'evaluated_at': '2026-08-01T10:00:00Z',
        'factors': [
          {'name': 'momentum', 'score': 0.8, 'weight': 0.3, 'description': '20d momentum'},
          {'name': 'volatility', 'score': 0.7, 'weight': 0.2, 'description': 'Realized vol'},
        ],
      };
      final s = SignalQuality.fromJson(json);
      expect(s.symbol, 'BTCUSD');
      expect(s.grade, 'A');
      expect(s.factors, hasLength(2));
      expect(s.statusEmoji, '🟢');
    });

    test('auto-assigns grade from score when grade missing', () {
      final json = {'symbol': 'X', 'overall_score': 0.5, 'evaluated_at': '2026-01-01'};
      final s = SignalQuality.fromJson(json);
      expect(s.grade, 'D'); // 0.5 → D (0.4–0.6 range)
    });

    test('statusEmoji returns correct emoji per score range', () {
      final high = SignalQuality.fromJson({'symbol': 'A', 'overall_score': 0.9, 'evaluated_at': '2026-01-01'});
      final mid = SignalQuality.fromJson({'symbol': 'B', 'overall_score': 0.65, 'evaluated_at': '2026-01-01'});
      final low = SignalQuality.fromJson({'symbol': 'C', 'overall_score': 0.3, 'evaluated_at': '2026-01-01'});
      expect(high.statusEmoji, '🟢');
      expect(mid.statusEmoji, '🟡');
      expect(low.statusEmoji, '🔴');
    });
  });

  // ── SignalFactor ─────────────────────────────────────────────────
  group('SignalFactor.fromJson', () {
    test('parses factor entry', () {
      final json = {'name': 'momentum', 'score': 0.8, 'weight': 0.3, 'description': '20d mom'};
      final f = SignalFactor.fromJson(json);
      expect(f.name, 'momentum');
      expect(f.score, 0.8);
      expect(f.weight, 0.3);
      expect(f.contribution, closeTo(0.24, 0.01)); // score * weight
    });

    test('handles alternative keys (factor, value, importance)', () {
      final json = {'factor': 'vol', 'value': 0.6, 'importance': 0.5, 'detail': 'vol detail'};
      final f = SignalFactor.fromJson(json);
      expect(f.name, 'vol');
      expect(f.score, 0.6);
      expect(f.weight, 0.5);
    });
  });
}
