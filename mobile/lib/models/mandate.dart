class Mandate {
  final String id;
  final String name;
  final String status;
  final List<MandateRule> rules;
  final DateTime committedAt;
  final DateTime? revokedAt;
  final String? revokedReason;

  Mandate({
    required this.id,
    required this.name,
    required this.status,
    required this.rules,
    required this.committedAt,
    this.revokedAt,
    this.revokedReason,
  });

  factory Mandate.fromJson(Map<String, dynamic> json) {
    try {
      return Mandate(
        id: json['id']?.toString() ?? 'current',
        name: json['name'] ?? json['title'] ?? 'Trading Mandate',
        status: json['status'] ?? 'unknown',
        rules: _parseRules(json['rules']),
        committedAt: DateTime.tryParse(json['committed_at'] ?? json['updated_at'] ?? '') ?? DateTime.now(),
        revokedAt: json['revoked_at'] != null
            ? DateTime.tryParse(json['revoked_at'])
            : null,
        revokedReason: json['revoked_reason'],
      );
    } catch (_) {
      return Mandate(
        id: 'current',
        name: 'Trading Mandate',
        status: json['status'] ?? 'unknown',
        rules: [],
        committedAt: DateTime.now(),
      );
    }
  }

  static List<MandateRule> _parseRules(dynamic rules) {
    if (rules is List) {
      return rules.map((e) {
        if (e is Map<String, dynamic>) return MandateRule.fromJson(e);
        return MandateRule(id: '', category: '', rule: e.toString(), enabled: true);
      }).toList();
    }
    return [];
  }

  bool get isActive => status.toLowerCase() == 'active';
}

class MandateRule {
  final String id;
  final String category;
  final String rule;
  final bool enabled;
  final Map<String, dynamic>? params;

  MandateRule({
    required this.id,
    required this.category,
    required this.rule,
    required this.enabled,
    this.params,
  });

  factory MandateRule.fromJson(Map<String, dynamic> json) {
    try {
      return MandateRule(
        id: json['id']?.toString() ?? '',
        category: json['category'] ?? json['type'] ?? '',
        rule: json['rule'] ?? json['description'] ?? json['name'] ?? '',
        enabled: json['enabled'] ?? true,
        params: json['params'] is Map ? Map<String, dynamic>.from(json['params']) : null,
      );
    } catch (_) {
      return MandateRule(
        id: '',
        category: '',
        rule: json.toString(),
        enabled: true,
      );
    }
  }
}
