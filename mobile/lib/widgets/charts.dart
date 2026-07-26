import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';

class PnlLineChart extends StatelessWidget {
  final List<FlSpot> spots;
  final double? minY;
  final double? maxY;
  final bool showGradient;
  final double height;

  const PnlLineChart({
    super.key,
    required this.spots,
    this.minY,
    this.maxY,
    this.showGradient = true,
    this.height = 200,
  });

  @override
  Widget build(BuildContext context) {
    if (spots.isEmpty) {
      return SizedBox(
        height: height,
        child: const Center(
          child: Text('No data', style: TextStyle(color: Colors.white24)),
        ),
      );
    }

    final isPositive = spots.last.y >= spots.first.y;
    final lineColor = isPositive ? TsarTheme.profit : TsarTheme.loss;

    return SizedBox(
      height: height,
      child: LineChart(
        LineChartData(
          minY: minY,
          maxY: maxY,
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            horizontalInterval: 1,
            getDrawingHorizontalLine: (_) =>
                FlLine(color: Colors.white.withOpacity(0.05), strokeWidth: 1),
          ),
          titlesData: const FlTitlesData(show: false),
          borderData: FlBorderData(show: false),
          lineBarsData: [
            LineChartBarData(
              spots: spots,
              isCurved: true,
              color: lineColor,
              barWidth: 2,
              isStrokeCapRound: true,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: showGradient,
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    lineColor.withOpacity(0.3),
                    lineColor.withOpacity(0.0),
                  ],
                ),
              ),
            ),
          ],
          lineTouchData: LineTouchData(
            touchTooltipData: LineTouchTooltipData(
              getTooltipItems: (spots) => spots
                  .map((s) => LineTooltipItem(
                        s.y.toStringAsFixed(2),
                        TsarTheme.numberStyle.copyWith(fontSize: 12),
                      ))
                  .toList(),
            ),
          ),
        ),
      ),
    );
  }
}

class RiskGauge extends StatelessWidget {
  final double value; // 0.0 - 1.0
  final String label;
  final double size;

  const RiskGauge({
    super.key,
    required this.value,
    required this.label,
    this.size = 120,
  });

  @override
  Widget build(BuildContext context) {
    final clamped = value.clamp(0.0, 1.0);
    final color = clamped < 0.5
        ? TsarTheme.profit
        : clamped < 0.8
            ? TsarTheme.warning
            : TsarTheme.loss;

    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          SizedBox(
            width: size,
            height: size,
            child: CircularProgressIndicator(
              value: clamped,
              strokeWidth: 8,
              backgroundColor: Colors.white.withOpacity(0.08),
              valueColor: AlwaysStoppedAnimation(color),
              strokeCap: StrokeCap.round,
            ),
          ),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${(clamped * 100).toInt()}%',
                style: TsarTheme.numberStyle.copyWith(
                  fontSize: 20,
                  color: color,
                ),
              ),
              Text(
                label,
                style: const TextStyle(fontSize: 10, color: Colors.white38),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class MiniBarChart extends StatelessWidget {
  final List<double> values;
  final double height;
  final Color? color;

  const MiniBarChart({
    super.key,
    required this.values,
    this.height = 40,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) return SizedBox(height: height);

    final maxVal = values.reduce((a, b) => a.abs() > b.abs() ? a : b).abs();
    if (maxVal == 0) return SizedBox(height: height);

    return SizedBox(
      height: height,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: values.map((v) {
          final normalized = (v.abs() / maxVal * height).clamp(2.0, height);
          final barColor = v >= 0
              ? (color ?? TsarTheme.profit)
              : TsarTheme.loss;
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 1),
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Container(
                  height: normalized,
                  decoration: BoxDecoration(
                    color: barColor.withOpacity(0.7),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}
