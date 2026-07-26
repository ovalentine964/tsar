class Factor {
  final String id;
  final String name;
  final String category;
  final String description;
  final double ic;
  final double ir;
  final double turnover;
  final double correlation;
  final String computation;
  final Map<String, dynamic>? metadata;

  Factor({
    required this.id,
    required this.name,
    required this.category,
    required this.description,
    required this.ic,
    required this.ir,
    required this.turnover,
    required this.correlation,
    required this.computation,
    this.metadata,
  });

  factory Factor.fromJson(Map<String, dynamic> json) {
    try {
      return Factor(
        id: json['id']?.toString() ?? json['name'] ?? '',
        name: json['name'] ?? json['id'] ?? '',
        category: json['category'] ?? 'other',
        description: json['description'] ?? '',
        ic: _toDouble(json['ic']),
        ir: _toDouble(json['ir']),
        turnover: _toDouble(json['turnover']),
        correlation: _toDouble(json['correlation']),
        computation: json['computation'] ?? json['formula'] ?? '',
        metadata: json['metadata'] is Map
            ? Map<String, dynamic>.from(json['metadata'])
            : json['universe'] is List
                ? {'universe': json['universe']}
                : null,
      );
    } catch (_) {
      return Factor(
        id: json['name']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        category: 'other',
        description: '',
        ic: 0,
        ir: 0,
        turnover: 0,
        correlation: 0,
        computation: '',
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  String get icFormatted => ic >= 0 ? '+${ic.toStringAsFixed(4)}' : ic.toStringAsFixed(4);
  String get irFormatted => ir >= 0 ? '+${ir.toStringAsFixed(4)}' : ir.toStringAsFixed(4);
}

class FactorCategory {
  final String name;
  final String description;
  final int count;

  FactorCategory({
    required this.name,
    required this.description,
    required this.count,
  });

  factory FactorCategory.fromJson(Map<String, dynamic> json) {
    try {
      return FactorCategory(
        name: json['name'] ?? '',
        description: json['description'] ?? '',
        count: json['count'] ?? 0,
      );
    } catch (_) {
      return FactorCategory(name: '', description: '', count: 0);
    }
  }
}
