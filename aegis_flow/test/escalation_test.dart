import 'package:flutter_test/flutter_test.dart';
import 'package:aegis_flow/core/ai/fact_model.dart';
import 'package:aegis_flow/core/ai/escalation.dart';

void main() {
  group('Escalation Tests', () {
    final knownAssets = ['P-201B', 'T-310A', 'V-104', 'F-501'];

    test('Normal equipment observation -> Level 0', () {
      final fact = Fact(
        id: 'F1',
        category: FactCategory.EQUIPMENT,
        assetTag: 'P-201B',
        assertedState: AssertedState.RUNNING,
        text: 'Pump is running',
        quote: 'running',
      );

      final result = calculateEscalation(
        transcript: 'P-201B is running fine',
        facts: [fact],
        extractionMethod: 'LLM',
        schemaValid: true,
        ungroundedFactIds: [],
        knownAssets: knownAssets,
      );

      expect(result.level, equals(0));
      expect(result.reasons, isEmpty);
    });

    test('ISOLATION category -> Level 1', () {
      final fact = Fact(
        id: 'F1',
        category: FactCategory.ISOLATION,
        assetTag: 'V-104',
        assertedState: AssertedState.ISOLATED,
        text: 'Valve isolated',
        quote: 'isolated',
      );

      final result = calculateEscalation(
        transcript: 'V-104 is isolated',
        facts: [fact],
        extractionMethod: 'LLM',
        schemaValid: true,
        ungroundedFactIds: [],
        knownAssets: knownAssets,
      );

      expect(result.level, equals(1));
      expect(result.reasons, contains(predicate((String s) => s.contains('critical safety category'))));
    });

    test('Heuristic method fallback -> Level 1', () {
      final result = calculateEscalation(
        transcript: 'Some text',
        facts: [],
        extractionMethod: 'HEURISTIC',
        schemaValid: true,
        ungroundedFactIds: [],
        knownAssets: knownAssets,
      );

      expect(result.level, equals(1));
      expect(result.reasons, contains(predicate((String s) => s.contains('HEURISTIC'))));
    });

    test('Hazard keyword with audio attached -> Level 2', () {
      final fact = Fact(
        id: 'F1',
        category: FactCategory.EQUIPMENT,
        assetTag: 'P-201B',
        assertedState: AssertedState.LEAKING,
        text: 'Pump leaking wet',
        quote: 'leaking',
      );

      final result = calculateEscalation(
        transcript: 'P-201B leak detected',
        facts: [fact],
        extractionMethod: 'LLM',
        schemaValid: true,
        ungroundedFactIds: [],
        knownAssets: knownAssets,
        hasAudioOrImage: true,
      );

      expect(result.level, equals(2));
      expect(result.reasons.any((r) => r.contains('leak')), isTrue);
    });
  });
}
