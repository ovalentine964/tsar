class KnowledgeResult {
  final String id;
  final String store;
  final String title;
  final String content;
  final double relevance;
  final Map<String, dynamic>? metadata;
  final DateTime? createdAt;

  KnowledgeResult({
    required this.id,
    required this.store,
    required this.title,
    required this.content,
    required this.relevance,
    this.metadata,
    this.createdAt,
  });

  factory KnowledgeResult.fromJson(Map<String, dynamic> json) {
    try {
      return KnowledgeResult(
        id: json['id']?.toString() ?? json['record_id']?.toString() ?? '',
        store: json['store'] ?? json['source'] ?? '',
        title: json['title'] ?? json['record_id']?.toString() ?? '',
        content: json['content'] ?? json['snippet'] ?? json['text'] ?? '',
        relevance: _toDouble(json['relevance'] ?? json['rank'] ?? json['score']),
        metadata: json['metadata'] is Map
            ? Map<String, dynamic>.from(json['metadata'])
            : null,
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'])
            : null,
      );
    } catch (_) {
      return KnowledgeResult(
        id: json['record_id']?.toString() ?? '',
        store: json['store'] ?? '',
        title: '',
        content: json['snippet']?.toString() ?? '',
        relevance: 0,
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }
}

class MarketRegime {
  final String currentRegime;
  final double confidence;
  final String description;
  final Map<String, double> probabilities;
  final DateTime detectedAt;

  MarketRegime({
    required this.currentRegime,
    required this.confidence,
    required this.description,
    required this.probabilities,
    required this.detectedAt,
  });

  factory MarketRegime.fromJson(Map<String, dynamic> json) {
    try {
      return MarketRegime(
        currentRegime: json['current_regime'] ?? json['regime'] ?? 'unknown',
        confidence: _toDouble(json['confidence']),
        description: json['description'] ?? '',
        probabilities: _parseProbabilities(json['probabilities']),
        detectedAt: DateTime.tryParse(json['detected_at'] ?? json['timestamp'] ?? '') ?? DateTime.now(),
      );
    } catch (_) {
      return MarketRegime(
        currentRegime: json['regime']?.toString() ?? 'unknown',
        confidence: _toDouble(json['confidence']),
        description: '',
        probabilities: {},
        detectedAt: DateTime.now(),
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static Map<String, double> _parseProbabilities(dynamic p) {
    if (p is Map) {
      return p.map((k, v) => MapEntry(k.toString(), _toDouble(v)));
    }
    return {};
  }
}

class FlywheelHealth {
  final String status;
  final double score;
  final Map<String, double> components;
  final List<String> issues;
  final DateTime checkedAt;

  FlywheelHealth({
    required this.status,
    required this.score,
    required this.components,
    required this.issues,
    required this.checkedAt,
  });

  factory FlywheelHealth.fromJson(Map<String, dynamic> json) {
    try {
      final componentsMap = <String, double>{};
      final rawComponents = json['components'];
      if (rawComponents is Map) {
        rawComponents.forEach((k, v) {
          if (v is String) {
            // Status strings like "ok" → 1.0, "error" → 0.0
            componentsMap[k.toString()] = (v == 'ok' || v == 'healthy') ? 1.0 : 0.0;
          } else {
            componentsMap[k.toString()] = _toDouble(v);
          }
        });
      }

      // Compute score from components if not provided
      double score = _toDouble(json['score']);
      if (score == 0 && componentsMap.isNotEmpty) {
        final okCount = componentsMap.values.where((v) => v > 0).length;
        score = (okCount / componentsMap.length) * 100;
      }

      return FlywheelHealth(
        status: json['status'] ?? 'unknown',
        score: score,
        components: componentsMap,
        issues: _parseIssues(json['issues']),
        checkedAt: DateTime.tryParse(json['last_cycle'] ?? json['checked_at'] ?? '') ?? DateTime.now(),
      );
    } catch (_) {
      return FlywheelHealth(
        status: 'unknown',
        score: 0,
        components: {},
        issues: [],
        checkedAt: DateTime.now(),
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static List<String> _parseIssues(dynamic issues) {
    if (issues is List) {
      return issues.map((e) => e.toString()).toList();
    }
    return [];
  }
}

class Pattern {
  final String id;
  final String name;
  final String description;
  final double confidence;
  final Map<String, dynamic>? metadata;

  Pattern({
    required this.id,
    required this.name,
    required this.description,
    required this.confidence,
    this.metadata,
  });

  factory Pattern.fromJson(Map<String, dynamic> json) {
    try {
      return Pattern(
        id: json['id']?.toString() ?? '',
        name: json['name'] ?? json['pattern'] ?? '',
        description: json['description'] ?? '',
        confidence: _toDouble(json['confidence'] ?? json['score']),
        metadata: json['metadata'] is Map ? Map<String, dynamic>.from(json['metadata']) : null,
      );
    } catch (_) {
      return Pattern(id: '', name: '', description: '', confidence: 0);
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }
}

class Lesson {
  final String id;
  final String title;
  final String content;
  final String? tradeId;
  final DateTime? createdAt;

  Lesson({
    required this.id,
    required this.title,
    required this.content,
    this.tradeId,
    this.createdAt,
  });

  factory Lesson.fromJson(Map<String, dynamic> json) {
    try {
      return Lesson(
        id: json['id']?.toString() ?? '',
        title: json['title'] ?? json['lesson'] ?? '',
        content: json['content'] ?? json['text'] ?? '',
        tradeId: json['trade_id']?.toString(),
        createdAt: json['created_at'] != null ? DateTime.tryParse(json['created_at']) : null,
      );
    } catch (_) {
      return Lesson(id: '', title: '', content: '');
    }
  }
}
