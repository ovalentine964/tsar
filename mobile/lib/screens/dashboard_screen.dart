import 'package:google_fonts/google_fonts.dart';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../providers/dashboard_provider.dart';
import '../providers/settings_provider.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Timer? _autoRefreshTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<DashboardProvider>().refresh();
      _setupAutoRefresh();
    });
  }

  void _setupAutoRefresh() {
    final settings = context.read<SettingsProvider>();
    if (settings.autoRefresh) {
      _autoRefreshTimer = Timer.periodic(
        Duration(seconds: settings.refreshIntervalSeconds),
        (_) => context.read<DashboardProvider>().refresh(),
      );
    }
  }

  @override
  void dispose() {
    _autoRefreshTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TSAR'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<DashboardProvider>().refresh(),
          ),
        ],
      ),
      body: Consumer<DashboardProvider>(
        builder: (context, dash, _) {
          if (dash.loading && dash.stats == null) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (dash.error != null && dash.stats == null) {
            return ErrorBanner(
              message: dash.error!,
              onRetry: () => dash.refresh(),
            );
          }

          return RefreshIndicator(
            onRefresh: dash.refresh,
            color: TsarTheme.accent,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _buildKillSwitchBanner(dash),
                const SizedBox(height: 16),
                _buildPnlCard(dash),
                const SizedBox(height: 12),
                _buildStatsGrid(dash),
                const SizedBox(height: 12),
                _buildEquityCurve(dash),
                const SizedBox(height: 12),
                _buildRegimeCard(dash),
                const SizedBox(height: 12),
                _buildFlywheelCard(dash),
                const SizedBox(height: 80), // FAB clearance
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildKillSwitchBanner(DashboardProvider dash) {
    if (!dash.killSwitchActive) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TsarTheme.killSwitch.withOpacity(0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TsarTheme.killSwitch.withOpacity(0.4)),
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: TsarTheme.killSwitch),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              'KILL SWITCH ACTIVE — Trading halted',
              style: TextStyle(
                fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                fontWeight: FontWeight.w700,
                color: TsarTheme.killSwitch,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPnlCard(DashboardProvider dash) {
    final pnl = dash.pnl;
    return TsarCard(
      title: 'P&L SUMMARY',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _formatPnl(pnl?.totalPnl ?? 0),
            style: TsarTheme.pnlLarge(pnl?.totalPnl ?? 0),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(child: _pnlStat('Daily', pnl?.dailyPnl ?? 0)),
              Expanded(child: _pnlStat('Weekly', pnl?.weeklyPnl ?? 0)),
              Expanded(child: _pnlStat('Monthly', pnl?.monthlyPnl ?? 0)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _pnlStat(String label, double value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.white38)),
        const SizedBox(height: 4),
        Text(_formatPnl(value), style: TsarTheme.pnlStyle(value)),
      ],
    );
  }

  Widget _buildStatsGrid(DashboardProvider dash) {
    final stats = dash.stats;
    return Row(
      children: [
        Expanded(
          child: TsarCard(
            child: StatTile(
              label: 'WIN RATE',
              value: '${(stats?.winRate ?? 0).toStringAsFixed(1)}%',
              icon: Icons.percent,
              iconColor: TsarTheme.profit,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TsarCard(
            child: StatTile(
              label: 'TRADES',
              value: '${stats?.totalTrades ?? 0}',
              icon: Icons.swap_horiz,
              iconColor: TsarTheme.info,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TsarCard(
            child: StatTile(
              label: 'POSITIONS',
              value: '${dash.openPositions}',
              icon: Icons.layers_outlined,
              iconColor: TsarTheme.accent,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TsarCard(
            child: StatTile(
              label: 'P. FACTOR',
              value: (stats?.profitFactor ?? 0).toStringAsFixed(2),
              icon: Icons.trending_up,
              iconColor: TsarTheme.warning,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildEquityCurve(DashboardProvider dash) {
    final points = dash.pnl?.equityCurve ?? [];
    final spots = points
        .asMap()
        .entries
        .map((e) => FlSpot(e.key.toDouble(), e.value.value))
        .toList();

    return TsarCard(
      title: 'EQUITY CURVE',
      child: PnlLineChart(spots: spots, height: 180),
    );
  }

  Widget _buildRegimeCard(DashboardProvider dash) {
    final regime = dash.regime;
    return TsarCard(
      title: 'MARKET REGIME',
      trailing: StatusDot(status: regime?.currentRegime ?? 'unknown'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            (regime?.currentRegime ?? 'Unknown').toUpperCase(),
            style: TsarTheme.numberStyle.copyWith(fontSize: 20),
          ),
          const SizedBox(height: 4),
          Text(
            regime?.description ?? '',
            style: const TextStyle(color: Colors.white54, fontSize: 13),
          ),
          if (regime != null) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                const Text('Confidence: ',
                    style: TextStyle(color: Colors.white38, fontSize: 12)),
                Text(
                  '${(regime.confidence * 100).toStringAsFixed(0)}%',
                  style: TsarTheme.numberStyle.copyWith(fontSize: 12),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildFlywheelCard(DashboardProvider dash) {
    final fw = dash.flywheel;
    return TsarCard(
      title: 'FLYWHEEL HEALTH',
      child: Row(
        children: [
          RiskGauge(
            value: (fw?.score ?? 0) / 100,
            label: 'Score',
            size: 80,
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    StatusDot(status: fw?.status ?? 'unknown'),
                    const SizedBox(width: 8),
                    Text(
                      (fw?.status ?? 'Unknown').toUpperCase(),
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                    ),
                  ],
                ),
                if (fw != null && fw.issues.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  ...fw.issues.take(3).map((issue) => Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Row(
                          children: [
                            const Icon(Icons.warning_amber,
                                size: 12, color: TsarTheme.warning),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Text(
                                issue,
                                style: const TextStyle(
                                    color: Colors.white54, fontSize: 11),
                              ),
                            ),
                          ],
                        ),
                      )),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _formatPnl(double value) {
    final prefix = value >= 0 ? '+' : '';
    return '$prefix\$${value.toStringAsFixed(2)}';
  }
}
