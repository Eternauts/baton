import 'dart:async';
import 'dart:convert';
import 'dart:developer';
import 'dart:io';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/widgets.dart';
import 'package:flutter_gemma/flutter_gemma.dart';
import 'package:flutter_gemma_litertlm/flutter_gemma_litertlm.dart';
import 'package:path_provider/path_provider.dart';
import '../../data/services/server_extraction_service.dart';
import 'ai_status.dart';
import 'fact_model.dart';
import 'gemma_prompt_builder.dart';

class ExtractionResult {
  final List<Fact> facts;
  final String method; // "LLM" (on-device), "SERVER_LLM" or "HEURISTIC"
  final bool schemaValid;
  final List<String> ungroundedFactIds;
  final List<String> unknownAssetTags;
  final int inferenceMs;
  final String rawResponse;

  ExtractionResult({
    required this.facts,
    required this.method,
    required this.schemaValid,
    required this.ungroundedFactIds,
    required this.unknownAssetTags,
    required this.inferenceMs,
    required this.rawResponse,
  });
}

class OnDeviceAiService {
  static final OnDeviceAiService instance = OnDeviceAiService._internal();

  OnDeviceAiService._internal();

  final _statusController = StreamController<AiStatus>.broadcast();
  Stream<AiStatus> get status => _statusController.stream;

  AiStatus _currentStatus = const AiStatusLoading();
  AiStatus get currentStatus => _currentStatus;

  InferenceModelSession? _modelSession;
  PreferredBackend? _activeBackend;
  int _lastLoadMs = 0;
  int _lastInferenceMs = 0;
  double _lastTokensPerSec = 0.0;
  String _modelPath = '';
  int _modelSizeBytes = 0;

  PreferredBackend? get activeBackend => _activeBackend;
  int get lastLoadMs => _lastLoadMs;
  int get lastInferenceMs => _lastInferenceMs;
  double get lastTokensPerSec => _lastTokensPerSec;
  String get modelPath => _modelPath;
  int get modelSizeBytes => _modelSizeBytes;

  /// TODO: In-app download stub for gemma-4-E2B-it.litertlm from HuggingFace
  Future<void> downloadModelInApp({
    required Function(double progress) onProgress,
  }) async {
    // Stub for future in-app downloader UI integration
    throw UnimplementedError('In-app download will be enabled in a future release.');
  }

  /// Whether the server may be asked to read a note when the on-device model cannot. The app turns this off
  /// while the user has chosen offline mode; the website has no on-device model, so it uses the server always.
  bool remoteAllowed = kIsWeb;
  final ServerExtractionService _remote = ServerExtractionService();

  void initializeInBackground() {
    if (kIsWeb) {
      _updateStatus(const AiStatusCloud());
      return;
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _initGemma();
    });
  }

  Future<void> _initGemma() async {
    _updateStatus(const AiStatusLoading());
    final stopwatch = Stopwatch()..start();

    try {
      // Locate external files directory: /sdcard/Android/data/com.aegisflow.aegis_flow/files/models/
      Directory? extDir;
      if (Platform.isAndroid) {
        final dirs = await getExternalStorageDirectories();
        if (dirs != null && dirs.isNotEmpty) {
          extDir = dirs.first;
        }
      }
      extDir ??= await getApplicationDocumentsDirectory();

      final modelsDir = Directory('${extDir.path}/models');
      if (!await modelsDir.exists()) {
        await modelsDir.create(recursive: true);
      }

      _modelPath = '${modelsDir.path}/gemma-4-E4B-it.litertlm';
      var modelFile = File(_modelPath);

      if (!await modelFile.exists()) {
        final fallbackE2b = File('${modelsDir.path}/gemma-4-E2B-it.litertlm');
        if (await fallbackE2b.exists()) {
          _modelPath = fallbackE2b.path;
          modelFile = fallbackE2b;
        } else {
          final litertLmFiles = modelsDir
              .listSync()
              .whereType<File>()
              .where((f) => f.path.endsWith('.litertlm'))
              .toList();
          if (litertLmFiles.isNotEmpty) {
            modelFile = litertLmFiles.first;
            _modelPath = modelFile.path;
          }
        }
      }

      if (!await modelFile.exists()) {
        _updateStatus(AiStatusNotInstalled(modelPath: _modelPath));
        log('Gemma model file not found at: $_modelPath', name: 'AEGIS_AI');
        return;
      }

      _modelSizeBytes = await modelFile.length();
      final fileSizeMb = _modelSizeBytes ~/ (1024 * 1024);

      // Initialize FlutterGemma with LiteRtLmEngine
      await FlutterGemma.initialize(
        inferenceEngines: [const LiteRtLmEngine()],
      );

      // Register installed local model
      await FlutterGemma.installModel(
        modelType: ModelType.gemmaIt,
        fileType: ModelFileType.litertlm,
      ).fromFile(_modelPath).install();

      // Try GPU backend first, fall back to CPU if GPU fails
      bool success = await _attemptLoadBackend(PreferredBackend.gpu, stopwatch, fileSizeMb);
      if (!success) {
        log('GPU backend initialization failed. Falling back to CPU backend...', name: 'AEGIS_AI');
        success = await _attemptLoadBackend(PreferredBackend.cpu, stopwatch, fileSizeMb);
      }

      if (!success) {
        _updateStatus(const AiStatusError('Failed to initialize model on both GPU and CPU backends.'));
      }
    } catch (e, st) {
      log('Error during Gemma initialization: $e\n$st', name: 'AEGIS_AI');
      _updateStatus(AiStatusError(e.toString()));
    }
  }

  Future<bool> _attemptLoadBackend(
    PreferredBackend backend,
    Stopwatch stopwatch,
    int fileSizeMb,
  ) async {
    try {
      final model = await FlutterGemma.getActiveModel(
        maxTokens: 1024,
        preferredBackend: backend,
      );

      _modelSession = await model.createSession(
        temperature: 0.1,
        systemInstruction: GemmaPromptBuilder.buildSystemInstruction(),
      );

      stopwatch.stop();
      _lastLoadMs = stopwatch.elapsedMilliseconds;
      _activeBackend = model.activeBackend ?? backend;

      log('AEGIS_AI initialized successfully! Backend: ${_activeBackend?.name}, Load time: ${_lastLoadMs}ms', name: 'AEGIS_AI');

      _updateStatus(AiStatusReady(
        backend: _activeBackend!,
        loadMs: _lastLoadMs,
        modelPath: _modelPath,
        fileSizeMb: fileSizeMb,
      ));
      return true;
    } catch (e) {
      log('Failed to load backend ${backend.name}: $e', name: 'AEGIS_AI');
      return false;
    }
  }

  void _updateStatus(AiStatus status) {
    _currentStatus = status;
    _statusController.add(status);
  }

  Future<ExtractionResult> extract(
    String transcript,
    List<String> knownAssets,
  ) async {
    if (_currentStatus is! AiStatusReady || _modelSession == null) {
      if (remoteAllowed) {
        final remote = await _remote.extract(transcript, knownAssets);
        if (remote != null) {
          return _parseAndValidateResponse(remote.raw, transcript, knownAssets, remote.latencyMs, isRetry: false, method: 'SERVER_LLM');
        }
      }
      log('Model not ready. Using fallback heuristic extraction.', name: 'AEGIS_AI');
      return _runHeuristicExtraction(transcript, knownAssets, 'Model not initialized');
    }

    final prompt = GemmaPromptBuilder.buildUserPrompt(transcript, knownAssets);
    final stopwatch = Stopwatch()..start();

    try {
      await _modelSession!.addQueryChunk(Message.text(text: prompt, isUser: true));

      // 20-second timeout for LLM response
      final responseFuture = _modelSession!.getResponse();
      final rawResponse = await responseFuture.timeout(const Duration(seconds: 20));

      stopwatch.stop();
      _lastInferenceMs = stopwatch.elapsedMilliseconds;

      final outputChars = rawResponse.length;
      final estTokens = outputChars / 4.0;
      _lastTokensPerSec = _lastInferenceMs > 0 ? (estTokens / (_lastInferenceMs / 1000.0)) : 0.0;

      log(
        'Backend: ${_activeBackend?.name}, In Chars: ${prompt.length}, Out Chars: $outputChars, '
        'Wall Time: ${_lastInferenceMs}ms, Speed: ${_lastTokensPerSec.toStringAsFixed(1)} tok/s',
        name: 'AEGIS_AI',
      );

      // Parse and validate JSON output
      return _parseAndValidateResponse(
        rawResponse,
        transcript,
        knownAssets,
        _lastInferenceMs,
        isRetry: false,
      );
    } on TimeoutException {
      stopwatch.stop();
      log('LLM extraction timed out after 20 seconds. Falling back to heuristic.', name: 'AEGIS_AI');
      return _runHeuristicExtraction(transcript, knownAssets, 'Timeout (20s)');
    } catch (e) {
      stopwatch.stop();
      log('LLM extraction error: $e. Retrying once...', name: 'AEGIS_AI');
      return _retryExtractionWithFeedback(prompt, e.toString(), transcript, knownAssets);
    }
  }

  Future<ExtractionResult> _retryExtractionWithFeedback(
    String prompt,
    String errorMsg,
    String transcript,
    List<String> knownAssets,
  ) async {
    final retryStopwatch = Stopwatch()..start();
    try {
      final retryPrompt = '$prompt\n\nPrevious attempt failed with error: $errorMsg. Return ONLY valid JSON matching the schema.';
      await _modelSession!.addQueryChunk(Message.text(text: retryPrompt, isUser: true));
      final rawResponse = await _modelSession!.getResponse().timeout(const Duration(seconds: 15));
      retryStopwatch.stop();

      return _parseAndValidateResponse(
        rawResponse,
        transcript,
        knownAssets,
        retryStopwatch.elapsedMilliseconds,
        isRetry: true,
      );
    } catch (e) {
      retryStopwatch.stop();
      log('Retry failed ($e). Falling back to heuristic.', name: 'AEGIS_AI');
      return _runHeuristicExtraction(transcript, knownAssets, 'Parse/Retry Error');
    }
  }

  ExtractionResult _parseAndValidateResponse(
    String rawResponse,
    String transcript,
    List<String> knownAssets,
    int inferenceMs, {
    required bool isRetry,
    String method = 'LLM',
  }) {
    final cleaned = GemmaPromptBuilder.sanitizeJsonResponse(rawResponse);

    try {
      final map = jsonDecode(cleaned) as Map<String, dynamic>;
      final rawFactsList = (map['facts'] as List?) ?? [];

      final List<Fact> facts = [];
      final List<String> ungroundedFactIds = [];
      final List<String> unknownAssetTags = [];

      final normalizedTranscript = transcript.toLowerCase().replaceAll(RegExp(r'\s+'), ' ');

      for (int i = 0; i < rawFactsList.length; i++) {
        final factMap = Map<String, dynamic>.from(rawFactsList[i] as Map);
        var fact = Fact.fromJson(factMap, i);
        // The models describe a fact with a quote, not free text: show the quote (or the note) instead of a blank line.
        if (fact.text.trim().isEmpty) {
          fact = fact.copyWith(text: fact.quote.trim().isNotEmpty ? fact.quote : transcript);
        }

        if (fact.assetTag != null && fact.assetTag!.isNotEmpty) {
          final inTranscript = Fact.transcriptContainsTag(transcript, fact.assetTag!);
          if (!inTranscript) {
            fact = fact.copyWith(assetTag: null);
          } else {
            final snapped = Fact.snapToKnownAsset(fact.assetTag!, knownAssets);
            if (snapped != null) fact = fact.copyWith(assetTag: snapped);
            final normTag = Fact.normalizeAssetTag(fact.assetTag!);
            final normKnown = knownAssets.map((a) => Fact.normalizeAssetTag(a)).toSet();
            if (!normKnown.contains(normTag)) {
              unknownAssetTags.add(normTag);
            }
          }
        }

        facts.add(fact);

        // Grounding check
        final normQuote = fact.quote.toLowerCase().replaceAll(RegExp(r'\s+'), ' ');
        if (normQuote.isNotEmpty && !normalizedTranscript.contains(normQuote)) {
          ungroundedFactIds.add(fact.id);
        }
      }

      return ExtractionResult(
        facts: facts,
        method: method,
        schemaValid: true,
        ungroundedFactIds: ungroundedFactIds,
        unknownAssetTags: unknownAssetTags,
        inferenceMs: inferenceMs,
        rawResponse: rawResponse,
      );
    } catch (e) {
      log('JSON parsing error: $e', name: 'AEGIS_AI');
      return _runHeuristicExtraction(transcript, knownAssets, 'JSON Parse Error');
    }
  }

  ExtractionResult _runHeuristicExtraction(
    String transcript,
    List<String> knownAssets,
    String reason,
  ) {
    final facts = <Fact>[];
    final upper = transcript.toUpperCase();

    String? detectedTag;
    for (final asset in knownAssets) {
      final norm = Fact.normalizeAssetTag(asset);
      if (upper.contains(norm) || upper.contains(norm.replaceAll('-', ''))) {
        detectedTag = norm;
        break;
      }
    }

    if (detectedTag != null || transcript.isNotEmpty) {
      final lower = transcript.toLowerCase();
      AssertedState state = AssertedState.UNKNOWN;
      FactCategory category = FactCategory.EQUIPMENT;

      if (lower.contains('leak') || lower.contains('bocor') || lower.contains('wet')) {
        state = AssertedState.LEAKING;
        category = FactCategory.CONTAINMENT;
      } else if (lower.contains('vibrat') || lower.contains('gegar')) {
        state = AssertedState.RUNNING;
        category = FactCategory.EQUIPMENT;
      } else if (lower.contains('isolate') || lower.contains('loto')) {
        state = AssertedState.ISOLATED;
        category = FactCategory.ISOLATION;
      }

      facts.add(Fact(
        id: 'F1',
        category: category,
        assetTag: detectedTag,
        assertedState: state,
        text: transcript,
        quote: transcript,
      ));
    }

    return ExtractionResult(
      facts: facts,
      method: 'HEURISTIC',
      schemaValid: false,
      ungroundedFactIds: [],
      unknownAssetTags: [],
      inferenceMs: 0,
      rawResponse: 'Fallback Heuristic ($reason)',
    );
  }
}
