import 'package:flutter/material.dart';
import '../models/mandate.dart';
import '../services/api_service.dart';

class MandateProvider extends ChangeNotifier {
  final ApiService _api;

  MandateProvider(this._api);

  bool _loading = false;
  String? _error;
  Mandate? _mandate;
  bool _commitLoading = false;
  bool _revokeLoading = false;

  bool get loading => _loading;
  String? get error => _error;
  Mandate? get mandate => _mandate;
  bool get commitLoading => _commitLoading;
  bool get revokeLoading => _revokeLoading;

  bool get isActive => _mandate?.isActive ?? false;

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _api.getMandate();
      _mandate = Mandate.fromJson(data);
    } catch (e) {
      _error = e.toString();
    }

    _loading = false;
    notifyListeners();
  }

  Future<bool> commitMandate({String? name, List<Map<String, dynamic>>? rules}) async {
    _commitLoading = true;
    _error = null;
    notifyListeners();

    try {
      final body = <String, dynamic>{};
      if (name != null) body['name'] = name;
      if (rules != null) body['rules'] = rules;
      await _api.commitMandate(body);
      await refresh();
      _commitLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString();
      _commitLoading = false;
      notifyListeners();
      return false;
    }
  }

  Future<bool> revokeMandate({String? reason}) async {
    _revokeLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _api.revokeMandate('current', reason: reason);
      await refresh();
      _revokeLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString();
      _revokeLoading = false;
      notifyListeners();
      return false;
    }
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
