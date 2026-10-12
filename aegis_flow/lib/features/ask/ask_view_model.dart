import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/ai/cloud_audio_recorder.dart';
import '../../core/config/app_config.dart';
import '../../core/data/handover_repository.dart';
import '../../core/platform/platform_support.dart';
import '../../data/services/api_client.dart';
import '../../data/services/cloud_transcription_service.dart';
import '../../data/services/query_service.dart';

enum MicState { idle, recording, transcribing }

/// One question and everything that came back for it. The documents arrive first (about a second), the answer after.
class AskEntry {
  final String id;
  final String question;
  final DateTime askedAt;
  final PermitInfo? permit;
  final String? asset;
  List<DocHit> docs = const [];
  bool searching = true;
  bool answering = true;
  QueryResult? result;
  String? error;
  bool retryable = true;
  final Set<int> doneSteps = {};
  AskEntry({required this.id, required this.question, required this.askedAt, this.permit, this.asset});
}

/// Query mode: a worker asks a question, optionally while working under a permit or on a piece of equipment, and
/// gets an answer from the plant's documents with sources. Safety verdicts are the server rules' words, shown as sent.
class AskViewModel extends ChangeNotifier {
  final HandoverRepository _repository;
  final QueryService _service;
  final CloudAudioRecorder? _recorderOverride;
  final CloudTranscriptionService? _transcriberOverride;

  AskViewModel({required HandoverRepository repository, QueryService? service, CloudAudioRecorder? recorder, CloudTranscriptionService? transcriber})
      : _repository = repository,
        _service = service ?? QueryService(),
        _recorderOverride = recorder,
        _transcriberOverride = transcriber;

  late final CloudAudioRecorder _recorder = _recorderOverride ?? CloudAudioRecorder();
  late final CloudTranscriptionService _transcriber = _transcriberOverride ?? CloudTranscriptionService();

  final List<AskEntry> entries = [];
  List<PermitInfo> permits = const [];
  int documentCount = 0;
  PermitInfo? permit;
  String? asset;
  MicState mic = MicState.idle;
  String? micNotice;
  bool _contextLoaded = false;
  bool _disposed = false;
  int _n = 0;

  List<String> get assets => _repository.knownAssets;

  /// Called by the screen when a spoken question has been transcribed: it puts the words in the box and asks.
  void Function(String text)? onTranscript;

  /// Loads the permits and how many documents can be searched. Quietly does nothing when offline or on failure.
  Future<void> loadContext({bool force = false}) async {
    if (_contextLoaded && !force) return;
    try {
      final r = await Future.wait([_service.permits(), _service.documentCount()]);
      permits = r[0] as List<PermitInfo>;
      documentCount = r[1] as int;
      _contextLoaded = true;
      _notify();
    } catch (_) {
      // optional context: asking still works without it
    }
  }

  void selectPermit(PermitInfo? p) {
    permit = (permit?.id == p?.id) ? null : p;
    _notify();
  }

  void selectAsset(String? a) {
    asset = (asset == a) ? null : a;
    _notify();
  }

  /// Starters that fit what the worker is doing.
  List<String> get suggestions {
    if (permit != null) {
      return const [
        'What exactly do I need to do for this permit?',
        'What PPE and checks do I need before I start?',
        'What are the stop-work conditions?',
      ];
    }
    if (asset != null) {
      return ['How do I isolate $asset?', 'What must I check before working on $asset?', 'Any bulletins about $asset?'];
    }
    return const ['What are the hot work requirements?', 'How do I isolate a pump safely?', 'What are the gas testing limits?', 'What do I do if a safety valve lifts?'];
  }

  List<String> get followUps => entries.isEmpty ? const [] : (entries.last.result?.followUps ?? const []);

  Future<void> ask(String raw) async {
    final q = raw.trim();
    if (q.length < 2) return;
    final entry = AskEntry(id: 'q${++_n}', question: q, askedAt: DateTime.now(), permit: permit, asset: asset);
    entries.add(entry);
    _notify();
    await _run(entry);
  }

  Future<void> retry(AskEntry e) async {
    e
      ..error = null
      ..result = null
      ..docs = const []
      ..searching = true
      ..answering = true;
    _notify();
    await _run(e);
  }

  Future<void> _run(AskEntry e) async {
    final device = await _repository.deviceId();
    // Two calls at once: the documents come back first, so the worker sees something within about a second.
    final search = _service.search(e.question, permitId: e.permit?.id).then<void>((d) {
      e.docs = d;
    }).catchError((_) {}).whenComplete(() {
      e.searching = false;
      _notify();
    });
    final answer = _service.query(e.question, unit: AppConfig.defaultUnit, assetTag: e.asset, permitId: e.permit?.id, deviceId: device).then<void>((r) {
      e.result = r;
    }).catchError((Object err) {
      e.error = err is ApiException ? err.message : 'Something went wrong. Try again.';
      e.retryable = err is ApiException ? err.retryable : true;
    }).whenComplete(() {
      e.answering = false;
      _notify();
    });
    await Future.wait([search, answer]);
  }

  void toggleStep(AskEntry e, int i) {
    e.doneSteps.contains(i) ? e.doneSteps.remove(i) : e.doneSteps.add(i);
    _notify();
  }

  Future<DocSection> section(String chunkId) => _service.section(chunkId);

  // ------------------------------------------------------------ voice: speak the question
  Future<void> toggleMic() async {
    if (mic == MicState.transcribing) return;
    micNotice = null;
    if (mic == MicState.recording) {
      await _stopAndAsk();
      return;
    }
    final path = await _recorder.startRecording(onMaxDurationReached: () => _stopAndAsk());
    if (path == null) {
      micNotice = 'The microphone is not available. Type your question instead.';
    } else {
      mic = MicState.recording;
    }
    _notify();
  }

  Future<void> _stopAndAsk() async {
    final path = await _recorder.stopRecording();
    if (path == null) {
      mic = MicState.idle;
      _notify();
      return;
    }
    mic = MicState.transcribing;
    _notify();
    try {
      final r = await _transcriber.transcribeAudio(filePath: path, assetHints: assets);
      if (r.noSpeech || r.text.trim().isEmpty) {
        micNotice = "Didn't catch that. Try again, or type it.";
      } else {
        onTranscript?.call(r.text.trim());
        mic = MicState.idle;
        _notify();
        await ask(r.text);
      }
    } catch (_) {
      micNotice = "Couldn't hear that. Try again, or type it.";
    } finally {
      mic = MicState.idle;
      unawaited(deleteRecording(path).catchError((_) {}));
      _notify();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    if (_recorderOverride != null || mic != MicState.idle) _recorder.dispose();
    super.dispose();
  }
}
