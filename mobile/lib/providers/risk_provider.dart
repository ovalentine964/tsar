import 'package:flutter/material.dart';
import '../models/risk.dart';
import '../services/api_service.dart';

class RiskProvider extends ChangeNotifier {
  final ApiService _api;

  RiskProvider(this._api);

  bool _loading = false;
  String? _error;
  RiskState? _riskState;
  bool _killSwitchLoading = false;

  bool get loading => _loading;
  String? get error => _error;
  RiskState? get riskState => _riskState;
  bool get killSwitchLoading => _killSwitchLoading;

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _api.getRiskState();
      _riskState = RiskState.fromJson(data);
    } catch (e) {
      _error = e.toString();
    }

    _loading = false;
    notifyListeners();
  }

  Future<bool> activateKillSwitch({String? reason}) async {
    _killSwitchLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _api.activateKillSwitch(reason: reason);
      await refresh();
      _killSwitchLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString();
      _killSwitchLoading = false;
      notifyListeners();
      return false;
    }
  }

  Future<bool> deactivateKillSwitch() async {
    _killSwitchLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _api.deactivateKillSwitch();
      await refresh();
      _killSwitchLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString();
      _killSwitchLoading = false;
      notifyListeners();
      return false;
    }
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
