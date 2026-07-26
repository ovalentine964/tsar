import 'package:google_fonts/google_fonts.dart';
import 'package:flutter/material.dart';
import '../theme.dart';

class TsarCard extends StatelessWidget {
  final String? title;
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final VoidCallback? onTap;
  final Widget? trailing;
  final Color? borderColor;

  const TsarCard({
    super.key,
    this.title,
    required this.child,
    this.padding,
    this.onTap,
    this.trailing,
    this.borderColor,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: borderColor ?? TsarTheme.cardBorder,
          width: 1,
        ),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: padding ?? const EdgeInsets.all(16),
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
      ),
    );
  }
}

class StatTile extends StatelessWidget {
  final String label;
  final String value;
  final TextStyle? valueStyle;
  final IconData? icon;
  final Color? iconColor;

  const StatTile({
    super.key,
    required this.label,
    required this.value,
    this.valueStyle,
    this.icon,
    this.iconColor,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            if (icon != null) ...[
              Icon(icon, size: 14, color: iconColor ?? Colors.white38),
              const SizedBox(width: 4),
            ],
            Text(
              label,
              style: const TextStyle(
                fontSize: 11,
                color: Colors.white38,
                letterSpacing: 0.5,
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(value, style: valueStyle ?? TsarTheme.numberStyle),
      ],
    );
  }
}

class PnlBadge extends StatelessWidget {
  final double value;
  final bool large;

  const PnlBadge({super.key, required this.value, this.large = false});

  @override
  Widget build(BuildContext context) {
    final color = value >= 0 ? TsarTheme.profit : TsarTheme.loss;
    final prefix = value >= 0 ? '+' : '';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        '$prefix${value.toStringAsFixed(2)}%',
        style: TextStyle(
          fontFamily: GoogleFonts.jetBrainsMono().fontFamily,
          fontSize: large ? 16 : 12,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

class StatusDot extends StatelessWidget {
  final String status;
  final double size;

  const StatusDot({super.key, required this.status, this.size = 8});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: _color,
        boxShadow: [BoxShadow(color: _color.withOpacity(0.5), blurRadius: 4)],
      ),
    );
  }

  Color get _color {
    switch (status.toLowerCase()) {
      case 'active':
      case 'open':
      case 'healthy':
        return TsarTheme.profit;
      case 'warning':
        return TsarTheme.warning;
      case 'critical':
      case 'halted':
      case 'error':
        return TsarTheme.loss;
      default:
        return Colors.grey;
    }
  }
}

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;

  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 48, color: Colors.white12),
          const SizedBox(height: 16),
          Text(title, style: const TextStyle(color: Colors.white38, fontSize: 16)),
          if (subtitle != null) ...[
            const SizedBox(height: 8),
            Text(subtitle!, style: const TextStyle(color: Colors.white24, fontSize: 13)),
          ],
        ],
      ),
    );
  }
}

class ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;

  const ErrorBanner({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      margin: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TsarTheme.loss.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: TsarTheme.loss.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, color: TsarTheme.loss, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Text(message, style: const TextStyle(color: Colors.white70, fontSize: 13)),
          ),
          if (onRetry != null)
            TextButton(
              onPressed: onRetry,
              child: Text('RETRY', style: TextStyle(fontFamily: GoogleFonts.jetBrainsMono().fontFamily, fontSize: 12)),
            ),
        ],
      ),
    );
  }
}

class LoadingOverlay extends StatelessWidget {
  final bool loading;
  final Widget child;

  const LoadingOverlay({super.key, required this.loading, required this.child});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        child,
        if (loading)
          Container(
            color: Colors.black26,
            child: const Center(
              child: CircularProgressIndicator(color: TsarTheme.accent),
            ),
          ),
      ],
    );
  }
}
