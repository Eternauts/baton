import 'dart:async';
import 'package:uuid/uuid.dart';
import '../models/observation_model.dart';
import '../models/scada_sensor_model.dart';
import '../models/chat_message_model.dart';

/// Implements Edge Gemma 2B INT4 Extraction and Multilingual Shift Assistant
class GemmaInferenceService {
  final _uuid = const Uuid();

  /// Mock Plant SCADA live data for cross-checking
  final Map<String, ScadaSensorModel> _scadaDatabase = {
    'P-201B': ScadaSensorModel(
      tag: 'P-201B',
      equipmentName: 'Crude Export Booster Pump B',
      currentValue: 1.25,
      unit: 'mm/s (Vibration)',
      normalMin: 0.5,
      normalMax: 4.5,
      status: 'NORMAL', // SCADA is unaware of field mechanical seal weeping!
      lastTelemetry: DateTime.now().subtract(const Duration(minutes: 4)),
    ),
    'T-310A': ScadaSensorModel(
      tag: 'T-310A',
      equipmentName: 'Fractionator Overhead Receiver',
      currentValue: 114.8,
      unit: '°C (Temp)',
      normalMin: 65.0,
      normalMax: 95.0,
      status: 'WARNING', // High temperature alarm
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

  /// Offline Structured Extraction using Edge Gemma 2B INT4
  Future<ObservationModel> extractObservationFromInput({
    required String rawText,
    String? explicitLanguage,
  }) async {
    // Simulate Edge INT4 inference latency (typically ~1.2s - 1.8s on NPU/CPU)
    await Future.delayed(const Duration(milliseconds: 900));

    final normalized = rawText.toUpperCase();
    String detectedTag = 'P-201B';
    String anomaly = 'vibration';
    int severity = 4;
    String unit = 'Unit 3 - Crude Pumping Area';
    String action = 'Urgent mechanical seal inspection required';
    String lang = explicitLanguage ?? _detectLanguage(rawText);

    if (normalized.contains('T-310') || normalized.contains('T310') || normalized.contains('TEMP') || normalized.contains('SUHU') || normalized.contains('வெப்ப')) {
      detectedTag = 'T-310A';
      anomaly = 'temperature high / cooling bypass';
      severity = 3;
      unit = 'Unit 2 - Fractionator Column';
      action = 'Verify fin-fan cooler pitch and trim bypass valve';
    } else if (normalized.contains('V-104') || normalized.contains('V104') || normalized.contains('VALVE') || normalized.contains('INJAP') || normalized.contains('வால்வு')) {
      detectedTag = 'V-104';
      anomaly = 'valve position mismatch / bypass locked';
      severity = 3;
      unit = 'Fuel Gas Skid 01';
      action = 'Check car-seal and lockout tagout status';
    } else if (normalized.contains('F-501') || normalized.contains('F501') || normalized.contains('FILTER') || normalized.contains('PENAPIS')) {
      detectedTag = 'F-501';
      anomaly = 'high differential pressure / fouling';
      severity = 5;
      unit = 'Produced Water Treatment';
      action = 'Immediate backwash or switch to standby cartridge';
    } else {
      // Default / P-201B
      detectedTag = 'P-201B';
      if (rawText.toLowerCase().contains('leak') || rawText.toLowerCase().contains('wet') || rawText.contains('bocor') || rawText.contains('கசிவு')) {
        anomaly = 'seal leak & high vibration';
        severity = 4;
      } else {
        anomaly = 'vibration';
        severity = 4;
      }
      unit = 'Unit 3 - Crude Transfer';
      action = 'Isolate and engage rotating equipment tech before next cycle';
    }

    // SCADA Cross-Check & Discrepancy Detection (Layer 3 in Architecture)
    String? discrepancy;
    String? scadaComp;
    final scada = _scadaDatabase[detectedTag];
    if (scada != null) {
      if (detectedTag == 'P-201B' && scada.status == 'NORMAL') {
        discrepancy = 'Discrepancy: $detectedTag vibration/leak high per field log, but SCADA sensor shows normal (${scada.currentValue} ${scada.unit}). Review required.';
        scadaComp = 'SCADA status: ${scada.status} (${scada.currentValue} ${scada.unit})';
      } else {
        scadaComp = 'SCADA status: ${scada.status} (${scada.currentValue} ${scada.unit})';
      }
    }

    return ObservationModel(
      id: _uuid.v4(),
      rawInput: rawText,
      language: lang,
      tag: detectedTag,
      anomaly: anomaly,
      severity: severity,
      unit: unit,
      actionRequired: action,
      timestamp: DateTime.now(),
      isSynced: false,
      discrepancyAlert: discrepancy,
      scadaComparison: scadaComp,
    );
  }

  /// Multilingual Shift Assistant & Knowledge Base Q&A
  Future<ChatMessageModel> answerShiftWorkerQuery({
    required String query,
    required List<ObservationModel> activeLogs,
  }) async {
    // Simulate inference time
    await Future.delayed(const Duration(milliseconds: 1100));

    final lang = _detectLanguage(query);
    final normalized = query.toUpperCase();
    final List<String> citations = [];
    bool hasAlert = false;
    String answer = '';

    // Search active logs for equipment mentions
    final matchingLogs = activeLogs.where((log) =>
        normalized.contains(log.tag) ||
        normalized.contains(log.anomaly.toUpperCase()) ||
        normalized.contains(log.unit.toUpperCase())).toList();

    for (final log in matchingLogs.take(3)) {
      citations.add('LOG: ${log.timestamp.hour.toString().padLeft(2, '0')}:${log.timestamp.minute.toString().padLeft(2, '0')} [${log.tag}] - ${log.anomaly}');
    }

    // Determine intent and language response
    if (normalized.contains('P-201B') || normalized.contains('P201B') || normalized.contains('PUMP') || normalized.contains('SEAL')) {
      citations.add('SOP-MECH-012: Centrifugal Pump Seal Barrier Fluid Flushing');
      hasAlert = true;

      switch (lang) {
        case 'ta': // Tamil
          answer = 'பம்ப் P-201B-ல் சீல் நனைந்து அதிக அதிர்வு இருப்பது பதிவு செய்யப்பட்டுள்ளது. SCADA சென்சார் வழக்கமான ரீடிங் காட்டினாலும், கசிவு இருப்பதை களப்பணி லாக் உறுதிப்படுத்துகிறது. SOP-MECH-012 படி மெக்கானிக்கல் ஆய்வு செய்யாமல் பம்பை இயக்க வேண்டாம்.';
          break;
        case 'ms': // Malay
          answer = 'Bagi pam P-201B, terdapat log getaran tinggi dan kebocoran meterai (seal leak) pada shif sebelumnya. Walaupun SCADA menunjukkan status NORMAL, pemeriksaan fizikal mengesahkan kebasahan meterai. Ikuti SOP-MECH-012 sebelum menghidupkan semula pam.';
          break;
        case 'zh': // Mandarin
          answer = '针对泵 P-201B，上一班次已记录到剧烈振动及机械密封湿润漏液。尽管 SCADA 仪表显示读数正常，请务必以现场观测为准。请依照 SOP-MECH-012 执行隔离及检修。';
          break;
        case 'hi': // Hindi
          answer = 'पंप P-201B के लिए पिछली शिफ्ट में अत्यधिक कंपन और सील लीक की सूचना दर्ज की गई है। हालांकि SCADA सामान्य रीडिंग दिखा रहा है, SOP-MECH-012 के तहत मैकेनिकल टीम द्वारा निरीक्षण किए बिना इसे चालू न करें।';
          break;
        case 'es': // Spanish
          answer = 'Para la bomba P-201B, se reportó vibración severa y fuga en el sello mecánico en el turno previo. Aunque el SCADA muestra lectura normal, no reiniciar el equipo sin la inspección mecánica bajo SOP-MECH-012.';
          break;
        default: // English
          answer = 'Pump P-201B was logged with heavy vibration and a wet mechanical seal at 14:30. Note: SCADA currently shows 1.25 mm/s (Normal), indicating an active DISCREPANCY. Do not restart without mechanical technician clearance under SOP-MECH-012.';
      }
    } else if (normalized.contains('T-310A') || normalized.contains('T310') || normalized.contains('TEMP') || normalized.contains('SUHU')) {
      citations.add('SCADA-TELEM: T-310A at 114.8°C (Max limit: 95.0°C)');
      citations.add('SOP-PROC-044: Fractionator Overhead Thermal Trim');
      hasAlert = true;

      switch (lang) {
        case 'ms':
          answer = 'Suhu Fractionator T-310A kini pada 114.8°C (melebihi had maksimum 95.0°C). Shif lalu telah merekodkan isu ini. Sila semak injap pintasan (trim bypass) dan kipas penyejuk fin-fan mengikut SOP-PROC-044.';
          break;
        case 'ta':
          answer = 'T-310A வெப்ப நிலை 114.8°C-ஆக உயர்ந்துள்ளது (அனுமதிக்கப்பட்ட அளவு: 95.0°C). கடந்த ஷிப்ட்டில் பதிவு செய்யப்பட்டுள்ளது. SOP-PROC-044-ஐ பின்பற்றி கூலிங் பைபாஸை சரிபார்க்கவும்.';
          break;
        default:
          answer = 'Receiver T-310A is currently operating at 114.8°C, which exceeds the high alarm threshold (95.0°C). Verified in the shift handover log. Immediate action required: verify fin-fan louvre pitch and adjust thermal bypass per SOP-PROC-044.';
      }
    } else if (normalized.contains('V-104') || normalized.contains('V104') || normalized.contains('VALVE') || normalized.contains('PERMIT') || normalized.contains('ISOLATION')) {
      citations.add('PTW-2026-0881: Hot Work & Fuel Gas Valve Isolation');
      citations.add('SOP-SAFE-007: Lockout/Tagout (LOTO) Verification');

      switch (lang) {
        case 'ms':
          answer = 'Injap V-104 kini di bawah permit kerja PTW-2026-0881 (Pengasingan Gas Bahan Api). Kunci keselamatan (Car-seal) mesti diperiksa sebelum sebarang perubahan posisi injap mengikut SOP-SAFE-007.';
          break;
        case 'ta':
          answer = 'வால்வு V-104 தற்போது PTW-2026-0881 அனுமதி மற்றும் LOTO பூட்டுதல் கீழ் உள்ளது. SOP-SAFE-007 வழிகாட்டுதலின்படி சூப்பர்வைசர் ஒப்புதல் இன்றி திறக்கக்கூடாது.';
          break;
        default:
          answer = 'Valve V-104 is under active isolation permit PTW-2026-0881 for fuel gas header maintenance. Car-seal and LOTO padlock must remain engaged. Do not alter position without permit clearance under SOP-SAFE-007.';
      }
    } else {
      // General shift status inquiry
      citations.add('SHIFT-SUMMARY: 4 logs recorded in current 12-hr window');
      citations.add('ALERT-STATUS: 1 active SCADA discrepancy flagged');

      switch (lang) {
        case 'ms':
          answer = 'Ringkasan shif terkini: Terdapat 4 rekod penyerahan shif. Perhatian utama diperlukan pada Pam P-201B (getaran & meterai basah) dan Penerima T-310A (suhu tinggi 114.8°C). Semua log telah disimpan di storan tempatan.';
          break;
        case 'ta':
          answer = 'தற்போதைய ஷிப்ட் சுருக்கம்: 4 முக்கிய பதிவுகள் உள்ளன. P-201B பம்ப் அதிர்வு மற்றும் T-310A அதிக வெப்பம் ஆகியவை கவனிக்கப்பட வேண்டியவை. அனைத்து தகவல்களும் ஆஃப்லைன் டேப்லெட்டில் பாதுகாப்பாக உள்ளன.';
          break;
        default:
          answer = 'Shift Status Overview: 4 observations logged during this handover. Key focus areas: Pump P-201B (vibration & wet seal with active SCADA discrepancy) and Column T-310A (high temperature alarm at 114.8°C). All local records buffered.';
      }
    }

    return ChatMessageModel(
      id: _uuid.v4(),
      sender: 'gemma',
      message: answer,
      detectedLanguage: lang,
      citations: citations,
      hasAlert: hasAlert,
      timestamp: DateTime.now(),
    );
  }

  String _detectLanguage(String text) {
    // Unicode range detection for Tamil
    if (RegExp(r'[\u0B80-\u0BFF]').hasMatch(text)) return 'ta';
    // Unicode range detection for Devanagari (Hindi)
    if (RegExp(r'[\u0900-\u097F]').hasMatch(text)) return 'hi';
    // Unicode range detection for Chinese characters
    if (RegExp(r'[\u4E00-\u9FFF]').hasMatch(text)) return 'zh';
    
    final lower = text.toLowerCase();
    // Malay / Indonesian keywords
    if (lower.contains('suhu') || lower.contains('pam') || lower.contains('injap') || lower.contains('bocor') || lower.contains('bergegar') || lower.contains('bagaimana') || lower.contains('apa')) {
      return 'ms';
    }
    // Spanish keywords
    if (lower.contains('bomba') || lower.contains('fuga') || lower.contains('cómo') || lower.contains('qué') || lower.contains('sello') || lower.contains('presión')) {
      return 'es';
    }
    return 'en';
  }
}
