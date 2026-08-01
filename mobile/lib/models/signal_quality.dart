import 'package:flutter/material.dart';
import '../theme.dart';

class SignalQuality {
  final String id;
  final String symbol;
  final double overallScore;
  final String grade; // A, B, C, D, F
  final List<SignalFactor> factors;
  final double confidence;
  final String recommendation;
  final DateTime evaluatedAt;
  final Map<String, dynamic>? metadata;

  SignalQuality({
    required this.id,
    required this.symbol,
    required this.overallScore,
    required this.grade,
    required this.factors,
    required this.confidence,
    required this.recommendation,
    required this.evaluatedAt,
    this.metadata,
  });

  factory SignalQuality.fromJson(Map<String, dynamic> json) {
    try {
      return SignalQuality(
        id: json['id']?.toString() ?? json['signal_id']?.toString() ?? '',
        symbol: json['symbol'] ?? json['ticker'] ?? '',
        overallScore: _toDouble(json['overall_score'] ?? json['score'] ?? json['quality_score']),
        grade: json['grade'] ?? _scoreToGrade(_toDouble(json['overall_score'] ?? json['score'])),
        factors: _parseFactors(json['factors'] ?? json['breakdown']),
        confidence: _toDouble(json['confidence']),
        recommendation: json['recommendation'] ?? json['action'] ?? '',
        evaluatedAt: DateTime.tryParse(json['evaluated_at'] ?? json['timestamp'] ?? json['created_at'] ?? '') ?? DateTime.now(),
        metadata: json['metadata'] is Map ? Map<String, dynamic>.from(json['metadata']) : null,
      );
    } catch (_) {
      return SignalQuality(
        id: '',
        symbol: json['symbol']?.toString() ?? '',
        overallScore: 0,
        grade: 'F',
        factors: [],
        confidence: 0,
        recommendation: '',
        evaluatedAt: DateTime.now(),
      );
    }
  }

  static String _scoreToGrade(double score) {
    if (score >= 0.9) return 'A';
    if (score >= 0.75) return 'B';
    if (score >= 0.6) return 'C';
    if (score >= 0.4) return 'D';
    return 'F';
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static List<SignalFactor> _parseFactors(dynamic v) {
    if (v is List) {
      return v.map((e) {
        if (e is Map<String, dynamic>) return SignalFactor.fromJson(e);
        return SignalFactor(name: e.toString(), score: 0, weight: 0, description: '');
      }).toList();
    }
    return [];
  }

  Color get gradeColor {
    switch (grade) {
      case 'A': return TsarTheme.profit;
      case 'B': return const Color(0xFF66BB6A);
      case 'C': return TsarTheme.warning;
      case 'D': return const Color(0xFFFF8A65);
      case 'F': return TsarTheme.loss;
      default: return Colors.white54;
    }
  }

  String get statusEmoji {
    if (overallScore >= 0.8) return '🟢';
    if (overallScore >= 0.6) return '🟡';
    if (overallScore >= 0.4) return '🟠';
    return '🔴';
  }
}

class SignalFactor {
  final String name;
  final double score;
  final double weight;
  final String description;
  final double? contribution;

  SignalFactor({
    required this.name,
    required this.score,
    required this.weight,
    required this.description,
    this.contribution,
  });

  factory SignalFactor.fromJson(Map<String, dynamic> json) {
    try {
      final score = _toDouble(json['score'] ?? json['value']);
      final weight = _toDouble(json['weight'] ?? json['importance']);
      return SignalFactor(
        name: json['name'] ?? json['factor'] ?? json['category'] ?? '',
        score: score,
        weight: weight,
        description: json['description'] ?? json['detail'] ?? '',
        contribution: json['contribution'] != null ? _toDouble(json['contribution']) : score * weight,
      );
    } catch (_) {
      return SignalFactor(name: '', score: 0, weight: 0, description: '');
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  Color get scoreColor {
    if (score >= 0.7) return TsarTheme.profit;
    if (score >= 0.4) return TsarTheme.warning;
    return TsarTheme.loss;
  }

  String get scoreEmoji {
    if (score >= 0.7) return '🟢';
    if (score >= 0.5) return '🟡';
    if (score >= 0.3) return '🟠';
    return '🔴';
  }
}
