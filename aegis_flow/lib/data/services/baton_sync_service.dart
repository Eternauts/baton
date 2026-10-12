import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../core/data/observation_capsule.dart';
import '../../core/config/app_config.dart';

sealed class SyncResult {}

class SyncSuccess extends SyncResult {
  /// Id of the handover the server recorded for these capsules (the same capsules always give the same id).
  final String? handoverId;
  SyncSuccess({this.handoverId});
}

class SyncConflict extends SyncResult {
  final List<dynamic> conflicts;
  final String? handoverId;
  SyncConflict(this.conflicts, {this.handoverId});
}

class SyncError extends SyncResult {
  final String message;
  SyncError(this.message);
}

class BatonSyncService {
  Future<SyncResult> syncPendingCapsules(List<ObservationCapsule> pendingCapsules, String deviceId) async {
    try {
      final uri = Uri.parse('${AppConfig.backendUrl}/v1/handover/batch_sync');

      final payload = {
        "device_id": deviceId,
        "capsules": pendingCapsules.map((c) {
          final fact = c.facts.isNotEmpty ? c.facts.first : null;
          final severity = c.escalation.level >= 2 
              ? "CRITICAL" 
              : (c.escalation.level == 1 ? "WARNING" : "INFO");

          return {
            "uuid": c.eventId,
            "timestamp": c.observedAt.toIso8601String(),
            "category": fact?.category.name ?? "EQUIPMENT",
            "asset_tag": fact?.assetTag ?? "UNTAGGED",
            "asserted_state": fact?.assertedState.name ?? "UNKNOWN",
            "text_transcript": c.transcript,
            "intent_severity": severity
          };
        }).toList()
      };

      final request = http.Request('POST', uri);
      request.headers['Content-Type'] = 'application/json';
      request.headers['X-Aegis-Key'] = AppConfig.aegisApiKey;
      request.body = jsonEncode(payload);

      // Timeout constraint for harsh environments
      final responseFuture = http.Client().send(request).timeout(const Duration(seconds: 5));
      final response = await http.Response.fromStream(await responseFuture);

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final handoverId = data['handover_id']?.toString();
        if (data['sync_status'] == 'SUCCESS') {
          return SyncSuccess(handoverId: handoverId);
        } else if (data['sync_status'] == 'CONFLICT_DETECTED') {
          return SyncConflict(data['conflicts'] ?? [], handoverId: handoverId);
        }
        return SyncError('Unknown sync status: ${data['sync_status']}');
      } else {
        return SyncError('Server returned status: ${response.statusCode}');
      }
    } catch (e) {
      return SyncError('Network error. Check connection or try offline QR mesh.');
    }
  }
}
