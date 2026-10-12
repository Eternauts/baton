import 'package:flutter/material.dart';
import '../../../core/ai/fact_model.dart';
import '../../../core/ai/on_device_ai_service.dart';
import '../../../ui/core/theme.dart';

class GlanceExtractionCard extends StatelessWidget {
  final bool isExtracting;
  final ExtractionResult? extractionResult;
  final List<String> knownAssets;
  final Function(String assetTag)? onSelectAssetTag;
  final Function(AssertedState state)? onSelectState;

  const GlanceExtractionCard({
    super.key,
    required this.isExtracting,
    required this.extractionResult,
    required this.knownAssets,
    this.onSelectAssetTag,
    this.onSelectState,
  });

  @override
  Widget build(BuildContext context) {
    if (isExtracting) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: AegisTheme.surfaceVariant,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AegisTheme.amberAccent.withValues(alpha: 0.3)),
        ),
        child: Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: const BoxDecoration(
                shape: BoxShape.circle,
                color: AegisTheme.amberAccent,
              ),
            ),
            const SizedBox(width: 10),
            const Text(
              'Reading on device...',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AegisTheme.amberAccent,
              ),
            ),
          ],
        ),
      );
    }

    if (extractionResult == null) return const SizedBox.shrink();

    final result = extractionResult!;
    final facts = result.facts.take(3).toList();

    String? foundTag;
    for (final f in result.facts) {
      if (f.assetTag != null && f.assetTag!.isNotEmpty) {
        foundTag = f.assetTag;
        break;
      }
    }

    final firstState = facts.isNotEmpty ? facts.first.assertedState.name : 'Unknown';

    final hasEscalation = result.facts.any((f) =>
        f.category.name == 'ISOLATION' ||
        f.category.name == 'PERMIT' ||
        f.category.name == 'SAFEGUARD' ||
        f.category.name == 'CONTAINMENT' ||
        f.assertedState.name == 'LEAKING' ||
        f.assertedState.name == 'BYPASSED');

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AegisTheme.surfaceVariant,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: hasEscalation
              ? AegisTheme.amberAccent.withValues(alpha: 0.6)
              : AegisTheme.cardBorder,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Flexible(
                child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AegisTheme.surface,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: foundTag != null
                        ? AegisTheme.amberAccent.withValues(alpha: 0.5)
                        : AegisTheme.amberAccent.withValues(alpha: 0.3),
                  ),
                ),
                child: Text(
                  foundTag ?? 'No asset found',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontFamily: foundTag != null ? 'monospace' : null,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: foundTag != null ? AegisTheme.amberAccent : AegisTheme.amberAccent.withValues(alpha: 0.8),
                  ),
                ),
                ),
              ),
              const SizedBox(width: 10),
              Text(
                firstState,
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AegisTheme.textPrimary,
                ),
              ),
            ],
          ),

          const SizedBox(height: 12),
          Text(
            foundTag == null
                ? 'No asset recognised. Pick one so the supervisor can match it:'
                : (knownAssets.contains(foundTag) ? 'Asset (tap to change):' : '"$foundTag" is not in the asset list. Correct it if needed:'),
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: foundTag == null || !knownAssets.contains(foundTag) ? AegisTheme.amberAccent : AegisTheme.textMuted,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: knownAssets.take(8).map((tag) => _choice(tag, selected: tag == foundTag, mono: true, onTap: () => onSelectAssetTag?.call(tag))).toList(),
          ),
          const SizedBox(height: 12),
          Text(
            firstState == 'UNKNOWN' ? 'State not stated. Pick one if you know it:' : 'State (tap to change):',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: firstState == 'UNKNOWN' ? AegisTheme.amberAccent : AegisTheme.textMuted,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _stateChoices
                .map((st) => _choice(st.name.replaceAll('_', ' '), selected: firstState == st.name, mono: false, onTap: () => onSelectState?.call(st)))
                .toList(),
          ),

          const SizedBox(height: 12),
          ...facts.map((fact) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('• ', style: TextStyle(color: AegisTheme.amberAccent, fontSize: 13)),
                    Expanded(
                      child: Text(
                        fact.text,
                        style: const TextStyle(
                          fontSize: 13,
                          color: AegisTheme.textSecondary,
                        ),
                      ),
                    ),
                  ],
                ),
              )),

          if (hasEscalation) ...[
            const SizedBox(height: 8),
            const Row(
              children: [
                Icon(Icons.shield, size: 14, color: AegisTheme.amberAccent),
                SizedBox(width: 6),
                Text(
                  'Safety item: source text will be attached',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AegisTheme.amberAccent,
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  static const _stateChoices = [
    AssertedState.ISOLATED,
    AssertedState.RUNNING,
    AssertedState.STOPPED,
    AssertedState.OPEN,
    AssertedState.CLOSED,
    AssertedState.LEAKING,
    AssertedState.VIBRATING,
    AssertedState.NORMAL,
  ];

  Widget _choice(String label, {required bool selected, required bool mono, required VoidCallback onTap}) {
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      excludeSemantics: true,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: selected ? AegisTheme.amberAccent : AegisTheme.surface,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: selected ? AegisTheme.amberAccent : AegisTheme.cardBorder),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontFamily: mono ? 'monospace' : null,
              fontSize: 12,
              fontWeight: FontWeight.bold,
              color: selected ? Colors.black : (mono ? AegisTheme.amberAccent : AegisTheme.textPrimary),
            ),
          ),
        ),
      ),
    );
  }
}
