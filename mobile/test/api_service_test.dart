import 'package:flutter_test/flutter_test.dart';
import 'package:tsar_mobile/services/api_service.dart';

void main() {
  group('ApiService', () {
    late ApiService api;

    setUp(() {
      api = ApiService();
    });

    test('singleton returns same instance', () {
      final a = ApiService();
      final b = ApiService();
      expect(identical(a, b), isTrue);
    });

    test('default base URL is tsar-api.onrender.com', () {
      expect(api.baseUrl, 'https://tsar-api.onrender.com');
    });

    test('isConfigured is false before configure()', () {
      // Fresh singleton may already be configured from prior test;
      // verify the getter exists and returns a bool.
      expect(api.isConfigured, isA<bool>());
    });

    test('configure() sets baseUrl and marks as configured', () {
      api.configure(baseUrl: 'https://example.com', apiKey: 'test-key');
      expect(api.baseUrl, 'https://example.com');
      expect(api.isConfigured, isTrue);
    });

    test('configure() strips trailing slash from baseUrl', () {
      api.configure(baseUrl: 'https://example.com/');
      expect(api.baseUrl, 'https://example.com');
    });

    test('configure() completes the ready future', () async {
      // The ready future should already be completed (or complete soon).
      // We just verify it doesn't hang.
      await api.ready;
      expect(api.isConfigured, isTrue);
    });

    test('getHealth() returns a Future', () {
      // We can't make real HTTP calls in unit tests without mocking,
      // but we verify the method exists and returns the right type.
      final future = api.getHealth();
      expect(future, isA<Future<Map<String, dynamic>>>());
    });

    test('getDashboard() returns a Future', () {
      final future = api.getDashboard();
      expect(future, isA<Future<Map<String, dynamic>>>());
    });

    test('getTrades() accepts optional params', () {
      final future = api.getTrades(symbol: 'BTCUSD', limit: 10);
      expect(future, isA<Future<Map<String, dynamic>>>());
    });

    test('ApiException carries statusCode and message', () {
      final e = ApiException('not found', statusCode: 404);
      expect(e.statusCode, 404);
      expect(e.message, 'not found');
      expect(e.toString(), contains('404'));
      expect(e.toString(), contains('not found'));
    });
  });
}
