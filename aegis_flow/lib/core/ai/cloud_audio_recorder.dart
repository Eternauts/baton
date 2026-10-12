import 'dart:async';
import 'dart:developer';
import 'dart:io';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

class CloudAudioRecorder {
  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription? _amplitudeSub;
  Timer? _maxDurationTimer;

  final _amplitudeController = StreamController<double>.broadcast();
  Stream<double> get amplitudeStream => _amplitudeController.stream;

  bool _isRecording = false;
  bool get isRecording => _isRecording;

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<String?> startRecording({
    required Function() onMaxDurationReached,
  }) async {
    if (!await _recorder.hasPermission()) {
      log('Microphone permission denied for CloudAudioRecorder', name: 'AEGIS_ASR');
      return null;
    }

    // Android records to a file in the cache. A browser records into memory and returns a blob: URL when it stops.
    String filePath = '';
    if (!kIsWeb) {
      final cacheDir = await getApplicationCacheDirectory();
      final audioDir = Directory('${cacheDir.path}/audio_recordings');
      if (!await audioDir.exists()) {
        await audioDir.create(recursive: true);
      }
      filePath = '${audioDir.path}/rec_${DateTime.now().millisecondsSinceEpoch}.m4a';
    }

    try {
      await _recorder.start(
        const RecordConfig(
          encoder: kIsWeb ? AudioEncoder.opus : AudioEncoder.aacLc, // browsers record webm/opus; the server detects it
          sampleRate: 44100, // Fixed sample rate to prevent backend hallucination
          numChannels: 1,
          autoGain: true,
          echoCancel: true,
          noiseSuppress: true,
        ),
        path: filePath,
      );

      _isRecording = true;

      // Amplitude change stream (dBFS -160 to 0) -> map to 0.0 .. 10.0
      _amplitudeSub?.cancel();
      _amplitudeSub = _recorder.onAmplitudeChanged(const Duration(milliseconds: 100)).listen((amp) {
        final currentDb = amp.current; // e.g. -60 to 0
        final normalized = ((currentDb + 60) / 6.0).clamp(0.0, 10.0);
        _amplitudeController.add(normalized);
      });

      // 55 seconds hard stop
      _maxDurationTimer?.cancel();
      _maxDurationTimer = Timer(const Duration(seconds: 55), () {
        log('55s hard stop reached for cloud audio recording', name: 'AEGIS_ASR');
        onMaxDurationReached();
      });

      return kIsWeb ? 'web-recording' : filePath;
    } catch (e) {
      log('Failed to start CloudAudioRecorder: $e', name: 'AEGIS_ASR');
      _isRecording = false;
      return null;
    }
  }

  Future<String?> stopRecording() async {
    _maxDurationTimer?.cancel();
    _amplitudeSub?.cancel();

    if (!_isRecording) return null;

    try {
      final path = await _recorder.stop();
      _isRecording = false;
      return path;
    } catch (e) {
      log('Failed to stop CloudAudioRecorder: $e', name: 'AEGIS_ASR');
      _isRecording = false;
      return null;
    }
  }

  Future<void> cancelRecording() async {
    _maxDurationTimer?.cancel();
    _amplitudeSub?.cancel();
    if (_isRecording) {
      await _recorder.cancel();
      _isRecording = false;
    }
  }

  void dispose() {
    _maxDurationTimer?.cancel();
    _amplitudeSub?.cancel();
    _amplitudeController.close();
    _recorder.dispose();
  }
}
