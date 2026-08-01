import 'package:flutter/material.dart';
import '../theme.dart';

enum ScenarioStatus { active, triggered, prevented, cleared }

class Scenario {
  final String id;
  final String name;
  final String description;
  final String category; // flash_crash, liquidation, correlation, volatility, liquidity
  final ScenarioStatus status;
  final double riskLevel; // 0-1
  final String triggerCondition;
  final String? preventionAction;
  final DateTime? triggeredAt;
  final DateTime? clearedAt;
  final Map<String, dynamic>? parameters;

  Scenario({
    required this.id,
    required this.name,
    required this.description,
    required this.category,
    required this.status,
    required this.riskLevel,
    required this.triggerCondition,
    this.preventionAction,
    this.triggeredAt,
    this.clearedAt,
    this.parameters,
  });

  factory Scenario.fromJson(Map<String, dynamic> json) {
    try {
      return Scenario(
        id: json['id']?.toString() ?? json['scenario_id']?.toString() ?? '',
        name: json['name'] ?? json['scenario'] ?? json['title'] ?? '',
        description: json['description'] ?? json['detail'] ?? '',
        category: json['category'] ?? json['type'] ?? 'general',
        status: _parseStatus(json['status']),
        riskLevel: _toDouble(json['risk_level'] ?? json['risk'] ?? json['severity']),
        triggerCondition: json['trigger_condition'] ?? json['condition'] ?? json['trigger'] ?? '',
        preventionAction: json['prevention_action'] ?? json['action'] ?? json['mitigation'],
        triggeredAt: json['triggered_at'] != null ? DateTime.tryParse(json['triggered_at']) : null,
        clearedAt: json['cleared_at'] != null ? DateTime.tryParse(json['cleared_at']) : null,
        parameters: json['parameters'] is Map ? Map<String, dynamic>.from(json['parameters']) : null,
      );
    } catch (_) {
      return Scenario(
        id: '',
        name: json['name']?.toString() ?? '',
        description: '',
        category: 'general',
        status: ScenarioStatus.active,
        riskLevel: 0,
        triggerCondition: '',
      );
    }
  }

  static ScenarioStatus _parseStatus(dynamic s) {
    final str = s?.toString().toLowerCase();
    switch (str) {
      case 'triggered': return ScenarioStatus.triggered;
      case 'prevented': return ScenarioStatus.prevented;
      case 'cleared': return ScenarioStatus.cleared;
      case 'active':
      default: return ScenarioStatus.active;
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  bool get isActive => status == ScenarioStatus.active;
  bool get isTriggered => status == ScenarioStatus.triggered;

  Color get statusColor {
    switch (status) {
      case ScenarioStatus.active: return TsarTheme.info;
      case ScenarioStatus.triggered: return TsarTheme.loss;
      case ScenarioStatus.prevented: return TsarTheme.profit;
      case ScenarioStatus.cleared: return Colors.white38;
    }
  }

  String get statusLabel {
    switch (status) {
      case ScenarioStatus.active: return 'MONITORING';
      case ScenarioStatus.triggered: return 'TRIGGERED';
      case ScenarioStatus.prevented: return 'PREVENTED';
      case ScenarioStatus.cleared: return 'CLEARED';
    }
  }

  IconData get categoryIcon {
    switch (category.toLowerCase()) {
      case 'flash_crash': return Icons.bolt;
      case 'liquidation': return Icons.water_drop;
      case 'correlation': return Icons.device_hub;
      case 'volatility': return Icons.show_chart;
      case 'liquidity': return Icons.waves;
      default: return Icons.shield;
    }
  }

  String get riskEmoji {
    if (riskLevel >= 0.8) return '🔴';
    if (riskLevel >= 0.5) return '🟠';
    if (riskLevel >= 0.3) return '🟡';
    return '🟢';
  }
}

class OnChainRule {
  final String id;
  final String name;
  final String description;
  final String chain;
  final String ruleType; // max_position, stop_loss, leverage, exposure
  final Map<String, dynamic> params;
  final bool isActive;
  final DateTime createdAt;
  final DateTime? lastTriggered;

  OnChainRule({
    required this.id,
    required this.name,
    required this.description,
    required this.chain,
    required this.ruleType,
    required this.params,
    required this.isActive,
    required this.createdAt,
    this.lastTriggered,
  });

  factory OnChainRule.fromJson(Map<String, dynamic> json) {
    try {
      return OnChainRule(
        id: json['id']?.toString() ?? json['rule_id']?.toString() ?? '',
        name: json['name'] ?? json['title'] ?? '',
        description: json['description'] ?? json['detail'] ?? '',
        chain: json['chain'] ?? json['network'] ?? '',
        ruleType: json['rule_type'] ?? json['type'] ?? '',
        params: json['params'] is Map ? Map<String, dynamic>.from(json['params']) : {},
        isActive: json['is_active'] ?? json['active'] ?? json['enabled'] ?? true,
        createdAt: DateTime.tryParse(json['created_at'] ?? '') ?? DateTime.now(),
        lastTriggered: json['last_triggered'] != null ? DateTime.tryParse(json['last_triggered']) : null,
      );
    } catch (_) {
      return OnChainRule(
        id: '',
        name: json['name']?.toString() ?? '',
        description: '',
        chain: '',
        ruleType: '',
        params: {},
        isActive: true,
        createdAt: DateTime.now(),
      );
    }
  }

  IconData get typeIcon {
    switch (ruleType.toLowerCase()) {
      case 'max_position': return Icons.layers;
      case 'stop_loss': return Icons.stop_circle;
      case 'leverage': return Icons.speed;
      case 'exposure': return Icons.pie_chart;
      default: return Icons.rule;
    }
  }
}

class AuditEntry {
  final String id;
  final String action;
  final String actor; // system, user, rule
  final String detail;
  final String? txHash;
  final String? chain;
  final DateTime timestamp;
  final Map<String, dynamic>? metadata;

  AuditEntry({
    required this.id,
    required this.action,
    required this.actor,
    required this.detail,
    this.txHash,
    this.chain,
    required this.timestamp,
    this.metadata,
  });

  factory AuditEntry.fromJson(Map<String, dynamic> json) {
    try {
      return AuditEntry(
        id: json['id']?.toString() ?? '',
        action: json['action'] ?? json['event'] ?? '',
        actor: json['actor'] ?? json['source'] ?? 'system',
        detail: json['detail'] ?? json['description'] ?? json['message'] ?? '',
        txHash: json['tx_hash'] ?? json['transaction_hash'],
        chain: json['chain'] ?? json['network'],
        timestamp: DateTime.tryParse(json['timestamp'] ?? json['created_at'] ?? '') ?? DateTime.now(),
        metadata: json['metadata'] is Map ? Map<String, dynamic>.from(json['metadata']) : null,
      );
    } catch (_) {
      return AuditEntry(
        id: '',
        action: '',
        actor: 'system',
        detail: json.toString(),
        timestamp: DateTime.now(),
      );
    }
  }

  IconData get actorIcon {
    switch (actor.toLowerCase()) {
      case 'user': return Icons.person;
      case 'rule': return Icons.rule;
      case 'system': return Icons.smart_toy;
      default: return Icons.circle;
    }
  }
}
