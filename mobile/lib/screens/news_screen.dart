import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import '../theme.dart';
import '../models/news.dart';
import '../providers/news_provider.dart';
import '../widgets/cards.dart';

class NewsScreen extends StatefulWidget {
  const NewsScreen({super.key});

  @override
  State<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends State<NewsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<NewsProvider>().refresh();
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
        title: const Text('News & Sentiment'),
        actions: [
          PopupMenuButton<SentimentType?>(
            icon: Icon(
              Icons.filter_list,
              color: context.watch<NewsProvider>().filterSentiment != null
                  ? TsarTheme.accent
                  : Colors.white54,
            ),
            onSelected: (v) => context.read<NewsProvider>().setFilter(sentiment: v),
            itemBuilder: (_) => [
              const PopupMenuItem(value: null, child: Text('All Sentiment')),
              const PopupMenuItem(value: SentimentType.bullish, child: Text('🟢 Bullish')),
              const PopupMenuItem(value: SentimentType.bearish, child: Text('🔴 Bearish')),
              const PopupMenuItem(value: SentimentType.neutral, child: Text('⚪ Neutral')),
            ],
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<NewsProvider>().refresh(),
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          labelColor: TsarTheme.accent,
          unselectedLabelColor: Colors.white38,
          indicatorColor: TsarTheme.accent,
          tabs: const [
            Tab(text: 'Feed'),
            Tab(text: 'Alerts'),
            Tab(text: 'Sentiment'),
          ],
        ),
      ),
      body: Consumer<NewsProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.allItems.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.allItems.isEmpty) {
            return ErrorBanner(
              message: provider.error!,
              onRetry: () => provider.refresh(),
            );
          }

          return TabBarView(
            controller: _tabController,
            children: [
              _buildFeed(provider),
              _buildAlerts(provider),
              _buildSentimentOverview(provider),
            ],
          );
        },
      ),
    );
  }

  Widget _buildFeed(NewsProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: provider.items.isEmpty
          ? const EmptyState(
              icon: Icons.article_outlined,
              title: 'No news items',
              subtitle: 'News will appear here when available',
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: provider.items.length,
              itemBuilder: (context, index) =>
                  _NewsTile(item: provider.items[index]),
            ),
    );
  }

  Widget _buildAlerts(NewsProvider provider) {
    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: provider.alerts.isEmpty
          ? const EmptyState(
              icon: Icons.notifications_none,
              title: 'No alerts',
              subtitle: 'Important news alerts will appear here',
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: provider.alerts.length,
              itemBuilder: (context, index) =>
                  _NewsTile(item: provider.alerts[index], isAlert: true),
            ),
    );
  }

  Widget _buildSentimentOverview(NewsProvider provider) {
    final items = provider.allItems;
    if (items.isEmpty) return const SizedBox.shrink();

    final bullish = items.where((n) => n.sentiment == SentimentType.bullish).length;
    final bearish = items.where((n) => n.sentiment == SentimentType.bearish).length;
    final neutral = items.where((n) => n.sentiment == SentimentType.neutral).length;
    final total = items.length;

    return RefreshIndicator(
      onRefresh: provider.refresh,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TsarCard(
            title: 'SENTIMENT DISTRIBUTION',
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      flex: bullish,
                      child: Container(
                        height: 24,
                        decoration: BoxDecoration(
                          color: TsarTheme.profit.withOpacity(0.7),
                          borderRadius: const BorderRadius.horizontal(
                              left: Radius.circular(4)),
                        ),
                        child: Center(
                          child: Text(
                            '$bullish',
                            style: _monoStyle(11, Colors.white),
                          ),
                        ),
                      ),
                    ),
                    Expanded(
                      flex: neutral,
                      child: Container(
                        height: 24,
                        color: Colors.white24,
                        child: Center(
                          child: Text('$neutral', style: _monoStyle(11, Colors.white)),
                        ),
                      ),
                    ),
                    Expanded(
                      flex: bearish,
                      child: Container(
                        height: 24,
                        decoration: BoxDecoration(
                          color: TsarTheme.loss.withOpacity(0.7),
                          borderRadius: const BorderRadius.horizontal(
                              right: Radius.circular(4)),
                        ),
                        child: Center(
                          child: Text(
                            '$bearish',
                            style: _monoStyle(11, Colors.white),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _sentimentStat('Bullish', bullish, total, TsarTheme.profit),
                    _sentimentStat('Neutral', neutral, total, Colors.white54),
                    _sentimentStat('Bearish', bearish, total, TsarTheme.loss),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          TsarCard(
            title: 'RECENT SENTIMENT',
            child: Column(
              children: items.take(10).map((item) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Icon(item.sentimentIcon, size: 16, color: item.sentimentColor),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          item.title,
                          style: const TextStyle(color: Colors.white70, fontSize: 13),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      Text(
                        '${item.sentimentScore >= 0 ? '+' : ''}${(item.sentimentScore * 100).toStringAsFixed(0)}%',
                        style: _monoStyle(12, item.sentimentColor),
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

  Widget _sentimentStat(String label, int count, int total, Color color) {
    final pct = total > 0 ? (count / total * 100).toStringAsFixed(0) : '0';
    return Column(
      children: [
        Text('$count', style: TsarTheme.numberStyle.copyWith(color: color, fontSize: 18)),
        Text('$pct%', style: _monoStyle(12, color)),
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
      ],
    );
  }

  TextStyle _monoStyle(double fontSize, Color color) {
    return TextStyle(
      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
      fontSize: fontSize,
      fontWeight: FontWeight.w600,
      color: color,
    );
  }
}

class _NewsTile extends StatelessWidget {
  final NewsItem item;
  final bool isAlert;

  const _NewsTile({required this.item, this.isAlert = false});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: isAlert
              ? item.sentimentColor.withOpacity(0.4)
              : TsarTheme.cardBorder,
          width: isAlert ? 1.5 : 1,
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
                  Icon(item.sentimentIcon, size: 16, color: item.sentimentColor),
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: item.sentimentColor.withOpacity(0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      item.sentimentLabel,
                      style: _monoStyle(10, item.sentimentColor),
                    ),
                  ),
                  const Spacer(),
                  Text(
                    item.source,
                    style: const TextStyle(color: Colors.white24, fontSize: 11),
                  ),
                  if (isAlert) ...[
                    const SizedBox(width: 6),
                    const Icon(Icons.warning_amber, size: 14, color: TsarTheme.warning),
                  ],
                ],
              ),
              const SizedBox(height: 8),
              Text(
                item.title,
                style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              if (item.summary.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(
                  item.summary,
                  style: const TextStyle(color: Colors.white54, fontSize: 12),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
              const SizedBox(height: 8),
              Row(
                children: [
                  if (item.symbols.isNotEmpty) ...[
                    ...item.symbols.take(3).map((s) => Container(
                      margin: const EdgeInsets.only(right: 4),
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: TsarTheme.accent.withOpacity(0.12),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(s, style: _monoStyle(10, TsarTheme.accent)),
                    )),
                  ],
                  const Spacer(),
                  Text(
                    _formatTime(item.publishedAt),
                    style: const TextStyle(color: Colors.white24, fontSize: 11),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  TextStyle _monoStyle(double fontSize, Color color) {
    return TextStyle(
      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
      fontSize: fontSize,
      fontWeight: FontWeight.w600,
      color: color,
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
            Row(
              children: [
                Icon(item.sentimentIcon, size: 24, color: item.sentimentColor),
                const SizedBox(width: 12),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: item.sentimentColor.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    item.sentimentLabel,
                    style: _monoStyle(12, item.sentimentColor),
                  ),
                ),
                const Spacer(),
                Text(
                  'Score: ${(item.sentimentScore * 100).toStringAsFixed(0)}%',
                  style: TsarTheme.numberStyle.copyWith(
                    fontSize: 12,
                    color: item.sentimentColor,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(item.title, style: TsarTheme.numberLarge.copyWith(fontSize: 20)),
            const SizedBox(height: 12),
            if (item.summary.isNotEmpty)
              Text(
                item.summary,
                style: const TextStyle(color: Colors.white70, fontSize: 15, height: 1.5),
              ),
            const Divider(height: 32),
            _detailRow('Source', item.source),
            _detailRow('Published', DateFormat('yyyy-MM-dd HH:mm').format(item.publishedAt)),
            if (item.symbols.isNotEmpty)
              _detailRow('Symbols', item.symbols.join(', ')),
            if (item.tags.isNotEmpty)
              _detailRow('Tags', item.tags.join(', ')),
          ],
        ),
      ),
    );
  }

  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 13)),
          Flexible(
            child: Text(
              value,
              style: TsarTheme.numberStyle.copyWith(fontSize: 13),
              textAlign: TextAlign.right,
            ),
          ),
        ],
      ),
    );
  }
}
