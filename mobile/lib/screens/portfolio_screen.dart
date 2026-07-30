import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../models/position.dart';
import '../providers/portfolio_provider.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

/// Portfolio overview screen with P&L curve and allocation pie chart.
class PortfolioScreen extends StatefulWidget {
  const PortfolioScreen({super.key});

  @override
  State<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends State<PortfolioScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<PortfolioProvider>().refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Portfolio'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<PortfolioProvider>().refresh(),
          ),
        ],
      ),
      body: Consumer<PortfolioProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.positions.isEmpty && provider.pnl == null) {
            return const Center(child: CircularProgressIndicator(color: TsarTheme.accent));
          }

          if (provider.error != null && provider.positions.isEmpty) {
            return ErrorBanner(message: provider.error!, onRetry: provider.refresh);
          }

          return RefreshIndicator(
            onRefresh: provider.refresh,
            color: TsarTheme.accent,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _buildSummaryCard(provider),
                const SizedBox(height: 12),
                _buildPnlCurve(provider),
                const SizedBox(height: 12),
                _buildAllocationPie(provider),
                const SizedBox(height: 12),
                _buildPositionsList(provider),
                const SizedBox(height: 80),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildSummaryCard(PortfolioProvider provider) {
    final pnl = provider.pnl;
    return TsarCard(
      child: Column(
        children: [
          Text(
            'TOTAL P&L',
            style: TsarTheme.numberStyle.copyWith(
              color: Colors.white38,
              fontSize: 12,
              letterSpacing: 1.5,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _formatPnl(pnl?.totalPnl ?? provider.totalUnrealizedPnl),
            style: TsarTheme.pnlLarge(pnl?.totalPnl ?? provider.totalUnrealizedPnl),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(child: _summaryStat('Daily', pnl?.dailyPnl ?? 0)),
              Expanded(child: _summaryStat('Weekly', pnl?.weeklyPnl ?? 0)),
              Expanded(child: _summaryStat('Monthly', pnl?.monthlyPnl ?? 0)),
            ],
          ),
          const Divider(height: 24),
          Row(
            children: [
              Expanded(child: _summaryStat('Market Value', provider.totalMarketValue, isCurrency: true)),
              Expanded(child: _summaryStat('Positions', provider.positions.length.toDouble())),
              Expanded(child: _summaryStat('Sharpe', pnl?.sharpeRatio ?? 0)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _summaryStat(String label, double value, {bool isCurrency = false}) {
    return Column(
      children: [
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
        const SizedBox(height: 4),
        Text(
          isCurrency ? '\$${value.toStringAsFixed(0)}' : _formatPnl(value),
          style: TsarTheme.numberStyle.copyWith(
            fontSize: 14,
            color: isCurrency
                ? Colors.white
                : value >= 0
                    ? TsarTheme.profit
                    : TsarTheme.loss,
          ),
        ),
      ],
    );
  }

  Widget _buildPnlCurve(PortfolioProvider provider) {
    final pnl = provider.pnl;
    if (pnl == null || pnl.equityCurve.isEmpty) return const SizedBox.shrink();

    final spots = pnl.equityCurve
        .asMap()
        .entries
        .map((e) => FlSpot(e.key.toDouble(), e.value.value))
        .toList();

    return TsarCard(
      title: 'EQUITY CURVE',
      trailing: Text(
        '${pnl.dailyReturn >= 0 ? '+' : ''}${pnl.dailyReturn.toStringAsFixed(2)}%',
        style: TsarTheme.pnlStyle(pnl.dailyReturn),
      ),
      child: PnlLineChart(spots: spots, height: 200),
    );
  }

  Widget _buildAllocationPie(PortfolioProvider provider) {
    if (provider.positions.isEmpty) return const SizedBox.shrink();

    final totalValue = provider.totalMarketValue;
    if (totalValue == 0) return const SizedBox.shrink();

    // Sort by weight descending
    final sorted = List<Position>.from(provider.positions)
      ..sort((a, b) => b.marketValue.compareTo(a.marketValue));

    // Group small positions (< 5%) into "Other"
    final mainPositions = <Position>[];
    double otherValue = 0;
    for (final pos in sorted) {
      final pct = pos.marketValue / totalValue;
      if (pct >= 0.05 || mainPositions.length < 5) {
        mainPositions.add(pos);
      } else {
        otherValue += pos.marketValue;
      }
    }

    final sections = <PieChartSectionData>[];
    final colors = [
      TsarTheme.accent,
      TsarTheme.profit,
      TsarTheme.warning,
      TsarTheme.info,
      const Color(0xFFFF6D00),
      const Color(0xFF00BFA5),
      const Color(0xFFAA00FF),
      Colors.white54,
    ];

    for (var i = 0; i < mainPositions.length; i++) {
      final pos = mainPositions[i];
      final pct = (pos.marketValue / totalValue * 100);
      sections.add(PieChartSectionData(
        value: pos.marketValue,
        title: '${pct.toStringAsFixed(0)}%',
        titleStyle: TextStyle(
          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
        color: colors[i % colors.length],
        radius: 60,
      ));
    }

    if (otherValue > 0) {
      final pct = (otherValue / totalValue * 100);
      sections.add(PieChartSectionData(
        value: otherValue,
        title: '${pct.toStringAsFixed(0)}%',
        titleStyle: TextStyle(
          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
          fontSize: 10,
          color: Colors.white70,
        ),
        color: Colors.white24,
        radius: 55,
      ));
    }

    return TsarCard(
      title: 'ALLOCATION',
      child: Column(
        children: [
          SizedBox(
            height: 180,
            child: PieChart(
              PieChartData(
                sections: sections,
                centerSpaceRadius: 40,
                sectionsSpace: 2,
              ),
            ),
          ),
          const SizedBox(height: 16),
          // Legend
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              for (var i = 0; i < mainPositions.length; i++)
                _legendItem(
                  mainPositions[i].symbol,
                  colors[i % colors.length],
                ),
              if (otherValue > 0) _legendItem('Other', Colors.white24),
            ],
          ),
        ],
      ),
    );
  }

  Widget _legendItem(String label, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 4),
        Text(
          label,
          style: TextStyle(
            fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
            fontSize: 11,
            color: Colors.white54,
          ),
        ),
      ],
    );
  }

  Widget _buildPositionsList(PortfolioProvider provider) {
    if (provider.positions.isEmpty) return const SizedBox.shrink();

    return TsarCard(
      title: 'POSITIONS (${provider.positions.length})',
      child: Column(
        children: [
          // Header
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                Expanded(
                  flex: 2,
                  child: Text('SYMBOL',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white24,
                        letterSpacing: 1,
                      )),
                ),
                Expanded(
                  child: Text('QTY',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white24,
                        letterSpacing: 1,
                      ),
                      textAlign: TextAlign.right),
                ),
                Expanded(
                  child: Text('PRICE',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white24,
                        letterSpacing: 1,
                      ),
                      textAlign: TextAlign.right),
                ),
                SizedBox(
                  width: 70,
                  child: Text('P&L',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white24,
                        letterSpacing: 1,
                      ),
                      textAlign: TextAlign.right),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          ...provider.positions.map((pos) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(
              children: [
                Expanded(
                  flex: 2,
                  child: Text(
                    pos.symbol,
                    style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                  ),
                ),
                Expanded(
                  child: Text(
                    pos.quantity.toStringAsFixed(2),
                    style: const TextStyle(color: Colors.white54, fontSize: 12),
                    textAlign: TextAlign.right,
                  ),
                ),
                Expanded(
                  child: Text(
                    '\$${pos.currentPrice.toStringAsFixed(2)}',
                    style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                    textAlign: TextAlign.right,
                  ),
                ),
                SizedBox(
                  width: 70,
                  child: PnlBadge(value: pos.unrealizedPnlPercent),
                ),
              ],
            ),
          )),
        ],
      ),
    );
  }

  String _formatPnl(double value) {
    final prefix = value >= 0 ? '+' : '';
    return '$prefix\$${value.toStringAsFixed(2)}';
  }
}
