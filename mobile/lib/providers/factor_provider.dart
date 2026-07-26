import 'package:flutter/material.dart';
import '../models/factor.dart';
import '../services/api_service.dart';

class FactorProvider extends ChangeNotifier {
  final ApiService _api;

  FactorProvider(this._api);

  bool _loading = false;
  String? _error;
  List<Factor> _factors = [];
  List<FactorCategory> _categories = [];
  String? _selectedCategory;

  bool get loading => _loading;
  String? get error => _error;
  List<Factor> get factors => _selectedCategory == null
      ? _factors
      : _factors.where((f) => f.category == _selectedCategory).toList();
  List<FactorCategory> get categories => _categories;
  String? get selectedCategory => _selectedCategory;

  List<Factor> get factorsByIC =>
      List<Factor>.from(factors)..sort((a, b) => b.ic.abs().compareTo(a.ic.abs()));

  List<Factor> get factorsByIR =>
      List<Factor>.from(factors)..sort((a, b) => b.ir.abs().compareTo(a.ir.abs()));

  void setCategory(String? category) {
    _selectedCategory = category;
    notifyListeners();
  }

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _api.getFactors();
      _factors = (data['factors'] as List<dynamic>?)
              ?.map((e) => Factor.fromJson(e))
              .toList() ??
          [];

      // Build categories from factors
      final catMap = <String, int>{};
      for (final f in _factors) {
        catMap[f.category] = (catMap[f.category] ?? 0) + 1;
      }
      _categories = catMap.entries
          .map((e) => FactorCategory(
                name: e.key,
                description: '',
                count: e.value,
              ))
          .toList();
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
