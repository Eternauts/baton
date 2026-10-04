import 'package:flutter/material.dart';
import '../../../core/theme.dart';
import '../../../../data/models/scada_sensor_model.dart';

class ScadaMonitorScreen extends StatelessWidget {
  final Map<String, ScadaSensorModel> sensors;
  final bool isOffline;
  final VoidCallback onToggleOffline;

  const ScadaMonitorScreen({
    super.key,
    required this.sensors,
    required this.isOffline,
    required this.onToggleOffline,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
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
                  color: AegisTheme.amberWarning.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.precision_manufacturing_rounded,
                  color: AegisTheme.amberWarning,
                  size: 20,
                ),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Plant SCADA & Hybrid Architecture',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        color: AegisTheme.textPrimary,
                      ),
                    ),
                    Text(
                      'Live DCS telemetry feed & Edge-Cloud verification pipeline',
                      style: TextStyle(fontSize: 11, color: AegisTheme.textMuted),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Solution Architecture Card (Matching the poster)
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AegisTheme.surfaceVariant,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AegisTheme.cardBorder),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.hub_outlined, color: AegisTheme.industrialCyan, size: 18),
                    SizedBox(width: 8),
                    Text(
                      'HYBRID EDGE-CLOUD MULTI-AGENT SYSTEM',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.6,
                        color: AegisTheme.industrialCyan,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _buildArchitectureLayer(
                  number: '1',
                  title: 'EDGE LAYER (Offline)',
                  desc: 'Ruggedized Android Tablet (ATEX Zone 2) • Gemma 2B INT4 On-Device Extraction • SQLite WAL Local Queue (Zero Data Loss).',
                  color: AegisTheme.safetyOrange,
                ),
                const SizedBox(height: 10),
                _buildArchitectureLayer(
                  number: '2',
                  title: 'SYNC LAYER',
                  desc: 'WorkManager Background Queue • HTTPS Sync when rig satellite connectivity is restored • Cloud Run FastAPI.',
                  color: AegisTheme.industrialCyan,
                ),
                const SizedBox(height: 10),
                _buildArchitectureLayer(
                  number: '3',
                  title: 'CLOUD AGENT LAYER',
                  desc: 'Gemini Cloud Agent + Google Cloud Storage • Cross-checks Mock SCADA Telemetry JSON • Generates Discrepancy Alerts.',
                  color: AegisTheme.amberWarning,
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // Live Telemetry Sensors Header
          const Text(
            'ACTIVE SCADA SENSOR TELEMETRY:',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.5,
              color: AegisTheme.textMuted,
            ),
          ),
          const SizedBox(height: 8),

          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: sensors.values.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final sensor = sensors.values.elementAt(index);
              return _buildSensorCard(sensor);
            },
          ),
          const SizedBox(height: 14),

          // Toggle Rig Offline Mode
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AegisTheme.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AegisTheme.cardBorder),
            ),
            child: Row(
              children: [
                Icon(
                  isOffline ? Icons.cloud_off : Icons.cloud_done,
                  color: isOffline ? AegisTheme.amberWarning : AegisTheme.successGreen,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        isOffline ? 'Offshore Rig Mode (Offline)' : 'Connected Mode (Online)',
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                      ),
                      Text(
                        isOffline
                            ? 'All inputs buffer locally in SQLite WAL'
                            : 'Background sync pushes logs to Google Cloud Storage',
                        style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted),
                      ),
                    ],
                  ),
                ),
                Switch(
                  value: !isOffline,
                  activeColor: AegisTheme.successGreen,
                  onChanged: (_) => onToggleOffline(),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildArchitectureLayer({
    required String number,
    required String title,
    required String desc,
    required Color color,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 22,
          height: 22,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.2),
            shape: BoxShape.circle,
            border: Border.all(color: color, width: 1.2),
          ),
          child: Text(
            number,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w900,
              color: color,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                  color: color,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                desc,
                style: const TextStyle(
                  fontSize: 11,
                  height: 1.35,
                  color: AegisTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildSensorCard(ScadaSensorModel sensor) {
    Color statusColor;
    if (sensor.status == 'CRITICAL') {
      statusColor = AegisTheme.alertRed;
    } else if (sensor.status == 'WARNING') {
      statusColor = AegisTheme.amberWarning;
    } else {
      statusColor = AegisTheme.successGreen;
    }

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AegisTheme.surfaceVariant,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: sensor.tag == 'P-201B'
              ? AegisTheme.alertRed.withValues(alpha: 0.5)
              : AegisTheme.cardBorder,
        ),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: AegisTheme.surface,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AegisTheme.cardBorder),
            ),
            child: Text(
              sensor.tag,
              style: const TextStyle(
                fontWeight: FontWeight.w900,
                fontSize: 13,
                color: AegisTheme.industrialCyan,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  sensor.equipmentName,
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  'Normal range: ${sensor.normalMin} - ${sensor.normalMax} ${sensor.unit}',
                  style: const TextStyle(fontSize: 10, color: AegisTheme.textMuted),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${sensor.currentValue} ${sensor.unit}',
                style: TextStyle(
                  fontWeight: FontWeight.w900,
                  fontSize: 13,
                  color: statusColor,
                ),
              ),
              const SizedBox(height: 2),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  sensor.status,
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w800,
                    color: statusColor,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
