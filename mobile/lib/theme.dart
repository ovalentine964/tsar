import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

// ═══════════════════════════════════════════════════════════════════════════
// TSAR Theme — Professional Trading Platform
// ═══════════════════════════════════════════════════════════════════════════

class TsarTheme {
  TsarTheme._();

  // ── Color Palette ──────────────────────────────────────────────────────
  static const Color background = Color(0xFF0A0A0F);
  static const Color surface = Color(0xFF12121A);
  static const Color surfaceVariant = Color(0xFF16162A);
  static const Color card = Color(0xFF1A1A2E);
  static const Color cardBorder = Color(0xFF2A2A3E);
  static const Color accent = Color(0xFF7C4DFF);
  static const Color accentLight = Color(0xFF9E7CFF);
  static const Color profit = Color(0xFF00C853);
  static const Color loss = Color(0xFFFF1744);
  static const Color warning = Color(0xFFFFAB00);
  static const Color info = Color(0xFF2979FF);
  static const Color muted = Color(0xFF8888A0);
  static const Color killSwitch = Color(0xFFFF1744);

  // Status indicator colors
  static const Color statusGreen = Color(0xFF00E676);
  static const Color statusYellow = Color(0xFFFFD600);
  static const Color statusOrange = Color(0xFFFF9100);
  static const Color statusRed = Color(0xFFFF1744);

  // ── Typography Helpers ─────────────────────────────────────────────────

  /// Monospace style for all numbers and financial data (JetBrains Mono).
  static TextStyle _mono({
    double? fontSize,
    FontWeight? fontWeight,
    Color? color,
    double? letterSpacing,
    List<FontFeature>? fontFeatures,
  }) {
    return GoogleFonts.jetBrainsMono(
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
      letterSpacing: letterSpacing,
      fontFeatures: fontFeatures ?? const [FontFeature.tabularFigures()],
    );
  }

  /// Inter / system font for headers and body text.
  static TextStyle interStyle({
    double? fontSize,
    FontWeight? fontWeight,
    Color? color,
    double? letterSpacing,
    double? height,
  }) {
    return GoogleFonts.inter(
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
      letterSpacing: letterSpacing,
      height: height,
    );
  }

  // ── Text Styles ────────────────────────────────────────────────────────

  // Headers (Inter)
  static TextStyle get h1 => interStyle(
        fontSize: 32,
        fontWeight: FontWeight.w800,
        color: Colors.white,
        letterSpacing: -0.5,
      );

  static TextStyle get h2 => interStyle(
        fontSize: 24,
        fontWeight: FontWeight.w700,
        color: Colors.white,
      );

  static TextStyle get h3 => interStyle(
        fontSize: 18,
        fontWeight: FontWeight.w600,
        color: Colors.white,
      );

  // Body (Inter)
  static TextStyle get bodyLarge => interStyle(
        fontSize: 16,
        fontWeight: FontWeight.w400,
        color: Colors.white70,
        height: 1.5,
      );

  static TextStyle get bodyMedium => interStyle(
        fontSize: 14,
        fontWeight: FontWeight.w400,
        color: Colors.white60,
        height: 1.4,
      );

  static TextStyle get bodySmall => interStyle(
        fontSize: 12,
        fontWeight: FontWeight.w400,
        color: Colors.white38,
      );

  // Labels (Inter)
  static TextStyle get labelLarge => interStyle(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: Colors.white,
      );

  static TextStyle get labelMedium => interStyle(
        fontSize: 12,
        fontWeight: FontWeight.w500,
        color: Colors.white60,
        letterSpacing: 0.5,
      );

  static TextStyle get labelSmall => interStyle(
        fontSize: 10,
        fontWeight: FontWeight.w500,
        color: Colors.white38,
        letterSpacing: 1.0,
      );

  // Numbers (JetBrains Mono with tabular figures)
  static TextStyle get numberStyle => _mono(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: Colors.white,
      );

  static TextStyle get numberLarge => _mono(
        fontSize: 28,
        fontWeight: FontWeight.w700,
        color: Colors.white,
      );

  static TextStyle get numberSmall => _mono(
        fontSize: 12,
        fontWeight: FontWeight.w500,
        color: Colors.white60,
      );

  // P&L styles
  static TextStyle pnlStyle(double value) {
    return _mono(
      fontSize: 16,
      fontWeight: FontWeight.w700,
      color: value >= 0 ? profit : loss,
    );
  }

  static TextStyle pnlLarge(double value) {
    return _mono(
      fontSize: 28,
      fontWeight: FontWeight.w700,
      color: value >= 0 ? profit : loss,
    );
  }

  // Section title style (ALL CAPS, tracked out)
  static TextStyle get sectionTitle => _mono(
        fontSize: 11,
        fontWeight: FontWeight.w600,
        color: Colors.white38,
        letterSpacing: 1.5,
      );

  // ── Status Emoji Helper ────────────────────────────────────────────────
  static String statusEmoji(double score) {
    if (score >= 0.8) return '🟢';
    if (score >= 0.6) return '🟡';
    if (score >= 0.4) return '🟠';
    return '🔴';
  }

  // ── Gradient Helpers ───────────────────────────────────────────────────

  /// Background gradient for profit-positive P&L cards.
  static LinearGradient get profitGradient => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          profit.withOpacity(0.08),
          profit.withOpacity(0.02),
        ],
      );

  /// Background gradient for loss-negative P&L cards.
  static LinearGradient get lossGradient => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          loss.withOpacity(0.08),
          loss.withOpacity(0.02),
        ],
      );

  /// Card gradient based on P&L value.
  static LinearGradient pnlGradient(double value) {
    return value >= 0 ? profitGradient : lossGradient;
  }

  // ── ThemeData ──────────────────────────────────────────────────────────

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: accent,
        secondary: profit,
        surface: surface,
        error: loss,
      ),
      scaffoldBackgroundColor: background,
      cardTheme: CardTheme(
        color: card,
        elevation: 0,
        shadowColor: Colors.black.withOpacity(0.3),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: cardBorder, width: 1),
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: surface,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: interStyle(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        indicatorColor: accent.withOpacity(0.2),
        labelTextStyle: WidgetStateProperty.all(
          interStyle(fontSize: 11, fontWeight: FontWeight.w500),
        ),
      ),
      textTheme: TextTheme(
        headlineLarge: h1,
        headlineMedium: h2,
        titleLarge: h3,
        titleMedium: interStyle(
          fontSize: 16,
          fontWeight: FontWeight.w500,
          color: Colors.white70,
        ),
        bodyLarge: bodyLarge,
        bodyMedium: bodyMedium,
        labelLarge: labelLarge,
      ),
      dividerTheme: const DividerThemeData(
        color: cardBorder,
        thickness: 1,
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: surfaceVariant,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    );
  }

  // ── Card Decorations ───────────────────────────────────────────────────

  /// Standard card decoration with border and subtle shadow.
  static BoxDecoration get cardDecoration => BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: cardBorder, width: 1),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.2),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      );

  /// Stat card decoration with icon badge area.
  static BoxDecoration get statCardDecoration => BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: cardBorder, width: 1),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.25),
            blurRadius: 10,
            offset: const Offset(0, 3),
          ),
        ],
      );

  /// Alert card decoration with colored left border.
  static BoxDecoration alertCardDecoration(Color alertColor) => BoxDecoration(
        color: card,
        borderRadius: BorderRadius.circular(12),
        border: Border(
          left: BorderSide(color: alertColor, width: 3),
          top: BorderSide(color: cardBorder, width: 1),
          right: BorderSide(color: cardBorder, width: 1),
          bottom: BorderSide(color: cardBorder, width: 1),
        ),
      );

  /// P&L card decoration with gradient background.
  static BoxDecoration pnlCardDecoration(double value) => BoxDecoration(
        gradient: pnlGradient(value),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: (value >= 0 ? profit : loss).withOpacity(0.25),
          width: 1,
        ),
      );
}
