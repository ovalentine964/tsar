import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../providers/settings_provider.dart';
import '../providers/dashboard_provider.dart';
import '../providers/mandate_provider.dart';
import '../providers/knowledge_provider.dart';
import '../providers/strategy_provider.dart';
import '../widgets/cards.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _urlController = TextEditingController();
  final _apiKeyController = TextEditingController();

  @override
  void initState() {
    super.initState();
    final settings = context.read<SettingsProvider>();
    _urlController.text = settings.baseUrl;
    _apiKeyController.text = settings.apiKey ?? '';
  }

  @override
  void dispose() {
    _urlController.dispose();
    _apiKeyController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: Consumer<SettingsProvider>(
        builder: (context, settings, _) {
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // API Configuration
              TsarCard(
                title: 'API CONNECTION',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Base URL',
                        style: TextStyle(color: Colors.white54, fontSize: 12)),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _urlController,
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                      decoration: InputDecoration(
                        hintText: 'http://localhost:8000',
                        filled: true,
                        fillColor: Colors.black26,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 14),
                      ),
                      onSubmitted: (v) {
                        settings.setBaseUrl(v);
                        _refreshAll();
                      },
                    ),
                    const SizedBox(height: 16),
                    const Text('API Key (optional)',
                        style: TextStyle(color: Colors.white54, fontSize: 12)),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _apiKeyController,
                      style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                      obscureText: true,
                      decoration: InputDecoration(
                        hintText: 'Bearer token',
                        filled: true,
                        fillColor: Colors.black26,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 14),
                      ),
                      onSubmitted: (v) {
                        settings.setApiKey(v.isEmpty ? null : v);
                        _refreshAll();
                      },
                    ),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: () {
                          settings.setBaseUrl(_urlController.text);
                          settings.setApiKey(
                            _apiKeyController.text.isEmpty
                                ? null
                                : _apiKeyController.text,
                          );
                          _refreshAll();
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('Settings saved'),
                              backgroundColor: TsarTheme.profit,
                            ),
                          );
                        },
                        icon: const Icon(Icons.save),
                        label: const Text('SAVE & CONNECT'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: TsarTheme.accent,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // Theme
              TsarCard(
                title: 'APPEARANCE',
                child: SwitchListTile(
                  title: const Text('Dark Mode',
                      style: TextStyle(color: Colors.white70)),
                  subtitle: const Text('Trading terminal aesthetic',
                      style: TextStyle(color: Colors.white30, fontSize: 12)),
                  value: settings.isDarkMode,
                  activeColor: TsarTheme.accent,
                  onChanged: settings.setDarkMode,
                  contentPadding: EdgeInsets.zero,
                ),
              ),

              const SizedBox(height: 12),

              // Auto-refresh
              TsarCard(
                title: 'DATA REFRESH',
                child: Column(
                  children: [
                    SwitchListTile(
                      title: const Text('Auto Refresh',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text(
                          'Periodically fetch latest data',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      value: settings.autoRefresh,
                      activeColor: TsarTheme.accent,
                      onChanged: settings.setAutoRefresh,
                      contentPadding: EdgeInsets.zero,
                    ),
                    if (settings.autoRefresh) ...[
                      const Divider(),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Text('Interval',
                              style: TextStyle(color: Colors.white54)),
                          DropdownButton<int>(
                            value: settings.refreshIntervalSeconds,
                            dropdownColor: TsarTheme.surfaceVariant,
                            underline: const SizedBox.shrink(),
                            items: const [
                              DropdownMenuItem(value: 10, child: Text('10s')),
                              DropdownMenuItem(value: 30, child: Text('30s')),
                              DropdownMenuItem(value: 60, child: Text('1m')),
                              DropdownMenuItem(value: 300, child: Text('5m')),
                            ],
                            onChanged: (v) {
                              if (v != null) settings.setRefreshInterval(v);
                            },
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // Mandate section
              TsarCard(
                title: 'MANDATE',
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.gavel, color: TsarTheme.accent),
                      title: const Text('Manage Mandates',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('View and manage trading mandates',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right,
                          color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () => _showMandateSheet(context),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // Knowledge search
              TsarCard(
                title: 'KNOWLEDGE BASE',
                child: Column(
                  children: [
                    ListTile(
                      leading:
                          const Icon(Icons.search, color: TsarTheme.accent),
                      title: const Text('Search Knowledge',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('FTS5 search across all stores',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right,
                          color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () => _showKnowledgeSearch(context),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // DeFi Configuration
              TsarCard(
                title: 'DeFi CONFIGURATION',
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.currency_exchange, color: TsarTheme.accent),
                      title: const Text('DeFi Positions',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('View and manage DeFi yield positions',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right, color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () {
                        // Navigate to DeFi screen - accessible from bottom nav
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('DeFi is available from the bottom navigation'),
                            backgroundColor: TsarTheme.info,
                          ),
                        );
                      },
                    ),
                    const Divider(),
                    SwitchListTile(
                      title: const Text('Auto-compound yields',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('Automatically reinvest earned yields',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      value: false,
                      activeColor: TsarTheme.accent,
                      onChanged: (v) {
                        // Placeholder for DeFi auto-compound setting
                      },
                      contentPadding: EdgeInsets.zero,
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // Blockchain Configuration
              TsarCard(
                title: 'BLOCKCHAIN & RULES',
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.rule, color: TsarTheme.accent),
                      title: const Text('On-Chain Rules',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('Manage blockchain-enforced trading rules',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right, color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Blockchain rules available from bottom navigation'),
                            backgroundColor: TsarTheme.info,
                          ),
                        );
                      },
                    ),
                    const Divider(),
                    ListTile(
                      leading: const Icon(Icons.shield, color: TsarTheme.warning),
                      title: const Text('Scenario Prevention',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('Configure scenario-based risk prevention',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right, color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Scenarios available from bottom navigation'),
                            backgroundColor: TsarTheme.info,
                          ),
                        );
                      },
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // News Sources
              TsarCard(
                title: 'NEWS SOURCES',
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.article, color: TsarTheme.accent),
                      title: const Text('News Feed',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('Real-time news with sentiment analysis',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right, color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('News available from bottom navigation'),
                            backgroundColor: TsarTheme.info,
                          ),
                        );
                      },
                    ),
                    const Divider(),
                    SwitchListTile(
                      title: const Text('Push notifications for alerts',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('Get notified for high-impact news',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      value: true,
                      activeColor: TsarTheme.accent,
                      onChanged: (v) {
                        // Placeholder for news notification setting
                      },
                      contentPadding: EdgeInsets.zero,
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // Strategies
              TsarCard(
                title: 'STRATEGIES',
                child: Column(
                  children: [
                    ListTile(
                      leading:
                          const Icon(Icons.account_tree, color: TsarTheme.accent),
                      title: const Text('Strategy Library',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text('View strategy genomes and performance',
                          style: TextStyle(color: Colors.white30, fontSize: 12)),
                      trailing: const Icon(Icons.chevron_right,
                          color: Colors.white24),
                      contentPadding: EdgeInsets.zero,
                      onTap: () => _showStrategiesSheet(context),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              // About
              TsarCard(
                title: 'ABOUT',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _aboutRow('Version', '1.0.0'),
                    _aboutRow('Build', '2024.01'),
                    _aboutRow('API', settings.baseUrl),
                    const SizedBox(height: 12),
                    Text(
                      'TSAR — Trading Super Agent',
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 12,
                        color: Colors.white24,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 80),
            ],
          );
        },
      ),
    );
  }

  Widget _aboutRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.white38, fontSize: 13)),
          Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 13, color: Colors.white54)),
        ],
      ),
    );
  }

  void _refreshAll() {
    context.read<DashboardProvider>().refresh();
  }

  void _showMandateSheet(BuildContext context) {
    context.read<MandateProvider>().refresh();
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => ChangeNotifierProvider.value(
        value: context.read<MandateProvider>(),
        child: const MandateSheet(),
      ),
    );
  }

  void _showKnowledgeSearch(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => ChangeNotifierProvider.value(
        value: context.read<KnowledgeProvider>(),
        child: const KnowledgeSearchSheet(),
      ),
    );
  }

  void _showStrategiesSheet(BuildContext context) {
    context.read<StrategyProvider>().refresh();
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => ChangeNotifierProvider.value(
        value: context.read<StrategyProvider>(),
        child: const StrategiesSheet(),
      ),
    );
  }
}

// ─── Mandate Sheet ─────────────────────────────────────────────────────

class MandateSheet extends StatefulWidget {
  const MandateSheet({super.key});

  @override
  State<MandateSheet> createState() => _MandateSheetState();
}

class _MandateSheetState extends State<MandateSheet> {
  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.7,
      maxChildSize: 0.9,
      minChildSize: 0.3,
      expand: false,
      builder: (ctx, sc) => Consumer<MandateProvider>(
        builder: (context, provider, _) {
          return ListView(
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
              Text('MANDATES', style: TsarTheme.numberStyle.copyWith(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                letterSpacing: 1.5,
              )),
              const SizedBox(height: 16),

              if (provider.loading)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.all(32),
                    child: CircularProgressIndicator(color: TsarTheme.accent),
                  ),
                )
              else if (provider.error != null)
                ErrorBanner(
                  message: provider.error!,
                  onRetry: () => provider.refresh(),
                )
              else if (provider.mandate != null) ...[
                // Status card
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: provider.isActive
                        ? TsarTheme.profit.withOpacity(0.1)
                        : TsarTheme.warning.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: provider.isActive
                          ? TsarTheme.profit.withOpacity(0.3)
                          : TsarTheme.warning.withOpacity(0.3),
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        provider.isActive ? Icons.check_circle : Icons.pause_circle,
                        color: provider.isActive ? TsarTheme.profit : TsarTheme.warning,
                        size: 32,
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'STATUS: ${provider.mandate!.status.toUpperCase()}',
                              style: TsarTheme.numberStyle.copyWith(
                                fontSize: 14,
                                color: provider.isActive ? TsarTheme.profit : TsarTheme.warning,
                                letterSpacing: 1.2,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              provider.mandate!.name,
                              style: const TextStyle(color: Colors.white54, fontSize: 13),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // Rules
                if (provider.mandate!.rules.isNotEmpty) ...[
                  Text(
                    'RULES (${provider.mandate!.rules.length})',
                    style: TsarTheme.numberStyle.copyWith(
                      color: Colors.white38,
                      fontSize: 12,
                      letterSpacing: 1.2,
                    ),
                  ),
                  const SizedBox(height: 8),
                  ...provider.mandate!.rules.map((rule) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.black26,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            rule.enabled ? Icons.check_box : Icons.check_box_outline_blank,
                            size: 16,
                            color: rule.enabled ? TsarTheme.profit : Colors.white24,
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                if (rule.category.isNotEmpty)
                                  Text(
                                    rule.category.toUpperCase(),
                                    style: TsarTheme.numberStyle.copyWith(
                                      fontSize: 10,
                                      color: TsarTheme.accent,
                                      letterSpacing: 1,
                                    ),
                                  ),
                                Text(
                                  rule.rule,
                                  style: const TextStyle(color: Colors.white70, fontSize: 13),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  )),
                ],

                const SizedBox(height: 24),

                // Actions
                if (provider.isActive)
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: provider.revokeLoading
                          ? null
                          : () async {
                              final success = await provider.revokeMandate();
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: Text(success
                                        ? 'Mandate revoked'
                                        : 'Failed to revoke mandate'),
                                    backgroundColor:
                                        success ? TsarTheme.warning : TsarTheme.loss,
                                  ),
                                );
                              }
                            },
                      icon: provider.revokeLoading
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.block),
                      label: const Text('REVOKE MANDATE'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: TsarTheme.loss,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                    ),
                  )
                else
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: provider.commitLoading
                          ? null
                          : () async {
                              final success = await provider.commitMandate();
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: Text(success
                                        ? 'Mandate committed — live trading enabled'
                                        : 'Failed to commit mandate'),
                                    backgroundColor:
                                        success ? TsarTheme.profit : TsarTheme.loss,
                                  ),
                                );
                              }
                            },
                      icon: provider.commitLoading
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.gavel),
                      label: const Text('COMMIT MANDATE'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: TsarTheme.accent,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                    ),
                  ),
              ] else
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(
                    child: Text(
                      'No mandate data available',
                      style: TextStyle(color: Colors.white24),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

// ─── Knowledge Search Sheet ────────────────────────────────────────────

class KnowledgeSearchSheet extends StatefulWidget {
  const KnowledgeSearchSheet({super.key});

  @override
  State<KnowledgeSearchSheet> createState() => _KnowledgeSearchSheetState();
}

class _KnowledgeSearchSheetState extends State<KnowledgeSearchSheet> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _doSearch() {
    final q = _controller.text.trim();
    if (q.isNotEmpty) {
      context.read<KnowledgeProvider>().search(q);
    }
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.8,
      maxChildSize: 0.95,
      minChildSize: 0.3,
      expand: false,
      builder: (ctx, sc) => Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
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
                Text('KNOWLEDGE SEARCH', style: TsarTheme.numberStyle.copyWith(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.5,
                )),
                const SizedBox(height: 16),
                TextField(
                  controller: _controller,
                  style: const TextStyle(color: Colors.white),
                  decoration: InputDecoration(
                    hintText: 'Search patterns, lessons, trades...',
                    hintStyle: const TextStyle(color: Colors.white24),
                    filled: true,
                    fillColor: Colors.black26,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide.none,
                    ),
                    suffixIcon: IconButton(
                      icon: const Icon(Icons.search, color: TsarTheme.accent),
                      onPressed: _doSearch,
                    ),
                  ),
                  autofocus: true,
                  onSubmitted: (_) => _doSearch(),
                ),
              ],
            ),
          ),
          Expanded(
            child: Consumer<KnowledgeProvider>(
              builder: (context, provider, _) {
                if (provider.loading) {
                  return const Center(
                    child: CircularProgressIndicator(color: TsarTheme.accent),
                  );
                }

                if (provider.error != null) {
                  return ErrorBanner(
                    message: provider.error!,
                    onRetry: _doSearch,
                  );
                }

                if (provider.results.isEmpty && provider.query.isNotEmpty) {
                  return const Center(
                    child: Text(
                      'No results found',
                      style: TextStyle(color: Colors.white24),
                    ),
                  );
                }

                if (provider.results.isEmpty) {
                  return const Center(
                    child: Text(
                      'Enter a search query to find\nknowledge across all stores',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.white24),
                    ),
                  );
                }

                return ListView.builder(
                  controller: sc,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: provider.results.length,
                  itemBuilder: (context, index) {
                    final result = provider.results[index];
                    return Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 6, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: TsarTheme.accent.withOpacity(0.12),
                                    borderRadius: BorderRadius.circular(4),
                                  ),
                                  child: Text(
                                    result.store.toUpperCase(),
                                    style: TsarTheme.numberStyle.copyWith(
                                      fontSize: 10,
                                      color: TsarTheme.accent,
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
                              style: const TextStyle(
                                  color: Colors.white54, fontSize: 13),
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Strategies Sheet ──────────────────────────────────────────────────

class StrategiesSheet extends StatefulWidget {
  const StrategiesSheet({super.key});

  @override
  State<StrategiesSheet> createState() => _StrategiesSheetState();
}

class _StrategiesSheetState extends State<StrategiesSheet> {
  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.7,
      maxChildSize: 0.9,
      minChildSize: 0.3,
      expand: false,
      builder: (ctx, sc) => Consumer<StrategyProvider>(
        builder: (context, provider, _) {
          return ListView(
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
                  Text('STRATEGIES', style: TsarTheme.numberStyle.copyWith(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.5,
                  )),
                  const Spacer(),
                  IconButton(
                    icon: const Icon(Icons.refresh, color: Colors.white38),
                    onPressed: () => provider.refresh(),
                  ),
                ],
              ),
              const SizedBox(height: 16),

              if (provider.loading)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.all(32),
                    child: CircularProgressIndicator(color: TsarTheme.accent),
                  ),
                )
              else if (provider.error != null)
                ErrorBanner(
                  message: provider.error!,
                  onRetry: () => provider.refresh(),
                )
              else if (provider.strategies.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(
                    child: Text(
                      'No strategies found',
                      style: TextStyle(color: Colors.white24),
                    ),
                  ),
                )
              else
                ...provider.strategies.map((strategy) => Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(12),
                    onTap: () => _showStrategyDetail(context, strategy),
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Row(
                        children: [
                          Container(
                            width: 4,
                            height: 40,
                            decoration: BoxDecoration(
                              color: strategy.isActive
                                  ? TsarTheme.profit
                                  : Colors.white24,
                              borderRadius: BorderRadius.circular(2),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  strategy.name,
                                  style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                                ),
                                if (strategy.description.isNotEmpty)
                                  Text(
                                    strategy.description,
                                    style: const TextStyle(
                                        color: Colors.white38, fontSize: 12),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                              ],
                            ),
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: strategy.isActive
                                  ? TsarTheme.profit.withOpacity(0.15)
                                  : Colors.white.withOpacity(0.06),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              strategy.status.toUpperCase(),
                              style: TsarTheme.numberStyle.copyWith(
                                fontSize: 10,
                                color: strategy.isActive
                                    ? TsarTheme.profit
                                    : Colors.white38,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                )),
            ],
          );
        },
      ),
    );
  }

  void _showStrategyDetail(BuildContext context, dynamic strategy) {
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
            Text(strategy.name, style: TsarTheme.numberLarge),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: strategy.isActive
                    ? TsarTheme.profit.withOpacity(0.15)
                    : Colors.white.withOpacity(0.06),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                strategy.status.toUpperCase(),
                style: TsarTheme.numberStyle.copyWith(
                  color: strategy.isActive ? TsarTheme.profit : Colors.white38,
                ),
              ),
            ),
            const SizedBox(height: 20),
            if (strategy.description.isNotEmpty)
              Text(strategy.description,
                  style: const TextStyle(color: Colors.white70, fontSize: 15)),
            const Divider(height: 32),
            _detailRow('Total Return', '${strategy.totalReturn.toStringAsFixed(2)}%'),
            _detailRow('Sharpe Ratio', strategy.sharpeRatio.toStringAsFixed(2)),
            _detailRow('Max Drawdown', '${strategy.maxDrawdown.toStringAsFixed(2)}%'),
            _detailRow('Win Rate', '${strategy.winRate.toStringAsFixed(1)}%'),
            _detailRow('Trade Count', '${strategy.tradeCount}'),
            _detailRow('Profit Factor', strategy.profitFactor.toStringAsFixed(2)),
            if (strategy.genome.isNotEmpty) ...[
              const Divider(height: 32),
              Text('GENOME', style: TsarTheme.numberStyle.copyWith(
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
                  strategy.genome,
                  style: TsarTheme.numberStyle.copyWith(
                    fontSize: 12,
                    color: Colors.white60,
                  ),
                ),
              ),
            ],
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
