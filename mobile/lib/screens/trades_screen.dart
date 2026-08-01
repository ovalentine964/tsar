import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../theme.dart';
import '../models/trade.dart';
import '../models/signal_quality.dart';
import '../models/news.dart';
import '../providers/trade_provider.dart';
import '../providers/signal_quality_provider.dart';
import '../providers/news_provider.dart';
import '../widgets/cards.dart';

class TradesScreen extends StatefulWidget {
  const TradesScreen({super.key});

  @override
  State<TradesScreen> createState() => _TradesScreenState();
}

class _TradesScreenState extends State<TradesScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TradeProvider>().refresh();
      context.read<SignalQualityProvider>().refresh();
      context.read<NewsProvider>().refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trades'),
        actions: [
          IconButton(
            icon: const Icon(Icons.filter_list),
            onPressed: _showFilterSheet,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<TradeProvider>().refresh(),
          ),
        ],
      ),
      body: Consumer<TradeProvider>(
        builder: (context, provider, _) {
          if (provider.loading && provider.trades.isEmpty) {
            return const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            );
          }

          if (provider.error != null && provider.trades.isEmpty) {
            return ErrorBanner(
              message: provider.error!,
              onRetry: () => provider.refresh(),
            );
          }

          return Column(
            children: [
              _buildStatsBar(provider),
              Expanded(
                child: RefreshIndicator(
                  onRefresh: provider.refresh,
                  color: TsarTheme.accent,
                  child: provider.trades.isEmpty
                      ? const EmptyState(
                          icon: Icons.candlestick_chart_outlined,
                          title: 'No trades found',
                          subtitle: 'Trades will appear here once executed',
                        )
                      : ListView.builder(
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          itemCount: provider.trades.length + (provider.hasMore ? 1 : 0),
                          itemBuilder: (context, index) {
                            if (index == provider.trades.length) {
                              provider.loadMore();
                              return const Padding(
                                padding: EdgeInsets.all(16),
                                child: Center(
                                  child: CircularProgressIndicator(
                                    color: TsarTheme.accent,
                                    strokeWidth: 2,
                                  ),
                                ),
                              );
                            }
                            return _TradeTile(
                              trade: provider.trades[index],
                              onTap: () => _showTradeDetail(provider.trades[index]),
                            );
                          },
                        ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildStatsBar(TradeProvider provider) {
    final stats = provider.stats;
    if (stats == null) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: TsarTheme.surfaceVariant,
        border: Border(
          bottom: BorderSide(color: TsarTheme.cardBorder.withOpacity(0.5)),
        ),
      ),
      child: Row(
        children: [
          _statChip('${stats.totalTrades} trades', Icons.swap_horiz),
          const SizedBox(width: 12),
          _statChip('${stats.winRate.toStringAsFixed(1)}% win', Icons.percent,
              TsarTheme.profit),
          const SizedBox(width: 12),
          _statChip(
            '${stats.totalPnl >= 0 ? '+' : ''}\$${stats.totalPnl.toStringAsFixed(0)}',
            Icons.account_balance_wallet,
            stats.totalPnl >= 0 ? TsarTheme.profit : TsarTheme.loss,
          ),
        ],
      ),
    );
  }

  Widget _statChip(String label, IconData icon, [Color? color]) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: color ?? Colors.white38),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(
          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
          fontSize: 12,
          color: color ?? Colors.white54,
        )),
      ],
    );
  }

  void _showFilterSheet() {
    final provider = context.read<TradeProvider>();
    showModalBottomSheet(
      context: context,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('FILTERS',
              style: TextStyle(
                fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                fontWeight: FontWeight.w700,
                letterSpacing: 1.2,
                color: Colors.white54,
              ),
            ),
            const SizedBox(height: 16),
            const Text('Status', style: TextStyle(color: Colors.white70)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [null, 'open', 'closed', 'cancelled'].map((s) {
                final isSelected = provider.filterStatus == s;
                return ChoiceChip(
                  label: Text(s ?? 'All'),
                  selected: isSelected,
                  selectedColor: TsarTheme.accent.withOpacity(0.3),
                  onSelected: (_) {
                    provider.setFilter(status: s);
                    Navigator.pop(ctx);
                  },
                );
              }).toList(),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  void _showTradeDetail(Trade trade) {
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
        builder: (ctx, scrollController) => _TradeDetailSheet(
          trade: trade,
          scrollController: scrollController,
        ),
      ),
    );
  }
}

class _TradeTile extends StatelessWidget {
  final Trade trade;
  final VoidCallback? onTap;

  const _TradeTile({required this.trade, this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 4,
                height: 40,
                decoration: BoxDecoration(
                  color: trade.sideColor,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          trade.symbol,
                          style: TsarTheme.numberStyle.copyWith(fontSize: 15),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: trade.sideColor.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            trade.sideLabel,
                            style: TextStyle(
                              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: trade.sideColor,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: Colors.white.withOpacity(0.06),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            trade.status.name.toUpperCase(),
                            style: TextStyle(
                              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                              fontSize: 10,
                              color: Colors.white38,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      DateFormat('MMM dd, HH:mm').format(trade.openedAt),
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
                    '\$${trade.entryPrice.toStringAsFixed(2)}',
                    style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                  ),
                  if (trade.pnl != null) ...[
                    const SizedBox(height: 4),
                    PnlBadge(value: trade.pnlPercent ?? 0),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TradeDetailSheet extends StatelessWidget {
  final Trade trade;
  final ScrollController scrollController;

  const _TradeDetailSheet({
    required this.trade,
    required this.scrollController,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      controller: scrollController,
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
            Text(
              trade.symbol,
              style: TsarTheme.numberLarge,
            ),
            const SizedBox(width: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: trade.sideColor.withOpacity(0.15),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                trade.sideLabel,
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontWeight: FontWeight.w700,
                  color: trade.sideColor,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        _detailRow('Status', trade.status.name.toUpperCase()),
        _detailRow('Entry Price', '\$${trade.entryPrice.toStringAsFixed(4)}'),
        if (trade.exitPrice != null)
          _detailRow('Exit Price', '\$${trade.exitPrice!.toStringAsFixed(4)}'),
        _detailRow('Quantity', trade.quantity.toStringAsFixed(4)),
        if (trade.pnl != null) ...[
          const Divider(height: 32),
          _detailRow(
            'P&L',
            '${trade.pnl! >= 0 ? '+' : ''}\$${trade.pnl!.toStringAsFixed(2)}',
            valueColor: trade.pnlColor,
          ),
          if (trade.pnlPercent != null)
            _detailRow(
              'Return',
              '${trade.pnlPercent! >= 0 ? '+' : ''}${trade.pnlPercent!.toStringAsFixed(2)}%',
              valueColor: trade.pnlColor,
            ),
        ],
        if (trade.strategy != null)
          _detailRow('Strategy', trade.strategy!),
        _detailRow('Opened', DateFormat('yyyy-MM-dd HH:mm').format(trade.openedAt)),
        if (trade.closedAt != null)
          _detailRow('Closed', DateFormat('yyyy-MM-dd HH:mm').format(trade.closedAt!)),
        if (trade.notes != null) ...[
          const Divider(height: 32),
          Text('Notes', style: TextStyle(color: Colors.white38, fontSize: 12)),
          const SizedBox(height: 8),
          Text(trade.notes!, style: TextStyle(color: Colors.white70)),
        ],

        // Signal quality context
        const Divider(height: 32),
        Text('SIGNAL CONTEXT',
            style: TextStyle(
              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
              fontSize: 11,
              color: Colors.white38,
              letterSpacing: 1.2,
            )),
        const SizedBox(height: 8),
        Consumer<SignalQualityProvider>(
          builder: (context, signalProvider, _) {
            final signal = signalProvider.signals
                .where((s) => s.symbol == trade.symbol)
                .toList();
            if (signal.isEmpty) {
              return Text(
                'No signal data for ${trade.symbol}',
                style: const TextStyle(color: Colors.white24, fontSize: 12),
              );
            }
            final s = signal.first;
            return Row(
              children: [
                Text(s.statusEmoji, style: const TextStyle(fontSize: 16)),
                const SizedBox(width: 8),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Grade: ${s.grade} (${(s.overallScore * 100).toStringAsFixed(0)}%)',
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 13,
                        color: s.gradeColor,
                      ),
                    ),
                    Text(
                      'Confidence: ${(s.confidence * 100).toStringAsFixed(0)}%',
                      style: const TextStyle(color: Colors.white54, fontSize: 11),
                    ),
                  ],
                ),
              ],
            );
          },
        ),

        // News context
        const SizedBox(height: 16),
        Text('NEWS CONTEXT',
            style: TextStyle(
              fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
              fontSize: 11,
              color: Colors.white38,
              letterSpacing: 1.2,
            )),
        const SizedBox(height: 8),
        Consumer<NewsProvider>(
          builder: (context, newsProvider, _) {
            final relatedNews = newsProvider.allItems
                .where((n) => n.symbols.contains(trade.symbol))
                .toList();
            if (relatedNews.isEmpty) {
              return Text(
                'No recent news for ${trade.symbol}',
                style: const TextStyle(color: Colors.white24, fontSize: 12),
              );
            }
            return Column(
              children: relatedNews.take(3).map((news) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Icon(news.sentimentIcon, size: 14, color: news.sentimentColor),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          news.title,
                          style: const TextStyle(color: Colors.white70, fontSize: 12),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                );
              }).toList(),
            );
          },
        ),
      ],
    );
  }

  Widget _detailRow(String label, String value, {Color? valueColor}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Colors.white38, fontSize: 13)),
          Text(
            value,
            style: TsarTheme.numberStyle.copyWith(
              fontSize: 14,
              color: valueColor ?? Colors.white,
            ),
          ),
        ],
      ),
    );
  }
}
