import 'package:flutter/material.dart';
import '../../core/data/observation_capsule.dart';
import '../../core/data/handover_repository.dart';
import '../../data/services/device_updates_service.dart';

enum FeedFilter { all, alerts }

class FeedViewModel extends ChangeNotifier {
  final HandoverRepository _repository;

  FeedViewModel({required HandoverRepository repository})
      : _repository = repository;

  List<ObservationCapsule> _capsules = [];
  FeedFilter _activeFilter = FeedFilter.all;
  bool _isLoading = false;
  bool _isSyncing = false;
  String? _syncMessage;
  List<DeviceUpdate> _updates = [];
  DateTime? _lastSyncedAt;

  List<ObservationCapsule> get capsules => _capsules;
  FeedFilter get activeFilter => _activeFilter;
  bool get isLoading => _isLoading;
  bool get isSyncing => _isSyncing;
  String? get syncMessage => _syncMessage;
  List<DeviceUpdate> get updates => _updates;
  DateTime? get lastSyncedAt => _lastSyncedAt;
  bool get hasCriticalUpdate => _updates.any((u) => u.isCritical);

  int get offlineCount => _capsules.where((c) => !c.isSynced).length;
  int get alertCount => _capsules.where((c) => c.escalation.level > 0 || c.discrepancyAlert != null || c.serverFlags.isNotEmpty).length;

  List<ObservationCapsule> get filteredCapsules {
    final list = _activeFilter == FeedFilter.alerts
        ? _capsules.where((c) => c.escalation.level > 0 || c.discrepancyAlert != null || c.serverFlags.isNotEmpty).toList()
        : _capsules;

    // Deduplicate by eventId
    final seen = <String>{};
    final deduped = <ObservationCapsule>[];
    for (final item in list) {
      if (!seen.contains(item.eventId)) {
        seen.add(item.eventId);
        deduped.add(item);
      }
    }
    return deduped;
  }

  List<ObservationCapsule> get todayCapsules {
    final now = DateTime.now();
    return filteredCapsules.where((c) =>
        c.observedAt.year == now.year &&
        c.observedAt.month == now.month &&
        c.observedAt.day == now.day).toList();
  }

  List<ObservationCapsule> get earlierCapsules {
    final now = DateTime.now();
    return filteredCapsules.where((c) =>
        c.observedAt.year != now.year ||
        c.observedAt.month != now.month ||
        c.observedAt.day != now.day).toList();
  }

  void setFilter(FeedFilter filter) {
    _activeFilter = filter;
    notifyListeners();
  }

  Future<void> loadFeed({bool isOnline = false}) async {
    _isLoading = true;
    notifyListeners();

    final rawList = await _repository.getObservations();

    // Sort feed: Level 2 / Level 1 alerts & discrepancies first, then newest observedAt
    rawList.sort((a, b) {
      final aPriority = (a.serverFlags.isNotEmpty ? 30 : 0) + (a.escalation.level * 10) + (a.discrepancyAlert != null ? 5 : 0);
      final bPriority = (b.serverFlags.isNotEmpty ? 30 : 0) + (b.escalation.level * 10) + (b.discrepancyAlert != null ? 5 : 0);
      if (aPriority != bPriority) {
        return bPriority.compareTo(aPriority);
      }
      return b.observedAt.compareTo(a.observedAt);
    });

    _capsules = rawList;
    _isLoading = false;
    notifyListeners();

    if (isOnline && offlineCount > 0) {
      autoSync();
    } else if (isOnline) {
      refreshUpdates();
    }
  }

  /// The cloud pipeline publishes its update about 10 to 20 s after a sync; look twice.
  void _refreshUpdatesSoon() {
    for (final s in const [8, 20]) {
      Future.delayed(Duration(seconds: s), refreshUpdates);
    }
  }

  /// Read-only: shows what the cloud pipeline concluded. Keeps the previous list if the read fails.
  Future<void> refreshUpdates() async {
    final fetched = await _repository.fetchDeviceUpdates();
    if (fetched == null) return;
    _updates = fetched;
    notifyListeners();
  }

  Future<void> autoSync() async {
    if (_isSyncing) return;
    _isSyncing = true;
    notifyListeners();

    try {
      final updated = await _repository.syncPendingRecords();
      _capsules = updated;
      _syncMessage = _syncDoneMessage('Synced with cloud.');
      _lastSyncedAt = DateTime.now();
      _refreshUpdatesSoon();
    } catch (e) {
      _syncMessage = 'Sync failed: $e';
    } finally {
      _isSyncing = false;
      notifyListeners();
    }
  }

  /// A synced batch can still carry safety conflicts flagged by the server: say so instead of a bare "done".
  String _syncDoneMessage(String ok) {
    final n = _repository.lastSyncConflicts.length;
    return n == 0 ? ok : 'Synced. The server flagged $n safety conflict${n == 1 ? '' : 's'}: see the supervisor dashboard.';
  }

  // Explicit manual sync specifically to test the BatonSyncService
  Future<void> manualCloudBatchSync() async {
    if (_isSyncing) return;
    _isSyncing = true;
    _syncMessage = 'Syncing...';
    notifyListeners();

    try {
      final updated = await _repository.syncPendingRecords();
      _capsules = updated;
      _syncMessage = _syncDoneMessage('Batch sync complete.');
      _lastSyncedAt = DateTime.now();
      _refreshUpdatesSoon();
    } catch (e) {
      _syncMessage = 'Batch sync failed: $e';
    } finally {
      _isSyncing = false;
      notifyListeners();
    }
  }
}
