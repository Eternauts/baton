import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../ai/on_device_ai_service.dart';
import '../ai/fact_model.dart';
import '../ai/escalation.dart';
import 'observation_capsule.dart';
import '../../data/services/cloud_storage_service.dart';
import '../../data/services/baton_sync_service.dart';
import '../../data/services/device_updates_service.dart';
import '../../data/models/scada_sensor_model.dart';
import '../../data/models/chat_message_model.dart';

class HandoverRepository {
  static const String _capsulesKey = 'aegis_flow_observation_capsules_v2';
  static const String _seqKey = 'aegis_flow_seq_counter';
  static const String _deviceIdKey = 'aegis_flow_device_id';
  static const String _offlineModeKey = 'aegis_flow_offline_mode_active';

  final CloudStorageService _cloudStorageService;
  final BatonSyncService _batonSyncService = BatonSyncService();
  final DeviceUpdatesService _updatesService = DeviceUpdatesService();

  /// Safety conflicts the server flagged in the most recent sync (empty when there were none).
  List<dynamic> lastSyncConflicts = const [];
  final _uuid = const Uuid();

  List<String> knownAssets = ['P-201B', 'T-310A', 'V-104', 'F-501'];

  final Map<String, ScadaSensorModel> _scadaDatabase = {
    'P-201B': ScadaSensorModel(
      tag: 'P-201B',
      equipmentName: 'Crude Export Booster Pump B',
      currentValue: 1.25,
      unit: 'mm/s (Vibration)',
      normalMin: 0.5,
      normalMax: 4.5,
      status: 'NORMAL',
      lastTelemetry: DateTime.now().subtract(const Duration(minutes: 4)),
    ),
    'T-310A': ScadaSensorModel(
      tag: 'T-310A',
      equipmentName: 'Fractionator Overhead Receiver',
      currentValue: 114.8,
      unit: '°C (Temp)',
      normalMin: 65.0,
      normalMax: 95.0,
      status: 'WARNING',
      lastTelemetry: DateTime.now().subtract(const Duration(minutes: 8)),
    ),
    'V-104': ScadaSensorModel(
      tag: 'V-104',
      equipmentName: 'Fuel Gas High Pressure Letdown Valve',
      currentValue: 35.0,
      unit: '% Open',
      normalMin: 20.0,
      normalMax: 80.0,
      status: 'NORMAL',
      lastTelemetry: DateTime.now().subtract(const Duration(minutes: 12)),
    ),
    'F-501': ScadaSensorModel(
      tag: 'F-501',
      equipmentName: 'Separator Coalescer Filter',
      currentValue: 2.8,
      unit: 'bar (Diff Press)',
      normalMin: 0.2,
      normalMax: 1.5,
      status: 'CRITICAL',
      lastTelemetry: DateTime.now().subtract(const Duration(minutes: 2)),
    ),
  };

  Map<String, ScadaSensorModel> get scadaSensors => Map.unmodifiable(_scadaDatabase);

  HandoverRepository({CloudStorageService? cloudStorageService})
      : _cloudStorageService = cloudStorageService ?? CloudStorageService();

  Future<bool> isOfflineMode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_offlineModeKey) ?? !kIsWeb; // the website has no airplane mode to simulate: it starts online
  }

  Future<void> setOfflineMode(bool isOffline) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_offlineModeKey, isOffline);
  }

  Future<String> _getDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    var devId = prefs.getString(_deviceIdKey);
    if (devId == null) {
      devId = '${kIsWeb ? 'web' : 'android'}-${_uuid.v4().substring(0, 8)}'; // so web visitors are told apart in the data
      await prefs.setString(_deviceIdKey, devId);
    }
    return devId;
  }

  Future<int> _getNextSeq() async {
    final prefs = await SharedPreferences.getInstance();
    final seq = (prefs.getInt(_seqKey) ?? 0) + 1;
    await prefs.setInt(_seqKey, seq);
    return seq;
  }

  Future<List<ObservationCapsule>> getObservations() async {
    final prefs = await SharedPreferences.getInstance();
    final jsonList = prefs.getStringList(_capsulesKey) ?? [];
    if (jsonList.isNotEmpty) {
      return jsonList
          .map((item) => ObservationCapsule.fromJson(item))
          .toList();
    }

    final seeded = await _seedInitialCapsules();
    return seeded;
  }

  Future<List<ObservationCapsule>> _seedInitialCapsules() async {
    final deviceId = await _getDeviceId();
    final now = DateTime.now();

    final f1 = Fact(
      id: 'F1',
      category: FactCategory.EQUIPMENT,
      assetTag: 'P-201B',
      assertedState: AssertedState.RUNNING,
      text: 'P-201B vibrating heavily and mechanical seal looks wet at 14:30',
      quote: 'P-201B vibrating heavily, seal looks wet',
    );

    final esc1 = calculateEscalation(
      transcript: f1.text,
      facts: [f1],
      extractionMethod: 'LLM',
      schemaValid: true,
      ungroundedFactIds: [],
      knownAssets: knownAssets,
    );

    final capsule1 = ObservationCapsule(
      eventId: _uuid.v4(),
      deviceId: deviceId,
      seq: 1,
      unitName: 'Unit 3 - Crude Pumping Area',
      shiftName: 'Alpha Shift',
      operatorId: 'OP-8821',
      observedAt: DateTime(now.year, now.month, now.day, 14, 30),
      sourceType: 'VOICE',
      language: 'en',
      transcript: 'P-201B vibrating heavily, seal looks wet, 14:30',
      facts: [f1],
      evidence: ObservationCapsule.buildEvidence('P-201B vibrating heavily, seal looks wet, 14:30'),
      extraction: {
        'method': 'LLM',
        'model': 'gemma-4-E4B-it',
        'schema_valid': true,
        'ungrounded_fact_ids': [],
        'unknown_asset_tags': [],
      },
      transcription: {
        'method': 'ON_DEVICE_ANDROID',
        'edited': false,
      },
      escalation: esc1,
      rawSizeBytes: 128,
      isSynced: false,
      discrepancyAlert: 'Discrepancy: P-201B vibration high per field log, but SCADA shows normal (1.25 mm/s).',
      scadaComparison: 'SCADA: 1.25 mm/s (NORMAL)',
    );

    final list = [capsule1];
    await saveCapsules(list);
    return list;
  }

  Future<void> saveCapsules(List<ObservationCapsule> list) async {
    final prefs = await SharedPreferences.getInstance();
    final jsonList = list.map((c) => c.toJson()).toList();
    await prefs.setStringList(_capsulesKey, jsonList);
  }

  Future<ObservationCapsule> extractAndSaveObservation({
    required String transcript,
    String sourceType = 'VOICE',
    bool hasAudioOrImage = false,
    Map<String, dynamic>? transcriptionData,
    String? sourceLanguage,
    String? englishText,
    List<Fact>? facts,
  }) async {
    final deviceId = await _getDeviceId();
    final seq = await _getNextSeq();

    // Facts the worker reviewed on the Report screen are used as they are; only a missing review
    // falls back to running the model again.
    final extraction = facts != null && facts.isNotEmpty
        ? ExtractionResult(
            facts: facts,
            method: 'REVIEWED',
            schemaValid: true,
            ungroundedFactIds: const [],
            unknownAssetTags: const [],
            inferenceMs: 0,
            rawResponse: '',
          )
        : await OnDeviceAiService.instance.extract(transcript, knownAssets);

    final escalation = calculateEscalation(
      transcript: transcript,
      facts: extraction.facts,
      extractionMethod: extraction.method,
      schemaValid: extraction.schemaValid,
      ungroundedFactIds: extraction.ungroundedFactIds,
      knownAssets: knownAssets,
      hasAudioOrImage: hasAudioOrImage,
    );

    String? discrepancy;
    String? scadaComp;
    for (final fact in extraction.facts) {
      if (fact.assetTag == 'P-201B' && (fact.assertedState == AssertedState.LEAKING || fact.assertedState == AssertedState.RUNNING)) {
        discrepancy = 'Discrepancy: P-201B high vibration/leak per field observation, but SCADA reads normal (1.25 mm/s).';
        scadaComp = 'SCADA: 1.25 mm/s (NORMAL)';
        break;
      }
    }

    final capsule = ObservationCapsule(
      eventId: _uuid.v4(),
      deviceId: deviceId,
      seq: seq,
      unitName: 'Unit 3 - Crude Pumping Area',
      shiftName: 'Alpha Shift',
      operatorId: 'OP-8821',
      observedAt: DateTime.now(),
      sourceType: sourceType,
      language: 'en',
      sourceLanguage: sourceLanguage,
      englishText: englishText,
      transcript: transcript,
      facts: extraction.facts,
      evidence: ObservationCapsule.buildEvidence(transcript),
      extraction: {
        'method': extraction.method,
        'model': extraction.method == 'SERVER_LLM' ? 'server-gemini' : 'gemma-4-E4B-it',
        'schema_valid': extraction.schemaValid,
        'ungrounded_fact_ids': extraction.ungroundedFactIds,
        'unknown_asset_tags': extraction.unknownAssetTags,
      },
      transcription: transcriptionData ?? {
        'method': 'ON_DEVICE_ANDROID',
        'edited': false,
      },
      escalation: escalation,
      rawSizeBytes: transcript.length,
      isSynced: false,
      discrepancyAlert: discrepancy,
      scadaComparison: scadaComp,
    );

    final current = await getObservations();
    current.insert(0, capsule);
    await saveCapsules(current);

    return capsule;
  }

  Future<ChatMessageModel> askAssistant({
    required String query,
    required dynamic currentLogs,
  }) async {
    return ChatMessageModel(
      id: _uuid.v4(),
      sender: 'gemma',
      message: 'On-device Gemma 4 E2B is configured for extraction. Assistant Q&A will query active shift capsules.',
      detectedLanguage: 'en',
      citations: ['SHIFT-LOGS: Active shift capsules'],
      hasAlert: false,
      timestamp: DateTime.now(),
    );
  }

  Future<List<ObservationCapsule>>? _syncInFlight;

  /// One sync at a time: the Report screen and the Feed can both ask, and a second concurrent call
  /// would re-send the same pending capsules (one duplicate handover and agent run each).
  Future<List<ObservationCapsule>> syncPendingRecords() {
    final running = _syncInFlight;
    if (running != null) return running;
    final f = _syncPendingRecordsOnce();
    _syncInFlight = f;
    return f.whenComplete(() => _syncInFlight = null);
  }

  Future<List<ObservationCapsule>> _syncPendingRecordsOnce() async {
    final currentList = await getObservations();
    final pendingCapsules = currentList.where((c) => !c.isSynced).toList();
    if (pendingCapsules.isEmpty) return currentList;

    final deviceId = await _getDeviceId();

    // Use BatonSyncService for batch sync
    final result = await _batonSyncService.syncPendingCapsules(pendingCapsules, deviceId);

    // HTTP 200 with CONFLICT_DETECTED means the server RECEIVED and stored the capsules and flagged a
    // safety conflict. They are delivered, so they must leave the pending queue; keeping them pending
    // re-sent the same capsule on every sync (one agent run each) and showed "Sync failed".
    if (result is SyncSuccess || result is SyncConflict) {
      lastSyncConflicts = result is SyncConflict ? result.conflicts : const [];
      final conflicts = lastSyncConflicts;
      final updatedList = currentList.map((obs) {
        if (!obs.isSynced) {
          return obs.copyWith(
            isSynced: true,
            syncedAt: DateTime.now(),
            serverFlags: _flagsFor(obs, conflicts),
          );
        }
        return obs;
      }).toList();
      await saveCapsules(updatedList);
      return updatedList;
    } else if (result is SyncError) {
      throw Exception(result.message);
    }
    
    return currentList;
  }

  /// Conflicts that concern this capsule: they cite its event id, or name its asset tag in the title.
  List<Map<String, dynamic>> _flagsFor(ObservationCapsule c, List<dynamic> conflicts) {
    final tag = c.facts.isNotEmpty ? c.facts.first.assetTag : null;
    final out = <Map<String, dynamic>>[];
    for (final raw in conflicts) {
      if (raw is! Map) continue;
      final evidence = (raw['evidence_ids'] as List? ?? const []).map((e) => e.toString());
      final title = raw['title']?.toString() ?? '';
      final cites = evidence.contains(c.eventId) || (tag != null && tag.isNotEmpty && title.contains(tag));
      if (!cites) continue;
      out.add({
        'rule_id': raw['rule_id']?.toString() ?? '',
        'title': title,
        'severity': raw['severity']?.toString() ?? 'CRITICAL',
      });
    }
    return out;
  }

  /// Latest safety updates the cloud published for this device's unit; null if they could not be read.
  Future<List<DeviceUpdate>?> fetchDeviceUpdates() async => _updatesService.fetch(await _getDeviceId());

  /// This shift's reports (today's), newest first. The handover interview is about these.
  Future<List<ObservationCapsule>> shiftCapsules() async {
    final now = DateTime.now();
    final list = (await getObservations())
        .where((c) => c.observedAt.year == now.year && c.observedAt.month == now.month && c.observedAt.day == now.day)
        .toList()
      ..sort((a, b) => b.observedAt.compareTo(a.observedAt));
    return list;
  }

  /// Sends the whole shift to the server as one handover (the same capsules always give the same id, so
  /// starting again does not create another) and returns its id for the interview. Anything still pending
  /// is delivered by the same call, so it is marked synced.
  Future<({String handoverId, List<dynamic> conflicts})> syncShiftForInterview() async {
    final shift = await shiftCapsules();
    if (shift.isEmpty) throw Exception('There are no reports from this shift to hand over yet.');
    final result = await _batonSyncService.syncPendingCapsules(shift, await _getDeviceId());
    String? id;
    List<dynamic> conflicts = const [];
    if (result is SyncSuccess) {
      id = result.handoverId;
    } else if (result is SyncConflict) {
      id = result.handoverId;
      conflicts = result.conflicts;
    } else if (result is SyncError) {
      throw Exception(result.message);
    }
    if (id == null || id.isEmpty) throw Exception('The server did not return a handover id. Update the server and try again.');

    final all = await getObservations();
    final shiftIds = shift.map((c) => c.eventId).toSet();
    await saveCapsules(all.map((c) {
      if (!shiftIds.contains(c.eventId)) return c;
      return c.copyWith(isSynced: true, syncedAt: c.syncedAt ?? DateTime.now(), serverFlags: _flagsFor(c, conflicts));
    }).toList());
    lastSyncConflicts = conflicts;
    return (handoverId: id, conflicts: conflicts);
  }
}
