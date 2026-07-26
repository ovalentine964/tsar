import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';

class SettingsProvider extends ChangeNotifier {
  static const _keyDarkMode = 'dark_mode';
  static const _keyBaseUrl = 'api_base_url';
  static const _keyAutoRefresh = 'auto_refresh';
  static const _keyRefreshInterval = 'refresh_interval';
  static const _keyApiKeySecure = 'tsar_api_key';

  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();
  final ApiService _apiService;

  bool _isDarkMode = true;
  String _baseUrl = 'http://localhost:8000';
  String? _apiKey;
  bool _autoRefresh = true;
  int _refreshIntervalSeconds = 30;

  bool get isDarkMode => _isDarkMode;
  String get baseUrl => _baseUrl;
  String? get apiKey => _apiKey;
  bool get autoRefresh => _autoRefresh;
  int get refreshIntervalSeconds => _refreshIntervalSeconds;

  SettingsProvider(this._apiService) {
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    _isDarkMode = prefs.getBool(_keyDarkMode) ?? true;
    _baseUrl = prefs.getString(_keyBaseUrl) ?? 'http://localhost:8000';
    _autoRefresh = prefs.getBool(_keyAutoRefresh) ?? true;
    _refreshIntervalSeconds = prefs.getInt(_keyRefreshInterval) ?? 30;

    // Read API key from secure storage
    try {
      _apiKey = await _secureStorage.read(key: _keyApiKeySecure);
    } catch (_) {
      _apiKey = null;
    }

    // Configure ApiService with loaded settings
    _apiService.configure(baseUrl: _baseUrl, apiKey: _apiKey);

    notifyListeners();
  }

  Future<void> setDarkMode(bool value) async {
    _isDarkMode = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_keyDarkMode, value);
    notifyListeners();
  }

  Future<void> setBaseUrl(String url) async {
    _baseUrl = url;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyBaseUrl, url);
    _apiService.configure(baseUrl: _baseUrl, apiKey: _apiKey);
    notifyListeners();
  }

  Future<void> setApiKey(String? key) async {
    _apiKey = key;
    try {
      if (key != null) {
        await _secureStorage.write(key: _keyApiKeySecure, value: key);
      } else {
        await _secureStorage.delete(key: _keyApiKeySecure);
      }
    } catch (_) {
      // Fallback: if secure storage fails, still update in-memory
    }
    _apiService.configure(baseUrl: _baseUrl, apiKey: _apiKey);
    notifyListeners();
  }

  Future<void> setAutoRefresh(bool value) async {
    _autoRefresh = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_keyAutoRefresh, value);
    notifyListeners();
  }

  Future<void> setRefreshInterval(int seconds) async {
    _refreshIntervalSeconds = seconds;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_keyRefreshInterval, seconds);
    notifyListeners();
  }
}
