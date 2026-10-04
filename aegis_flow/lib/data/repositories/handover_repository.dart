import 'dart:async';
import 'package:uuid/uuid.dart';
import '../models/observation_model.dart';
import '../models/scada_sensor_model.dart';
import '../models/chat_message_model.dart';
import '../services/local_storage_service.dart';
import '../services/cloud_storage_service.dart';
import '../services/gemma_inference_service.dart';

/// Single source of truth for shift handover records, offline buffer & cloud sync
class HandoverRepository {
  final LocalStorageService _localStorageService;
  final CloudStorageService _cloudStorageService;
  final GemmaInferenceService _gemmaService;
  final _uuid = const Uuid();

  HandoverRepository({
    LocalStorageService? localStorageService,
    CloudStorageService? cloudStorageService,
    GemmaInferenceService? gemmaService,
  })  : _localStorageService = localStorageService ?? LocalStorageService(),
        _cloudStorageService = cloudStorageService ?? CloudStorageService(),
        _gemmaService = gemmaService ?? GemmaInferenceService();

  Map<String, ScadaSensorModel> get scadaSensors => _gemmaService.scadaSensors;

  /// Loads all observations from local buffer, seeding initial poster demo records if empty
  Future<List<ObservationModel>> getObservations() async {
    final cached = await _localStorageService.getLocalObservations();
    if (cached.isNotEmpty) {
      return cached;
    }

    // Seed default records matching the AEGIS Flow poster
    final now = DateTime.now();
    final seeded = [
      ObservationModel(
        id: _uuid.v4(),
        rawInput: 'P-201B vibrating heavily, seal looks wet, 14:30',
        language: 'en',
        tag: 'P-201B',
        anomaly: 'vibration & seal weeping',
        severity: 4,
        unit: 'Unit 3 - Crude Pumping Area',
        actionRequired: 'Mechanical inspection required before restart',
        timestamp: DateTime(now.year, now.month, now.day, 14, 30),
        isSynced: false, // In offline queue
        discrepancyAlert: 'Discrepancy: P-201B vibration high per field log, but SCADA shows normal. Review required.',
        scadaComparison: 'SCADA: 1.25 mm/s (NORMAL)',
      ),
      ObservationModel(
        id: _uuid.v4(),
        rawInput: 'T-310A overhead receiver temperature running high at 114 deg C',
        language: 'en',
        tag: 'T-310A',
        anomaly: 'temp high',
        severity: 3,
        unit: 'Unit 2 - Fractionator Overhead',
        actionRequired: 'Verify fin-fan coolers and trim bypass',
        timestamp: DateTime(now.year, now.month, now.day, 12, 15),
        isSynced: true,
        syncedAt: DateTime(now.year, now.month, now.day, 12, 20),
        scadaComparison: 'SCADA: 114.8 °C (WARNING)',
      ),
      ObservationModel(
        id: _uuid.v4(),
        rawInput: 'V-104 fuel gas letdown valve position confirmed locked under PTW-2026-0881',
        language: 'en',
        tag: 'V-104',
        anomaly: 'valve position locked',
        severity: 2,
        unit: 'Fuel Gas Skid 01',
        actionRequired: 'Maintain LOTO car-seal lock',
        timestamp: DateTime(now.year, now.month, now.day, 10, 42),
        isSynced: true,
        syncedAt: DateTime(now.year, now.month, now.day, 10, 45),
        scadaComparison: 'SCADA: 35.0% Open (NORMAL)',
      ),
    ];

    await _localStorageService.updateObservations(seeded);
    return seeded;
  }

  /// Extracts structured observation using Gemma 2B INT4 and buffers locally
  Future<ObservationModel> extractAndSaveObservation({
    required String rawText,
    String? explicitLanguage,
  }) async {
    final extracted = await _gemmaService.extractObservationFromInput(
      rawText: rawText,
      explicitLanguage: explicitLanguage,
    );

    // Save to local zero-loss SQLite buffer
    await _localStorageService.saveObservation(extracted);
    return extracted;
  }

  /// Syncs offline buffered records to Google Cloud Storage
  Future<List<ObservationModel>> syncPendingRecords() async {
    final currentList = await _localStorageService.getLocalObservations();
    final pending = currentList.where((obs) => !obs.isSynced).toList();

    if (pending.isEmpty) {
      return currentList;
    }

    final updated = await _cloudStorageService.syncBatch(currentList);
    await _localStorageService.updateObservations(updated);
    return updated;
  }

  /// Multilingual RAG shift assistant
  Future<ChatMessageModel> askAssistant({
    required String query,
    required List<ObservationModel> currentLogs,
  }) async {
    return await _gemmaService.answerShiftWorkerQuery(
      query: query,
      activeLogs: currentLogs,
    );
  }

  Future<bool> isOfflineMode() => _localStorageService.isOfflineMode();
  Future<void> setOfflineMode(bool isOffline) => _localStorageService.setOfflineMode(isOffline);
}
