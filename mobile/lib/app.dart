import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'theme.dart';
import 'providers/settings_provider.dart';
import 'screens/dashboard_screen.dart';
import 'screens/trades_screen.dart';
import 'screens/risk_screen.dart';
import 'screens/factors_screen.dart';
import 'screens/news_screen.dart';
import 'screens/defi_screen.dart';
import 'screens/blockchain_screen.dart';
import 'screens/settings_screen.dart';
import 'services/websocket_service.dart';
import 'providers/risk_provider.dart';
import 'widgets/kill_switch_fab.dart';

// ═══════════════════════════════════════════════════════════════════════════
// TSAR App — Shell & Navigation
// ═══════════════════════════════════════════════════════════════════════════

class TsarApp extends StatelessWidget {
  const TsarApp({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<SettingsProvider>(
      builder: (context, settings, _) {
        return MaterialApp(
          title: 'TSAR',
          debugShowCheckedModeBanner: false,
          theme: TsarTheme.darkTheme,
          darkTheme: TsarTheme.darkTheme,
          themeMode: settings.isDarkMode ? ThemeMode.dark : ThemeMode.light,
          home: const MainShell(),
        );
      },
    );
  }
}

// ── Main Shell ───────────────────────────────────────────────────────────

class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _currentIndex = 0;

  /// 4 primary tabs: Dashboard, Trades, Risk, More.
  /// "More" opens a bottom sheet for secondary screens.
  static const _primaryTabs = <_TabDef>[
    _TabDef(
      icon: Icons.dashboard_outlined,
      selectedIcon: Icons.dashboard,
      label: 'Dashboard',
    ),
    _TabDef(
      icon: Icons.candlestick_chart_outlined,
      selectedIcon: Icons.candlestick_chart,
      label: 'Trades',
    ),
    _TabDef(
      icon: Icons.shield_outlined,
      selectedIcon: Icons.shield,
      label: 'Risk',
    ),
    _TabDef(
      icon: Icons.more_horiz,
      selectedIcon: Icons.more_horiz,
      label: 'More',
    ),
  ];

  /// IndexedStack screens — index 0-2 are primary, index 3 is a placeholder
  /// (the "More" tab opens a sheet instead of showing a screen).
  final _screens = const [
    DashboardScreen(),
    TradesScreen(),
    RiskScreen(),
    // Placeholder for "More" tab — shows the last-visited secondary screen.
    SettingsScreen(),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<WebSocketService>().connect();
    });
  }

  @override
  void dispose() {
    try {
      context.read<WebSocketService>().disconnect();
    } catch (_) {}
    super.dispose();
  }

  // ── Navigation ──────────────────────────────────────────────────────

  void _onTabSelected(int index) {
    if (index == 3) {
      // "More" tab — open bottom sheet
      _showMoreSheet();
      return;
    }
    setState(() => _currentIndex = index);
  }

  void _showMoreSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: TsarTheme.surfaceVariant,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => _MoreSheet(
        onNavigate: (screen) {
          Navigator.pop(ctx);
          // Swap the placeholder screen and switch to index 3
          setState(() {
            _currentIndex = 3;
          });
          // Navigate to the actual screen
          Navigator.push(
            context,
            _createSlideRoute(screen),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _buildAppBar(context),
      body: IndexedStack(
        index: _currentIndex.clamp(0, 2),
        children: _screens.sublist(0, 3),
      ),
      bottomNavigationBar: _buildBottomNav(),
      floatingActionButton: const KillSwitchFab(),
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
    );
  }

  // ── App Bar ─────────────────────────────────────────────────────────

  PreferredSizeWidget _buildAppBar(BuildContext context) {
    return AppBar(
      leadingWidth: 120,
      leading: Padding(
        padding: const EdgeInsets.only(left: 16),
        child: Row(
          children: [
            // TSAR logo / wordmark
            Text(
              'TSAR',
              style: TsarTheme.interStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: TsarTheme.accent,
                letterSpacing: 2,
              ),
            ),
          ],
        ),
      ),
      actions: [
        // Connection status indicator
        Consumer<WebSocketService>(
          builder: (context, ws, _) {
            final connected = ws.connected;
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Tooltip(
                message: connected ? 'Connected' : 'Disconnected',
                child: Container(
                  width: 10,
                  height: 10,
                  margin: const EdgeInsets.only(right: 4),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: connected ? TsarTheme.statusGreen : TsarTheme.statusRed,
                    boxShadow: [
                      BoxShadow(
                        color: (connected ? TsarTheme.statusGreen : TsarTheme.statusRed)
                            .withOpacity(0.6),
                        blurRadius: 6,
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
        // Kill switch button in app bar (always visible)
        Consumer<RiskProvider>(
          builder: (context, risk, _) {
            final isActive = risk.riskState?.killSwitchActive ?? false;
            return IconButton(
              onPressed: () => KillSwitchFab.activateFromAppBar(context),
              icon: Icon(
                isActive ? Icons.play_arrow : Icons.power_settings_new,
                color: isActive ? Colors.white : TsarTheme.killSwitch,
              ),
              tooltip: isActive ? 'Resume Trading' : 'Kill Switch',
            );
          },
        ),
        const SizedBox(width: 8),
      ],
    );
  }

  // ── Bottom Navigation Bar ───────────────────────────────────────────

  Widget _buildBottomNav() {
    return Container(
      decoration: BoxDecoration(
        color: TsarTheme.surface,
        border: const Border(
          top: BorderSide(color: TsarTheme.cardBorder, width: 0.5),
        ),
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: List.generate(_primaryTabs.length, (i) {
              final tab = _primaryTabs[i];
              final selected = i == _currentIndex;
              return _NavTab(
                tab: tab,
                selected: selected,
                onTap: () => _onTabSelected(i),
              );
            }),
          ),
        ),
      ),
    );
  }
}

// ── Tab Definition ───────────────────────────────────────────────────────

class _TabDef {
  final IconData icon;
  final IconData selectedIcon;
  final String label;

  const _TabDef({
    required this.icon,
    required this.selectedIcon,
    required this.label,
  });
}

// ── Nav Tab Widget ──────────────────────────────────────────────────────

class _NavTab extends StatelessWidget {
  final _TabDef tab;
  final bool selected;
  final VoidCallback onTap;

  const _NavTab({
    required this.tab,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = selected ? TsarTheme.accent : TsarTheme.muted;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? TsarTheme.accent.withOpacity(0.1) : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              selected ? tab.selectedIcon : tab.icon,
              color: color,
              size: 24,
            ),
            const SizedBox(height: 4),
            Text(
              tab.label,
              style: TsarTheme.labelSmall.copyWith(
                color: color,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── "More" Bottom Sheet ─────────────────────────────────────────────────

class _MoreSheet extends StatelessWidget {
  final ValueChanged<Widget> onNavigate;

  const _MoreSheet({required this.onNavigate});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Drag handle
            Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.white24,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: 20),
            Text(
              'MORE',
              style: TsarTheme.sectionTitle.copyWith(fontSize: 13),
            ),
            const SizedBox(height: 16),
            _MoreTile(
              icon: Icons.science_outlined,
              label: 'Factors',
              subtitle: 'Alpha factors & signals',
              onTap: () => onNavigate(const FactorsScreen()),
            ),
            _MoreTile(
              icon: Icons.article_outlined,
              label: 'News',
              subtitle: 'Real-time news feed',
              onTap: () => onNavigate(const NewsScreen()),
            ),
            _MoreTile(
              icon: Icons.currency_exchange_outlined,
              label: 'DeFi',
              subtitle: 'Yield positions & protocols',
              onTap: () => onNavigate(const DeFiScreen()),
            ),
            _MoreTile(
              icon: Icons.link_outlined,
              label: 'Blockchain',
              subtitle: 'On-chain rules & activity',
              onTap: () => onNavigate(const BlockchainScreen()),
            ),
            const Divider(height: 24, color: TsarTheme.cardBorder),
            _MoreTile(
              icon: Icons.settings_outlined,
              label: 'Settings',
              subtitle: 'API, appearance, about',
              onTap: () => onNavigate(const SettingsScreen()),
            ),
          ],
        ),
      ),
    );
  }
}

class _MoreTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String subtitle;
  final VoidCallback onTap;

  const _MoreTile({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: TsarTheme.accent.withOpacity(0.1),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Icon(icon, color: TsarTheme.accent, size: 20),
      ),
      title: Text(label, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
      subtitle: Text(subtitle, style: const TextStyle(color: Colors.white38, fontSize: 12)),
      trailing: const Icon(Icons.chevron_right, color: Colors.white24),
      contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      onTap: onTap,
    );
  }
}

// ── Slide Transition Route ──────────────────────────────────────────────

Route _createSlideRoute(Widget page) {
  return PageRouteBuilder(
    pageBuilder: (context, animation, secondaryAnimation) => page,
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      const begin = Offset(1.0, 0.0);
      const end = Offset.zero;
      const curve = Curves.easeOutCubic;
      final tween = Tween(begin: begin, end: end).chain(CurveTween(curve: curve));
      final offsetAnimation = animation.drive(tween);
      return SlideTransition(position: offsetAnimation, child: child);
    },
    transitionDuration: const Duration(milliseconds: 300),
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Animated Widgets
// ═══════════════════════════════════════════════════════════════════════════

/// Fade-in wrapper for cards and content.
class FadeInWidget extends StatefulWidget {
  final Widget child;
  final Duration delay;
  final Duration duration;

  const FadeInWidget({
    super.key,
    required this.child,
    this.delay = Duration.zero,
    this.duration = const Duration(milliseconds: 400),
  });

  @override
  State<FadeInWidget> createState() => _FadeInWidgetState();
}

class _FadeInWidgetState extends State<FadeInWidget>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: widget.duration);
    _animation = CurvedAnimation(parent: _controller, curve: Curves.easeOut);
    Future.delayed(widget.delay, () {
      if (mounted) _controller.forward();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _animation,
      child: SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(0, 0.05),
          end: Offset.zero,
        ).animate(_animation),
        child: widget.child,
      ),
    );
  }
}

/// Animated number counter for stat displays.
class AnimatedNumber extends StatefulWidget {
  final double value;
  final TextStyle? style;
  final String prefix;
  final String suffix;
  final int decimals;

  const AnimatedNumber({
    super.key,
    required this.value,
    this.style,
    this.prefix = '',
    this.suffix = '',
    this.decimals = 2,
  });

  @override
  State<AnimatedNumber> createState() => _AnimatedNumberState();
}

class _AnimatedNumberState extends State<AnimatedNumber>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;
  double _oldValue = 0;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _animation = Tween<double>(begin: 0, end: widget.value)
        .animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic));
    _controller.forward();
  }

  @override
  void didUpdateWidget(AnimatedNumber old) {
    super.didUpdateWidget(old);
    if (old.value != widget.value) {
      _oldValue = old.value;
      _animation = Tween<double>(begin: _oldValue, end: widget.value)
          .animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic));
      _controller.reset();
      _controller.forward();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, _) {
        final val = _animation.value;
        final formatted = val.toStringAsFixed(widget.decimals);
        return Text(
          '${widget.prefix}$formatted${widget.suffix}',
          style: widget.style,
        );
      },
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Stubs for imports used in app.dart but defined elsewhere.
// These prevent compile errors if the actual providers/services don't expose
// the exact interface. Replace with real imports.
// ═══════════════════════════════════════════════════════════════════════════

// NOTE: RiskProvider is imported from providers/risk_provider.dart.

