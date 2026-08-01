import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme.dart';
import '../models/scenario.dart';
import '../providers/blockchain_provider.dart';
import '../widgets/cards.dart';

class ScenarioScreen extends StatefulWidget {
  const ScenarioScreen({super.key});

  @override
  State<ScenarioScreen> createState() => _ScenarioScreenState();
}

class _ScenarioScreenState extends State<ScenarioScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<BlockchainProvider>().refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scenario Prevention'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<BlockchainProvider>().refresh(),
          ),
        ],
      ),
      body: Consumer<BlockchainProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.scenarios.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.scenarios.isEmpty) {
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
                _buildStatusOverview(provider),
                const SizedBox(height: 12),
                _buildTriggeredSection(provider),
                const SizedBox(height: 12),
                _buildActiveSection(provider),
                const SizedBox(height: 12),
                _buildAllScenarios(provider),
                const SizedBox(height: 80),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildStatusOverview(BlockchainProvider provider) {
    final active = provider.activeScenarios.length;
    final triggered = provider.triggeredScenarios.length;
    final total = provider.scenarios.length;

    return TsarCard(
      child: Column(
        children: [
          Text(
            'SCENARIO MONITORING',
            style: TsarTheme.numberStyle.copyWith(
              color: Colors.white38,
              fontSize: 12,
              letterSpacing: 1.5,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _statusItem('🟢', 'Active', '$active', TsarTheme.info),
              _statusItem('🔴', 'Triggered', '$triggered', triggered > 0 ? TsarTheme.loss : Colors.white54),
              _statusItem('📊', 'Total', '$total', Colors.white70),
            ],
          ),
          if (triggered > 0) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: TsarTheme.loss.withOpacity(0.12),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  const Icon(Icons.warning_amber, size: 16, color: TsarTheme.loss),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '$triggered scenario(s) require attention',
                      style: const TextStyle(color: TsarTheme.loss, fontSize: 12),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _statusItem(String emoji, String label, String value, Color color) {
    return Column(
      children: [
        Text(emoji, style: const TextStyle(fontSize: 20)),
        const SizedBox(height: 4),
        Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 18, color: color)),
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
      ],
    );
  }

  Widget _buildTriggeredSection(BlockchainProvider provider) {
    final triggered = provider.triggeredScenarios;
    if (triggered.isEmpty) return const SizedBox.shrink();

    return TsarCard(
      title: '⚠️ TRIGGERED SCENARIOS',
      borderColor: TsarTheme.loss.withOpacity(0.3),
      child: Column(
        children: triggered.map((s) => _ScenarioRow(scenario: s)).toList(),
      ),
    );
  }

  Widget _buildActiveSection(BlockchainProvider provider) {
    final active = provider.activeScenarios;
    if (active.isEmpty) return const SizedBox.shrink();

    return TsarCard(
      title: '🛡️ MONITORING (${active.length})',
      child: Column(
        children: active.map((s) => _ScenarioRow(scenario: s)).toList(),
      ),
    );
  }

  Widget _buildAllScenarios(BlockchainProvider provider) {
    if (provider.scenarios.isEmpty) {
      return const EmptyState(
        icon: Icons.shield_outlined,
        title: 'No scenarios configured',
        subtitle: 'Scenario prevention rules will appear here',
      );
    }

    return TsarCard(
      title: 'ALL SCENARIOS (${provider.scenarios.length})',
      child: Column(
        children: provider.scenarios.map((s) => _ScenarioRow(scenario: s, showDetail: true)).toList(),
      ),
    );
  }
}

class _ScenarioRow extends StatelessWidget {
  final Scenario scenario;
  final bool showDetail;

  const _ScenarioRow({required this.scenario, this.showDetail = false});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: showDetail ? () => _showDetail(context) : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              Text(scenario.riskEmoji, style: const TextStyle(fontSize: 16)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      scenario.name,
                      style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                    ),
                    if (showDetail && scenario.description.isNotEmpty)
                      Text(
                        scenario.description,
                        style: const TextStyle(color: Colors.white38, fontSize: 11),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: scenario.statusColor.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  scenario.statusLabel,
                  style: TextStyle(
                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                    fontSize: 10,
                    color: scenario.statusColor,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showDetail(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        maxChildSize: 0.9,
        minChildSize: 0.3,
        expand: false,
        builder: (ctx, sc) => ListView(
          controller: sc,
          padding: const EdgeInsets.all(24),
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.white24,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Text(scenario.riskEmoji, style: const TextStyle(fontSize: 24)),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(scenario.name, style: TsarTheme.numberLarge.copyWith(fontSize: 20)),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(scenario.description, style: const TextStyle(color: Colors.white70, fontSize: 15)),
            const Divider(height: 32),
            _detailRow('Category', scenario.category.toUpperCase()),
            _detailRow('Risk Level', '${(scenario.riskLevel * 100).toStringAsFixed(1)}%'),
            _detailRow('Trigger', scenario.triggerCondition),
            if (scenario.preventionAction != null)
              _detailRow('Prevention', scenario.preventionAction!),
          ],
        ),
      ),
    );
  }

  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(label, style: const TextStyle(color: Colors.white38, fontSize: 13)),
          ),
          Expanded(
            child: Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 13)),
          ),
        ],
      ),
    );
  }
}
