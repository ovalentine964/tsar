import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'api_service.dart';

/// Real-time WebSocket price streaming service.
///
/// Connects to the TSAR WebSocket endpoint for live price updates,
/// trade fills, and risk alerts instead of polling.
class WebSocketService extends ChangeNotifier {
  final ApiService _api;

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _reconnectTimer;
  Timer? _heartbeatTimer;

  bool _connected = false;
  bool _disposed = false;
  int _reconnectAttempts = 0;
  static const int _maxReconnectAttempts = 10;
  static const Duration _heartbeatInterval = Duration(seconds: 30);

  // Latest price data: symbol → price
  final Map<String, PriceTick> _prices = {};
  // Stream controllers for different event types
  final StreamController<PriceTick> _priceController =
      StreamController<PriceTick>.broadcast();
  final StreamController<TradeFillEvent> _tradeFillController =
      StreamController<TradeFillEvent>.broadcast();
  final StreamController<RiskAlertEvent> _riskAlertController =
      StreamController<RiskAlertEvent>.broadcast();

  WebSocketService(this._api);

  bool get connected => _connected;
  Map<String, PriceTick> get prices => Map.unmodifiable(_prices);
  Stream<PriceTick> get priceStream => _priceController.stream;
  Stream<TradeFillEvent> get tradeFillStream => _tradeFillController.stream;
  Stream<RiskAlertEvent> get riskAlertStream => _riskAlertController.stream;

  /// Connect to the WebSocket endpoint derived from the API base URL.
  void connect() {
    if (_connected || _disposed) return;

    try {
      final baseHttp = _api.isConfigured ? _getBaseUrl() : null;
      if (baseHttp == null) return;

      // Convert http(s) → ws(s)
      final wsUrl = baseHttp
          .replaceFirst('https://', 'wss://')
          .replaceFirst('http://', 'ws://');
      final uri = Uri.parse('$wsUrl/ws');

      _channel = WebSocketChannel.connect(uri);
      _subscription = _channel!.stream.listen(
        _onMessage,
        onError: _onError,
        onDone: _onDone,
      );

      _connected = true;
      _reconnectAttempts = 0;
      _startHeartbeat();
      notifyListeners();
    } catch (e) {
      _scheduleReconnect();
    }
  }

  void _onMessage(dynamic data) {
    try {
      final json = jsonDecode(data as String) as Map<String, dynamic>;
      final type = json['type'] as String?;

      switch (type) {
        case 'price':
          final tick = PriceTick.fromJson(json);
          _prices[tick.symbol] = tick;
          _priceController.add(tick);
          notifyListeners();
          break;
        case 'trade_fill':
          final fill = TradeFillEvent.fromJson(json);
          _tradeFillController.add(fill);
          break;
        case 'risk_alert':
          final alert = RiskAlertEvent.fromJson(json);
          _riskAlertController.add(alert);
          break;
        case 'pong':
          // Heartbeat response
          break;
        default:
          debugPrint('WS unknown message type: $type');
      }
    } catch (e) {
      debugPrint('WS message parse error: $e');
    }
  }

  void _onError(Object error) {
    debugPrint('WS error: $error');
    _connected = false;
    notifyListeners();
    _scheduleReconnect();
  }

  void _onDone() {
    debugPrint('WS connection closed');
    _connected = false;
    _heartbeatTimer?.cancel();
    notifyListeners();
    if (!_disposed) _scheduleReconnect();
  }

  void _startHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(_heartbeatInterval, (_) {
      try {
        _channel?.sink.add(jsonEncode({'type': 'ping'}));
      } catch (_) {
        _onDone();
      }
    });
  }

  void _scheduleReconnect() {
    if (_disposed || _reconnectAttempts >= _maxReconnectAttempts) return;
    _reconnectTimer?.cancel();
    final delay = Duration(seconds: (2 * (_reconnectAttempts + 1)).clamp(2, 60));
    _reconnectAttempts++;
    debugPrint('WS reconnecting in ${delay.inSeconds}s (attempt $_reconnectAttempts)');
    _reconnectTimer = Timer(delay, connect);
  }

  String? _getBaseUrl() {
    // Extract base URL from ApiService (reflection not available, use a helper)
    // The ApiService.configure() stores the URL internally.
    // We access it through a stored copy.
    return _api.baseUrl;
  }

  void disconnect() {
    _heartbeatTimer?.cancel();
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    _channel = null;
    _connected = false;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    disconnect();
    _priceController.close();
    _tradeFillController.close();
    _riskAlertController.close();
    super.dispose();
  }
}

/// Real-time price tick for a symbol.
class PriceTick {
  final String symbol;
  final double price;
  final double? change;
  final double? changePercent;
  final double? volume;
  final DateTime timestamp;

  PriceTick({
    required this.symbol,
    required this.price,
    this.change,
    this.changePercent,
    this.volume,
    required this.timestamp,
  });

  factory PriceTick.fromJson(Map<String, dynamic> json) {
    return PriceTick(
      symbol: json['symbol'] ?? '',
      price: _toDouble(json['price']),
      change: json['change'] != null ? _toDouble(json['change']) : null,
      changePercent: json['change_percent'] != null ? _toDouble(json['change_percent']) : null,
      volume: json['volume'] != null ? _toDouble(json['volume']) : null,
      timestamp: DateTime.tryParse(json['timestamp'] ?? '') ?? DateTime.now(),
    );
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }
}

class TradeFillEvent {
  final String tradeId;
  final String symbol;
  final String side;
  final double price;
  final double quantity;
  final DateTime timestamp;

  TradeFillEvent({
    required this.tradeId,
    required this.symbol,
    required this.side,
    required this.price,
    required this.quantity,
    required this.timestamp,
  });

  factory TradeFillEvent.fromJson(Map<String, dynamic> json) {
    return TradeFillEvent(
      tradeId: json['trade_id']?.toString() ?? '',
      symbol: json['symbol'] ?? '',
      side: json['side'] ?? 'buy',
      price: _toDouble(json['price']),
      quantity: _toDouble(json['quantity']),
      timestamp: DateTime.tryParse(json['timestamp'] ?? '') ?? DateTime.now(),
    );
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }
}

class RiskAlertEvent {
  final String level;
  final String message;
  final DateTime timestamp;

  RiskAlertEvent({
    required this.level,
    required this.message,
    required this.timestamp,
  });

  factory RiskAlertEvent.fromJson(Map<String, dynamic> json) {
    return RiskAlertEvent(
      level: json['level'] ?? 'info',
      message: json['message'] ?? '',
      timestamp: DateTime.tryParse(json['timestamp'] ?? '') ?? DateTime.now(),
    );
  }
}
