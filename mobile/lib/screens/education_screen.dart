import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme.dart';
import '../models/knowledge.dart';
import '../services/api_service.dart';
import '../widgets/cards.dart';

class EducationScreen extends StatefulWidget {
  const EducationScreen({super.key});

  @override
  State<EducationScreen> createState() => _EducationScreenState();
}

class _EducationScreenState extends State<EducationScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _lessons = [];
  List<Map<String, dynamic>> _patterns = [];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _refresh();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final api = context.read<ApiService>();
      final results = await Future.wait([
        api.getLessons(),
        api.getPatterns(),
        api.getTradeEducation(),
      ], eagerError: false);

      setState(() {
        _lessons = (results[0]['lessons'] as List<dynamic>?)
                ?.map((e) => Map<String, dynamic>.from(e as Map))
                .toList() ??
            [];
        _patterns = (results[1]['patterns'] as List<dynamic>?)
                ?.map((e) => Map<String, dynamic>.from(e as Map))
                .toList() ??
            [];
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trade Education'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          labelColor: TsarTheme.accent,
          unselectedLabelColor: Colors.white38,
          indicatorColor: TsarTheme.accent,
          tabs: const [
            Tab(text: 'Lessons'),
            Tab(text: 'Patterns'),
            Tab(text: 'Insights'),
          ],
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: TsarTheme.accent))
          : _error != null
              ? ErrorBanner(message: _error!, onRetry: _refresh)
              : TabBarView(
                  controller: _tabController,
                  children: [
                    _buildLessons(),
                    _buildPatterns(),
                    _buildInsights(),
                  ],
                ),
    );
  }

  Widget _buildLessons() {
    return RefreshIndicator(
      onRefresh: _refresh,
      color: TsarTheme.accent,
      child: _lessons.isEmpty
          ? const EmptyState(
              icon: Icons.school_outlined,
              title: 'No lessons learned',
              subtitle: 'Trade lessons will appear here over time',
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _lessons.length,
              itemBuilder: (context, index) {
                final lesson = _lessons[index];
                return Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(12),
                    onTap: () => _showLessonDetail(lesson),
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.lightbulb_outline,
                                  size: 16, color: TsarTheme.warning),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  lesson['title'] ?? lesson['lesson'] ?? 'Lesson',
                                  style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 6),
                          Text(
                            lesson['content'] ?? lesson['text'] ?? '',
                            style: const TextStyle(color: Colors.white54, fontSize: 12),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                          if (lesson['trade_id'] != null) ...[
                            const SizedBox(height: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: TsarTheme.info.withOpacity(0.12),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                'Trade: ${lesson['trade_id']}',
                                style: TextStyle(
                                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                                  fontSize: 10,
                                  color: TsarTheme.info,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
    );
  }

  Widget _buildPatterns() {
    return RefreshIndicator(
      onRefresh: _refresh,
      color: TsarTheme.accent,
      child: _patterns.isEmpty
          ? const EmptyState(
              icon: Icons.pattern_outlined,
              title: 'No patterns detected',
              subtitle: 'Recognized patterns will appear here',
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _patterns.length,
              itemBuilder: (context, index) {
                final pattern = _patterns[index];
                final confidence = (pattern['confidence'] ?? pattern['score'] ?? 0).toDouble();
                return Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.auto_graph,
                                size: 16, color: TsarTheme.accent),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                pattern['name'] ?? pattern['pattern'] ?? 'Pattern',
                                style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color: (confidence >= 0.7
                                        ? TsarTheme.profit
                                        : confidence >= 0.4
                                            ? TsarTheme.warning
                                            : TsarTheme.loss)
                                    .withOpacity(0.15),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                '${(confidence * 100).toStringAsFixed(0)}%',
                                style: TsarTheme.numberStyle.copyWith(
                                  fontSize: 11,
                                  color: confidence >= 0.7
                                      ? TsarTheme.profit
                                      : confidence >= 0.4
                                          ? TsarTheme.warning
                                          : TsarTheme.loss,
                                ),
                              ),
                            ),
                          ],
                        ),
                        if (pattern['description'] != null &&
                            (pattern['description'] as String).isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Text(
                            pattern['description'],
                            style: const TextStyle(color: Colors.white54, fontSize: 12),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }

  Widget _buildInsights() {
    return RefreshIndicator(
      onRefresh: _refresh,
      color: TsarTheme.accent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TsarCard(
            title: 'LEARNING PROGRESS',
            child: Column(
              children: [
                _insightRow('Lessons Learned', '${_lessons.length}', Icons.school, TsarTheme.accent),
                const Divider(height: 16),
                _insightRow('Patterns Recognized', '${_patterns.length}', Icons.auto_graph, TsarTheme.profit),
                const Divider(height: 16),
                _insightRow(
                  'Avg Pattern Confidence',
                  _patterns.isEmpty
                      ? '—'
                      : '${(_patterns.fold(0.0, (s, p) => s + ((p['confidence'] ?? p['score'] ?? 0) as num).toDouble()) / _patterns.length * 100).toStringAsFixed(0)}%',
                  Icons.analytics,
                  TsarTheme.warning,
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          TsarCard(
            title: 'TRADE EDUCATION TIPS',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _tip('Always check signal quality before entering a trade'),
                _tip('Review scenario prevention status for open positions'),
                _tip('Monitor news sentiment for symbols in your portfolio'),
                _tip('Check DeFi yields regularly for rebalancing opportunities'),
                _tip('Review on-chain audit trail for compliance'),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _insightRow(String label, String value, IconData icon, Color color) {
    return Row(
      children: [
        Icon(icon, size: 18, color: color),
        const SizedBox(width: 12),
        Expanded(
          child: Text(label, style: const TextStyle(color: Colors.white70, fontSize: 14)),
        ),
        Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 16, color: color)),
      ],
    );
  }

  Widget _tip(String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('💡 ', style: TextStyle(fontSize: 12)),
          Expanded(
            child: Text(text, style: const TextStyle(color: Colors.white54, fontSize: 13)),
          ),
        ],
      ),
    );
  }

  void _showLessonDetail(Map<String, dynamic> lesson) {
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
                const Icon(Icons.lightbulb, color: TsarTheme.warning, size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    lesson['title'] ?? lesson['lesson'] ?? 'Lesson',
                    style: TsarTheme.numberLarge.copyWith(fontSize: 20),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            Text(
              lesson['content'] ?? lesson['text'] ?? '',
              style: const TextStyle(color: Colors.white70, fontSize: 15, height: 1.6),
            ),
          ],
        ),
      ),
    );
  }
}
