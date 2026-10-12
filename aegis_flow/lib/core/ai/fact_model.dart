// ignore_for_file: constant_identifier_names

enum FactCategory {
  ISOLATION,
  PERMIT,
  SAFEGUARD,
  CONTAINMENT,
  EQUIPMENT,
  ALARM,
  GENERAL,
}

enum AssertedState {
  ISOLATED,
  DE_ENERGIZED,
  ENERGIZED,
  OPEN,
  CLOSED,
  RUNNING,
  STOPPED,
  BYPASSED,
  LEAKING,
  VIBRATING,
  NORMAL,
  UNKNOWN,
}

enum PermitType {
  HOT_WORK,
  COLD_WORK,
  CONFINED_SPACE,
  ELECTRICAL,
  OTHER,
}

class Fact {
  final String id;
  final FactCategory category;
  final String? assetTag;
  final AssertedState assertedState;
  final String? permitId;
  final PermitType? permitType;
  final String text;
  final String quote;

  Fact({
    required this.id,
    required this.category,
    this.assetTag,
    required this.assertedState,
    this.permitId,
    this.permitType,
    required this.text,
    required this.quote,
  });

  Fact copyWith({
    String? id,
    FactCategory? category,
    String? assetTag,
    AssertedState? assertedState,
    String? permitId,
    PermitType? permitType,
    String? text,
    String? quote,
  }) {
    return Fact(
      id: id ?? this.id,
      category: category ?? this.category,
      assetTag: assetTag ?? this.assetTag,
      assertedState: assertedState ?? this.assertedState,
      permitId: permitId ?? this.permitId,
      permitType: permitType ?? this.permitType,
      text: text ?? this.text,
      quote: quote ?? this.quote,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'category': category.name,
        'asset_tag': assetTag,
        'asserted_state': assertedState.name,
        'permit_id': permitId,
        'permit_type': permitType?.name,
        'text': text,
        'quote': quote,
      };

  factory Fact.fromJson(Map<String, dynamic> json, int index) {
    final catStr = json['category']?.toString().toUpperCase() ?? 'EQUIPMENT';
    final category = FactCategory.values.firstWhere(
      (e) => e.name == catStr,
      orElse: () => FactCategory.EQUIPMENT,
    );

    final stateStr = json['asserted_state']?.toString().toUpperCase() ?? 'UNKNOWN';
    final assertedState = AssertedState.values.firstWhere(
      (e) => e.name == stateStr,
      orElse: () => AssertedState.UNKNOWN,
    );

    final pTypeStr = json['permit_type']?.toString().toUpperCase();
    PermitType? permitType;
    if (pTypeStr != null && pTypeStr != 'NULL' && pTypeStr.isNotEmpty) {
      permitType = PermitType.values.firstWhere(
        (e) => e.name == pTypeStr,
        orElse: () => PermitType.OTHER,
      );
    }

    String? tag = json['asset_tag']?.toString();
    if (tag != null && tag.toLowerCase() == 'null') tag = null;
    if (tag != null && tag.isNotEmpty) {
      tag = normalizeAssetTag(tag);
    }

    final quoteStr = json['quote']?.toString() ?? '';
    final textStr = json['text']?.toString() ?? '';

    return Fact(
      id: json['id']?.toString() ?? 'F${index + 1}',
      category: category,
      assetTag: tag,
      assertedState: assertedState,
      permitId: (json['permit_id']?.toString() == 'null') ? null : json['permit_id']?.toString(),
      permitType: permitType,
      text: textStr,
      quote: quoteStr,
    );
  }

  static String normalizeAssetTag(String input) {
    final trimmed = input.trim();
    final regExp = RegExp(r'^([A-Z]{1,4})[\s-]*(\d{2,4}[A-Z]?)$', caseSensitive: false);
    final match = regExp.firstMatch(trimmed);
    if (match != null) {
      return '${match.group(1)!.toUpperCase()}-${match.group(2)!.toUpperCase()}';
    }
    return trimmed;
  }

  /// A spoken name that contains a registry tag ("Pump P-201B", "pump p201b") is that asset: return the registry tag.
  /// Null when it contains none, so a genuinely unknown name stays as spoken and is flagged for review.
  static String? snapToKnownAsset(String spoken, List<String> knownAssets) {
    String squash(String v) => v.toUpperCase().replaceAll(RegExp(r'[\s-]'), '');
    final s = squash(spoken);
    for (final a in knownAssets) {
      final k = squash(a);
      if (k.isNotEmpty && s.contains(k)) return a;
    }
    return null;
  }

  static bool transcriptContainsTag(String transcript, String assetTag) {
    final normTranscript = transcript.replaceAll('-', '').replaceAll(' ', '').toUpperCase();
    final normTag = assetTag.replaceAll('-', '').replaceAll(' ', '').toUpperCase();
    return normTranscript.contains(normTag);
  }
}
