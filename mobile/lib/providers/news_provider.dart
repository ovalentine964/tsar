import 'package:flutter/material.dart';
import '../models/news.dart';
import '../services/api_service.dart';

class NewsProvider extends ChangeNotifier {
  final ApiService _api;

  NewsProvider(this._api);

  bool _loading = false;
  String? _error;
  List<NewsItem> _items = [];
  List<NewsItem> _alerts = [];
  String? _filterSymbol;
  SentimentType? _filterSentiment;
  int _total = 0;

  bool get loading => _loading;
  String? get error => _error;
  List<NewsItem> get items => _filterSentiment != null
      ? _items.where((n) => n.sentiment == _filterSentiment).toList()
      : _items;
  List<NewsItem> get allItems => _items;
  List<NewsItem> get alerts => _alerts;
  String? get filterSymbol => _filterSymbol;
  SentimentType? get filterSentiment => _filterSentiment;
  int get total => _total;

  void setFilter({String? symbol, SentimentType? sentiment}) {
    _filterSymbol = symbol;
    _filterSentiment = sentiment;
    notifyListeners();
  }

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getNews(symbol: _filterSymbol),
        _api.getNewsAlerts(),
      ], eagerError: false);

      _items = (results[0]['news'] as List<dynamic>?)
              ?.map((e) => NewsItem.fromJson(e))
              .toList() ??
          [];
      _total = results[0]['total'] ?? _items.length;

      _alerts = (results[1]['alerts'] as List<dynamic>?)
              ?.map((e) => NewsItem.fromJson(e))
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
