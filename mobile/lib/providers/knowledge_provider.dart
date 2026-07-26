import 'package:flutter/material.dart';
import '../models/knowledge.dart';
import '../services/api_service.dart';

class KnowledgeProvider extends ChangeNotifier {
  final ApiService _api;

  KnowledgeProvider(this._api);

  bool _loading = false;
  String? _error;
  List<KnowledgeResult> _results = [];
  String _query = '';
  int _resultCount = 0;

  bool get loading => _loading;
  String? get error => _error;
  List<KnowledgeResult> get results => _results;
  String get query => _query;
  int get resultCount => _resultCount;

  Future<void> search(String q) async {
    if (q.trim().isEmpty) return;
    _loading = true;
    _error = null;
    _query = q;
    notifyListeners();

    try {
      final data = await _api.searchKnowledge(q);
      _results = (data['results'] as List<dynamic>?)
              ?.map((e) => KnowledgeResult.fromJson(e))
              .toList() ??
          [];
      _resultCount = data['count'] ?? _results.length;
    } catch (e) {
      _error = e.toString();
      _results = [];
    }

    _loading = false;
    notifyListeners();
  }

  void clear() {
    _results = [];
    _query = '';
    _error = null;
    _resultCount = 0;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
