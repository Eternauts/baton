import 'package:flutter/material.dart';
import '../../../core/ai/ai_status.dart';
import '../../../core/ai/on_device_ai_service.dart';
import '../../../features/report/report_view_model.dart';
import '../theme.dart';
import 'baton_logo.dart';

class IndustrialHeader extends StatelessWidget implements PreferredSizeWidget {
  final bool isOffline;
  final int pendingCount;
  final VoidCallback onToggleOffline;
  final Function(String text)? onSelectPreset;
  final ReportViewModel? reportViewModel;

  const IndustrialHeader({
    super.key,
    required this.isOffline,
    required this.pendingCount,
    required this.onToggleOffline,
    this.onSelectPreset,
    this.reportViewModel,
  });

  @override
  Size get preferredSize => const Size.fromHeight(52);

  static const List<Map<String, String>> debugPresets = [
    {
      'label': 'P-201B Vibration & Seal',
      'text': 'P-201B vibrating heavily, seal looks wet, 14:30',
    },
    {
      'label': 'T-310A High Temperature',
      'text': 'T-310A overhead receiver running high temp at 114 deg C',
    },
    {
      'label': 'V-104 Fuel Gas Isolation',
      'text': 'V-104 bypass valve locked in 35% position per PTW-2026-0881',
    },
    {
      'label': 'F-501 High Differential Press',
      'text': 'F-501 coalescer filter high differential pressure 2.8 bar',
    },
  ];

  void _showDebugSheet(BuildContext context) {
    final ai = OnDeviceAiService.instance;
    final status = ai.currentStatus;
    final rvm = reportViewModel;

    showModalBottomSheet(
      context: context,
      backgroundColor: AegisTheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(20),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Diagnostics & presets',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: AegisTheme.amberAccent,
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, color: AegisTheme.textMuted),
                      onPressed: () => Navigator.pop(context),
                    ),
                  ],
                ),
                const Divider(color: AegisTheme.cardBorder),
                const SizedBox(height: 8),

                const Text(
                  'Quick test presets',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: AegisTheme.textMuted,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: debugPresets.map((preset) {
                    return ActionChip(
                      backgroundColor: AegisTheme.surfaceVariant,
                      side: const BorderSide(color: AegisTheme.cardBorder),
                      label: Text(
                        preset['label']!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: AegisTheme.amberAccent,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      onPressed: () {
                        Navigator.pop(context);
                        if (onSelectPreset != null) {
                          onSelectPreset!(preset['text']!);
                        }
                      },
                    );
                  }).toList(),
                ),

                const SizedBox(height: 16),
                const Divider(color: AegisTheme.cardBorder),
                const SizedBox(height: 8),

                const Text(
                  'Cloud ASR diagnostics',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: AegisTheme.textMuted,
                  ),
                ),
                const SizedBox(height: 8),
                _debugRow('Audio path', rvm?.lastAsrPath ?? 'None'),
                _debugRow('ASR engine', rvm?.lastAsrEngine ?? 'None'),
                _debugRow('ASR model', rvm?.lastAsrModel ?? 'None'),
                _debugRow('Language', rvm?.lastAsrLang ?? 'None'),
                _debugRow('Audio seconds', rvm?.lastAsrAudioSec != null ? '${rvm!.lastAsrAudioSec!.toStringAsFixed(1)} s' : 'None'),
                _debugRow('Upload bytes', rvm?.lastAsrUploadBytes != null ? '${rvm!.lastAsrUploadBytes} B' : 'None'),
                _debugRow('Round trip ms', rvm?.lastAsrRoundTripMs != null ? '${rvm!.lastAsrRoundTripMs} ms' : 'None'),
                _debugRow('Server latency ms', rvm?.lastAsrServerLatencyMs != null ? '${rvm!.lastAsrServerLatencyMs} ms' : 'None'),
                _debugRow('Last error', rvm?.lastAsrError ?? 'None'),

                const SizedBox(height: 16),
                const Divider(color: AegisTheme.cardBorder),
                const SizedBox(height: 8),

                const Text(
                  'AI model status & specs',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: AegisTheme.textMuted,
                  ),
                ),
                const SizedBox(height: 8),
                _debugRow('Model path', ai.modelPath.isEmpty ? 'Not set' : ai.modelPath),
                _debugRow('Model size', ai.modelSizeBytes > 0 ? '${(ai.modelSizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB' : '0 MB'),
                _debugRow('Active backend', ai.activeBackend?.name ?? 'None'),
                _debugRow('Model load time', '${ai.lastLoadMs} ms'),
                _debugRow('Last inference time', '${ai.lastInferenceMs} ms'),
                _debugRow('Inference speed', '${ai.lastTokensPerSec.toStringAsFixed(1)} tok/s'),
                _debugRow('Status', _formatStatus(status)),
                const SizedBox(height: 16),
              ],
            ),
          ),
        );
      },
    );
  }

  String _formatStatus(AiStatus status) {
    switch (status) {
      case AiStatusNotInstalled():
        return 'Not installed';
      case AiStatusLoading():
        return 'Loading...';
      case AiStatusReady():
        return 'Ready (${status.backend.name})';
      case AiStatusCloud():
        return 'Cloud model (server reads notes)';
      case AiStatusError():
        return 'Error: ${status.message}';
    }
  }

  Widget _debugRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 140,
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: AegisTheme.textSecondary,
              ),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: AegisTheme.textPrimary,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AegisTheme.surface,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: SafeArea(
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            GestureDetector(
              onLongPress: () => _showDebugSheet(context),
              child: const BatonLockup(markHeight: 26),
            ),

            Row(
              children: [
                if (pendingCount > 0) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AegisTheme.amberAccent.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: AegisTheme.amberAccent.withValues(alpha: 0.5),
                      ),
                    ),
                    child: Text(
                      '$pendingCount pending',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: AegisTheme.amberAccent,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                ],

                GestureDetector(
                  onTap: onToggleOffline,
                  child: Container(
                    width: 12,
                    height: 12,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: isOffline ? AegisTheme.amberAccent : AegisTheme.successGreen,
                      boxShadow: [
                        BoxShadow(
                          color: (isOffline ? AegisTheme.amberAccent : AegisTheme.successGreen)
                              .withValues(alpha: 0.5),
                          blurRadius: 6,
                          spreadRadius: 1,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
