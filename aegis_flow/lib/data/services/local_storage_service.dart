import 'package:shared_preferences/shared_preferences.dart';
import '../models/observation_model.dart';

/// Manages offline buffering and local persistence (simulating Room/SQLite WAL)
class LocalStorageService {
  static const String _observationsKey = 'aegis_flow_local_observations';
  static const String _offlineModeKey = 'aegis_flow_offline_mode_active';

  Future<List<ObservationModel>> getLocalObservations() async {
    final prefs = await SharedPreferences.getInstance();
    final jsonList = prefs.getStringList(_observationsKey) ?? [];
    return jsonList
        .map((item) => ObservationModel.fromJson(item))
        .toList();
  }

  Future<void> saveObservation(ObservationModel observation) async {
    final prefs = await SharedPreferences.getInstance();
    final currentList = await getLocalObservations();
    
    // Check if updating existing or prepending new
    final existingIndex = currentList.indexWhere((obs) => obs.id == observation.id);
    if (existingIndex >= 0) {
      currentList[existingIndex] = observation;
    } else {
      currentList.insert(0, observation);
    }

    final rawJsonList = currentList.map((obs) => obs.toJson()).toList();
    await prefs.setStringList(_observationsKey, rawJsonList);
  }

  Future<void> updateObservations(List<ObservationModel> observations) async {
    final prefs = await SharedPreferences.getInstance();
    final rawJsonList = observations.map((obs) => obs.toJson()).toList();
    await prefs.setStringList(_observationsKey, rawJsonList);
  }

  Future<void> clearAll() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_observationsKey);
  }

  Future<bool> isOfflineMode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_offlineModeKey) ?? false;
  }

  Future<void> setOfflineMode(bool isOffline) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_offlineModeKey, isOffline);
  }
}
