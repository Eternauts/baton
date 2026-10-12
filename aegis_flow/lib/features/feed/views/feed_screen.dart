import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../../ui/core/theme.dart';
import '../../../ui/core/widgets/baton_logo.dart';
import '../../../data/services/device_updates_service.dart';
import '../feed_view_model.dart';
import '../widgets/capsule_feed_item.dart';

class FeedScreen extends StatefulWidget {
  final FeedViewModel viewModel;
  final bool isOnline;

  const FeedScreen({
    super.key,
    required this.viewModel,
    required this.isOnline,
  });

  @override
  State<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends State<FeedScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      widget.viewModel.loadFeed(isOnline: widget.isOnline);
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.viewModel,
      builder: (context, _) {
        final vm = widget.viewModel;
        final todayItems = vm.todayCapsules;
        final earlierItems = vm.earlierCapsules;
        final isEmpty = todayItems.isEmpty && earlierItems.isEmpty;

        return Scaffold(
          backgroundColor: AegisTheme.background,
          body: SafeArea(
            child: Column(
              children: [
                // Top Segmented Control (All / Alerts)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: SegmentedButton<FeedFilter>(
                          segments: [
                            const ButtonSegment(
                              value: FeedFilter.all,
                              label: Text('All', style: TextStyle(fontSize: 12)),
                            ),
                            ButtonSegment(
                              value: FeedFilter.alerts,
                              label: Text('Alerts${vm.alertCount > 0 ? ' (${vm.alertCount})' : ''}', style: const TextStyle(fontSize: 12)),
                            ),
                          ],
                          selected: {vm.activeFilter},
                          onSelectionChanged: (set) {
                            vm.setFilter(set.first);
                          },
                          style: ButtonStyle(
                            backgroundColor: WidgetStateProperty.resolveWith((states) {
                              if (states.contains(WidgetState.selected)) {
                                return AegisTheme.amberAccent;
                              }
                              return AegisTheme.surfaceVariant;
                            }),
                            foregroundColor: WidgetStateProperty.resolveWith((states) {
                              if (states.contains(WidgetState.selected)) {
                                return Colors.black;
                              }
                              return AegisTheme.textSecondary;
                            }),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      // Manual Sync Button
                      if (widget.isOnline)
                        IconButton(
                          onPressed: vm.isSyncing ? null : () {
                            vm.manualCloudBatchSync();
                          },
                          style: IconButton.styleFrom(
                            backgroundColor: AegisTheme.surfaceVariant,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          icon: vm.isSyncing
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: AegisTheme.amberAccent,
                                  ),
                                )
                              : const Icon(
                                  Icons.cloud_sync,
                                  color: AegisTheme.amberAccent,
                                ),
                        ),
                    ],
                  ),
                ),

                _SyncStatusStrip(vm: vm, isOnline: widget.isOnline),
                if (vm.updates.isNotEmpty) _ServerUpdateBanner(update: vm.updates.first),

                // Main List with Pull-to-Refresh
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: () async {
                      await vm.loadFeed(isOnline: widget.isOnline);
                      if (widget.isOnline) await vm.refreshUpdates();
                    },
                    color: AegisTheme.amberAccent,
                    child: isEmpty && vm.isLoading
                        ? ListView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            children: const [
                              SizedBox(height: 120),
                              Center(child: BatonLoader(height: 72, label: 'Loading reports')),
                            ],
                          )
                        : isEmpty
                        ? ListView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.all(32),
                            children: [
                              const SizedBox(height: 48),
                              const Icon(Icons.mic_none_rounded, size: 48, color: AegisTheme.textMuted),
                              const SizedBox(height: 12),
                              Center(
                                child: Text(
                                  vm.activeFilter == FeedFilter.alerts ? 'No alerts.' : 'Nothing reported yet this shift.',
                                  style: const TextStyle(color: AegisTheme.textSecondary, fontSize: 15, fontWeight: FontWeight.w600),
                                ),
                              ),
                              const SizedBox(height: 6),
                              Center(
                                child: Text(
                                  vm.activeFilter == FeedFilter.alerts ? 'Switch to All to see every report.' : 'Open the Report tab and say what you saw.',
                                  style: const TextStyle(color: AegisTheme.textMuted, fontSize: 13),
                                ),
                              ),
                            ],
                          )
                        : ListView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                            children: [
                              if (todayItems.isNotEmpty) ...[
                                const Padding(
                                  padding: EdgeInsets.symmetric(vertical: 6),
                                  child: Text(
                                    'Today',
                                    style: TextStyle(
                                      fontSize: 12,
                                      fontWeight: FontWeight.bold,
                                      color: AegisTheme.textMuted,
                                    ),
                                  ),
                                ),
                                ...todayItems.map((c) => Padding(
                                      padding: const EdgeInsets.only(bottom: 8),
                                      child: CapsuleFeedItem(capsule: c),
                                    )),
                              ],
                              if (earlierItems.isNotEmpty) ...[
                                const Padding(
                                  padding: EdgeInsets.fromLTRB(0, 12, 0, 6),
                                  child: Text(
                                    'Earlier',
                                    style: TextStyle(
                                      fontSize: 12,
                                      fontWeight: FontWeight.bold,
                                      color: AegisTheme.textMuted,
                                    ),
                                  ),
                                ),
                                ...earlierItems.map((c) => Padding(
                                      padding: const EdgeInsets.only(bottom: 8),
                                      child: CapsuleFeedItem(capsule: c),
                                    )),
                              ],
                            ],
                          ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// One line that always answers: am I online, what is waiting, what did the last sync say.
class _SyncStatusStrip extends StatelessWidget {
  final FeedViewModel vm;
  final bool isOnline;
  const _SyncStatusStrip({required this.vm, required this.isOnline});

  @override
  Widget build(BuildContext context) {
    final pending = vm.offlineCount;
    final String text;
    final Color color;
    final IconData icon;
    if (vm.isSyncing) {
      text = 'Syncing…';
      color = AegisTheme.amberAccent;
      icon = Icons.sync;
    } else if (pending > 0) {
      text = isOnline ? '$pending waiting to sync' : 'Offline: $pending saved on this device';
      color = AegisTheme.amberAccent;
      icon = Icons.cloud_off;
    } else if (vm.lastSyncedAt != null) {
      text = vm.syncMessage ?? 'All synced';
      color = AegisTheme.successGreen;
      icon = Icons.cloud_done;
    } else {
      text = isOnline ? 'All synced' : 'Offline';
      color = isOnline ? AegisTheme.successGreen : AegisTheme.textMuted;
      icon = isOnline ? Icons.cloud_done : Icons.cloud_off;
    }
    final failed = (vm.syncMessage ?? '').toLowerCase().contains('failed');
    final shown = failed && pending > 0 ? '${vm.syncMessage}' : text;
    final at = vm.lastSyncedAt != null && pending == 0 && !vm.isSyncing ? '  ·  ${DateFormat('HH:mm').format(vm.lastSyncedAt!)}' : '';
    return Semantics(
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 6),
        child: Row(
          children: [
            Icon(icon, size: 14, color: failed && pending > 0 ? AegisTheme.alertRed : color),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                '$shown$at',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 12, color: failed && pending > 0 ? AegisTheme.alertRed : color),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The latest safety update the cloud published for this unit. Display only: nothing here clears or resolves it.
class _ServerUpdateBanner extends StatefulWidget {
  final DeviceUpdate update;
  const _ServerUpdateBanner({required this.update});

  @override
  State<_ServerUpdateBanner> createState() => _ServerUpdateBannerState();
}

class _ServerUpdateBannerState extends State<_ServerUpdateBanner> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final u = widget.update;
    final color = u.isCritical ? AegisTheme.alertRed : AegisTheme.amberAccent;
    final time = u.createdAt != null ? DateFormat('HH:mm').format(u.createdAt!) : '';
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Material(
        color: color.withValues(alpha: 0.12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: BorderSide(color: color.withValues(alpha: 0.5))),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.shield_outlined, size: 16, color: color),
                    const SizedBox(width: 6),
                    Text('${u.severity.toUpperCase()} · from the cloud${time.isEmpty ? '' : ' · $time'}',
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
                    const Spacer(),
                    Icon(_open ? Icons.expand_less : Icons.expand_more, size: 18, color: color),
                  ],
                ),
                const SizedBox(height: 6),
                Text(u.summary,
                    maxLines: _open ? null : 2,
                    overflow: _open ? TextOverflow.visible : TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 13, height: 1.3, color: AegisTheme.textPrimary)),
                if (_open && u.requiredActions.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text('Required actions', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
                  const SizedBox(height: 4),
                  for (final a in u.requiredActions)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Text('• $a', style: const TextStyle(fontSize: 12, color: AegisTheme.textPrimary)),
                    ),
                ],
                if (_open)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('Only a supervisor can acknowledge this on the dashboard.',
                        style: TextStyle(fontSize: 11, color: AegisTheme.textMuted)),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
