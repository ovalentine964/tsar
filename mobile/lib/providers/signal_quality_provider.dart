import 'package:flutter/material.dart';
import '../models/signal_quality.dart';
import '../services/api_service.dart';

class SignalQualityProvider extends ChangeNotifier {
  final ApiService _api;

  SignalQualityProvider(this._api);

  bool _loading = false;
  String? _error;
  List<SignalQuality> _signals = [];
  SignalQuality? _latest;

  bool get loading => _loading;
  String? get error => _error;
  List<SignalQuality> get signals => _signals;
  SignalQuality? get latest => _latest;

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _api.getSignalQuality();
      _signals = (data['signals'] as List<dynamic>?)
              ?.map((e) => SignalQuality.fromJson(e))
              .toList() ??
          [];
      if (_signals.isNotEmpty) {
        _latest = _signals.first;
      }
    } catch (e) {
      _error = e.toString();
    }

    _loading = false;
    notifyListeners();
  }

  Future<SignalQuality?> evaluate(String symbol) async {
    try {
      final data = await _api.evaluateSignal(symbol);
      final signal = SignalQuality.fromJson(data);
      _signals.insert(0, signal);
      _latest = signal;
      notifyListeners();
      return signal;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return null;
    }
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
