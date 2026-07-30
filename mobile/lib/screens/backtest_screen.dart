import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../theme.dart';
import '../models/strategy.dart';
import '../providers/strategy_provider.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

/// Backtest screen — maps to POST /api/v1/backtest.
///
/// Allows selecting a strategy, configuring parameters,
/// running a backtest, and viewing the results with equity curve,
/// monthly returns heatmap, and key metrics.
class BacktestScreen extends StatefulWidget {
  final String? strategyId;
  const BacktestScreen({super.key, this.strategyId});

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  String? _selectedStrategyId;
  final _startDateController = TextEditingController();
  final _endDateController = TextEditingController();
  final _initialCapitalController = TextEditingController(text: '100000');
  bool _showResults = false;

  @override
  void initState() {
    super.initState();
    _selectedStrategyId = widget.strategyId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<StrategyProvider>().refresh();
    });
  }

  @override
  void dispose() {
    _startDateController.dispose();
    _endDateController.dispose();
    _initialCapitalController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Backtest'),
        actions: [
          if (_showResults)
            IconButton(
              icon: const Icon(Icons.tune),
              onPressed: () => setState(() => _showResults = false),
              tooltip: 'Configure',
            ),
        ],
      ),
      body: Consumer<StrategyProvider>(
        builder: (context, provider, _) {
          if (_showResults && provider.lastBacktest != null) {
            return _buildResults(provider.lastBacktest!);
          }
          return _buildConfiguration(provider);
        },
      ),
    );
  }

  Widget _buildConfiguration(StrategyProvider provider) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TsarCard(
          title: 'SELECT STRATEGY',
          child: provider.strategies.isEmpty
              ? const Text(
                  'No strategies loaded. Pull to refresh.',
                  style: TextStyle(color: Colors.white38),
                )
              : Column(
                  children: provider.strategies.map((s) {
                    final isSelected = s.id == _selectedStrategyId;
                    return RadioListTile<String>(
                      value: s.id,
                      groupValue: _selectedStrategyId,
                      onChanged: (v) => setState(() => _selectedStrategyId = v),
                      activeColor: TsarTheme.accent,
                      title: Text(
                        s.name,
                        style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                      ),
                      subtitle: Text(
                        '${s.tradeCount} trades · ${(s.winRate).toStringAsFixed(1)}% win',
                        style: const TextStyle(color: Colors.white38, fontSize: 12),
                      ),
                      secondary: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: (s.isActive ? TsarTheme.profit : Colors.white24).withOpacity(0.15),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          s.status.toUpperCase(),
                          style: TextStyle(
                            fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                            fontSize: 10,
                            color: s.isActive ? TsarTheme.profit : Colors.white38,
                          ),
                        ),
                      ),
                      contentPadding: EdgeInsets.zero,
                    );
                  }).toList(),
                ),
        ),

        const SizedBox(height: 12),

        TsarCard(
          title: 'PARAMETERS',
          child: Column(
            children: [
              _buildDateField('Start Date', _startDateController),
              const SizedBox(height: 12),
              _buildDateField('End Date', _endDateController),
              const SizedBox(height: 12),
              TextField(
                controller: _initialCapitalController,
                style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: 'Initial Capital',
                  labelStyle: const TextStyle(color: Colors.white38),
                  prefixText: '\$ ',
                  prefixStyle: TextStyle(
                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                    color: TsarTheme.accent,
                  ),
                  filled: true,
                  fillColor: Colors.black26,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: 24),

        SizedBox(
          width: double.infinity,
          height: 50,
          child: ElevatedButton.icon(
            onPressed: _selectedStrategyId == null || provider.backtestLoading
                ? null
                : () => _runBacktest(provider),
            icon: provider.backtestLoading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.play_arrow),
            label: Text(provider.backtestLoading ? 'RUNNING...' : 'RUN BACKTEST'),
            style: ElevatedButton.styleFrom(
              backgroundColor: TsarTheme.accent,
              disabledBackgroundColor: TsarTheme.accent.withOpacity(0.3),
            ),
          ),
        ),

        if (provider.error != null) ...[
          const SizedBox(height: 16),
          ErrorBanner(
            message: provider.error!,
            onRetry: _selectedStrategyId != null
                ? () => _runBacktest(provider)
                : null,
          ),
        ],
      ],
    );
  }

  Widget _buildDateField(String label, TextEditingController controller) {
    return TextField(
      controller: controller,
      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
      readOnly: true,
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: Colors.white38),
        filled: true,
        fillColor: Colors.black26,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide.none,
        ),
        suffixIcon: const Icon(Icons.calendar_today, size: 18, color: Colors.white38),
      ),
      onTap: () async {
        final date = await showDatePicker(
          context: context,
          initialDate: DateTime.now().subtract(const Duration(days: 365)),
          firstDate: DateTime(2020),
          lastDate: DateTime.now(),
          builder: (ctx, child) => Theme(
            data: ThemeData.dark().copyWith(
              colorScheme: const ColorScheme.dark(primary: TsarTheme.accent),
            ),
            child: child!,
          ),
        );
        if (date != null) {
          controller.text = DateFormat('yyyy-MM-dd').format(date);
        }
      },
    );
  }

  Future<void> _runBacktest(StrategyProvider provider) async {
    final params = <String, dynamic>{};
    if (_startDateController.text.isNotEmpty) {
      params['start_date'] = _startDateController.text;
    }
    if (_endDateController.text.isNotEmpty) {
      params['end_date'] = _endDateController.text;
    }
    if (_initialCapitalController.text.isNotEmpty) {
      params['initial_capital'] = double.tryParse(_initialCapitalController.text);
    }

    final success = await provider.runBacktest(_selectedStrategyId!, params: params);
    if (success && mounted) {
      setState(() => _showResults = true);
    }
  }

  Widget _buildResults(BacktestResult result) {
    return RefreshIndicator(
      onRefresh: () async {
        setState(() => _showResults = false);
      },
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Header
          TsarCard(
            child: Column(
              children: [
                Text(
                  'BACKTEST RESULTS',
                  style: TsarTheme.numberStyle.copyWith(
                    color: Colors.white38,
                    fontSize: 12,
                    letterSpacing: 1.5,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '${result.totalReturn >= 0 ? '+' : ''}${result.totalReturn.toStringAsFixed(2)}%',
                  style: TsarTheme.pnlLarge(result.totalReturn),
                ),
                const SizedBox(height: 4),
                Text(
                  '${result.totalTrades} trades',
                  style: const TextStyle(color: Colors.white38, fontSize: 13),
                ),
              ],
            ),
          ),

          const SizedBox(height: 12),

          // Metrics grid
          Row(
            children: [
              Expanded(child: _metricCard('Sharpe', result.sharpeRatio.toStringAsFixed(2), TsarTheme.accent)),
              const SizedBox(width: 8),
              Expanded(child: _metricCard('Win Rate', '${result.winRate.toStringAsFixed(1)}%', TsarTheme.profit)),
              const SizedBox(width: 8),
              Expanded(child: _metricCard('Max DD', '${result.maxDrawdown.toStringAsFixed(2)}%', TsarTheme.loss)),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: _metricCard('Profit Factor', result.profitFactor.toStringAsFixed(2), TsarTheme.warning)),
              const SizedBox(width: 8),
              Expanded(child: _metricCard('Total Trades', '${result.totalTrades}', TsarTheme.info)),
              const SizedBox(width: 8),
              Expanded(child: _metricCard('Avg Hold', '${result.avgHoldingPeriod.toStringAsFixed(1)}d', Colors.white54)),
            ],
          ),

          const SizedBox(height: 12),

          // Equity curve
          if (result.equityCurve.isNotEmpty)
            TsarCard(
              title: 'EQUITY CURVE',
              child: _buildEquityCurve(result),
            ),

          const SizedBox(height: 12),

          // Monthly returns
          if (result.monthlyReturns.isNotEmpty)
            TsarCard(
              title: 'MONTHLY RETURNS',
              child: _buildMonthlyReturns(result),
            ),

          const SizedBox(height: 12),

          // Run again button
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => setState(() => _showResults = false),
              icon: const Icon(Icons.tune),
              label: const Text('MODIFY PARAMETERS'),
              style: OutlinedButton.styleFrom(
                foregroundColor: TsarTheme.accent,
                side: const BorderSide(color: TsarTheme.accent),
              ),
            ),
          ),
          const SizedBox(height: 80),
        ],
      ),
    );
  }

  Widget _metricCard(String label, String value, Color color) {
    return TsarCard(
      child: Column(
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
          const SizedBox(height: 4),
          Text(value, style: TsarTheme.numberStyle.copyWith(color: color, fontSize: 16)),
        ],
      ),
    );
  }

  Widget _buildEquityCurve(BacktestResult result) {
    final points = result.equityCurve;
    final spots = <FlSpot>[];
    for (var i = 0; i < points.length; i++) {
      final val = points[i]['value'] ?? points[i]['equity'] ?? 0;
      spots.add(FlSpot(i.toDouble(), (val as num).toDouble()));
    }
    return PnlLineChart(spots: spots, height: 200);
  }

  Widget _buildMonthlyReturns(BacktestResult result) {
    final months = result.monthlyReturns.entries.toList();
    if (months.isEmpty) return const SizedBox.shrink();

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: months.map((entry) {
        final ret = (entry.value as num?)?.toDouble() ?? 0;
        final color = ret >= 0 ? TsarTheme.profit : TsarTheme.loss;
        return Container(
          width: 60,
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
          decoration: BoxDecoration(
            color: color.withOpacity(0.12),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: color.withOpacity(0.3)),
          ),
          child: Column(
            children: [
              Text(
                entry.key,
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 10,
                  color: Colors.white38,
                ),
              ),
              Text(
                '${ret >= 0 ? '+' : ''}${ret.toStringAsFixed(1)}%',
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }
}
