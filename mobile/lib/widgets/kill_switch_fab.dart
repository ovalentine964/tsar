import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import 'package:provider/provider.dart';
import '../theme.dart';
import '../providers/risk_provider.dart';

class KillSwitchFab extends StatefulWidget {
  const KillSwitchFab({super.key});

  @override
  State<KillSwitchFab> createState() => _KillSwitchFabState();
}

class _KillSwitchFabState extends State<KillSwitchFab>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<RiskProvider>(
      builder: (context, risk, _) {
        final isActive = risk.riskState?.killSwitchActive ?? false;

        return AnimatedBuilder(
          animation: _pulseController,
          builder: (context, child) {
            final glow = isActive ? 0.8 : _pulseController.value * 0.3;
            return Container(
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: TsarTheme.killSwitch.withOpacity(glow),
                    blurRadius: 20,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: child,
            );
          },
          child: FloatingActionButton(
            onPressed: () => _handleKillSwitch(context, isActive),
            backgroundColor:
                isActive ? Colors.grey.shade800 : TsarTheme.killSwitch,
            child: Icon(
              isActive ? Icons.play_arrow : Icons.power_settings_new,
              color: Colors.white,
              size: 28,
            ),
          ),
        );
      },
    );
  }

  Future<void> _handleKillSwitch(BuildContext context, bool isActive) async {
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

    // Final confirmation
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: TsarTheme.surfaceVariant,
        title: const Row(
          children: [
            Icon(Icons.warning, color: TsarTheme.killSwitch),
            SizedBox(width: 8),
            Text('KILL SWITCH'),
          ],
        ),
        content: const Text(
          'This will immediately halt ALL trading activity. '
          'All open positions will be preserved but no new trades will execute.\n\n'
          'Are you sure?',
          style: TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('CANCEL'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: TsarTheme.killSwitch,
            ),
            child: const Text('ACTIVATE',
                style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );

    if (confirmed == true && context.mounted) {
      final success = await context
          .read<RiskProvider>()
          .activateKillSwitch(reason: 'Manual activation via mobile app');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              success ? 'Kill switch ACTIVATED' : 'Failed to activate kill switch',
            ),
            backgroundColor: success ? TsarTheme.killSwitch : Colors.grey,
          ),
        );
      }
    }
  }

  Future<void> _showDeactivateDialog(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: TsarTheme.surfaceVariant,
        title: const Text('Resume Trading?'),
        content: const Text(
          'This will deactivate the kill switch and resume normal trading operations.',
          style: TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('CANCEL'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: TsarTheme.profit),
            child: const Text('RESUME'),
          ),
        ],
      ),
    );

    if (confirmed == true && context.mounted) {
      await context.read<RiskProvider>().deactivateKillSwitch();
    }
  }

  Future<bool> _showPinDialog(BuildContext context) async {
    final controller = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: TsarTheme.surfaceVariant,
        title: const Text('Enter PIN'),
        content: TextField(
          controller: controller,
          obscureText: true,
          keyboardType: TextInputType.number,
          maxLength: 6,
          decoration: const InputDecoration(
            hintText: '6-digit PIN',
            counterText: '',
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('CANCEL'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, controller.text.length >= 4),
            child: const Text('CONFIRM'),
          ),
        ],
      ),
    );
    return result ?? false;
  }
}
