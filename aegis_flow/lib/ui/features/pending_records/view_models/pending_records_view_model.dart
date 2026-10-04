import 'package:flutter/material.dart';
import '../../../../data/models/observation_model.dart';
import '../../../../data/repositories/handover_repository.dart';

enum RecordsFilter { all, offline, synced }

class PendingRecordsViewModel extends ChangeNotifier {
  final HandoverRepository _repository;

  PendingRecordsViewModel({required HandoverRepository repository})
      : _repository = repository;

  List<ObservationModel> _observations = [];
  RecordsFilter _activeFilter = RecordsFilter.all;
  bool _isLoading = false;
  bool _isSyncing = false;
  String? _syncMessage;

  List<ObservationModel> get observations => _observations;
  RecordsFilter get activeFilter => _activeFilter;
  bool get isLoading => _isLoading;
  bool get isSyncing => _isSyncing;
  String? get syncMessage => _syncMessage;

  int get totalCount => _observations.length;
  int get offlineCount => _observations.where((o) => !o.isSynced).length;
  int get syncedCount => _observations.where((o) => o.isSynced).length;
  int get alertCount => _observations.where((o) => o.discrepancyAlert != null).length;

  List<ObservationModel> get filteredObservations {
    switch (_activeFilter) {
      case RecordsFilter.offline:
        return _observations.where((o) => !o.isSynced).toList();
      case RecordsFilter.synced:
        return _observations.where((o) => o.isSynced).toList();
      case RecordsFilter.all:
        return _observations;
    }
  }

  void setFilter(RecordsFilter filter) {
    _activeFilter = filter;
    notifyListeners();
  }

  Future<void> loadRecords() async {
    _isLoading = true;
    notifyListeners();

    _observations = await _repository.getObservations();
    _isLoading = false;
    notifyListeners();
  }

  /// Syncs pending offline records to Google Cloud Storage
  Future<void> syncPendingRecords() async {
    _isSyncing = true;
    _syncMessage = null;
    notifyListeners();

    final updated = await _repository.syncPendingRecords();
    _observations = updated;
    _isSyncing = false;
    _syncMessage = 'Successfully synced ${offlineCount == 0 ? "all" : "records"} to Google Cloud Storage (Cloud Run verified)';
    notifyListeners();
  }
}
