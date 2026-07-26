import 'package:flutter/material.dart';
import '../models/trade.dart';
import '../models/position.dart';
import '../models/knowledge.dart';
import '../services/api_service.dart';

class DashboardProvider extends ChangeNotifier {
  final ApiService _api;

  DashboardProvider(this._api);

  bool _loading = false;
  String? _error;
  TradeStats? _stats;
  PnlSummary? _pnl;
  FlywheelHealth? _flywheel;
  MarketRegime? _regime;
  int _openPositions = 0;
  bool _killSwitchActive = false;

  bool get loading => _loading;
  String? get error => _error;
  TradeStats? get stats => _stats;
  PnlSummary? get pnl => _pnl;
  FlywheelHealth? get flywheel => _flywheel;
  MarketRegime? get regime => _regime;
  int get openPositions => _openPositions;
  bool get killSwitchActive => _killSwitchActive;

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getDashboard(),
        _api.getPnlSummary(),
        _api.getFlywheelHealth(),
        _api.getMarketRegime(),
        _api.getTradeStats(),
      ], eagerError: false);

      final dashData = results[0];
      _openPositions = dashData['open_positions'] ?? dashData['trades']?['total'] ?? 0;
      _killSwitchActive = dashData['kill_switch']?['active'] ?? false;

      _pnl = PnlSummary.fromJson(results[1]);
      _flywheel = FlywheelHealth.fromJson(results[2]);
      _regime = MarketRegime.fromJson(results[3]);
      _stats = TradeStats.fromJson(results[4]);
    } catch (e) {
      _error = e.toString();
    }

    _loading = false;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
