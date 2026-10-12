import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:aegis_flow/data/services/cloud_transcription_service.dart';

void main() {
  group('CloudTranscriptionService Unit Tests', () {
    test('checkHealth returns true when ok is true or status is ok', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/api/health');
        return http.Response(jsonEncode({'status': 'ok'}), 200);
      });

      final service = CloudTranscriptionService();
      final ok = await service.checkHealth(client: mockClient);
      expect(ok, isTrue);
    });

    test('transcribeAudio returns parsed response on 200 OK', () async {
      final response = CloudTranscriptionResponse.fromJson({
        'request_id': 'req-123',
        'text': 'Pam P-201B bergegar',
        'language': 'ms',
        'english_text': 'Pump P-201B is vibrating',
        'engine': 'whisper',
        'model': 'large-v3',
        'audio_seconds': 4.5,
        'latency_ms': 250,
        'no_speech': false,
      }, 300, 1024);

      expect(response.text, equals('Pam P-201B bergegar'));
      expect(response.englishText, equals('Pump P-201B is vibrating'));
      expect(response.language, equals('ms'));
      expect(response.noSpeech, isFalse);
    });

    test('handles no_speech true case', () async {
      final response = CloudTranscriptionResponse.fromJson({
        'request_id': 'req-456',
        'text': '',
        'language': 'en',
        'english_text': null,
        'engine': 'whisper',
        'model': 'large-v3',
        'audio_seconds': 2.0,
        'latency_ms': 100,
        'no_speech': true,
      }, 150, 512);

      expect(response.noSpeech, isTrue);
    });

    test('english_text is present when translated', () {
      final response = CloudTranscriptionResponse.fromJson({
        'request_id': 'req-789',
        'text': 'P-201B பம்ப் அதிக அதிர்வுடன் உள்ளது',
        'language': 'ta',
        'english_text': 'P-201B pump has high vibration',
        'engine': 'whisper',
        'model': 'large-v3',
        'audio_seconds': 3.2,
        'latency_ms': 210,
        'no_speech': false,
      }, 250, 800);

      expect(response.language, equals('ta'));
      expect(response.englishText, equals('P-201B pump has high vibration'));
    });

    test('handles 401, 413, 504 error statuses', () async {
      final exception401 = CloudTranscriptionException(statusCode: 401, message: 'Unauthorized', code: 'UNAUTHORIZED');
      final exception413 = CloudTranscriptionException(statusCode: 413, message: 'Payload Too Large', code: 'PAYLOAD_TOO_LARGE');
      final exception504 = CloudTranscriptionException(statusCode: 504, message: 'Gateway Timeout', code: 'TIMEOUT');

      expect(exception401.statusCode, equals(401));
      expect(exception413.statusCode, equals(413));
      expect(exception504.statusCode, equals(504));
    });
  });
}
