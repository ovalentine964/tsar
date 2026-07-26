import 'package:flutter/material.dart';
import '../theme.dart';

enum TradeStatus { open, closed, cancelled, pending }
enum TradeSide { buy, sell }

class Trade {
  final String id;
  final String symbol;
  final TradeSide side;
  final TradeStatus status;
  final double entryPrice;
  final double? exitPrice;
  final double quantity;
  final double? pnl;
  final double? pnlPercent;
  final String? strategy;
  final String? notes;
  final DateTime openedAt;
  final DateTime? closedAt;
  final Map<String, dynamic>? metadata;

  Trade({
    required this.id,
    required this.symbol,
    required this.side,
    required this.status,
    required this.entryPrice,
    this.exitPrice,
    required this.quantity,
    this.pnl,
    this.pnlPercent,
    this.strategy,
    this.notes,
    required this.openedAt,
    this.closedAt,
    this.metadata,
  });

  factory Trade.fromJson(Map<String, dynamic> json) {
    try {
      return Trade(
        id: json['id']?.toString() ?? json['trade_id']?.toString() ?? '',
        symbol: json['symbol'] ?? '',
        side: json['side'] == 'sell' ? TradeSide.sell : TradeSide.buy,
        status: _parseStatus(json['status']),
        entryPrice: _toDouble(json['entry_price'] ?? json['price'] ?? 0),
        exitPrice: json['exit_price'] != null ? _toDouble(json['exit_price']) : null,
        quantity: _toDouble(json['quantity'] ?? json['qty'] ?? 0),
        pnl: json['pnl'] != null ? _toDouble(json['pnl']) : null,
        pnlPercent: json['pnl_percent'] != null ? _toDouble(json['pnl_percent']) : null,
        strategy: json['strategy'] ?? json['strategy_id'],
        notes: json['notes'],
        openedAt: DateTime.tryParse(json['opened_at'] ?? json['timestamp'] ?? json['created_at'] ?? '') ?? DateTime.now(),
        closedAt: json['closed_at'] != null ? DateTime.tryParse(json['closed_at']) : null,
        metadata: json['metadata'] is Map ? Map<String, dynamic>.from(json['metadata']) : null,
      );
    } catch (_) {
      return Trade(
        id: json['id']?.toString() ?? '',
        symbol: json['symbol'] ?? '',
        side: TradeSide.buy,
        status: TradeStatus.closed,
        entryPrice: 0,
        quantity: 0,
        openedAt: DateTime.now(),
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static TradeStatus _parseStatus(String? s) {
    switch (s?.toLowerCase()) {
      case 'open': return TradeStatus.open;
      case 'closed': return TradeStatus.closed;
      case 'cancelled': return TradeStatus.cancelled;
      case 'pending': return TradeStatus.pending;
      default: return TradeStatus.closed;
    }
  }

  Color get sideColor => side == TradeSide.buy ? TsarTheme.profit : TsarTheme.loss;
  Color get pnlColor =>
      pnl != null ? (pnl! >= 0 ? TsarTheme.profit : TsarTheme.loss) : Colors.grey;
  String get sideLabel => side == TradeSide.buy ? 'BUY' : 'SELL';
}

class TradeStats {
  final int totalTrades;
  final int wins;
  final int losses;
  final double winRate;
  final double totalPnl;
  final double avgWin;
  final double avgLoss;
  final double largestWin;
  final double largestLoss;
  final double profitFactor;

  TradeStats({
    required this.totalTrades,
    required this.wins,
    required this.losses,
    required this.winRate,
    required this.totalPnl,
    required this.avgWin,
    required this.avgLoss,
    required this.largestWin,
    required this.largestLoss,
    required this.profitFactor,
  });

  factory TradeStats.fromJson(Map<String, dynamic> json) {
    try {
      return TradeStats(
        totalTrades: json['total_trades'] ?? json['total'] ?? 0,
        wins: json['wins'] ?? json['win_count'] ?? 0,
        losses: json['losses'] ?? json['loss_count'] ?? 0,
        winRate: _toDouble(json['win_rate']),
        totalPnl: _toDouble(json['total_pnl']),
        avgWin: _toDouble(json['avg_win']),
        avgLoss: _toDouble(json['avg_loss']),
        largestWin: _toDouble(json['largest_win']),
        largestLoss: _toDouble(json['largest_loss']),
        profitFactor: _toDouble(json['profit_factor']),
      );
    } catch (_) {
      return TradeStats(
        totalTrades: json['total'] ?? 0,
        wins: 0,
        losses: 0,
        winRate: 0,
        totalPnl: 0,
        avgWin: 0,
        avgLoss: 0,
        largestWin: 0,
        largestLoss: 0,
        profitFactor: 0,
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }
}
