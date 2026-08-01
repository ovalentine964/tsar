import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../models/signal_quality.dart';
import '../providers/signal_quality_provider.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

class SignalQualityScreen extends StatefulWidget {
  const SignalQualityScreen({super.key});

  @override
  State<SignalQualityScreen> createState() => _SignalQualityScreenState();
}

class _SignalQualityScreenState extends State<SignalQualityScreen> {
  final _symbolController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SignalQualityProvider>().refresh();
    });
  }

  @override
  void dispose() {
    _symbolController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Signal Quality'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<SignalQualityProvider>().refresh(),
          ),
        ],
      ),
      body: Consumer<SignalQualityProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.signals.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.signals.isEmpty) {
            return ErrorBanner(
              message: provider.error!,
              onRetry: () => provider.refresh(),
            );
          }

          return RefreshIndicator(
            onRefresh: provider.refresh,
            color: TsarTheme.accent,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _buildEvaluateCard(provider),
                const SizedBox(height: 12),
                if (provider.latest != null) ...[
                  _buildLatestSignalCard(provider.latest!),
                  const SizedBox(height: 12),
                  _buildFactorBreakdown(provider.latest!),
                  const SizedBox(height: 12),
                ],
                _buildSignalsList(provider),
                const SizedBox(height: 80),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildEvaluateCard(SignalQualityProvider provider) {
    return TsarCard(
      title: 'EVALUATE SIGNAL',
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _symbolController,
              style: TsarTheme.numberStyle.copyWith(fontSize: 14),
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                hintText: 'e.g. AAPL, BTC, SPY',
                hintStyle: const TextStyle(color: Colors.white24),
                filled: true,
                fillColor: Colors.black26,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
              ),
            ),
          ),
          const SizedBox(width: 12),
          ElevatedButton.icon(
            onPressed: () {
              final symbol = _symbolController.text.trim().toUpperCase();
              if (symbol.isNotEmpty) {
                provider.evaluate(symbol);
              }
            },
            icon: const Icon(Icons.analytics, size: 18),
            label: const Text('SCORE'),
            style: ElevatedButton.styleFrom(
              backgroundColor: TsarTheme.accent,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLatestSignalCard(SignalQuality signal) {
    return TsarCard(
      borderColor: signal.gradeColor.withOpacity(0.3),
      child: Column(
        children: [
          Row(
            children: [
              Text(
                signal.statusEmoji,
                style: const TextStyle(fontSize: 24),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      signal.symbol,
                      style: TsarTheme.numberLarge.copyWith(fontSize: 22),
                    ),
                    Text(
                      signal.recommendation.isNotEmpty
                          ? signal.recommendation
                          : 'Signal Analysis',
                      style: const TextStyle(color: Colors.white54, fontSize: 13),
                    ),
                  ],
                ),
              ),
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: signal.gradeColor.withOpacity(0.15),
                  shape: BoxShape.circle,
                  border: Border.all(color: signal.gradeColor, width: 2),
                ),
                child: Center(
                  child: Text(
                    signal.grade,
                    style: TsarTheme.numberStyle.copyWith(
                      fontSize: 24,
                      color: signal.gradeColor,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _metricTile(
                  'Overall Score',
                  '${(signal.overallScore * 100).toStringAsFixed(0)}%',
                  signal.gradeColor,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _metricTile(
                  'Confidence',
                  '${(signal.confidence * 100).toStringAsFixed(0)}%',
                  TsarTheme.accent,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _metricTile(
                  'Factors',
                  '${signal.factors.length}',
                  TsarTheme.info,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _metricTile(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 10)),
          const SizedBox(height: 4),
          Text(value, style: TsarTheme.numberStyle.copyWith(color: color, fontSize: 16)),
        ],
      ),
    );
  }

  Widget _buildFactorBreakdown(SignalQuality signal) {
    if (signal.factors.isEmpty) return const SizedBox.shrink();

    return TsarCard(
      title: 'FACTOR BREAKDOWN',
      child: Column(
        children: signal.factors.map((factor) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      factor.scoreEmoji,
                      style: const TextStyle(fontSize: 14),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        factor.name.toUpperCase(),
                        style: TsarTheme.numberStyle.copyWith(fontSize: 12, letterSpacing: 0.8),
                      ),
                    ),
                    Text(
                      '${(factor.score * 100).toStringAsFixed(0)}%',
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 13,
                        color: factor.scoreColor,
                      ),
                    ),
                  ],
                ),
                if (factor.description.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Padding(
                    padding: const EdgeInsets.only(left: 26),
                    child: Text(
                      factor.description,
                      style: const TextStyle(color: Colors.white38, fontSize: 11),
                    ),
                  ),
                ],
                const SizedBox(height: 4),
                Padding(
                  padding: const EdgeInsets.only(left: 26),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: factor.score.clamp(0.0, 1.0),
                      backgroundColor: Colors.white.withOpacity(0.08),
                      valueColor: AlwaysStoppedAnimation(factor.scoreColor),
                      minHeight: 4,
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

  Widget _buildSignalsList(SignalQualityProvider provider) {
    if (provider.signals.isEmpty) return const SizedBox.shrink();

    return TsarCard(
      title: 'SIGNAL HISTORY (${provider.signals.length})',
      child: Column(
        children: provider.signals.map((signal) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                Text(signal.statusEmoji, style: const TextStyle(fontSize: 14)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    signal.symbol,
                    style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                  ),
                ),
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: signal.gradeColor.withOpacity(0.15),
                    shape: BoxShape.circle,
                  ),
                  child: Center(
                    child: Text(
                      signal.grade,
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 12,
                        color: signal.gradeColor,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  '${(signal.overallScore * 100).toStringAsFixed(0)}%',
                  style: TsarTheme.numberStyle.copyWith(
                    fontSize: 13,
                    color: signal.gradeColor,
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }
}
