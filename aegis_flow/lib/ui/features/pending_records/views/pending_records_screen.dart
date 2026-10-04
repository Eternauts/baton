import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../../core/theme.dart';
import '../../../core/widgets/discrepancy_alert_card.dart';
import '../view_models/pending_records_view_model.dart';
import '../../../../data/models/observation_model.dart';

class PendingRecordsScreen extends StatelessWidget {
  final PendingRecordsViewModel viewModel;

  const PendingRecordsScreen({
    super.key,
    required this.viewModel,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: viewModel,
      builder: (context, _) {
        final records = viewModel.filteredObservations;

        return RefreshIndicator(
          onRefresh: viewModel.loadRecords,
          color: AegisTheme.safetyOrange,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Section Title
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: AegisTheme.industrialCyan.withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Icon(
                        Icons.sync_alt_rounded,
                        color: AegisTheme.industrialCyan,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '2. Pending Records & Sync Queue',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: AegisTheme.textPrimary,
                            ),
                          ),
                          Text(
                            'Zero-loss SQLite WAL buffer • HTTPS Sync to Google Storage',
                            style: TextStyle(
                              fontSize: 11,
                              color: AegisTheme.textMuted,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                // Top Metrics Dashboard
                Row(
                  children: [
                    _buildMetricCard(
                      label: 'OFFLINE QUEUE',
                      value: '${viewModel.offlineCount}',
                      color: viewModel.offlineCount > 0
                          ? AegisTheme.amberWarning
                          : AegisTheme.textMuted,
                      icon: Icons.cloud_queue,
                    ),
                    const SizedBox(width: 8),
                    _buildMetricCard(
                      label: 'CLOUD SYNCED',
                      value: '${viewModel.syncedCount}',
                      color: AegisTheme.successGreen,
                      icon: Icons.cloud_done,
                    ),
                    const SizedBox(width: 8),
                    _buildMetricCard(
                      label: 'DISCREPANCIES',
                      value: '${viewModel.alertCount}',
                      color: viewModel.alertCount > 0
                          ? AegisTheme.alertRed
                          : AegisTheme.textMuted,
                      icon: Icons.warning_amber_rounded,
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                // Sync Action Button
                if (viewModel.offlineCount > 0) ...[
                  ElevatedButton.icon(
                    onPressed: viewModel.isSyncing ? null : viewModel.syncPendingRecords,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AegisTheme.industrialCyan,
                      foregroundColor: Colors.black,
                      minimumSize: const Size.fromHeight(46),
                    ),
                    icon: viewModel.isSyncing
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                          )
                        : const Icon(Icons.cloud_upload_outlined, size: 20),
                    label: Text(
                      viewModel.isSyncing
                          ? 'SYNCING WITH GOOGLE CLOUD STORAGE...'
                          : 'SYNC ${viewModel.offlineCount} OFFLINE RECORDS TO CLOUD',
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],

                if (viewModel.syncMessage != null) ...[
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AegisTheme.successGreen.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AegisTheme.successGreen.withValues(alpha: 0.3)),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.check_circle, size: 16, color: AegisTheme.successGreen),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            viewModel.syncMessage!,
                            style: const TextStyle(fontSize: 12, color: AegisTheme.textPrimary),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                ],

                // Filter Tabs (All, Offline, Synced - exactly as in poster)
                Container(
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    color: AegisTheme.surfaceVariant,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AegisTheme.cardBorder),
                  ),
                  child: Row(
                    children: [
                      _buildFilterTab(
                        label: 'All (${viewModel.totalCount})',
                        filter: RecordsFilter.all,
                        isSelected: viewModel.activeFilter == RecordsFilter.all,
                      ),
                      _buildFilterTab(
                        label: 'Offline (${viewModel.offlineCount})',
                        filter: RecordsFilter.offline,
                        isSelected: viewModel.activeFilter == RecordsFilter.offline,
                      ),
                      _buildFilterTab(
                        label: 'Synced (${viewModel.syncedCount})',
                        filter: RecordsFilter.synced,
                        isSelected: viewModel.activeFilter == RecordsFilter.synced,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),

                // Records List
                if (records.isEmpty)
                  Container(
                    padding: const EdgeInsets.all(32),
                    alignment: Alignment.center,
                    child: const Text(
                      'No records found in this view',
                      style: TextStyle(color: AegisTheme.textMuted),
                    ),
                  )
                else
                  ListView.separated(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: records.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final item = records[index];
                      return _buildObservationItem(item);
                    },
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildMetricCard({
    required String label,
    required String value,
    required Color color,
    required IconData icon,
  }) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
        decoration: BoxDecoration(
          color: AegisTheme.surfaceVariant,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Column(
          children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(height: 4),
            Text(
              value,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w900,
                color: color,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: const TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w700,
                color: AegisTheme.textMuted,
              ),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterTab({
    required String label,
    required RecordsFilter filter,
    required bool isSelected,
  }) {
    return Expanded(
      child: InkWell(
        onTap: () => viewModel.setFilter(filter),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: isSelected ? AegisTheme.safetyOrange : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: isSelected ? FontWeight.w800 : FontWeight.w600,
              color: isSelected ? Colors.white : AegisTheme.textSecondary,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildObservationItem(ObservationModel item) {
    final timeStr = DateFormat('HH:mm').format(item.timestamp);

    return Container(
      decoration: BoxDecoration(
        color: AegisTheme.surfaceVariant,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: item.discrepancyAlert != null
              ? AegisTheme.alertRed.withValues(alpha: 0.5)
              : AegisTheme.cardBorder,
        ),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              // Equipment Tag Chip
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AegisTheme.surface,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: AegisTheme.industrialCyan.withValues(alpha: 0.5)),
                ),
                child: Text(
                  item.tag,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                    letterSpacing: 0.5,
                    color: AegisTheme.industrialCyan,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  item.anomaly,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AegisTheme.textPrimary,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                timeStr,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AegisTheme.textMuted,
                ),
              ),
              const SizedBox(width: 8),
              // Status Badge (Offline vs Synced)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                decoration: BoxDecoration(
                  color: item.isSynced
                      ? AegisTheme.successGreen.withValues(alpha: 0.15)
                      : AegisTheme.amberWarning.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      item.isSynced ? Icons.cloud_done : Icons.cloud_off,
                      size: 13,
                      color: item.isSynced ? AegisTheme.successGreen : AegisTheme.amberWarning,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      item.isSynced ? 'Synced' : 'Offline',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: item.isSynced ? AegisTheme.successGreen : AegisTheme.amberWarning,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            item.rawInput,
            style: const TextStyle(
              fontSize: 12,
              color: AegisTheme.textSecondary,
            ),
          ),
          if (item.scadaComparison != null) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                const Icon(Icons.sensors, size: 13, color: AegisTheme.industrialCyan),
                const SizedBox(width: 4),
                Text(
                  item.scadaComparison!,
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AegisTheme.industrialCyan,
                  ),
                ),
              ],
            ),
          ],
          // Embedded Discrepancy Card if triggered
          if (item.discrepancyAlert != null) ...[
            const SizedBox(height: 8),
            DiscrepancyAlertCard(
              title: 'SCADA Discrepancy Flag',
              description: item.discrepancyAlert!,
            ),
          ],
        ],
      ),
    );
  }
}
