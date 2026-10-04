import 'dart:convert';

/// Represents a field observation logged by an offshore shift operator.
class ObservationModel {
  final String id;
  final String rawInput;
  final String language;
  final String tag;
  final String anomaly;
  final int severity; // 1 (Minor) to 5 (Critical)
  final String unit;
  final String actionRequired;
  final DateTime timestamp;
  final bool isSynced;
  final DateTime? syncedAt;
  final String? discrepancyAlert;
  final String? scadaComparison;

  ObservationModel({
    required this.id,
    required this.rawInput,
    required this.language,
    required this.tag,
    required this.anomaly,
    required this.severity,
    required this.unit,
    required this.actionRequired,
    required this.timestamp,
    this.isSynced = false,
    this.syncedAt,
    this.discrepancyAlert,
    this.scadaComparison,
  });

  ObservationModel copyWith({
    String? id,
    String? rawInput,
    String? language,
    String? tag,
    String? anomaly,
    int? severity,
    String? unit,
    String? actionRequired,
    DateTime? timestamp,
    bool? isSynced,
    DateTime? syncedAt,
    String? discrepancyAlert,
    String? scadaComparison,
  }) {
    return ObservationModel(
      id: id ?? this.id,
      rawInput: rawInput ?? this.rawInput,
      language: language ?? this.language,
      tag: tag ?? this.tag,
      anomaly: anomaly ?? this.anomaly,
      severity: severity ?? this.severity,
      unit: unit ?? this.unit,
      actionRequired: actionRequired ?? this.actionRequired,
      timestamp: timestamp ?? this.timestamp,
      isSynced: isSynced ?? this.isSynced,
      syncedAt: syncedAt ?? this.syncedAt,
      discrepancyAlert: discrepancyAlert ?? this.discrepancyAlert,
      scadaComparison: scadaComparison ?? this.scadaComparison,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'rawInput': rawInput,
      'language': language,
      'tag': tag,
      'anomaly': anomaly,
      'severity': severity,
      'unit': unit,
      'actionRequired': actionRequired,
      'timestamp': timestamp.toIso8601String(),
      'isSynced': isSynced,
      'syncedAt': syncedAt?.toIso8601String(),
      'discrepancyAlert': discrepancyAlert,
      'scadaComparison': scadaComparison,
    };
  }

  factory ObservationModel.fromMap(Map<String, dynamic> map) {
    return ObservationModel(
      id: map['id'] as String,
      rawInput: map['rawInput'] as String,
      language: map['language'] as String? ?? 'en',
      tag: map['tag'] as String,
      anomaly: map['anomaly'] as String,
      severity: (map['severity'] as num?)?.toInt() ?? 3,
      unit: map['unit'] as String? ?? 'General Plant',
      actionRequired: map['actionRequired'] as String? ?? 'Review during handover',
      timestamp: DateTime.tryParse(map['timestamp'] as String? ?? '') ?? DateTime.now(),
      isSynced: map['isSynced'] as bool? ?? false,
      syncedAt: map['syncedAt'] != null ? DateTime.tryParse(map['syncedAt'] as String) : null,
      discrepancyAlert: map['discrepancyAlert'] as String?,
      scadaComparison: map['scadaComparison'] as String?,
    );
  }

  String toJson() => json.encode(toMap());

  factory ObservationModel.fromJson(String source) =>
      ObservationModel.fromMap(json.decode(source) as Map<String, dynamic>);

  /// Formatted JSON output representation matching on-device Gemma INT4 extraction
  String toStructuredJsonPreview() {
    final Map<String, dynamic> structured = {
      'tag': tag,
      'anomaly': anomaly,
      'severity': severity,
      'unit': unit,
      'action_required': actionRequired,
    };
    return const JsonEncoder.withIndent('  ').convert(structured);
  }
}
