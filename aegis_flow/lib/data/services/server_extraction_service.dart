import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../core/config/app_config.dart';

class ServerExtraction {
  final String raw; // the model's JSON, in the same schema the on-device model uses
  final int latencyMs;
  const ServerExtraction({required this.raw, required this.latencyMs});
}

/// Reads a note with the server's model when the on-device one is not available (the website, or a phone that
/// has not installed Gemma). The app validates the answer with the same code as for the on-device model.
class ServerExtractionService {
  /// Null on any failure (offline, rejected, slow, unusable answer): the caller falls back to its heuristic.
  Future<ServerExtraction?> extract(String transcript, List<String> knownAssets) async {
    if (!AppConfig.hasBackendConfig) return null;
    try {
      final res = await http
          .post(
            Uri.parse('${AppConfig.backendUrl}/api/v1/extract'),
            headers: {'Content-Type': 'application/json', 'X-Aegis-Key': AppConfig.aegisApiKey},
            body: jsonEncode({'transcript': transcript, 'known_assets': knownAssets.take(50).toList()}),
          )
          .timeout(const Duration(seconds: 14));
      if (res.statusCode != 200) return null;
      final d = jsonDecode(res.body) as Map<String, dynamic>;
      final raw = d['raw']?.toString();
      if (raw == null || raw.isEmpty) return null;
      return ServerExtraction(raw: raw, latencyMs: (d['latency_ms'] as num?)?.toInt() ?? 0);
    } catch (_) {
      return null;
    }
  }
}
