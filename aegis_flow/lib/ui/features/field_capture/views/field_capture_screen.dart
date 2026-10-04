import 'package:flutter/material.dart';
import '../../../core/theme.dart';
import '../../../core/widgets/discrepancy_alert_card.dart';
import '../view_models/field_capture_view_model.dart';

class FieldCaptureScreen extends StatelessWidget {
  final FieldCaptureViewModel viewModel;
  final VoidCallback onSavedNavigateToRecords;

  const FieldCaptureScreen({
    super.key,
    required this.viewModel,
    required this.onSavedNavigateToRecords,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: viewModel,
      builder: (context, _) {
        return SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Screen Header
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: AegisTheme.safetyOrange.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(
                      Icons.edit_note_rounded,
                      color: AegisTheme.safetyOrange,
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '1. Field Capture',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: AegisTheme.textPrimary,
                        ),
                      ),
                      Text(
                        'Voice or text input • On-device Gemma 2B INT4 extraction',
                        style: TextStyle(
                          fontSize: 11,
                          color: AegisTheme.textMuted,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 14),

              // Demo Preset Chips
              const Text(
                'QUICK TEST OBSERVATIONS (TAP TO LOAD):',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.5,
                  color: AegisTheme.textMuted,
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                height: 38,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: viewModel.presets.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (context, index) {
                    final preset = viewModel.presets[index];
                    return ActionChip(
                      backgroundColor: AegisTheme.surfaceVariant,
                      side: const BorderSide(color: AegisTheme.cardBorder),
                      label: Text(
                        preset['label']!,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AegisTheme.industrialCyan,
                        ),
                      ),
                      onPressed: () => viewModel.selectPreset(index),
                    );
                  },
                ),
              ),
              const SizedBox(height: 14),

              // Input Box with Voice Mic Button
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    children: [
                      TextField(
                        controller: viewModel.inputController,
                        maxLines: 3,
                        style: const TextStyle(fontSize: 14, color: AegisTheme.textPrimary),
                        decoration: InputDecoration(
                          hintText: 'e.g. P-201B vibrating heavily, seal looks wet, 14:30',
                          suffixIcon: IconButton(
                            icon: Icon(
                              viewModel.isRecording ? Icons.mic : Icons.mic_none,
                              color: viewModel.isRecording
                                  ? AegisTheme.alertRed
                                  : AegisTheme.safetyOrange,
                              size: 26,
                            ),
                            tooltip: 'Simulate Voice Input',
                            onPressed: viewModel.toggleRecording,
                          ),
                        ),
                      ),
                      if (viewModel.isRecording) ...[
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: AegisTheme.alertRed,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              'Voice recording active... Transcribing audio locally',
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: AegisTheme.alertRed.withValues(alpha: 0.9),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),

              // Primary Action Button (Rugged large touch target)
              ElevatedButton.icon(
                onPressed: viewModel.isProcessing
                    ? null
                    : () async {
                        final ok = await viewModel.processAndSaveObservation();
                        if (ok && context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              backgroundColor: AegisTheme.surfaceVariant,
                              content: const Row(
                                children: [
                                  Icon(Icons.check_circle, color: AegisTheme.successGreen),
                                  SizedBox(width: 10),
                                  Text(
                                    'Buffered to Local SQLite WAL (Zero Data Loss)',
                                    style: TextStyle(fontWeight: FontWeight.w600),
                                  ),
                                ],
                              ),
                              action: SnackBarAction(
                                label: 'VIEW QUEUE',
                                textColor: AegisTheme.industrialCyan,
                                onPressed: onSavedNavigateToRecords,
                              ),
                            ),
                          );
                        }
                      },
                icon: viewModel.isProcessing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.bolt, size: 20),
                label: Text(
                  viewModel.isProcessing
                      ? 'EXTRACTING WITH GEMMA 2B...'
                      : 'RECORD OBSERVATION',
                ),
              ),

              if (viewModel.errorMessage != null) ...[
                const SizedBox(height: 10),
                Text(
                  viewModel.errorMessage!,
                  style: const TextStyle(color: AegisTheme.alertRed, fontSize: 12),
                ),
              ],

              // Structured Output Showcase (Matching AEGIS Flow poster UI Showcase #1)
              if (viewModel.extractedObservation != null) ...[
                const SizedBox(height: 20),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'STRUCTURED OUTPUT (JSON)',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.8,
                        color: AegisTheme.industrialCyan,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AegisTheme.industrialCyan.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: const Text(
                        'On-Device Gemma 2B INT4 • 1.8s',
                        style: TextStyle(fontSize: 10, color: AegisTheme.industrialCyan, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),

                // Terminal Code Box
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xFF070B12),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AegisTheme.cardBorder),
                  ),
                  child: SelectableText(
                    viewModel.extractedObservation!.toStructuredJsonPreview(),
                    style: const TextStyle(
                      fontFamily: 'Courier',
                      fontSize: 13,
                      height: 1.4,
                      color: Color(0xFF68D391), // Terminal Green
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),

                // Discrepancy Card if triggered
                if (viewModel.extractedObservation!.discrepancyAlert != null) ...[
                  const SizedBox(height: 12),
                  DiscrepancyAlertCard(
                    title: 'Discrepancy Detected',
                    description: viewModel.extractedObservation!.discrepancyAlert!,
                    onReview: onSavedNavigateToRecords,
                  ),
                ],

                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: onSavedNavigateToRecords,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AegisTheme.textPrimary,
                    side: const BorderSide(color: AegisTheme.industrialCyan),
                    minimumSize: const Size.fromHeight(44),
                  ),
                  icon: const Icon(Icons.list_alt, size: 18),
                  label: const Text('VIEW ALL RECORDS IN QUEUE'),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}
