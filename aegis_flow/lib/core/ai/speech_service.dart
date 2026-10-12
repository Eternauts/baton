import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:speech_to_text/speech_to_text.dart';

class SpeechService {
  final SpeechToText _speechToText = SpeechToText();
  bool _isInitialized = false;
  bool _isOnDeviceAvailable = false;
  bool _isListening = false;

  final _transcriptController = StreamController<String>.broadcast();
  final _soundLevelController = StreamController<double>.broadcast();
  final _noticeController = StreamController<String?>.broadcast();

  Stream<String> get partialTranscript => _transcriptController.stream;
  Stream<double> get soundLevel => _soundLevelController.stream;
  Stream<String?> get noticeStream => _noticeController.stream;

  bool get isListening => _isListening;
  bool get isOnDeviceAvailable => _isOnDeviceAvailable;

  Future<bool> initialize() async {
    if (_isInitialized) return true;
    try {
      _isInitialized = await _speechToText.initialize(
        onError: (val) {
          debugPrint('STT Error: ${val.errorMsg}');
          _isListening = false;
        },
        onStatus: (val) {
          if (val == 'done' || val == 'notListening') {
            _isListening = false;
          }
        },
      );

      final hasOnDevice = await _speechToText.hasPermission;
      _isOnDeviceAvailable = hasOnDevice;

      if (!_isOnDeviceAvailable) {
        _noticeController.add('On-device speech recognition unavailable. Falling back to system recognizer.');
      }

      return _isInitialized;
    } catch (e) {
      debugPrint('SpeechService init failed: $e');
      _noticeController.add('Speech recognition error: $e');
      return false;
    }
  }

  Future<void> startListening() async {
    if (!_isInitialized) {
      final ok = await initialize();
      if (!ok) return;
    }

    _isListening = true;
    _transcriptController.add('');

    try {
      await _speechToText.listen(
        onResult: (result) {
          _transcriptController.add(result.recognizedWords);
        },
        onSoundLevelChange: (level) {
          _soundLevelController.add(level);
        },
        listenOptions: SpeechListenOptions(
          onDevice: _isOnDeviceAvailable,
          partialResults: true,
        ),
      );
    } catch (e) {
      debugPrint('Error starting listening: $e');
      _isListening = false;
    }
  }

  Future<void> stopListening() async {
    if (_isListening) {
      await _speechToText.stop();
      _isListening = false;
    }
  }

  void dispose() {
    _transcriptController.close();
    _soundLevelController.close();
    _noticeController.close();
  }
}
