import 'package:flutter/material.dart';
import '../theme.dart';

enum SentimentType { bullish, bearish, neutral }

class NewsItem {
  final String id;
  final String title;
  final String summary;
  final String source;
  final String url;
  final SentimentType sentiment;
  final double sentimentScore;
  final List<String> symbols;
  final List<String> tags;
  final DateTime publishedAt;
  final bool isAlert;

  NewsItem({
    required this.id,
    required this.title,
    required this.summary,
    required this.source,
    required this.url,
    required this.sentiment,
    required this.sentimentScore,
    required this.symbols,
    required this.tags,
    required this.publishedAt,
    this.isAlert = false,
  });

  factory NewsItem.fromJson(Map<String, dynamic> json) {
    try {
      return NewsItem(
        id: json['id']?.toString() ?? '',
        title: json['title'] ?? '',
        summary: json['summary'] ?? json['description'] ?? json['snippet'] ?? '',
        source: json['source'] ?? json['provider'] ?? '',
        url: json['url'] ?? json['link'] ?? '',
        sentiment: _parseSentiment(json['sentiment']),
        sentimentScore: _toDouble(json['sentiment_score'] ?? json['score']),
        symbols: _parseStringList(json['symbols'] ?? json['tickers']),
        tags: _parseStringList(json['tags'] ?? json['categories']),
        publishedAt: DateTime.tryParse(json['published_at'] ?? json['timestamp'] ?? json['created_at'] ?? '') ?? DateTime.now(),
        isAlert: json['is_alert'] ?? json['alert'] ?? false,
      );
    } catch (_) {
      return NewsItem(
        id: json['id']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        summary: '',
        source: '',
        url: '',
        sentiment: SentimentType.neutral,
        sentimentScore: 0,
        symbols: [],
        tags: [],
        publishedAt: DateTime.now(),
      );
    }
  }

  static SentimentType _parseSentiment(dynamic s) {
    final str = s?.toString().toLowerCase();
    switch (str) {
      case 'bullish':
      case 'positive':
        return SentimentType.bullish;
      case 'bearish':
      case 'negative':
        return SentimentType.bearish;
      default:
        return SentimentType.neutral;
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static List<String> _parseStringList(dynamic v) {
    if (v is List) return v.map((e) => e.toString()).toList();
    return [];
  }

  Color get sentimentColor {
    switch (sentiment) {
      case SentimentType.bullish:
        return TsarTheme.profit;
      case SentimentType.bearish:
        return TsarTheme.loss;
      case SentimentType.neutral:
        return Colors.white54;
    }
  }

  String get sentimentLabel {
    switch (sentiment) {
      case SentimentType.bullish:
        return 'BULLISH';
      case SentimentType.bearish:
        return 'BEARISH';
      case SentimentType.neutral:
        return 'NEUTRAL';
    }
  }

  IconData get sentimentIcon {
    switch (sentiment) {
      case SentimentType.bullish:
        return Icons.trending_up;
      case SentimentType.bearish:
        return Icons.trending_down;
      case SentimentType.neutral:
        return Icons.remove;
    }
  }
}
