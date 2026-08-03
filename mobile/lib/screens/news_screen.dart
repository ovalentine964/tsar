import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../providers/news_provider.dart';
import '../models/news.dart';

class NewsScreen extends StatefulWidget {
  const NewsScreen({super.key});

  @override
  State<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends State<NewsScreen> {
  String _selectedSource = 'All';

  final List<String> _sources = ['All', 'Whale Alert', 'SEC/CFTC', 'Twitter', 'Reddit', 'CryptoPanic'];

  @override
  void initState() {
    super.initState();
    context.read<NewsProvider>().refresh();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<NewsProvider>(
      builder: (context, news, _) {
        final items = news.items;
        return Scaffold(
          appBar: AppBar(
            title: const Text('NEWS INTEL'),
            actions: [
              IconButton(icon: const Icon(Icons.refresh), onPressed: news.refresh),
            ],
          ),
          body: Column(
            children: [
              _buildSentimentBar(news),
              _buildSourceChips(),
              Expanded(
                child: news.loading && items.isEmpty
                    ? const Center(child: CircularProgressIndicator(color: TsarTheme.accent))
                    : news.error != null && items.isEmpty
                        ? _buildError(news)
                        : items.isEmpty
                            ? _buildEmpty()
                            : RefreshIndicator(
                                onRefresh: news.refresh,
                                color: TsarTheme.accent,
                                child: ListView.builder(
                                  padding: const EdgeInsets.all(12),
                                  itemCount: items.length,
                                  itemBuilder: (ctx, i) => _buildNewsCard(items[i]),
                                ),
                              ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSentimentBar(NewsProvider news) {
    final items = news.allItems;
    if (items.isEmpty) return const SizedBox.shrink();
    final bullish = items.where((n) => n.sentiment == SentimentType.bullish).length;
    final bearish = items.where((n) => n.sentiment == SentimentType.bearish).length;
    final total = items.length;
    final bullishPct = total > 0 ? bullish / total : 0.5;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      color: TsarTheme.surfaceVariant,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('SENTIMENT', style: TextStyle(color: Colors.white54, fontSize: 11)),
          const SizedBox(height: 6),
          Row(
            children: [
              Text('${(bullishPct * 100).toStringAsFixed(0)}%', style: TsarTheme.pnlStyle(1).copyWith(fontSize: 13)),
              const SizedBox(width: 8),
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: bullishPct,
                    backgroundColor: TsarTheme.loss.withOpacity(0.3),
                    valueColor: const AlwaysStoppedAnimation(TsarTheme.profit),
                    minHeight: 8,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text('${((1 - bullishPct) * 100).toStringAsFixed(0)}%', style: TsarTheme.pnlStyle(-1).copyWith(fontSize: 13)),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('$bullish bullish', style: const TextStyle(color: TsarTheme.profit, fontSize: 10)),
              Text('$bearish bearish', style: const TextStyle(color: TsarTheme.loss, fontSize: 10)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSourceChips() {
    return Container(
      height: 48,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: ListView(
        scrollDirection: Axis.horizontal,
        children: _sources.map((source) {
          final selected = _selectedSource == source;
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: FilterChip(
              label: Text(source, style: TextStyle(
                color: selected ? Colors.white : Colors.white54,
                fontSize: 12,
              )),
              selected: selected,
              onSelected: (_) => setState(() => _selectedSource = source),
              selectedColor: TsarTheme.accent.withOpacity(0.3),
              backgroundColor: TsarTheme.card,
              side: BorderSide(color: selected ? TsarTheme.accent : TsarTheme.cardBorder),
              showCheckmark: false,
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildNewsCard(NewsItem item) {
    Color sentimentColor;
    String sentimentLabel;
    IconData sentimentIcon;
    switch (item.sentiment) {
      case SentimentType.bullish:
        sentimentColor = TsarTheme.profit;
        sentimentLabel = 'BULLISH';
        sentimentIcon = Icons.trending_up;
        break;
      case SentimentType.bearish:
        sentimentColor = TsarTheme.loss;
        sentimentLabel = 'BEARISH';
        sentimentIcon = Icons.trending_down;
        break;
      default:
        sentimentColor = Colors.white38;
        sentimentLabel = 'NEUTRAL';
        sentimentIcon = Icons.trending_flat;
    }

    final timeAgo = _formatTimeAgo(item.publishedAt);

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TsarTheme.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TsarTheme.cardBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _buildSourceIcon(item.source),
              const SizedBox(width: 8),
              Expanded(
                child: Text(item.source, style: const TextStyle(color: Colors.white54, fontSize: 11)),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: sentimentColor.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(sentimentIcon, color: sentimentColor, size: 12),
                    const SizedBox(width: 4),
                    Text(sentimentLabel, style: TextStyle(color: sentimentColor, fontSize: 10, fontWeight: FontWeight.w600)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(item.title, style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
          if (item.summary.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(item.summary, style: const TextStyle(color: Colors.white54, fontSize: 12), maxLines: 2, overflow: TextOverflow.ellipsis),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Icon(Icons.access_time, color: Colors.white24, size: 14),
              const SizedBox(width: 4),
              Text(timeAgo, style: const TextStyle(color: Colors.white38, fontSize: 11)),
              const Spacer(),
              if (item.isAlert)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: TsarTheme.warning.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: const Text('ALERT', style: TextStyle(color: TsarTheme.warning, fontSize: 9, fontWeight: FontWeight.w700)),
                ),
              if (item.symbols.isNotEmpty) ...[
                const SizedBox(width: 6),
                ...item.symbols.take(3).map((s) => Container(
                  margin: const EdgeInsets.only(left: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: TsarTheme.accent.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(s, style: const TextStyle(color: TsarTheme.accent, fontSize: 9, fontWeight: FontWeight.w600)),
                )),
              ],
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSourceIcon(String source) {
    IconData icon;
    Color color;
    switch (source.toLowerCase()) {
      case 'whale alert':
        icon = Icons.water_drop;
        color = Colors.blue;
        break;
      case 'sec':
      case 'cftc':
        icon = Icons.gavel;
        color = Colors.amber;
        break;
      case 'twitter':
      case 'x':
        icon = Icons.alternate_email;
        color = Colors.lightBlue;
        break;
      case 'reddit':
        icon = Icons.forum;
        color = Colors.orange;
        break;
      default:
        icon = Icons.article;
        color = TsarTheme.accent;
    }
    return Container(
      padding: const EdgeInsets.all(6),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Icon(icon, color: color, size: 16),
    );
  }

  Widget _buildError(NewsProvider news) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.cloud_off, size: 48, color: TsarTheme.loss),
          const SizedBox(height: 12),
          Text(news.error!, style: const TextStyle(color: Colors.white54), textAlign: TextAlign.center),
          const SizedBox(height: 16),
          ElevatedButton(onPressed: news.refresh, child: const Text('RETRY')),
        ],
      ),
    );
  }

  Widget _buildEmpty() {
    return const Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.article_outlined, size: 48, color: Colors.white24),
          SizedBox(height: 12),
          Text('No news alerts', style: TextStyle(color: Colors.white38, fontSize: 16)),
          SizedBox(height: 4),
          Text('Pull to refresh', style: TextStyle(color: Colors.white24, fontSize: 12)),
        ],
      ),
    );
  }

  String _formatTimeAgo(DateTime dt) {
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }
}
