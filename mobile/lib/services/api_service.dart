import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiException implements Exception {
  final int? statusCode;
  final String message;
  ApiException(this.message, {this.statusCode});

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  String _baseUrl = 'https://tsar-api.onrender.com';
  String? _apiKey;
  Duration _timeout = const Duration(seconds: 15);
  bool _configured = false;

  /// Completes when [configure] has been called at least once.
  final Completer<void> _readyCompleter = Completer<void>();
  Future<void> get ready => _readyCompleter.future;

  bool get isConfigured => _configured;
  String get baseUrl => _baseUrl;

  void configure({required String baseUrl, String? apiKey, Duration? timeout}) {
    _baseUrl = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    _apiKey = apiKey;
    if (timeout != null) _timeout = timeout;
    _configured = true;
    if (!_readyCompleter.isCompleted) {
      _readyCompleter.complete();
    }
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_apiKey != null) 'Authorization': 'Bearer $_apiKey',
      };

  // ─── Generic HTTP helpers ────────────────────────────────────────────

  Future<Map<String, dynamic>> _get(String path, {Map<String, String>? queryParams}) async {
    await ready; // Block until configured
    final uri = Uri.parse('$_baseUrl$path').replace(queryParameters: queryParams);
    final resp = await http.get(uri, headers: _headers).timeout(_timeout);
    return _handleResponse(resp);
  }

  Future<Map<String, dynamic>> _post(String path, {Map<String, dynamic>? body}) async {
    await ready;
    final uri = Uri.parse('$_baseUrl$path');
    final resp = await http
        .post(uri, headers: _headers, body: jsonEncode(body ?? {}))
        .timeout(_timeout);
    return _handleResponse(resp);
  }

  Future<Map<String, dynamic>> _put(String path, {Map<String, dynamic>? body}) async {
    await ready;
    final uri = Uri.parse('$_baseUrl$path');
    final resp = await http
        .put(uri, headers: _headers, body: jsonEncode(body ?? {}))
        .timeout(_timeout);
    return _handleResponse(resp);
  }

  Future<Map<String, dynamic>> _delete(String path) async {
    await ready;
    final uri = Uri.parse('$_baseUrl$path');
    final resp = await http.delete(uri, headers: _headers).timeout(_timeout);
    return _handleResponse(resp);
  }

  Map<String, dynamic> _handleResponse(http.Response resp) {
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      if (resp.body.isEmpty) return {};
      return jsonDecode(resp.body) as Map<String, dynamic>;
    }
    throw ApiException(
      resp.body.isNotEmpty ? resp.body : 'Request failed',
      statusCode: resp.statusCode,
    );
  }

  // ─── Health / Dashboard ──────────────────────────────────────────────

  Future<Map<String, dynamic>> getHealth() => _get('/health');

  Future<Map<String, dynamic>> getDashboard() => _get('/');

  // ─── Trades ──────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getTrades({
    String? symbol,
    String? status,
    int? limit,
    int? offset,
  }) {
    final params = <String, String>{};
    if (symbol != null) params['symbol'] = symbol;
    if (status != null) params['status'] = status;
    if (limit != null) params['limit'] = limit.toString();
    if (offset != null) params['offset'] = offset.toString();
    return _get('/api/v1/trades', queryParams: params);
  }

  Future<Map<String, dynamic>> getTradeDetail(String tradeId) =>
      _get('/api/v1/trades/$tradeId');

  Future<Map<String, dynamic>> getTradeStats() => _get('/api/v1/trades/stats');

  // ─── P&L ─────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getPnlSummary() => _get('/api/v1/pnl');

  Future<Map<String, dynamic>> getPnlDaily({int? days}) {
    final params = <String, String>{};
    if (days != null) params['days'] = days.toString();
    return _get('/api/v1/pnl', queryParams: params);
  }

  // ─── Risk ────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getRiskState() => _get('/api/v1/risk');

  Future<Map<String, dynamic>> activateKillSwitch({String? reason}) =>
      _post('/api/v1/kill-switch', body: {
        if (reason != null) 'reason': reason,
      });

  Future<Map<String, dynamic>> deactivateKillSwitch() =>
      _post('/api/v1/resume');

  // ─── Mandate ─────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getMandate() => _get('/api/v1/mandate');

  Future<Map<String, dynamic>> commitMandate(Map<String, dynamic> mandate) =>
      _post('/api/v1/mandate/commit', body: mandate);

  Future<Map<String, dynamic>> revokeMandate(String mandateId,
          {String? reason}) =>
      _post('/api/v1/mandate/revoke',
          body: {'mandate_id': mandateId, if (reason != null) 'reason': reason});

  // ─── Factors ─────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getFactors({String? category}) {
    final params = <String, String>{};
    if (category != null) params['category'] = category;
    return _get('/api/v1/factors', queryParams: params);
  }

  Future<Map<String, dynamic>> getFactorDetail(String factorId) =>
      _get('/api/v1/factors/$factorId');

  Future<Map<String, dynamic>> getFactorCategories() =>
      _get('/api/v1/factors');

  Future<Map<String, dynamic>> benchmarkFactors() =>
      _get('/api/v1/factors/benchmark');

  Future<Map<String, dynamic>> getFactorsRank({String? sortBy}) {
    final params = <String, String>{};
    if (sortBy != null) params['sort'] = sortBy;
    return _get('/api/v1/factors/rank', queryParams: params);
  }

  // ─── Strategies ──────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getStrategies() => _get('/api/v1/strategies');

  Future<Map<String, dynamic>> getStrategyDetail(String strategyId) =>
      _get('/api/v1/strategies/$strategyId');

  Future<Map<String, dynamic>> runBacktest(String strategyId,
          {Map<String, dynamic>? params}) =>
      _post('/api/v1/backtest',
          body: {'strategy': strategyId, ...?params});

  Future<Map<String, dynamic>> activateStrategy(String strategyId) =>
      _post('/api/v1/strategies/$strategyId/activate');

  Future<Map<String, dynamic>> deactivateStrategy(String strategyId) =>
      _post('/api/v1/strategies/$strategyId/deactivate');

  // ─── Shadow Account ──────────────────────────────────────────────────

  Future<Map<String, dynamic>> getShadowRules() => _get('/api/v1/shadow/rules');

  Future<Map<String, dynamic>> triggerShadowExtraction() =>
      _post('/api/v1/shadow/extract');

  // ─── Knowledge ───────────────────────────────────────────────────────

  Future<Map<String, dynamic>> searchKnowledge(String query, {String? store}) {
    final params = <String, String>{'query': query};
    if (store != null) params['stores'] = store;
    return _get('/api/v1/knowledge/search', queryParams: params);
  }

  // ─── Patterns & Lessons ──────────────────────────────────────────────

  Future<Map<String, dynamic>> getPatterns() => _get('/api/v1/patterns');

  Future<Map<String, dynamic>> getLessons() => _get('/api/v1/lessons');

  // ─── Market Regime ───────────────────────────────────────────────────

  Future<Map<String, dynamic>> getMarketRegime() => _get('/api/v1/regime');

  // ─── Backends ────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getBackends() => _get('/api/v1/backends');

  // ─── Flywheel ────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getFlywheelHealth() =>
      _get('/api/v1/flywheel');

  // ─── News ────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getNews({String? symbol, int? limit}) {
    final params = <String, String>{};
    if (symbol != null) params['symbol'] = symbol;
    if (limit != null) params['limit'] = limit.toString();
    return _get('/api/v1/news', queryParams: params);
  }

  Future<Map<String, dynamic>> getNewsAlerts() => _get('/api/v1/news/alerts');

  // ─── Signal Quality ─────────────────────────────────────────────

  Future<Map<String, dynamic>> getSignalQuality({String? symbol}) {
    final params = <String, String>{};
    if (symbol != null) params['symbol'] = symbol;
    return _get('/api/v1/signals/quality', queryParams: params);
  }

  Future<Map<String, dynamic>> evaluateSignal(String symbol) =>
      _post('/api/v1/signals/evaluate', body: {'symbol': symbol});

  // ─── DeFi ───────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getDeFiPositions({String? chain}) {
    final params = <String, String>{};
    if (chain != null) params['chain'] = chain;
    return _get('/api/v1/defi/positions', queryParams: params);
  }

  Future<Map<String, dynamic>> getDeFiYield() => _get('/api/v1/defi/yield');

  // ─── Blockchain / On-Chain ──────────────────────────────────────

  Future<Map<String, dynamic>> getScenarios() => _get('/api/v1/scenarios');

  Future<Map<String, dynamic>> getOnChainRules() => _get('/api/v1/blockchain/rules');

  Future<Map<String, dynamic>> getAuditTrail({int? limit}) {
    final params = <String, String>{};
    if (limit != null) params['limit'] = limit.toString();
    return _get('/api/v1/blockchain/audit', queryParams: params);
  }

  // ─── Education ──────────────────────────────────────────────────

  Future<Map<String, dynamic>> getTradeEducation({String? category}) {
    final params = <String, String>{};
    if (category != null) params['category'] = category;
    return _get('/api/v1/education', queryParams: params);
  }
}
