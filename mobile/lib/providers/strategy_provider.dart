import 'package:flutter/material.dart';
import '../models/strategy.dart';
import '../services/api_service.dart';

class StrategyProvider extends ChangeNotifier {
  final ApiService _api;

  StrategyProvider(this._api);

  bool _loading = false;
  String? _error;
  List<Strategy> _strategies = [];
  BacktestResult? _lastBacktest;
  bool _backtestLoading = false;

  bool get loading => _loading;
  String? get error => _error;
  List<Strategy> get strategies => _strategies;
  BacktestResult? get lastBacktest => _lastBacktest;
  bool get backtestLoading => _backtestLoading;

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _api.getStrategies();
      _strategies = (data['strategies'] as List<dynamic>?)
              ?.map((e) => Strategy.fromJson(e))
              .toList() ??
          [];
    } catch (e) {
      _error = e.toString();
    }

    _loading = false;
    notifyListeners();
  }

  Future<Strategy?> getDetail(String id) async {
    try {
      final data = await _api.getStrategyDetail(id);
      return Strategy.fromJson(data);
    } catch (e) {
      return null;
    }
  }

  Future<bool> runBacktest(String strategyId,
      {Map<String, dynamic>? params}) async {
    _backtestLoading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _api.runBacktest(strategyId, params: params);
      _lastBacktest = BacktestResult.fromJson(data);
      _backtestLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString();
      _backtestLoading = false;
      notifyListeners();
      return false;
    }
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
