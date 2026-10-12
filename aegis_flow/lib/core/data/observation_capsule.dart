import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:uuid/uuid.dart';
import '../ai/fact_model.dart';
import '../ai/escalation.dart';

class ObservationCapsule {
  final String schemaVersion;
  final String eventId;
  final String deviceId;
  final int seq;
  final String unitName;
  final String shiftName;
  final String operatorId;
  final DateTime observedAt;
  final String sourceType; // "VOICE" or "LOG"
  final String language;
  final String? sourceLanguage;
  final String? englishText;
  final String transcript;
  final List<Fact> facts;
  final List<Map<String, dynamic>> evidence;
  final Map<String, dynamic> extraction;
  final Map<String, dynamic> transcription;
  final EscalationResult escalation;
  final int rawSizeBytes;
  final bool isSynced;
  final DateTime? syncedAt;
  final String? discrepancyAlert;
  final String? scadaComparison;
  /// Safety conflicts the server flagged for this capsule at sync time: {rule_id, title, severity}.
  final List<Map<String, dynamic>> serverFlags;

  ObservationCapsule({
    this.schemaVersion = '1.0',
    required this.eventId,
    required this.deviceId,
    required this.seq,
    required this.unitName,
    required this.shiftName,
    required this.operatorId,
    required this.observedAt,
    required this.sourceType,
    this.language = 'en',
    this.sourceLanguage,
    this.englishText,
    required this.transcript,
    required this.facts,
    required this.evidence,
    required this.extraction,
    required this.transcription,
    required this.escalation,
    required this.rawSizeBytes,
    this.isSynced = false,
    this.syncedAt,
    this.discrepancyAlert,
    this.scadaComparison,
    this.serverFlags = const [],
  });

  ObservationCapsule copyWith({
    bool? isSynced,
    DateTime? syncedAt,
    String? discrepancyAlert,
    String? scadaComparison,
    List<Map<String, dynamic>>? serverFlags,
  }) {
    return ObservationCapsule(
      schemaVersion: schemaVersion,
      eventId: eventId,
      deviceId: deviceId,
      seq: seq,
      unitName: unitName,
      shiftName: shiftName,
      operatorId: operatorId,
      observedAt: observedAt,
      sourceType: sourceType,
      language: language,
      sourceLanguage: sourceLanguage,
      englishText: englishText,
      transcript: transcript,
      facts: facts,
      evidence: evidence,
      extraction: extraction,
      transcription: transcription,
      escalation: escalation,
      rawSizeBytes: rawSizeBytes,
      isSynced: isSynced ?? this.isSynced,
      syncedAt: syncedAt ?? this.syncedAt,
      discrepancyAlert: discrepancyAlert ?? this.discrepancyAlert,
      scadaComparison: scadaComparison ?? this.scadaComparison,
      serverFlags: serverFlags ?? this.serverFlags,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'schema_version': schemaVersion,
      'event_id': eventId,
      'device_id': deviceId,
      'seq': seq,
      'unit_name': unitName,
      'shift_name': shiftName,
      'operator_id': operatorId,
      'observed_at': observedAt.toIso8601String(),
      'source_type': sourceType,
      'language': language,
      if (sourceLanguage != null) 'source_language': sourceLanguage,
      if (englishText != null) 'english_text': englishText,
      'transcript': transcript,
      'facts': facts.map((f) => f.toJson()).toList(),
      'evidence': evidence,
      'extraction': extraction,
      'transcription': transcription,
      'escalation': escalation.toJson(),
      'raw_size_bytes': rawSizeBytes,
      'is_synced': isSynced,
      'synced_at': syncedAt?.toIso8601String(),
      'discrepancy_alert': discrepancyAlert,
      'scada_comparison': scadaComparison,
      'server_flags': serverFlags,
    };
  }

  factory ObservationCapsule.fromMap(Map<String, dynamic> map) {
    final factsList = (map['facts'] as List?)
            ?.asMap()
            .entries
            .map((e) => Fact.fromJson(Map<String, dynamic>.from(e.value), e.key))
            .toList() ??
        [];

    final escMap = map['escalation'] != null
        ? EscalationResult.fromJson(Map<String, dynamic>.from(map['escalation']))
        : const EscalationResult(level: 0, reasons: []);

    return ObservationCapsule(
      schemaVersion: map['schema_version']?.toString() ?? '1.0',
      eventId: map['event_id']?.toString() ?? const Uuid().v4(),
      deviceId: map['device_id']?.toString() ?? 's22-ultra-dev-01',
      seq: (map['seq'] as num?)?.toInt() ?? 1,
      unitName: map['unit_name']?.toString() ?? 'Unit 3 - Offshore',
      shiftName: map['shift_name']?.toString() ?? 'Alpha Shift',
      operatorId: map['operator_id']?.toString() ?? 'OP-8821',
      observedAt: DateTime.tryParse(map['observed_at']?.toString() ?? '') ?? DateTime.now(),
      sourceType: map['source_type']?.toString() ?? 'VOICE',
      language: map['language']?.toString() ?? 'en',
      sourceLanguage: map['source_language']?.toString(),
      englishText: map['english_text']?.toString(),
      transcript: map['transcript']?.toString() ?? '',
      facts: factsList,
      evidence: (map['evidence'] as List?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList() ??
          [],
      extraction: Map<String, dynamic>.from(map['extraction'] ?? {}),
      transcription: Map<String, dynamic>.from(map['transcription'] ?? {'method': 'ON_DEVICE_ANDROID'}),
      escalation: escMap,
      rawSizeBytes: (map['raw_size_bytes'] as num?)?.toInt() ?? 0,
      isSynced: map['is_synced'] as bool? ?? false,
      syncedAt: map['synced_at'] != null ? DateTime.tryParse(map['synced_at'].toString()) : null,
      discrepancyAlert: map['discrepancy_alert']?.toString(),
      scadaComparison: map['scada_comparison']?.toString(),
      serverFlags: (map['server_flags'] as List?)?.map((e) => Map<String, dynamic>.from(e as Map)).toList() ?? const [],
    );
  }

  String toJson() => jsonEncode(toMap());

  factory ObservationCapsule.fromJson(String source) =>
      ObservationCapsule.fromMap(jsonDecode(source) as Map<String, dynamic>);

  static List<Map<String, dynamic>> buildEvidence(String text) {
    final bytes = utf8.encode(text);
    final digest = sha256.convert(bytes);
    return [
      {
        'kind': 'SOURCE_TEXT',
        'sha256': digest.toString(),
        'size_bytes': bytes.length,
        'uploaded': false,
      }
    ];
  }
}
