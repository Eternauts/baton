import 'package:flutter_test/flutter_test.dart';
import 'package:aegis_flow/core/ai/fact_model.dart';
import 'package:aegis_flow/core/ai/escalation.dart';

void main() {
  group('Asset Tag Integrity Tests', () {
    final registry = ['P-201B', 'T-310A', 'V-104', 'F-501'];

    test('"p104 valve failure" keeps P-104 and is never snapped to V-104', () {
      const transcript = 'p104 valve failure';
      final tag = Fact.normalizeAssetTag('p104');

      expect(tag, equals('P-104'));
      expect(tag, isNot(equals('V-104')));

      final fact = Fact(
        id: 'F1',
        category: FactCategory.EQUIPMENT,
        assetTag: tag,
        assertedState: AssertedState.UNKNOWN,
        text: 'p104 valve failure',
        quote: 'valve failure',
      );

      final esc = calculateEscalation(
        transcript: transcript,
        facts: [fact],
        extractionMethod: 'LLM',
        schemaValid: true,
        ungroundedFactIds: [],
        knownAssets: registry,
      );

      expect(esc.level, equals(1));
      expect(esc.reasons, contains('tag as spoken, not in registry'));
    });

    test('"P-201B vibrating" keeps P-201B', () {
      const transcript = 'P-201B vibrating heavily';
      final tag = Fact.normalizeAssetTag('P-201B');

      expect(tag, equals('P-201B'));
      expect(Fact.transcriptContainsTag(transcript, tag), isTrue);

      final fact = Fact(
        id: 'F1',
        category: FactCategory.EQUIPMENT,
        assetTag: tag,
        assertedState: AssertedState.RUNNING,
        text: 'P-201B vibrating heavily',
        quote: 'vibrating heavily',
      );

      final esc = calculateEscalation(
        transcript: transcript,
        facts: [fact],
        extractionMethod: 'LLM',
        schemaValid: true,
        ungroundedFactIds: [],
        knownAssets: registry,
      );

      expect(esc.level, equals(0));
    });
  });

  group('snapToKnownAsset', () {
    const known = ['P-201B', 'T-310A', 'V-104', 'F-501'];
    test('a spoken name containing a registry tag is that tag', () {
      expect(Fact.snapToKnownAsset('Pump P-201B', known), 'P-201B');
      expect(Fact.snapToKnownAsset('pump p201b', known), 'P-201B');
      expect(Fact.snapToKnownAsset('valve v 104 bleeder', known), 'V-104');
    });
    test('an unknown name stays unknown', () {
      expect(Fact.snapToKnownAsset('Beta-403A pressure gauge', known), isNull);
      expect(Fact.snapToKnownAsset('compressor unit', known), isNull);
    });
  });
}
