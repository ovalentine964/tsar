enum CircuitBreakerLevel { none, warning, critical, halted }

class RiskState {
  final CircuitBreakerLevel circuitBreaker;
  final double portfolioHeat;
  final double maxDrawdown;
  final double currentDrawdown;
  final double dailyLossLimit;
  final double dailyLossUsed;
  final double positionLimit;
  final double currentPositions;
  final bool killSwitchActive;
  final DateTime? killSwitchActivatedAt;
  final String? killSwitchReason;
  final Map<String, dynamic> exposure;
  final List<RiskAlert> alerts;

  RiskState({
    required this.circuitBreaker,
    required this.portfolioHeat,
    required this.maxDrawdown,
    required this.currentDrawdown,
    required this.dailyLossLimit,
    required this.dailyLossUsed,
    required this.positionLimit,
    required this.currentPositions,
    required this.killSwitchActive,
    this.killSwitchActivatedAt,
    this.killSwitchReason,
    required this.exposure,
    required this.alerts,
  });

  factory RiskState.fromJson(Map<String, dynamic> json) {
    try {
      return RiskState(
        circuitBreaker: _parseBreaker(json['circuit_breaker'] ?? json['level']),
        portfolioHeat: _toDouble(json['portfolio_heat']),
        maxDrawdown: _toDouble(json['max_drawdown']),
        currentDrawdown: _toDouble(json['current_drawdown'] ?? json['drawdown_pct']),
        dailyLossLimit: _toDouble(json['daily_loss_limit']),
        dailyLossUsed: _toDouble(json['daily_loss_used']),
        positionLimit: _toDouble(json['position_limit']),
        currentPositions: _toDouble(json['current_positions'] ?? json['open_positions']),
        killSwitchActive: json['kill_switch_active'] ?? false,
        killSwitchActivatedAt: json['kill_switch_activated_at'] != null
            ? DateTime.tryParse(json['kill_switch_activated_at'])
            : null,
        killSwitchReason: json['kill_switch_reason'],
        exposure: json['exposure'] is Map
            ? Map<String, dynamic>.from(json['exposure'])
            : {},
        alerts: _parseAlerts(json['alerts']),
      );
    } catch (_) {
      return RiskState(
        circuitBreaker: CircuitBreakerLevel.none,
        portfolioHeat: 0,
        maxDrawdown: 0,
        currentDrawdown: 0,
        dailyLossLimit: 0,
        dailyLossUsed: 0,
        positionLimit: 0,
        currentPositions: 0,
        killSwitchActive: json['kill_switch_active'] ?? false,
        exposure: {},
        alerts: [],
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static List<RiskAlert> _parseAlerts(dynamic alerts) {
    if (alerts is List) {
      return alerts.map((e) {
        if (e is Map<String, dynamic>) return RiskAlert.fromJson(e);
        return RiskAlert(id: '', level: 'info', message: e.toString(), timestamp: DateTime.now());
      }).toList();
    }
    return [];
  }

  static CircuitBreakerLevel _parseBreaker(dynamic s) {
    final str = s?.toString().toLowerCase();
    switch (str) {
      case 'warning':
      case 'yellow':
        return CircuitBreakerLevel.warning;
      case 'critical':
      case 'red':
        return CircuitBreakerLevel.critical;
      case 'halted':
      case 'halt':
        return CircuitBreakerLevel.halted;
      case 'green':
      case 'none':
      case 'ok':
        return CircuitBreakerLevel.none;
      default:
        return CircuitBreakerLevel.none;
    }
  }

  double get dailyLossPercent =>
      dailyLossLimit > 0 ? dailyLossUsed / dailyLossLimit : 0;
}

class RiskAlert {
  final String id;
  final String level;
  final String message;
  final DateTime timestamp;

  RiskAlert({
    required this.id,
    required this.level,
    required this.message,
    required this.timestamp,
  });

  factory RiskAlert.fromJson(Map<String, dynamic> json) {
    try {
      return RiskAlert(
        id: json['id']?.toString() ?? '',
        level: json['level'] ?? json['severity'] ?? 'info',
        message: json['message'] ?? json['text'] ?? '',
        timestamp: DateTime.tryParse(json['timestamp'] ?? json['created_at'] ?? '') ?? DateTime.now(),
      );
    } catch (_) {
      return RiskAlert(
        id: '',
        level: 'info',
        message: json.toString(),
        timestamp: DateTime.now(),
      );
    }
  }
}
