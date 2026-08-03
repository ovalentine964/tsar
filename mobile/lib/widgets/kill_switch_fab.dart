import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../providers/risk_provider.dart';

// ═══════════════════════════════════════════════════════════════════════════
// Kill Switch FAB — Prominent, Animated, Secure
// ═══════════════════════════════════════════════════════════════════════════

class KillSwitchFab extends StatefulWidget {
  const KillSwitchFab({super.key});

  /// Static helper so the app bar can trigger the same kill switch flow.
  static Future<void> activateFromAppBar(BuildContext context) async {
    final risk = context.read<RiskProvider>();
    final isActive = risk.riskState?.killSwitchActive ?? false;
    await _KillSwitchFabState._handleKillSwitchStatic(context, isActive);
  }

  @override
  State<KillSwitchFab> createState() => _KillSwitchFabState();
}

class _KillSwitchFabState extends State<KillSwitchFab>
    with TickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;
  late AnimationController _scaleController;
  late Animation<double> _scaleAnimation;

  @override
  void initState() {
    super.initState();

    // Pulse glow animation (repeating, slows when inactive)
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    );
    _pulseAnimation = Tween<double>(begin: 0.2, end: 0.9).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    _pulseController.repeat(reverse: true);

    // Press scale animation
    _scaleController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 100),
      reverseDuration: const Duration(milliseconds: 200),
    );
    _scaleAnimation = Tween<double>(begin: 1.0, end: 0.88).animate(
      CurvedAnimation(parent: _scaleController, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _scaleController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final isActive = risk.riskState?.killSwitchActive ?? false;

        // Speed up pulse when kill switch is active
        if (isActive && _pulseController.duration != const Duration(milliseconds: 800)) {
          _pulseController.duration = const Duration(milliseconds: 800);
        } else if (!isActive && _pulseController.duration != const Duration(milliseconds: 1500)) {
          _pulseController.duration = const Duration(milliseconds: 1500);
        }

        return Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            // Main FAB with pulse glow
            AnimatedBuilder(
              animation: _pulseAnimation,
              builder: (context, child) {
                final glow = isActive ? _pulseAnimation.value : _pulseAnimation.value * 0.3;
                return Container(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: TsarTheme.killSwitch.withOpacity(glow * 0.6),
                        blurRadius: isActive ? 28 : 18,
                        spreadRadius: isActive ? 4 : 1,
                      ),
                      if (isActive)
                        BoxShadow(
                          color: TsarTheme.killSwitch.withOpacity(glow * 0.3),
                          blurRadius: 48,
                          spreadRadius: 8,
                        ),
                    ],
                  ),
                  child: ScaleTransition(
                    scale: _scaleAnimation,
                    child: child,
                  ),
                );
              },
              child: GestureDetector(
                onTapDown: (_) => _scaleController.forward(),
                onTapUp: (_) => _scaleController.reverse(),
                onTapCancel: () => _scaleController.reverse(),
                child: FloatingActionButton(
                  onPressed: () {
                    HapticFeedback.heavyImpact();
                    _handleKillSwitch(context, isActive);
                  },
                  backgroundColor:
                      isActive ? TsarTheme.surface : TsarTheme.killSwitch,
                  elevation: 0,
                  highlightElevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Container(
                    width: 56,
                    height: 56,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(16),
                      gradient: isActive
                          ? LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: [
                                Colors.grey.shade700,
                                Colors.grey.shade900,
                              ],
                            )
                          : const LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: [
                                Color(0xFFFF1744),
                                Color(0xFFD50000),
                              ],
                            ),
                    ),
                    child: Icon(
                      isActive ? Icons.play_arrow_rounded : Icons.power_settings_new_rounded,
                      color: Colors.white,
                      size: 28,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            // Status label below FAB
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 300),
              child: Text(
                isActive ? 'HALTED' : 'KILL',
                key: ValueKey(isActive),
                style: TsarTheme.numberSmall.copyWith(
                  color: isActive ? TsarTheme.statusRed : TsarTheme.muted,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.5,
                  fontSize: 10,
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  // ── Instance method delegates to static ────────────────────────────

  Future<void> _handleKillSwitch(BuildContext context, bool isActive) async {
    await _handleKillSwitchStatic(context, isActive);
  }

  // ── Static Kill Switch Logic (shared with app bar) ─────────────────

  static Future<void> _handleKillSwitchStatic(
    BuildContext context,
    bool isActive,
  ) async {
    if (isActive) {
      _showDeactivateDialog(context);
      return;
    }

    // Biometric confirmation for activation
    final auth = LocalAuthentication();
    bool authenticated = false;
    try {
      authenticated = await auth.authenticate(
        localizedReason: 'Authenticate to activate kill switch',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: true,
        ),
      );
    } catch (_) {
      // Biometric not available, show PIN dialog
      authenticated = await _showPinDialog(context);
    }

    if (!authenticated || !context.mounted) return;

    // Final confirmation dialog
    final confirmed = await showDialog<bool>(
      context: context,
      barrierColor: Colors.black87,
      builder: (ctx) => AlertDialog(
        backgroundColor: TsarTheme.surfaceVariant,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: TsarTheme.cardBorder),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: TsarTheme.killSwitch.withOpacity(0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.warning_amber_rounded, color: TsarTheme.killSwitch, size: 24),
            ),
            const SizedBox(width: 12),
            Text(
              'KILL SWITCH',
              style: TsarTheme.interStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: TsarTheme.killSwitch,
                letterSpacing: 1,
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'This will immediately halt ALL trading activity.',
              style: TsarTheme.bodyMedium.copyWith(color: Colors.white70),
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: TsarTheme.warning.withOpacity(0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: TsarTheme.warning.withOpacity(0.2)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.info_outline, color: TsarTheme.warning, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Open positions will be preserved. No new trades will execute.',
                      style: TsarTheme.bodySmall.copyWith(color: TsarTheme.warning),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Are you sure?',
              style: TsarTheme.interStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(
              'CANCEL',
              style: TsarTheme.labelMedium.copyWith(color: Colors.white54),
            ),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: TsarTheme.killSwitch,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            ),
            child: Text(
              'ACTIVATE',
              style: TsarTheme.interStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );

    if (confirmed == true && context.mounted) {
      HapticFeedback.heavyImpact();
      final success = await context
          .read<RiskProvider>()
          .activateKillSwitch(reason: 'Manual activation via mobile app');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: [
                Icon(
                  success ? Icons.check_circle : Icons.error_outline,
                  color: Colors.white,
                  size: 18,
                ),
                const SizedBox(width: 8),
                Text(
                  success ? 'Kill switch ACTIVATED' : 'Failed to activate kill switch',
                ),
              ],
            ),
            backgroundColor: success ? TsarTheme.killSwitch : Colors.grey.shade800,
            duration: const Duration(seconds: 3),
          ),
        );
      }
    }
  }

  // ── Deactivate Dialog ──────────────────────────────────────────────

  static Future<void> _showDeactivateDialog(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      barrierColor: Colors.black87,
      builder: (ctx) => AlertDialog(
        backgroundColor: TsarTheme.surfaceVariant,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: TsarTheme.cardBorder),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: TsarTheme.profit.withOpacity(0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.play_circle_outline, color: TsarTheme.profit, size: 24),
            ),
            const SizedBox(width: 12),
            Text(
              'Resume Trading?',
              style: TsarTheme.interStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ],
        ),
        content: Text(
          'This will deactivate the kill switch and resume normal trading operations.',
          style: TsarTheme.bodyMedium.copyWith(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(
              'CANCEL',
              style: TsarTheme.labelMedium.copyWith(color: Colors.white54),
            ),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: TsarTheme.profit,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            ),
            child: Text(
              'RESUME',
              style: TsarTheme.interStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );

    if (confirmed == true && context.mounted) {
      HapticFeedback.mediumImpact();
      await context.read<RiskProvider>().deactivateKillSwitch();
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Row(
              children: [
                Icon(Icons.check_circle, color: Colors.white, size: 18),
                SizedBox(width: 8),
                Text('Trading resumed'),
              ],
            ),
            backgroundColor: TsarTheme.profit,
            duration: const Duration(seconds: 2),
          ),
        );
      }
    }
  }

  // ── PIN Fallback ───────────────────────────────────────────────────

  static Future<bool> _showPinDialog(BuildContext context) async {
    final controller = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      barrierColor: Colors.black87,
      builder: (ctx) => AlertDialog(
        backgroundColor: TsarTheme.surfaceVariant,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: TsarTheme.cardBorder),
        ),
        title: Text(
          'Enter PIN',
          style: TsarTheme.interStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: Colors.white,
          ),
        ),
        content: TextField(
          controller: controller,
          obscureText: true,
          keyboardType: TextInputType.number,
          maxLength: 6,
          style: TsarTheme.numberStyle.copyWith(letterSpacing: 8, fontSize: 20),
          textAlign: TextAlign.center,
          decoration: InputDecoration(
            hintText: '······',
            hintStyle: TextStyle(color: Colors.white24, letterSpacing: 8),
            filled: true,
            fillColor: Colors.black26,
            counterText: '',
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
            ),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(
              'CANCEL',
              style: TsarTheme.labelMedium.copyWith(color: Colors.white54),
            ),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, controller.text.length >= 4),
            style: ElevatedButton.styleFrom(
              backgroundColor: TsarTheme.accent,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: Text(
              'CONFIRM',
              style: TsarTheme.interStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
    return result ?? false;
  }
}
