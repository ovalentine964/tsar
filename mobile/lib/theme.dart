import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class TsarTheme {
  // Brand colors
  static const Color profit = Color(0xFF00C853);
  static const Color loss = Color(0xFFFF1744);
  static const Color warning = Color(0xFFFFAB00);
  static const Color info = Color(0xFF2979FF);
  static const Color surface = Color(0xFF121212);
  static const Color surfaceVariant = Color(0xFF1E1E1E);
  static const Color card = Color(0xFF1A1A2E);
  static const Color cardBorder = Color(0xFF2A2A3E);
  static const Color accent = Color(0xFF7C4DFF);
  static const Color killSwitch = Color(0xFFFF1744);

  static TextStyle _mono({double? fontSize, FontWeight? fontWeight, Color? color}) {
    return GoogleFonts.jetBrainsMono(
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
    );
  }

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
      scaffoldBackgroundColor: surface,
      cardTheme: const CardTheme(
        color: card,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(12)),
          side: BorderSide(color: cardBorder, width: 1),
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: surface,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: _mono(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surfaceVariant,
        indicatorColor: accent.withOpacity(0.2),
        labelTextStyle: WidgetStateProperty.all(
          const TextStyle(fontSize: 12, fontWeight: FontWeight.w500),
        ),
      ),
      textTheme: TextTheme(
        headlineLarge: _mono(
          fontSize: 32,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
        headlineMedium: _mono(
          fontSize: 24,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
        titleLarge: _mono(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: Colors.white,
        ),
        titleMedium: _mono(
          fontSize: 16,
          fontWeight: FontWeight.w500,
          color: Colors.white70,
        ),
        bodyLarge: const TextStyle(fontSize: 16, color: Colors.white70),
        bodyMedium: const TextStyle(fontSize: 14, color: Colors.white60),
        labelLarge: _mono(
          fontSize: 14,
          fontWeight: FontWeight.w600,
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: cardBorder,
        thickness: 1,
      ),
    );
  }

  // Number style for monospace financial data
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
}
