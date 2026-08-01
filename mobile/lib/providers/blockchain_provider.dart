import 'package:flutter/material.dart';
import '../models/scenario.dart';
import '../services/api_service.dart';

class BlockchainProvider extends ChangeNotifier {
  final ApiService _api;

  BlockchainProvider(this._api);

  bool _loading = false;
  String? _error;
  List<Scenario> _scenarios = [];
  List<OnChainRule> _rules = [];
  List<AuditEntry> _auditTrail = [];

  bool get loading => _loading;
  String? get error => _error;
  List<Scenario> get scenarios => _scenarios;
  List<OnChainRule> get rules => _rules;
  List<AuditEntry> get auditTrail => _auditTrail;

  List<Scenario> get triggeredScenarios =>
      _scenarios.where((s) => s.isTriggered).toList();

  List<Scenario> get activeScenarios =>
      _scenarios.where((s) => s.isActive).toList();

  int get activeRuleCount => _rules.where((r) => r.isActive).length;

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getScenarios(),
        _api.getOnChainRules(),
        _api.getAuditTrail(),
      ], eagerError: false);

      _scenarios = (results[0]['scenarios'] as List<dynamic>?)
              ?.map((e) => Scenario.fromJson(e))
              .toList() ??
          [];
      _rules = (results[1]['rules'] as List<dynamic>?)
              ?.map((e) => OnChainRule.fromJson(e))
              .toList() ??
          [];
      _auditTrail = (results[2]['entries'] as List<dynamic>?)
              ?.map((e) => AuditEntry.fromJson(e))
              .toList() ??
          [];
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
