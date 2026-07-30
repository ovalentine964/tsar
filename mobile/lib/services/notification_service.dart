import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Push notification service for TSAR.
///
/// Handles trade fill alerts, risk alerts, and regime change notifications.
/// Uses platform-specific notification APIs (flutter_local_notifications)
/// with Firebase Cloud Messaging for push delivery.
///
/// For MVP, uses local notifications. FCM integration requires
/// firebase_core and firebase_messaging packages + platform setup.
class NotificationService {
  static const MethodChannel _channel =
      MethodChannel('com.tsar/notifications');

  bool _initialized = false;
  final StreamController<NotificationPayload> _onNotification =
      StreamController<NotificationPayload>.broadcast();

  Stream<NotificationPayload> get onNotification => _onNotification.stream;
  bool get initialized => _initialized;

  /// Initialize the notification system.
  /// Requests permissions on iOS, creates notification channels on Android.
  Future<void> initialize() async {
    if (_initialized) return;
    try {
      // Request permissions
      if (Platform.isIOS) {
        await _channel.invokeMethod('requestPermission');
      } else if (Platform.isAndroid) {
        await _channel.invokeMethod('createChannels', {
          'channels': [
            {
              'id': 'trade_fills',
              'name': 'Trade Fills',
              'description': 'Notifications for trade executions',
              'importance': 'high',
            },
            {
              'id': 'risk_alerts',
              'name': 'Risk Alerts',
              'description': 'Risk threshold and circuit breaker alerts',
              'importance': 'max',
            },
            {
              'id': 'regime_changes',
              'name': 'Regime Changes',
              'description': 'Market regime change notifications',
              'importance': 'default',
            },
          ],
        });
      }

      // Listen for notification taps
      _channel.setMethodCallHandler(_handleMethodCall);
      _initialized = true;
    } catch (e) {
      debugPrint('Notification init failed: $e');
      // Notifications are non-critical; app still works without them
      _initialized = false;
    }
  }

  Future<dynamic> _handleMethodCall(MethodCall call) async {
    switch (call.method) {
      case 'onNotificationTapped':
        final payload = NotificationPayload.fromMap(
          Map<String, dynamic>.from(call.arguments),
        );
        _onNotification.add(payload);
        break;
    }
  }

  /// Show a local notification for a trade fill.
  Future<void> showTradeFill({
    required String symbol,
    required String side,
    required double price,
    required double quantity,
  }) async {
    if (!_initialized) return;
    try {
      await _channel.invokeMethod('showNotification', {
        'channelId': 'trade_fills',
        'title': 'Trade Fill: $symbol',
        'body': '${side.toUpperCase()} ${quantity.toStringAsFixed(4)} @ \$${price.toStringAsFixed(2)}',
        'payload': 'trade_fill:$symbol',
        'importance': 'high',
      });
    } catch (e) {
      debugPrint('Trade fill notification failed: $e');
    }
  }

  /// Show a local notification for a risk alert.
  Future<void> showRiskAlert({
    required String level,
    required String message,
  }) async {
    if (!_initialized) return;
    try {
      final icon = level == 'critical' ? '🔴' : level == 'warning' ? '🟡' : 'ℹ️';
      await _channel.invokeMethod('showNotification', {
        'channelId': 'risk_alerts',
        'title': '$icon Risk Alert: ${level.toUpperCase()}',
        'body': message,
        'payload': 'risk_alert:$level',
        'importance': level == 'critical' ? 'max' : 'high',
      });
    } catch (e) {
      debugPrint('Risk alert notification failed: $e');
    }
  }

  /// Show a local notification for a regime change.
  Future<void> showRegimeChange({
    required String newRegime,
    required double confidence,
  }) async {
    if (!_initialized) return;
    try {
      await _channel.invokeMethod('showNotification', {
        'channelId': 'regime_changes',
        'title': 'Market Regime Change',
        'body': 'Regime: ${newRegime.toUpperCase()} (${(confidence * 100).toStringAsFixed(0)}% confidence)',
        'payload': 'regime_change:$newRegime',
        'importance': 'default',
      });
    } catch (e) {
      debugPrint('Regime change notification failed: $e');
    }
  }

  /// Subscribe to FCM topic for push notifications.
  Future<void> subscribeToTopic(String topic) async {
    try {
      await _channel.invokeMethod('subscribeTopic', {'topic': topic});
    } catch (e) {
      debugPrint('Topic subscribe failed: $e');
    }
  }

  void dispose() {
    _onNotification.close();
  }
}

class NotificationPayload {
  final String type;
  final String data;

  NotificationPayload({required this.type, required this.data});

  factory NotificationPayload.fromMap(Map<String, dynamic> map) {
    final payload = map['payload'] as String? ?? '';
    final parts = payload.split(':');
    return NotificationPayload(
      type: parts.isNotEmpty ? parts[0] : 'unknown',
      data: parts.length > 1 ? parts.sublist(1).join(':') : '',
    );
  }
}
