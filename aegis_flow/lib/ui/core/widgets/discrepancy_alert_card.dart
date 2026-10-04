import 'package:flutter/material.dart';
import '../theme.dart';

/// Warning banner highlighting SCADA vs field log discrepancies
class DiscrepancyAlertCard extends StatelessWidget {
  final String title;
  final String description;
  final VoidCallback? onReview;

  const DiscrepancyAlertCard({
    super.key,
    required this.title,
    required this.description,
    this.onReview,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF2A1517),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AegisTheme.alertRed.withValues(alpha: 0.6), width: 1.2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AegisTheme.alertRed.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Icon(
                  Icons.warning_amber_rounded,
                  color: AegisTheme.alertRed,
                  size: 20,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: AegisTheme.alertRed,
                    letterSpacing: 0.3,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            description,
            style: const TextStyle(
              fontSize: 13,
              height: 1.4,
              color: AegisTheme.textPrimary,
            ),
          ),
          if (onReview != null) ...[
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: onReview,
                style: TextButton.styleFrom(
                  foregroundColor: AegisTheme.amberWarning,
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                ),
                icon: const Icon(Icons.arrow_forward, size: 15),
                label: const Text(
                  'Review Cross-Check',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
