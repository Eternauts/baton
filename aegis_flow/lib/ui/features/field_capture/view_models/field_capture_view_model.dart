import 'package:flutter/material.dart';
import '../../../../data/models/observation_model.dart';
import '../../../../data/repositories/handover_repository.dart';

class FieldCaptureViewModel extends ChangeNotifier {
  final HandoverRepository _repository;

  FieldCaptureViewModel({required HandoverRepository repository})
      : _repository = repository;

  final TextEditingController inputController = TextEditingController();
  bool _isProcessing = false;
  bool _isRecording = false;
  ObservationModel? _extractedObservation;
  String? _errorMessage;

  bool get isProcessing => _isProcessing;
  bool get isRecording => _isRecording;
  ObservationModel? get extractedObservation => _extractedObservation;
  String? get errorMessage => _errorMessage;

  /// Preset sample inputs for testing quick handover observations
  final List<Map<String, String>> presets = [
    {
      'label': 'P-201B Vibration & Seal (English)',
      'text': 'P-201B vibrating heavily, seal looks wet, 14:30',
      'lang': 'en',
    },
    {
      'label': 'P-201B Pam Bergegar & Bocor (Malay)',
      'text': 'Pam P-201B bergegar kuat dan ada kebocoran meterai (seal leak) di kawasan Unit 3',
      'lang': 'ms',
    },
    {
      'label': 'P-201B பம்ப் அதிர்வு (Tamil)',
      'text': 'P-201B பம்ப் அதிக அதிர்வுடன் உள்ளது, சீல் நனைந்துள்ளது 14:30',
      'lang': 'ta',
    },
    {
      'label': 'T-310A High Temperature (English)',
      'text': 'T-310A overhead receiver running high temp at 114 deg C',
      'lang': 'en',
    },
    {
      'label': 'V-104 Fuel Gas Isolation (English)',
      'text': 'V-104 bypass valve locked in 35% position per PTW-2026-0881',
      'lang': 'en',
    },
  ];

  void selectPreset(int index) {
    if (index >= 0 && index < presets.length) {
      inputController.text = presets[index]['text']!;
      notifyListeners();
    }
  }

  void toggleRecording() {
    _isRecording = !_isRecording;
    if (_isRecording) {
      // Simulate live voice transcript feed
      inputController.text = 'P-201B vibrating heavily, seal looks wet, 14:30';
    }
    notifyListeners();
  }

  /// Runs Gemma 2B Edge extraction and buffers to local zero-loss queue
  Future<bool> processAndSaveObservation() async {
    final text = inputController.text.trim();
    if (text.isEmpty) {
      _errorMessage = 'Please enter or record an observation first.';
      notifyListeners();
      return false;
    }

    _isProcessing = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final result = await _repository.extractAndSaveObservation(rawText: text);
      _extractedObservation = result;
      _isProcessing = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = 'Extraction error: $e';
      _isProcessing = false;
      notifyListeners();
      return false;
    }
  }

  void resetExtraction() {
    _extractedObservation = null;
    inputController.clear();
    notifyListeners();
  }

  @override
  void dispose() {
    inputController.dispose();
    super.dispose();
  }
}
