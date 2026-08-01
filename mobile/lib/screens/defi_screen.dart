import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import '../theme.dart';
import '../models/defi_position.dart';
import '../providers/defi_provider.dart';
import '../widgets/cards.dart';

class DeFiScreen extends StatefulWidget {
  const DeFiScreen({super.key});

  @override
  State<DeFiScreen> createState() => _DeFiScreenState();
}

class _DeFiScreenState extends State<DeFiScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<DeFiProvider>().refresh();
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
        title: const Text('DeFi Positions'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<DeFiProvider>().refresh(),
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          labelColor: TsarTheme.accent,
          unselectedLabelColor: Colors.white38,
          indicatorColor: TsarTheme.accent,
          tabs: const [
            Tab(text: 'Overview'),
            Tab(text: 'Positions'),
            Tab(text: 'Cross-Chain'),
          ],
        ),
      ),
      body: Consumer<DeFiProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.positions.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.positions.isEmpty) {
            return ErrorBanner(
              message: provider.error!,
              onRetry: () => provider.refresh(),
            );
          }

          return TabBarView(
            controller: _tabController,
            children: [
              _buildOverview(provider),
              _buildPositions(provider),
              _buildCrossChain(provider),
            ],
          );
        },
      ),
    );
  }

  Widget _buildOverview(DeFiProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Total value card
          TsarCard(
            child: Column(
              children: [
                Text(
                  'TOTAL DeFi VALUE',
                  style: TsarTheme.numberStyle.copyWith(
                    color: Colors.white38,
                    fontSize: 12,
                    letterSpacing: 1.5,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '\$${_formatNumber(provider.totalValueUsd)}',
                  style: TsarTheme.numberLarge.copyWith(fontSize: 28),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: _overviewStat(
                        'Yield Earned',
                        '\$${_formatNumber(provider.totalYieldEarned)}',
                        TsarTheme.profit,
                      ),
                    ),
                    Expanded(
                      child: _overviewStat(
                        'Avg APY',
                        provider.summary != null
                            ? '${provider.summary!.averageApy.toStringAsFixed(1)}%'
                            : '—',
                        TsarTheme.accent,
                      ),
                    ),
                    Expanded(
                      child: _overviewStat(
                        'Positions',
                        '${provider.activePositions.length}',
                        TsarTheme.info,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const SizedBox(height: 12),

          // Yield summary
          if (provider.summary != null) ...[
            TsarCard(
              title: 'YIELD BREAKDOWN',
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: _yieldStat(
                          'Total Value',
                          '\$${_formatNumber(provider.summary!.totalValueUsd)}',
                          Icons.account_balance_wallet,
                        ),
                      ),
                      Expanded(
                        child: _yieldStat(
                          'Total Earned',
                          '\$${_formatNumber(provider.summary!.totalYieldEarned)}',
                          Icons.trending_up,
                          TsarTheme.profit,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: _yieldStat(
                          'Avg APY',
                          '${provider.summary!.averageApy.toStringAsFixed(2)}%',
                          Icons.percent,
                          TsarTheme.accent,
                        ),
                      ),
                      Expanded(
                        child: _yieldStat(
                          'Active',
                          '${provider.summary!.activePositions}',
                          Icons.layers,
                          TsarTheme.info,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Type breakdown
          if (provider.summary != null &&
              provider.summary!.typeBreakdown.isNotEmpty)
            TsarCard(
              title: 'BY TYPE',
              child: Column(
                children: provider.summary!.typeBreakdown.entries.map((entry) {
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            entry.key.toUpperCase(),
                            style: TsarTheme.numberStyle.copyWith(fontSize: 12),
                          ),
                        ),
                        Text(
                          '\$${_formatNumber(entry.value)}',
                          style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                        ),
                      ],
                    ),
                  );
                }).toList(),
              ),
            ),
        ],
      ),
    );
  }

  Widget _overviewStat(String label, String value, Color color) {
    return Column(
      children: [
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
        const SizedBox(height: 4),
        Text(
          value,
          style: TsarTheme.numberStyle.copyWith(color: color, fontSize: 16),
        ),
      ],
    );
  }

  Widget _yieldStat(String label, String value, IconData icon, [Color? color]) {
    return Row(
      children: [
        Icon(icon, size: 16, color: color ?? Colors.white38),
        const SizedBox(width: 8),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(color: Colors.white38, fontSize: 10)),
            Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 14)),
          ],
        ),
      ],
    );
  }

  Widget _buildPositions(DeFiProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: provider.positions.isEmpty
          ? const EmptyState(
              icon: Icons.currency_exchange,
              title: 'No DeFi positions',
              subtitle: 'Positions will appear here when active',
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: provider.positions.length,
              itemBuilder: (context, index) =>
                  _PositionTile(position: provider.positions[index]),
            ),
    );
  }

  Widget _buildCrossChain(DeFiProvider provider) {
    final byChain = provider.positionsByChain;
    if (byChain.isEmpty) {
      return const EmptyState(
        icon: Icons.language,
        title: 'No cross-chain data',
      );
    }

    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: byChain.entries.map((entry) {
          final chain = entry.key;
          final positions = entry.value;
          final totalValue = positions.fold(0.0, (s, p) => s + p.valueUsd);

          return TsarCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 12,
                      height: 12,
                      decoration: BoxDecoration(
                        color: positions.first.chainColor,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      chain.toUpperCase(),
                      style: TsarTheme.numberStyle.copyWith(fontSize: 16, letterSpacing: 1),
                    ),
                    const Spacer(),
                    Text(
                      '\$${_formatNumber(totalValue)}',
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                    ),
                  ],
                ),
                const Divider(height: 20),
                ...positions.map((p) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Icon(p.typeIcon, size: 14, color: Colors.white38),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          '${p.protocol} · ${p.asset}',
                          style: const TextStyle(color: Colors.white70, fontSize: 13),
                        ),
                      ),
                      Text(
                        '\$${_formatNumber(p.valueUsd)}',
                        style: TsarTheme.numberStyle.copyWith(fontSize: 12),
                      ),
                    ],
                  ),
                )),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  String _formatNumber(double v) {
    if (v >= 1000000) return '${(v / 1000000).toStringAsFixed(2)}M';
    if (v >= 1000) return '${(v / 1000).toStringAsFixed(1)}K';
    return v.toStringAsFixed(2);
  }
}

class _PositionTile extends StatelessWidget {
  final DeFiPosition position;
  const _PositionTile({required this.position});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _showDetail(context),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: position.chainColor.withOpacity(0.15),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(position.typeIcon, size: 18, color: position.chainColor),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${position.protocol} · ${position.asset}',
                          style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                        ),
                        Text(
                          '${position.chain.toUpperCase()} · ${position.type.toUpperCase()}',
                          style: const TextStyle(color: Colors.white38, fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        '\$${position.valueUsd.toStringAsFixed(2)}',
                        style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                      ),
                      Text(
                        '${position.apy.toStringAsFixed(1)}% APY',
                        style: TsarTheme.numberStyle.copyWith(
                          fontSize: 12,
                          color: TsarTheme.profit,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              if (position.yieldEarned > 0) ...[
                const Divider(height: 16),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Yield Earned',
                        style: TextStyle(color: Colors.white38, fontSize: 12)),
                    Text(
                      '\$${position.yieldEarned.toStringAsFixed(2)}',
                      style: TsarTheme.pnlStyle(position.yieldEarned),
                    ),
                  ],
                ),
              ],
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
            Text(position.protocol, style: TsarTheme.numberLarge),
            const SizedBox(height: 8),
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: position.chainColor.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    position.chain.toUpperCase(),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 12,
                      color: position.chainColor,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: TsarTheme.accent.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    position.type.toUpperCase(),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 12,
                      color: TsarTheme.accent,
                    ),
                  ),
                ),
              ],
            ),
            const Divider(height: 32),
            _detailRow('Asset', position.asset),
            _detailRow('Amount', position.amount.toStringAsFixed(6)),
            _detailRow('Value', '\$${position.valueUsd.toStringAsFixed(2)}'),
            _detailRow('APY', '${position.apy.toStringAsFixed(2)}%'),
            _detailRow('Yield Earned', '\$${position.yieldEarned.toStringAsFixed(2)}'),
            _detailRow('Status', position.status.toUpperCase()),
            _detailRow('Deposited', DateFormat('yyyy-MM-dd').format(position.depositedAt)),
          ],
        ),
      ),
    );
  }

  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 13)),
          Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 14)),
        ],
      ),
    );
  }
}
