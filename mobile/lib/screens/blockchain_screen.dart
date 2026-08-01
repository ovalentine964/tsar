import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import '../theme.dart';
import '../models/scenario.dart';
import '../providers/blockchain_provider.dart';
import '../widgets/cards.dart';

class BlockchainScreen extends StatefulWidget {
  const BlockchainScreen({super.key});

  @override
  State<BlockchainScreen> createState() => _BlockchainScreenState();
}

class _BlockchainScreenState extends State<BlockchainScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<BlockchainProvider>().refresh();
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Blockchain & Rules'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<BlockchainProvider>().refresh(),
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          labelColor: TsarTheme.accent,
          unselectedLabelColor: Colors.white38,
          indicatorColor: TsarTheme.accent,
          tabs: const [
            Tab(text: 'Rules'),
            Tab(text: 'Scenarios'),
            Tab(text: 'Audit Trail'),
          ],
        ),
      ),
      body: Consumer<BlockchainProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.rules.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.rules.isEmpty) {
            return ErrorBanner(
              message: provider.error!,
              onRetry: () => provider.refresh(),
            );
          }

          return TabBarView(
            controller: _tabController,
            children: [
              _buildRules(provider),
              _buildScenarios(provider),
              _buildAuditTrail(provider),
            ],
          );
        },
      ),
    );
  }

  Widget _buildRules(BlockchainProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Summary
          TsarCard(
            child: Row(
              children: [
                Expanded(
                  child: _summaryStat(
                    'Active Rules',
                    '${provider.activeRuleCount}',
                    Icons.rule,
                    TsarTheme.profit,
                  ),
                ),
                Expanded(
                  child: _summaryStat(
                    'Total Rules',
                    '${provider.rules.length}',
                    Icons.list_alt,
                    TsarTheme.info,
                  ),
                ),
                Expanded(
                  child: _summaryStat(
                    'Scenarios',
                    '${provider.scenarios.length}',
                    Icons.shield,
                    TsarTheme.accent,
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 12),

          // Rules list
          if (provider.rules.isEmpty)
            const EmptyState(
              icon: Icons.rule_outlined,
              title: 'No on-chain rules',
              subtitle: 'Rules will appear here when configured',
            )
          else
            ...provider.rules.map((rule) => _RuleTile(rule: rule)),
        ],
      ),
    );
  }

  Widget _summaryStat(String label, String value, IconData icon, Color color) {
    return Column(
      children: [
        Icon(icon, color: color, size: 20),
        const SizedBox(height: 4),
        Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 18)),
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
      ],
    );
  }

  Widget _buildScenarios(BlockchainProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Status summary
          if (provider.triggeredScenarios.isNotEmpty)
            Container(
              padding: const EdgeInsets.all(14),
              margin: const EdgeInsets.only(bottom: 12),
              decoration: BoxDecoration(
                color: TsarTheme.loss.withOpacity(0.15),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: TsarTheme.loss.withOpacity(0.4)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.warning_amber, color: TsarTheme.loss),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '${provider.triggeredScenarios.length} scenario(s) triggered',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontWeight: FontWeight.w700,
                        color: TsarTheme.loss,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),

          if (provider.scenarios.isEmpty)
            const EmptyState(
              icon: Icons.shield_outlined,
              title: 'No scenarios configured',
              subtitle: 'Scenario prevention rules will appear here',
            )
          else
            ...provider.scenarios.map((s) => _ScenarioTile(scenario: s)),
        ],
      ),
    );
  }

  Widget _buildAuditTrail(BlockchainProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: provider.auditTrail.isEmpty
          ? const EmptyState(
              icon: Icons.history,
              title: 'No audit entries',
              subtitle: 'On-chain audit trail will appear here',
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: provider.auditTrail.length,
              itemBuilder: (context, index) =>
                  _AuditTile(entry: provider.auditTrail[index]),
            ),
    );
  }
}

class _RuleTile extends StatelessWidget {
  final OnChainRule rule;
  const _RuleTile({required this.rule});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(rule.typeIcon, size: 18, color: rule.isActive ? TsarTheme.accent : Colors.white24),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    rule.name,
                    style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: (rule.isActive ? TsarTheme.profit : Colors.white24).withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    rule.isActive ? 'ACTIVE' : 'INACTIVE',
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 10,
                      color: rule.isActive ? TsarTheme.profit : Colors.white38,
                    ),
                  ),
                ),
              ],
            ),
            if (rule.description.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                rule.description,
                style: const TextStyle(color: Colors.white54, fontSize: 12),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ],
            const SizedBox(height: 8),
            Row(
              children: [
                if (rule.chain.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: TsarTheme.info.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      rule.chain.toUpperCase(),
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: TsarTheme.info,
                      ),
                    ),
                  ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: TsarTheme.accent.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    rule.ruleType.toUpperCase(),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 10,
                      color: TsarTheme.accent,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ScenarioTile extends StatelessWidget {
  final Scenario scenario;
  const _ScenarioTile({required this.scenario});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: scenario.isTriggered
              ? TsarTheme.loss.withOpacity(0.4)
              : TsarTheme.cardBorder,
          width: scenario.isTriggered ? 1.5 : 1,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _showDetail(context),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(scenario.riskEmoji, style: const TextStyle(fontSize: 16)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      scenario.name,
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
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
              const SizedBox(height: 6),
              Text(
                scenario.description,
                style: const TextStyle(color: Colors.white54, fontSize: 12),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Icon(scenario.categoryIcon, size: 14, color: Colors.white38),
                  const SizedBox(width: 6),
                  Text(
                    scenario.category.toUpperCase(),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 10,
                      color: Colors.white38,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    'Risk: ${(scenario.riskLevel * 100).toStringAsFixed(0)}%',
                    style: TsarTheme.numberStyle.copyWith(
                      fontSize: 11,
                      color: scenario.riskLevel >= 0.7
                          ? TsarTheme.loss
                          : scenario.riskLevel >= 0.4
                              ? TsarTheme.warning
                              : TsarTheme.profit,
                    ),
                  ),
                ],
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
        initialChildSize: 0.6,
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
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: scenario.statusColor.withOpacity(0.15),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                scenario.statusLabel,
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 12,
                  color: scenario.statusColor,
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              scenario.description,
              style: const TextStyle(color: Colors.white70, fontSize: 15, height: 1.5),
            ),
            const Divider(height: 32),
            _detailRow('Category', scenario.category.toUpperCase()),
            _detailRow('Risk Level', '${(scenario.riskLevel * 100).toStringAsFixed(1)}%'),
            _detailRow('Trigger', scenario.triggerCondition),
            if (scenario.preventionAction != null)
              _detailRow('Prevention', scenario.preventionAction!),
            if (scenario.triggeredAt != null)
              _detailRow('Triggered At', DateFormat('yyyy-MM-dd HH:mm').format(scenario.triggeredAt!)),
            if (scenario.clearedAt != null)
              _detailRow('Cleared At', DateFormat('yyyy-MM-dd HH:mm').format(scenario.clearedAt!)),
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

class _AuditTile extends StatelessWidget {
  final AuditEntry entry;
  const _AuditTile({required this.entry});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(entry.actorIcon, size: 16, color: TsarTheme.accent),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: TsarTheme.accent.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    entry.action.toUpperCase(),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 10,
                      color: TsarTheme.accent,
                    ),
                  ),
                ),
                const Spacer(),
                Text(
                  _formatTime(entry.timestamp),
                  style: const TextStyle(color: Colors.white24, fontSize: 11),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              entry.detail,
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
            if (entry.txHash != null) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Icon(Icons.link, size: 12, color: Colors.white24),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      entry.txHash!,
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: TsarTheme.info,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return DateFormat('MMM dd').format(dt);
  }
}
