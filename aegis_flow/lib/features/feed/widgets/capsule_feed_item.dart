import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../../core/data/observation_capsule.dart';
import '../../../ui/core/theme.dart';
import 'capsule_detail_sheet.dart';

class CapsuleFeedItem extends StatelessWidget {
  final ObservationCapsule capsule;

  const CapsuleFeedItem({
    super.key,
    required this.capsule,
  });

  void _showDetail(BuildContext context) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AegisTheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => CapsuleDetailSheet(capsule: capsule),
    );
  }

  static const _untagged = 'Untagged';

  @override
  Widget build(BuildContext context) {
    final timeStr = DateFormat('HH:mm').format(capsule.observedAt);
    final rawTag = capsule.facts.isNotEmpty ? capsule.facts.first.assetTag : null;
    final hasTag = rawTag != null && rawTag.trim().isNotEmpty;
    final tag = hasTag ? rawTag : _untagged;
    final state = capsule.facts.isNotEmpty ? capsule.facts.first.assertedState.name : 'Unknown';
    final flagged = capsule.serverFlags.isNotEmpty;
    final isAlert = flagged || capsule.escalation.level > 0 || capsule.discrepancyAlert != null;
    final critical = flagged || capsule.escalation.level >= 2;
    final accent = critical ? AegisTheme.alertRed : AegisTheme.amberAccent;
    final alertReason = flagged
        ? (capsule.serverFlags.first['title']?.toString() ?? 'Safety conflict flagged by the server')
        : (capsule.escalation.reasons.isNotEmpty ? capsule.escalation.reasons.first : (capsule.discrepancyAlert ?? 'Discrepancy detected'));
    final syncLabel = capsule.isSynced ? 'Synced' : 'Waiting to sync';

    return Semantics(
      button: true,
      label: '$tag, $state, $timeStr. ${isAlert ? (flagged ? "Server flagged a safety conflict. " : "Alert. ") : ""}$syncLabel. ${capsule.transcript}',
      excludeSemantics: true,
      child: GestureDetector(
        onTap: () => _showDetail(context),
        child: Container(
          decoration: BoxDecoration(
            color: AegisTheme.surfaceVariant,
            borderRadius: BorderRadius.circular(16),
          ),
          clipBehavior: Clip.antiAlias,
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (isAlert) Container(width: 4, color: accent),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            // The chip may shrink and ellipsize: a long spoken name must never push the time off the card.
                            Flexible(
                              child: Container(
                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                decoration: BoxDecoration(
                                  color: AegisTheme.surface,
                                  borderRadius: BorderRadius.circular(8),
                                  border: hasTag ? null : Border.all(color: AegisTheme.cardBorder),
                                ),
                                child: Text(
                                  tag,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    fontFamily: hasTag ? 'monospace' : null,
                                    fontSize: 12,
                                    fontWeight: FontWeight.bold,
                                    fontStyle: hasTag ? FontStyle.normal : FontStyle.italic,
                                    color: hasTag ? AegisTheme.amberAccent : AegisTheme.textSecondary,
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              state,
                              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AegisTheme.textPrimary),
                            ),
                            const Spacer(),
                            const SizedBox(width: 8),
                            Text(timeStr, style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted)),
                            const SizedBox(width: 6),
                            Icon(
                              capsule.isSynced ? Icons.cloud_done : Icons.cloud_off,
                              size: 14,
                              color: capsule.isSynced ? AegisTheme.successGreen : AegisTheme.amberAccent,
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          capsule.transcript,
                          maxLines: 4,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 13, height: 1.3, fontWeight: FontWeight.w600, color: AegisTheme.textPrimary),
                        ),
                        if (isAlert) ...[
                          const SizedBox(height: 8),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(Icons.warning_amber_rounded, size: 14, color: accent),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  flagged ? 'Server flagged: $alertReason' : alertReason,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: accent),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
