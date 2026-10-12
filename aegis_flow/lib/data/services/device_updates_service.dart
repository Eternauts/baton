import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../core/config/app_config.dart';

/// A safety update the cloud pipeline published for this device's unit. Read-only: the app never
/// clears, acknowledges or resolves anything.
class DeviceUpdate {
  final String id;
  final String severity;
  final String summary;
  final List<String> alerts;
  final List<String> requiredActions;
  final DateTime? createdAt;

  const DeviceUpdate({
    required this.id,
    required this.severity,
    required this.summary,
    required this.alerts,
    required this.requiredActions,
    this.createdAt,
  });

  bool get isCritical => severity.toUpperCase() == 'CRITICAL';

  factory DeviceUpdate.fromMap(Map<String, dynamic> m) {
    List<String> strings(dynamic v) => (v as List?)?.map((e) => e.toString()).toList() ?? const [];
    return DeviceUpdate(
      id: m['update_id']?.toString() ?? '',
      severity: m['severity']?.toString() ?? 'INFO',
      summary: m['summary']?.toString() ?? '',
      alerts: strings(m['alerts']),
      requiredActions: strings(m['required_actions']),
      createdAt: DateTime.tryParse(m['created_at']?.toString() ?? '')?.toLocal(),
    );
  }
}

class DeviceUpdatesService {
  /// Newest first. Returns null when the updates could not be read (offline, rejected, timeout),
  /// so the caller keeps showing what it already had instead of an empty list.
  Future<List<DeviceUpdate>?> fetch(String deviceId) async {
    if (!AppConfig.hasBackendConfig) return null;
    try {
      final uri = Uri.parse('${AppConfig.backendUrl}/api/v1/devices/${Uri.encodeComponent(deviceId)}/updates');
      final res = await http.get(uri, headers: {'X-Aegis-Key': AppConfig.aegisApiKey}).timeout(const Duration(seconds: 6));
      if (res.statusCode != 200) return null;
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      return (data['updates'] as List? ?? const [])
          .map((e) => DeviceUpdate.fromMap(Map<String, dynamic>.from(e as Map)))
          .toList();
    } catch (_) {
      return null;
    }
  }
}
