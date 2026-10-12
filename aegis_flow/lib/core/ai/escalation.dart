import 'fact_model.dart';

class EscalationResult {
  final int level;
  final List<String> reasons;

  const EscalationResult({required this.level, required this.reasons});

  Map<String, dynamic> toJson() => {
        'level': level,
        'reasons': reasons,
      };

  factory EscalationResult.fromJson(Map<String, dynamic> json) => EscalationResult(
        level: (json['level'] as num?)?.toInt() ?? 0,
        reasons: (json['reasons'] as List?)?.map((e) => e.toString()).toList() ?? [],
      );
}

EscalationResult calculateEscalation({
  required String transcript,
  required List<Fact> facts,
  required String extractionMethod, // "LLM" or "HEURISTIC"
  required bool schemaValid,
  required List<String> ungroundedFactIds,
  required List<String> knownAssets,
  bool hasAudioOrImage = false,
}) {
  final reasons = <String>[];
  bool isLevel1 = false;
  bool isLevel2 = false;

  final trimmedTranscript = transcript.trim();
  final lowerTranscript = trimmedTranscript.toLowerCase();

  final safetyCategories = {
    FactCategory.ISOLATION,
    FactCategory.PERMIT,
    FactCategory.SAFEGUARD,
    FactCategory.CONTAINMENT,
  };

  // Level 1 rules
  for (final fact in facts) {
    if (safetyCategories.contains(fact.category)) {
      isLevel1 = true;
      reasons.add('Fact ${fact.id} has critical safety category ${fact.category.name}');
      if (fact.assertedState == AssertedState.UNKNOWN) {
        reasons.add('Safety fact ${fact.id} has UNKNOWN state');
      }
    }

    if (fact.permitType == PermitType.HOT_WORK) {
      isLevel1 = true;
      reasons.add('Fact ${fact.id} involves HOT_WORK permit');
    }

    if (fact.assetTag != null && fact.assetTag!.isNotEmpty) {
      final normTag = Fact.normalizeAssetTag(fact.assetTag!);
      final normKnown = knownAssets.map((a) => Fact.normalizeAssetTag(a)).toSet();
      if (!normKnown.contains(normTag)) {
        isLevel1 = true;
        reasons.add('tag as spoken, not in registry');
      }
    }
  }

  if (ungroundedFactIds.isNotEmpty) {
    isLevel1 = true;
    reasons.add('Ungrounded facts detected: ${ungroundedFactIds.join(', ')}');
  }

  if (extractionMethod == 'HEURISTIC') {
    isLevel1 = true;
    reasons.add('Extraction performed via fallback HEURISTIC method');
  }

  if (trimmedTranscript.isNotEmpty && facts.isEmpty) {
    isLevel1 = true;
    reasons.add('Non-empty transcript produced zero extracted facts');
  }

  // Level 2 rules (only if audio or image exists)
  if (hasAudioOrImage) {
    const level2Keywords = [
      'gas',
      'leak',
      'h2s',
      'fire',
      'smoke',
      'smell',
      'injury',
      'spill',
      'alarm',
      'trip',
      'bypass',
      'override',
      'overpressure',
    ];

    for (final kw in level2Keywords) {
      if (lowerTranscript.contains(kw)) {
        isLevel2 = true;
        reasons.add('Hazard keyword "$kw" in transcript with media attached');
        break;
      }
    }

    for (final fact in facts) {
      if (fact.assertedState == AssertedState.BYPASSED ||
          fact.assertedState == AssertedState.LEAKING) {
        isLevel2 = true;
        reasons.add('Fact ${fact.id} has severe state ${fact.assertedState.name} with media attached');
      }
    }

    if (!schemaValid) {
      isLevel2 = true;
      reasons.add('Invalid JSON schema with media attached');
    }
  }

  int level = 0;
  if (isLevel2) {
    level = 2;
  } else if (isLevel1) {
    level = 1;
  }

  return EscalationResult(level: level, reasons: reasons);
}
