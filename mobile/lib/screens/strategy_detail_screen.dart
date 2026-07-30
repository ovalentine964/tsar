import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../models/strategy.dart';
import '../providers/strategy_provider.dart';
import '../services/api_service.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';
import 'backtest_screen.dart';

/// Strategy detail screen — maps to /api/v1/strategies/{name}.
///
/// Shows full strategy info, performance metrics, genome,
/// and provides start/stop/backtest actions.
class StrategyDetailScreen extends StatefulWidget {
  final String strategyId;
  const StrategyDetailScreen({super.key, required this.strategyId});

  @override
  State<StrategyDetailScreen> createState() => _StrategyDetailScreenState();
}

class _StrategyDetailScreenState extends State<StrategyDetailScreen> {
  Strategy? _strategy;
  bool _loading = true;
  String? _error;
  bool _actionLoading = false;

  @override
  void initState() {
    super.initState();
    _loadStrategy();
  }

  Future<void> _loadStrategy() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final api = context.read<ApiService>();
      final data = await api.getStrategyDetail(widget.strategyId);
      setState(() {
        _strategy = Strategy.fromJson(data);
        _loading = false;
      });
    } catch (e) {
      // Fall back to strategy from provider list
      final provider = context.read<StrategyProvider>();
      final match = provider.strategies.where((s) => s.id == widget.strategyId).toList();
      if (match.isNotEmpty) {
        setState(() {
          _strategy = match.first;
          _loading = false;
        });
      } else {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_strategy?.name ?? 'Strategy'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadStrategy,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: TsarTheme.accent))
          : _error != null && _strategy == null
              ? ErrorBanner(message: _error!, onRetry: _loadStrategy)
              : _buildContent(_strategy!),
    );
  }

  Widget _buildContent(Strategy strategy) {
    return RefreshIndicator(
      onRefresh: _loadStrategy,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Status header
          _buildStatusHeader(strategy),
          const SizedBox(height: 12),

          // Performance metrics
          _buildMetricsGrid(strategy),
          const SizedBox(height: 12),

          // Performance chart placeholder
          _buildPerformanceChart(strategy),
          const SizedBox(height: 12),

          // Description
          if (strategy.description.isNotEmpty)
            TsarCard(
              title: 'DESCRIPTION',
              child: Text(
                strategy.description,
                style: const TextStyle(color: Colors.white70, fontSize: 14, height: 1.5),
              ),
            ),

          if (strategy.description.isNotEmpty) const SizedBox(height: 12),

          // Genome
          if (strategy.genome.isNotEmpty)
            TsarCard(
              title: 'GENOME',
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.black26,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  strategy.genome,
                  style: TextStyle(
                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                    fontSize: 12,
                    color: Colors.white60,
                    height: 1.5,
                  ),
                ),
              ),
            ),

          if (strategy.genome.isNotEmpty) const SizedBox(height: 12),

          // Parameters
          if (strategy.params != null && strategy.params!.isNotEmpty)
            TsarCard(
              title: 'PARAMETERS',
              child: Column(
                children: strategy.params!.entries.map((e) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(e.key, style: const TextStyle(color: Colors.white38, fontSize: 13)),
                      Text('${e.value}', style: TsarTheme.numberStyle.copyWith(fontSize: 13)),
                    ],
                  ),
                )).toList(),
              ),
            ),

          if (strategy.params != null && strategy.params!.isNotEmpty) const SizedBox(height: 12),

          // Metadata
          TsarCard(
            title: 'INFO',
            child: Column(
              children: [
                _infoRow('ID', strategy.id),
                _infoRow('Status', strategy.status.toUpperCase()),
                _infoRow('Created', _formatDate(strategy.createdAt)),
                if (strategy.lastTradeAt != null)
                  _infoRow('Last Trade', _formatDate(strategy.lastTradeAt!)),
              ],
            ),
          ),

          const SizedBox(height: 24),

          // Action buttons
          _buildActionButtons(strategy),

          const SizedBox(height: 80),
        ],
      ),
    );
  }

  Widget _buildStatusHeader(Strategy strategy) {
    final isActive = strategy.isActive;
    return TsarCard(
      borderColor: isActive ? TsarTheme.profit.withOpacity(0.3) : null,
      child: Row(
        children: [
          Container(
            width: 4,
            height: 50,
            decoration: BoxDecoration(
              color: isActive ? TsarTheme.profit : Colors.white24,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  strategy.name,
                  style: TsarTheme.numberLarge.copyWith(fontSize: 22),
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    StatusDot(status: isActive ? 'active' : 'inactive'),
                    const SizedBox(width: 6),
                    Text(
                      strategy.status.toUpperCase(),
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 12,
                        color: isActive ? TsarTheme.profit : Colors.white38,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          PnlBadge(value: strategy.totalReturn, large: true),
        ],
      ),
    );
  }

  Widget _buildMetricsGrid(Strategy strategy) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(child: _metricTile('Sharpe Ratio', strategy.sharpeRatio.toStringAsFixed(2), TsarTheme.accent)),
            const SizedBox(width: 8),
            Expanded(child: _metricTile('Win Rate', '${strategy.winRate.toStringAsFixed(1)}%', TsarTheme.profit)),
            const SizedBox(width: 8),
            Expanded(child: _metricTile('Max DD', '${strategy.maxDrawdown.toStringAsFixed(2)}%', TsarTheme.loss)),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(child: _metricTile('Profit Factor', strategy.profitFactor.toStringAsFixed(2), TsarTheme.warning)),
            const SizedBox(width: 8),
            Expanded(child: _metricTile('Trade Count', '${strategy.tradeCount}', TsarTheme.info)),
            const SizedBox(width: 8),
            Expanded(child: _metricTile('Total Return', '${strategy.totalReturn.toStringAsFixed(2)}%', strategy.totalReturn >= 0 ? TsarTheme.profit : TsarTheme.loss)),
          ],
        ),
      ],
    );
  }

  Widget _metricTile(String label, String value, Color color) {
    return TsarCard(
      child: Column(
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 10)),
          const SizedBox(height: 4),
          Text(value, style: TsarTheme.numberStyle.copyWith(color: color, fontSize: 15)),
        ],
      ),
    );
  }

  Widget _buildPerformanceChart(Strategy strategy) {
    // Synthetic performance visualization from available metrics
    final winRate = strategy.winRate;
    final lossRate = 100 - winRate;
    return TsarCard(
      title: 'WIN/LOSS DISTRIBUTION',
      child: Row(
        children: [
          Expanded(
            flex: winRate.round().clamp(1, 99),
            child: Container(
              height: 24,
              decoration: BoxDecoration(
                color: TsarTheme.profit.withOpacity(0.7),
                borderRadius: const BorderRadius.horizontal(left: Radius.circular(4)),
              ),
              child: Center(
                child: Text(
                  '${winRate.toStringAsFixed(0)}%',
                  style: TextStyle(
                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            flex: lossRate.round().clamp(1, 99),
            child: Container(
              height: 24,
              decoration: BoxDecoration(
                color: TsarTheme.loss.withOpacity(0.7),
                borderRadius: const BorderRadius.horizontal(right: Radius.circular(4)),
              ),
              child: Center(
                child: Text(
                  '${lossRate.toStringAsFixed(0)}%',
                  style: TextStyle(
                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildActionButtons(Strategy strategy) {
    return Column(
      children: [
        // Start/Stop button
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton.icon(
            onPressed: _actionLoading ? null : () => _toggleStrategy(strategy),
            icon: _actionLoading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : Icon(strategy.isActive ? Icons.stop : Icons.play_arrow),
            label: Text(strategy.isActive ? 'STOP STRATEGY' : 'START STRATEGY'),
            style: ElevatedButton.styleFrom(
              backgroundColor: strategy.isActive ? TsarTheme.loss : TsarTheme.profit,
              disabledBackgroundColor: (strategy.isActive ? TsarTheme.loss : TsarTheme.profit).withOpacity(0.3),
            ),
          ),
        ),
        const SizedBox(height: 8),

        // Backtest button
        SizedBox(
          width: double.infinity,
          height: 48,
          child: OutlinedButton.icon(
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => BacktestScreen(strategyId: strategy.id),
                ),
              );
            },
            icon: const Icon(Icons.analytics_outlined),
            label: const Text('RUN BACKTEST'),
            style: OutlinedButton.styleFrom(
              foregroundColor: TsarTheme.accent,
              side: const BorderSide(color: TsarTheme.accent),
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _toggleStrategy(Strategy strategy) async {
    final api = context.read<ApiService>();
    setState(() => _actionLoading = true);

    try {
      if (strategy.isActive) {
        await api.deactivateStrategy(strategy.id);
      } else {
        await api.activateStrategy(strategy.id);
      }

      // Reload strategy state
      await _loadStrategy();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              strategy.isActive
                  ? '${strategy.name} stopped'
                  : '${strategy.name} started',
            ),
            backgroundColor: strategy.isActive ? TsarTheme.warning : TsarTheme.profit,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed: $e'),
            backgroundColor: TsarTheme.loss,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _actionLoading = false);
    }
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 13)),
          Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 13)),
        ],
      ),
    );
  }

  String _formatDate(DateTime dt) {
    return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';
  }
}
