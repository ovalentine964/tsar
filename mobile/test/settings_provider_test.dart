import 'package:flutter_test/flutter_test.dart';
import 'package:tsar_mobile/services/api_service.dart';
import 'package:tsar_mobile/providers/settings_provider.dart';

void main() {
  group('SettingsProvider defaults', () {
    late SettingsProvider provider;

    setUp(() {
      // SettingsProvider reads from SharedPreferences/SecureStorage on
      // construction. In test environment those are empty, so defaults apply.
      provider = SettingsProvider(ApiService());
    });

    test('dark mode defaults to true', () {
      expect(provider.isDarkMode, isTrue);
    });

    test('baseUrl defaults to tsar-api.onrender.com', () {
      expect(provider.baseUrl, 'https://tsar-api.onrender.com');
    });

    test('autoRefresh defaults to true', () {
      expect(provider.autoRefresh, isTrue);
    });

    test('refreshIntervalSeconds defaults to 30', () {
      expect(provider.refreshIntervalSeconds, 30);
    });

    test('apiKey is null by default', () {
      expect(provider.apiKey, isNull);
    });

    test('initialized becomes true after load completes', () async {
      // Wait for the async _load() to finish
      await provider.ready;
      expect(provider.initialized, isTrue);
    });

    test('setDarkMode toggles value', () async {
      await provider.setDarkMode(false);
      expect(provider.isDarkMode, isFalse);
      await provider.setDarkMode(true);
      expect(provider.isDarkMode, isTrue);
    });

    test('setBaseUrl updates the value', () async {
      await provider.setBaseUrl('https://custom.api.com');
      expect(provider.baseUrl, 'https://custom.api.com');
    });

    test('setAutoRefresh toggles value', () async {
      await provider.setAutoRefresh(false);
      expect(provider.autoRefresh, isFalse);
    });

    test('setRefreshInterval updates value', () async {
      await provider.setRefreshInterval(60);
      expect(provider.refreshIntervalSeconds, 60);
    });
  });
}
