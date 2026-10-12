import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../core/config/app_config.dart';

/// A readable failure for the screen: what went wrong, and whether trying again can help.
class ApiException implements Exception {
  final String message;
  final bool retryable;
  ApiException(this.message, {this.retryable = true});
  @override
  String toString() => message;
}

/// The one place that talks to the Baton API with the app key: JSON in, JSON out, errors turned into plain words.
class ApiClient {
  Map<String, String> get _headers => {'Content-Type': 'application/json', 'X-Aegis-Key': AppConfig.aegisApiKey};

  Future<Map<String, dynamic>> send(String method, String path, {Object? body, int timeoutSec = 20}) async {
    if (!AppConfig.hasBackendConfig) {
      throw ApiException('This build has no server key, so it cannot reach the server.', retryable: false);
    }
    try {
      final req = http.Request(method, Uri.parse('${AppConfig.backendUrl}$path'))..headers.addAll(_headers);
      if (body != null) req.body = jsonEncode(body);
      final res = await http.Response.fromStream(await req.send().timeout(Duration(seconds: timeoutSec)));
      final data = res.body.isEmpty ? <String, dynamic>{} : (jsonDecode(res.body) as Map<String, dynamic>);
      if (res.statusCode == 200) return data;
      final detail = data['detail'];
      final text = detail is String ? detail : (detail is Map ? (detail['error']?['message']?.toString() ?? '') : '');
      switch (res.statusCode) {
        case 401:
          throw ApiException("The server rejected this app's key.", retryable: false);
        case 404:
          throw ApiException('That is no longer on the server.', retryable: false);
        case 409:
        case 422:
          throw ApiException(text.isEmpty ? 'The server did not accept that.' : text, retryable: false);
        case 429:
          throw ApiException('Too many questions in a short time. Wait a moment and try again.');
        default:
          throw ApiException('The server had a problem (${res.statusCode}). Try again.');
      }
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException('No connection to the server. Check the network and try again.');
    }
  }
}
