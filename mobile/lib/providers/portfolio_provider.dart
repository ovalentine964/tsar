import 'package:flutter/material.dart';
import '../models/position.dart';
import '../services/api_service.dart';

class PortfolioProvider extends ChangeNotifier {
  final ApiService _api;

  PortfolioProvider(this._api);

  bool _loading = false;
  String? _error;
  List<Position> _positions = [];
  PnlSummary? _pnl;

  bool get loading => _loading;
  String? get error => _error;
  List<Position> get positions => _positions;
  PnlSummary? get pnl => _pnl;

  double get totalMarketValue =>
      _positions.fold(0, (sum, p) => sum + p.marketValue);

  double get totalUnrealizedPnl =>
      _positions.fold(0, (sum, p) => sum + p.unrealizedPnl);

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getDashboard(),
        _api.getPnlSummary(),
      ], eagerError: false);

      _positions = (results[0]['positions'] as List<dynamic>?)
              ?.map((e) => Position.fromJson(e))
              .toList() ??
          [];
      _pnl = PnlSummary.fromJson(results[1]);
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
