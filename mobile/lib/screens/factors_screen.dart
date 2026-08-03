import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../models/factor.dart';
import '../providers/factor_provider.dart';
import '../widgets/cards.dart';

// ─────────────────────────────────────────────────────────────────────────────
// Factors Screen — Professional Trading Terminal
// ─────────────────────────────────────────────────────────────────────────────

class FactorsScreen extends StatefulWidget {
  const FactorsScreen({super.key});

  @override
  State<FactorsScreen> createState() => _FactorsScreenState();
}

class _FactorsScreenState extends State<FactorsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final TextEditingController _searchController = TextEditingController();
  String _searchQuery = '';
  String? _selectedCategory;

  static const _categoryTabs = [
    _CategoryTabDef('ALL', Icons.dashboard, null),
    _CategoryTabDef('MOMENTUM', Icons.trending_up, 'momentum'),
    _CategoryTabDef('MEAN REV', Icons.swap_vert, 'mean_reversion'),
    _CategoryTabDef('VOLATILITY', Icons.show_chart, 'volatility'),
    _CategoryTabDef('VOLUME', Icons.bar_chart, 'volume'),
    _CategoryTabDef('TREND', Icons.timeline, 'trend'),
    _CategoryTabDef('PATTERN', Icons.auto_graph, 'pattern'),
  ];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _categoryTabs.length, vsync: this);
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) {
        setState(() {
          _selectedCategory = _categoryTabs[_tabController.index].categoryKey;
        });
      }
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<FactorProvider>().refresh();
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  List<Factor> _filteredFactors(FactorProvider provider) {
    var factors = _selectedCategory == null
        ? provider.factors
        : provider.factors.where((f) => f.category == _selectedCategory).toList();

    if (_searchQuery.isNotEmpty) {
      final q = _searchQuery.toLowerCase();
      factors = factors.where((f) {
        return f.name.toLowerCase().contains(q) ||
            f.category.toLowerCase().contains(q) ||
            f.description.toLowerCase().contains(q);
      }).toList();
    }

    return factors;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('FACTORS'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<FactorProvider>().refresh(),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(90),
          child: Column(
            children: [
              // Search bar
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Container(
                  height: 40,
                  decoration: BoxDecoration(
                    color: TsarTheme.surfaceVariant,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: TsarTheme.cardBorder),
                  ),
                  child: TextField(
                    controller: _searchController,
                    onChanged: (v) => setState(() => _searchQuery = v),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 13,
                      color: Colors.white,
                    ),
                    decoration: InputDecoration(
                      hintText: 'Search factors...',
                      hintStyle: const TextStyle(color: Colors.white24, fontSize: 13),
                      prefixIcon: const Icon(Icons.search, color: Colors.white24, size: 18),
                      suffixIcon: _searchQuery.isNotEmpty
                          ? IconButton(
                              icon: const Icon(Icons.close, color: Colors.white24, size: 16),
                              onPressed: () {
                                _searchController.clear();
                                setState(() => _searchQuery = '');
                              },
                            )
                          : null,
                      border: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    ),
                  ),
                ),
              ),
              // Category tabs
              TabBar(
                controller: _tabController,
                isScrollable: true,
                labelColor: TsarTheme.accent,
                unselectedLabelColor: Colors.white38,
                indicatorColor: TsarTheme.accent,
                indicatorSize: TabBarIndicatorSize.label,
                labelStyle: TsarTheme.numberStyle.copyWith(fontSize: 11, letterSpacing: 1),
                unselectedLabelStyle: TsarTheme.numberStyle.copyWith(fontSize: 11),
                tabAlignment: TabAlignment.start,
                tabs: _categoryTabs.map((t) => Tab(text: t.label)).toList(),
              ),
            ],
          ),
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
            children: _categoryTabs.map((tab) {
              return _FactorTabContent(
                categoryKey: tab.categoryKey,
                searchQuery: _searchQuery,
                provider: provider,
              );
            }).toList(),
          );
        },
      ),
    );
  }
}

class _FactorTabContent extends StatelessWidget {
  final String? categoryKey;
  final String searchQuery;
  final FactorProvider provider;

  const _FactorTabContent({
    required this.categoryKey,
    required this.searchQuery,
    required this.provider,
  });

  List<Factor> _getFilteredFactors() {
    var factors = categoryKey == null
        ? provider.factors
        : provider.factors.where((f) => f.category == categoryKey).toList();

    if (searchQuery.isNotEmpty) {
      final q = searchQuery.toLowerCase();
      factors = factors.where((f) {
        return f.name.toLowerCase().contains(q) ||
            f.category.toLowerCase().contains(q) ||
            f.description.toLowerCase().contains(q);
      }).toList();
    }

    return factors;
  }

  @override
  Widget build(BuildContext context) {
    final factors = _getFilteredFactors();
    final topFactors = List<Factor>.from(factors)
      ..sort((a, b) => b.ic.abs().compareTo(a.ic.abs()));
    final top5 = topFactors.take(5).toList();

    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: factors.isEmpty
          ? const EmptyState(
              icon: Icons.science_outlined,
              title: 'No factors found',
              subtitle: 'Try adjusting your search or filters',
            )
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Top 5 Factors
                if (top5.isNotEmpty) ...[
                  _buildTopFactors(top5),
                  const SizedBox(height: 16),
                ],
                // Factor Heatmap
                if (factors.length > 3) ...[
                  _buildFactorHeatmap(factors),
                  const SizedBox(height: 16),
                ],
                // Factor List Header
                Row(
                  children: [
                    Text(
                      '${factors.length} FACTORS',
                      style: TsarTheme.numberStyle.copyWith(
                        color: Colors.white38,
                        fontSize: 11,
                        letterSpacing: 1.2,
                      ),
                    ),
                    const Spacer(),
                    _sortIndicator(),
                  ],
                ),
                const SizedBox(height: 10),
                // Factor Cards
                ...factors.map((f) => _FactorCard(factor: f)),
                const SizedBox(height: 80),
              ],
            ),
    );
  }

  Widget _buildTopFactors(List<Factor> top5) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.star, size: 16, color: TsarTheme.warning),
            const SizedBox(width: 8),
            Text(
              'TOP FACTORS BY IC',
              style: TsarTheme.numberStyle.copyWith(
                color: Colors.white54,
                fontSize: 12,
                letterSpacing: 1.2,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        ...top5.asMap().entries.map((entry) {
          final idx = entry.key;
          final factor = entry.value;
          final rankColor = idx == 0
              ? const Color(0xFFFFD700) // Gold
              : idx == 1
                  ? const Color(0xFFC0C0C0) // Silver
                  : idx == 2
                      ? const Color(0xFFCD7F32) // Bronze
                      : Colors.white24;

          return Container(
            margin: const EdgeInsets.only(bottom: 6),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: idx < 3
                    ? rankColor.withOpacity(0.3)
                    : TsarTheme.cardBorder,
              ),
              gradient: LinearGradient(
                begin: Alignment.centerLeft,
                end: Alignment.centerRight,
                colors: [
                  idx < 3
                      ? rankColor.withOpacity(0.06)
                      : TsarTheme.card,
                  TsarTheme.surfaceVariant,
                ],
              ),
            ),
            child: Row(
              children: [
                // Rank badge
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: rankColor.withOpacity(idx < 3 ? 0.2 : 0.08),
                    border: Border.all(color: rankColor.withOpacity(0.4)),
                  ),
                  child: Center(
                    child: Text(
                      '#${idx + 1}',
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 11,
                        color: rankColor,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        factor.name,
                        style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                      ),
                      Text(
                        factor.category,
                        style: TextStyle(
                          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                          fontSize: 10,
                          color: Colors.white30,
                        ),
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
                        fontSize: 11,
                        color: factor.ir >= 0 ? TsarTheme.profit.withOpacity(0.7) : TsarTheme.loss.withOpacity(0.7),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          );
        }),
      ],
    );
  }

  Widget _buildFactorHeatmap(List<Factor> factors) {
    // Sort by category then by IC
    final sorted = List<Factor>.from(factors)
      ..sort((a, b) {
        final catComp = a.category.compareTo(b.category);
        if (catComp != 0) return catComp;
        return b.ic.abs().compareTo(a.ic.abs());
      });

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.grid_view, size: 16, color: TsarTheme.accent),
            const SizedBox(width: 8),
            Text(
              'FACTOR HEATMAP',
              style: TsarTheme.numberStyle.copyWith(
                color: Colors.white54,
                fontSize: 12,
                letterSpacing: 1.2,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: TsarTheme.cardBorder),
            color: TsarTheme.surfaceVariant,
          ),
          child: Wrap(
            spacing: 4,
            runSpacing: 4,
            children: sorted.map((f) {
              final intensity = (f.ic.abs() / 0.1).clamp(0.1, 1.0);
              final color = f.ic >= 0 ? TsarTheme.profit : TsarTheme.loss;

              return Tooltip(
                message: '${f.name}\nIC: ${f.icFormatted}\nIR: ${f.irFormatted}',
                child: Container(
                  width: _heatmapCellWidth(f, sorted.length),
                  height: 36,
                  decoration: BoxDecoration(
                    color: color.withOpacity(intensity * 0.6),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: color.withOpacity(intensity * 0.3)),
                  ),
                  child: Center(
                    child: Text(
                      f.name.length > 8 ? '${f.name.substring(0, 7)}…' : f.name,
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 8,
                        color: Colors.white.withOpacity(intensity > 0.3 ? 0.9 : 0.5),
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
        ),
        const SizedBox(height: 8),
        // Legend
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _heatmapLegendItem('Bearish IC', TsarTheme.loss),
            const SizedBox(width: 16),
            _heatmapLegendItem('Neutral', Colors.white24),
            const SizedBox(width: 16),
            _heatmapLegendItem('Bullish IC', TsarTheme.profit),
          ],
        ),
      ],
    );
  }

  double _heatmapCellWidth(Factor f, int total) {
    // Vary cell width based on importance (IC magnitude)
    final importance = (f.ic.abs() / 0.1).clamp(0.3, 1.0);
    final base = total > 20 ? 40.0 : 55.0;
    return base + (importance * 20);
  }

  Widget _heatmapLegendItem(String label, Color color) {
    return Row(
      children: [
        Container(
          width: 12,
          height: 12,
          decoration: BoxDecoration(
            color: color.withOpacity(0.5),
            borderRadius: BorderRadius.circular(3),
          ),
        ),
        const SizedBox(width: 4),
        Text(
          label,
          style: const TextStyle(fontSize: 10, color: Colors.white38),
        ),
      ],
    );
  }

  Widget _sortIndicator() {
    return Text(
      'Sorted by IC ↓',
      style: TsarTheme.numberStyle.copyWith(
        fontSize: 10,
        color: Colors.white24,
      ),
    );
  }
}

class _FactorCard extends StatelessWidget {
  final Factor factor;
  const _FactorCard({required this.factor});

  @override
  Widget build(BuildContext context) {
    final icColor = factor.ic >= 0 ? TsarTheme.profit : TsarTheme.loss;
    final irColor = factor.ir >= 0 ? TsarTheme.profit : TsarTheme.loss;
    final categoryColor = _categoryColor(factor.category);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TsarTheme.cardBorder),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            TsarTheme.card,
            TsarTheme.surfaceVariant,
          ],
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
              // Header: name + category badge
              Row(
                children: [
                  Expanded(
                    child: Text(
                      factor.name,
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: categoryColor.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: categoryColor.withOpacity(0.2)),
                    ),
                    child: Text(
                      factor.category.toUpperCase(),
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 9,
                        color: categoryColor,
                        letterSpacing: 0.5,
                      ),
                    ),
                  ),
                ],
              ),
              if (factor.description.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  factor.description,
                  style: const TextStyle(color: Colors.white38, fontSize: 12),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
              const SizedBox(height: 10),
              // Metrics row
              Row(
                children: [
                  _metricChip('IC', factor.icFormatted, icColor),
                  const SizedBox(width: 8),
                  _metricChip('IR', factor.irFormatted, irColor),
                  const SizedBox(width: 8),
                  _metricChip(
                    'TURN',
                    factor.turnover.toStringAsFixed(2),
                    Colors.white54,
                  ),
                  const Spacer(),
                  // IC strength bar
                  _icStrengthBar(factor.ic),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _metricChip(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$label ',
            style: TextStyle(
              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
              fontSize: 9,
              color: color.withOpacity(0.6),
            ),
          ),
          Text(
            value,
            style: TsarTheme.numberStyle.copyWith(
              fontSize: 11,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _icStrengthBar(double ic) {
    final strength = (ic.abs() / 0.1).clamp(0.0, 1.0);
    final color = ic >= 0 ? TsarTheme.profit : TsarTheme.loss;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(
          'IC Strength',
          style: TextStyle(
            fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
            fontSize: 8,
            color: Colors.white24,
          ),
        ),
        const SizedBox(height: 2),
        SizedBox(
          width: 50,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: strength,
              backgroundColor: Colors.white.withOpacity(0.06),
              valueColor: AlwaysStoppedAnimation(color.withOpacity(0.7)),
              minHeight: 4,
            ),
          ),
        ),
      ],
    );
  }

  Color _categoryColor(String category) {
    switch (category.toLowerCase()) {
      case 'momentum':
        return TsarTheme.profit;
      case 'mean_reversion':
        return TsarTheme.info;
      case 'volatility':
        return TsarTheme.warning;
      case 'volume':
        return TsarTheme.accent;
      case 'trend':
        return TsarTheme.statusOrange;
      case 'pattern':
        return const Color(0xFFE040FB);
      default:
        return Colors.white54;
    }
  }

  void _showDetail(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => _FactorDetailSheet(factor: factor),
    );
  }
}

class _FactorDetailSheet extends StatelessWidget {
  final Factor factor;
  const _FactorDetailSheet({required this.factor});

  @override
  Widget build(BuildContext context) {
    final icColor = factor.ic >= 0 ? TsarTheme.profit : TsarTheme.loss;
    final irColor = factor.ir >= 0 ? TsarTheme.profit : TsarTheme.loss;
    final categoryColor = _categoryColorFor(factor.category);

    return DraggableScrollableSheet(
      initialChildSize: 0.7,
      maxChildSize: 0.9,
      minChildSize: 0.3,
      expand: false,
      builder: (ctx, sc) => ListView(
        controller: sc,
        padding: const EdgeInsets.all(24),
        children: [
          // Drag handle
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

          // Name + category
          Text(factor.name, style: TsarTheme.numberLarge),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: categoryColor.withOpacity(0.12),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: categoryColor.withOpacity(0.2)),
            ),
            child: Text(
              factor.category.toUpperCase(),
              style: TextStyle(
                fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                fontSize: 12,
                color: categoryColor,
                letterSpacing: 1,
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Description
          if (factor.description.isNotEmpty) ...[
            Text(
              factor.description,
              style: const TextStyle(color: Colors.white70, fontSize: 15, height: 1.5),
            ),
            const Divider(height: 32),
          ],

          // Key metrics grid
          Row(
            children: [
              Expanded(child: _detailMetricCard('IC', factor.icFormatted, icColor, 'Information Coefficient')),
              const SizedBox(width: 10),
              Expanded(child: _detailMetricCard('IR', factor.irFormatted, irColor, 'Information Ratio')),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(child: _detailMetricCard('Turnover', factor.turnover.toStringAsFixed(4), Colors.white70, 'Daily turnover')),
              const SizedBox(width: 10),
              Expanded(child: _detailMetricCard('Correlation', factor.correlation.toStringAsFixed(4), Colors.white70, 'Cross-factor corr')),
            ],
          ),

          const Divider(height: 32),

          // Computation
          Text(
            'COMPUTATION',
            style: TextStyle(
              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
              fontSize: 11,
              color: Colors.white38,
              letterSpacing: 1.2,
            ),
          ),
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.black26,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.white.withOpacity(0.06)),
            ),
            child: Text(
              factor.computation,
              style: TextStyle(
                fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                fontSize: 12,
                color: Colors.white60,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _detailMetricCard(String label, String value, Color color, String description) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: TsarTheme.cardBorder),
        color: TsarTheme.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(
              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
              fontSize: 10,
              color: Colors.white38,
              letterSpacing: 1,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: TsarTheme.numberStyle.copyWith(
              fontSize: 18,
              color: color,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            description,
            style: const TextStyle(fontSize: 10, color: Colors.white24),
          ),
        ],
      ),
    );
  }

  Color _categoryColorFor(String category) {
    switch (category.toLowerCase()) {
      case 'momentum':
        return TsarTheme.profit;
      case 'mean_reversion':
        return TsarTheme.info;
      case 'volatility':
        return TsarTheme.warning;
      case 'volume':
        return TsarTheme.accent;
      case 'trend':
        return TsarTheme.statusOrange;
      case 'pattern':
        return const Color(0xFFE040FB);
      default:
        return Colors.white54;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Private helper types
// ─────────────────────────────────────────────────────────────────────────────

class _CategoryTabDef {
  final String label;
  final IconData icon;
  final String? categoryKey;

  const _CategoryTabDef(this.label, this.icon, this.categoryKey);
}
