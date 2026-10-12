import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../../core/data/observation_capsule.dart';
import '../../../ui/core/theme.dart';

class CapsuleDetailSheet extends StatelessWidget {
  final ObservationCapsule capsule;

  const CapsuleDetailSheet({
    super.key,
    required this.capsule,
  });

  TextSpan _buildHighlightedTranscript(String transcript, List<String> quotes) {
    if (quotes.isEmpty || transcript.isEmpty) {
      return TextSpan(text: transcript, style: const TextStyle(color: AegisTheme.textPrimary, fontSize: 14));
    }

    final spans = <TextSpan>[];
    String remaining = transcript;

    for (final quote in quotes) {
      if (quote.isEmpty) continue;
      final index = remaining.toLowerCase().indexOf(quote.toLowerCase());
      if (index >= 0) {
        if (index > 0) {
          spans.add(TextSpan(text: remaining.substring(0, index)));
        }
        final matchEnd = index + quote.length;
        spans.add(TextSpan(
          text: remaining.substring(index, matchEnd),
          style: TextStyle(
            backgroundColor: AegisTheme.amberAccent.withValues(alpha: 0.25),
            color: AegisTheme.amberAccent,
            fontWeight: FontWeight.bold,
          ),
        ));
        remaining = remaining.substring(matchEnd);
      }
    }

    if (remaining.isNotEmpty) {
      spans.add(TextSpan(text: remaining));
    }

    return TextSpan(
      style: const TextStyle(color: AegisTheme.textPrimary, fontSize: 14, height: 1.4),
      children: spans,
    );
  }

  @override
  Widget build(BuildContext context) {
    final dateStr = DateFormat('yyyy-MM-dd HH:mm').format(capsule.observedAt);
    final quotes = capsule.facts.map((f) => f.quote).where((q) => q.isNotEmpty).toList();

    return Padding(
      padding: const EdgeInsets.all(20),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'Capsule detail',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: AegisTheme.amberAccent,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close, color: AegisTheme.textMuted),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
            const Divider(color: AegisTheme.cardBorder),
            const SizedBox(height: 8),

            const Text(
              'Spoken transcript (quoted spans highlighted):',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.textMuted),
            ),
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AegisTheme.surfaceVariant,
                borderRadius: BorderRadius.circular(12),
              ),
              child: RichText(
                text: _buildHighlightedTranscript(capsule.transcript, quotes),
              ),
            ),

            if (capsule.serverFlags.isNotEmpty) ...[
              const SizedBox(height: 14),
              const Text(
                'Flagged by the server:',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.alertRed),
              ),
              const SizedBox(height: 6),
              ...capsule.serverFlags.map((f) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text(
                      '${f['rule_id'] ?? ''} ${f['severity'] ?? ''}: ${f['title'] ?? ''}',
                      style: const TextStyle(fontSize: 12, color: AegisTheme.alertRed, fontWeight: FontWeight.w600),
                    ),
                  )),
              const Text(
                'Acknowledging or resolving this happens on the supervisor dashboard, not here.',
                style: TextStyle(fontSize: 11, color: AegisTheme.textMuted),
              ),
            ],

            const SizedBox(height: 14),
            const Text(
              'Extracted facts:',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.textMuted),
            ),
            const SizedBox(height: 6),
            ...capsule.facts.map((f) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('• ', style: TextStyle(color: AegisTheme.amberAccent, fontSize: 13)),
                      Expanded(
                        child: Text(
                          '${f.assetTag != null ? "[${f.assetTag}] " : ""}${f.text} (${f.assertedState.name})',
                          style: const TextStyle(fontSize: 12, color: AegisTheme.textPrimary),
                        ),
                      ),
                    ],
                  ),
                )),

            if (capsule.scadaComparison != null || capsule.discrepancyAlert != null) ...[
              const SizedBox(height: 14),
              const Text(
                'Telemetry:',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.textMuted),
              ),
              const SizedBox(height: 6),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AegisTheme.surfaceVariant,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AegisTheme.cardBorder),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: AegisTheme.amberAccent.withValues(alpha: 0.2),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: const Text(
                            'Mock SCADA',
                            style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AegisTheme.amberAccent),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          capsule.scadaComparison ?? 'SCADA reading attached',
                          style: const TextStyle(fontSize: 12, color: AegisTheme.textPrimary, fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                    if (capsule.discrepancyAlert != null) ...[
                      const SizedBox(height: 6),
                      Text(
                        capsule.discrepancyAlert!,
                        style: const TextStyle(fontSize: 11, color: AegisTheme.alertRed),
                      ),
                    ],
                  ],
                ),
              ),
            ],

            const SizedBox(height: 16),
            const Text(
              'Timeline:',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.textMuted),
            ),
            const SizedBox(height: 8),
            _timelineStep('Captured', dateStr, isDone: true),
            _timelineStep('Read on device', 'Method: ${capsule.extraction['method'] ?? 'LLM'}', isDone: true),
            _timelineStep('Synced', capsule.isSynced ? (capsule.syncedAt != null ? DateFormat('HH:mm').format(capsule.syncedAt!) : 'Synced') : 'Pending online sync', isDone: capsule.isSynced),
            _timelineStep('Checked in cloud', capsule.isSynced ? (capsule.serverFlags.isNotEmpty ? 'Conflict flagged' : 'No conflict flagged') : 'Pending', isDone: capsule.isSynced),

            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Widget _timelineStep(String title, String subtitle, {required bool isDone}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(
            isDone ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
            size: 16,
            color: isDone ? AegisTheme.successGreen : AegisTheme.textMuted,
          ),
          const SizedBox(width: 10),
          Text(
            '$title: ',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary),
          ),
          Expanded(
            child: Text(
              subtitle,
              style: TextStyle(fontSize: 12, color: isDone ? AegisTheme.textSecondary : AegisTheme.textMuted),
            ),
          ),
        ],
      ),
    );
  }
}
