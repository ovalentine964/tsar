import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme.dart';
import '../models/knowledge.dart';
import '../providers/knowledge_provider.dart';
import '../widgets/cards.dart';

/// Full-screen Knowledge Search — maps to /api/v1/knowledge/search.
///
/// Provides FTS5 search across all knowledge stores with
/// debounced input, store filtering, and rich result display.
class KnowledgeScreen extends StatefulWidget {
  const KnowledgeScreen({super.key});

  @override
  State<KnowledgeScreen> createState() => _KnowledgeScreenState();
}

class _KnowledgeScreenState extends State<KnowledgeScreen> {
  final _controller = TextEditingController();
  Timer? _debounce;
  String? _selectedStore;

  static const _stores = [
    null, // All
    'patterns',
    'lessons',
    'trades',
    'strategies',
  ];

  @override
  void dispose() {
    _controller.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  void _onSearchChanged(String query) {
    _debounce?.cancel();
    if (query.trim().isEmpty) {
      context.read<KnowledgeProvider>().clear();
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 400), () {
      context.read<KnowledgeProvider>().search(query.trim());
    });
  }

  void _doSearch() {
    final q = _controller.text.trim();
    if (q.isNotEmpty) {
      context.read<KnowledgeProvider>().search(q);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Knowledge Search'),
        actions: [
          PopupMenuButton<String?>(
            icon: Icon(
              Icons.filter_list,
              color: _selectedStore != null ? TsarTheme.accent : Colors.white54,
            ),
            onSelected: (v) {
              setState(() => _selectedStore = v);
              if (_controller.text.trim().isNotEmpty) {
                context.read<KnowledgeProvider>().search(_controller.text.trim());
              }
            },
            itemBuilder: (_) => [
              const PopupMenuItem(value: null, child: Text('All Stores')),
              const PopupMenuItem(value: 'patterns', child: Text('Patterns')),
              const PopupMenuItem(value: 'lessons', child: Text('Lessons')),
              const PopupMenuItem(value: 'trades', child: Text('Trades')),
              const PopupMenuItem(value: 'strategies', child: Text('Strategies')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          // Search bar
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: TextField(
              controller: _controller,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Search patterns, lessons, trades...',
                hintStyle: const TextStyle(color: Colors.white24),
                filled: true,
                fillColor: TsarTheme.surfaceVariant,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
                prefixIcon: const Icon(Icons.search, color: Colors.white38),
                suffixIcon: _controller.text.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear, color: Colors.white38, size: 18),
                        onPressed: () {
                          _controller.clear();
                          context.read<KnowledgeProvider>().clear();
                        },
                      )
                    : null,
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              ),
              onChanged: _onSearchChanged,
              onSubmitted: (_) => _doSearch(),
              autofocus: true,
              textInputAction: TextInputAction.search,
            ),
          ),

          // Store filter chips
          if (_selectedStore != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  const Text('Filter: ', style: TextStyle(color: Colors.white38, fontSize: 12)),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: TsarTheme.accent.withOpacity(0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          _selectedStore!.toUpperCase(),
                          style: TextStyle(
                            fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                            fontSize: 11,
                            color: TsarTheme.accent,
                          ),
                        ),
                        const SizedBox(width: 4),
                        GestureDetector(
                          onTap: () => setState(() => _selectedStore = null),
                          child: const Icon(Icons.close, size: 14, color: TsarTheme.accent),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),

          // Results
          Expanded(
            child: Consumer<KnowledgeProvider>(
              builder: (context, provider, _) {
                if (provider.loading) {
                  return const Center(
                    child: CircularProgressIndicator(color: TsarTheme.accent),
                  );
                }

                if (provider.error != null) {
                  return ErrorBanner(message: provider.error!, onRetry: _doSearch);
                }

                if (provider.results.isEmpty && provider.query.isNotEmpty) {
                  return Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.search_off, size: 48, color: Colors.white12),
                        const SizedBox(height: 16),
                        Text(
                          'No results for "${provider.query}"',
                          style: const TextStyle(color: Colors.white38, fontSize: 15),
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Try different keywords or remove store filter',
                          style: TextStyle(color: Colors.white24, fontSize: 13),
                        ),
                      ],
                    ),
                  );
                }

                if (provider.results.isEmpty) {
                  return Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.auto_stories, size: 48, color: Colors.white12),
                        const SizedBox(height: 16),
                        const Text(
                          'Search the Knowledge Base',
                          style: TextStyle(color: Colors.white38, fontSize: 15),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Find patterns, lessons, and insights\nacross ${_stores.length - 1} stores',
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Colors.white24, fontSize: 13),
                        ),
                      ],
                    ),
                  );
                }

                return ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 80),
                  itemCount: provider.results.length,
                  itemBuilder: (context, index) =>
                      _KnowledgeResultTile(result: provider.results[index]),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _KnowledgeResultTile extends StatelessWidget {
  final KnowledgeResult result;
  const _KnowledgeResultTile({required this.result});

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
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: _storeColor.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      result.store.toUpperCase(),
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: _storeColor,
                      ),
                    ),
                  ),
                  const Spacer(),
                  Text(
                    'Score: ${result.relevance.toStringAsFixed(2)}',
                    style: TsarTheme.numberStyle.copyWith(
                      fontSize: 11,
                      color: Colors.white38,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              if (result.title.isNotEmpty)
                Text(
                  result.title,
                  style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                ),
              const SizedBox(height: 4),
              Text(
                result.content,
                style: const TextStyle(color: Colors.white54, fontSize: 13),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color get _storeColor {
    switch (result.store.toLowerCase()) {
      case 'patterns': return TsarTheme.accent;
      case 'lessons': return TsarTheme.warning;
      case 'trades': return TsarTheme.info;
      case 'strategies': return TsarTheme.profit;
      default: return Colors.white54;
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
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _storeColor.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    result.store.toUpperCase(),
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 11,
                      color: _storeColor,
                    ),
                  ),
                ),
                const Spacer(),
                Text(
                  'Relevance: ${result.relevance.toStringAsFixed(2)}',
                  style: TsarTheme.numberStyle.copyWith(
                    fontSize: 12,
                    color: Colors.white38,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            if (result.title.isNotEmpty) ...[
              Text(result.title, style: TsarTheme.numberLarge),
              const SizedBox(height: 16),
            ],
            Text(
              result.content,
              style: const TextStyle(color: Colors.white70, fontSize: 15, height: 1.6),
            ),
            if (result.createdAt != null) ...[
              const Divider(height: 32),
              Text(
                'Created: ${result.createdAt}',
                style: const TextStyle(color: Colors.white24, fontSize: 12),
              ),
            ],
            if (result.metadata != null && result.metadata!.isNotEmpty) ...[
              const Divider(height: 32),
              Text('METADATA', style: TsarTheme.numberStyle.copyWith(
                fontSize: 11,
                color: Colors.white38,
                letterSpacing: 1.2,
              )),
              const SizedBox(height: 8),
              ...result.metadata!.entries.map((e) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    Text('${e.key}: ', style: const TextStyle(color: Colors.white38, fontSize: 12)),
                    Expanded(child: Text('${e.value}', style: TsarTheme.numberStyle.copyWith(fontSize: 12))),
                  ],
                ),
              )),
            ],
          ],
        ),
      ),
    );
  }
}
