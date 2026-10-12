import 'dart:async';
import 'dart:convert';
import 'dart:developer';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:uuid/uuid.dart';
import '../../core/config/app_config.dart';
import '../../core/platform/platform_support.dart';

class CloudTranscriptionResponse {
  final String requestId;
  final String text;
  final String language;
  final String? englishText;
  final String engine;
  final String model;
  final double audioSeconds;
  final int latencyMs;
  final bool noSpeech;
  final int roundTripMs;
  final int uploadBytes;

  CloudTranscriptionResponse({
    required this.requestId,
    required this.text,
    required this.language,
    this.englishText,
    required this.engine,
    required this.model,
    required this.audioSeconds,
    required this.latencyMs,
    required this.noSpeech,
    required this.roundTripMs,
    required this.uploadBytes,
  });

  factory CloudTranscriptionResponse.fromJson(Map<String, dynamic> json, int roundTripMs, int uploadBytes) {
    return CloudTranscriptionResponse(
      requestId: json['request_id']?.toString() ?? '',
      text: json['text']?.toString() ?? '',
      language: json['language']?.toString() ?? 'en',
      englishText: json['english_text']?.toString(),
      engine: json['engine']?.toString() ?? 'whisper',
      model: json['model']?.toString() ?? 'large-v3',
      audioSeconds: (json['audio_seconds'] as num?)?.toDouble() ?? 0.0,
      latencyMs: (json['latency_ms'] as num?)?.toInt() ?? 0,
      noSpeech: json['no_speech'] as bool? ?? false,
      roundTripMs: roundTripMs,
      uploadBytes: uploadBytes,
    );
  }
}

class CloudTranscriptionException implements Exception {
  final int? statusCode;
  final String message;
  final String? code;

  CloudTranscriptionException({
    this.statusCode,
    required this.message,
    this.code,
  });

  @override
  String toString() => 'CloudTranscriptionException(status: $statusCode, code: $code, msg: $message)';
}

class CloudTranscriptionService {
  final _uuid = const Uuid();
  DateTime? _lastHealthSuccess;

  /// Check server health GET /api/health with 1.5s timeout. Caches success for 20s.
  Future<bool> checkHealth({http.Client? client}) async {
    if (_lastHealthSuccess != null &&
        DateTime.now().difference(_lastHealthSuccess!) < const Duration(seconds: 20)) {
      return true;
    }

    if (!AppConfig.hasBackendConfig) {
      debugPrint('[AEGIS_ASR] No backend config');
      return false;
    }

    final httpClient = client ?? http.Client();
    final shouldClose = client == null;

    try {
      final uri = Uri.parse(AppConfig.healthEndpoint);
      final response = await httpClient.get(uri).timeout(const Duration(seconds: 4));

      if (response.statusCode == 200) {
        final body = jsonDecode(response.body);
        if (body is Map && (body['ok'] == true || body['status'] == 'ok')) {
          _lastHealthSuccess = DateTime.now();
          debugPrint('[AEGIS_ASR] Health check succeeded');
          return true;
        }
      }
      debugPrint('[AEGIS_ASR] Health check returned ${response.statusCode}');
      return false;
    } catch (e) {
      debugPrint('[AEGIS_ASR] Health check failed: $e');
      log('Health check failed: $e', name: 'AEGIS_ASR');
      return false;
    } finally {
      if (shouldClose) httpClient.close();
    }
  }

  /// POST /api/transcribe multipart request
  Future<CloudTranscriptionResponse> transcribeAudio({
    required String filePath,
    required List<String> assetHints,
    http.Client? client,
  }) async {
    final Uint8List audioBytes;
    try {
      audioBytes = await readRecordingBytes(filePath);
    } catch (_) {
      debugPrint('[AEGIS_ASR] Audio missing at path: $filePath');
      log('Audio missing at path: $filePath', name: 'AEGIS_ASR');
      throw CloudTranscriptionException(
        statusCode: 400,
        message: 'Audio file missing',
        code: 'FILE_NOT_FOUND',
      );
    }

    final uploadBytes = audioBytes.length;
    final uri = Uri.parse(AppConfig.transcribeEndpoint);
    final request = http.MultipartRequest('POST', uri);

    request.headers['X-Aegis-Key'] = AppConfig.aegisApiKey;
    request.fields['client_request_id'] = _uuid.v4();
    request.fields['languages'] = 'en'; // Force English by default
    request.fields['asset_hints'] = assetHints.take(50).join(',');

    request.files.add(http.MultipartFile.fromBytes(
      'audio',
      audioBytes,
      filename: isWeb ? 'recording.webm' : 'recording.m4a',
      contentType: MediaType('audio', isWeb ? 'webm' : 'mp4'),
    ));

    final stopwatch = Stopwatch()..start();

    try {
      final httpClient = client ?? http.Client();
      final streamedResponse = await httpClient.send(request).timeout(const Duration(seconds: 8));
      final response = await http.Response.fromStream(streamedResponse).timeout(const Duration(seconds: 15));

      stopwatch.stop();
      final roundTripMs = stopwatch.elapsedMilliseconds;

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        final parsed = CloudTranscriptionResponse.fromJson(json, roundTripMs, uploadBytes);

        final logMsg = 'Cloud ASR Success! engine=${parsed.engine}, model=${parsed.model}, roundTripMs=$roundTripMs, bytes=$uploadBytes, noSpeech=${parsed.noSpeech}';
        debugPrint('[AEGIS_ASR] $logMsg');
        log(logMsg, name: 'AEGIS_ASR');
        return parsed;
      } else {
        String errCode = 'HTTP_${response.statusCode}';
        String errMessage = 'Server returned status ${response.statusCode}';
        try {
          final errBody = jsonDecode(response.body);
          if (errBody is Map && errBody['error'] != null) {
            errCode = errBody['error']['code']?.toString() ?? errCode;
            errMessage = errBody['error']['message']?.toString() ?? errMessage;
          }
        } catch (_) {}

        final logMsg = 'Cloud ASR Error: $errCode ($response.statusCode) - $errMessage';
        debugPrint('[AEGIS_ASR] $logMsg');
        log(logMsg, name: 'AEGIS_ASR');
        throw CloudTranscriptionException(
          statusCode: response.statusCode,
          message: errMessage,
          code: errCode,
        );
      }
    } on TimeoutException {
      stopwatch.stop();
      final logMsg = 'Cloud ASR Timeout after ${stopwatch.elapsedMilliseconds}ms';
      debugPrint('[AEGIS_ASR] $logMsg');
      log(logMsg, name: 'AEGIS_ASR');
      throw CloudTranscriptionException(
        statusCode: 504,
        message: 'Request timed out',
        code: 'TIMEOUT',
      );
    } catch (e) {
      stopwatch.stop();
      if (e is CloudTranscriptionException) rethrow;

      final logMsg = 'Cloud ASR Exception: $e';
      debugPrint('[AEGIS_ASR] $logMsg');
      log(logMsg, name: 'AEGIS_ASR');
      throw CloudTranscriptionException(
        statusCode: 500,
        message: 'Network error',
        code: 'NETWORK_ERROR',
      );
    }
  }
}
