import 'package:flutter/material.dart';
import '../theme.dart';

class DeFiPosition {
  final String id;
  final String protocol;
  final String chain;
  final String type; // lending, staking, lp, vault, bridge
  final String asset;
  final double amount;
  final double valueUsd;
  final double apy;
  final double yieldEarned;
  final String status; // active, pending, closed
  final DateTime depositedAt;
  final DateTime? lastUpdated;
  final Map<String, dynamic>? metadata;

  DeFiPosition({
    required this.id,
    required this.protocol,
    required this.chain,
    required this.type,
    required this.asset,
    required this.amount,
    required this.valueUsd,
    required this.apy,
    required this.yieldEarned,
    required this.status,
    required this.depositedAt,
    this.lastUpdated,
    this.metadata,
  });

  factory DeFiPosition.fromJson(Map<String, dynamic> json) {
    try {
      return DeFiPosition(
        id: json['id']?.toString() ?? json['position_id']?.toString() ?? '',
        protocol: json['protocol'] ?? json['platform'] ?? json['dapp'] ?? '',
        chain: json['chain'] ?? json['network'] ?? 'ethereum',
        type: json['type'] ?? json['strategy'] ?? 'staking',
        asset: json['asset'] ?? json['token'] ?? json['symbol'] ?? '',
        amount: _toDouble(json['amount'] ?? json['balance']),
        valueUsd: _toDouble(json['value_usd'] ?? json['value'] ?? json['usd_value']),
        apy: _toDouble(json['apy'] ?? json['apr'] ?? json['yield_rate']),
        yieldEarned: _toDouble(json['yield_earned'] ?? json['earned'] ?? json['rewards']),
        status: json['status'] ?? 'active',
        depositedAt: DateTime.tryParse(json['deposited_at'] ?? json['created_at'] ?? '') ?? DateTime.now(),
        lastUpdated: json['last_updated'] != null ? DateTime.tryParse(json['last_updated']) : null,
        metadata: json['metadata'] is Map ? Map<String, dynamic>.from(json['metadata']) : null,
      );
    } catch (_) {
      return DeFiPosition(
        id: '',
        protocol: json['protocol']?.toString() ?? '',
        chain: 'ethereum',
        type: 'staking',
        asset: json['asset']?.toString() ?? '',
        amount: 0,
        valueUsd: 0,
        apy: 0,
        yieldEarned: 0,
        status: 'active',
        depositedAt: DateTime.now(),
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  bool get isActive => status.toLowerCase() == 'active';

  IconData get typeIcon {
    switch (type.toLowerCase()) {
      case 'lending': return Icons.account_balance;
      case 'staking': return Icons.lock;
      case 'lp':
      case 'liquidity': return Icons.water_drop;
      case 'vault': return Icons.savings;
      case 'bridge': return Icons.swap_horiz;
      default: return Icons.currency_exchange;
    }
  }

  Color get chainColor {
    switch (chain.toLowerCase()) {
      case 'ethereum': return const Color(0xFF627EEA);
      case 'solana': return const Color(0xFF9945FF);
      case 'bsc': return const Color(0xFFF3BA2F);
      case 'polygon': return const Color(0xFF8247E5);
      case 'arbitrum': return const Color(0xFF28A0F0);
      case 'avalanche': return const Color(0xFFE84142);
      default: return Colors.white54;
    }
  }
}

class DeFiYieldSummary {
  final double totalValueUsd;
  final double totalYieldEarned;
  final double averageApy;
  final int activePositions;
  final Map<String, double> chainBreakdown;
  final Map<String, double> typeBreakdown;

  DeFiYieldSummary({
    required this.totalValueUsd,
    required this.totalYieldEarned,
    required this.averageApy,
    required this.activePositions,
    required this.chainBreakdown,
    required this.typeBreakdown,
  });

  factory DeFiYieldSummary.fromJson(Map<String, dynamic> json) {
    try {
      return DeFiYieldSummary(
        totalValueUsd: _toDouble(json['total_value_usd'] ?? json['total_value']),
        totalYieldEarned: _toDouble(json['total_yield_earned'] ?? json['total_earned']),
        averageApy: _toDouble(json['average_apy'] ?? json['avg_apy']),
        activePositions: json['active_positions'] ?? json['count'] ?? 0,
        chainBreakdown: _parseMap(json['chain_breakdown'] ?? json['by_chain']),
        typeBreakdown: _parseMap(json['type_breakdown'] ?? json['by_type']),
      );
    } catch (_) {
      return DeFiYieldSummary(
        totalValueUsd: 0,
        totalYieldEarned: 0,
        averageApy: 0,
        activePositions: 0,
        chainBreakdown: {},
        typeBreakdown: {},
      );
    }
  }

  static double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0;
    return 0;
  }

  static Map<String, double> _parseMap(dynamic v) {
    if (v is Map) {
      return v.map((k, val) => MapEntry(k.toString(), _toDouble(val)));
    }
    return {};
  }
}
