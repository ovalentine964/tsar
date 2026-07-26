import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../models/factor.dart';
import '../providers/factor_provider.dart';
import '../widgets/cards.dart';

class FactorsScreen extends StatefulWidget {
  const FactorsScreen({super.key});

  @override
  State<FactorsScreen> createState() => _FactorsScreenState();
}

class _FactorsScreenState extends State<FactorsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  String _sortBy = 'ic';

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<FactorProvider>().refresh();
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
        title: const Text('Factors'),
        actions: [
          PopupMenuButton<String>(
            icon: const Icon(Icons.sort),
            onSelected: (v) => setState(() => _sortBy = v),
            itemBuilder: (_) => [
              const PopupMenuItem(value: 'ic', child: Text('Sort by IC')),
              const PopupMenuItem(value: 'ir', child: Text('Sort by IR')),
              const PopupMenuItem(value: 'name', child: Text('Sort by Name')),
            ],
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<FactorProvider>().refresh(),
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          labelColor: TsarTheme.accent,
          unselectedLabelColor: Colors.white38,
          indicatorColor: TsarTheme.accent,
          tabs: const [
            Tab(text: 'All'),
            Tab(text: 'Categories'),
            Tab(text: 'Rankings'),
          ],
        ),
      ),
      body: Consumer<FactorProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.factors.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.factors.isEmpty) {
            return ErrorBanner(
              message: provider.error!,
              onRetry: () => provider.refresh(),
            );
          }

          return TabBarView(
            controller: _tabController,
            children: [
              _buildAllFactors(provider),
              _buildCategories(provider),
              _buildRankings(provider),
            ],
          );
        },
      ),
    );
  }

  Widget _buildAllFactors(FactorProvider provider) {
    final factors = _sorted(provider.factors);

    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: Column(
        children: [
          _buildCategoryFilter(provider),
          Expanded(
            child: factors.isEmpty
                ? const EmptyState(
                    icon: Icons.science_outlined,
                    title: 'No factors found',
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    itemCount: factors.length,
                    itemBuilder: (context, index) => _FactorTile(factor: factors[index]),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildCategoryFilter(FactorProvider provider) {
    return Container(
      height: 44,
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: [
          _filterChip(null, 'All', provider),
          ...provider.categories.map((c) => _filterChip(c.name, c.name, provider)),
        ],
      ),
    );
  }

  Widget _filterChip(String? value, String label, FactorProvider provider) {
    final isSelected = provider.selectedCategory == value;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: FilterChip(
        label: Text(label),
        selected: isSelected,
        selectedColor: TsarTheme.accent.withOpacity(0.3),
        checkmarkColor: TsarTheme.accent,
        onSelected: (_) => provider.setCategory(value),
      ),
    );
  }

  Widget _buildCategories(FactorProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: provider.categories.length,
        itemBuilder: (context, index) {
          final cat = provider.categories[index];
          return TsarCard(
            title: '${cat.count} FACTORS',
            trailing: const Icon(Icons.chevron_right, color: Colors.white24),
            onTap: () {
              provider.setCategory(cat.name);
              _tabController.animateTo(0);
            },
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  cat.name.toUpperCase(),
                  style: TsarTheme.numberStyle.copyWith(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  cat.description,
                  style: TextStyle(color: Colors.white54, fontSize: 13),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildRankings(FactorProvider provider) {
    final sorted = _sortBy == 'ic' ? provider.factorsByIC : provider.factorsByIR;

    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Text(
                  'RANKED BY ${_sortBy.toUpperCase()}',
                  style: TsarTheme.numberStyle.copyWith(
                    color: Colors.white38,
                    fontSize: 12,
                    letterSpacing: 1.2,
                  ),
                ),
                const Spacer(),
                Text(
                  '${sorted.length} factors',
                  style: TextStyle(color: Colors.white24, fontSize: 12),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              itemCount: sorted.length,
              itemBuilder: (context, index) {
                final factor = sorted[index];
                return Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 28,
                          child: Text(
                            '#${index + 1}',
                            style: TsarTheme.numberStyle.copyWith(
                              color: index < 3 ? TsarTheme.accent : Colors.white24,
                              fontSize: 12,
                            ),
                          ),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                factor.name,
                                style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                              ),
                              Text(
                                factor.category,
                                style: TextStyle(
                                    color: Colors.white30, fontSize: 11),
                              ),
                            ],
                          ),
                        ),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              'IC: ${factor.icFormatted}',
                              style: TsarTheme.numberStyle.copyWith(
                                fontSize: 12,
                                color: factor.ic >= 0 ? TsarTheme.profit : TsarTheme.loss,
                              ),
                            ),
                            Text(
                              'IR: ${factor.irFormatted}',
                              style: TsarTheme.numberStyle.copyWith(
                                fontSize: 12,
                                color: factor.ir >= 0 ? TsarTheme.profit : TsarTheme.loss,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  List<Factor> _sorted(List<Factor> factors) {
    final list = List<Factor>.from(factors);
    switch (_sortBy) {
      case 'ic':
        list.sort((a, b) => b.ic.abs().compareTo(a.ic.abs()));
        break;
      case 'ir':
        list.sort((a, b) => b.ir.abs().compareTo(a.ir.abs()));
        break;
      case 'name':
        list.sort((a, b) => a.name.compareTo(b.name));
        break;
    }
    return list;
  }
}

class _FactorTile extends StatelessWidget {
  final Factor factor;
  const _FactorTile({required this.factor});

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
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      factor.name,
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                    ),
                  ),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: TsarTheme.accent.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      factor.category,
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: TsarTheme.accent,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                factor.description,
                style: TextStyle(color: Colors.white54, fontSize: 12),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  _metric('IC', factor.icFormatted, factor.ic),
                  const SizedBox(width: 16),
                  _metric('IR', factor.irFormatted, factor.ir),
                  const SizedBox(width: 16),
                  _metric('Turnover', factor.turnover.toStringAsFixed(2), 0),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _metric(String label, String value, double colorVal) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 10, color: Colors.white24)),
        Text(
          value,
          style: TsarTheme.numberStyle.copyWith(
            fontSize: 12,
            color: colorVal > 0
                ? TsarTheme.profit
                : colorVal < 0
                    ? TsarTheme.loss
                    : Colors.white70,
          ),
        ),
      ],
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
        initialChildSize: 0.7,
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
            Text(factor.name, style: TsarTheme.numberLarge),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: TsarTheme.accent.withOpacity(0.12),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                factor.category,
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 12,
                  color: TsarTheme.accent,
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text(factor.description,
                style: TextStyle(color: Colors.white70, fontSize: 15)),
            const Divider(height: 32),
            _detailRow('IC (Information Coefficient)', factor.icFormatted),
            _detailRow('IR (Information Ratio)', factor.irFormatted),
            _detailRow('Turnover', factor.turnover.toStringAsFixed(4)),
            _detailRow('Correlation', factor.correlation.toStringAsFixed(4)),
            const Divider(height: 32),
            Text('COMPUTATION',
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 11,
                  color: Colors.white38,
                  letterSpacing: 1.2,
                )),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.black26,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                factor.computation,
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 12,
                  color: Colors.white60,
                ),
              ),
            ),
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
          Text(label, style: TextStyle(color: Colors.white38, fontSize: 13)),
          Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 14)),
        ],
      ),
    );
  }
}
