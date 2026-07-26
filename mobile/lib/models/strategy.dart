class Strategy {
  final String id;
  final String name;
  final String description;
  final String genome;
  final double totalReturn;
  final double sharpeRatio;
  final double maxDrawdown;
  final double winRate;
  final int tradeCount;
  final double profitFactor;
  final String status;
  final DateTime createdAt;
  final DateTime? lastTradeAt;
  final Map<String, dynamic>? params;

  Strategy({
    required this.id,
    required this.name,
    required this.description,
    required this.genome,
    required this.totalReturn,
    required this.sharpeRatio,
    required this.maxDrawdown,
    required this.winRate,
    required this.tradeCount,
    required this.profitFactor,
    required this.status,
    required this.createdAt,
    this.lastTradeAt,
    this.params,
  });

  factory Strategy.fromJson(Map<String, dynamic> json) {
    try {
      return Strategy(
        id: json['id']?.toString() ?? json['name'] ?? '',
        name: json['name'] ?? json['id'] ?? '',
        description: json['description'] ?? '',
        genome: json['genome'] ?? json['genome_hash'] ?? '',
        totalReturn: _toDouble(json['total_return']),
        sharpeRatio: _toDouble(json['sharpe_ratio']),
        maxDrawdown: _toDouble(json['max_drawdown']),
        winRate: _toDouble(json['win_rate']),
        tradeCount: json['trade_count'] ?? json['trades'] ?? 0,
        profitFactor: _toDouble(json['profit_factor']),
        status: json['status'] ?? 'inactive',
        createdAt: DateTime.tryParse(json['created_at'] ?? '') ?? DateTime.now(),
        lastTradeAt: json['last_trade_at'] != null
            ? DateTime.tryParse(json['last_trade_at'])
            : null,
        params: json['params'] is Map ? Map<String, dynamic>.from(json['params']) : null,
      );
    } catch (_) {
      return Strategy(
        id: json['name']?.toString() ?? json['id']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        description: '',
        genome: '',
        totalReturn: 0,
        sharpeRatio: 0,
        maxDrawdown: 0,
        winRate: 0,
        tradeCount: 0,
        profitFactor: 0,
        status: 'inactive',
        createdAt: DateTime.now(),
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  bool get isActive => status == 'active';
}

class BacktestResult {
  final String strategyId;
  final double totalReturn;
  final double sharpeRatio;
  final double maxDrawdown;
  final double winRate;
  final int totalTrades;
  final double profitFactor;
  final double avgHoldingPeriod;
  final List<Map<String, dynamic>> equityCurve;
  final Map<String, dynamic> monthlyReturns;

  BacktestResult({
    required this.strategyId,
    required this.totalReturn,
    required this.sharpeRatio,
    required this.maxDrawdown,
    required this.winRate,
    required this.totalTrades,
    required this.profitFactor,
    required this.avgHoldingPeriod,
    required this.equityCurve,
    required this.monthlyReturns,
  });

  factory BacktestResult.fromJson(Map<String, dynamic> json) {
    try {
      final metrics = json['metrics'] is Map
          ? Map<String, dynamic>.from(json['metrics'])
          : json;
      return BacktestResult(
        strategyId: json['strategy_id']?.toString() ?? json['strategy'] ?? '',
        totalReturn: _toDouble(metrics['total_return']),
        sharpeRatio: _toDouble(metrics['sharpe_ratio']),
        maxDrawdown: _toDouble(metrics['max_drawdown']),
        winRate: _toDouble(metrics['win_rate']),
        totalTrades: metrics['total_trades'] ?? 0,
        profitFactor: _toDouble(metrics['profit_factor']),
        avgHoldingPeriod: _toDouble(metrics['avg_holding_period']),
        equityCurve: (metrics['equity_curve'] as List<dynamic>?)
                ?.map((e) => Map<String, dynamic>.from(e))
                .toList() ??
            [],
        monthlyReturns: metrics['monthly_returns'] is Map
            ? Map<String, dynamic>.from(metrics['monthly_returns'])
            : {},
      );
    } catch (_) {
      return BacktestResult(
        strategyId: json['strategy']?.toString() ?? '',
        totalReturn: 0,
        sharpeRatio: 0,
        maxDrawdown: 0,
        winRate: 0,
        totalTrades: 0,
        profitFactor: 0,
        avgHoldingPeriod: 0,
        equityCurve: [],
        monthlyReturns: {},
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
