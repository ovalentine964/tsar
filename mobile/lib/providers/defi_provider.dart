import 'package:flutter/material.dart';
import '../models/defi_position.dart';
import '../services/api_service.dart';

class DeFiProvider extends ChangeNotifier {
  final ApiService _api;

  DeFiProvider(this._api);

  bool _loading = false;
  String? _error;
  List<DeFiPosition> _positions = [];
  DeFiYieldSummary? _summary;

  bool get loading => _loading;
  String? get error => _error;
  List<DeFiPosition> get positions => _positions;
  DeFiYieldSummary? get summary => _summary;

  List<DeFiPosition> get activePositions =>
      _positions.where((p) => p.isActive).toList();

  double get totalValueUsd =>
      _positions.fold(0, (sum, p) => sum + p.valueUsd);

  double get totalYieldEarned =>
      _positions.fold(0, (sum, p) => sum + p.yieldEarned);

  Map<String, List<DeFiPosition>> get positionsByChain {
    final map = <String, List<DeFiPosition>>{};
    for (final p in _positions) {
      map.putIfAbsent(p.chain, () => []).add(p);
    }
    return map;
  }

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getDeFiPositions(),
        _api.getDeFiYield(),
      ], eagerError: false);

      _positions = (results[0]['positions'] as List<dynamic>?)
              ?.map((e) => DeFiPosition.fromJson(e))
              .toList() ??
          [];
      _summary = DeFiYieldSummary.fromJson(results[1]);
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
