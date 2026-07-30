import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme.dart';

/// OHLC candlestick chart using fl_chart.
///
/// Renders candle bodies and wicks for financial price data.
/// Each candle represents open/high/low/close for a time period.
class CandlestickChart extends StatelessWidget {
  final List<CandleData> candles;
  final double height;
  final bool showVolume;

  const CandlestickChart({
    super.key,
    required this.candles,
    this.height = 300,
    this.showVolume = false,
  });

  @override
  Widget build(BuildContext context) {
    if (candles.isEmpty) {
      return SizedBox(
        height: height,
        child: const Center(
          child: Text('No candle data', style: TextStyle(color: Colors.white24)),
        ),
      );
    }

    // Calculate bounds
    double minY = double.infinity;
    double maxY = double.negativeInfinity;
    for (final c in candles) {
      if (c.low < minY) minY = c.low;
      if (c.high > maxY) maxY = c.high;
    }
    final padding = (maxY - minY) * 0.1;
    minY -= padding;
    maxY += padding;

    return SizedBox(
      height: height,
      child: Padding(
        padding: const EdgeInsets.only(right: 8),
        child: CustomPaint(
          size: Size.infinite,
          painter: _CandlestickPainter(
            candles: candles,
            minY: minY,
            maxY: maxY,
            bullishColor: TsarTheme.profit,
            bearishColor: TsarTheme.loss,
          ),
        ),
      ),
    );
  }
}

class CandleData {
  final double open;
  final double high;
  final double low;
  final double close;
  final double? volume;

  CandleData({
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    this.volume,
  });

  bool get isBullish => close >= open;
  Color get color => isBullish ? TsarTheme.profit : TsarTheme.loss;
}

class _CandlestickPainter extends CustomPainter {
  final List<CandleData> candles;
  final double minY;
  final double maxY;
  final Color bullishColor;
  final Color bearishColor;

  _CandlestickPainter({
    required this.candles,
    required this.minY,
    required this.maxY,
    required this.bullishColor,
    required this.bearishColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (candles.isEmpty) return;

    final chartHeight = size.height - 20; // Bottom padding for labels
    final chartWidth = size.width;
    final candleWidth = (chartWidth / candles.length).clamp(4.0, 20.0);
    final bodyWidth = candleWidth * 0.7;
    final range = maxY - minY;
    if (range == 0) return;

    for (var i = 0; i < candles.length; i++) {
      final candle = candles[i];
      final x = (i + 0.5) * (chartWidth / candles.length);
      final color = candle.isBullish ? bullishColor : bearishColor;

      // Y coordinates (inverted: 0 = top)
      double yFromPrice(double price) {
        return chartHeight * (1 - (price - minY) / range);
      }

      // Draw wick (thin line from high to low)
      final wickPaint = Paint()
        ..color = color
        ..strokeWidth = 1.5;
      canvas.drawLine(
        Offset(x, yFromPrice(candle.high)),
        Offset(x, yFromPrice(candle.low)),
        wickPaint,
      );

      // Draw body (rectangle from open to close)
      final bodyTop = yFromPrice(candle.open > candle.close ? candle.open : candle.close);
      final bodyBottom = yFromPrice(candle.open > candle.close ? candle.close : candle.open);
      final bodyHeight = (bodyBottom - bodyTop).clamp(1.0, chartHeight);

      final bodyPaint = Paint()
        ..color = color
        ..style = PaintingStyle.fill;

      final rect = RRect.fromRectAndRadius(
        Rect.fromCenter(
          center: Offset(x, bodyTop + bodyHeight / 2),
          width: bodyWidth,
          height: bodyHeight,
        ),
        const Radius.circular(1),
      );
      canvas.drawRRect(rect, bodyPaint);

      // Draw border for hollow candles (bearish in some styles)
      if (!candle.isBullish) {
        final borderPaint = Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1;
        canvas.drawRRect(rect, borderPaint);
      }
    }

    // Draw price labels on right side
    final labelPaint = TextPainter(
      textDirection: TextDirection.ltr,
    );
    final steps = 5;
    for (var i = 0; i <= steps; i++) {
      final price = minY + (range * i / steps);
      final y = chartHeight * (1 - i / steps);
      labelPaint.text = TextSpan(
        text: price.toStringAsFixed(2),
        style: TextStyle(
          color: Colors.white24,
          fontSize: 10,
        ),
      );
      labelPaint.layout();
      labelPaint.paint(canvas, Offset(chartWidth - labelPaint.width - 4, y - 6));
    }
  }

  @override
  bool shouldRepaint(covariant _CandlestickPainter oldDelegate) {
    return oldDelegate.candles != candles;
  }
}
