import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../models/knowledge.dart';
import '../services/api_service.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

/// Dedicated Flywheel Health screen — maps to /api/v1/flywheel endpoint.
///
/// Shows the health score, component breakdown, active issues,
/// and historical health trend.
class FlywheelScreen extends StatefulWidget {
  const FlywheelScreen({super.key});

  @override
  State<FlywheelScreen> createState() => _FlywheelScreenState();
}

class _FlywheelScreenState extends State<FlywheelScreen> {
  bool _loading = true;
  String? _error;
  FlywheelHealth? _health;
  List<FlywheelHealth> _history = [];

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final api = context.read<ApiService>();
      final data = await api.getFlywheelHealth();
      final health = FlywheelHealth.fromJson(data);
      setState(() {
        _health = health;
        _history = [..._history, health];
        if (_history.length > 50) _history = _history.sublist(_history.length - 50);
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Flywheel Health'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
      ),
      body: _loading && _health == null
          ? const Center(child: CircularProgressIndicator(color: TsarTheme.accent))
          : _error != null && _health == null
              ? ErrorBanner(message: _error!, onRetry: _refresh)
              : RefreshIndicator(
                  onRefresh: _refresh,
                  color: TsarTheme.accent,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _buildScoreCard(),
                      const SizedBox(height: 12),
                      _buildStatusCard(),
                      const SizedBox(height: 12),
                      _buildComponentsCard(),
                      const SizedBox(height: 12),
                      _buildIssuesCard(),
                      const SizedBox(height: 12),
                      _buildTrendCard(),
                      const SizedBox(height: 80),
                    ],
                  ),
                ),
    );
  }

  Widget _buildScoreCard() {
    final health = _health!;
    final scoreColor = health.score >= 80
        ? TsarTheme.profit
        : health.score >= 50
            ? TsarTheme.warning
            : TsarTheme.loss;

    return TsarCard(
      child: Column(
        children: [
          Text(
            'FLYWHEEL SCORE',
            style: TsarTheme.numberStyle.copyWith(
              color: Colors.white38,
              fontSize: 12,
              letterSpacing: 1.5,
            ),
          ),
          const SizedBox(height: 16),
          RiskGauge(
            value: health.score / 100,
            label: 'Health',
            size: 140,
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              StatusDot(status: health.status),
              const SizedBox(width: 8),
              Text(
                health.status.toUpperCase(),
                style: TsarTheme.numberStyle.copyWith(
                  fontSize: 16,
                  color: scoreColor,
                  letterSpacing: 1.2,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Last checked: ${_formatTime(health.checkedAt)}',
            style: const TextStyle(color: Colors.white24, fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusCard() {
    final health = _health!;
    return TsarCard(
      title: 'STATUS SUMMARY',
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: _statItem(
                  'Components',
                  '${health.components.length}',
                  Icons.widgets_outlined,
                ),
              ),
              Expanded(
                child: _statItem(
                  'Healthy',
                  '${health.components.values.where((v) => v > 0).length}',
                  Icons.check_circle_outline,
                  TsarTheme.profit,
                ),
              ),
              Expanded(
                child: _statItem(
                  'Issues',
                  '${health.issues.length}',
                  Icons.warning_amber,
                  health.issues.isEmpty ? TsarTheme.profit : TsarTheme.warning,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statItem(String label, String value, IconData icon, [Color? color]) {
    return Column(
      children: [
        Icon(icon, color: color ?? Colors.white38, size: 20),
        const SizedBox(height: 4),
        Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 18)),
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
      ],
    );
  }

  Widget _buildComponentsCard() {
    final components = _health!.components;
    if (components.isEmpty) return const SizedBox.shrink();

    return TsarCard(
      title: 'COMPONENT BREAKDOWN',
      child: Column(
        children: components.entries.map((entry) {
          final isHealthy = entry.value > 0;
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                Icon(
                  isHealthy ? Icons.check_circle : Icons.error_outline,
                  size: 16,
                  color: isHealthy ? TsarTheme.profit : TsarTheme.loss,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    entry.key.replaceAll('_', ' ').toUpperCase(),
                    style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: (isHealthy ? TsarTheme.profit : TsarTheme.loss).withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    isHealthy ? 'OK' : 'FAIL',
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      color: isHealthy ? TsarTheme.profit : TsarTheme.loss,
                    ),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildIssuesCard() {
    final issues = _health!.issues;
    if (issues.isEmpty) {
      return TsarCard(
        title: 'ISSUES',
        child: Row(
          children: [
            const Icon(Icons.check_circle, color: TsarTheme.profit, size: 20),
            const SizedBox(width: 10),
            Text(
              'No issues detected',
              style: TextStyle(color: Colors.white54, fontSize: 14),
            ),
          ],
        ),
      );
    }

    return TsarCard(
      title: 'ISSUES (${issues.length})',
      child: Column(
        children: issues.map((issue) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.warning_amber, size: 16, color: TsarTheme.warning),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    issue,
                    style: const TextStyle(color: Colors.white70, fontSize: 13),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildTrendCard() {
    if (_history.length < 2) return const SizedBox.shrink();

    final spots = _history
        .asMap()
        .entries
        .map((e) => FlSpot(e.key.toDouble(), e.value.score))
        .toList();

    return TsarCard(
      title: 'HEALTH TREND',
      child: Column(
        children: [
          PnlLineChart(spots: spots, height: 120),
          const SizedBox(height: 8),
          Text(
            '${_history.length} data points',
            style: const TextStyle(color: Colors.white24, fontSize: 11),
          ),
        ],
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${dt.month}/${dt.day} ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
  }
}
