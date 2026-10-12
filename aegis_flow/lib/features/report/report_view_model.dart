import 'dart:async';
import 'dart:developer';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/ai/speech_service.dart';
import '../../core/ai/cloud_audio_recorder.dart';
import '../../data/services/cloud_transcription_service.dart';
import '../../core/ai/on_device_ai_service.dart';
import '../../core/ai/fact_model.dart';
import '../../core/platform/platform_support.dart';
import '../../core/data/handover_repository.dart';

enum ReportState { idle, listening, reviewing, saved }

/// What the save overlay is doing, tied to the real calls: saving, saved, syncing, then the outcome.
enum SubmitPhase { reading, saving, saved, syncing, synced, flagged, queued }
enum SpeechPath { onDevice, cloud }

class ReportViewModel extends ChangeNotifier {
  final HandoverRepository _repository;
  final SpeechService _speechService = SpeechService();
  final CloudAudioRecorder _cloudRecorder = CloudAudioRecorder();
  final CloudTranscriptionService _cloudTranscriptionService = CloudTranscriptionService();

  /// Called after a submit finished (saved, and synced if online) so the feed can reload.
  final VoidCallback? onSubmitted;

  ReportViewModel({required HandoverRepository repository, this.onSubmitted})
      : _repository = repository {
    _initSpeech();
  }

  ReportState _state = ReportState.idle;
  SubmitPhase _submitPhase = SubmitPhase.saving;
  SubmitPhase get submitPhase => _submitPhase;
  int _submitConflicts = 0;
  int get submitConflicts => _submitConflicts;
  ReportState get state => _state;

  SpeechPath _activeSpeechPath = SpeechPath.onDevice;
  SpeechPath get activeSpeechPath => _activeSpeechPath;

  String _transcript = '';
  String get transcript => _transcript;

  String? _originalText;
  String? _englishText;
  String? _sourceLanguage;
  bool _showEnglish = true;
  bool get showEnglish => _showEnglish;
  bool get hasTranslation => _englishText != null && _englishText!.isNotEmpty && _englishText != _originalText;

  double _soundLevel = 0.0;
  double get soundLevel => _soundLevel;

  int _listenSeconds = 0;
  int get listenSeconds => _listenSeconds;
  Timer? _timer;

  ExtractionResult? _extractionResult;
  ExtractionResult? get extractionResult => _extractionResult;

  bool _isExtracting = false;
  bool get isExtracting => _isExtracting;

  bool _isTranscribingCloud = false;
  bool get isTranscribingCloud => _isTranscribingCloud;

  String? _cloudErrorNotice;
  String? get cloudErrorNotice => _cloudErrorNotice;

  String? _sttNotice;
  String? get sttNotice => _sttNotice;

  String? _currentAudioPath;

  // ASR Debug Sheet Metrics
  String? lastAsrPath;
  String? lastAsrEngine;
  String? lastAsrModel;
  String? lastAsrLang;
  double? lastAsrAudioSec;
  int? lastAsrUploadBytes;
  int? lastAsrRoundTripMs;
  int? lastAsrServerLatencyMs;
  String? lastAsrError;

  bool _isEdited = false;

  List<String> get knownAssets => _repository.knownAssets;

  StreamSubscription<String>? _transcriptSub;
  StreamSubscription<double>? _soundLevelSub;
  StreamSubscription<double>? _cloudAmpSub;
  StreamSubscription<String?>? _noticeSub;

  void _initSpeech() {
    _speechService.initialize();

    _transcriptSub = _speechService.partialTranscript.listen((text) {
      if (_state == ReportState.listening && _activeSpeechPath == SpeechPath.onDevice) {
        _transcript = text;
        notifyListeners();
      }
    });

    _soundLevelSub = _speechService.soundLevel.listen((level) {
      if (_state == ReportState.listening && _activeSpeechPath == SpeechPath.onDevice) {
        _soundLevel = level;
        notifyListeners();
      }
    });

    _cloudAmpSub = _cloudRecorder.amplitudeStream.listen((level) {
      if (_state == ReportState.listening && _activeSpeechPath == SpeechPath.cloud) {
        _soundLevel = level;
        notifyListeners();
      }
    });

    _noticeSub = _speechService.noticeStream.listen((notice) {
      _sttNotice = notice;
      notifyListeners();
    });
  }

  void startListening() async {
    HapticFeedback.lightImpact();
    _transcript = '';
    _originalText = null;
    _englishText = null;
    _sourceLanguage = null;
    _showEnglish = true;
    _soundLevel = 0.0;
    _listenSeconds = 0;
    _extractionResult = null;
    _isExtracting = false;
    _isTranscribingCloud = false;
    _cloudErrorNotice = null;
    _isEdited = false;
    _currentAudioPath = null;

    // Check health endpoint for cloud path (1.5s timeout / 20s cache)
    final isCloudHealthy = await _cloudTranscriptionService.checkHealth();
    _activeSpeechPath = isCloudHealthy ? SpeechPath.cloud : SpeechPath.onDevice;

    _state = ReportState.listening;
    notifyListeners();

    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      _listenSeconds++;
      notifyListeners();
    });

    if (_activeSpeechPath == SpeechPath.cloud) {
      _currentAudioPath = await _cloudRecorder.startRecording(
        onMaxDurationReached: () {
          stopListening();
        },
      );
    } else {
      await _speechService.startListening();
    }
  }

  void stopListening() async {
    _timer?.cancel();
    HapticFeedback.lightImpact();

    if (_activeSpeechPath == SpeechPath.cloud) {
      final audioPath = await _cloudRecorder.stopRecording();
      _currentAudioPath = audioPath;

      if (audioPath == null) {
        _state = ReportState.idle;
        notifyListeners();
        return;
      }

      _state = ReportState.reviewing;
      _isTranscribingCloud = true;
      notifyListeners();

      await _transcribeCloudAudio(audioPath);
    } else {
      await _speechService.stopListening();

      if (_transcript.trim().isEmpty) {
        _state = ReportState.idle;
        notifyListeners();
        return;
      }

      _state = ReportState.reviewing;
      notifyListeners();

      _runExtraction();
    }
  }

  Future<void> retryCloudTranscription() async {
    if (_currentAudioPath == null) {
      startListening();
      return;
    }

    _cloudErrorNotice = null;
    _isTranscribingCloud = true;
    notifyListeners();

    await _transcribeCloudAudio(_currentAudioPath!);
  }

  Future<void> _transcribeCloudAudio(String audioPath) async {
    try {
      final response = await _cloudTranscriptionService.transcribeAudio(
        filePath: audioPath,
        assetHints: knownAssets,
      );

      _isTranscribingCloud = false;

      // Update ASR Debug Metrics
      lastAsrPath = audioPath;
      lastAsrEngine = response.engine;
      lastAsrModel = response.model;
      lastAsrLang = response.language;
      lastAsrAudioSec = response.audioSeconds;
      lastAsrUploadBytes = response.uploadBytes;
      lastAsrRoundTripMs = response.roundTripMs;
      lastAsrServerLatencyMs = response.latencyMs;
      lastAsrError = null;

      if (response.noSpeech) {
        _cloudErrorNotice = "Didn't catch anything. Tap to try again.";
        _state = ReportState.idle;
        notifyListeners();
        return;
      }

      _originalText = response.text;
      _englishText = response.englishText;
      _sourceLanguage = response.language;
      _transcript = (_englishText != null && _englishText!.isNotEmpty) ? _englishText! : response.text;

      notifyListeners();

      // Run Gemma extraction on the transcription text
      _runExtraction();
    } catch (e) {
      _isTranscribingCloud = false;
      lastAsrError = e.toString();
      _cloudErrorNotice = "Couldn't transcribe. Retry, or type it.";
      log('Cloud transcription failed: $e', name: 'AEGIS_ASR');
      notifyListeners();
    }
  }

  void toggleTranslationLanguage(bool showEng) {
    _showEnglish = showEng;
    if (!_isEdited) {
      if (_showEnglish && _englishText != null && _englishText!.isNotEmpty) {
        _transcript = _englishText!;
      } else if (_originalText != null) {
        _transcript = _originalText!;
      }
      _runExtraction();
    }
    notifyListeners();
  }

  void openKeyboardInput() {
    _state = ReportState.reviewing;
    notifyListeners();
  }

  Timer? _extractDebounce;

  /// Typing fires this per character; the model reads once the typing pauses, not 40 times in a queue.
  void updateTranscript(String newText) {
    _transcript = newText;
    _isEdited = true;
    _extractDebounce?.cancel();
    if (_transcript.trim().isNotEmpty) {
      _isExtracting = true;
      _extractionResult = null;
      _extractDebounce = Timer(const Duration(milliseconds: 700), _runExtraction);
    } else {
      _isExtracting = false;
      _extractionResult = null;
    }
    notifyListeners();
  }

  /// The worker's own correction of what the model read. Works when the model extracted nothing:
  /// a fact is created from the transcript, so the choice is never silently dropped.
  void selectAssetTag(String tag) => _correctFacts(tag: tag);

  void selectAssetState(AssertedState state) => _correctFacts(state: state);

  /// A state the worker picks carries its safety category, unless the fact already has a safety one.
  FactCategory _categoryFor(AssertedState? state, FactCategory current) {
    const safety = {FactCategory.ISOLATION, FactCategory.PERMIT, FactCategory.SAFEGUARD, FactCategory.CONTAINMENT};
    if (state == null || safety.contains(current)) return current;
    if (state == AssertedState.ISOLATED || state == AssertedState.DE_ENERGIZED) return FactCategory.ISOLATION;
    if (state == AssertedState.LEAKING) return FactCategory.CONTAINMENT;
    return current;
  }

  void _correctFacts({String? tag, AssertedState? state}) {
    final r = _extractionResult;
    if (r == null) return;
    final facts = r.facts.isEmpty
        ? [
            Fact(
              id: 'F1',
              category: _categoryFor(state, FactCategory.EQUIPMENT),
              assetTag: tag,
              assertedState: state ?? AssertedState.UNKNOWN,
              text: _transcript.trim(),
              quote: '',
            )
          ]
        : r.facts.map((f) => f.copyWith(assetTag: tag, assertedState: state, category: _categoryFor(state, f.category))).toList();

    _extractionResult = ExtractionResult(
      facts: facts,
      method: r.method,
      schemaValid: r.schemaValid,
      ungroundedFactIds: r.ungroundedFactIds,
      unknownAssetTags: tag == null ? r.unknownAssetTags : r.unknownAssetTags.where((t) => t != tag).toList(),
      inferenceMs: r.inferenceMs,
      rawResponse: r.rawResponse,
    );
    notifyListeners();
  }

  int _extractionVersion = 0;
  Future<void>? _extractionFuture;

  Future<void> _runExtraction() {
    final f = _extract();
    _extractionFuture = f;
    return f;
  }

  Future<void> _extract() async {
    if (_transcript.trim().isEmpty) return;

    final version = ++_extractionVersion;
    _isExtracting = true;
    _extractionResult = null;
    notifyListeners();

    final result = await OnDeviceAiService.instance.extract(
      _transcript,
      _repository.knownAssets,
    );

    if (version != _extractionVersion) return; // the note changed while the model was reading it
    _extractionResult = result;
    _isExtracting = false;
    notifyListeners();
  }

  Future<void> submit({bool isOnline = false}) async {
    if (_transcript.trim().isEmpty) return;
    if (_state == ReportState.saved) return; // a second tap while the first call is running

    HapticFeedback.mediumImpact();

    Map<String, dynamic> transcriptionMap = {};
    if (_activeSpeechPath == SpeechPath.cloud && lastAsrEngine != null) {
      transcriptionMap = {
        'method': 'CLOUD',
        'engine': lastAsrEngine,
        'model': lastAsrModel,
        'language': lastAsrLang,
        'audio_seconds': lastAsrAudioSec,
        'round_trip_ms': lastAsrRoundTripMs,
        'server_latency_ms': lastAsrServerLatencyMs,
        'edited': _isEdited,
      };
    } else {
      transcriptionMap = {
        'method': 'ON_DEVICE_ANDROID',
        'edited': _isEdited,
      };
    }

    _state = ReportState.saved;
    _submitPhase = _isExtracting ? SubmitPhase.reading : SubmitPhase.saving;
    _submitConflicts = 0;
    notifyListeners();

    // A read that is still running (or about to start after typing) finishes first, so the save uses
    // what the worker is looking at instead of starting a second, queued read.
    if (_isExtracting) {
      if (_extractDebounce?.isActive ?? false) {
        _extractDebounce!.cancel();
        _runExtraction(); // typing paused only now: start the single read immediately
      }
      try {
        await (_extractionFuture ?? Future.value()).timeout(const Duration(seconds: 25));
      } catch (_) {}
      _submitPhase = SubmitPhase.saving;
      notifyListeners();
    }

    try {
      await _repository.extractAndSaveObservation(
        transcript: _transcript,
        sourceType: 'VOICE',
        transcriptionData: transcriptionMap,
        sourceLanguage: _sourceLanguage,
        englishText: _englishText,
        // The worker's reviewed choice wins over a fresh model read.
        facts: _extractionResult?.facts,
      );
    } catch (e) {
      log('Saving the observation failed: $e', name: 'AEGIS_REPORT');
      _state = ReportState.reviewing; // nothing was saved: keep the note so it can be retried
      notifyListeners();
      return;
    }

    // Delete audio file on submit
    if (_currentAudioPath != null) {
      try {
        await deleteRecording(_currentAudioPath!);
      } catch (e) {
        log('Failed to delete audio file: $e', name: 'AEGIS_ASR');
      }
    }

    _submitPhase = SubmitPhase.saved;
    notifyListeners();
    await Future.delayed(const Duration(milliseconds: 700));

    if (isOnline) {
      _submitPhase = SubmitPhase.syncing;
      notifyListeners();
      final syncStarted = DateTime.now();
      try {
        await _repository.syncPendingRecords();
        _submitConflicts = _repository.lastSyncConflicts.length;
        _submitPhase = _submitConflicts > 0 ? SubmitPhase.flagged : SubmitPhase.synced;
      } catch (e) {
        log('Sync after submit failed: $e', name: 'AEGIS_SYNC');
        _submitPhase = SubmitPhase.queued;
      }
      // A fast answer would flash past unseen: keep the phase readable for at least 800 ms.
      final spent = DateTime.now().difference(syncStarted);
      if (spent < const Duration(milliseconds: 800)) {
        await Future.delayed(const Duration(milliseconds: 800) - spent);
      }
    } else {
      _submitPhase = SubmitPhase.queued;
    }
    notifyListeners();
    onSubmitted?.call();

    await Future.delayed(Duration(milliseconds: _submitPhase == SubmitPhase.flagged ? 2600 : 1400));
    redo();
  }

  void redo() {
    _timer?.cancel();
    _extractDebounce?.cancel();
    _extractionVersion++;
    _speechService.stopListening();
    _cloudRecorder.cancelRecording();

    _state = ReportState.idle;
    _transcript = '';
    _originalText = null;
    _englishText = null;
    _sourceLanguage = null;
    _showEnglish = true;
    _soundLevel = 0.0;
    _listenSeconds = 0;
    _extractionResult = null;
    _isExtracting = false;
    _isTranscribingCloud = false;
    _cloudErrorNotice = null;
    _isEdited = false;
    _currentAudioPath = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _extractDebounce?.cancel();
    _transcriptSub?.cancel();
    _soundLevelSub?.cancel();
    _cloudAmpSub?.cancel();
    _noticeSub?.cancel();
    _speechService.dispose();
    _cloudRecorder.dispose();
    super.dispose();
  }
}
