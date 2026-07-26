class Position {
  final String symbol;
  final double quantity;
  final double entryPrice;
  final double currentPrice;
  final double unrealizedPnl;
  final double unrealizedPnlPercent;
  final double marketValue;
  final double weight;
  final String? strategy;

  Position({
    required this.symbol,
    required this.quantity,
    required this.entryPrice,
    required this.currentPrice,
    required this.unrealizedPnl,
    required this.unrealizedPnlPercent,
    required this.marketValue,
    required this.weight,
    this.strategy,
  });

  factory Position.fromJson(Map<String, dynamic> json) {
    try {
      return Position(
        symbol: json['symbol'] ?? '',
        quantity: _toDouble(json['quantity'] ?? json['qty']),
        entryPrice: _toDouble(json['entry_price'] ?? json['avg_entry']),
        currentPrice: _toDouble(json['current_price'] ?? json['price']),
        unrealizedPnl: _toDouble(json['unrealized_pnl'] ?? json['pnl']),
        unrealizedPnlPercent: _toDouble(json['unrealized_pnl_percent'] ?? json['pnl_percent']),
        marketValue: _toDouble(json['market_value'] ?? json['value']),
        weight: _toDouble(json['weight'] ?? json['allocation']),
        strategy: json['strategy'] ?? json['strategy_id'],
      );
    } catch (_) {
      return Position(
        symbol: json['symbol'] ?? '',
        quantity: 0,
        entryPrice: 0,
        currentPrice: 0,
        unrealizedPnl: 0,
        unrealizedPnlPercent: 0,
        marketValue: 0,
        weight: 0,
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

class PnlSummary {
  final double dailyPnl;
  final double weeklyPnl;
  final double monthlyPnl;
  final double totalPnl;
  final double dailyReturn;
  final double maxDrawdown;
  final double sharpeRatio;
  final List<PnlPoint> equityCurve;

  PnlSummary({
    required this.dailyPnl,
    required this.weeklyPnl,
    required this.monthlyPnl,
    required this.totalPnl,
    required this.dailyReturn,
    required this.maxDrawdown,
    required this.sharpeRatio,
    required this.equityCurve,
  });

  factory PnlSummary.fromJson(Map<String, dynamic> json) {
    try {
      return PnlSummary(
        dailyPnl: _toDouble(json['daily_pnl']),
        weeklyPnl: _toDouble(json['weekly_pnl']),
        monthlyPnl: _toDouble(json['monthly_pnl']),
        totalPnl: _toDouble(json['total_pnl']),
        dailyReturn: _toDouble(json['daily_return'] ?? json['win_rate']),
        maxDrawdown: _toDouble(json['max_drawdown']),
        sharpeRatio: _toDouble(json['sharpe_ratio']),
        equityCurve: _parseCurve(json['equity_curve']),
      );
    } catch (_) {
      return PnlSummary(
        dailyPnl: _toDouble(json['daily_pnl']),
        weeklyPnl: 0,
        monthlyPnl: 0,
        totalPnl: _toDouble(json['total_pnl']),
        dailyReturn: 0,
        maxDrawdown: 0,
        sharpeRatio: 0,
        equityCurve: [],
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static List<PnlPoint> _parseCurve(dynamic curve) {
    if (curve is List) {
      return curve.map((e) {
        if (e is Map<String, dynamic>) return PnlPoint.fromJson(e);
        return PnlPoint(date: DateTime.now(), value: 0);
      }).toList();
    }
    return [];
  }
}

class PnlPoint {
  final DateTime date;
  final double value;

  PnlPoint({required this.date, required this.value});

  factory PnlPoint.fromJson(Map<String, dynamic> json) {
    try {
      return PnlPoint(
        date: DateTime.tryParse(json['date'] ?? json['timestamp'] ?? '') ?? DateTime.now(),
        value: (json['value'] ?? json['pnl'] ?? 0).toDouble(),
      );
    } catch (_) {
      return PnlPoint(date: DateTime.now(), value: 0);
    }
  }
}
