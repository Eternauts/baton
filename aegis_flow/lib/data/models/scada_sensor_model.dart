/// Mock SCADA telemetry sensor data to cross-check field logs vs physical sensors
class ScadaSensorModel {
  final String tag;
  final String equipmentName;
  final double currentValue;
  final String unit;
  final double normalMin;
  final double normalMax;
  final String status; // 'NORMAL', 'WARNING', 'CRITICAL'
  final DateTime lastTelemetry;

  ScadaSensorModel({
    required this.tag,
    required this.equipmentName,
    required this.currentValue,
    required this.unit,
    required this.normalMin,
    required this.normalMax,
    required this.status,
    required this.lastTelemetry,
  });

  bool get isWithinNormalRange => currentValue >= normalMin && currentValue <= normalMax;

  Map<String, dynamic> toMap() {
    return {
      'tag': tag,
      'equipmentName': equipmentName,
      'currentValue': currentValue,
      'unit': unit,
      'normalMin': normalMin,
      'normalMax': normalMax,
      'status': status,
      'lastTelemetry': lastTelemetry.toIso8601String(),
    };
  }

  factory ScadaSensorModel.fromMap(Map<String, dynamic> map) {
    return ScadaSensorModel(
      tag: map['tag'] as String,
      equipmentName: map['equipmentName'] as String,
      currentValue: (map['currentValue'] as num).toDouble(),
      unit: map['unit'] as String,
      normalMin: (map['normalMin'] as num).toDouble(),
      normalMax: (map['normalMax'] as num).toDouble(),
      status: map['status'] as String,
      lastTelemetry: DateTime.parse(map['lastTelemetry'] as String),
    );
  }
}
