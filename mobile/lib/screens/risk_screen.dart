import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';
import '../models/risk.dart';
import '../providers/risk_provider.dart';
import '../providers/portfolio_provider.dart';
import '../widgets/cards.dart';
import '../widgets/charts.dart';

class RiskScreen extends StatefulWidget {
  const RiskScreen({super.key});

  @override
  State<RiskScreen> createState() => _RiskScreenState();
}

class _RiskScreenState extends State<RiskScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<RiskProvider>().refresh();
      context.read<PortfolioProvider>().refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Risk & Portfolio'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              context.read<RiskProvider>().refresh();
              context.read<PortfolioProvider>().refresh();
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          await Future.wait([
            context.read<RiskProvider>().refresh(),
            context.read<PortfolioProvider>().refresh(),
          ]);
        },
        color: TsarTheme.accent,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _buildKillSwitchCard(),
            const SizedBox(height: 12),
            _buildCircuitBreakerCard(),
            const SizedBox(height: 12),
            _buildRiskGauges(),
            const SizedBox(height: 12),
            _buildDailyPnlChart(),
            const SizedBox(height: 12),
            _buildPositionsList(),
            const SizedBox(height: 12),
            _buildAlertsList(),
            const SizedBox(height: 80),
          ],
        ),
      ),
    );
  }

  Widget _buildKillSwitchCard() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        final isActive = rs?.killSwitchActive ?? false;

        return TsarCard(
          borderColor: isActive ? TsarTheme.killSwitch : null,
          child: Column(
            children: [
              Row(
                children: [
                  Icon(
                    isActive ? Icons.power_settings_new : Icons.check_circle_outline,
                    color: isActive ? TsarTheme.killSwitch : TsarTheme.profit,
                    size: 32,
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          isActive ? 'KILL SWITCH ACTIVE' : 'SYSTEM OPERATIONAL',
                          style: TsarTheme.numberStyle.copyWith(
                            fontSize: 14,
                            color: isActive ? TsarTheme.killSwitch : TsarTheme.profit,
                            letterSpacing: 1.2,
                          ),
                        ),
                        if (isActive && rs?.killSwitchReason != null)
                          Text(
                            rs!.killSwitchReason!,
                            style: TextStyle(color: Colors.white54, fontSize: 12),
                          ),
                      ],
                    ),
                  ),
                  if (isActive)
                    ElevatedButton(
                      onPressed: risk.killSwitchLoading
                          ? null
                          : () => risk.deactivateKillSwitch(),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: TsarTheme.profit,
                      ),
                      child: const Text('RESUME'),
                    ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildCircuitBreakerCard() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        final level = rs?.circuitBreaker.name ?? 'none';
        final levelColor = _breakerColor(rs?.circuitBreaker);

        return TsarCard(
          title: 'CIRCUIT BREAKER',
          borderColor: levelColor.withOpacity(0.3),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(
                  color: levelColor.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  level.toUpperCase(),
                  style: TsarTheme.numberStyle.copyWith(
                    color: levelColor,
                    letterSpacing: 1.5,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Text(
                  _breakerDescription(rs?.circuitBreaker),
                  style: TextStyle(color: Colors.white54, fontSize: 13),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildRiskGauges() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final rs = risk.riskState;
        return Row(
          children: [
            Expanded(
              child: TsarCard(
                child: Column(
                  children: [
                    RiskGauge(
                      value: rs?.portfolioHeat ?? 0,
                      label: 'Heat',
                      size: 100,
                    ),
                    const SizedBox(height: 8),
                    Text('PORTFOLIO HEAT',
                        style: TextStyle(
                          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                          fontSize: 10,
                          color: Colors.white38,
                          letterSpacing: 1,
                        )),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TsarCard(
                child: Column(
                  children: [
                    RiskGauge(
                      value: rs?.dailyLossPercent ?? 0,
                      label: 'Used',
                      size: 100,
                    ),
                    const SizedBox(height: 8),
                    Text('DAILY LOSS LIMIT',
                        style: TextStyle(
                          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                          fontSize: 10,
                          color: Colors.white38,
                          letterSpacing: 1,
                        )),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TsarCard(
                child: Column(
                  children: [
                    RiskGauge(
                      value: (rs?.currentDrawdown ?? 0) /
                          ((rs?.maxDrawdown ?? 1) == 0 ? 1 : rs!.maxDrawdown),
                      label: 'DD',
                      size: 100,
                    ),
                    const SizedBox(height: 8),
                    Text('DRAWDOWN',
                        style: TextStyle(
                          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
                          fontSize: 10,
                          color: Colors.white38,
                          letterSpacing: 1,
                        )),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

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

        return TsarCard(
          title: 'DAILY P&L',
          trailing: Text(
            '${pnl.dailyReturn >= 0 ? '+' : ''}${pnl.dailyReturn.toStringAsFixed(2)}%',
            style: TsarTheme.pnlStyle(pnl.dailyReturn),
          ),
          child: PnlLineChart(spots: spots, height: 180),
        );
      },
    );
  }

  Widget _buildPositionsList() {
    return Consumer<PortfolioProvider>(
      builder: (context, portfolio, _) {
        if (portfolio.positions.isEmpty) return const SizedBox.shrink();

        return TsarCard(
          title: 'OPEN POSITIONS (${portfolio.positions.length})',
          child: Column(
            children: portfolio.positions.map((pos) {
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Row(
                  children: [
                    Expanded(
                      flex: 2,
                      child: Text(
                        pos.symbol,
                        style: TsarTheme.numberStyle.copyWith(fontSize: 14),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '${pos.quantity.toStringAsFixed(2)} qty',
                        style: TextStyle(color: Colors.white54, fontSize: 12),
                        textAlign: TextAlign.right,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '\$${pos.currentPrice.toStringAsFixed(2)}',
                        style: TsarTheme.numberStyle.copyWith(fontSize: 13),
                        textAlign: TextAlign.right,
                      ),
                    ),
                    SizedBox(
                      width: 70,
                      child: Text(
                        '${pos.unrealizedPnlPercent >= 0 ? '+' : ''}${pos.unrealizedPnlPercent.toStringAsFixed(2)}%',
                        style: TsarTheme.pnlStyle(pos.unrealizedPnlPercent),
                        textAlign: TextAlign.right,
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

  Widget _buildAlertsList() {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final alerts = risk.riskState?.alerts ?? [];
        if (alerts.isEmpty) return const SizedBox.shrink();

        return TsarCard(
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
                    Icon(Icons.circle, size: 8, color: color),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        alert.message,
                        style: TextStyle(color: Colors.white70, fontSize: 13),
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

  Color _breakerColor(CircuitBreakerLevel? level) {
    switch (level) {
      case CircuitBreakerLevel.warning: return TsarTheme.warning;
      case CircuitBreakerLevel.critical: return TsarTheme.loss;
      case CircuitBreakerLevel.halted: return TsarTheme.killSwitch;
      case CircuitBreakerLevel.none:
      default: return TsarTheme.profit;
    }
  }

  String _breakerDescription(CircuitBreakerLevel? level) {
    switch (level) {
      case CircuitBreakerLevel.warning: return 'Risk thresholds approaching limits';
      case CircuitBreakerLevel.critical: return 'Risk limits breached — reducing exposure';
      case CircuitBreakerLevel.halted: return 'Trading halted by circuit breaker';
      case CircuitBreakerLevel.none:
      default: return 'All risk parameters within normal range';
    }
  }
}
