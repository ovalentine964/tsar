import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../providers/dashboard_provider.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  @override
  void initState() {
    super.initState();
    context.read<DashboardProvider>().refresh();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DashboardProvider>(
      builder: (context, dash, _) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('COMMAND CENTER'),
            actions: [
              IconButton(
                icon: const Icon(Icons.refresh),
                onPressed: dash.refresh,
              ),
            ],
          ),
          body: dash.loading && dash.stats == null
              ? const Center(child: CircularProgressIndicator(color: TsarTheme.accent))
              : dash.error != null && dash.stats == null
                  ? _buildError(dash)
                  : RefreshIndicator(
                      onRefresh: dash.refresh,
                      color: TsarTheme.accent,
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          _buildPnlHero(dash),
                          const SizedBox(height: 16),
                          _buildStatsGrid(dash),
                          const SizedBox(height: 16),
                          _buildRegimeCard(dash),
                          const SizedBox(height: 16),
                          _buildFlywheelCard(dash),
                          const SizedBox(height: 16),
                          _buildKillSwitchBadge(dash),
                          const SizedBox(height: 80),
                        ],
                      ),
                    ),
        );
      },
    );
  }

  Widget _buildError(DashboardProvider dash) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.cloud_off, size: 64, color: TsarTheme.loss),
          const SizedBox(height: 16),
          Text('Connection Error', style: TsarTheme.darkTheme.textTheme.titleLarge),
          const SizedBox(height: 8),
          Text(dash.error!, style: const TextStyle(color: Colors.white54), textAlign: TextAlign.center),
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: dash.refresh,
            icon: const Icon(Icons.refresh),
            label: const Text('RETRY'),
            style: ElevatedButton.styleFrom(backgroundColor: TsarTheme.accent),
          ),
        ],
      ),
    );
  }

  Widget _buildPnlHero(DashboardProvider dash) {
    final pnl = dash.pnl;
    final dailyPnl = pnl?.dailyPnl ?? 0;
    final totalPnl = pnl?.totalPnl ?? 0;
    final isPositive = dailyPnl >= 0;

    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            TsarTheme.card,
            isPositive
                ? TsarTheme.profit.withOpacity(0.08)
                : TsarTheme.loss.withOpacity(0.08),
          ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: isPositive
              ? TsarTheme.profit.withOpacity(0.3)
              : TsarTheme.loss.withOpacity(0.3),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text('DAILY P&L', style: TextStyle(color: Colors.white54, fontSize: 12, fontFamily: 'JetBrains Mono')),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: isPositive ? TsarTheme.profit.withOpacity(0.15) : TsarTheme.loss.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${isPositive ? '+' : ''}${(pnl?.dailyReturn ?? 0).toStringAsFixed(2)}%',
                  style: TsarTheme.pnlStyle(dailyPnl).copyWith(fontSize: 13),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '${isPositive ? '+' : ''}\$${dailyPnl.toStringAsFixed(2)}',
            style: TsarTheme.pnlLarge(dailyPnl).copyWith(fontSize: 36),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _buildMiniPnl('Weekly', pnl?.weeklyPnl ?? 0),
              const SizedBox(width: 24),
              _buildMiniPnl('Monthly', pnl?.monthlyPnl ?? 0),
              const Spacer(),
              _buildMiniPnl('Total', totalPnl),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildMiniPnl(String label, double value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: Colors.white38, fontSize: 10)),
        const SizedBox(height: 2),
        Text(
          '${value >= 0 ? '+' : ''}\$${value.toStringAsFixed(2)}',
          style: TsarTheme.pnlStyle(value).copyWith(fontSize: 14),
        ),
      ],
    );
  }

  Widget _buildStatsGrid(DashboardProvider dash) {
    final stats = dash.stats;
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      childAspectRatio: 2.2,
      mainAxisSpacing: 10,
      crossAxisSpacing: 10,
      children: [
        _buildStatCard('Win Rate', '${((stats?.winRate ?? 0) * 100).toStringAsFixed(1)}%', TsarTheme.profit, Icons.trending_up),
        _buildStatCard('Trades', '${stats?.totalTrades ?? 0}', TsarTheme.info, Icons.swap_horiz),
        _buildStatCard('Open Pos', '${dash.openPositions}', TsarTheme.warning, Icons.account_balance),
        _buildStatCard('Profit Factor', (stats?.profitFactor ?? 0).toStringAsFixed(2), TsarTheme.accent, Icons.analytics),
      ],
    );
  }

  Widget _buildStatCard(String label, String value, Color color, IconData icon) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: TsarTheme.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TsarTheme.cardBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Row(
            children: [
              Text(label, style: const TextStyle(color: Colors.white54, fontSize: 11)),
              const Spacer(),
              Icon(icon, color: color.withOpacity(0.6), size: 16),
            ],
          ),
          const SizedBox(height: 4),
          Text(value, style: TsarTheme.numberStyle.copyWith(fontSize: 20, color: color)),
        ],
      ),
    );
  }

  Widget _buildRegimeCard(DashboardProvider dash) {
    final regime = dash.regime;
    final regimeName = regime?.currentRegime ?? 'unknown';
    final confidence = regime?.confidence ?? 0;
    Color regimeColor;
    IconData regimeIcon;
    switch (regimeName.toLowerCase()) {
      case 'bull':
      case 'bullish':
        regimeColor = TsarTheme.profit;
        regimeIcon = Icons.trending_up;
        break;
      case 'bear':
      case 'bearish':
        regimeColor = TsarTheme.loss;
        regimeIcon = Icons.trending_down;
        break;
      default:
        regimeColor = TsarTheme.warning;
        regimeIcon = Icons.trending_flat;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TsarTheme.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TsarTheme.cardBorder),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: regimeColor.withOpacity(0.15),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(regimeIcon, color: regimeColor, size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('MARKET REGIME', style: TextStyle(color: Colors.white54, fontSize: 11)),
                const SizedBox(height: 4),
                Text(
                  regimeName.toUpperCase(),
                  style: TsarTheme.numberStyle.copyWith(fontSize: 22, color: regimeColor),
                ),
                if (regime?.description.isNotEmpty == true)
                  Text(regime!.description, style: const TextStyle(color: Colors.white38, fontSize: 11)),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Text('Confidence', style: TextStyle(color: Colors.white38, fontSize: 10)),
              const SizedBox(height: 4),
              Text(
                '${(confidence * 100).toStringAsFixed(0)}%',
                style: TsarTheme.numberStyle.copyWith(fontSize: 18, color: regimeColor),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildFlywheelCard(DashboardProvider dash) {
    final fw = dash.flywheel;
    final status = fw?.status ?? 'unknown';
    final score = fw?.score ?? 0;
    final Color statusColor = status == 'ok' || status == 'healthy'
        ? TsarTheme.profit
        : status == 'warning'
            ? TsarTheme.warning
            : TsarTheme.loss;

    return Container(
      padding: const EdgeInsets.all(16),
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
              const Icon(Icons.sync, color: TsarTheme.accent, size: 20),
              const SizedBox(width: 8),
              const Text('FLYWHEEL HEALTH', style: TextStyle(color: Colors.white54, fontSize: 11)),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: statusColor.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(status.toUpperCase(), style: TextStyle(color: statusColor, fontSize: 11, fontWeight: FontWeight.w600)),
              ),
            ],
          ),
          const SizedBox(height: 12),
          LinearProgressIndicator(
            value: score.clamp(0, 1),
            backgroundColor: Colors.white10,
            valueColor: AlwaysStoppedAnimation(statusColor),
            minHeight: 6,
            borderRadius: BorderRadius.circular(3),
          ),
          const SizedBox(height: 8),
          Text('${(score * 100).toStringAsFixed(0)}% — TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT',
              style: const TextStyle(color: Colors.white38, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _buildKillSwitchBadge(DashboardProvider dash) {
    final isActive = dash.killSwitchActive;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: isActive ? TsarTheme.loss.withOpacity(0.1) : TsarTheme.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isActive ? TsarTheme.loss.withOpacity(0.5) : TsarTheme.cardBorder,
        ),
      ),
      child: Row(
        children: [
          Icon(
            isActive ? Icons.warning_amber : Icons.shield_outlined,
            color: isActive ? TsarTheme.loss : TsarTheme.profit,
            size: 24,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('KILL SWITCH', style: TextStyle(color: Colors.white54, fontSize: 11)),
                const SizedBox(height: 2),
                Text(
                  isActive ? 'ACTIVE — TRADING HALTED' : 'INACTIVE — SYSTEM NORMAL',
                  style: TextStyle(
                    color: isActive ? TsarTheme.loss : TsarTheme.profit,
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    fontFamily: 'JetBrains Mono',
                  ),
                ),
              ],
            ),
          ),
          Container(
            width: 12,
            height: 12,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isActive ? TsarTheme.loss : TsarTheme.profit,
              boxShadow: isActive
                  ? [BoxShadow(color: TsarTheme.loss.withOpacity(0.6), blurRadius: 8)]
                  : null,
            ),
          ),
        ],
      ),
    );
  }
}
