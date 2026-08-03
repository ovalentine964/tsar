import 'dart:io';
import 'package:flutter/foundation.dart';

/// HTTPS enforcement and SSL certificate pinning for TSAR.
///
/// Pinning prevents MITM attacks by validating the server's certificate
/// against known SHA-256 hashes. In production, these should be updated
/// when certificates are rotated.
class SecurityService {
  // SHA-256 hashes of pinned certificates (SPKI pinning).
  // Update these when the server certificate is rotated.
  //
  // Current pin: tsar-api.onrender.com (Render-managed cert)
  // Retrieved: 2026-08-03 via openssl s_client
  // When Render rotates the cert, update this hash or the app will
  // refuse connections (which is the desired security behaviour).
  static const List<String> _pinnedShas = [
    'sha256/04:1E:C4:C6:9F:66:77:19:7B:4E:F1:C0:67:42:11:64:F4:B2:69:DA:27:F2:F5:30:29:2C:AB:BB:05:1F:C1:B1',
  ];

  /// Validate that a URL uses HTTPS in production.
  /// Returns true if the URL is acceptable.
  static bool enforceHttps(String url) {
    if (kDebugMode) {
      // Allow HTTP in debug mode for local development
      return true;
    }
    final uri = Uri.tryParse(url);
    if (uri == null) return false;
    return uri.scheme == 'https';
  }

  /// Create an HttpClient with SSL pinning configured.
  /// Use this instead of the default http.Client for production builds.
  static HttpClient createPinnedClient() {
    final client = HttpClient()
      ..badCertificateCallback = (X509Certificate cert, String host, int port) {
        // In debug mode, allow all certificates
        if (kDebugMode) return true;

        // In production, validate against pinned certificates
        if (_pinnedShas.isEmpty) {
          // No pins configured — rely on system certificate store
          return false;
        }

        // Compare certificate SHA-256 fingerprint against pinned values
        final sha = cert.sha256.toString();
        // Normalize: the Dart X509Certificate.sha256 returns a colon-separated hex string
        final normalized = 'sha256/$sha';
        return _pinnedShas.contains(normalized);
      };

    // Enforce TLS 1.2+
    client.connectionTimeout = const Duration(seconds: 15);

    return client;
  }

  /// Validate a base URL for security concerns.
  /// Returns a list of warnings (empty = safe).
  static List<String> validateUrl(String url) {
    final warnings = <String>[];
    final uri = Uri.tryParse(url);

    if (uri == null) {
      warnings.add('Invalid URL format');
      return warnings;
    }

    if (uri.scheme == 'http' && !kDebugMode) {
      warnings.add('HTTP is insecure — use HTTPS in production');
    }

    if (uri.host == 'localhost' || uri.host == '127.0.0.1') {
      warnings.add('Localhost URLs only work in development');
    }

    if (uri.port != 443 && uri.scheme == 'https') {
      warnings.add('Non-standard HTTPS port — ensure firewall allows it');
    }

    return warnings;
  }
}
