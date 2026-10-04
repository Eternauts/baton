import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../theme.dart';

/// Top header for industrial offshore tablet
class IndustrialHeader extends StatelessWidget implements PreferredSizeWidget {
  final bool isOffline;
  final VoidCallback onToggleOffline;

  const IndustrialHeader({
    super.key,
    required this.isOffline,
    required this.onToggleOffline,
  });

  @override
  Size get preferredSize => const Size.fromHeight(68);

  @override
  Widget build(BuildContext context) {
    final timeStr = DateFormat('HH:mm').format(DateTime.now());

    return Container(
      color: AegisTheme.surface,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: SafeArea(
        child: Row(
          children: [
            // Aegis Flow Logo / Badge
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: AegisTheme.safetyOrange.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AegisTheme.safetyOrange.withValues(alpha: 0.4)),
              ),
              child: const Icon(
                Icons.shield_outlined,
                color: AegisTheme.safetyOrange,
                size: 22,
              ),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Row(
                  children: [
                    const Text(
                      'AEGIS ',
                      style: TextStyle(
                        fontWeight: FontWeight.w900,
                        fontSize: 16,
                        letterSpacing: 1.1,
                        color: AegisTheme.textPrimary,
                      ),
                    ),
                    Text(
                      'Flow',
                      style: TextStyle(
                        fontWeight: FontWeight.w900,
                        fontSize: 16,
                        letterSpacing: 1.1,
                        color: AegisTheme.industrialCyan,
                      ),
                    ),
                  ],
                ),
                Text(
                  'ATEX Zone 2 • Gemma 2B Edge',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w500,
                    color: AegisTheme.textMuted,
                  ),
                ),
              ],
            ),
            const Spacer(),
            // Network Connectivity Toggle Badge
            InkWell(
              onTap: onToggleOffline,
              borderRadius: BorderRadius.circular(20),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: isOffline
                      ? AegisTheme.amberWarning.withValues(alpha: 0.15)
                      : AegisTheme.successGreen.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: isOffline ? AegisTheme.amberWarning : AegisTheme.successGreen,
                    width: 1,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      isOffline ? Icons.cloud_off : Icons.cloud_done,
                      color: isOffline ? AegisTheme.amberWarning : AegisTheme.successGreen,
                      size: 14,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      isOffline ? 'OFFLINE' : 'ONLINE',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: isOffline ? AegisTheme.amberWarning : AegisTheme.successGreen,
                        letterSpacing: 0.5,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 10),
            // Rig Local Time
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
              decoration: BoxDecoration(
                color: AegisTheme.surfaceVariant,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: AegisTheme.cardBorder),
              ),
              child: Row(
                children: [
                  const Icon(Icons.access_time, size: 13, color: AegisTheme.textSecondary),
                  const SizedBox(width: 4),
                  Text(
                    timeStr,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AegisTheme.textPrimary,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
