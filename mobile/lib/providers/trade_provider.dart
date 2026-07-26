import 'package:flutter/material.dart';
import '../models/trade.dart';
import '../services/api_service.dart';

class TradeProvider extends ChangeNotifier {
  final ApiService _api;

  TradeProvider(this._api);

  bool _loading = false;
  String? _error;
  List<Trade> _trades = [];
  TradeStats? _stats;
  String? _filterSymbol;
  String? _filterStatus;
  int _total = 0;
  bool _hasMore = true;

  bool get loading => _loading;
  String? get error => _error;
  List<Trade> get trades => _trades;
  TradeStats? get stats => _stats;
  String? get filterSymbol => _filterSymbol;
  String? get filterStatus => _filterStatus;
  int get total => _total;
  bool get hasMore => _hasMore;

  void setFilter({String? symbol, String? status}) {
    _filterSymbol = symbol;
    _filterStatus = status;
    _trades = [];
    refresh();
  }

  Future<void> refresh() async {
    _loading = true;
    _error = null;
    _trades = [];
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getTrades(
          symbol: _filterSymbol,
          status: _filterStatus,
          limit: 50,
          offset: 0,
        ),
        _api.getTradeStats(),
      ], eagerError: false);

      final tradeData = results[0];
      _trades = (tradeData['trades'] as List<dynamic>?)
              ?.map((e) => Trade.fromJson(e))
              .toList() ??
          [];
      _total = tradeData['total'] ?? tradeData['count'] ?? _trades.length;
      _hasMore = _trades.length >= 50;
      _stats = TradeStats.fromJson(results[1]);
    } catch (e) {
      _error = e.toString();
    }

    _loading = false;
    notifyListeners();
  }

  Future<void> loadMore() async {
    if (_loading || !_hasMore) return;
    try {
      final data = await _api.getTrades(
        symbol: _filterSymbol,
        status: _filterStatus,
        limit: 50,
        offset: _trades.length,
      );
      final more = (data['trades'] as List<dynamic>?)
              ?.map((e) => Trade.fromJson(e))
              .toList() ??
          [];
      _trades.addAll(more);
      _hasMore = more.length >= 50;
      notifyListeners();
    } catch (e) {
      // silently fail on load-more
    }
  }

  Future<Trade?> getTradeDetail(String id) async {
    try {
      final data = await _api.getTradeDetail(id);
      return Trade.fromJson(data);
    } catch (e) {
      return null;
    }
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
