import 'dart:async';
import 'dart:math';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../models/risk.dart';
import '../models/scenario.dart';
import '../providers/risk_provider.dart';
import '../providers/portfolio_provider.dart';
import '../providers/blockchain_provider.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

// ─────────────────────────────────────────────────────────────────────────────
// Risk Screen — Professional Trading Terminal
// ─────────────────────────────────────────────────────────────────────────────

class RiskScreen extends StatefulWidget {
  const RiskScreen({super.key});

  @override
  State<RiskScreen> createState() => _RiskScreenState();
}

class _RiskScreenState extends State<RiskScreen> with TickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  // Simulated economic calendar events
  final List<_EconomicEvent> _economicEvents = [
    _EconomicEvent(
      title: 'FOMC Rate Decision',
      time: DateTime.now().add(const Duration(hours: 3, minutes: 42)),
      impact: _EventImpact.high,
      icon: Icons.account_balance,
    ),
    _EconomicEvent(
      title: 'CPI m/m',
      time: DateTime.now().add(const Duration(hours: 18, minutes: 15)),
      impact: _EventImpact.high,
      icon: Icons.trending_up,
    ),
    _EconomicEvent(
      title: 'Non-Farm Payrolls',
      time: DateTime.now().add(const Duration(days: 2, hours: 6)),
      impact: _EventImpact.medium,
      icon: Icons.work_outline,
    ),
  ];

  Timer? _clockTimer;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _pulseAnimation = Tween<double>(begin: 0.8, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<RiskProvider>().refresh();
      context.read<PortfolioProvider>().refresh();
      context.read<BlockchainProvider>().refresh();
    });
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _clockTimer?.cancel();
    super.dispose();
  }

  void _updatePulse(bool isActive) {
    if (isActive && !_pulseController.isAnimating) {
      _pulseController.repeat(reverse: true);
    } else if (!isActive && _pulseController.isAnimating) {
      _pulseController.stop();
      _pulseController.reset();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('RISK & PORTFOLIO'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              context.read<RiskProvider>().refresh();
              context.read<PortfolioProvider>().refresh();
              context.read<BlockchainProvider>().refresh();
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          await Future.wait([
            context.read<RiskProvider>().refresh(),
            context.read<PortfolioProvider>().refresh(),
            context.read<BlockchainProvider>().refresh(),
          ]);
        },
        color: TsarTheme.accent,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _buildKillSwitchCard(),
            const SizedBox(height: 14),
            _buildCircuitBreakerGauge(),
            const SizedBox(height: 14),
            _buildDailyLossBar(),
            const SizedBox(height: 14),
            _buildBehavioralGuards(),
            const SizedBox(height: 14),
            _buildScenarioPrevention(),
            const SizedBox(height: 14),
            _buildEconomicCalendar(),
            const SizedBox(height: 14),
            _buildPositionLimits(),
            const SizedBox(height: 14),
            _buildRiskGauges(),
            const SizedBox(height: 14),
            _buildDailyPnlChart(),
            const SizedBox(height: 14),
            _buildAlertsList(),
            const SizedBox(height: 80),
          ],
        ),
      ),
    );
  }

  // ── Kill Switch ──────────────────────────────────────────────────────────

  Widget _buildKillSwitchCard() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        final isActive = rs?.killSwitchActive ?? false;
        _updatePulse(isActive);

        return AnimatedBuilder(
          animation: _pulseAnimation,
          builder: (context, child) {
            final glowIntensity = isActive ? _pulseAnimation.value : 0.0;
            return Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                border: Border.all(
                  color: isActive
                      ? TsarTheme.killSwitch.withOpacity(glowIntensity)
                      : TsarTheme.profit.withOpacity(0.3),
                  width: isActive ? 2.0 : 1.0,
                ),
                boxShadow: isActive
                    ? [
                        BoxShadow(
                          color: TsarTheme.killSwitch.withOpacity(glowIntensity * 0.4),
                          blurRadius: 20 * glowIntensity,
                          spreadRadius: 2 * glowIntensity,
                        ),
                      ]
                    : [],
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: isActive
                      ? [
                          TsarTheme.killSwitch.withOpacity(0.15),
                          TsarTheme.surfaceVariant,
                        ]
                      : [
                          TsarTheme.profit.withOpacity(0.05),
                          TsarTheme.surfaceVariant,
                        ],
                ),
              ),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  children: [
                    Row(
                      children: [
                        // Big kill switch button
                        GestureDetector(
                          onTap: risk.killSwitchLoading
                              ? null
                              : () {
                                  if (isActive) {
                                    risk.deactivateKillSwitch();
                                  } else {
                                    risk.activateKillSwitch(reason: 'Manual activation');
                                  }
                                },
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 300),
                            width: 72,
                            height: 72,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: RadialGradient(
                                colors: isActive
                                    ? [
                                        TsarTheme.killSwitch,
                                        TsarTheme.killSwitch.withOpacity(0.7),
                                      ]
                                    : [
                                        TsarTheme.profit,
                                        TsarTheme.profit.withOpacity(0.7),
                                      ],
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: (isActive
                                          ? TsarTheme.killSwitch
                                          : TsarTheme.profit)
                                      ..withOpacity(0.5 * glowIntensity.clamp(0.3, 1.0)),
                                  blurRadius: 16,
                                  spreadRadius: 2,
                                ),
                              ],
                            ),
                            child: Icon(
                              isActive
                                  ? Icons.power_settings_new
                                  : Icons.check_circle_outline,
                              color: Colors.white,
                              size: 36,
                            ),
                          ),
                        ),
                        const SizedBox(width: 20),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                isActive ? 'KILL SWITCH ACTIVE' : 'SYSTEM OPERATIONAL',
                                style: TsarTheme.numberStyle.copyWith(
                                  fontSize: 15,
                                  color: isActive
                                      ? TsarTheme.killSwitch
                                      : TsarTheme.profit,
                                  letterSpacing: 1.5,
                                ),
                              ),
                              const SizedBox(height: 6),
                              if (isActive && rs?.killSwitchReason != null)
                                Text(
                                  rs!.killSwitchReason!,
                                  style: const TextStyle(
                                    color: Colors.white54,
                                    fontSize: 12,
                                  ),
                                ),
                              if (isActive && rs?.killSwitchActivatedAt != null)
                                Text(
                                  'Since ${_formatTime(rs!.killSwitchActivatedAt!)}',
                                  style: TextStyle(
                                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                                    color: TsarTheme.killSwitch.withOpacity(0.6),
                                    fontSize: 11,
                                  ),
                                ),
                              if (!isActive)
                                const Text(
                                  'All systems nominal',
                                  style: TextStyle(
                                    color: Colors.white38,
                                    fontSize: 12,
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    if (isActive) ...[
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: risk.killSwitchLoading
                              ? null
                              : () => risk.deactivateKillSwitch(),
                          icon: risk.killSwitchLoading
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
                                )
                              : const Icon(Icons.play_arrow, size: 18),
                          label: const Text('RESUME TRADING'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: TsarTheme.profit,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  // ── Circuit Breaker Gauge ────────────────────────────────────────────────

  Widget _buildCircuitBreakerGauge() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        final level = rs?.circuitBreaker ?? CircuitBreakerLevel.none;

        return _TerminalCard(
          title: 'CIRCUIT BREAKER',
          child: Column(
            children: [
              const SizedBox(height: 8),
              // Gauge bar: GREEN → YELLOW → ORANGE → RED
              _buildBreakerGaugeBar(level),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _breakerSegmentLabel('GREEN', 'Normal', TsarTheme.profit, level == CircuitBreakerLevel.none),
                  _breakerSegmentLabel('YELLOW', 'Warning', TsarTheme.warning, level == CircuitBreakerLevel.warning),
                  _breakerSegmentLabel('ORANGE', 'Critical', TsarTheme.statusOrange, level == CircuitBreakerLevel.critical),
                  _breakerSegmentLabel('RED', 'Halted', TsarTheme.loss, level == CircuitBreakerLevel.halted),
                ],
              ),
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: _breakerColor(level).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: _breakerColor(level).withOpacity(0.3),
                  ),
                ),
                child: Text(
                  _breakerDescription(level),
                  style: TextStyle(
                    color: _breakerColor(level),
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildBreakerGaugeBar(CircuitBreakerLevel level) {
    final segments = [
      _GaugeSegment(0.25, TsarTheme.profit, level == CircuitBreakerLevel.none),
      _GaugeSegment(0.25, TsarTheme.warning, level == CircuitBreakerLevel.warning),
      _GaugeSegment(0.25, TsarTheme.statusOrange, level == CircuitBreakerLevel.critical),
      _GaugeSegment(0.25, TsarTheme.loss, level == CircuitBreakerLevel.halted),
    ];

    // Determine pointer position
    double pointerPos;
    switch (level) {
      case CircuitBreakerLevel.none:
        pointerPos = 0.125;
        break;
      case CircuitBreakerLevel.warning:
        pointerPos = 0.375;
        break;
      case CircuitBreakerLevel.critical:
        pointerPos = 0.625;
        break;
      case CircuitBreakerLevel.halted:
        pointerPos = 0.875;
        break;
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final totalWidth = constraints.maxWidth;
        return SizedBox(
          height: 40,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              // Gauge segments
              Row(
                children: segments.map((seg) {
                  return Expanded(
                    flex: 1,
                    child: Container(
                      height: 20,
                      decoration: BoxDecoration(
                        color: seg.isActive
                            ? seg.color
                            : seg.color.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  );
                }).toList(),
              ),
              // Pointer
              Positioned(
                left: totalWidth * pointerPos - 8,
                top: -6,
                child: Column(
                  children: [
                    Icon(
                      Icons.arrow_drop_down,
                      color: _breakerColor(level),
                      size: 24,
                    ),
                    Container(
                      width: 3,
                      height: 12,
                      decoration: BoxDecoration(
                        color: _breakerColor(level),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _breakerSegmentLabel(String label, String sublabel, Color color, bool isActive) {
    return Opacity(
      opacity: isActive ? 1.0 : 0.4,
      child: Column(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: color,
              boxShadow: isActive
                  ? [BoxShadow(color: color.withOpacity(0.6), blurRadius: 6)]
                  : null,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: TsarTheme.numberStyle.copyWith(
              fontSize: 9,
              color: isActive ? color : Colors.white24,
              letterSpacing: 1,
            ),
          ),
          Text(
            sublabel,
            style: TextStyle(
              fontSize: 8,
              color: isActive ? Colors.white54 : Colors.white24,
            ),
          ),
        ],
      ),
    );
  }

  // ── Daily Loss Progress Bar ──────────────────────────────────────────────

  Widget _buildDailyLossBar() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        final limit = rs?.dailyLossLimit ?? 100;
        final used = rs?.dailyLossUsed ?? 0;
        final pct = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;

        return _TerminalCard(
          title: 'DAILY LOSS LIMIT',
          trailing: Text(
            '${used.toStringAsFixed(1)}% / ${limit.toStringAsFixed(1)}%',
            style: TsarTheme.numberStyle.copyWith(
              fontSize: 12,
              color: _lossBarColor(pct),
            ),
          ),
          child: Column(
            children: [
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: SizedBox(
                  height: 24,
                  child: Stack(
                    children: [
                      // Background
                      Container(
                        decoration: BoxDecoration(
                          color: Colors.white.withOpacity(0.06),
                          borderRadius: BorderRadius.circular(6),
                        ),
                      ),
                      // Gradient fill
                      FractionallySizedBox(
                        widthFactor: pct,
                        child: Container(
                          decoration: BoxDecoration(
                            gradient: LinearGradient(
                              colors: [
                                TsarTheme.profit,
                                if (pct > 0.5) TsarTheme.warning,
                                if (pct > 0.75) TsarTheme.statusOrange,
                                if (pct > 0.9) TsarTheme.loss,
                              ],
                              stops: [
                                0.0,
                                if (pct > 0.5) 0.5,
                                if (pct > 0.75) 0.75,
                                if (pct > 0.9) 0.9,
                              ],
                            ),
                            borderRadius: BorderRadius.circular(6),
                          ),
                        ),
                      ),
                      // Percentage label
                      Center(
                        child: Text(
                          '${(pct * 100).toStringAsFixed(0)}%',
                          style: TsarTheme.numberStyle.copyWith(
                            fontSize: 11,
                            color: Colors.white,
                            shadows: [
                              Shadow(
                                color: Colors.black.withOpacity(0.8),
                                blurRadius: 4,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
              // Tick marks
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: ['0%', '25%', '50%', '75%', '100%'].map((tick) {
                  return Text(
                    tick,
                    style: TextStyle(
                      fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                      fontSize: 9,
                      color: Colors.white24,
                    ),
                  );
                }).toList(),
              ),
            ],
          ),
        );
      },
    );
  }

  // ── Anti-Behavioral Guards ───────────────────────────────────────────────

  Widget _buildBehavioralGuards() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        // Derive guard states from risk metrics
        final heat = rs?.portfolioHeat ?? 0;
        final dailyLoss = rs?.dailyLossPercent ?? 0;
        final drawdown = rs?.currentDrawdown ?? 0;
        final positions = rs?.currentPositions ?? 0;
        final maxPositions = rs?.positionLimit ?? 1;

        final guards = [
          _GuardData(
            name: 'REVENGE',
            subtitle: 'No re-entry after loss',
            icon: Icons.local_fire_department,
            isActive: dailyLoss > 0.02,
            riskLevel: (dailyLoss * 10).clamp(0.0, 1.0),
            color: TsarTheme.loss,
          ),
          _GuardData(
            name: 'GREED',
            subtitle: 'Position size cap',
            icon: Icons.monetization_on,
            isActive: positions / maxPositions > 0.8,
            riskLevel: (positions / maxPositions).clamp(0.0, 1.0),
            color: TsarTheme.warning,
          ),
          _GuardData(
            name: 'FOMO',
            subtitle: 'Chase prevention',
            icon: Icons.speed,
            isActive: heat > 0.7,
            riskLevel: heat.clamp(0.0, 1.0),
            color: TsarTheme.statusOrange,
          ),
          _GuardData(
            name: 'OVERCONF',
            subtitle: 'Win streak limiter',
            icon: Icons.psychology,
            isActive: drawdown > 0.05,
            riskLevel: (drawdown * 5).clamp(0.0, 1.0),
            color: TsarTheme.accent,
          ),
        ];

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.shield, size: 16, color: TsarTheme.accent),
                const SizedBox(width: 8),
                Text(
                  'ANTI-BEHAVIORAL GUARDS',
                  style: TsarTheme.numberStyle.copyWith(
                    color: Colors.white54,
                    fontSize: 12,
                    letterSpacing: 1.2,
                  ),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: guards.any((g) => g.isActive)
                        ? TsarTheme.warning.withOpacity(0.15)
                        : TsarTheme.profit.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    guards.any((g) => g.isActive)
                        ? '${guards.where((g) => g.isActive).length} ACTIVE'
                        : 'ALL CLEAR',
                    style: TsarTheme.numberStyle.copyWith(
                      fontSize: 10,
                      color: guards.any((g) => g.isActive)
                          ? TsarTheme.warning
                          : TsarTheme.profit,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisSpacing: 10,
              mainAxisSpacing: 10,
              childAspectRatio: 1.5,
              children: guards.map((g) => _GuardCard(guard: g)).toList(),
            ),
          ],
        );
      },
    );
  }

  // ── Scenario Prevention ──────────────────────────────────────────────────

  Widget _buildScenarioPrevention() {
    return Consumer<BlockchainProvider>(
      builder: (context, blockchain, _) {
        final scenarios = blockchain.scenarios;
        if (scenarios.isEmpty) {
          return _TerminalCard(
            title: '🛡️ SCENARIO PREVENTION',
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  'No scenarios loaded',
                  style: TextStyle(
                    color: Colors.white24,
                    fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                    fontSize: 12,
                  ),
                ),
              ),
            ),
          );
        }

        final triggered = blockchain.triggeredScenarios;
        final active = blockchain.activeScenarios;

        // Scenario types to highlight
        final scenarioTypes = [
          _ScenarioType(
            label: 'Flash Crash',
            icon: Icons.bolt,
            scenarios: scenarios.where((s) => s.category == 'flash_crash').toList(),
          ),
          _ScenarioType(
            label: 'Stop Hunt',
            icon: Icons.gps_fixed,
            scenarios: scenarios.where((s) => s.category == 'liquidation').toList(),
          ),
          _ScenarioType(
            label: 'Whipsaw',
            icon: Icons.swap_vert,
            scenarios: scenarios.where((s) => s.category == 'volatility').toList(),
          ),
        ];

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.shield_outlined, size: 16, color: TsarTheme.accent),
                const SizedBox(width: 8),
                Text(
                  'SCENARIO PREVENTION',
                  style: TsarTheme.numberStyle.copyWith(
                    color: Colors.white54,
                    fontSize: 12,
                    letterSpacing: 1.2,
                  ),
                ),
                const Spacer(),
                if (triggered.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: TsarTheme.loss.withOpacity(0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      '${triggered.length} TRIGGERED',
                      style: TsarTheme.numberStyle.copyWith(
                        fontSize: 10,
                        color: TsarTheme.loss,
                      ),
                    ),
                  )
                else
                  Text(
                    '${active.length} monitoring',
                    style: TsarTheme.numberStyle.copyWith(
                      fontSize: 11,
                      color: TsarTheme.profit,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            ...scenarioTypes.map((st) => _buildScenarioAlertCard(st, scenarios)),
          ],
        );
      },
    );
  }

  Widget _buildScenarioAlertCard(_ScenarioType type, List<Scenario> allScenarios) {
    final matching = type.scenarios;
    final hasTriggered = matching.any((s) => s.isTriggered);
    final hasActive = matching.any((s) => s.isActive);
    final statusColor = hasTriggered
        ? TsarTheme.loss
        : hasActive
            ? TsarTheme.warning
            : TsarTheme.profit;
    final statusLabel = hasTriggered
        ? 'TRIGGERED'
        : hasActive
            ? 'MONITORING'
            : 'CLEAR';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: statusColor.withOpacity(hasTriggered ? 0.5 : 0.2),
        ),
        gradient: LinearGradient(
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
          colors: [
            statusColor.withOpacity(hasTriggered ? 0.1 : 0.03),
            TsarTheme.surfaceVariant,
          ],
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: statusColor.withOpacity(0.15),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(type.icon, color: statusColor, size: 20),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  type.label,
                  style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                ),
                const SizedBox(height: 2),
                Text(
                  matching.isEmpty
                      ? 'No scenarios configured'
                      : '${matching.length} scenario${matching.length > 1 ? 's' : ''} tracked',
                  style: const TextStyle(color: Colors.white38, fontSize: 11),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: statusColor.withOpacity(0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              statusLabel,
              style: TsarTheme.numberStyle.copyWith(
                fontSize: 10,
                color: statusColor,
                letterSpacing: 1,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── Economic Calendar ────────────────────────────────────────────────────

  Widget _buildEconomicCalendar() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.calendar_today, size: 16, color: TsarTheme.accent),
            const SizedBox(width: 8),
            Text(
              'ECONOMIC CALENDAR',
              style: TsarTheme.numberStyle.copyWith(
                color: Colors.white54,
                fontSize: 12,
                letterSpacing: 1.2,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        ..._economicEvents.map((event) => _buildEventCard(event)),
      ],
    );
  }

  Widget _buildEventCard(_EconomicEvent event) {
    final now = DateTime.now();
    final diff = event.time.difference(now);
    final isPast = diff.isNegative;
    final impactColor = event.impact == _EventImpact.high
        ? TsarTheme.loss
        : event.impact == _EventImpact.medium
            ? TsarTheme.warning
            : TsarTheme.profit;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TsarTheme.cardBorder),
        color: TsarTheme.surfaceVariant,
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: impactColor.withOpacity(0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(event.icon, color: impactColor, size: 22),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  event.title,
                  style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: impactColor.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        event.impact == _EventImpact.high
                            ? 'HIGH'
                            : event.impact == _EventImpact.medium
                                ? 'MED'
                                : 'LOW',
                        style: TsarTheme.numberStyle.copyWith(
                          fontSize: 9,
                          color: impactColor,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      _formatEventTime(event.time),
                      style: const TextStyle(
                        color: Colors.white38,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          // Countdown timer
          if (!isPast)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.05),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.white.withOpacity(0.08)),
              ),
              child: Text(
                _formatCountdown(diff),
                style: TextStyle(
                  fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: diff.inHours < 2 ? TsarTheme.warning : Colors.white70,
                ),
              ),
            )
          else
            Text(
              'PASSED',
              style: TsarTheme.numberStyle.copyWith(
                fontSize: 11,
                color: Colors.white24,
              ),
            ),
        ],
      ),
    );
  }

  // ── Position Limits ──────────────────────────────────────────────────────

  Widget _buildPositionLimits() {
    return Consumer2<RiskProvider, PortfolioProvider>(
      builder: (context, risk, portfolio, _) {
        final rs = risk.riskState;
        final currentPositions = portfolio.positions.length.toDouble();
        final maxPositions = rs?.positionLimit ?? 10;
        final ratio = maxPositions > 0 ? (currentPositions / maxPositions).clamp(0.0, 1.0) : 0.0;

        final currentSize = portfolio.totalMarketValue;
        final maxSize = rs?.exposure['max_size']?.toDouble() ?? currentSize * 2;
        final sizeRatio = maxSize > 0 ? (currentSize / maxSize).clamp(0.0, 1.0) : 0.0;

        return _TerminalCard(
          title: 'POSITION LIMITS',
          child: Column(
            children: [
              _buildLimitRow(
                'Open Positions',
                '${currentPositions.toInt()}',
                '${maxPositions.toInt()} max',
                ratio,
              ),
              const SizedBox(height: 12),
              _buildLimitRow(
                'Total Exposure',
                '\$${_formatNumber(currentSize)}',
                '\$${_formatNumber(maxSize)} max',
                sizeRatio,
              ),
              if (portfolio.positions.isNotEmpty) ...[
                const SizedBox(height: 12),
                const Divider(color: Colors.white12, height: 1),
                const SizedBox(height: 12),
                ...portfolio.positions.take(5).map((pos) {
                  final posRatio = maxPositions > 0 ? (1.0 / maxPositions).clamp(0.0, 1.0) : 0.0;
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 70,
                          child: Text(
                            pos.symbol,
                            style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                          ),
                        ),
                        Expanded(
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(3),
                            child: LinearProgressIndicator(
                              value: posRatio,
                              backgroundColor: Colors.white.withOpacity(0.06),
                              valueColor: AlwaysStoppedAnimation(
                                pos.unrealizedPnlPercent >= 0
                                    ? TsarTheme.profit.withOpacity(0.6)
                                    : TsarTheme.loss.withOpacity(0.6),
                              ),
                              minHeight: 6,
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        SizedBox(
                          width: 65,
                          child: Text(
                            '${pos.unrealizedPnlPercent >= 0 ? '+' : ''}${pos.unrealizedPnlPercent.toStringAsFixed(2)}%',
                            style: TsarTheme.numberStyle.copyWith(
                              fontSize: 12,
                              color: pos.unrealizedPnlPercent >= 0
                                  ? TsarTheme.profit
                                  : TsarTheme.loss,
                            ),
                            textAlign: TextAlign.right,
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildLimitRow(String label, String current, String max, double ratio) {
    final color = ratio < 0.5
        ? TsarTheme.profit
        : ratio < 0.8
            ? TsarTheme.warning
            : TsarTheme.loss;

    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: const TextStyle(color: Colors.white54, fontSize: 12)),
            Row(
              children: [
                Text(
                  current,
                  style: TsarTheme.numberStyle.copyWith(fontSize: 14, color: color),
                ),
                Text(
                  ' / $max',
                  style: TsarTheme.numberStyle.copyWith(
                    fontSize: 11,
                    color: Colors.white38,
                  ),
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: ratio,
            backgroundColor: Colors.white.withOpacity(0.06),
            valueColor: AlwaysStoppedAnimation(color),
            minHeight: 8,
          ),
        ),
      ],
    );
  }

  // ── Risk Gauges ──────────────────────────────────────────────────────────

  Widget _buildRiskGauges() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        return Row(
          children: [
            Expanded(
              child: _TerminalCard(
                child: Column(
                  children: [
                    RiskGauge(
                      value: rs?.portfolioHeat ?? 0,
                      label: 'Heat',
                      size: 100,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'PORTFOLIO HEAT',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white38,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _TerminalCard(
                child: Column(
                  children: [
                    RiskGauge(
                      value: rs?.dailyLossPercent ?? 0,
                      label: 'Used',
                      size: 100,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'DAILY LOSS LIMIT',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white38,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _TerminalCard(
                child: Column(
                  children: [
                    RiskGauge(
                      value: (rs?.currentDrawdown ?? 0) /
                          ((rs?.maxDrawdown ?? 1) == 0 ? 1 : rs!.maxDrawdown),
                      label: 'DD',
                      size: 100,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'DRAWDOWN',
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white38,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  // ── Daily P&L Chart ──────────────────────────────────────────────────────

  Widget _buildDailyPnlChart() {
    return Consumer<PortfolioProvider>(
      builder: (context, portfolio, _) {
        final pnl = portfolio.pnl;
        if (pnl == null) return const SizedBox.shrink();

        final spots = pnl.equityCurve
            .asMap()
            .entries
            .map((e) => FlSpot(e.key.toDouble(), e.value.value))
            .toList();

        return _TerminalCard(
          title: 'DAILY P&L',
          trailing: PnlBadge(value: pnl.dailyReturn),
          child: PnlLineChart(spots: spots, height: 180),
        );
      },
    );
  }

  // ── Alerts List ──────────────────────────────────────────────────────────

  Widget _buildAlertsList() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final alerts = risk.riskState?.alerts ?? [];
        if (alerts.isEmpty) return const SizedBox.shrink();

        return _TerminalCard(
          title: 'ALERTS (${alerts.length})',
          child: Column(
            children: alerts.take(5).map((alert) {
              final color = alert.level == 'critical'
                  ? TsarTheme.loss
                  : alert.level == 'warning'
                      ? TsarTheme.warning
                      : TsarTheme.info;
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    Container(
                      width: 6,
                      height: 6,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: color,
                        boxShadow: [BoxShadow(color: color.withOpacity(0.5), blurRadius: 4)],
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        alert.message,
                        style: const TextStyle(color: Colors.white70, fontSize: 13),
                      ),
                    ),
                    Text(
                      _formatTime(alert.timestamp),
                      style: TextStyle(
                        fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                        fontSize: 10,
                        color: Colors.white24,
                      ),
                    ),
                  ],
                ),
              );
            }).toList(),
          ),
        );
      },
    );
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  Color _breakerColor(CircuitBreakerLevel? level) {
    switch (level) {
      case CircuitBreakerLevel.warning:
        return TsarTheme.warning;
      case CircuitBreakerLevel.critical:
        return TsarTheme.statusOrange;
      case CircuitBreakerLevel.halted:
        return TsarTheme.loss;
      case CircuitBreakerLevel.none:
      default:
        return TsarTheme.profit;
    }
  }

  String _breakerDescription(CircuitBreakerLevel? level) {
    switch (level) {
      case CircuitBreakerLevel.warning:
        return 'Risk thresholds approaching limits — monitoring closely';
      case CircuitBreakerLevel.critical:
        return 'Risk limits breached — auto-reducing exposure';
      case CircuitBreakerLevel.halted:
        return 'Trading halted by circuit breaker — manual intervention required';
      case CircuitBreakerLevel.none:
      default:
        return 'All risk parameters within normal range';
    }
  }

  Color _lossBarColor(double pct) {
    if (pct < 0.5) return TsarTheme.profit;
    if (pct < 0.75) return TsarTheme.warning;
    if (pct < 0.9) return TsarTheme.statusOrange;
    return TsarTheme.loss;
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }

  String _formatEventTime(DateTime dt) {
    final now = DateTime.now();
    final diff = dt.difference(now);
    if (diff.inDays > 0) return '${dt.month}/${dt.day} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    return 'Today ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  String _formatCountdown(Duration d) {
    if (d.inHours >= 24) {
      final days = d.inDays;
      final hours = d.inHours % 24;
      return '${days}d ${hours}h';
    }
    final hours = d.inHours;
    final minutes = d.inMinutes % 60;
    final seconds = d.inSeconds % 60;
    return '${hours.toString().padLeft(2, '0')}:${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  String _formatNumber(double n) {
    if (n >= 1e6) return '${(n / 1e6).toStringAsFixed(1)}M';
    if (n >= 1e3) return '${(n / 1e3).toStringAsFixed(1)}K';
    return n.toStringAsFixed(0);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Private helper types
// ─────────────────────────────────────────────────────────────────────────────

class _TerminalCard extends StatelessWidget {
  final String? title;
  final Widget child;
  final Widget? trailing;

  const _TerminalCard({this.title, required this.child, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Container(
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
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null || trailing != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    if (title != null)
                      Text(
                        title!,
                        style: TsarTheme.numberStyle.copyWith(
                          color: Colors.white54,
                          fontSize: 12,
                          letterSpacing: 1.2,
                        ),
                      ),
                    if (trailing != null) trailing!,
                  ],
                ),
              ),
            child,
          ],
        ),
      ),
    );
  }
}

class _GuardData {
  final String name;
  final String subtitle;
  final IconData icon;
  final bool isActive;
  final double riskLevel;
  final Color color;

  _GuardData({
    required this.name,
    required this.subtitle,
    required this.icon,
    required this.isActive,
    required this.riskLevel,
    required this.color,
  });
}

class _GuardCard extends StatelessWidget {
  final _GuardData guard;

  const _GuardCard({required this.guard});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: guard.isActive
              ? guard.color.withOpacity(0.5)
              : TsarTheme.cardBorder,
        ),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            guard.isActive
                ? guard.color.withOpacity(0.1)
                : TsarTheme.card,
            TsarTheme.surfaceVariant,
          ],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Row(
            children: [
              Icon(guard.icon, size: 18, color: guard.color.withOpacity(guard.isActive ? 1.0 : 0.4)),
              const Spacer(),
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: guard.isActive ? guard.color : Colors.white24,
                  boxShadow: guard.isActive
                      ? [BoxShadow(color: guard.color.withOpacity(0.6), blurRadius: 6)]
                      : null,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            guard.name,
            style: TsarTheme.numberStyle.copyWith(
              fontSize: 13,
              color: guard.isActive ? guard.color : Colors.white54,
              letterSpacing: 1,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            guard.subtitle,
            style: TextStyle(
              fontSize: 10,
              color: guard.isActive ? Colors.white54 : Colors.white24,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: guard.riskLevel,
              backgroundColor: Colors.white.withOpacity(0.06),
              valueColor: AlwaysStoppedAnimation(
                guard.color.withOpacity(guard.isActive ? 0.8 : 0.3),
              ),
              minHeight: 4,
            ),
          ),
        ],
      ),
    );
  }
}

class _GaugeSegment {
  final double widthFactor;
  final Color color;
  final bool isActive;

  _GaugeSegment(this.widthFactor, this.color, this.isActive);
}

enum _EventImpact { high, medium, low }

class _EconomicEvent {
  final String title;
  final DateTime time;
  final _EventImpact impact;
  final IconData icon;

  _EconomicEvent({
    required this.title,
    required this.time,
    required this.impact,
    required this.icon,
  });
}

class _ScenarioType {
  final String label;
  final IconData icon;
  final List<Scenario> scenarios;

  _ScenarioType({
    required this.label,
    required this.icon,
    required this.scenarios,
  });
}
